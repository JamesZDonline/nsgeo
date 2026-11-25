"""A MALÅ line end to end in the plugin (M21b, spec §14).

The core reads a MALÅ line through `nsgeo.io`'s dispatcher, so nothing here
is MALÅ-specific code: these pin that the plugin's paths (profile,
processing, save and reopen, the facts line) really reach it.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io import MalaError, MalaHeader
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.add_step_dialog import AddStepDialog, header_facts
from nsgeo_qgis.ui.profile_dock import ProfileDock
from plugin_testing import synthetic_mala

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 16.0, "EPSG:32616", 0.5)


@pytest.fixture
def mala_site(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_mala(tmp_path / "raw", "LINE01.rd7", n_traces=24)
    line = Line.open(p, GridPlacement("A", "y", 0.25, 0.0, 1, "LINE01"))
    session.add_lines([line])
    key = session.keys()[0]
    yield session, dock, key, line, tmp_path
    dock.hide()
    dock.deleteLater()


def test_a_mala_line_draws_its_profile_from_its_own_header(mala_site):
    session, dock, key, line, _ = mala_site
    session.open_line(key)
    assert isinstance(line.header, MalaHeader)
    assert dock.view.transform.n_traces == 24 and dock.view.transform.n_samples == 500
    assert dock.view.transform.t0_ns == 0.0
    session.set_profiles(key, line.load())
    assert dock.image is not None and dock.image.rg.n_samples == 500


def test_a_mala_line_takes_steps_and_comes_back_after_save_and_reopen(mala_site):
    session, _, key, line, _ = mala_site
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
    assert isinstance(reopened.header, MalaHeader) and reopened.n_traces == 24
    np.testing.assert_array_equal(reopened.load()[0].data, line.load()[0].data)
    assert again.stack_for(key).to_dicts() == saved
    again.close_site()


def test_a_mala_line_whose_rad_went_missing_stops_the_site_opening_with_why(mala_site):
    session, _, _, line, _ = mala_site
    session.save()
    json_path = session.json_path
    session.close_site()
    line.path.with_suffix(".rad").unlink()
    again = SiteSession()
    with pytest.raises(MalaError, match=r"^no LINE01\.rad beside it$"):
        again.open_site(json_path)
    assert not again.is_open


def test_the_facts_line_names_the_format(mala_site):
    _, _, _, line, _ = mala_site
    assert header_facts(line.header).startswith(
        "From this file's header: MALÅ · antenna GX450 HDR (v.1) · sample interval "
    )
    d = AddStepDialog("bandpass", header=line.header)
    assert "MALÅ" in d.facts.text()
