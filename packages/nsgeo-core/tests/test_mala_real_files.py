"""The MALÅ reader on real GX450 HDR files (M21b; spec §2, measured 2026-11-25).

The files are gitignored (tests/data/local/mala and mala-edge), so on CI these
skip. They assert counts, intervals, sample indices and metres only, never a
coordinate, and open no .cor.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io import MalaError, read_header, read_samples, trace_count

from tests.real_data import MALA, MALA_EDGE, MALA_RD3

COUNTS = {
    "DAT_0320": 7567,
    "DAT_0321": 1283,
    "DAT_0323": 5301,
    "DAT_0326": 1959,
    "DAT_0327": 973,
    "DAT_0328": 950,
    "DAT_0329": 2549,
    "DAT_0330": 1217,
}
RD7 = {p.stem: p for p in MALA}
RD3 = {p.stem: p for p in MALA_RD3}

needs_mala = pytest.mark.skipif(not MALA, reason="no mala survey in tests/data/local")
needs_edge = pytest.mark.skipif(not MALA_EDGE.is_dir(), reason="no mala-edge in tests/data/local")


@needs_mala
def test_mala_lines_read_with_their_counts_spacing_and_interval():
    assert {stem: read_header(p).n_traces for stem, p in RD7.items()} == COUNTS
    assert set(RD3) == set(COUNTS)
    for p in MALA + MALA_RD3:
        h = read_header(p)
        assert trace_count(p, h) == h.n_traces and h.n_samples == 1511
        assert h.bytes_per_sample == (4 if p.suffix == ".rd7" else 2)
        assert h.dt_ns == pytest.approx(1000 / 5120)
        assert h.range_ns == pytest.approx(295.117188, abs=1e-4)
        assert h.traces_per_metre == pytest.approx(1 / 0.496293) and h.trigger == "distance"
        assert h.antenna == "GX450 HDR (v.1)" and h.position_ns == 0.0
        assert len(h.notes) == 1  # time zero only: the stop/start cross-check agrees


@needs_mala
@pytest.mark.parametrize("stem", ["DAT_0327", "DAT_0328"])  # the two smallest
def test_an_rd3_reads_as_its_rd7_less_its_low_16_bits(stem):
    rd3, rd7 = read_samples(RD3[stem]), read_samples(RD7[stem])
    assert rd3.shape == rd7.shape == (1, 1511, COUNTS[stem])
    np.testing.assert_array_equal(rd3, rd7 & ~np.int32(0xFFFF))


@needs_mala
@pytest.mark.parametrize("stem", sorted(COUNTS))
def test_the_direct_wave_is_well_below_the_first_sample(stem):
    """Measured 43-58: time zero is not at sample 0, which is why every MALÅ
    line comes in with a note asking for a Time zero step, and not at
    SIGNAL POSITION (102.7) either."""
    p = RD3[stem]  # the .rd3, for speed: same picture (the test above)
    envelope = np.abs(read_samples(p)[0].astype(float)).mean(axis=1)
    assert 40 <= int(np.argmax(envelope)) <= 62


@needs_edge
def test_mala_edge_cases_on_real_files():
    with pytest.raises(MalaError, match=r"^no DAT_0328\.rad beside it$"):
        read_header(MALA_EDGE / "DAT_0328.rd7")
    for name in ("DAT_0327.rd3", "DAT_0327.rd7"):
        h = read_header(MALA_EDGE / name)
        assert h.rad_path.name == "DAT_0327.RAD" and h.n_traces == 973
