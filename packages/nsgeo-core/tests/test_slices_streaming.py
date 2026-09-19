from __future__ import annotations

import dataclasses

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
    # A re-shot pass over line 1's track, at a DIFFERENT trace spacing: a
    # real cross-hatched or re-occupied survey lands two different lines'
    # traces -- in different numbers -- in the same cell. Every line above
    # sits at its own y, so every cell is touched by exactly one line; a
    # binner that pools each line's own mean before combining across lines,
    # instead of pooling every trace by its true count, agrees with the
    # correct one everywhere above and diverges only here.
    collide_with = 1  # line index whose y this repeat pass shares
    n_repeat = n_traces - 5
    repeat_data = rng.normal(size=(n_samples, n_repeat)).astype(np.float32)
    repeat_y = 0.25 + collide_with * 0.5
    repeat_coords = np.column_stack(
        [np.linspace(0.05, 5.95, n_repeat), np.full(n_repeat, repeat_y)]
    )
    lines.append(
        PreparedLine(
            key="l_repeat", data=np.abs(repeat_data), dt_ns=0.5, t0_ns=0.0, coords=repeat_coords
        )
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


def test_streaming_rejects_a_plan_built_for_a_different_z_axis():
    """`resample_window` slices `plan.z_index[k0:k1]`, which silently
    yields fewer than `k1 - k0` rows if the plan was built against a
    shorter axis -- `.sum(axis=0)` swallows the shortfall and `count` is
    still multiplied by the requested level count, diluting the mean with
    no error. `build_cube` raises on the same stale-plan input (the
    z-major `total` array's shape no longer broadcasts against the block),
    so streaming must raise too rather than quietly dim the picture."""
    lines, frame, _ = make_survey(n_samples=64)
    short_z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=16)
    long_z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=32)
    plans = [plan_line(ln, frame, short_z) for ln in lines]
    with pytest.raises(ValueError, match="plan is stale"):
        stream_slice(lines, plans, frame, long_z, 0, 32)


def test_streaming_accumulates_counts_without_int32_overflow():
    """A single cell whose count is large enough that int32 accumulation
    of `plan.counts * n_levels` wraps negative before this function ever
    gets a chance to narrow the dtype. Coverage must still come back
    correct and positive: counts are accumulated in int64 throughout and
    narrowed to int32 only on the final return.

    A real per-cell trace count this large never occurs; `plan.counts` is
    fabricated from a real plan to reach it cheaply rather than binning
    billions of synthetic traces.
    """
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=1.0, nx=2, ny=2, crs="EPSG:32633")
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=8)
    line = PreparedLine(
        key="l0",
        data=np.zeros((8, 1), dtype=np.float32),
        dt_ns=1.0,
        t0_ns=0.0,
        coords=np.array([[0.5, 0.5]]),
    )
    plan = plan_line(line, frame, z)
    huge = np.full(plan.counts.shape, 2**29, dtype=np.int32)
    plan = dataclasses.replace(plan, counts=huge)
    _, cov = stream_slice([line], [plan], frame, z, 0, 6)
    touched = cov[cov != 0]
    assert touched.size == 1
    assert touched[0] == 2**29
