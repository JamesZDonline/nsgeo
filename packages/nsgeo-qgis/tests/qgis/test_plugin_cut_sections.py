"""`CutSections`: a cut's section from the Slices panel's engines (cut spec §4.3, §4.4)."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest
from nsgeo.slices import finish_section, section_columns
from nsgeo.slices.resample import sample
from nsgeo_qgis import site_engine as site_engine_module
from nsgeo_qgis.cut_sections import NO_CUBE_TEXT, NO_SOURCE_TEXT, CutSection, CutSections
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.slices_dock import SlicesDock
from test_plugin_session import Spy
from test_plugin_site_scope import _close, _open, whole_site
from test_plugin_slices_dock import GRID, GRID_B, PRESET, _line, _ready

H = [(1.0, 1.0), (5.0, 1.0)]  # along x, 4 m


@pytest.fixture
def shown(qgis_app, tmp_path):
    """Grids A and B, A prepared in the Slices panel at cell 0.25, and the service."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    session.add_grid(GRID_B)
    session.add_lines([_line(tmp_path, "A", f"FILE__00{i + 1}", 1.0 + i) for i in range(3)])
    session.add_lines([_line(tmp_path, "B", f"FILE__01{i}", 1.0 + i) for i in range(2)])
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    dock = SlicesDock(session)
    _ready(dock)
    sections = CutSections(session, dock)
    yield dock, session, sections
    sections.dispose()
    dock.refiner.shutdown()
    dock.engine.wait_for_preparation(20_000)
    dock.engine.dispose()
    dock.deleteLater()


@pytest.fixture
def site(fake_iface, site3, answer_modal):
    """The three-grid site in the plugin, with the plugin's own service."""
    plugin = _open(fake_iface, site3, answer_modal)
    yield plugin
    _close(plugin, answer_modal)


def _sampled(engine, cube, finish, key, cut):
    """The same section read the long way: finish each whole level, sample the columns."""
    columns = section_columns(cube.frame, np.asarray(cut.vertices, dtype=float))
    return np.stack(
        [
            sample(engine.finish(cube.level(k), cube.coverage(), finish), columns.taps)
            for k in range(cube.z.nz)
        ]
    )


