"""The gap rule against the real GPS surveys (gitignored; skips when absent).

Assertions are trace numbers, steps and counts only: never a coordinate.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.spacing import gap_steps, left_out
from nsgeo.geometry.track import track_from_log
from nsgeo.io import dzg_for, read_dzg, read_header, trace_count

from tests.dzg_data import local_xy
from tests.real_data import GPS_LINES, GRID2_LINES


def _distance(dzt) -> np.ndarray:
    header = read_header(dzt)
    n = trace_count(dzt, header)
    dzg = dzg_for(dzt)
    assert dzg is not None, f"no DZG beside {dzt.name}"
    log = read_dzg(dzg, n)
    first = next(f for f in log.fixes if f.quality == 4)
    track = track_from_log(log, local_xy(first.lat, first.lon), "LOCAL")
    return track.distance_along(n, header)


def _named(lines, stem):
    (found,) = [p for p in lines if p.stem == stem]
    return found


@pytest.mark.skipif(not (GPS_LINES and GRID2_LINES), reason="no real GPS surveys")
def test_the_gps_surveys_lifts_are_gaps_and_their_slips_are_not():
    d28 = _distance(_named(GPS_LINES, "FILE__028"))
    assert gap_steps(d28)[841]  # trace 841 -> 842

    out = left_out(_distance(_named(GPS_LINES, "FILE__016")))
    assert out[355:363].all()
    assert not out[354] and not out[363]

    with_gap = sum(bool(gap_steps(_distance(dzt)).any()) for dzt in [*GPS_LINES, *GRID2_LINES])
    # Measured: 19 of the 120 lines have a gap (the same 19 as §17's fix-to-fix count).
    assert with_gap == 19
