"""Minimum curvature: the smoothest surface through the data, solved near it
(interpolation spec §5.4). The tests every method shares are in
`test_slices_interpolate.py`."""

from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.slices import CurvaturePlan, SolveStopped, plan_curvature, plan_fill
from nsgeo.slices.curvature import CURVATURE_EPS
from nsgeo.slices.interpolate import reach_mask

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


@pytest.mark.parametrize("max_distance", [0.15, 0.5])
def test_min_curvature_matches_a_dense_solve(max_distance):
    """Spec §9's reference case, over part of the frame and over all of it."""
    rng = np.random.default_rng(5)
    pop = rng.random((12, 14)) < 0.2
    v = rng.normal(size=pop.shape)
    reach = reach_mask(pop, 0.1, max_distance)
    assert reach.all() == (max_distance == 0.5)
    want = dense_solve(pop, v, 0.1, max_distance)
    got = plan_curvature(pop, 0.1, max_distance).apply(v)
    assert np.array_equal(np.isfinite(got), reach)
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
    spike, crawling through the empty ground (interpolation spec §5.4)."""
    cell, n = 0.2, 250
    pop = np.zeros((n, n), bool)
    rows = (np.arange(0.25, 0.4 * n * cell, 0.5) // cell).astype(int)
    pop[np.delete(rows, rows.size // 2)] = True
    y, x = centres(pop.shape, cell)
    v = np.sin(x / 1.7) * np.cos(y / 2.3) + 0.05 * x
    plan = plan_curvature(pop, cell, 0.375)
    assert not plan.domain[n // 2 :].any()
    assert plan.solve(v)[1] <= 400


def test_one_line_continues_flat_across_it():
    """Data on one line leave a tilt across it that costs no curvature; the
    slope term settles it flat (plan call 1). A profile that is straight
    along the line carries on unchanged across it. A curved one bends away
    from the line, as the thin plate should (sin x by up to 0.011 in
    `dense_solve`), but the same on both sides."""
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


def test_nbytes_counts_the_arrays():
    plan = plan_fill(lines(), STEP, "min_curvature", 0.25, 1.0)
    assert isinstance(plan, CurvaturePlan)
    assert plan.coefficients.shape == (13, 40, 60)
    assert plan.coefficients.dtype == np.float32
    assert plan.nbytes == (
        plan.populated.nbytes + plan.reach.nbytes + plan.domain.nbytes + plan.coefficients.nbytes
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
