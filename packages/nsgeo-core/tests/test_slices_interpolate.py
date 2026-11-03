"""Interpolation weights: which empty cells get filled, and from what."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices import CubeFrame, FillWeights, plan_fill
from nsgeo.slices.interpolate import DISTANCE_TOL_M, METHODS, NEIGHBOURS_PER_QUADRANT

from tests.real_lines import (
    CELL,
    SPACING,
    WINDOWS,
    binned,
    needs_real_files,
    prepared_lines,
)

BOTH = pytest.mark.parametrize("method", ["idw", "kriging"])
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
    assert METHODS == ("none", "idw", "kriging")


def test_none_keeps_data_cells_and_blanks_the_rest():
    pop = lines()
    fw = plan(pop, "none")
    v = values(pop)
    out = fw.apply(v)
    assert fw.targets.size == 0
    assert np.array_equal(out[pop], v.astype(np.float32)[pop])
    assert np.isnan(out[~pop]).all()


@BOTH
def test_data_cells_come_back_exactly(method):
    pop = lines()
    v = values(pop)
    out = plan(pop, method).apply(v)
    assert np.array_equal(out[pop], v.astype(np.float32)[pop])


@BOTH
def test_a_constant_field_is_reproduced(method):
    pop = lines()
    out = plan(pop, method).apply(np.full(pop.shape, 3.5))
    fin = out[np.isfinite(out)]
    assert fin.size > pop.sum()
    np.testing.assert_allclose(fin, 3.5, rtol=1e-6)


@BOTH
def test_interpolation_is_affine_equivariant(method):
    pop = lines()
    fw = plan(pop, method)
    v = values(pop)
    same(fw.apply(-2.5 * v + 7), -2.5 * fw.apply(v) + 7, rtol=1e-5, atol=1e-5)


@BOTH
def test_cells_beyond_max_distance_are_blank_and_within_it_are_finite(method):
    pop = np.zeros((21, 21), bool)
    pop[10, 10] = True
    out = plan(pop, method, 0.35, 0.7, 0.1).apply(np.ones(pop.shape))
    dy, dx = np.indices(pop.shape) - 10
    expect = np.hypot(dy, dx) * 0.1 <= 0.35 + DISTANCE_TOL_M
    assert np.array_equal(np.isfinite(out), expect)


@BOTH
def test_the_limit_is_inclusive_so_the_midpoint_between_lines_fills(method):
    odd = np.zeros((5, 3), bool)
    odd[[0, 4], :] = True
    out = plan(odd, method, 0.25, 1.0, 0.125).apply(values(odd))
    assert np.isfinite(out[2]).all()
    even = np.zeros((6, 3), bool)
    even[[0, 5], :] = True
    out = plan(even, method, 0.25, 1.0, 0.1).apply(values(even))
    assert np.isfinite(out[1:5]).all()


@BOTH
def test_no_holes_between_lines_at_nominal_spacing(method):
    out = plan(lines(), method).apply(values(lines()))
    assert np.isfinite(out[5:36]).all()


@BOTH
def test_a_line_that_wanders_leaves_a_stripe_that_a_larger_max_distance_closes(method):
    pop = lines((5, 15, 27, 35))
    v = values(pop)
    assert np.isnan(plan(pop, method, 0.25).apply(v)[21]).all()
    assert np.isfinite(plan(pop, method, 0.30, 1.0).apply(v)[5:36]).all()


@BOTH
def test_a_skipped_line_leaves_a_blank_stripe(method):
    pop = lines((5, 15, 35))
    v = values(pop)
    assert np.isnan(plan(pop, method, 0.25).apply(v)[25]).all()
    assert np.isfinite(plan(pop, method, 0.5, 1.0).apply(v)[25]).all()


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


@BOTH
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


@BOTH
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


@BOTH
def test_a_cross_hatched_grid_fills_without_holes(method):
    pop = lines((5, 15, 25, 35), ny=60, nx=60)
    pop[:, 5:56:10] = True
    out = plan(pop, method).apply(values(pop))
    assert np.isfinite(out[5:56, 5:56]).all()


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


@BOTH
def test_all_blank_input_gives_all_blank_output(method):
    fw = plan(lines(), method)
    assert np.isnan(fw.apply(np.full((40, 60), np.nan))).all()


@BOTH
def test_apply_at_matches_apply(method):
    pop = lines((5, 15, 35))  # rows around 25 are neither data nor targets
    fw = plan(pop, method)
    v = values(pop)
    ids = np.random.default_rng(1).integers(0, pop.size, 200)
    is_target = np.isin(ids, fw.targets)
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


def test_plan_fill_refuses_bad_input():
    pop = lines()
    for args in (
        (pop, 0.05, "magic", 0.25, 1.0),
        (pop, 0.05, "idw", -0.1, 1.0),
        (pop, 0.05, "idw", 0.25, 0.1),
        (pop.ravel(), 0.05, "idw", 0.25, 1.0),
        (pop, 0.0, "idw", 0.25, 1.0),
    ):
        with pytest.raises(ValueError):
            plan_fill(*args)
    with pytest.raises(ValueError):
        plan(pop, "idw").apply(np.zeros((3, 3)))


@needs_real_files
@BOTH
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