def test_this_grid_scope_reads_the_shown_grids_engine(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    got = sections.section(key, build_cube=True)
    assert isinstance(got, CutSection)
    assert got.source.scope == "grid"
    assert got.source.engine is dock.engine
    assert got.source.grid_id == "A"
    assert got.values.shape == (got.z.nz, got.columns.distance_m.size)
    assert got.method == "kriging" and not got.standing_in
    assert got.source.palette == dock.palette_combo.currentText()
    assert sections.source_for("A").engine is dock.engine


def test_this_grid_scope_gives_the_message_for_another_grid(site):
    dock = site.slices_dock
    session = site.session
    key = session.add_cut("B", H)
    sections = site.cut_sections
    text = NO_SOURCE_TEXT.format(name="Cut 1", grid="B")
    assert sections.section(key, build_cube=True) == text
    # Even though a site engine for B is prepared once the site has been shown.
    whole_site(site)
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    dock.set_scope("grid")
    dock.engine.wait_for_preparation(20_000)
    assert dock.site_engine.engine_for("B") is not None
    assert sections.section(key, build_cube=True) == text


def test_whole_site_reads_the_grids_site_engine_without_the_gain(site, monkeypatch):
    dock = site.slices_dock
    session = site.session
    key = session.add_cut("B", H)
    # Whatever the site normalises by, a section is not scaled by it.
    monkeypatch.setattr(
        site_engine_module,
        "normalise",
        lambda method, binned, seams, manual: dict.fromkeys(binned, (2.0, 5.0)),
    )
    whole_site(site)
    got = site.cut_sections.section(key, build_cube=True)
    assert isinstance(got, CutSection)
    engine = dock.site_engine.engine_for("B")
    assert got.source.scope == "site" and got.source.engine is engine
    cube = engine.cube()
    finish = dock.site_finish.value()
    want = _sampled(engine, cube, finish, key, session.cut_for_key(key))
    for k in (cube.z.nz // 4, cube.z.nz // 2, 3 * cube.z.nz // 4):
        np.testing.assert_allclose(got.values[k], want[k], rtol=1e-5, equal_nan=True)
        assert np.isfinite(got.values[k]).any()
    assert json.loads(got.provenance_json)["scope"] == "Whole site (not normalised)"


def test_a_preview_never_builds_a_cube(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()  # what a streaming engine looks like
    assert not engine.has_cube
    assert sections.section(key, build_cube=False) == NO_CUBE_TEXT.format(name="Cut 1", grid="A")
    assert not engine.has_cube
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    assert engine.has_cube


def test_settings_or_source_changes_redraw_an_open_cut(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    changed = Spy(sections.section_changed)
    first = sections.section(key, build_cube=True)
    assert isinstance(first, CutSection)
    assert sections.section(key, build_cube=True) is first  # cached while nothing moves
    base = dock.grid_finish.value()
    edits = {
        "method": lambda: dock.grid_finish.set_value(dataclasses.replace(base, method="idw")),
        "max distance": lambda: dock.grid_finish.set_value(
            dataclasses.replace(base, max_distance_spacings=2.0)
        ),
        "smoothing": lambda: dock.grid_finish.set_value(dataclasses.replace(base, smooth_y_m=0.1)),
        "palette": lambda: dock.palette_combo.setCurrentIndex(
            1 - dock.palette_combo.currentIndex()
        ),
        "cell": lambda: (dock.cell_spin.setValue(0.5), dock.flush_debounce()),
    }
    for name, edit in edits.items():
        changed.calls.clear()
        edit()
        dock.refresh_slice()  # the dock's own redraw announces slice_changed
        assert changed.calls == [(key,)], name
        again = sections.section(key, build_cube=True)
        assert isinstance(again, CutSection), name
        assert again is not first, name
        first = again
    assert first.source.palette == dock.palette_combo.currentText()
    assert first.source.finish.smooth_y_m == 0.1
    assert first.columns.distance_m.size == 17  # cell 0.5: a column every 0.25 m over 4 m


def test_an_open_cut_shows_the_message_when_its_engine_goes_away(site, monkeypatch):
    dock = site.slices_dock
    session = site.session
    sections = site.cut_sections
    key = session.add_cut("A", H)
    changed = Spy(sections.section_changed)
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    # Switching the shown grid: A's cut loses its source, is announced, and
    # recovers (is announced again) when A is shown again.
    first_engine = dock.engine
    dock.grid_combo.setCurrentText("B")
    dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert (key,) in changed.calls
    assert isinstance(sections.section(key, build_cube=False), str)
    changed.calls.clear()
    dock.grid_combo.setCurrentText("A")
    dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert changed.calls.count((key,)) >= 1
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    # Switching scope: the cut reads the site engine, never the This-grid one.
    changed.calls.clear()
    whole_site(site)
    with monkeypatch.context() as scoped:
        scoped.setattr(first_engine, "cube", _boom)
        got = sections.section(key, build_cube=True)
    assert (key,) in changed.calls
    assert isinstance(got, CutSection) and got.source.scope == "site"
    assert got.source.engine is dock.site_engine.engine_for("A")
    # Back to This grid, then the site closes: a message or nothing, never a read.
    dock.set_scope("grid")
    dock.engine.wait_for_preparation(20_000)
    assert isinstance(sections.section(key, build_cube=False), CutSection)
    for engine in (dock.engine, dock.site_engine.engine_for("A")):
        monkeypatch.setattr(engine, "cube", _boom)
    session.close_site()
    assert sections.section(key, build_cube=True) == ""


def _boom(*_a, **_k):
    raise AssertionError("a disposed or foreign engine was read")


def test_a_cut_past_a_shrunk_grid_edge_shows_blank_columns(shown):
    dock, session, sections = shown
    key = session.add_cut("A", [(1.0, 1.0), (5.0, 1.0)])
    first = sections.section(key, build_cube=True)
    assert isinstance(first, CutSection) and np.isfinite(first.values).any()
    changed = Spy(sections.section_changed)
    session.replace_grid(dataclasses.replace(session.grid("A"), size_x=3.0))
    dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert changed.calls.count((key,)) >= 1  # announced; the profile tests check it recovers
    got = sections.section(key, build_cube=True)
    assert isinstance(got, CutSection)
    outside = got.columns.cells < 0
    assert outside.any() and (~outside).any()
    assert np.isnan(got.values[:, outside]).all()
    assert np.isfinite(got.values[:, ~outside]).any()
    assert got.values.shape[1] == first.values.shape[1]  # the cut did not move


def test_minimum_curvature_stands_in_with_kriging(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    mc = dataclasses.replace(dock.grid_finish.value(), method="min_curvature")
    dock.grid_finish.set_value(mc)
    dock.refresh_slice()
    got = sections.section(key, build_cube=True)
    assert isinstance(got, CutSection)
    assert got.method == "kriging" and got.standing_in is True
    assert got.solved == (0, got.z.nz)
    engine = dock.engine
    cube = engine.cube()
    settings = engine.finish_settings(mc)
    _, preview = engine.section_fills(mc)
    want = finish_section(cube, preview, got.columns, settings)
    np.testing.assert_array_equal(got.values, want)
    assert json.loads(got.provenance_json)["standing_in_for"] == "min_curvature"
    assert json.loads(got.provenance_json)["finish"]["method"] == "kriging"


def test_provenance_names_the_cut_cube_and_finish(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    cut = session.cut_for_key(key)
    got = sections.section(key, build_cube=True)
    assert isinstance(got, CutSection)
    doc = json.loads(got.provenance_json)
    engine = dock.engine
    settings = engine.finish_settings(dock.grid_finish.value())
    assert doc["kind"] == "cut"
    assert doc["cut_id"] == cut.id and doc["cut_name"] == "Cut 1" and doc["grid_id"] == "A"
    assert doc["scope"] == "This grid"
    assert doc["cube"]["line_keys"] == list(engine.provenance().line_keys)
    assert doc["cube"]["line_keys"]  # the prepared lines, not none
    assert doc["resolution"] == {"cell": engine.frame.cell, "dz_ns": engine.z.dz_ns}
    assert doc["finish"] == {
        "method": settings.method,
        "max_distance_m": settings.max_distance_m,
        "smooth_x_m": settings.smooth_x_m,
        "smooth_y_m": settings.smooth_y_m,
    }
    assert "standing_in_for" not in doc


def test_column_at_is_the_nearest_column(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    assert sections.column_at(key, 1.04) == 8  # cell 0.25: a column every 0.125 m
    assert sections.column_at(key, -3.0) == 0
    got = sections.section(key, build_cube=True)
    assert sections.column_at(key, 99.0) == got.columns.distance_m.size - 1
    other = session.add_cut("B", H)  # B is not shown
    assert sections.column_at(other, 1.0) is None
    assert sections.column_at("cut:nope", 1.0) is None


def test_a_waiting_cut_is_announced_once_its_source_returns(shown):
    dock, session, sections = shown
    key = session.add_cut("B", H)
    changed = Spy(sections.section_changed)
    assert sections.section(key, build_cube=True) == NO_SOURCE_TEXT.format(name="Cut 1", grid="B")
    assert changed.calls == []
    dock.grid_combo.setCurrentText("B")
    _ready(dock)
    assert changed.calls.count((key,)) == 1  # once, and not again for later redraws
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    dock.refresh_slice()
    assert changed.calls.count((key,)) == 1


def test_a_preview_waiting_for_a_cube_is_announced_when_one_is_held(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    dock.engine.drop_cube()
    changed = Spy(sections.section_changed)
    assert sections.section(key, build_cube=False) == NO_CUBE_TEXT.format(name="Cut 1", grid="A")
    dock.refresh_slice()
    assert changed.calls == []  # still no cube: nothing to say
    dock.engine.cube()
    dock.refresh_slice()
    assert changed.calls == [(key,)]


def test_a_rebuilt_cube_redraws_the_cut_though_nothing_else_moved(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    first = sections.section(key, build_cube=True)
    changed = Spy(sections.section_changed)
    engine = dock.engine
    before = (engine.choice, engine.frame, engine.z)
    engine.drop_cube()
    engine.cube()
    assert (engine.choice, engine.frame, engine.z) == before
    dock.refresh_slice()
    assert changed.calls == [(key,)]
    again = sections.section(key, build_cube=True)
    assert isinstance(again, CutSection) and again is not first


def test_a_source_that_cannot_be_read_is_logged_critical(shown, message_log, monkeypatch):
    dock, session, sections = shown
    monkeypatch.setattr(dock, "scope", lambda: (_ for _ in ()).throw(ValueError("boom")))
    assert sections.source_for("A") is None
    assert any("boom" in m for m in message_log)
