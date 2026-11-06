"""Interpolation weights: which empty cells get filled, and from what."""

from __future__ import annotations

import tracemalloc

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.slices import CubeFrame, FillWeights, interpolate, plan_fill
from nsgeo.slices.interpolate import (
    DISTANCE_TOL_M,
    METHODS,
    NEIGHBOURS_PER_QUADRANT,
    reach_mask,
)

from tests.real_lines import (
    CELL,
    SPACING,
    WINDOWS,
    binned,
    needs_real_files,
    prepared_lines,
)

BOTH = pytest.mark.parametrize("method", ["idw", "kriging"])
ALL = pytest.mark.parametrize("method", ["idw", "kriging", "min_curvature"])
STEP = 0.05
ROWS = (5, 15, 25, 35)


def lines(rows=ROWS, ny=40, nx=60):
    pop = np.zeros((ny, nx), bool)
    pop[list(rows), :] = True
    return pop


def plan(pop, method, max_d=0.25, search=1.0, cell=STEP):
    return plan_fill(pop, cell, method, max_d, search)


def values(pop, seed=0):
    return np.random.default_rng(seed).normal(size=pop.shape)


def same(a, b, **kw):
    assert np.array_equal(np.isnan(a), np.isnan(b))
    np.testing.assert_allclose(a[~np.isnan(a)], b[~np.isnan(b)], **kw)


def test_methods_are_in_order():
    assert METHODS == ("none", "idw", "kriging", "min_curvature")


def test_none_keeps_data_cells_and_blanks_the_rest():
    pop = lines()
    fw = plan(pop, "none")
    v = values(pop)
    out = fw.apply(v)
    assert fw.targets.size == 0
    assert np.array_equal(out[pop], v.astype(np.float32)[pop])
    assert np.isnan(out[~pop]).all()


@ALL
def test_data_cells_come_back_exactly(method):
    pop = lines()
    v = values(pop)
    out = plan(pop, method).apply(v)
    assert np.array_equal(out[pop], v.astype(np.float32)[pop])


@ALL
def test_a_constant_field_is_reproduced(method):
    pop = lines()
    out = plan(pop, method).apply(np.full(pop.shape, 3.5))
    fin = out[np.isfinite(out)]
    assert fin.size > pop.sum()
    np.testing.assert_allclose(fin, 3.5, rtol=1e-6)


@ALL
def test_interpolation_is_affine_equivariant(method):
    pop = lines()
    fw = plan(pop, method)
    v = values(pop)
    if method == "min_curvature":
        # An iterative solve, exact only to its tolerance (interpolation spec §5.4).
        tol = {"rtol": 0, "atol": 1e-4 * 2.5 * np.ptp(v[pop])}
    else:
        tol = {"rtol": 1e-5, "atol": 1e-5}
    same(fw.apply(-2.5 * v + 7), -2.5 * fw.apply(v) + 7, **tol)


@ALL
def test_cells_beyond_max_distance_are_blank_and_within_it_are_finite(method):
    pop = np.zeros((21, 21), bool)
    pop[10, 10] = True
    out = plan(pop, method, 0.35, 0.7, 0.1).apply(np.ones(pop.shape))
    dy, dx = np.indices(pop.shape) - 10
    expect = np.hypot(dy, dx) * 0.1 <= 0.35 + DISTANCE_TOL_M
    assert np.array_equal(np.isfinite(out), expect)


@ALL
def test_the_limit_is_inclusive_so_the_midpoint_between_lines_fills(method):
    odd = np.zeros((5, 3), bool)
    odd[[0, 4], :] = True
    out = plan(odd, method, 0.25, 1.0, 0.125).apply(values(odd))
    assert np.isfinite(out[2]).all()
    even = np.zeros((6, 3), bool)
    even[[0, 5], :] = True
    out = plan(even, method, 0.25, 1.0, 0.1).apply(values(even))
    assert np.isfinite(out[1:5]).all()


@ALL
def test_no_holes_between_lines_at_nominal_spacing(method):
    out = plan(lines(), method).apply(values(lines()))
    assert np.isfinite(out[5:36]).all()


@ALL
def test_a_line_that_wanders_leaves_a_stripe_that_a_larger_max_distance_closes(method):
    pop = lines((5, 15, 27, 35))
    v = values(pop)
    assert np.isnan(plan(pop, method, 0.25).apply(v)[21]).all()
    assert np.isfinite(plan(pop, method, 0.30, 1.0).apply(v)[5:36]).all()


