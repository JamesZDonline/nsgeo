"""The DZG reader against the real GPS surveys (gitignored; skips when absent).

Assertions are counts, qualities, trace numbers and file names only.
"""

from __future__ import annotations

import pytest
from nsgeo.io import dzg_for, read_dzg, read_header, trace_count

from tests.real_data import GPS_LINES, GRID2_LINES


def _log(dzt):
    dzg = dzg_for(dzt)
    assert dzg is not None, f"no DZG beside {dzt.name}"
    return dzg, read_dzg(dzg, trace_count(dzt, read_header(dzt)))


@pytest.mark.skipif(not (GPS_LINES and GRID2_LINES), reason="no real GPS surveys")
def test_every_gps_line_has_a_dzg_that_reads_cleanly():
    for dzt in [*GPS_LINES, *GRID2_LINES]:
        dzg, log = _log(dzt)
        assert (log.bad_checksum, log.unpaired) == (0, 0), dzg
        assert log.fixes, dzg


@pytest.mark.skipif(not GPS_LINES, reason="no real GPS survey")
def test_the_first_survey_is_rtk_fixed_throughout():
    fixes = [f for dzt in GPS_LINES for f in _log(dzt)[1].fixes]
    assert len(GPS_LINES) == 60
    assert len(fixes) == 2999
    assert {f.quality for f in fixes} == {4}


@pytest.mark.skipif(not GRID2_LINES, reason="no real second survey")
def test_the_second_survey_has_float_fixes_on_two_lines():
    total = 0
    odd: dict[str, list[int]] = {}
    for dzt in GRID2_LINES:
        dzg, log = _log(dzt)
        total += len(log.fixes)
        bad = [f for f in log.fixes if f.quality != 4]
        if bad:
            assert {f.quality for f in bad} == {5}
            odd[dzg.name] = [f.trace for f in bad]
    assert total == 2523
    assert odd == {"FILE__039.DZG": [190, 212, 239], "FILE__042.DZG": [1753, 1754]}
