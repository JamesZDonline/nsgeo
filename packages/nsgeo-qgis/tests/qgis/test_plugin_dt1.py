"""A Sensors & Software DT1 line end to end in the plugin (M21a, spec §6).

The core reads a DT1 through `nsgeo.io`'s dispatcher, so nothing here is
DT1-specific code: these pin that the plugin's paths (profile, processing,
save and reopen, the facts line) really reach it.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io import Dt1Error, Dt1Header
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.add_step_dialog import AddStepDialog, header_facts
from nsgeo_qgis.ui.profile_dock import ProfileDock
from plugin_testing import synthetic_dt1

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 16.0, "EPSG:32616", 0.5)


@pytest.fixture
def dt1_site(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dt1(tmp_path / "raw", "LINE01.DT1", n_traces=48, timezero_point=20.0)
    line = Line.open(p, GridPlacement("A", "y", 0.25, 0.0, 1, "LINE01"))
    session.add_lines([line])
    key = session.keys()[0]
    yield session, dock, key, line, tmp_path
    dock.hide()
    dock.deleteLater()


def test_a_dt1_line_draws_its_profile_from_its_own_header(dt1_site):
    session, dock, key, line, _ = dt1_site
    session.open_line(key)
    assert isinstance(line.header, Dt1Header)
    assert dock.view.transform.n_traces == 48 and dock.view.transform.n_samples == 500
    assert dock.view.transform.t0_ns == pytest.approx(-20.0 * 100.0 / 500)
    session.set_profiles(key, line.load())
    assert dock.image is not None and dock.image.rg.n_samples == 500


def test_a_dt1_line_takes_steps_and_comes_back_after_save_and_reopen(dt1_site):
    session, _, key, line, tmp_path = dt1_site
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow", window_ns=4.0))
    saved = session.stack_for(key).to_dicts()
    session.save()
    json_path = session.json_path
    session.close_site()

    again = SiteSession()
    again.open_site(json_path)
    assert again.keys() == [key]
    reopened = again.line_for_key(key)
    assert isinstance(reopened.header, Dt1Header) and reopened.n_traces == 48
    np.testing.assert_array_equal(reopened.load()[0].data, line.load()[0].data)
    assert again.stack_for(key).to_dicts() == saved
    again.close_site()


def test_a_dt1_whose_hd_went_missing_stops_the_site_opening_with_why(dt1_site):
    session, _, _, line, _ = dt1_site
    session.save()
    json_path = session.json_path
    session.close_site()
    line.path.with_suffix(".HD").unlink()
    again = SiteSession()
    with pytest.raises(Dt1Error, match=r"^no LINE01\.HD beside it$"):
        again.open_site(json_path)
    assert not again.is_open  # nothing installed, as for a missing DZT


def test_the_facts_line_names_the_format(dt1_site):
    _, _, _, line, _ = dt1_site
    assert header_facts(line.header).startswith(
        "From this file's header: Sensors & Software DT1 · antenna 100 MHz · sample interval "
    )
    d = AddStepDialog("bandpass", header=line.header)
    assert "Sensors & Software DT1" in d.facts.text()
