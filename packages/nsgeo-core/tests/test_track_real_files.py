"""TrackPlacement against the real GPS surveys (gitignored; skips when absent).

Assertions are lengths, counts, trace numbers and bridge metres only: never a
coordinate. Each line is projected about its own first fix, read at run time.
"""

from __future__ import annotations

import pytest
from nsgeo.geometry.track import END_LIMIT_M, TrackPlacement, track_from_log
from nsgeo.io import dzg_for, read_dzg, read_header, trace_count

from tests.dzg_data import local_xy
from tests.real_data import GPS_LINES, GRID2_LINES


def _line(dzt) -> tuple[TrackPlacement, int, object]:
    header = read_header(dzt)
    n = trace_count(dzt, header)
    dzg = dzg_for(dzt)
    assert dzg is not None, f"no DZG beside {dzt.name}"
    log = read_dzg(dzg, n)
    first = next(f for f in log.fixes if f.quality == 4)
    return track_from_log(log, local_xy(first.lat, first.lon), "LOCAL"), n, header


def _named(lines, stem):
    (found,) = [p for p in lines if p.stem == stem]
    return found


@pytest.mark.skipif(not GPS_LINES, reason="no real GPS survey")
def test_file_011_is_placed_along_its_whole_walk():
    track, n, header = _line(_named(GPS_LINES, "FILE__011"))
    assert n == 1560
    assert n / header.traces_per_metre == pytest.approx(26.0, abs=0.05)
    d = track.distance_along(n, header)
    assert 29.5 < d[-1] - d[0] < 31.0


@pytest.mark.skipif(not GRID2_LINES, reason="no real second survey")
def test_the_second_surveys_dropouts_are_bridged():
    expected = {"FILE__039": (149, 246, 1.83), "FILE__042": (1739, 1755, 0.39)}
    seen = set()
    for dzt in GRID2_LINES:
        track = _line(dzt)[0]
        bridges = track.bridges()
        if dzt.stem in expected:
            first, last, metres = expected[dzt.stem]
            assert len(bridges) == 1, dzt.name
            assert (bridges[0].first_trace, bridges[0].last_trace) == (first, last)
            assert bridges[0].metres == pytest.approx(metres, abs=0.02)
            seen.add(dzt.stem)
        else:
            assert bridges == (), dzt.name
    assert seen == set(expected)


@pytest.mark.skipif(not GPS_LINES, reason="no real GPS survey")
def test_every_first_survey_line_starts_close_to_its_first_fix_and_ends_at_its_last():
    assert len(GPS_LINES) == 60
    for dzt in GPS_LINES:
        track, n, header = _line(dzt)
        start, end = track.end_runs(n, header)
        assert 0.0 <= start <= 0.70, dzt.name
        assert 0.0 <= end <= 0.05, dzt.name
        assert max(start, end) < END_LIMIT_M
