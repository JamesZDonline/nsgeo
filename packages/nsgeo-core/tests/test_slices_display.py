"""Windows, labels, the shared stretch, and the north-up resample."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import PercentileClip, UnipolarClip
from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.display import (
    SliceWindow,
    limit_over_slices,
    plan_windows,
    shared_limit,
    to_north_up,
    window_depths_m,
    window_label,
    window_times_ns,
)
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.velocity import VelocityModel


def _axis(nz: int = 100, dz: float = 0.5, t0: float = 0.0) -> ZAxis:
    return ZAxis(t0_ns=t0, dz_ns=dz, nz=nz)


def test_a_window_rejects_an_empty_or_reversed_range():
    with pytest.raises(ValueError):
        SliceWindow(5, 5)
    with pytest.raises(ValueError):
        SliceWindow(5, 4)
    with pytest.raises(ValueError):
        SliceWindow(-1, 3)


def test_abutting_windows_tile_the_axis_without_gaps_or_overlap():
    windows = plan_windows(_axis(nz=100), thickness_levels=10, step_levels=10)
    assert len(windows) == 10
    assert windows[0] == SliceWindow(0, 10)
    assert windows[-1] == SliceWindow(90, 100)
    for a, b in zip(windows, windows[1:]):
        assert b.k0 == a.k1


def test_overlapping_windows_match_the_specs_band_count_formula():
    """Spec 9.4: n_bands = (z_range - thickness) / step + 1. In levels,
    that is (nz - thickness) // step + 1 -- the count a GeoTIFF export
    turns into bands, so an off-by-one here is an off-by-one file."""
    nz, thickness, step = 100, 10, 5
    windows = plan_windows(_axis(nz=nz), thickness, step)
    assert len(windows) == (nz - thickness) // step + 1 == 19
    assert windows[1].k0 == 5  # 50% overlap: the second window starts mid-first
    assert windows[1].k1 == 15
    assert windows[-1].k1 == nz  # the last window still ends on the axis


def test_a_window_thicker_than_the_axis_becomes_the_whole_axis():
    assert plan_windows(_axis(nz=8), thickness_levels=20, step_levels=1) == (SliceWindow(0, 8),)


def test_plan_windows_rejects_a_non_positive_thickness_or_step():
    with pytest.raises(ValueError):
        plan_windows(_axis(), 0, 5)
    with pytest.raises(ValueError):
        plan_windows(_axis(), 5, 0)


def test_a_windows_time_span_is_n_minus_one_sample_intervals():
    """Levels are POINT samples -- plan_line resamples at each level's
    exact time by linear interpolation, it does not integrate a bin -- so
    n levels span (n - 1) * dz, not n * dz. The plausible wrong version
    (k1 * dz, i.e. n * dz) is off by one interval at every thickness, and
    at thickness 1 it reports a 0.5 ns window where the truth is a single
    sample."""
    z = _axis(nz=100, dz=0.5, t0=2.0)
    assert window_times_ns(z, SliceWindow(10, 20)) == pytest.approx((7.0, 11.5))
    assert window_times_ns(z, SliceWindow(10, 11)) == pytest.approx((7.0, 7.0))


def test_the_label_reports_what_level_range_actually_returned_not_what_was_asked_for():
    """Spec 6.6 and ZAxis.level_range's own docstring: at either end of the
    axis the returned window is genuinely thinner than requested. A label
    derived from (top_ns, thickness_ns) instead of from (k0, k1) claims a
    window that was never averaged."""
    z = _axis(nz=100, dz=0.5, t0=0.0)  # axis covers 0.0 .. 49.5 ns
    k0, k1 = z.level_range(top_ns=48.0, thickness_ns=8.0)  # asks for 8 ns, cannot have it
    assert (k0, k1) == (96, 100)
    lo, hi = window_times_ns(z, SliceWindow(k0, k1))
    assert (lo, hi) == pytest.approx((48.0, 49.5))
    assert hi - lo < 8.0  # the point: what was asked for is not what happened
    assert "48.0" in window_label(z, SliceWindow(k0, k1))
    assert "49.5" in window_label(z, SliceWindow(k0, k1))
    assert "56.0" not in window_label(z, SliceWindow(k0, k1))  # 48 + 8, the wrong answer


def test_the_label_carries_both_units_when_a_velocity_is_given():
    z = _axis(nz=100, dz=0.5, t0=0.0)
    v = VelocityModel.constant(0.08)  # m/ns; depth = v/2 * t
    lo_m, hi_m = window_depths_m(z, SliceWindow(30, 40), v)
    assert (lo_m, hi_m) == pytest.approx((0.6, 0.78))
    label = window_label(z, SliceWindow(30, 40), v)
    assert "ns" in label and "m" in label
    assert "15.0" in label and "19.5" in label  # the ns range
    # Without a velocity the depth half is simply absent, never invented.
    assert "m" not in window_label(z, SliceWindow(30, 40)).replace("ns", "")


def _cube_with_varying_levels(seed: int = 0) -> SliceCube:
    """A cube whose LEVELS have much more spread than their window means.

    That gap is the whole subject: averaging 10 levels pulls the extremes
    in hard, so a limit measured on raw levels is far too large for the
    slices actually displayed. Built deliberately rather than sampled from
    real data so the effect is unambiguous.
    """
    rng = np.random.default_rng(seed)
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=1.0, nx=20, ny=20, crs="EPSG:32633")
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=40)
    count = np.ones(frame.n_cells, dtype=np.int32)
    mean = np.abs(rng.standard_normal((z.nz, frame.n_cells))).astype(np.float32)
    prov = Provenance(
        line_keys=("a",),
        preset_name="p",
        steps=(),
        transform="amp_abs",
        velocity=None,
        built_utc="2026-09-19T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    return SliceCube(frame=frame, z=z, mean=mean, count=count, provenance=prov)


def test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels():
    """The M10 final review's Important 3, now a test. A window mean has
    far lower variance than the levels it averages, so UnipolarClip().
    limit(cube.mean) is systematically too high -- and because the bias is
    uniform across depth, every slice renders dim IDENTICALLY at every
    depth, which reads as 'the data is dim' rather than as a bug. That is
    exactly why it needs a test rather than an eye."""
    cube = _cube_with_varying_levels()
    clip = UnipolarClip()
    over_levels = clip.limit(cube.mean)
    over_slices = shared_limit(cube, thickness_levels=10, clip=clip)
    assert over_slices < over_levels
    assert over_slices / over_levels < 0.8  # measured ~0.55 on this fixture
    # And it really is the limit of what gets shown: every displayed slice
    # sits at or below it apart from the percentile's own tail.
    windows = plan_windows(cube.z, 10, 10)
    shown = np.concatenate([cube.slice_levels(w.k0, w.k1).ravel() for w in windows])
    assert over_slices == pytest.approx(float(np.percentile(shown, clip.percentile)), rel=1e-6)


def test_the_shared_limit_covers_every_level_exactly_once():
    """Abutting windows, so no depth is weighted twice in the percentile.
    A step-1 implementation would weight the middle of the axis ~10x more
    than its ends and shift the limit.

    The non-divisible case is the one that matters: `plan_windows` emits
    whole windows only, so without a final partial window the tail of the
    axis is excluded from the stretch entirely -- 20 of 181 levels on the
    real corpus, and the brightest ones in it."""
    cube = _cube_with_varying_levels()
    windows = plan_windows(cube.z, 10, 10)
    assert sum(w.n_levels for w in windows) == cube.z.nz
    assert [w.k0 for w in windows] == [0, 10, 20, 30]

    # nz=37 with thickness 10: plan_windows gives 0,10,20 and stops at 30,
    # leaving 7 levels. shared_limit must still see all 37.
    odd = SliceCube(
        frame=cube.frame,
        z=ZAxis(t0_ns=0.0, dz_ns=0.5, nz=37),
        mean=cube.mean[:37],
        count=cube.count,
        provenance=cube.provenance,
    )
    seen: list[np.ndarray] = []

    class _Recording:
        percentile = 99.0

        def limit(self, data: np.ndarray) -> float:
            seen.append(np.asarray(data))
            return 1.0

    shared_limit(odd, 10, _Recording())
    # `slice_levels` returns one aggregated value per CELL per window, not
    # per level, so the total `shared_limit` hands to `clip.limit` is
    # (n_windows * n_cells), never (nz * n_cells) -- a window of any
    # thickness still contributes exactly `frame.n_cells` values. The
    # windows are abutting and whole except for one thinner tail window
    # (spec 9.4's whole-window rule applies to `plan_windows`, not to this
    # measurement), so the expected window count is a plain ceiling
    # division: 4 windows for nz=37, thickness=10 (0-10, 10-20, 20-30,
    # 30-37), not 3 (without the tail fix, the last 7 levels are dropped
    # entirely and `shared_limit` never sees them).
    expected_n_windows = -(-odd.z.nz // 10)  # ceil(37 / 10) == 4
    assert seen and seen[0].size == expected_n_windows * odd.frame.n_cells, (
        f"shared_limit saw {seen[0].size} values from an implied "
        f"{seen[0].size // odd.frame.n_cells} window(s); expected "
        f"{expected_n_windows} windows (the tail window must not be dropped)"
    )


def test_limit_over_slices_ignores_nodata_and_survives_an_all_nodata_slice():
    clip = PercentileClip(percentile=100.0)
    a = np.array([[1.0, np.nan], [np.nan, 3.0]])
    b = np.full((2, 2), np.nan)
    assert limit_over_slices([a, b], clip) == pytest.approx(3.0)
    assert limit_over_slices([b], clip) == 1.0  # the documented empty fallback, never 0 or NaN


def test_limit_over_slices_refuses_an_empty_sequence():
    with pytest.raises(ValueError):
        limit_over_slices([], PercentileClip())


def _ramp_frame(azimuth: float = 0.0) -> tuple[CubeFrame, np.ndarray]:
    """A frame and a values array whose rows are all different, so a
    vertical flip is visible. `values[0]` is frame-local y index 0."""
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=azimuth, cell=1.0, nx=4, ny=3, crs="EPSG:32633")
    values = np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0], [9.0, 10.0, 11.0, 12.0]])
    return frame, values


def test_north_up_puts_frame_row_zero_at_the_BOTTOM_of_the_raster():
    """The single most likely defect in this function, and invisible in
    any symmetric test fixture. A raster's row 0 is its NORTHERN edge --
    the geotransform's y pixel size is negative -- while a CubeFrame's
    y index 0 is its SOUTHERN edge, because frame-local +Y points north
    at azimuth 0. Getting this wrong mirrors every exported slice
    vertically: the anomalies are all still there, in the wrong place,
    and nothing about the image says so."""
    frame, values = _ramp_frame()
    out, gt = to_north_up(values, frame)
    assert out.shape == (3, 4)
    np.testing.assert_allclose(out[0], [9.0, 10.0, 11.0, 12.0])  # north = frame's LAST row
    np.testing.assert_allclose(out[-1], [1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(out, values[::-1])


def test_north_up_geotransform_is_north_up_and_anchored_at_the_top_left():
    frame, values = _ramp_frame()
    _, gt = to_north_up(values, frame)
    origin_x, px_w, rot_x, origin_y, rot_y, px_h = gt
    assert (origin_x, origin_y) == pytest.approx((0.0, 3.0))  # top-left = (xmin, ymax)
    assert px_w == pytest.approx(1.0)
    assert px_h == pytest.approx(-1.0)  # negative: rows run south
    assert (rot_x, rot_y) == (0.0, 0.0)  # no rotation terms: that is the point of resampling


def test_north_up_of_a_rotated_frame_fills_a_larger_box_and_masks_the_corners():
    """A rotated rectangle does not fill its own bounding box, so the
    corners must come back as nodata rather than as the nearest in-frame
    value -- clamping there would smear a real edge across empty ground."""
    frame, values = _ramp_frame(azimuth=45.0)
    out, _ = to_north_up(values, frame)
    assert out.shape[0] > 3 and out.shape[1] > 4  # the box grew
    assert np.isnan(out[0, 0])  # a corner of the box the frame never reaches
    finite = out[np.isfinite(out)]
    assert finite.size > 0
    assert set(np.unique(finite)) <= set(values.ravel())  # only real cell values, never blended


def test_north_up_never_invents_a_value_outside_the_frame():
    frame, values = _ramp_frame(azimuth=30.0)
    out, _ = to_north_up(values, frame)
    assert np.isnan(out).any()  # there ARE outside cells at this azimuth
    assert np.isfinite(out).any()


def test_north_up_rejects_values_that_do_not_match_the_frame():
    frame, _ = _ramp_frame()
    with pytest.raises(ValueError):
        to_north_up(np.zeros((2, 2)), frame)


def test_north_up_carries_nodata_through_unchanged():
    frame, values = _ramp_frame()
    values = values.copy()
    values[1, 1] = np.nan
    out, _ = to_north_up(values, frame)
    assert np.isnan(out[1, 1])  # row 1 of 3 is its own mirror image
    assert np.isfinite(out[0]).all()


def test_north_up_of_an_axis_aligned_frame_has_exactly_the_frames_shape():
    """At spec 6.4's realistic 0.10 m cells the span `(xmax - xmin) / cell`
    is an exact integer mathematically and `n + 4e-15` in floating point,
    so a plain ceil() adds a phantom all-nodata row and column. The
    fixture used by the other north-up tests has cell=1.0, where the
    arithmetic is exact, and so cannot see this."""
    for nx, ny, cell in ((29, 12, 0.1), (23, 19, 0.05), (7, 3, 0.2), (13, 11, 1.0)):
        frame = CubeFrame(
            origin=(500000.0, 4500000.0),
            azimuth=0.0,
            cell=cell,
            nx=nx,
            ny=ny,
            crs="EPSG:32633",
        )
        values = np.arange(ny * nx, dtype=float).reshape(ny, nx)
        out, _ = to_north_up(values, frame)
        assert out.shape == (ny, nx), f"{nx}x{ny} at cell={cell} gained a phantom row/column"
        np.testing.assert_allclose(out, values[::-1])
