from __future__ import annotations

import json

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.project import ProjectError
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


def _lines(folder, n=3):
    out = []
    for i in range(n):
        p = synthetic_dzt(folder / "raw", f"FILE__00{i + 1}.DZT", n_traces=60 + i)
        out.append(
            Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1 if i % 2 == 0 else -1, p.stem))
        )
    return out


class Spy:
    def __init__(self, signal):
        self.calls: list = []
        signal.connect(lambda *a: self.calls.append(a))


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    return s


def test_new_site_writes_the_survey_file_and_derives_the_gpkg_name(qgis_app, tmp_path):
    s = SiteSession()
    opened = Spy(s.site_opened)
    s.new_site(tmp_path)
    assert (tmp_path / SURVEY_FILE).is_file()
    assert s.site_name == tmp_path.name
    assert s.gpkg_path == tmp_path / f"{tmp_path.name}.nsgeo.gpkg"
    assert s.is_open and not s.dirty
    assert opened.calls == [()]
    with pytest.raises(ProjectError, match="already"):
        s.new_site(tmp_path)


def test_grids_and_lines_mark_dirty_and_round_trip(session, tmp_path):
    dirty = Spy(session.dirty_changed)
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path))
    assert session.dirty and dirty.calls[0] == (True,)
    assert session.keys() == ["raw/FILE__001.DZT", "raw/FILE__002.DZT", "raw/FILE__003.DZT"]
    session.save()
    assert not session.dirty
    back = SiteSession()
    back.open_site(tmp_path / SURVEY_FILE)
    assert [g.id for g in back.site.grids] == ["A"]
    assert back.keys() == session.keys()


def test_duplicate_grid_ids_and_line_keys_are_refused(session, tmp_path):
    session.add_grid(GRID)
    with pytest.raises(ValueError, match="A"):
        session.add_grid(GRID)
    lines = _lines(tmp_path)
    session.add_lines(lines)
    with pytest.raises(ValueError, match="FILE__001"):
        session.add_lines(lines[:1])


def test_remove_grid_refuses_while_lines_reference_it(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    with pytest.raises(ValueError, match="1 line"):
        session.remove_grid("A")
    session.remove_line("raw/FILE__001.DZT")
    session.remove_grid("A")
    assert session.site.grids == []


def test_remove_line_drops_its_stack_and_closes_it_if_current(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    key = "raw/FILE__001.DZT"
    session.append_step(key, build_step("dewow"))
    session.open_line(key)
    opened = Spy(session.line_opened)
    session.remove_line(key)
    assert key not in session.site.stacks
    assert session.current_key is None
    assert opened.calls == [("",)]


def test_velocity_resolution_and_override(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    assert session.resolved_velocity(key) == VelocityModel.from_dielectric(14.0)
    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    assert session.resolved_velocity(key) == VelocityModel.constant(0.09)
    session.set_line_velocity(key, VelocityModel.constant(0.07))
    assert session.resolved_velocity(key) == VelocityModel.constant(0.07)
    session.set_line_velocity(key, None)
    assert session.resolved_velocity(key) == VelocityModel.constant(0.09)


def test_stack_mutations_emit_and_go_through_the_stack(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    changed = Spy(session.stack_changed)
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("background_mean"))
    session.insert_step(key, 0, build_step("time_zero"))
    session.set_step_enabled(key, 1, False)
    session.move_step(key, 2, 0)
    session.replace_step(key, 1, build_step("time_zero", mode="sample", sample=3))
    session.remove_step(key, 0)
    names = [s.name for s, _ in session.stack_for(key).entries]
    assert names == ["time_zero", "dewow"]
    assert session.stack_for(key).entries[1][1] is False
    assert len(changed.calls) == 7 and all(c == (key,) for c in changed.calls)


def test_profiles_feed_the_stack_source_and_channel_switching(session, tmp_path):
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    loaded = Spy(session.line_loaded)
    session.set_profiles(key, lines[0].load())
    assert loaded.calls == [(key,)]
    src = session.stack_for(key).source
    assert src is not None and src.n_traces == 60 and src.data.dtype.kind == "f"
    assert session.channel(key) == 0
    with pytest.raises(IndexError):
        session.set_channel(key, 1)


def test_apply_stack_to_grid_copies_independent_stacks(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 3))
    a, b, c = session.keys()
    session.append_step(a, build_step("dewow", window_ns=6.0))
    changed = session.apply_stack_to_grid(a, "A")
    assert changed == [b, c]
    assert session.stack_for(b).to_dicts() == session.stack_for(a).to_dicts()
    assert session.stack_for(b) is not session.stack_for(a)
    session.replace_step(a, 0, build_step("dewow", window_ns=2.0))
    assert session.stack_for(b).to_dicts()[0]["params"]["window_ns"] == 6.0


def test_trace_and_selection_emit_only_on_change_and_only_for_the_current_line(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    a, b = session.keys()
    session.open_line(a)
    trace = Spy(session.trace_changed)
    sel = Spy(session.selection_changed)
    session.set_trace(a, 10)
    session.set_trace(a, 10)
    session.set_trace(a, 999)  # clamped to the last trace
    session.set_trace(b, 5)  # not current: ignored
    assert trace.calls == [(a, 10), (a, 59)]
    session.set_selection(a, 30, 20)
    session.set_selection(a, 30, 20)
    session.clear_selection()
    assert sel.calls == [(a, 20, 30), (a, -1, -1)]
    assert session.current_trace == 59


def test_open_line_resets_trace_and_selection(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    a, b = session.keys()
    session.open_line(a)
    session.set_trace(a, 4)
    session.set_selection(a, 1, 2)
    session.open_line(b)
    assert (session.current_key, session.current_trace, session.selection) == (b, -1, (-1, -1))
    with pytest.raises(KeyError):
        session.open_line("nope")


def test_further_mutators_emit_only_on_real_change(session, tmp_path):
    # The module docstring promises every signal fires only on a real change.
    # set_trace/set_selection/set_channel are pinned by the tests above;
    # this covers the rest of the "setter" surface the same way: a checkbox
    # re-synced to its current state, or a reorder dropped back in place,
    # must not trigger a redundant re-render of the radargram.
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    session.set_profiles(key, lines[0].load())
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("background_mean"))
    session.open_line(key)

    stack_changed = Spy(session.stack_changed)
    session.set_step_enabled(key, 0, True)  # already enabled: no-op
    session.move_step(key, 1, 1)  # same source and destination: no-op
    session.set_channel(key, 0)  # already the current channel: no-op
    assert stack_changed.calls == []
    session.set_step_enabled(key, 0, False)
    session.move_step(key, 1, 0)
    assert stack_changed.calls == [(key,), (key,)]

    line_opened = Spy(session.line_opened)
    session.open_line(key)  # already current: no-op
    assert line_opened.calls == []

    session.set_selection(key, 2, 5)
    selection_changed = Spy(session.selection_changed)
    session.clear_selection()
    session.clear_selection()  # already cleared: no-op
    assert selection_changed.calls == [(key, -1, -1)]


def test_save_out_of_tree_line_needs_allow_absolute(qgis_app, tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    s = SiteSession()
    s.new_site(site_dir)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "elsewhere", "X.DZT")
    s.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    with pytest.raises(ProjectError, match="allow_absolute"):
        s.save()
    s.save(allow_absolute=True)
    doc = json.loads((site_dir / SURVEY_FILE).read_text())
    assert doc["lines"][0]["path"].startswith("/")
    s.add_grid(Grid("B", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    s.save()  # the opt-in is remembered for the session
