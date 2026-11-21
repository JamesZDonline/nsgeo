"""M17c (#134): the profile draws a real GPS line at true distance.

Real-data tier: reads tests/data/local (gitignored) and asserts only on trace
indices, widths, counts and metres along a line, never a coordinate.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry import track_from_log
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io import dzg_for, read_dzg, read_header, trace_count
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.processing.migration import MigrateFk
from nsgeo_qgis.session import SiteSession, source_radargram
from nsgeo_qgis.ui.profile_dock import ProfileDock
from plugin_testing import CRS
from tests.dzg_data import local_xy
from tests.real_data import CAMPUS_LINES, GPS_LINES

needs_gps = pytest.mark.skipif(not GPS_LINES, reason="needs the with-dzg lines in tests/data/local")


def _gps_line(stem: str) -> Line:
    (path,) = [p for p in GPS_LINES if p.stem == stem]
    header = read_header(path)
    n = trace_count(path, header)
    log = read_dzg(dzg_for(path), n)
    first = next(f for f in log.fixes if f.quality == 4)
    placement = track_from_log(log, local_xy(first.lat, first.lon), CRS)
    return Line.open(path, placement)


@pytest.fixture
def shown(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.set_site_crs(CRS)

    def show(line: Line):
        session.add_lines([line])
        key = session.keys()[0]
        session.open_line(key)
        session.set_profiles(key, line.load())
        return dock.view.transform

    yield session, dock, show
    dock.hide()
    dock.deleteLater()


@needs_gps
def test_file016s_lift_is_one_gap_in_its_profile(shown):
    session, dock, show = shown
    t = show(_gps_line("FILE__016"))
    axis = t.axis
    assert axis is not None
    lo, hi = axis.drawn()
    assert np.all(hi[355:363] == lo[355:363])  # zero drawn width
    assert hi[354] > lo[354] and hi[363] > lo[363]  # the lift's edges are drawn
    middle = 0.5 * (hi[354] + lo[363])
    assert t.trace_at(t.x_of_walk(float(middle))) is None
    assert t.trace_at(t.x_of_walk(float(hi[354]) - 1e-3)) == 354
    assert t.trace_at(t.x_of_walk(float(lo[363]) + 1e-3)) == 363


@needs_gps
def test_file028s_lift_has_no_traces_left_out(shown):
    session, dock, show = shown
    t = show(_gps_line("FILE__028"))
    lo, hi = t.axis.drawn()
    assert np.all(hi[830:850] > lo[830:850])  # every trace around the lift drawn
    gaps = np.diff(t.axis.distance)
    assert gaps[841] > 6 * np.median(gaps)  # trace 841 to 842 is a gap
    mid = 0.5 * (hi[841] + lo[842])
    assert t.trace_at(t.x_of_walk(float(mid))) is None


@pytest.mark.skipif(not CAMPUS_LINES, reason="needs the campus lines in tests/data/local")
def test_a_tape_lines_profile_gets_no_axis(shown):
    session, dock, show = shown
    session.add_grid(Grid("A", (500.0, 700.0), 0.0, 12.0, 12.0, "EPSG:32632", 0.5))
    (path,) = [p for p in CAMPUS_LINES if p.stem == "FILE__007"]
    t = show(Line.open(path, GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__007")))
    assert t.axis is None


@needs_gps
def test_file016_migrates_at_true_spacing(shown):
    line = _gps_line("FILE__016")
    rg = build_step("time_zero", mode="first_break").apply(source_radargram(line, line.load()[0]))
    assert rg.trace_x_m is not None
    out = MigrateFk(0.1).apply(rg)
    assert out.data.shape == rg.data.shape
    assert np.all(np.isfinite(out.data))
    rms = np.sqrt(np.mean(out.data**2, axis=0))
    left = np.mean(rms[349:354])  # five drawn traces before the lift
    right = np.mean(rms[364:369])  # five drawn traces after it
    for edge, neighbours in ((354, left), (363, right)):
        assert neighbours / 2 <= rms[edge] <= neighbours * 2, edge
