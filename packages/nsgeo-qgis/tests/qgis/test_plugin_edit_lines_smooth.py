"""M21d: a GPS line placed without RTK is smoothed per line from Edit lines
(radar formats spec §16). Coordinates are made up."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry import Grid, GridPlacement
from nsgeo.model.survey import Line
from nsgeo.project import load_site
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.edit_lines_dialog import CHANGED, COL_SMOOTH, EditLinesDialog
from plugin_testing import CRS, LAT0, LON0, M_PER_DEG, open_gps, synthetic_dzt, synthetic_gps_dzt
from qgis.PyQt.QtCore import Qt

GA = Grid("A", (0.0, 0.0), 0.0, 10.0, 30.0, CRS, 0.5)


def _jittery(folder, name):
    """A DGPS-only line walked north, a fix every 10 traces jittering 1 m east-west."""
    fixes = []
    for i, t in enumerate(range(5, 200, 10)):
        east = (1.0 if i % 2 else -1.0) / (M_PER_DEG * np.cos(np.radians(LAT0)))
        fixes.append((t, LAT0 + t * 0.1 / M_PER_DEG, LON0 + east, 2))
    path = synthetic_gps_dzt(folder, name, fixes, n_traces=200, traces_per_metre=10.0)
    return open_gps(path, grid_id="A")


def _rtk(folder, name):
    fixes = [(t, LAT0 + t * 0.1 / M_PER_DEG, LON0 + 2.0 / M_PER_DEG, 4) for t in (25, 175)]
    path = synthetic_gps_dzt(folder, name, fixes, n_traces=200, traces_per_metre=10.0)
    return open_gps(path, grid_id="A")


@pytest.fixture
def site(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.set_site_crs(CRS)
    s.add_grid(GA)
    raw = tmp_path / "raw"
    tape = Line.open(
        synthetic_dzt(raw, "T1.DZT", n_traces=60), GridPlacement("A", "y", 5.0, 0.0, 1, "T1")
    )
    s.add_lines([_jittery(raw, "G1.DZT"), _rtk(raw, "G2.DZT"), tape])
    dialog = EditLinesDialog(s, "A")
    yield s, dialog
    dialog._measurer.shutdown()
    dialog.hide()
    dialog.deleteLater()


def _row(d, name):
    return d.keys().index(f"raw/{name}.DZT")


def _coords(s, name):
    return s.line_for_key(f"raw/{name}.DZT").trace_coords(s.site.frames)


def test_a_line_without_rtk_is_smoothed_from_its_cell_and_back(site):
    s, d = site
    key = "raw/G1.DZT"
    assert s.line_for_key(key).placement.anchor_on == "all"
    raw = _coords(s, "G1").copy()
    row = _row(d, "G1")
    item = d.table.item(row, COL_SMOOTH)
    assert item.text() == "0.0" and item.flags() & Qt.ItemFlag.ItemIsEditable
    item.setText("6")
    assert d.table.item(row, COL_SMOOTH).background().color() == CHANGED
    d.accept()
    assert d.outcome.changed == (key,)
    assert s.line_for_key(key).placement.smooth_m == 6.0
    smoothed = _coords(s, "G1")
    assert np.ptp(smoothed[20:180, 0]) < np.ptp(raw[20:180, 0])

    again = EditLinesDialog(s, "A")
    again.table.item(_row(again, "G1"), COL_SMOOTH).setText("0")
    again.accept()
    np.testing.assert_allclose(_coords(s, "G1"), raw)
    again._measurer.shutdown()
    again.deleteLater()


def test_rtk_and_tape_lines_cannot_be_smoothed(site):
    s, d = site
    for name in ("G2", "T1"):
        item = d.table.item(_row(d, name), COL_SMOOTH)
        assert item.text() == "—"
        assert not item.flags() & Qt.ItemFlag.ItemIsEditable
    # Typed in anyway (as a stray edit would), it springs back and nothing changes.
    d.table.item(_row(d, "G2"), COL_SMOOTH).setText("3")
    assert d.table.item(_row(d, "G2"), COL_SMOOTH).text() == "—"
    assert s.line_for_key("raw/G2.DZT").placement.smooth_m == 0.0


def test_a_bad_smoothing_is_refused_and_a_saved_one_reopens(site):
    s, d = site
    row = _row(d, "G1")
    d.table.item(row, COL_SMOOTH).setText("-1")
    assert d.table.item(row, COL_SMOOTH).text() == "0.0"
    assert "is not a smoothing of 0 m or more; unchanged" in d.status.text()
    d.table.item(row, COL_SMOOTH).setText("2.5")
    d.accept()
    s.save()
    back = load_site(s.json_path)
    smooth = {
        ln.path.name: ln.placement.smooth_m
        for ln in back.lines
        if hasattr(ln.placement, "smooth_m")
    }
    assert smooth["G1.DZT"] == 2.5
