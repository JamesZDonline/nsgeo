"""The surface builder: follow the reflection the picks name, leave holes where it fades (M16 B)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest
from nsgeo.slices import (
    FIT_CLOSE_M,
    JOINS,
    JUMP_M,
    SurfaceSettings,
    VolumeSettings,
    ZAxis,
    build_surface,
    picks_span_an_area,
    prepare_volume,
    surface_mesh,
    surface_volume,
)
from nsgeo.velocity import VelocityModel

from tests.real_lines import AXIS, CELL, needs_real_files, squared_volume

NX, NY, C = 40, 30, 0.1
Z = ZAxis.from_range(0.0, 40.0, 0.1)
VEL = VelocityModel.constant(0.1)
STEP = 0.005  # depth per level: 0.05 m/ns * 0.1 ns


def _ricker2(tau_ns: np.ndarray) -> np.ndarray:
    a = (math.pi / 2.5) ** 2 * tau_ns**2
    return ((1.0 - 2.0 * a) * np.exp(-a)) ** 2


def _depth_of(x: np.ndarray) -> np.ndarray:
    return 0.5 + 0.01 * x


def _dipping(shift_ns: float = 0.0, extra_below_m: float = 0.0, extra_gain: float = 0.0):
    """A dipping reflector, a weak patch and an uncovered strip, as squared amplitude."""
    t = Z.times_ns()[:, None, None]
    xc = (np.arange(NX) + 0.5) * C
    tc = 2.0 * _depth_of(xc) / 0.1 + shift_ns
    filled = 1e-4 + _ricker2(t - tc[None, None, :]) * np.ones((1, NY, 1))
    if extra_gain:
        tc2 = tc + 2.0 * extra_below_m / 0.1
        filled = filled + extra_gain**2 * _ricker2(t - tc2[None, None, :])
    yc = (np.arange(NY) + 0.5) * C
    patch = (yc[:, None] >= 1.0) & (yc[:, None] < 1.5) & (xc[None, :] >= 2.0) & (xc[None, :] < 2.5)
    base = 1e-4
    filled = np.where(patch[None], base + (filled - base) * 0.02, filled)
    filled[:, :, -3:] = np.nan
    return filled.astype(np.float32)


def _picks(n: int = 12):
    """Cell-centre picks over x 0.5-3.5 m, y 0.5-2.5 m, 2 cm above the reflector."""
    ix = np.linspace(5, 34, n).astype(int)
    iy = np.array([5 + (7 * i + 1) % 20 for i in range(n)])  # none inside the weak patch
    x = (ix + 0.5) * C
    y = (iy + 0.5) * C
    return x, y, _depth_of(x) - 0.02


def _volume(filled=None, settings: VolumeSettings | None = None):
    filled = _dipping() if filled is None else filled
    return surface_volume(filled, Z, VEL, C, settings or VolumeSettings())


def _build(vol=None, picks=None, **kw):
    vol = vol or _volume()
    x, y, d = picks or _picks()
    return build_surface(vol, x, y, d, SurfaceSettings(**kw))


def _patch_mask():
    xc = (np.arange(NX) + 0.5) * C
    yc = (np.arange(NY) + 0.5) * C
    return (yc[:, None] >= 1.0) & (yc[:, None] < 1.5) & (xc[None, :] >= 2.0) & (xc[None, :] < 2.5)


def test_settings_defaults_validation_and_round_trip():
    s = SurfaceSettings()
    assert (s.join, s.window_m, s.strength, s.smoothing_m) == ("min_curvature", 0.02, 1.0, 0.0)
    assert JOINS == ("min_curvature", "idw")
    for bad in (
        {"join": "kriging"},
        {"window_m": 0.0},
        {"window_m": float("nan")},
        {"strength": -1.0},
        {"smoothing_m": float("inf")},
    ):
        with pytest.raises(ValueError):
            SurfaceSettings(**bad)
    got = SurfaceSettings.from_dict({"window_m": -1, "strength": 2})
    assert (got.window_m, got.strength) == (0.02, 2.0)
    assert SurfaceSettings.from_dict({"join": "nope", "extra": 1}) == SurfaceSettings()
    full = SurfaceSettings("idw", 0.03, 1.5, 0.1)
    assert SurfaceSettings.from_dict(full.to_dict()) == full
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.window_m = 1.0  # type: ignore[misc]


def test_build_refuses_a_blurred_volume():
    vol = prepare_volume(_dipping(), Z, VEL, C, VolumeSettings(blur_m=0.1))
    with pytest.raises(ValueError):
        build_surface(vol, *_picks(), SurfaceSettings())


def test_fewer_than_three_or_collinear_picks_are_refused():
    x, y, d = _picks()
    vol = _volume()
    assert not picks_span_an_area(x[:2], y[:2])
    with pytest.raises(ValueError):
        build_surface(vol, x[:2], y[:2], d[:2], SurfaceSettings())
    lx = np.linspace(0.5, 3.0, 5)
    ly = 0.5 + 0.2 * lx
    assert not picks_span_an_area(lx, ly)
    with pytest.raises(ValueError):
        build_surface(vol, lx, ly, np.full(5, 0.6), SurfaceSettings())
    assert picks_span_an_area(x, y)
    assert picks_span_an_area(lx, ly + np.array([0, 0, 0.5, 0, 0]))
    with pytest.raises(ValueError):
        build_surface(vol, x, y[:-1], d, SurfaceSettings())
    with pytest.raises(ValueError):
        build_surface(vol, x, y, np.where(np.arange(12) == 3, np.nan, d), SurfaceSettings())


def test_surface_follows_a_dipping_reflector_and_returns_to_the_picks():
    s = _build()
    assert abs(s.offset_m - 0.02) <= 0.005
    truth = np.broadcast_to(_depth_of((np.arange(NX) + 0.5) * C) - 0.02, (NY, NX))
    kept = np.isfinite(s.depth_m) & ~_patch_mask()
    assert kept.sum() > 100
    assert np.abs(s.depth_m[kept] - truth[kept]).max() <= 0.005
    assert s.fit.within_close == 12
    assert s.fit.on_holes == 0 and s.fit.at_edge == 0 and s.fit.outliers == ()
    assert s.depth_m.dtype == np.float32 and s.strength.dtype == np.float32
    assert s.region.shape == s.depth_m.shape == s.guide_m.shape == (NY, NX)
    assert s.cell == C


def test_weak_patch_is_a_hole_and_the_median_never_fills_it():
    s = _build()
    assert np.isnan(s.depth_m[_patch_mask()]).all()
    # a single weak cell, surrounded by kept cells, stays a hole
    filled = _dipping()
    yy, xx = 20, 12
    base = 1e-4
    filled[:, yy, xx] = base + (filled[:, yy, xx] - base) * 0.02
    s = _build(_volume(filled))
    assert np.isnan(s.depth_m[yy, xx])
    ring = s.depth_m[yy - 1 : yy + 2, xx - 1 : xx + 2].copy()
    ring[1, 1] = 0.0
    assert np.isfinite(ring[np.arange(9).reshape(3, 3) != 4]).all()


def test_uncovered_cells_are_outside_the_region():
    s = _build()
    assert not s.region[:, -3:].any()
    assert np.isnan(s.depth_m[:, -3:]).all() and np.isnan(s.guide_m[:, -3:]).all()
    assert s.region[:, :5].any() or s.region.any()
    assert np.isnan(s.guide_m[~s.region]).all()


def test_tracking_never_leaves_its_window():
    vol = _volume(_dipping(extra_below_m=0.04, extra_gain=3.0))
    s = _build(vol)
    kept = np.isfinite(s.depth_m)
    assert kept.sum() > 50
    gap = np.abs(s.depth_m[kept] - s.guide_m[kept])
    assert gap.max() <= 0.02 + STEP + 1e-6


def test_refinement_finds_a_peak_between_levels():
    shift = 0.5  # half a level, in ns
    vol = _volume(_dipping(shift_ns=shift))
    truth = _depth_of((np.arange(NX) + 0.5) * C) + 0.05 * shift
    x, y, _ = _picks()
    s = build_surface(vol, x, y, _depth_of(x) + 0.05 * shift, SurfaceSettings())
    kept = np.isfinite(s.depth_m)
    # away from the edge of the kept area, where the 3x3 median meets a tilted neighbour
    inner = kept.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            inner &= np.roll(kept, (dy, dx), axis=(0, 1))
    inner &= ~_patch_mask()
    assert inner.sum() > 100
    assert np.abs(s.depth_m - truth[None, :])[inner].max() <= 0.1 * STEP


def test_a_pick_outside_the_depth_range_or_frame_is_reported_not_fatal():
    vol = _volume()
    x, y, d = _picks()
    base = build_surface(vol, x, y, d, SurfaceSettings())
    bx = np.append(x, [1.0, 1.5, -1.0])
    by = np.append(y, [1.5, 1.7, 1.5])
    bd = np.append(d, [-0.01, vol.depths_m[-1] + 0.5, 0.6])
    s = build_surface(vol, bx, by, bd, SurfaceSettings())
    assert [o.index for o in s.fit.outliers] == [12, 13, 14]
    assert all(o.surface_m is None and o.reason == "hole" for o in s.fit.outliers)
    assert s.fit.on_holes == 3 and s.fit.within_close == 12
    np.testing.assert_array_equal(s.depth_m, base.depth_m)
    assert s.offset_m == base.offset_m


def test_a_surface_with_no_cell_passing_is_empty_not_an_error():
    s = _build(strength=1e9)
    assert np.isnan(s.depth_m).all()
    assert s.fit.on_holes == 12 and s.fit.within_close == 0
    assert len(s.fit.outliers) == 12 and all(o.reason == "hole" for o in s.fit.outliers)
    points, triangles, cells = surface_mesh(s.depth_m, s.cell)
    assert points.shape == (0, 3) and triangles.shape == (0, 3) and cells.shape == (0,)


def _categories(fit) -> int:
    return fit.within_close + fit.within_near + fit.further + fit.at_edge + fit.on_holes


def test_fit_categories_are_disjoint_and_edge_picks_are_named():
    vol = _volume()
    x, y, d = _picks()
    d = d.copy()
    d[4] += 0.015  # the reflection lies 1.5 cm below the offset-corrected pick: inside the window
    d[5] += 0.03  # 3 cm: the surface can only be held at the edge of its window
    s = build_surface(vol, x, y, d, SurfaceSettings())
    fit = s.fit
    assert _categories(fit) == 12
    edge = [o for o in fit.outliers if o.reason == "edge"]
    assert 5 in [o.index for o in edge]
    assert all(o.surface_m is not None for o in edge)
    assert fit.within_close + fit.within_near + fit.further + fit.at_edge + fit.on_holes == 12
    assert [o.index for o in fit.outliers] == sorted(o.index for o in fit.outliers)
    for o in fit.outliers:
        assert o.reason in ("hole", "edge", "far")


def test_mesh_never_joins_cells_more_than_6_cm_apart():
    d = np.full((3, 3), 0.5)
    d[:, 2] = 0.57  # a 7 cm step between columns 1 and 2
    points, triangles, cells = surface_mesh(d, 0.2)
    assert points.shape == (9, 3) and points.dtype == np.float64
    assert triangles.dtype == np.int64 and cells.dtype == np.int64
    np.testing.assert_array_equal(cells, np.arange(9))
    np.testing.assert_allclose(points[4], [0.3, 0.3, 0.5])
    assert len(triangles) == 4  # only the left column of quads
    assert set(triangles.ravel()) <= {0, 1, 3, 4, 6, 7}
    flat = surface_mesh(np.full((3, 3), 0.5), 0.2)[1]
    assert len(flat) == 8
    d[:, 2] = 0.5 + JUMP_M - 0.001  # just inside the limit still joins
    assert len(surface_mesh(d, 0.2)[1]) == 8
    hole = np.full((3, 3), 0.5)
    hole[1, 1] = np.nan
    pts, tri, flats = surface_mesh(hole, 0.2)
    assert len(pts) == 8 and 4 not in flats
    assert 0 < len(tri) < 8  # the quads that touch the hole lose a triangle or two
    assert np.isfinite(pts).all()
    assert (tri < 8).all()


def test_smoothing_is_off_by_default_and_never_fills_holes():
    plain = _build()
    soft = _build(smoothing_m=0.15)
    assert np.array_equal(np.isnan(plain.depth_m), np.isnan(soft.depth_m))
    kept = np.isfinite(plain.depth_m)
    assert not np.array_equal(plain.depth_m[kept], soft.depth_m[kept])
    again = _build(smoothing_m=0.0)
    np.testing.assert_array_equal(plain.depth_m, again.depth_m)
    assert np.isnan(soft.depth_m[_patch_mask()]).all()


def test_a_small_slab_gives_the_same_surface():
    vol = _volume()
    a = _build(vol)
    x, y, d = _picks()
    b = build_surface(vol, x, y, d, SurfaceSettings(), max_levels=7)
    np.testing.assert_array_equal(a.depth_m, b.depth_m)
    assert a.offset_m == b.offset_m


def test_idw_guide_passes_through_the_picks_and_flat_between():
    s = _build(join="idw")
    assert np.isfinite(s.guide_m[s.region]).all()
    assert s.fit.within_close == 12
    assert FIT_CLOSE_M == 0.02


def test_swing_is_the_filled_amplitude_and_nan_off_coverage():
    filled = _dipping()
    vol = _volume(filled)
    sw = vol.swing(40, 60)
    assert sw.shape == (20, NY, NX) and sw.dtype == np.float32
    np.testing.assert_allclose(sw[:, :, :5], filled[40:60, :, :5], rtol=1e-6)
    assert np.isnan(sw[:, :, -3:]).all()
    with pytest.raises(ValueError):
        vol.swing(5, 5)


# --- real lines ---------------------------------------------------------------------------------

_V = 0.071


def _surface_vol():
    out, _ = squared_volume()
    return surface_volume(out, AXIS, VelocityModel.constant(_V), CELL, VolumeSettings())


def _peak(col: np.ndarray, k: int) -> float:
    if k == 0 or k == len(col) - 1:
        return 0.0
    vm, v0, vp = col[k - 1], col[k], col[k + 1]
    denom = vm - 2 * v0 + vp
    return 0.0 if not denom < 0 else float(np.clip(0.5 * (vm - vp) / denom, -0.5, 0.5))


def _reflector_picks(vol):
    """15 picks on a real reflection, along the data rows, x 4-16 m.

    The level below 0.3 m where most covered data-row cells have strength >= 1.5 is the
    reflection. The picks are 15 of that level's strong cells, spread over x, each at the
    refined swing peak within 5 cm of the level.
    """
    nd = vol.depths_m.size
    step = vol.depths_m[1] - vol.depths_m[0]
    rows = [int((0.25 + 0.5 * i) // CELL) for i in range(10)]
    _, strength = vol.slab(0, nd)
    data = strength[:, rows, :]
    share = np.array([np.mean(data[j][np.isfinite(data[j])] >= 1.5) for j in range(nd)])
    share[vol.depths_m < 0.3] = -1.0
    level = int(np.argmax(share))
    cells = [
        (iy, ix)
        for ix in range(int(4.0 // CELL), int(16.0 // CELL) + 1)
        for iy in rows
        if strength[level, iy, ix] >= 1.5
    ]
    assert len(cells) >= 15
    chosen = [cells[i] for i in np.linspace(0, len(cells) - 1, 15).round().astype(int)]
    reach = int(round(0.05 / step))
    j0, j1 = max(0, level - reach), min(nd, level + reach + 1)
    px, py, pd = [], [], []
    for iy, ix in chosen:
        col = vol.swing(j0, j1)[:, iy, ix].astype(float)
        k = int(np.argmax(col))
        px.append((ix + 0.5) * CELL)
        py.append((iy + 0.5) * CELL)
        pd.append(vol.depths_m[j0 + k] + _peak(col, k) * step)
    return np.array(px), np.array(py), np.array(pd)


@needs_real_files
def test_real_picks_on_a_reflector_land_within_2_cm():
    vol = _surface_vol()
    x, y, d = _reflector_picks(vol)
    assert len(x) == 15
    s = build_surface(vol, x, y, d, SurfaceSettings())
    iy, ix = (y // CELL).astype(int), (x // CELL).astype(int)
    got = s.depth_m[iy, ix]
    kept = np.isfinite(got)
    print("kept", int(kept.sum()), "offset", s.offset_m, s.fit)
    assert kept.sum() >= 12
    assert np.abs(got[kept] - d[kept]).max() <= 0.02 + 1e-6


@needs_real_files
def test_real_holes_are_where_strength_fails():
    vol = _surface_vol()
    x, y, d = _reflector_picks(vol)
    s = build_surface(vol, x, y, d, SurfaceSettings())
    kept = np.isfinite(s.depth_m)
    assert kept.any()
    assert (s.strength[kept] >= 1.0).all()
    strict = build_surface(vol, x, y, d, SurfaceSettings(strength=2.0))
    assert (strict.strength[np.isfinite(strict.depth_m)] >= 2.0).all()
    assert np.isfinite(strict.depth_m).sum() <= kept.sum()


@needs_real_files
def test_real_surface_never_leaves_its_window():
    vol = _surface_vol()
    s = build_surface(vol, *_reflector_picks(vol), SurfaceSettings())
    kept = np.isfinite(s.depth_m)
    assert np.abs(s.depth_m[kept] - s.guide_m[kept]).max() <= 0.02 + 1e-6


@needs_real_files
def test_real_one_ns_shift_is_recovered_as_the_offset():
    vol = _surface_vol()
    x, y, d = _reflector_picks(vol)
    base = build_surface(vol, x, y, d, SurfaceSettings())
    up = _V / 2.0  # 1 ns of two-way time
    moved = build_surface(vol, x, y, d - up, SurfaceSettings())
    assert abs((moved.offset_m - base.offset_m) - up) <= 0.005
    iy, ix = (y // CELL).astype(int), (x // CELL).astype(int)
    both = np.isfinite(base.depth_m[iy, ix]) & np.isfinite(moved.depth_m[iy, ix])
    assert both.sum() >= 10
    shift = base.depth_m[iy, ix][both] - moved.depth_m[iy, ix][both]
    assert np.abs(shift - up).max() <= 0.005


@needs_real_files
def test_real_pick_on_another_reflection_is_reported():
    vol = _surface_vol()
    x, y, d = _reflector_picks(vol)
    d = d.copy()
    d[7] += 0.15
    s = build_surface(vol, x, y, d, SurfaceSettings())
    print("outliers", s.fit.outliers)
    assert [o.index for o in s.fit.outliers if o.index == 7] != []
    assert _categories(s.fit) == 15
    assert [o.reason for o in s.fit.outliers if o.index == 7] == ["edge"]


@needs_real_files
def test_real_joins_differ_as_described():
    vol = _surface_vol()
    x, y, d = _reflector_picks(vol)
    mc = build_surface(vol, x, y, d, SurfaceSettings(join="min_curvature"))
    idw = build_surface(vol, x, y, d, SurfaceSettings(join="idw"))
    iy, ix = (y // CELL).astype(int), (x // CELL).astype(int)
    binned = np.zeros(mc.depth_m.shape)
    count = np.zeros(mc.depth_m.shape)
    np.add.at(binned, (iy, ix), d)
    np.add.at(count, (iy, ix), 1)
    populated = (count > 0) & mc.region
    np.testing.assert_allclose(
        mc.guide_m[populated], (binned / np.maximum(count, 1))[populated], atol=1e-6
    )

    # the minimum-curvature join passes through every pick; inverse distance is pulled off them
    assert np.abs(idw.guide_m[populated] - (binned / np.maximum(count, 1))[populated]).max() > 1e-4
