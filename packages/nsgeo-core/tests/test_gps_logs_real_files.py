"""GPS logs from the real MALÅ and SEG-Y surveys (M21d; spec §2, measured 2026-11-25).

The files are gitignored, so on CI these skip. They assert counts, quality
values, trace numbers and length ratios only: never a latitude, a longitude or a
projected coordinate, and a failure prints none (each assertion is on a derived
number, labelled by line name).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from nsgeo.geometry.track import gps_length_note, track_from_log
from nsgeo.io import QUALITY_UNKNOWN, read_gps, read_header, trace_count

from tests.real_data import MALA, SEGY

MALA_FIXES = {
    "DAT_0320": 1800,
    "DAT_0321": 283,
    "DAT_0323": 1124,
    "DAT_0326": 594,
    "DAT_0327": 347,
    "DAT_0328": 212,
    "DAT_0329": 608,
    "DAT_0330": 248,
}
#: The first trace of each run of equal positions, measured 2026-11-25.
SEGY_FIXES = {
    "LINE01": 308,
    "LINE02": 283,
    "LINE03": 213,
    "LINE04": 266,
    "LINE05": 363,
    "LINE06": 365,
    "LINE07": 790,
    "LINE08": 325,
    "LINE09": 427,
    "LINE10": 360,
    "LINE11": 280,
    "LINE12": 1006,
    "LINE13": 258,
    "LINE14": 253,
    "LINE15": 362,
    "LINE16": 100,
    "LINE17": 172,
    "LINE18": 189,
}
#: The MALÅ lines whose GPS track runs more than 20 % longer than their wheel.
MALA_LONG = {"DAT_0320", "DAT_0321", "DAT_0323"}

needs_mala = pytest.mark.skipif(not MALA, reason="no mala survey in tests/data/local")
needs_segy = pytest.mark.skipif(not SEGY, reason="no segy survey in tests/data/local")


def _read(path):
    header = read_header(path)
    n = trace_count(path, header)
    return header, n, read_gps(path, header, n)


def _local(log):
    """A flat projection about the log's own first fix: metres, never asserted on."""
    lat0 = log.fixes[0].lat
    lon0 = log.fixes[0].lon
    c = math.cos(math.radians(lat0))

    def to_xy(lon, lat):
        return (np.asarray(lon) - lon0) * 111_320.0 * c, (np.asarray(lat) - lat0) * 111_320.0

    return to_xy


@needs_mala
def test_every_mala_cor_reads_with_its_fixes_inside_the_line():
    counts = {}
    for p in MALA:
        header, n, log = _read(p)
        counts[p.stem] = len(log.fixes)
        assert {f.quality for f in log.fixes} <= {1, 2}, p.stem
        assert all(0 <= f.trace < n for f in log.fixes), p.stem
        assert log.n_fixed == 0, p.stem
        track = track_from_log(log, _local(log), "LOCAL")
        assert track.anchor_on == "all", p.stem
    assert counts == MALA_FIXES


@needs_segy
def test_every_segy_line_has_a_log_of_its_change_points():
    counts = {}
    for p in SEGY:
        header, n, log = _read(p)
        counts[p.stem] = len(log.fixes)
        assert {f.quality for f in log.fixes} == {QUALITY_UNKNOWN}, p.stem
        assert all(0 <= f.trace < n for f in log.fixes), p.stem
        assert track_from_log(log, _local(log), "LOCAL").anchor_on == "all", p.stem
    assert counts == SEGY_FIXES


@needs_mala
@needs_segy
def test_the_length_note_flags_every_segy_line_and_three_mala_lines():
    flagged = set()
    for p in MALA + SEGY:
        header, _, log = _read(p)
        if gps_length_note(log, _local(log), header) is not None:
            flagged.add(p.stem)
    assert flagged == MALA_LONG | set(SEGY_FIXES)