@ALL
def test_a_skipped_line_leaves_a_blank_stripe(method):
    pop = lines((5, 15, 35))
    v = values(pop)
    assert np.isnan(plan(pop, method, 0.25).apply(v)[25]).all()
    assert np.isfinite(plan(pop, method, 0.5, 1.0).apply(v)[25]).all()


def binned_lines(spacing, cell, size=10.0, skip=()):
    """The populated mask of straight lines along X, `spacing` apart from
    `spacing / 2`, binned through `CubeFrame.for_grid` and `cell_index` as the
    cube bins traces. Each datum lands on its cell's centre, up to half a cell
    from its line, so data rows are floor or ceil(spacing / cell) cells apart."""
    grid = Grid("A", (0.0, 0.0), 0.0, size, size, "EPSG:32633", spacing)
    frame = CubeFrame.for_grid(grid, cell)
    pop = np.zeros(frame.n_cells, bool)
    xs = np.arange(0.01, size, 0.03)
    for i, y in enumerate(np.arange(spacing / 2, size - 1e-9, spacing)):
        if i not in skip:
            ids = frame.cell_index(grid.to_world(np.column_stack([xs, np.full(xs.size, y)])))
            pop[ids[ids >= 0]] = True
    return pop.reshape(frame.ny, frame.nx)


def between_lines(pop, out):
    rows = np.flatnonzero(pop.any(axis=1))
    return out[rows[0] : rows[-1] + 1]


@ALL
@pytest.mark.parametrize(("spacing", "cell"), [(0.75, 0.2), (0.7, 0.2), (0.5, 0.15), (1.5, 0.2)])
def test_binned_lines_fill_at_three_quarters_of_a_spacing(method, spacing, cell):
    """The plugin's default max distance. When ceil(spacing / cell) is even
    the middle row is ceil(spacing / cell) * cell / 2 from both lines, at most
    (spacing + cell) / 2, which is within 0.75 x spacing for any cell up to
    half the spacing."""
    pop = binned_lines(spacing, cell)
    assert len(set(np.diff(np.flatnonzero(pop.any(axis=1))).tolist())) == 2  # floor and ceil
    out = plan_fill(pop, cell, method, 0.75 * spacing, 2 * spacing).apply(values(pop))
    assert np.isfinite(between_lines(pop, out)).all()


@ALL
def test_half_a_spacing_stripes_binned_lines(method):
    """Why the default is not 0.5 x spacing: with 0.75 m lines at a 0.2 m cell,
    every gap of 4 cells leaves its middle row 0.4 m from data, past 0.375 m."""
    pop = binned_lines(0.75, 0.2)
    out = plan_fill(pop, 0.2, method, 0.5 * 0.75, 2 * 0.75).apply(values(pop))
    assert np.isnan(between_lines(pop, out)).all(axis=1).any()


@ALL
def test_a_skipped_binned_line_leaves_a_blank_stripe_at_three_quarters_of_a_spacing(method):
    """The user's 0.5 m lines at a 0.2 m cell: the skipped line's gap is 5
    cells, so its middle rows are 0.4 m from data, past 0.375 m."""
    pop = binned_lines(0.5, 0.2, skip=(10,))
    out = plan_fill(pop, 0.2, method, 0.75 * 0.5, 2 * 0.5).apply(values(pop))
    blank = np.flatnonzero(np.isnan(between_lines(pop, out)).all(axis=1))
    assert blank.size == 2


