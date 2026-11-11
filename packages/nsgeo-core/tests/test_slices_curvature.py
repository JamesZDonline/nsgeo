"""Minimum curvature: the smoothest surface through the data, solved near it
(interpolation spec §5.4). The tests every method shares are in
`test_slices_interpolate.py`."""

from __future__ import annotations

import math
import threading

import numpy as np
import pytest
from nsgeo.slices import (
    CubeFrame,
    CurvaturePlan,
    SolveStopped,
    multigrid,
    plan_curvature,
    plan_fill,
)
from nsgeo.slices.curvature import _OFFSETS, CURVATURE_EPS
from nsgeo.slices.interpolate import reach_mask

from tests.real_lines import SPACING, WINDOWS, binned, needs_real_files, prepared_lines

STEP = 0.05
ROWS = (5, 15, 25, 35)


def lines(rows=ROWS, ny=40, nx=60):
    pop = np.zeros((ny, nx), bool)
    pop[list(rows), :] = True
    return pop


def values(pop, seed=0):
    return np.random.default_rng(seed).normal(size=pop.shape)


def centres(shape, cell):
    """(y, x) of every cell centre, in metres."""
    yy, xx = np.indices(shape)
    return (yy + 0.5) * cell, (xx + 0.5) * cell


def grow(mask, times):
    """`mask` dilated `times` times by its 4-neighbours."""
    out = mask.copy()
    for _ in range(times):
        wider = out.copy()
        wider[1:] |= out[:-1]
        wider[:-1] |= out[1:]
        wider[:, 1:] |= out[:, :-1]
        wider[:, :-1] |= out[:, 1:]
        out = wider
    return out


# Plan call 1's energy, one term kind a row: the cells of a term as offsets
# from its first cell, their coefficients, and the term's weight. Squared, the
# weights are 1, 2 and ε, as in the energy.
TERMS = (
    (((0, 0), (0, 1), (0, 2)), (1, -2, 1), 1.0),
    (((0, 0), (1, 0), (2, 0)), (1, -2, 1), 1.0),
    (((0, 0), (0, 1), (1, 0), (1, 1)), (1, -1, -1, 1), math.sqrt(2.0)),
    (((0, 0), (0, 1)), (-1, 1), math.sqrt(CURVATURE_EPS)),
    (((0, 0), (1, 0)), (-1, 1), math.sqrt(CURVATURE_EPS)),
)


def dense_solve(pop, v, cell, max_distance_m):
    """The reference: every energy term a row of a dense B, and min ‖B u‖ over
    the unknowns with the data held fixed, by least squares."""
    ny, nx = pop.shape
    domain = grow(reach_mask(pop, cell, max_distance_m), 2)
    rows = []
    for offsets, coefficients, weight in TERMS:
        for i in range(ny):
            for j in range(nx):
                cells = [(i + dy, j + dx) for dy, dx in offsets]
                if all(0 <= a < ny and 0 <= b < nx and domain[a, b] for a, b in cells):
                    row = np.zeros(pop.size)
                    # zip without strict=: the core supports Python 3.9.
                    for (a, b), c in zip(cells, coefficients):
                        row[a * nx + b] = weight * c
                    rows.append(row)
    big_b = np.array(rows)
    data = pop.ravel()
    unknown = (domain & ~pop).ravel()
    u = np.where(data, v.ravel(), 0.0)
    rhs = -big_b[:, data] @ u[data]
    u[unknown] = np.linalg.lstsq(big_b[:, unknown], rhs, rcond=None)[0]
    return u.reshape(pop.shape)


def test_min_curvature_reproduces_a_plane():
    pop = lines()
    y, x = centres(pop.shape, STEP)
    plane = 0.3 + 0.8 * x - 0.5 * y
    out = plan_curvature(pop, STEP, 0.25).apply(plane)
    fin = np.isfinite(out)
    assert fin.sum() > pop.sum()
    np.testing.assert_allclose(out[fin], plane[fin], rtol=0, atol=1e-4 * np.ptp(plane[pop]))


