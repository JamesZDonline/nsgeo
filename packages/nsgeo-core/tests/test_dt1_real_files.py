"""The DT1 reader on real pulseEKKO files (M21a; spec §2, measured 2026-11-24).

The files are gitignored (tests/data/local/dt1-a and dt1-b), so on CI these
skip. They assert counts, intervals, sample indices and metres only, never a
coordinate.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io import read_header, read_samples, trace_count
from nsgeo.io.dt1 import Dt1Error

from tests.real_data import DT1_A, DT1_B

A = {p.stem: p for p in DT1_A}
B = {p.stem: p for p in DT1_B}

needs_a = pytest.mark.skipif(not DT1_A, reason="no dt1-a survey in tests/data/local")
needs_b = pytest.mark.skipif(not DT1_B, reason="no dt1-b survey in tests/data/local")


def _peak_after_time_zero(samples: np.ndarray, position_ns: float, dt_ns: float) -> float:
    """Samples from the header's time zero to the direct wave's envelope peak.

    The peak of the mean |amplitude| across the line is a steadier mark than
    a threshold on its rise, which varies with how fast the wave rises."""
    envelope = np.abs(samples.astype(float)).mean(axis=1)
    return int(np.argmax(envelope)) - (-position_ns / dt_ns)


@needs_a
def test_dt1_a_lines_read_with_their_counts_and_spacing():
    counts = {s: read_header(p).n_traces for s, p in A.items() if s.startswith("LINE")}
    assert counts == {"LINE00": 223, "LINE01": 46, "LINE02": 275, "LINE03": 360, "LINE04": 445}
    for stem, p in A.items():
        h = read_header(p)
        assert trace_count(p, h) == h.n_traces and h.bytes_per_sample == 2
        assert h.dt_ns == pytest.approx(0.4) and h.n_samples == 1000
        assert h.antenna == "100 MHz"
        if stem.startswith("LINE"):
            assert h.traces_per_metre == pytest.approx(4.0)
            assert h.notes == () and h.not_a_profile == ""


@needs_a
@pytest.mark.parametrize("stem", ["LINE00", "LINE01", "LINE02", "LINE03", "LINE04"])
def test_dt1_a_time_zero_is_just_before_the_direct_wave(stem):
    p = A[stem]
    h = read_header(p)
    samples = read_samples(p, h)
    assert samples.shape == (1, 1000, h.n_traces)
    # Measured: the peak follows the .HD's time zero by 0.5 (LINE02) to 3.5 (LINE00) samples.
    assert 0 <= _peak_after_time_zero(samples[0], h.position_ns, h.dt_ns) <= 4


@needs_a
def test_dt1_a_cmp_is_a_sounding():
    h = read_header(A["CMP"])
    assert h.not_a_profile == "a CMP/WARR velocity sounding, not a profile"
    assert h.n_traces == 40 and h.traces_per_metre == pytest.approx(2.0)


@needs_b
def test_dt1_b_reads_its_merged_line():
    p = B["yyline3"]
    h = read_header(p)
    assert (h.n_traces, h.n_samples, h.bytes_per_sample) == (391, 500, 2)
    assert h.dt_ns == pytest.approx(0.8) and h.traces_per_metre == pytest.approx(4.0)
    assert h.notes == () and h.not_a_profile == ""
    samples = read_samples(p, h)
    # Measured: the peak follows the .HD's time zero by 2.1 samples.
    assert 0 <= _peak_after_time_zero(samples[0], h.position_ns, h.dt_ns) <= 4


@needs_b
def test_dt1_b_refuses_the_cmp_with_no_hd():
    with pytest.raises(Dt1Error, match=r"^no CMP\.HD beside it$"):
        read_header(B["CMP"])
