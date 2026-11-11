"""The multigrid hierarchy that preconditions minimum curvature (#111)."""

from __future__ import annotations

import threading

import numpy as np
import pytest
from nsgeo.slices import multigrid
from nsgeo.slices.curvature import _OFFSETS, plan_curvature
from nsgeo.slices.multigrid import (
    COARSE_OFFSETS,
    apply_stencil,
    build_hierarchy,
    coarse_shape,
    prolong,
    restrict,
)

from tests.test_slices_curvature import lines


def operator(pop, cell, md):
    plan = plan_curvature(pop, cell, md)
    return plan.coefficients, plan.domain & ~plan.populated.reshape(plan.shape)


def dense(level):
    ny, nx = level.active.shape
    cells = np.flatnonzero(level.active.ravel())
    m = np.zeros((cells.size, cells.size))
    for j, c in enumerate(cells):
        e = np.zeros(ny * nx, np.float32)
        e[c] = 1
        m[:, j] = apply_stencil(level.offsets, level.coefficients, e.reshape(ny, nx)).ravel()[cells]
    return m


def prolongation(fine_active, fine_shape):
    cs = coarse_shape(fine_shape)
    fcells = np.flatnonzero(fine_active.ravel())
    p = np.zeros((fcells.size, cs[0] * cs[1]))
    for j in range(cs[0] * cs[1]):
        e = np.zeros(cs[0] * cs[1], np.float32)
        e[j] = 1
        p[:, j] = (prolong(e.reshape(cs), fine_shape) * fine_active).ravel()[fcells]
    return p


def small_frame():
    pop = np.random.default_rng(5).random((11, 13)) < 0.2
    pop[6] = True
    return operator(pop, 0.1, 0.3)


def test_coarse_offsets_are_the_25_row_major():
    assert len(COARSE_OFFSETS) == 25
    assert COARSE_OFFSETS[0] == (-2, -2) and COARSE_OFFSETS[-1] == (2, 2)
    assert tuple(sorted(COARSE_OFFSETS)) == COARSE_OFFSETS


def test_restrict_is_the_transpose_of_prolong():
    rng = np.random.default_rng(0)
    for s in [(17, 9), (16, 10), (1, 7), (2, 2), (1, 1)]:
        cs = coarse_shape(s)
        c = rng.normal(size=cs).astype(np.float32)
        f = rng.normal(size=s).astype(np.float32)
        a = float(np.vdot(prolong(c, s), f))
        b = float(np.vdot(c, restrict(f, cs)))
        assert abs(a - b) <= 1e-5 * np.linalg.norm(c) * np.linalg.norm(f), s


def test_prolong_keeps_constants_and_lines():
    for s in [(17, 9), (16, 10)]:
        cs = coarse_shape(s)
        assert np.allclose(prolong(np.full(cs, 2.5, np.float32), s), 2.5, atol=1e-6)
        c = np.repeat(np.arange(cs[0], dtype=np.float32)[:, None], cs[1], 1)
        i = np.arange(1, s[0] - 1)
        assert np.allclose(prolong(c, s)[1:-1, :], ((i + 0.5) / 2 - 0.5)[:, None], atol=1e-6)
        c = np.repeat(np.arange(cs[1], dtype=np.float32)[None, :], cs[0], 0)
        j = np.arange(1, s[1] - 1)
        assert np.allclose(prolong(c, s)[:, 1:-1], ((j + 0.5) / 2 - 0.5)[None, :], atol=1e-6)


def test_the_coarse_operator_is_the_galerkin_product(monkeypatch):
    monkeypatch.setattr(multigrid, "COARSEST_UNKNOWNS", 1)
    coef, act = small_frame()
    levels = build_hierarchy(_OFFSETS, coef, act).levels
    assert len(levels) >= 3
    for k in range(1, len(levels)):
        p = prolongation(levels[k - 1].active, levels[k - 1].active.shape)
        want = p.T @ dense(levels[k - 1]) @ p
        # P' spans every coarse cell; the coarse level keeps only its active ones.
        keep = levels[k].active.ravel()
        want = want[np.ix_(keep, keep)]
        assert np.abs(dense(levels[k]) - want).max() <= 1e-5 * np.abs(want).max()


def test_a_coarse_cell_is_active_exactly_when_it_reaches_a_fine_unknown(monkeypatch):
    monkeypatch.setattr(multigrid, "COARSEST_UNKNOWNS", 1)
    coef, act = small_frame()
    levels = build_hierarchy(_OFFSETS, coef, act).levels
    for k in range(1, len(levels)):
        shape = levels[k].active.shape
        want = restrict(levels[k - 1].active.astype(np.float32), shape) > 0
        assert np.array_equal(levels[k].active, want), k


