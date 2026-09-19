from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.binning import CoverageError, PreparedLine, build_cube, plan_line
from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis


def frame(nx=4, ny=3, cell=1.0):
    return CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=cell, nx=nx, ny=ny, crs="EPSG:32633")


def axis(nz=5, dz=1.0, t0=0.0):
    return ZAxis(t0_ns=t0, dz_ns=dz, nz=nz)


def prov():
    return Provenance(
        line_keys=("a.dzt",),
        preset_name="p",
        steps=(),
        transform="amp_abs",
        velocity=None,
        built_utc="2026-09-18T00:00:00Z",
        core_version="0.1.0.dev0",
    )


def line(key="a.dzt", value=1.0, n_samples=8, xs=(0.5, 1.5, 2.5), y=0.5, dt_ns=1.0, t0_ns=0.0):
    data = np.full((n_samples, len(xs)), value, dtype=np.float32)
    coords = np.column_stack([np.asarray(xs, dtype=float), np.full(len(xs), y)])
    return PreparedLine(key=key, data=data, dt_ns=dt_ns, t0_ns=t0_ns, coords=coords)


def cube_of(lines, f=None, z=None):
    f = f or frame()
    z = z or axis()
    plans = [plan_line(ln, f, z) for ln in lines]
    return build_cube(lines, plans, f, z, prov())


def test_a_constant_line_bins_to_that_constant():
    cube = cube_of([line(value=7.0)])
    got = cube.slice_levels(0, 5)
    np.testing.assert_allclose(got[0, :3], 7.0)


def test_cells_with_no_traces_are_nan_not_zero():
    """Zero is an ordinary amplitude. Absence must be distinguishable."""
    cube = cube_of([line()])
    got = cube.slice_levels(0, 5)
    assert np.isnan(got[1, 0])
    assert np.isnan(got[0, 3])


def test_count_records_traces_per_cell():
    cube = cube_of([line(xs=(0.2, 0.4, 1.5))])
    cov = cube.coverage()
    assert cov[0, 0] == 2
    assert cov[0, 1] == 1
    assert cov[0, 2] == 0


def test_two_lines_in_one_cell_average_rather_than_sum():
    cube = cube_of([line(key="a", value=2.0), line(key="b", value=4.0)])
    np.testing.assert_allclose(cube.slice_levels(0, 5)[0, 0], 3.0)


def test_two_distinct_traces_in_one_cell_average_within_the_line():
    """The within-line reduceat must SUM the cell's segment, not pick one
    column of it: two same-value lines (above) exercise the accumulator
    loop across build_cube calls but never the reduceat itself, since
    every trace in the segment already agrees. Distinct values close the
    gap, and mean x count reconstructing the sum is the exact invariant
    Task 5's fill depends on.
    """
    xs = (0.2, 0.4, 1.5)
    coords = np.column_stack([np.asarray(xs, dtype=float), np.full(len(xs), 0.5)])
    data = np.empty((8, 3), dtype=np.float32)
    data[:, 0] = 2.0
    data[:, 1] = 8.0
    data[:, 2] = 100.0
    ln = PreparedLine(key="a.dzt", data=data, dt_ns=1.0, t0_ns=0.0, coords=coords)
    f, z = frame(), axis()
    cube = build_cube([ln], [plan_line(ln, f, z)], f, z, prov())
    assert cube.coverage()[0, 0] == 2
    np.testing.assert_allclose(cube.slice_levels(0, 5)[0, 0], 5.0)
    np.testing.assert_allclose(cube.mean[0, 0] * cube.count[0], 10.0)


def test_traces_outside_the_frame_are_dropped_not_clipped():
    """Clipping would pile an excluded line onto one border row."""
    cube = cube_of([line(xs=(0.5, 99.0))])
    assert cube.coverage()[0, 0] == 1
    assert cube.coverage().sum() == 1