@BOTH
def test_every_filled_cell_between_two_lines_draws_on_both(method):
    fw = plan(lines(), method)
    nx = 60
    rows = fw.targets // nx
    sel = (rows >= 6) & (rows <= 14)
    assert sel.any()
    for src in fw.sources[sel]:
        got = set((src[src >= 0] // nx).tolist())
        assert {5, 15} <= got


@ALL
def test_no_step_from_neighbourhood_switching(method):
    pop = lines(nx=200)
    yy, xx = np.indices(pop.shape)
    f = np.sin((xx + 0.5) * STEP / 1.5) + 0.4 * (yy + 0.5) * STEP
    out = plan(pop, method).apply(f)
    bound = 2.5 * np.hypot(1 / 1.5, 0.4) * STEP + 1e-6
    for axis in (0, 1):
        a, b = out, np.roll(out, -1, axis)
        d = np.abs(b - a)
        d = d[:-1] if axis == 0 else d[:, :-1]
        d = d[np.isfinite(d)]
        assert d.size
        assert d.max() <= bound


@ALL
def test_one_line_fills_both_sides_out_to_max_distance_and_no_further(method):
    pop = np.zeros((21, 30), bool)
    pop[10] = True
    out = plan(pop, method).apply(values(pop))
    assert np.isfinite(out[5:16]).all()
    assert np.isnan(out[:5]).all() and np.isnan(out[16:]).all()
    one = np.zeros((21, 21), bool)
    one[10, 10] = True
    out = plan(one, method).apply(np.ones(one.shape))
    dy, dx = np.indices(one.shape) - 10
    assert np.array_equal(np.isfinite(out), np.hypot(dy, dx) * STEP <= 0.25 + DISTANCE_TOL_M)


@ALL
def test_a_cross_hatched_grid_fills_without_holes(method):
    pop = lines((5, 15, 25, 35), ny=60, nx=60)
    pop[:, 5:56:10] = True
    out = plan(pop, method).apply(values(pop))
    assert np.isfinite(out[5:56, 5:56]).all()


@BOTH
@pytest.mark.parametrize("rows", [ROWS, (5, 15, 27, 35), (5, 15, 35)])
def test_the_targets_are_the_reach_less_the_data(method, rows):
    """One reach rule for every method, so minimum curvature blanks exactly
    where IDW and kriging do."""
    pop = lines(rows)
    fw = plan(pop, method)
    assert np.array_equal(fw.targets, np.flatnonzero(reach_mask(pop, STEP, 0.25) & ~pop))


def test_idw_halfway_between_two_cells_is_their_mean():
    pop = np.zeros((1, 5), bool)
    pop[0, [0, 4]] = True
    v = np.array([[2.0, 0, 0, 0, 6.0]])
    out = plan_fill(pop, 0.1, "idw", 0.2, 0.5).apply(v)
    assert out[0, 2] == pytest.approx(4.0)


def test_kriging_weights_sum_to_one():
    fw = plan(lines(), "kriging")
    assert fw.targets.size
    np.testing.assert_allclose(fw.weights.sum(axis=1), 1.0, atol=1e-5)


def test_kriging_matches_a_direct_solve_for_one_cell():
    rng = np.random.default_rng(3)
    pop = rng.random((30, 30)) < 0.15
    fw = plan_fill(pop, 0.1, "kriging", 0.3, 0.6)
    row = fw.targets.size // 2
    t = fw.targets[row]
    slots = np.flatnonzero(fw.sources[row] >= 0)
    src = fw.sources[row, slots]
    p = np.column_stack([src // 30 - t // 30, src % 30 - t % 30]) * 0.1
    n = len(src)
    a = np.zeros((n + 1, n + 1))
    a[:n, :n] = np.hypot(*(p[:, None, :] - p[None, :, :]).transpose(2, 0, 1))
    a[:n, n] = a[n, :n] = 1.0
    rhs = np.append(np.hypot(p[:, 0], p[:, 1]), 1.0)
    w = np.linalg.solve(a, rhs)[:n]
    np.testing.assert_allclose(fw.weights[row, slots], w, atol=1e-5)
    assert (fw.weights[row, fw.sources[row] < 0] == 0).all()


@BOTH
def test_a_nan_data_value_does_not_poison_targets_with_other_sources(method):
    pop = lines()
    fw = plan(pop, method)
    v = values(pop)
    bad = 15 * 60 + 30
    v[15, 30] = np.nan
    out = fw.apply(v)
    assert np.isnan(out[15, 30])
    hit = np.flatnonzero((fw.sources == bad).any(axis=1))
    assert hit.size
    assert np.isfinite(out.ravel()[fw.targets[hit]]).all()


@BOTH
def test_renormalising_over_finite_sources_keeps_a_constant_field(method):
    pop = lines()
    fw = plan(pop, method)
    v = np.full(pop.shape, 3.5)
    v[15, 30] = np.nan
    out = fw.apply(v)
    hit = np.flatnonzero((fw.sources == 15 * 60 + 30).any(axis=1))
    assert hit.size
    np.testing.assert_allclose(out.ravel()[fw.targets[hit]], 3.5, rtol=1e-5)


@ALL
def test_all_blank_input_gives_all_blank_output(method):
    fw = plan(lines(), method)
    assert np.isnan(fw.apply(np.full((40, 60), np.nan))).all()


@ALL
def test_apply_at_matches_apply(method):
    pop = lines((5, 15, 35))  # rows around 25 are neither data nor targets
    fw = plan(pop, method)
    v = values(pop)
    ids = np.random.default_rng(1).integers(0, pop.size, 200)
    is_target = np.isin(ids, np.flatnonzero(reach_mask(pop, STEP, 0.25) & ~pop))
    assert pop.ravel()[ids].any() and is_target.any()
    assert (~pop.ravel()[ids] & ~is_target).any()
    same(fw.apply_at(v, ids), fw.apply(v).ravel()[ids], rtol=0, atol=0)
    assert fw.apply_at(v, ids).dtype == np.float32


def test_nbytes_counts_the_tables():
    fw = plan(lines(), "kriging")
    assert (
        fw.nbytes == fw.populated.nbytes + fw.targets.nbytes + fw.sources.nbytes + fw.weights.nbytes
    )
    assert isinstance(fw, FillWeights)
    assert fw.sources.shape[1] == 4 * NEIGHBOURS_PER_QUADRANT


def traced_peak(fn, *args):
    """`fn(*args)` and the most memory it allocated at once, in bytes."""
    started = not tracemalloc.is_tracing()
    if started:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        before, _ = tracemalloc.get_traced_memory()
        out = fn(*args)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if started:
            tracemalloc.stop()
    return out, peak - before


def dense_lines(cell=0.05, size=10.0):
    """0.5 m lines at a fine cell: nine in ten cells are targets, the worst case
    for memory."""
    ny = int(np.ceil(size / cell))
    pop = np.zeros((ny, ny), bool)
    for y in np.arange(0.25, size - 1e-9, 0.5):
        pop[int(y // cell)] = True
    return pop


@BOTH
def test_the_plan_does_not_depend_on_the_chunk_size(method, monkeypatch):
    """Planning runs its per-target stages in chunks to bound memory; no
    weight may move. A random mask gives kriging many distinct patterns, so
    the chunks dedupe and solve different sets."""
    pop = np.random.default_rng(5).random((60, 70)) < 0.12
    want = plan_fill(pop, 0.1, method, 0.3, 0.6)
    monkeypatch.setattr(interpolate, "_PLAN_CHUNK", 7)
    monkeypatch.setattr(interpolate, "_SOLVE_CHUNK", 5)
    got = plan_fill(pop, 0.1, method, 0.3, 0.6)
    assert np.array_equal(got.targets, want.targets)
    assert np.array_equal(got.sources, want.sources)
    assert np.array_equal(got.weights, want.weights)


@BOTH
def test_planning_needs_little_more_memory_than_the_weights_it_returns(method, monkeypatch):
    """Spec §7: the weights' memory is estimated before they are built, so the
    build must not need several times what it keeps. Measured before the
    chunking: 5.9-6.1 x `nbytes` on this grid. Small chunks here, so their
    fixed working set (a few megabytes at the shipped sizes) does not swamp a
    grid this size."""
    monkeypatch.setattr(interpolate, "_PLAN_CHUNK", 1024, raising=False)
    monkeypatch.setattr(interpolate, "_SOLVE_CHUNK", 256)
    fw, peak = traced_peak(plan_fill, dense_lines(), 0.05, method, 0.375, 1.0)
    assert fw.targets.size > 0.8 * fw.populated.size
    assert peak <= 1.5 * fw.nbytes


def test_plan_fill_refuses_bad_input():
    pop = lines()
    for args in (
        (pop, 0.05, "magic", 0.25, 1.0),
        (pop, 0.05, "idw", -0.1, 1.0),
        (pop, 0.05, "idw", 0.25, 0.1),
        (pop.ravel(), 0.05, "idw", 0.25, 1.0),
        (pop, 0.0, "idw", 0.25, 1.0),
        (pop, 0.05, "min_curvature", -0.1, 1.0),
    ):
        with pytest.raises(ValueError):
            plan_fill(*args)
    with pytest.raises(ValueError):
        plan(pop, "idw").apply(np.zeros((3, 3)))


@needs_real_files
@ALL
def test_real_lines_keep_their_data_and_fill_every_gap(method):
    frame = CubeFrame((0.0, 0.0), 0.0, CELL, 100, 25, "EPSG:32633")
    lns = prepared_lines(range(10), lambda local: local)
    for k0, k1 in WINDOWS:
        v, cov = binned(lns, frame, k0, k1)
        pop = cov > 0
        out = plan_fill(pop, CELL, method, 0.5 * SPACING, 2 * SPACING).apply(v)
        assert np.array_equal(out[pop], np.asarray(v, np.float32)[pop])
        rows = np.flatnonzero(pop.any(axis=1))
        assert np.isfinite(out[rows[0] : rows[-1] + 1]).all()