def test_every_level_is_smoothed_within_its_bound(monkeypatch):
    monkeypatch.setattr(multigrid, "COARSEST_UNKNOWNS", 1)
    coef, act = small_frame()
    for level in build_hierarchy(_OFFSETS, coef, act).levels:
        m = dense(level)
        s = np.sqrt(level.scale[level.active].astype(np.float64))
        scaled = s[:, None] * m * s[None, :]
        w = np.linalg.eigvalsh(0.5 * (scaled + scaled.T))
        assert w.min() > 0 and w.max() <= 1 + 1e-5


def test_the_preconditioner_is_symmetric_and_positive(monkeypatch):
    monkeypatch.setattr(multigrid, "COARSEST_UNKNOWNS", 8)
    coef, act = operator(lines(), 0.05, 0.25)
    h = build_hierarchy(_OFFSETS, coef, act)
    assert len(h.levels) >= 4
    for seed in range(10):
        rng = np.random.default_rng(seed)
        r1 = (rng.normal(size=act.shape) * act).astype(np.float32)
        r2 = (rng.normal(size=act.shape) * act).astype(np.float32)
        keep = r1.copy()
        m1, m2 = h.precondition(r1), h.precondition(r2)
        # Random signs cancel the dot to ~0.3 against norm products of ~1e5, so float32
        # rounding in the cycle is held to the norms, not to the dot itself.
        a = float(np.vdot(m1.astype(np.float64), r2))
        b = float(np.vdot(r1.astype(np.float64), m2))
        scale = max(
            np.linalg.norm(m1) * np.linalg.norm(r2), np.linalg.norm(r1) * np.linalg.norm(m2)
        )
        assert abs(a - b) <= 1e-5 * scale
        assert np.vdot(m1, r1) > 0
        assert np.all(m1[~act] == 0)
        assert np.array_equal(r1, keep)


def test_one_level_inverts_exactly():
    pop = np.random.default_rng(5).random((12, 14)) < 0.2
    coef, act = operator(pop, 0.1, 0.15)
    h = build_hierarchy(_OFFSETS, coef, act)
    assert len(h.levels) == 1
    r = (np.random.default_rng(1).normal(size=act.shape) * act).astype(np.float32)
    back = apply_stencil(_OFFSETS, coef, h.precondition(r))
    assert np.abs(back - r)[act].max() <= 1e-4 * np.abs(r).max()


def test_no_unknowns_build_an_empty_hierarchy():
    coef, act = operator(np.ones((20, 20), bool), 0.05, 0.2)
    h = build_hierarchy(_OFFSETS, coef, act)
    assert len(h.levels) == 1
    assert h.coarse_inverse.shape == (0, 0) and h.coarse_cells.size == 0
    assert not h.precondition(np.zeros((20, 20), np.float32)).any()


def test_a_one_row_frame_coarsens_along_its_row():
    pop = np.zeros((1, 3000), bool)
    pop[0, ::7] = True
    coef, act = operator(pop, 0.05, 0.2)
    h = build_hierarchy(_OFFSETS, coef, act)
    assert [lv.active.shape for lv in h.levels] == [(1, 3000), (1, 1500), (1, 750), (1, 375)]
    assert h.levels[-1].active.sum() <= 500
    r = (np.random.default_rng(2).normal(size=act.shape) * act).astype(np.float32)
    assert np.vdot(h.precondition(r), r) > 0


def test_a_hierarchy_is_read_only():
    coef, act = operator(lines(), 0.05, 0.25)
    caller_active = act.copy()
    h = build_hierarchy(_OFFSETS, coef, caller_active)
    assert len(h.levels) > 1
    for level in h.levels:
        for array in (level.coefficients, level.active, level.scale):
            assert not array.flags.writeable
    assert not h.coarse_cells.flags.writeable and not h.coarse_inverse.flags.writeable
    with pytest.raises(ValueError):
        h.levels[1].coefficients[0, 0, 0] = 1.0
    caller_active[:] = ~caller_active
    assert np.array_equal(h.levels[0].active, act)


def test_nbytes_counts_every_array_but_the_fine_coefficients():
    coef, act = operator(lines(), 0.05, 0.25)
    h = build_hierarchy(_OFFSETS, coef, act)
    want = h.coarse_cells.nbytes + h.coarse_inverse.nbytes - h.levels[0].coefficients.nbytes
    for level in h.levels:
        want += level.coefficients.nbytes + level.active.nbytes + level.scale.nbytes
    assert h.nbytes == want


def test_two_threads_precondition_as_one():
    pop = np.zeros((200, 200), bool)
    pop[::10, :] = True
    coef, act = operator(pop, 0.05, 0.375)
    h = build_hierarchy(_OFFSETS, coef, act)
    rs = [
        (np.random.default_rng(s).normal(size=act.shape) * act).astype(np.float32) for s in range(4)
    ]
    serial = [h.precondition(r) for r in rs]
    out: list = [None] * 4

    def work(i):
        out[i] = h.precondition(rs[i])

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for got, want in zip(out, serial):
        assert np.array_equal(got, want)