def test_a_large_offset_costs_no_precision():
    """Processed amplitudes can sit far from 0. Solved as they come, an offset
    of 1000 moved the result by 3.8% of the data range: float32 spent its
    digits on the offset. The solve is about the data mean."""
    pop = lines()
    plan = plan_curvature(pop, STEP, 0.25)
    v = values(pop)
    shifted = plan.apply(v + 1000.0).astype(np.float64) - 1000.0
    fin = np.isfinite(shifted)
    np.testing.assert_allclose(shifted[fin], plan.apply(v)[fin], rtol=0, atol=1e-4 * np.ptp(v[pop]))


@pytest.mark.parametrize("coarsest", [500, 2])
@pytest.mark.parametrize("max_distance", [0.15, 0.5])
def test_min_curvature_matches_a_dense_solve(max_distance, coarsest, monkeypatch):
    """Spec §9's reference case, over part of the frame and over all of it,
    on one level and, with a tiny coarsest level, on a hierarchy (#111)."""
    monkeypatch.setattr(multigrid, "COARSEST_UNKNOWNS", coarsest)
    rng = np.random.default_rng(5)
    pop = rng.random((12, 14)) < 0.2
    v = rng.normal(size=pop.shape)
    reach = reach_mask(pop, 0.1, max_distance)
    assert reach.all() == (max_distance == 0.5)
    want = dense_solve(pop, v, 0.1, max_distance)
    plan = plan_curvature(pop, 0.1, max_distance)
    assert (len(plan.hierarchy.levels) > 1) == (coarsest == 2)
    got = plan.apply(v)
    assert np.array_equal(np.isfinite(got), reach)
    np.testing.assert_allclose(got[reach], want[reach], rtol=0, atol=1e-4 * np.ptp(v[pop]))


def test_min_curvature_matches_a_dense_solve_across_levels():
    """A frame big enough for the default coarsest level to be a coarse grid:
    sparse scatter plus four full rows, against the dense solve."""
    rng = np.random.default_rng(7)
    pop = rng.random((30, 34)) < 0.08
    pop[[4, 12, 20, 27]] = True
    v = rng.normal(size=pop.shape)
    reach = reach_mask(pop, 0.1, 0.3)
    want = dense_solve(pop, v, 0.1, 0.3)
    plan = plan_curvature(pop, 0.1, 0.3)
    assert len(plan.hierarchy.levels) >= 2
    got = plan.apply(v)
    np.testing.assert_allclose(got[reach], want[reach], rtol=0, atol=1e-4 * np.ptp(v[pop]))


@pytest.mark.parametrize("rows", [ROWS, (5, 15, 27, 35), (5, 15, 35)])
@pytest.mark.parametrize("max_distance", [0.25, 0.30])
def test_min_curvature_blanks_exactly_where_idw_does(rows, max_distance):
    pop = lines(rows)
    v = values(pop)
    idw = plan_fill(pop, STEP, "idw", max_distance, 1.0).apply(v)
    out = plan_curvature(pop, STEP, max_distance).apply(v)
    assert np.array_equal(np.isnan(out), np.isnan(idw))


def test_the_solve_area_is_the_reach_grown_by_two_cells():
    """Plan call 2: the solve stays near the data, so rows far from both
    lines are no part of it."""
    pop = lines((5, 15))
    plan = plan_curvature(pop, STEP, 0.25)
    assert np.array_equal(plan.domain, grow(reach_mask(pop, STEP, 0.25), 2))
    assert not plan.domain[23:].any()
    unknown = plan.domain & ~pop
    assert (plan.coefficients[:, ~unknown] == 0).all()
    assert (plan.coefficients[:, unknown] != 0).any(axis=0).all()


