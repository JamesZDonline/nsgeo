"""`CutSections`: a cut's section from the Slices panel's engines (cut spec §4.3, §4.4)."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest
from nsgeo.slices import finish_section, section_columns
from nsgeo.slices.resample import sample
from nsgeo_qgis import cut_sections as cut_sections_module
from nsgeo_qgis import site_engine as site_engine_module
from nsgeo_qgis.cut_sections import (
    BUILD_FAILED_TEXT,
    NO_CUBE_TEXT,
    NO_SOURCE_TEXT,
    PREPARING_TEXT,
    TOO_BIG_TEXT,
    CutSection,
    CutSections,
)
from nsgeo_qgis.line_edit import LineEdit
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.slices_dock import SlicesDock
from test_plugin_session import Spy
from test_plugin_site_scope import _close, _open, settle, whole_site
from test_plugin_slices_dock import GRID, GRID_B, PRESET, TIME_ZERO_PRESET, _line, _ready

H = [(1.0, 1.0), (5.0, 1.0)]  # along x, 4 m


def _shown_with(tmp_path, preset):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    session.add_grid(GRID_B)
    session.add_lines([_line(tmp_path, "A", f"FILE__00{i + 1}", 1.0 + i) for i in range(3)])
    session.add_lines([_line(tmp_path, "B", f"FILE__01{i}", 1.0 + i) for i in range(2)])
    session.site.presets["p"] = list(preset)
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
def shown(qgis_app, tmp_path):
    """Grids A and B, A prepared in the Slices panel at cell 0.25, and the service."""
    yield from _shown_with(tmp_path, PRESET)


@pytest.fixture
def shown_zeroed(qgis_app, tmp_path):
    """The same, with a preset that sets time zero (#97), so the cube is on that clock."""
    yield from _shown_with(tmp_path, TIME_ZERO_PRESET)


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
    # The streaming engine's cube went with the cut's leaving it (M15 final review, I2).
    assert sections.section(key, build_cube=False) == NO_CUBE_TEXT.format(name="Cut 1", grid="A")
    assert isinstance(sections.section(key, build_cube=True), CutSection)
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


def test_the_exact_texts():
    assert PREPARING_TEXT == "{grid} is being prepared again. The cut will redraw when it is ready."
    assert BUILD_FAILED_TEXT == "{grid}'s cube could not be built for this cut: {reason}"
    assert TOO_BIG_TEXT == (
        "{grid}'s cube is too large to hold in memory for a cut. "
        "Use a coarser cell or a shorter depth range in the Slices panel."
    )


def test_a_streaming_engine_over_budget_refuses_to_build_a_cube(shown, monkeypatch):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()
    assert engine.mode == "streaming" and not engine.has_cube
    monkeypatch.setattr(cut_sections_module, "DEFAULT_BUDGET_BYTES", 1)
    assert sections.section(key, build_cube=True) == TOO_BIG_TEXT.format(grid="A")
    assert not engine.has_cube
    assert key not in sections._streamed


def test_a_streaming_engine_under_budget_keeps_its_cube_across_a_line_visit(shown):
    """The cube is dropped when a cut on another engine opens, the cut goes, its source
    changes or the site closes, never because the working item moved to a line: a visit
    to a line keeps the cube and the solve (M15 residual B2)."""
    dock, session, sections = shown
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()
    assert engine.mode == "streaming" and engine.estimate.total_bytes < 1_500_000_000
    mc = dataclasses.replace(dock.grid_finish.value(), method="min_curvature")
    dock.grid_finish.set_value(mc)
    dock.refresh_slice()
    session.open_line(key)
    first = sections.section(key, build_cube=True)
    assert isinstance(first, CutSection) and engine.has_cube
    entry = sections._cache[key]
    entry.section.values[3] = 7.0  # a solved row, which a restart would overwrite
    entry.levels.add(3)
    generation = engine.cube_generation
    line = session.keys()[0]
    session.set_profiles(line, session.line_for_key(line).load())
    session.open_line(line)  # the working item leaves the cut
    assert engine.has_cube and engine.cube_generation == generation
    assert sections._streamed == {key: engine}
    session.open_line(key)  # and comes back
    again = sections.section(key, build_cube=True)
    assert again is first or again.values is first.values  # the cached section, not a rebuild
    assert sections._cache[key] is entry and entry.levels == {3}
    assert sections._working == key and sections._stamp == entry.stamp  # the solve resumes
    assert sections._cache[key].section.solved == (1, first.z.nz)  # from 1 done, not from 0


def test_a_streaming_engine_drops_its_cube_when_a_cut_on_another_engine_opens(site):
    dock = site.slices_dock
    session = site.session
    sections = site.cut_sections
    key_a = session.add_cut("A", H)
    key_b = session.add_cut("B", H)
    whole_site(site)
    engine_a = dock.site_engine.engine_for("A")
    engine_b = dock.site_engine.engine_for("B")
    assert engine_a is not engine_b
    for engine in (engine_a, engine_b):
        engine.drop_cube()
        assert engine.mode == "streaming"
    session.open_line(key_a)
    assert isinstance(sections.section(key_a, build_cube=True), CutSection)
    assert engine_a.has_cube and not engine_b.has_cube
    session.open_line(key_b)  # a cut on another engine opens
    assert not engine_a.has_cube
    assert isinstance(sections.section(key_b, build_cube=True), CutSection)
    assert engine_b.has_cube and sections._streamed == {key_b: engine_b}


def test_a_scope_round_trip_with_a_cut_open_holds_one_cube(site):
    """This grid -> Whole site -> This grid -> Whole site with the cut open in the
    profile: after each switch at most one streaming engine holds a cube that a cut
    built (M15 residual B2; the scratch leak held This grid's cube from the second
    visit on)."""
    dock = site.slices_dock
    session = site.session
    key = session.add_cut("A", H)
    grid_engine = dock.engine
    grid_engine.drop_cube()
    assert grid_engine.mode == "streaming"

    def held():
        engines = [dock.engine, *(dock.site_engine.engine_for(g) for g in "ABC")]
        seen = []
        for engine in engines:
            streaming = engine is not None and engine.mode == "streaming" and engine.has_cube
            if streaming and not any(engine is other for other in seen):
                seen.append(engine)
        return seen

    session.open_line(key)  # the profile asks, with build_cube=True
    assert len(held()) == 1
    for step in ("site", "grid", "site"):
        if step == "site":
            whole_site(site)
        else:
            dock.set_scope("grid")
            dock.engine.wait_for_preparation(20_000)
            dock.flush_debounce()
        assert len(held()) <= 1, step
    assert sections_streamed_ok(site.cut_sections)


def sections_streamed_ok(sections):
    """Every engine a cut recorded is streaming (a resident one is never recorded)."""
    return all(e.mode == "streaming" for e in sections._streamed.values())


def test_a_streaming_engines_cube_goes_when_its_cut_is_deleted_or_the_site_closes(shown):
    dock, session, sections = shown
    engine = dock.engine
    key = session.add_cut("A", H)
    engine.drop_cube()
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    session.remove_cut(key)
    assert not engine.has_cube
    again = session.add_cut("A", H)
    assert isinstance(sections.section(again, build_cube=True), CutSection)
    assert engine.has_cube
    session.close_site()
    assert not engine.has_cube


def test_a_second_cut_on_the_same_streaming_engine_keeps_the_cube(shown):
    dock, session, sections = shown
    engine = dock.engine
    first = session.add_cut("A", H)
    second = session.add_cut("A", [(1.0, 2.0), (5.0, 2.0)])
    engine.drop_cube()
    session.open_line(first)
    assert isinstance(sections.section(first, build_cube=True), CutSection)
    built = engine.cube_generation
    session.open_line(second)  # another cut on the same engine reads the same cube
    assert engine.has_cube and engine.cube_generation == built


def test_a_resident_engines_cube_is_never_dropped_by_a_cut(shown):
    dock, session, sections = shown
    engine = dock.engine
    engine.set_always_resident(True)
    assert engine.mode == "resident"
    key = session.add_cut("A", H)
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    session.open_line(key)
    line = session.keys()[0]
    session.set_profiles(line, session.line_for_key(line).load())
    session.open_line(line)
    assert engine.has_cube
    session.remove_cut(key)
    assert engine.has_cube  # the engine's own choice, whatever the cuts do


def test_a_cut_says_its_grid_is_being_prepared_again_and_redraws_when_ready(shown):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    changed = Spy(sections.section_changed)
    session.replace_grid(dataclasses.replace(session.grid("A"), size_x=4.0))
    assert dock.engine.is_running  # the re-preparation is under way
    assert sections.section(key, build_cube=True) == PREPARING_TEXT.format(name="Cut 1", grid="A")
    dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert changed.calls.count((key,)) >= 1
    assert isinstance(sections.section(key, build_cube=True), CutSection)


def test_whole_site_says_a_queued_grid_is_being_prepared(site):
    """B4: in Whole site scope the site engine's own state says a grid is being prepared,
    and a grid waiting behind another is too, though its engine is not running. Driven
    through real queue states: an edit to a B line re-queues B alone, and the cut is asked
    from inside the site engine's change callback at each state B passes through."""
    dock = site.slices_dock
    session = site.session
    key = session.add_cut("B", H)
    whole_site(site)
    sections = site.cut_sections
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    texts: dict[str, str] = {}
    inner = dock.site_engine.on_changed

    def record() -> None:
        state = dock.site_engine.grid_state("B")
        if state != "ready":
            texts.setdefault(state, sections.section(key, build_cube=True))
        if inner is not None:
            inner()

    dock.site_engine.on_changed = record
    lines = session.keys()
    b_line = next(k for k in lines if session.line_for_key(k).placement.grid_id == "B")
    session.edit_lines([LineEdit(b_line, session.line_for_key(b_line).placement, offset=1.75)])
    settle(dock)
    expected = PREPARING_TEXT.format(name="Cut 1", grid="B")
    assert texts.get("queued") == expected, texts
    assert all(text == expected for text in texts.values()), texts
    assert sections._preparing("not-in-the-site") is False  # unknown: not preparing


def test_a_cube_that_cannot_be_built_says_why_and_logs_it(shown, message_log, monkeypatch):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()

    def refuse():
        raise RuntimeError("out of memory")

    monkeypatch.setattr(engine, "cube", refuse)
    text = sections.section(key, build_cube=True)
    assert text == BUILD_FAILED_TEXT.format(grid="A", reason="out of memory")
    assert any("out of memory" in m for m in message_log)


def test_a_build_failure_with_no_message_still_names_its_reason(shown, monkeypatch):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    dock.engine.drop_cube()

    def refuse():
        raise MemoryError()

    monkeypatch.setattr(dock.engine, "cube", refuse)
    text = sections.section(key, build_cube=True)
    assert text == BUILD_FAILED_TEXT.format(grid="A", reason="MemoryError")
    assert text.endswith(": MemoryError")


def test_a_failed_build_is_retried_only_when_its_inputs_change(shown, message_log, monkeypatch):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()
    calls = []

    def refuse():
        calls.append(1)
        raise RuntimeError("out of memory")

    monkeypatch.setattr(engine, "cube", refuse)
    assert sections.section(key, build_cube=True).startswith("A's cube could not be built")
    assert len(calls) == 1
    warnings = len([m for m in message_log if "could not build" in m])
    changed = Spy(sections.section_changed)
    for _ in range(3):  # slider ticks
        dock.refresh_slice()
    assert len(calls) == 1
    assert len([m for m in message_log if "could not build" in m]) == warnings
    assert changed.calls == []  # the profile is not asked again for nothing
    assert sections.section(key, build_cube=True).startswith("A's cube could not be built")
    assert len(calls) == 1  # a profile that asks anyway is told the same, with no build
    # The engine prepared again: tried once more.
    engine.clear()
    dock.prepare()
    assert engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert (key,) in changed.calls
    monkeypatch.setattr(engine, "cube", refuse)  # the re-preparation may have dropped it
    assert sections.section(key, build_cube=True).startswith("A's cube could not be built")
    assert len(calls) == 2


def test_opening_the_cut_again_retries_a_failed_build(shown, monkeypatch):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()
    calls = []
    real = engine.cube

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("out of memory")
        return real()

    monkeypatch.setattr(engine, "cube", flaky)
    assert sections.section(key, build_cube=True).startswith("A's cube could not be built")
    assert len(calls) == 1
    dock.refresh_slice()
    assert len(calls) == 1  # a slider tick does not retry
    changed = Spy(sections.section_changed)
    session.open_line(key)  # the user opens the cut: the profile is asked again
    assert changed.calls == [(key,)]
    assert isinstance(sections.section(key, build_cube=True), CutSection)
    assert len(calls) >= 2  # the build was tried again, and held


def test_the_first_open_of_a_failing_cut_builds_once_with_the_profile_attached(
    site,  # noqa: F811
    message_log,
    monkeypatch,
):
    """The profile connects to `line_opened` before CutSections, so it asks first and the
    build fails; the open's own slot must not count that fresh failure as an old one and
    ask again (M15 5b review I1). Reopening after a line visit retries exactly once."""
    dock = site.slices_dock
    session = site.session
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()
    calls = []

    def refuse():
        calls.append(1)
        raise RuntimeError("out of memory")

    monkeypatch.setattr(engine, "cube", refuse)

    def warnings():
        return len([m for m in message_log if "could not build" in m])

    session.open_line(key)
    assert (len(calls), warnings()) == (1, 1)
    session.open_line(session.keys()[0])
    assert len(calls) == 1
    session.open_line(key)
    assert (len(calls), warnings()) == (2, 2)
    dock.refresh_slice()
    assert len(calls) == 2


def test_a_failed_build_is_retried_after_a_resolution_change(shown, monkeypatch):
    """`set_resolution` does not move `preparation_generation`, and "use a coarser cell"
    is the remedy the guide gives (M15 5b review I2)."""
    dock, session, sections = shown
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()
    calls = []

    def refuse():
        calls.append(1)
        raise RuntimeError("out of memory")

    monkeypatch.setattr(engine, "cube", refuse)
    assert sections.section(key, build_cube=True).startswith("A's cube could not be built")
    assert len(calls) == 1
    changed = Spy(sections.section_changed)
    generation = engine.preparation_generation
    dock.cell_spin.setValue(dock.cell_spin.value() * 2)
    dock.flush_debounce()
    assert engine.preparation_generation == generation  # the memo cannot rely on it
    assert (key,) in changed.calls  # announced, so the profile asks again
    assert sections.section(key, build_cube=True).startswith("A's cube could not be built")
    assert len(calls) == 2  # and the build was tried once more, not on every tick
    for _ in range(3):
        dock.refresh_slice()
    assert len(calls) == 2


def test_a_cube_the_engine_builds_itself_after_a_failure_reannounces_the_cut(shown, monkeypatch):
    dock, session, sections = shown
    key = session.add_cut("A", H)
    engine = dock.engine
    engine.drop_cube()
    real = engine.cube

    def refuse():
        raise RuntimeError("out of memory")

    monkeypatch.setattr(engine, "cube", refuse)
    assert sections.section(key, build_cube=True).startswith("A's cube could not be built")
    monkeypatch.undo()
    changed = Spy(sections.section_changed)
    real()  # the engine builds it for itself (a slice refresh, say)
    assert engine.has_cube
    dock.refresh_slice()
    assert (key,) in changed.calls
    assert isinstance(sections.section(key, build_cube=True), CutSection)


def test_opening_a_sourceless_cut_keeps_the_working_cuts_cube_and_solve(shown):
    dock, session, sections = shown
    mc = dataclasses.replace(dock.grid_finish.value(), method="min_curvature")
    dock.grid_finish.set_value(mc)
    dock.refresh_slice()
    key = session.add_cut("A", H)
    other = session.add_cut("B", H)  # grid B is not the one This grid shows: no source
    engine = dock.engine
    engine.drop_cube()
    session.open_line(key)
    first = sections.section(key, build_cube=True)
    assert isinstance(first, CutSection) and engine.has_cube
    entry = sections._cache[key]
    entry.section.values[3] = 7.0
    entry.levels.add(3)
    generation = engine.cube_generation
    session.open_line(other)
    assert isinstance(sections.section(other, build_cube=True), str)
    assert engine.has_cube and engine.cube_generation == generation
    session.open_line(key)
    again = sections.section(key, build_cube=True)
    assert sections._cache[key] is entry and entry.levels == {3}
    assert again.values[3][np.isfinite(again.values[3])].max() == 7.0