def test_a_dropped_trace_preceding_kept_ones_does_not_corrupt_the_grid():
    """`order` must remap the sorted-by-cell positions back through `keep`
    to ORIGINAL trace columns. In every other test the dropped trace comes
    last, where a missing remap is numerically invisible (`keep[argsort]`
    and plain `argsort` agree on a prefix). Put it first instead: a bug
    that skips the remap scatters the dropped trace's amplitude into a
    real cell while silently losing a kept one -- the wrong-corner
    failure `frame.py`'s docstring and `test_traces_outside_the_frame_are_
    dropped_not_clipped` both exist to prevent, but only catch when the
    drop comes first.
    """
    xs = (99.0, 0.5, 1.5, 2.5)
    coords = np.column_stack([np.asarray(xs, dtype=float), np.full(len(xs), 0.5)])
    data = np.empty((8, 4), dtype=np.float32)
    data[:, 0] = 999.0  # outside the frame; must never land in any cell
    data[:, 1] = 20.0
    data[:, 2] = 30.0
    data[:, 3] = 40.0
    ln = PreparedLine(key="a.dzt", data=data, dt_ns=1.0, t0_ns=0.0, coords=coords)
    f, z = frame(), axis()
    cube = build_cube([ln], [plan_line(ln, f, z)], f, z, prov())
    row0 = cube.slice_levels(0, 5)[0]
    np.testing.assert_allclose(row0[:3], [20.0, 30.0, 40.0])
    assert np.isnan(row0[3])
    np.testing.assert_array_equal(cube.coverage()[0], [1, 1, 1, 0])


def test_a_line_wholly_outside_the_frame_is_an_error():
    f, z = frame(), axis()
    with pytest.raises(CoverageError, match="no traces inside"):
        plan_line(line(xs=(50.0, 60.0)), f, z)


def test_a_line_whose_time_range_misses_the_window_is_rejected_by_name():
    """Rather than counting a zero-padded level as if it were data."""
    f = frame()
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=40)
    with pytest.raises(CoverageError, match="short.dzt"):
        plan_line(line(key="short.dzt", n_samples=8), f, z)


def test_resampling_interpolates_between_source_samples():
    ln = line(n_samples=4, dt_ns=1.0, xs=(0.5,))
    ln.data[:, 0] = np.array([0.0, 10.0, 20.0, 30.0], dtype=np.float32)
    f = frame()
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=7)
    cube = build_cube([ln], [plan_line(ln, f, z)], f, z, prov())
    column = cube.mean[:, 0]
    np.testing.assert_allclose(column, [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0], rtol=1e-6)


def test_a_line_with_a_different_dt_lands_on_the_same_axis():
    """Files in one grid may differ in dt; the common axis is the point."""
    fine = line(key="fine", n_samples=16, dt_ns=0.5, xs=(0.5,), value=3.0)
    coarse = line(key="coarse", n_samples=8, dt_ns=1.0, xs=(1.5,), value=3.0)
    f, z = frame(), axis(nz=5, dz=1.0)
    plans = [plan_line(fine, f, z), plan_line(coarse, f, z)]
    cube = build_cube([fine, coarse], plans, f, z, prov())
    np.testing.assert_allclose(cube.slice_levels(0, 5)[0, :2], 3.0)


def test_slice_levels_averages_over_the_window():
    ln = line(n_samples=8, xs=(0.5,))
    ln.data[:, 0] = np.arange(8, dtype=np.float32)
    f = frame()
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=8)
    cube = build_cube([ln], [plan_line(ln, f, z)], f, z, prov())
    assert cube.slice_levels(2, 6)[0, 0] == pytest.approx(3.5)


def test_slice_levels_shape_is_ny_by_nx():
    assert cube_of([line()]).slice_levels(0, 2).shape == (3, 4)


def test_cube_rejects_a_mean_of_the_wrong_shape():
    with pytest.raises(ValueError, match="mean must be"):
        SliceCube(
            frame=frame(),
            z=axis(),
            mean=np.zeros((2, 2), dtype=np.float32),
            count=np.zeros(12, dtype=np.int32),
            provenance=prov(),
        )


def test_provenance_round_trips_through_a_dict():
    p = prov()
    assert Provenance.from_dict(p.to_dict()) == p
