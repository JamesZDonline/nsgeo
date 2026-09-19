from __future__ import annotations

import numpy as np
import pytest
from nsgeo.slices.binning import PreparedLine, build_cube, plan_line, stream_slice
from nsgeo.slices.cube import Provenance
from nsgeo.slices.frame import CubeFrame, ZAxis


def prov():
    return Provenance(
        line_keys=(),
        preset_name="p",
        steps=(),
        transform="amp_abs",
        velocity=None,
        built_utc="2026-09-18T00:00:00Z",
        core_version="0.1.0.dev0",
    )


def make_survey(seed=0, n_lines=6, n_traces=40, n_samples=64):
    rng = np.random.default_rng(seed)
    lines = []
    for i in range(n_lines):
        data = rng.normal(size=(n_samples, n_traces)).astype(np.float32)
        xs = np.linspace(0.05, 5.95, n_traces)
        coords = np.column_stack([xs, np.full(n_traces, 0.25 + i * 0.5)])
        lines.append(
            PreparedLine(key=f"l{i}", data=np.abs(data), dt_ns=0.5, t0_ns=0.0, coords=coords)
        )
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=0.2, nx=30, ny=16, crs="EPSG:32633")
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=n_samples)
    return lines, frame, z


def test_streaming_a_window_equals_slicing_a_resident_cube():
    """The load-bearing property: the two paths are one algorithm, so the
    default residency cannot quietly disagree with the pinned one."""
    lines, frame, z = make_survey()
    plans = [plan_line(ln, frame, z) for ln in lines]
    cube = build_cube(lines, plans, frame, z, prov())
    for k0, k1 in ((0, 1), (4, 12), (30, 64)):
        streamed, _ = stream_slice(lines, plans, frame, z, k0, k1)
        np.testing.assert_allclose(streamed, cube.slice_levels(k0, k1), rtol=1e-5, atol=1e-6)


def test_streaming_coverage_equals_the_cube_coverage():
    lines, frame, z = make_survey()
    plans = [plan_line(ln, frame, z) for ln in lines]
    cube = build_cube(lines, plans, frame, z, prov())
    _, cov = stream_slice(lines, plans, frame, z, 3, 9)
    np.testing.assert_array_equal(cov, cube.coverage())


def test_streaming_marks_empty_cells_nan():
    lines, frame, z = make_survey()
    plans = [plan_line(ln, frame, z) for ln in lines]
    values, cov = stream_slice(lines, plans, frame, z, 0, 4)
    assert np.isnan(values[cov == 0]).all()
    assert np.isfinite(values[cov > 0]).all()


def test_streaming_rejects_an_inverted_window():
    lines, frame, z = make_survey()
    plans = [plan_line(ln, frame, z) for ln in lines]
    with pytest.raises(ValueError, match="level window"):
        stream_slice(lines, plans, frame, z, 5, 5)
