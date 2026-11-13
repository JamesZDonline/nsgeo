"""The DZG reader, on synthetic logs at a made-up place."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from nsgeo.io import DzgError, dzg_for, read_dzg

from tests.dzg_data import gga_body, nmea, write_dzg

FIXES = [(13, 45.2057, 10.5017, 4), (26, 45.2058, 10.5018, 5), (47, 45.2059, 10.5019, 4)]


def test_reads_gssis_and_gga_pairs_in_order(tmp_path: Path):
    log = read_dzg(write_dzg(tmp_path / "x.DZG", FIXES))
    assert [f.trace for f in log.fixes] == [13, 26, 47]
    assert [f.quality for f in log.fixes] == [4, 5, 4]
    assert log.bad_checksum == 0 and log.unpaired == 0
    assert log.n_fixed == 2
    first = log.fixes[0]
    assert first.lat == pytest.approx(45.2057, abs=1e-8)
    assert first.lon == pytest.approx(10.5017, abs=1e-8)
    assert first.alt_m == 120.0 and first.geoid_m == 47.5
    assert first.n_sats == 22 and first.hdop == 0.6
    assert first.utc_s == pytest.approx(16 * 3600 + 39 * 60 + 15.4)
    assert log.fixes[1].utc_s == pytest.approx(first.utc_s + 1.0)


def test_ddmm_decoding_and_hemispheres(tmp_path: Path):
    body = "GNGGA,163915.40,4512.3456789,N,01030.1234567,E,4,22,0.6,120.000,M,47.500,M,1.4,0000"
    p = tmp_path / "x.DZG"
    p.write_text(f"$GSSIS,3,-1\r\n{nmea(body)}\r\n")
    fix = read_dzg(p).fixes[0]
    assert fix.lat == pytest.approx(45 + 12.3456789 / 60)
    assert fix.lon == pytest.approx(10 + 30.1234567 / 60)
    south_west = body.replace(",N,", ",S,").replace(",E,", ",W,")
    p.write_text(f"$GSSIS,3,-1\r\n{nmea(south_west)}\r\n")
    fix = read_dzg(p).fixes[0]
    assert fix.lat == pytest.approx(-(45 + 12.3456789 / 60))
    assert fix.lon == pytest.approx(-(10 + 30.1234567 / 60))


def test_any_talker_reads_as_gga(tmp_path: Path):
    gn = read_dzg(write_dzg(tmp_path / "a.DZG", FIXES))
    gp = read_dzg(write_dzg(tmp_path / "b.DZG", FIXES, talker="GP"))
    assert gp.fixes == gn.fixes


def test_other_sentences_are_ignored(tmp_path: Path):
    p = write_dzg(tmp_path / "x.DZG", FIXES)
    clean = read_dzg(p)
    lines = p.read_text().splitlines()
    lines.insert(2, nmea("GNRMC,163915.40,A,4512.3456789,N,01030.1234567,E,0.0,0.0,131126,,,R"))
    p.write_text("\r\n".join(lines) + "\r\n")
    assert read_dzg(p) == clean


def test_a_bad_checksum_drops_the_sentence_and_counts_it(tmp_path: Path):
    p = tmp_path / "x.DZG"
    good = nmea(gga_body(100.0, 45.2, 10.5, 4))
    bad = good[:-2] + ("00" if not good.endswith("00") else "01")
    p.write_text(f"$GSSIS,5,-1\r\n{good}\r\n$GSSIS,9,-1\r\n{bad}\r\n")
    log = read_dzg(p)
    assert [f.trace for f in log.fixes] == [5]
    assert log.bad_checksum == 1
    assert log.unpaired == 1


def test_a_gga_with_no_preceding_gssis_is_unpaired(tmp_path: Path):
    p = tmp_path / "x.DZG"
    gga = nmea(gga_body(100.0, 45.2, 10.5, 4))
    p.write_text(f"{gga}\r\n$GSSIS,5,-1\r\n{gga}\r\n")
    log = read_dzg(p)
    assert [f.trace for f in log.fixes] == [5]
    assert log.unpaired == 1


def test_a_gga_with_no_position_reads_as_nan_with_its_quality(tmp_path: Path):
    p = tmp_path / "x.DZG"
    p.write_text(f"$GSSIS,8,-1\r\n{nmea('GNGGA,163916.40,,,,,0,0,,,M,,M,,')}\r\n")
    fix = read_dzg(p).fixes[0]
    assert fix.quality == 0
    assert math.isnan(fix.lat) and math.isnan(fix.lon)
    assert fix.n_sats == 0
    assert fix.hdop is None and fix.alt_m is None and fix.geoid_m is None


@pytest.mark.parametrize("second", [12, 40])
def test_trace_numbers_that_do_not_rise_are_refused(tmp_path: Path, second: int):
    p = write_dzg(tmp_path / "x.DZG", [(40, 45.2, 10.5, 4), (second, 45.2, 10.5, 4)])
    with pytest.raises(
        DzgError, match=rf"x\.DZG: trace numbers must rise, but 40 is followed by {second}"
    ):
        read_dzg(p)


def test_a_trace_beyond_the_dzt_is_refused(tmp_path: Path):
    p = write_dzg(tmp_path / "x.DZG", [(10, 45.2, 10.5, 4), (50, 45.2, 10.5, 4)])
    with pytest.raises(DzgError, match=r"names trace 50, but the DZT has 50 traces"):
        read_dzg(p, n_traces=50)
    assert len(read_dzg(p).fixes) == 2


def test_dzg_for_finds_either_case_and_none_when_absent(tmp_path: Path):
    dzt = tmp_path / "a.DZT"
    dzt.write_bytes(b"")
    assert dzg_for(dzt) is None
    (tmp_path / "a.dzg").write_bytes(b"")
    assert dzg_for(dzt) == tmp_path / "a.dzg"
    (tmp_path / "a.DZG").write_bytes(b"")
    found = dzg_for(dzt)
    assert found is not None and found.name in {"a.DZG", "a.dzg"}
