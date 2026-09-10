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
