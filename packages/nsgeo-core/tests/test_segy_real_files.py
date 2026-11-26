"""The SEG-Y reader on real RadExplorer exports (M21c; spec §2, measured 2026-11-25).

The files are gitignored (tests/data/local/segy), so on CI these skip. They
assert counts, intervals, times, sample indices and metres only: never a
coordinate, and the geographic flag only as a count.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io import read_header, read_samples, trace_count

from tests.real_data import SEGY, SEGY_DIR

COUNTS = {
    "LINE01": 517,
    "LINE02": 524,
    "LINE03": 487,
    "LINE04": 587,
    "LINE05": 761,
    "LINE06": 758,
    "LINE07": 946,
    "LINE08": 387,
    "LINE09": 572,
    "LINE10": 445,
    "LINE11": 351,
    "LINE12": 1217,
    "LINE13": 316,
    "LINE14": 316,
    "LINE15": 384,
    "LINE16": 242,
    "LINE17": 293,
    "LINE18": 292,
}
#: 344 recorded samples a trace; the rest have 424.
SHORT = {"LINE01", "LINE02", "LINE03", "LINE04", "LINE05", "LINE06", "LINE07"}

needs_segy = pytest.mark.skipif(not SEGY, reason="no segy survey in tests/data/local")


@needs_segy
def test_segy_lines_read_with_their_counts_samples_and_spacing():
    assert {p.stem: read_header(p).n_traces for p in SEGY} == COUNTS
    for p in SEGY:
        h = read_header(p)
        assert trace_count(p, h) == h.n_traces
        assert h.n_samples == (344 if p.stem in SHORT else 424), p.stem
        assert h.stored_samples > 2000 and h.dt_ns == pytest.approx(0.406)
        assert h.step_m == pytest.approx(0.06844, abs=2e-5), p.stem
        assert h.geographic_traces == h.n_traces
        assert h.max_static_ns > 0
        assert h.notes[0] == (
            f"its traces carry a static shift of up to {h.max_static_ns:g} ns: "
            f"read as recorded, without it"
        )
        assert len(h.notes) == (2 if p.stem == "LINE04" else 1), p.stem
    assert read_header(SEGY_DIR / "LINE02.sgy").position_ns == pytest.approx(-9.766)
    assert read_header(SEGY_DIR / "LINE12.sgy").position_ns == pytest.approx(-11.766)
    assert read_header(SEGY_DIR / "LINE08.sgy").max_static_ns == 836


@needs_segy
def test_line04s_jumps_are_a_note_and_it_stays_evenly_spaced():
    h = read_header(SEGY_DIR / "LINE04.sgy")
    assert h.jumps == 2 and h.traces_per_metre == pytest.approx(1 / 0.06844, rel=1e-3)
    assert h.notes[1] == (
        "its trace coordinates jump at 2 traces, the largest 3.15 m at trace 586: "
        "placed at an even 0.06844 m"
    )


@needs_segy
def test_every_sample_is_live_once_the_static_is_undone():
    for p in SEGY:
        s = read_samples(p)
        assert s.dtype == np.float32 and s.shape == (1, read_header(p).n_samples, COUNTS[p.stem])
        assert (s != 0).all(), p.stem


@needs_segy
def test_time_zero_is_at_the_direct_wave():
    """The mean trace's first sample past 10 % of its peak, in ns after time
    zero: measured -0.4 to +2.8 (§2). Read as +delay it would be near +24."""
    for p in SEGY:
        h = read_header(p)
        mean = read_samples(p, h)[0].astype(float).mean(axis=1)
        first = int(np.argmax(np.abs(mean) > 0.1 * np.abs(mean).max()))
        t = h.position_ns + first * h.dt_ns
        assert -1.0 <= t <= 3.5, (p.stem, t)