def test_partial_coverage_solves_in_few_iterations():
    """Lines 0.5 m apart over the lower 40% of a 50 m frame at 0.2 m, one
    skipped. Solved over the whole frame this took 14,593 iterations in the
    spike, crawling through the empty ground (interpolation spec §5.4). Inside
    the solve area Jacobi took 95 iterations here; the multigrid
    preconditioner took 4 in the spike (#111)."""
    cell, n = 0.2, 250
    pop = np.zeros((n, n), bool)
    rows = (np.arange(0.25, 0.4 * n * cell, 0.5) // cell).astype(int)
    pop[np.delete(rows, rows.size // 2)] = True
    y, x = centres(pop.shape, cell)
    v = np.sin(x / 1.7) * np.cos(y / 2.3) + 0.05 * x
    plan = plan_curvature(pop, cell, 0.375)
    assert not plan.domain[n // 2 :].any()
    assert plan.solve(v)[1] <= 20


def crossing_lines(cell):
    """10 m x 10 m: lines along X, wandering, 0.5 m apart, and three full
    columns (the spike's crossing-lines frame)."""
    n = int(round(10 / cell))
    pop = np.zeros((n, n), bool)
    x = (np.arange(n) + 0.5) * cell
    for i, y0 in enumerate(np.arange(0.25, 10, 0.5)):
        y = y0 + 0.06 * np.sin(x / 3.0 + i)
        pop[np.clip((y / cell).astype(int), 0, n - 1), np.arange(n)] = True
    for x0 in (2.1, 5.3, 8.6):
        pop[:, int(x0 / cell)] = True
    return pop


def test_iterations_barely_grow_as_cells_shrink():
    """The point of #111: with Jacobi the count grew about 4x per halving of
    the cell (39, 152, 549 here); with the hierarchy the spike took 6, 10, 14."""
    its = {}
    for cell in (0.2, 0.1, 0.05):
        pop = crossing_lines(cell)
        y, x = centres(pop.shape, cell)
        v = np.sin(x / 1.7) * np.cos(y / 2.3) + 0.3 * np.sin(3.1 * x + 1.3 * y)
        its[cell] = plan_curvature(pop, cell, 0.375).solve(v)[1]
    assert all(n <= 30 for n in its.values()), its
    assert its[0.05] <= 3 * its[0.2], its


def test_the_hierarchy_shares_the_plans_operator():
    pop = lines()
    plan = plan_curvature(pop, STEP, 0.25)
    assert plan.hierarchy.levels[0].coefficients is plan.coefficients
    assert np.array_equal(plan.hierarchy.levels[0].active, plan.domain & ~pop)


def test_the_hierarchy_costs_less_memory_than_the_operator():
    pop = np.zeros((400, 400), bool)
    pop[::10] = True
    plan = plan_curvature(pop, STEP, 0.375)
    assert plan.hierarchy.nbytes < plan.coefficients.nbytes  # the spike measured 0.78x


def test_two_threads_solve_one_plan_as_one():
    """Plans are shared between threads: `precondition` and `solve` keep their
    scratch to themselves."""
    pop = lines((10, 30, 50, 70), ny=80, nx=120)
    plan = plan_curvature(pop, STEP, 0.25)
    fields = [values(pop, seed) for seed in range(4)]
    want = [plan.solve(v) for v in fields]
    got = [None] * 4

    def work(k):
        got[k] = plan.solve(fields[k])

    threads = [threading.Thread(target=work, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for (out, its), (want_out, want_its) in zip(got, want):
        assert its == want_its
        assert np.array_equal(out, want_out, equal_nan=True)


def test_the_start_weights_each_direction_by_its_span():
    """Plan call 3 as amended (controller, 2026-11-05). A wandering line
    crosses a row only now and then, so a row's bracketing data can be metres
    apart. An equal average of the column and row estimates needed about 40%
    more iterations on such lines. Columns alone suit lines along X only, and a
    grid may hold lines both ways. So a bracketed estimate counts by 1 / its
    span in cells; a one-sided one counts only where neither direction is
    bracketed."""
    from nsgeo.slices.curvature import _start

    d = np.random.default_rng(3).normal(size=(9, 21)).astype(np.float32)
    pop = np.zeros(d.shape, bool)
    pop[[2, 6]] = True
    pop[:, [0, 20]] = True
    start = _start(d, pop)
    along_y = d[2, 10] + 0.5 * (d[6, 10] - d[2, 10])  # span 4, halfway
    along_x = d[4, 0] + 0.5 * (d[4, 20] - d[4, 0])  # span 20, halfway
    want = (along_y / 4 + along_x / 20) / (1 / 4 + 1 / 20)
    assert start[4, 10] == pytest.approx(want, abs=1e-6)
    # Above row 2 a column has data on one side only; the row is bracketed.
    assert start[0, 10] == pytest.approx(d[0, 0] + 0.5 * (d[0, 20] - d[0, 0]), abs=1e-6)
    corner = np.zeros(d.shape, bool)
    corner[2] = True
    corner[:, 0] = True
    # Below row 2 and right of column 0, both sides are one-sided: averaged.
    assert _start(d, corner)[5, 8] == pytest.approx((d[2, 8] + d[5, 0]) / 2, abs=1e-6)


def test_one_line_continues_flat_across_it():
    """Data on one line leave a tilt across it that costs no curvature; the
    slope term settles it flat (plan call 1). A profile that is straight
    along the line carries on unchanged across it.

    A curved one may not: the exact solution bends away from the line, as a
    thin plate should (sin x by up to 0.011 in `dense_solve`). So it is held
    to the same on both sides, which is what no tilt means, and not to flat
    within 1e-4, as the plan first asked: a correct solve would fail that."""
    pop = np.zeros((21, 30), bool)
    pop[10] = True
    plan = plan_curvature(pop, STEP, 0.25)
    _, x = centres(pop.shape, STEP)
    out = plan.apply(0.3 + 0.8 * x)
    fin = np.isfinite(out)
    assert fin[5:16].all()
    np.testing.assert_allclose(
        out[fin], np.broadcast_to(out[10], out.shape)[fin], rtol=0, atol=1e-4
    )
    out = plan.apply(np.sin(x))
    np.testing.assert_allclose(out[5:10], out[15:10:-1], rtol=0, atol=1e-4)
    one = np.zeros((21, 21), bool)
    one[10, 10] = True
    v = np.full(one.shape, np.nan)
    v[10, 10] = 0.7
    out = plan_curvature(one, STEP, 0.25).apply(v)
    disc = reach_mask(one, STEP, 0.25)
    assert np.isnan(out[~disc]).all()
    np.testing.assert_allclose(out[disc], 0.7, rtol=0, atol=1e-4)


def test_a_nan_data_value_does_not_poison_the_cells_around_it():
    """Plan call 10: a non-finite datum shows NaN, and the slice is solved
    around it."""
    pop = lines()
    plan = plan_curvature(pop, STEP, 0.25)
    v = values(pop)
    v[15, 30] = np.nan
    out = plan.apply(v)
    assert np.isnan(out[15, 30])
    near_finite = reach_mask(pop & np.isfinite(v), STEP, 0.25)
    near_finite[15, 30] = False
    assert np.isfinite(out[near_finite]).all()
    flat = np.full(pop.shape, 3.5)
    flat[15, 30] = np.nan
    out = plan.apply(flat)
    fin = np.isfinite(out)
    assert fin.sum() > pop.sum()
    np.testing.assert_allclose(out[fin], 3.5, rtol=0, atol=1e-5)


def test_max_distance_zero_returns_the_data_alone():
    pop = lines()
    v = values(pop)
    out, iterations = plan_curvature(pop, STEP, 0.0).solve(v)
    assert iterations == 0
    assert np.array_equal(out[pop], v.astype(np.float32)[pop])
    assert np.isnan(out[~pop]).all()


def test_a_solve_stops_when_asked():
    """Task 2 runs solves on a worker thread, so a stop must land between
    iterations and the solve must touch neither the plan nor the values."""
    pop = lines()
    plan = plan_curvature(pop, STEP, 0.25)
    v = values(pop)
    kept_values, kept_coefficients = v.copy(), plan.coefficients.copy()
    want, iterations = plan.solve(v)
    assert iterations > 5
    calls = []

    def stop_on_the_fourth_call():
        calls.append(None)
        return len(calls) == 4

    with pytest.raises(SolveStopped):
        plan.solve(v, should_stop=stop_on_the_fourth_call)
    assert len(calls) == 4
    got, ran = plan.solve(v, should_stop=lambda: False)
    assert ran == iterations
    assert np.array_equal(got, want, equal_nan=True)
    assert np.array_equal(v, kept_values)
    assert np.array_equal(plan.coefficients, kept_coefficients)


def test_a_plan_is_read_only():
    """A worker thread solves on a plan while the GUI thread reads it (plan
    call 6), which is safe only while nothing writes to it: its arrays refuse
    writes, so the contract is enforced, not just stated. The caller's mask is
    copied, never frozen, and a non-finite datum is solved on a plan of its own."""
    pop = lines()
    plan = plan_curvature(pop, STEP, 0.25)
    with pytest.raises(ValueError):
        plan.coefficients[0, 0, 0] = 1.0
    hierarchy = plan.hierarchy
    arrays = [hierarchy.coarse_cells, hierarchy.coarse_inverse]
    for level in hierarchy.levels:
        arrays += [level.coefficients, level.active, level.scale]
    for array in (plan.populated, plan.reach, plan.domain, plan.coefficients, *arrays):
        assert not array.flags.writeable
    pop[0, 0] = True  # the caller's own array stays theirs
    assert not plan.populated[0]
    v = values(pop)
    v[15, 30] = np.nan
    assert np.isnan(plan.apply(v)[15, 30])


def test_nbytes_counts_the_arrays():
    plan = plan_fill(lines(), STEP, "min_curvature", 0.25, 1.0)
    assert isinstance(plan, CurvaturePlan)
    assert plan.coefficients.shape == (13, 40, 60)
    assert plan.coefficients.dtype == np.float32
    assert plan.nbytes == (
        plan.populated.nbytes
        + plan.reach.nbytes
        + plan.domain.nbytes
        + plan.coefficients.nbytes
        + plan.hierarchy.nbytes
    )


def test_plan_curvature_refuses_bad_input():
    pop = lines()
    for args in (
        (pop.ravel(), STEP, 0.25),
        (pop, 0.0, 0.25),
        (pop, -STEP, 0.25),
        (pop, STEP, -0.1),
    ):
        with pytest.raises(ValueError):
            plan_curvature(*args)
    with pytest.raises(ValueError):
        plan_curvature(pop, STEP, 0.25).apply(np.zeros((3, 3)))


def tight_solve(plan, values):
    """float64 Jacobi-preconditioned CG on the plan's operator to 1e-10, the
    reference for fine cells: the slice with the data in place, NaN off the
    reach. About 1,100 iterations on the real lines at 0.05 m."""
    shape = plan.shape
    pop = plan.populated.reshape(shape)
    unknown = plan.domain & ~pop
    a = plan.coefficients.astype(np.float64)

    def times(x):
        pad = np.zeros((shape[0] + 4, shape[1] + 4))
        pad[2:-2, 2:-2] = x
        return sum(
            a[k] * pad[2 + dy : 2 + dy + shape[0], 2 + dx : 2 + dx + shape[1]]
            for k, (dy, dx) in enumerate(_OFFSETS)
        )

    v = np.asarray(values, np.float64)
    b = -times(np.where(pop, v, 0.0))
    x = np.zeros(shape)
    diag = a[_OFFSETS.index((0, 0))]
    inv = np.where(unknown, 1.0 / np.where(unknown, diag, 1.0), 0.0)
    r = b.copy()
    z = r * inv
    p = z.copy()
    rz = (r * z).sum()
    b_norm = math.sqrt((b * b).sum())
    its = 0
    while math.sqrt((r * r).sum()) > 1e-10 * b_norm and its < 20000:
        q = times(p * unknown)
        alpha = rz / (p * q).sum()
        x += alpha * p
        r -= alpha * q
        z = r * inv
        rz_next = (r * z).sum()
        p = z + rz_next / rz * p
        rz = rz_next
        its += 1
    out = np.where(pop, v, x)
    out[~plan.reach.reshape(shape)] = np.nan
    return out


@needs_real_files
def test_real_lines_at_a_fine_cell_match_a_tight_solve():
    """The ten real lines at 0.05 m, where Jacobi took 540 iterations: the
    hierarchy takes about 16 (spike), and agrees with a float64 solve to
    milestone B's 0.05 m figure, 4e-4 of the data range (spike: 3e-5)."""
    frame = CubeFrame((0.0, 0.0), 0.0, 0.05, 400, 100, "EPSG:32633")
    lns = prepared_lines(range(10), lambda local: local)
    for k0, k1 in (WINDOWS[0], WINDOWS[2]):
        v, cov = binned(lns, frame, k0, k1)
        pop = cov > 0
        plan = plan_curvature(pop, 0.05, 0.75 * SPACING)
        out, iterations = plan.solve(v)
        assert iterations <= 30
        want = tight_solve(plan, v)
        gap = plan.reach.reshape(plan.shape) & ~pop
        err = np.abs(out - want)[gap].max() / np.ptp(np.asarray(v)[pop])
        assert err <= 4e-4
