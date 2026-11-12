"""The prepared volume: RMS over a wave period, blur, depth-trend balance (M16 spec §2.1)."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing import build_step
from nsgeo.processing.base import Radargram
from nsgeo.slices import (
    CubeFrame,
    FinishSettings,
    PreparedLine,
    Provenance,
    SliceCube,
    VolumeSettings,
    VolumeStopped,
    ZAxis,
    build_cube,
    depth_axis,
    fill_levels,
    plan_fill,
    plan_line,
    prepare_volume,
)
from nsgeo.velocity import VelocityModel

from tests.real_data import CAMPUS_LINES
from tests.real_lines import AXIS, CELL, SPACING, needs_real_files, prepared_lines


def _prov(transform: str) -> Provenance:
    return Provenance(
        line_keys=("a",),
        preset_name="p",
        steps=(),
        transform=transform,
        velocity=None,
        built_utc="2026-11-12T00:00:00Z",
        core_version="0.1.0.dev0",
    )


def _cube(mean: np.ndarray, count: np.ndarray, transform: str, cell: float = 0.1) -> SliceCube:
    nz, n_cells = mean.shape
    ny, nx = count.shape
    frame = CubeFrame((0.0, 0.0), 0.0, cell, nx, ny, "EPSG:32633")
    z = ZAxis(0.0, 0.1, nz)
    return SliceCube.from_dense(frame, z, mean, count.reshape(-1), _prov(transform))


def _small(transform: str = "amp_envelope"):
    mean = np.arange(1, 13, dtype=np.float32).reshape(3, 4)  # 3 levels, 2x2 cells
    count = np.array([[1, 1], [1, 0]], dtype=np.int32)
    cube = _cube(mean, count, transform)
    weights = plan_fill(count > 0, 0.1, "none", 0.0, 0.0)
    finish = FinishSettings("none", 0.0, 0.0)
    return cube, weights, finish, mean


def test_settings_defaults_validation_and_round_trip():
    s = VolumeSettings()
    assert (s.period_ns, s.blur_m, s.trend_m) == (2.5, 0.1, 0.15)
    for bad in ({"period_ns": 0.0}, {"trend_m": -1.0}, {"blur_m": float("nan")}):
        with pytest.raises(ValueError):
            VolumeSettings(**bad)
    assert VolumeSettings.from_dict(s.to_dict()) == s
    assert VolumeSettings.from_dict({"period_ns": "x", "blur_m": 0.2}) == VolumeSettings(blur_m=0.2)
    assert VolumeSettings.from_dict({"trend_m": -3.0}) == VolumeSettings()


def test_fill_levels_squares_unless_the_cube_is_already_squared():
    for transform, want in (
        ("amp_envelope", lambda v: v**2),
        ("amp_abs", lambda v: v**2),
        ("amp_square", lambda v: v),
    ):
        cube, weights, finish, mean = _small(transform)
        out = np.empty((3, 2, 2), dtype=np.float32)
        fill_levels(cube, weights, finish, out)
        v = mean.reshape(3, 2, 2)
        np.testing.assert_allclose(
            out[:, :2, :][:, [0, 0, 1], [0, 1, 0]], want(v)[:, [0, 0, 1], [0, 1, 0]]
        )
        assert np.isnan(out[:, 1, 1]).all()


def test_fill_levels_matches_finish_slice_for_a_filled_level():
    mean = np.tile(np.array([[1.0, 2.0, 0.0, 4.0]], dtype=np.float32), (2, 1))
    count = np.array([[1, 1, 0, 1]], dtype=np.int32)
    cube = _cube(mean, count, "amp_square")
    weights = plan_fill(count > 0, 0.1, "idw", 0.2, 0.4)
    finish = FinishSettings("idw", 0.2, 0.4, smooth_x_m=0.1)
    from nsgeo.slices import finish_slice

    out = np.empty((2, 1, 4), dtype=np.float32)
    fill_levels(cube, weights, finish, out)
    np.testing.assert_array_equal(out[1], finish_slice(cube.level(1), weights, 0.1, finish))
    assert np.isfinite(out[1]).all()


def test_fill_levels_stops_when_progress_says_so():
    cube, weights, finish, _ = _small()
    out = np.empty((3, 2, 2), dtype=np.float32)
    calls: list[int] = []
    with pytest.raises(VolumeStopped):
        fill_levels(cube, weights, finish, out, progress=lambda k, n: calls.append(k) or k < 2)
    assert calls == [1, 2]


def _ringing_volume():
    z = ZAxis(0.0, 0.1, 400)
    t = z.times_ns()
    # A ringing 400 MHz wavelet, about five cycles long: its square has several lobes.
    wave = np.cos(2 * np.pi * 0.4 * (t - 20.0)) * np.exp(-(((t - 20.0) / 3.0) ** 2))
    column = wave**2
    filled = column.astype(np.float32).reshape(-1, 1, 1)
    return z, column, prepare_volume(filled, z, VelocityModel.constant(0.1), 0.1, VolumeSettings())


def test_rms_turns_one_reflection_into_one_hump():
    z, column, vol = _ringing_volume()

    def humps(c):
        peak = (c[1:-1] > c[:-2]) & (c[1:-1] >= c[2:]) & (c[1:-1] > 0.5 * c.max())
        return np.flatnonzero(peak) + 1

    assert humps(column).size >= 2
    amp, _ = vol.slab(0, vol.depths_m.size)
    found = humps(amp[:, 0, 0].astype(float))
    assert found.size == 1
    assert abs(z.times_ns()[found[0]] - 20.0) < 1.5


def test_depth_axis_constant_velocity_is_the_levels_from_time_zero():
    z = ZAxis(t0_ns=-0.476, dz_ns=0.1, nz=455)
    depths, src = depth_axis(z, VelocityModel.constant(0.071))
    assert depths[0] >= 0 and src[0] == 5
    assert np.allclose(np.diff(depths), 0.071 * 0.1 / 2)
    assert depths.size == 450 and np.array_equal(src, np.arange(5, 455))


def test_layered_velocity_gives_a_uniform_depth_axis():
    v = VelocityModel(layers=((0.0, 0.10), (20.0, 0.06)))
    depths, src = depth_axis(ZAxis(0.0, 0.2, 300), v)
    assert np.allclose(np.diff(depths), np.diff(depths)[0])
    assert np.all(np.diff(src) > 0) and src[-1] <= 299
    # each depth sits where the velocity model puts its source time
    t = ZAxis(0.0, 0.2, 300).times_ns()
    np.testing.assert_allclose(np.interp(src, np.arange(300), v.depth_at(t)), depths, atol=1e-9)


def test_a_cube_with_no_level_after_time_zero_is_refused():
    with pytest.raises(ValueError):
        depth_axis(ZAxis(-5.0, 0.1, 10), VelocityModel.constant(0.1))


def _real_volume():
    frame = CubeFrame((0.0, 0.0), 0.0, CELL, 100, 25, "EPSG:32633")
    lines = prepared_lines(range(10), lambda local: local)
    plans = [plan_line(p, frame, AXIS) for p in lines]
    cube = build_cube(lines, plans, frame, AXIS, _prov("amp_envelope"))
    weights = plan_fill(cube.coverage() > 0, CELL, "idw", 0.25, 1.0)
    finish = FinishSettings("idw", 0.25, 1.0)
    out = np.empty((AXIS.nz, frame.ny, frame.nx), dtype=np.float32)
    fill_levels(cube, weights, finish, out)
    return out, prepare_volume(out, AXIS, VelocityModel.constant(0.071), CELL, VolumeSettings())


@needs_real_files
def test_strength_is_about_one_at_every_depth_on_real_lines():
    _, vol = _real_volume()
    _, strength = vol.slab(0, vol.depths_m.size)
    medians = np.array([np.median(level[vol.covered]) for level in strength])
    print("median strength range", medians.min(), medians.max())
    assert np.mean((medians >= 0.7) & (medians <= 1.3)) >= 0.9


def _holey():
    rng = np.random.default_rng(3)
    filled = rng.random((60, 6, 7)).astype(np.float32) ** 2
    filled[:, 2:4, 3:5] = np.nan
    filled[:, 0, 0] = np.nan
    vol = prepare_volume(
        filled, ZAxis(0.0, 0.1, 60), VelocityModel.constant(0.1), 0.1, VolumeSettings()
    )
    return filled, vol


def test_uncovered_cells_are_nan_in_both_arrays_and_blur_keeps_holes():
    filled, vol = _holey()
    amp, strength = vol.slab(0, vol.depths_m.size)
    hole = ~vol.covered
    assert hole.sum() == 5
    assert np.isnan(amp[:, hole]).all() and np.isnan(strength[:, hole]).all()
    assert np.isfinite(amp[:, vol.covered]).all()
    assert np.isfinite(amp[:, 1, 3]).all()  # covered, beside the hole
    assert amp.dtype == np.float32 and strength.dtype == np.float32


def test_slabs_equal_the_whole():
    _, vol = _holey()
    nd = vol.depths_m.size
    a0, s0 = vol.slab(0, nd)
    parts = [vol.slab(j, min(j + 7, nd)) for j in range(0, nd, 7)]
    np.testing.assert_array_equal(np.concatenate([p[0] for p in parts]), a0)
    np.testing.assert_array_equal(np.concatenate([p[1] for p in parts]), s0)


def test_slabs_equal_the_whole_with_a_layered_velocity():
    filled = np.random.default_rng(5).random((120, 3, 3)).astype(np.float32)
    v = VelocityModel(layers=((0.0, 0.10), (6.0, 0.06)))
    vol = prepare_volume(filled, ZAxis(0.0, 0.1, 120), v, 0.1, VolumeSettings(), slab_levels=16)
    nd = vol.depths_m.size
    assert np.any(vol.source_level % 1 > 0)
    a0, _ = vol.slab(0, nd)
    parts = [vol.slab(j, min(j + 11, nd))[0] for j in range(0, nd, 11)]
    np.testing.assert_array_equal(np.concatenate(parts), a0)


def test_prepare_volume_stops_when_progress_says_so():
    filled = np.random.default_rng(7).random((60, 3, 3)).astype(np.float32)
    calls: list[tuple[int, int]] = []

    def progress(done: int, total: int) -> bool:
        calls.append((done, total))
        return done < 2

    with pytest.raises(VolumeStopped):
        prepare_volume(
            filled,
            ZAxis(0.0, 0.1, 60),
            VelocityModel.constant(0.1),
            0.1,
            VolumeSettings(),
            slab_levels=16,
            progress=progress,
        )
    assert calls == [(1, 4), (2, 4)]


def test_prepare_volume_reports_every_slab():
    filled = np.random.default_rng(7).random((60, 3, 3)).astype(np.float32)
    calls: list[tuple[int, int]] = []
    prepare_volume(
        filled,
        ZAxis(0.0, 0.1, 60),
        VelocityModel.constant(0.1),
        0.1,
        VolumeSettings(),
        slab_levels=25,
        progress=lambda d, t: calls.append((d, t)) or True,
    )
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_an_empty_cube_is_refused():
    filled = np.full((10, 2, 2), np.nan, dtype=np.float32)
    with pytest.raises(ValueError):
        prepare_volume(
            filled, ZAxis(0.0, 0.1, 10), VelocityModel.constant(0.1), 0.1, VolumeSettings()
        )


# --- real lines, squared amplitude from the bipolar data (no envelope step) -------------------

_SQUARED: list = []


def _squared_volume():
    """Ten real lines, left bipolar and squared (`amp_square`), binned on a frame with spare rows
    and columns so some cells stay uncovered. Built once."""
    if not _SQUARED:
        lines = []
        for i, path in enumerate(CAMPUS_LINES[:10]):
            header = read_header(path)
            rg = Radargram(
                data=np.asarray(read_samples(path, header)[0], dtype=float),
                dt_ns=header.dt_ns,
                t0_ns=header.position_ns,
            )
            for name in ("time_zero", "dewow", "background_mean", "gain_agc"):
                rg = build_step(name).apply(rg)
            n = rg.data.shape[1]
            local = np.column_stack([np.linspace(0.0, 19.99, n), np.full(n, 0.25 + i * SPACING)])
            lines.append(
                PreparedLine(
                    key=path.name,
                    data=(rg.data**2).astype(np.float32),
                    dt_ns=rg.dt_ns,
                    t0_ns=rg.t0_ns,
                    coords=local,
                )
            )
        frame = CubeFrame((0.0, 0.0), 0.0, CELL, 110, 30, "EPSG:32633")
        plans = [plan_line(p, frame, AXIS) for p in lines]
        cube = build_cube(lines, plans, frame, AXIS, _prov("amp_square"))
        finish = FinishSettings("idw", 0.25, 1.0)
        weights = plan_fill(cube.coverage() > 0, CELL, "idw", 0.25, 1.0)
        out = np.empty((AXIS.nz, frame.ny, frame.nx), dtype=np.float32)
        fill_levels(cube, weights, finish, out)
        vol = prepare_volume(out, AXIS, VelocityModel.constant(0.071), CELL, VolumeSettings())
        _SQUARED.append((out, vol))
    return _SQUARED[0]


def _humps(c: np.ndarray) -> int:
    """Humps above half the maximum. Two maxima are one hump unless the dip between them falls
    below 80% of the lower of the two (a ripple on a plateau is not a second reflection)."""
    peaks = np.flatnonzero((c[1:-1] > c[:-2]) & (c[1:-1] >= c[2:]) & (c[1:-1] > 0.5 * c.max())) + 1
    count = 1 if peaks.size else 0
    for a, b in zip(peaks, peaks[1:]):
        if c[a : b + 1].min() < 0.8 * min(c[a], c[b]):
            count += 1
    return count


@needs_real_files
def test_real_volume_is_unipolar_and_uncovered_cells_stay_nan():
    _, vol = _squared_volume()
    amp, strength = vol.slab(0, vol.depths_m.size)
    for arr in (amp, strength):
        assert np.nanmin(arr) >= 0.0
        assert np.isfinite(arr[:, vol.covered]).all()
        assert np.isnan(arr[:, ~vol.covered]).all()
    assert (~vol.covered).any() and vol.covered.any()


@needs_real_files
def test_real_column_through_a_strong_reflection_has_one_hump():
    out, vol = _squared_volume()
    # constant velocity from level 0: depth level j is source level j
    assert vol.source_level[0] == 0
    peaks = np.nan_to_num(out, nan=-1.0).max(axis=0)
    strongest = np.argsort(peaks, axis=None)[::-1][:300]  # the 300 strongest columns
    ringing = merged = 0
    for flat in strongest:
        y, x = np.unravel_index(flat, peaks.shape)
        k = int(np.argmax(out[:, y, x]))
        k0, k1 = max(0, k - 10), min(out.shape[0], k + 11)  # about +-2 ns round the peak
        if _humps(out[k0:k1, y, x]) < 2:
            continue
        ringing += 1
        amp, _ = vol.slab(k0, k1)
        merged += _humps(amp[:, y, x].astype(float)) == 1
    print("ringing columns", ringing, "merged to one hump", merged)
    assert ringing >= 10
    assert merged == ringing


@needs_real_files
def test_real_slabs_equal_the_whole():
    _, vol = _squared_volume()
    nd = vol.depths_m.size
    a0, s0 = vol.slab(0, nd)
    parts = [vol.slab(j, min(j + 23, nd)) for j in range(0, nd, 23)]
    np.testing.assert_array_equal(np.concatenate([p[0] for p in parts]), a0)
    np.testing.assert_array_equal(np.concatenate([p[1] for p in parts]), s0)
