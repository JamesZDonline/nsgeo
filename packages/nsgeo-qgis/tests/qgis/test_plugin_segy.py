"""A SEG-Y line end to end in the plugin (M21c, spec §15).

The core reads a SEG-Y line through `nsgeo.io`'s dispatcher, so nothing here
is SEG-Y-specific code: these pin that the plugin's paths (profile,
processing, save and reopen, slices, the facts line) really reach it, with
float samples and a static shift undone.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io import SegyHeader
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.slices import SliceWindow
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import Resolution, SourceChoice
from nsgeo_qgis.ui.add_step_dialog import AddStepDialog, header_facts
from nsgeo_qgis.ui.profile_dock import ProfileDock
from plugin_testing import synthetic_segy

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 16.0, "EPSG:32616", 0.5)
STATICS = [700] + [5, 9, 14, 20, 25] * 5 + [3] * 3


@pytest.fixture
def segy_site(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_segy(tmp_path / "raw", "LINE01.sgy", n_traces=29, statics_ns=STATICS)
    line = Line.open(p, GridPlacement("A", "y", 0.25, 0.0, 1, "LINE01"))
    session.add_lines([line])
    key = session.keys()[0]
    yield session, dock, key, line, tmp_path
    dock.hide()
    dock.deleteLater()


def test_a_segy_line_draws_its_profile_at_the_undone_length(segy_site):
    session, dock, key, line, _ = segy_site
    session.open_line(key)
    assert isinstance(line.header, SegyHeader) and line.header.stored_samples > 2000
    assert dock.view.transform.n_traces == 29 and dock.view.transform.n_samples == 500
    assert dock.view.transform.t0_ns == pytest.approx(-11.766)
    session.set_profiles(key, line.load())
    assert dock.image is not None and dock.image.rg.n_samples == 500


def test_a_segy_line_takes_steps_and_comes_back_after_save_and_reopen(segy_site):
    session, _, key, line, _ = segy_site
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
    assert isinstance(reopened.header, SegyHeader) and reopened.n_traces == 29
    data = reopened.load()[0].data
    assert data.dtype == np.float32
    np.testing.assert_array_equal(data, line.load()[0].data)
    assert again.stack_for(key).to_dicts() == saved
    again.close_site()


def test_segy_lines_slice_through_the_engine(qgis_app, tmp_path):
    """Float samples through preparation, a slice and the cube a cut reads (C5)."""
    session = SiteSession()
    session.new_site(tmp_path)
    # A SEG-Y header has no dielectric (epsr 0), so the grid carries the
    # velocity, as the import's note asks the user to set.
    session.add_grid(
        Grid(
            "B",
            (500.0, 700.0),
            0.0,
            6.0,
            6.0,
            "EPSG:32616",
            0.5,
            velocity=VelocityModel.constant(0.1),
        )
    )
    lines = []
    for i in range(4):
        p = synthetic_segy(
            tmp_path / "raw",
            f"LINE0{i + 1}.sgy",
            n_traces=60,
            statics_ns=[650] + [i * 3] * 59,
            x_mm=[83 * k for k in range(60)],
        )
        lines.append(Line.open(p, GridPlacement("B", "y", 1.0 + i, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = [
        {"step": "time_zero", "params": {}, "enabled": True},
        {"step": "dewow", "params": {}, "enabled": True},
        {"step": "gain_agc", "params": {}, "enabled": True},
    ]
    errors: list[str] = []
    engine = SliceEngine(session, on_prepared=lambda: None, on_error=errors.append)
    try:
        engine.set_source(
            SourceChoice(
                grid_id="B",
                preset="p",
                transform="amp_envelope",
                line_keys=tuple(session.keys()),
            )
        )
        assert engine.wait_for_preparation(20_000), "preparation did not finish"
        engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
        assert errors == [] and engine.line_count == 4
        values, coverage = engine.slice_at(SliceWindow(4, 14))
        covered = values[coverage > 0]
        assert covered.size > 0 and np.isfinite(covered).all()
        cube = engine.cube()
        assert cube.blocks and all(np.isfinite(b.mean).all() for b in cube.blocks)
    finally:
        engine.dispose()


def test_the_facts_line_names_the_format(segy_site):
    _, _, _, line, _ = segy_site
    assert header_facts(line.header).startswith(
        "From this file's header: SEG-Y · antenna ? · sample interval 0.4060 ns"
    )
    d = AddStepDialog("bandpass", header=line.header)
    assert "SEG-Y" in d.facts.text()
