"""Validation against real survey files.

These files are gitignored: DZT headers can carry GPS and publishing site
locations is not reversible. The suite skips when they are absent, so CI
remains green while local runs get real validation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples, trace_count
from nsgeo.processing import StepStack, build_step
from nsgeo.processing.base import Radargram

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []

pytestmark = pytest.mark.skipif(not FILES, reason="no real DZT files in tests/data/local")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_header_matches_verified_expectations(path):
    h = read_header(path)
    assert h.tag == 2047  # not the widely cited 255
    assert h.data_offset == 131072  # 1024 * rh_data, not the 1024 minimum
    assert h.n_samples == 512
    assert h.bits == 32
    assert h.n_channels == 1
    assert h.antenna == "HS350US"
    assert h.traces_per_metre == pytest.approx(60.0)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_trace_count_is_a_whole_number(path):
    """The diagnostic that caught the wrong header-size assumption."""
    h = read_header(path)
    n = trace_count(path, h)
    assert n > 0
    length_m = n / h.traces_per_metre
    assert 9.0 < length_m < 13.0  # recorded lines are 10.1-11.1 m


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_samples_are_int32_centred_near_zero(path):
    data = read_samples(path)
    assert data.shape[0] == 1
    assert data.dtype == np.int32
    assert abs(float(data.mean())) < 5_000  # real means are around -300
    assert np.abs(data).max() > 1_000_000


@pytest.mark.parametrize("path", FILES[:1], ids=lambda p: p.name)
def test_leading_zero_traces_survive_the_reader(path):
    """Recording starts before the cart moves. Real files begin with zero
    traces, and trimming them would corrupt the distance axis."""
    data = read_samples(path)[0]
    assert not data[:, 0].any()


def test_a_full_stack_runs_on_a_real_profile():
    h = read_header(FILES[0])
    data = read_samples(FILES[0])[0].astype(float)
    rg = Radargram(data=data, dt_ns=h.dt_ns, t0_ns=h.position_ns)

    stack = StepStack()
    stack.source = rg
    stack.append(build_step("time_zero", mode="first_break", threshold=0.25))
    stack.append(build_step("dewow", window_ns=4.0))
    stack.append(build_step("bandpass", low_mhz=100.0, high_mhz=700.0))
    stack.append(build_step("background_sliding", window_traces=200))
    stack.append(build_step("gain_agc", window_ns=20.0))

    out = stack.result()
    assert np.isfinite(out.data).all()
    assert out.n_traces == rg.n_traces
    assert out.n_samples <= rg.n_samples  # time_zero cropped rows
    assert out.t0_ns >= rg.t0_ns

    removed = stack.difference(3)  # what background removal took
    assert removed.data.shape == out.data.shape


def test_a_cube_binned_from_real_files_is_covered_and_finite(tmp_path):
    """End to end on real data: preset, transform, bin, slice, save, reload."""
    from nsgeo.slices.binning import PreparedLine, build_cube, plan_line, stream_slice
    from nsgeo.slices.cube import Provenance
    from nsgeo.slices.frame import CubeFrame, ZAxis
    from nsgeo.slices.store import load_cube, save_cube

    prepared = []
    for i, path in enumerate(FILES[:4]):
        header = read_header(path)
        rg = Radargram(
            data=np.asarray(read_samples(path, header)[0], dtype=float),
            dt_ns=header.dt_ns,
            t0_ns=header.position_ns,
        )
        for name in ("time_zero", "dewow", "background_mean", "gain_agc", "amp_envelope"):
            rg = build_step(name).apply(rg)
        n_traces = rg.data.shape[1]
        coords = np.column_stack(
            [np.linspace(0.0, 19.99, n_traces), np.full(n_traces, 0.25 + i * 0.5)]
        )
        prepared.append(
            PreparedLine(
                key=path.name,
                data=rg.data.astype(np.float32),
                dt_ns=rg.dt_ns,
                t0_ns=rg.t0_ns,
                coords=coords,
            )
        )

    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=0.2, nx=100, ny=12, crs="EPSG:32633")
    z = ZAxis.from_range(1.0, 40.0, 0.2165)
    plans = [plan_line(p, frame, z) for p in prepared]
    prov = Provenance(
        line_keys=tuple(p.key for p in prepared),
        preset_name="test",
        steps=(),
        transform="amp_envelope",
        velocity=None,
        built_utc="2026-09-18T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    cube = build_cube(prepared, plans, frame, z, prov)

    assert cube.coverage().sum() == sum(p.data.shape[1] for p in prepared)
    covered = cube.slice_levels(10, 28)[cube.coverage() > 0]
    assert np.isfinite(covered).all()
    assert (covered >= 0.0).all()  # the envelope is unipolar

    streamed, _ = stream_slice(prepared, plans, frame, z, 10, 28)
    np.testing.assert_allclose(streamed[cube.coverage() > 0], covered, rtol=1e-4, atol=1e-5)

    out = tmp_path / "real.npz"
    save_cube(cube, out)
    reloaded = load_cube(out)
    assert reloaded.provenance == prov
    np.testing.assert_array_equal(reloaded.count, cube.count)
    np.testing.assert_allclose(
        reloaded.slice_levels(10, 28)[cube.coverage() > 0], covered, rtol=1e-4, atol=1e-5
    )
