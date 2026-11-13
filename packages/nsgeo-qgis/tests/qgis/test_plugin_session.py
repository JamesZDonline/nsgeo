from __future__ import annotations

import dataclasses
import json
from datetime import datetime

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.project import ProjectError
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit
from nsgeo.velocity_source import SourceFit, VelocitySource
from nsgeo_qgis import session as session_module
from nsgeo_qgis.line_edit import CHANGED_ELSEWHERE, REMOVED, LineEdit
from nsgeo_qgis.session import GPKG_FILE, SURVEY_FILE, SiteSession
from plugin_testing import REAL_DZT, connect_message_log, needs_real_data, synthetic_dzt
from qgis.core import Qgis

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


def test_new_site_writes_the_survey_file_and_names_the_gpkg_for_the_site(qgis_app, tmp_path):
    s = SiteSession()
    opened = Spy(s.site_opened)
    s.new_site(tmp_path)
    assert (tmp_path / SURVEY_FILE).is_file()
    assert s.site_name == tmp_path.name
    # Final review, I5: the package name must NOT be derived from the
    # folder name -- see test_the_package_name_survives_renaming_the_site
    # _folder below. site_name stays the folder's, because that is a
    # display label (the legend group, the survey tree's root) and is
    # meant to follow a rename.
    assert s.gpkg_path == tmp_path / GPKG_FILE
    assert s.gpkg_path.name == "site.nsgeo.gpkg"
    assert s.is_open and not s.dirty
    assert opened.calls == [()]
    with pytest.raises(ProjectError, match="already"):
        s.new_site(tmp_path)


def test_the_package_name_survives_renaming_the_site_folder(qgis_app, tmp_path):
    # Final review, I5: `gpkg_path` used to be root / f"{root.name}.nsgeo
    # .gpkg". Create the site as Site1/, rename the folder once the
    # fieldwork has a name, and the package path resolved to a file that
    # did not exist -- so ensure_tables() built a fresh empty one and
    # every authored pick was orphaned under the old filename with no
    # message at all.
    old = tmp_path / "Site1"
    old.mkdir()
    s = SiteSession()
    s.new_site(old)
    before = s.gpkg_path.name
    s.close_site()

    new = tmp_path / "Kavusan2026"
    old.rename(new)
    s.open_site(new / SURVEY_FILE)

    assert s.site_name == "Kavusan2026"  # the display label does follow
    assert s.gpkg_path == new / before  # the package name does not


def test_opening_a_site_adopts_a_package_left_under_the_old_folder_name(
    qgis_app, tmp_path, message_log
):
    # The migration path. A package written before this fix is named
    # after whatever the folder was called then, so a site renamed since
    # holds e.g. Site1.nsgeo.gpkg in Kavusan2026/ -- a name no rule can
    # re-derive. Left alone it comes up as an empty picks table with the
    # user's picks still on disk and nothing saying so.
    root = tmp_path / "Kavusan2026"
    root.mkdir()
    s = SiteSession()
    s.new_site(root)
    s.close_site()
    legacy = root / "Site1.nsgeo.gpkg"
    legacy.write_bytes(b"not a real GeoPackage, but a real filename")

    s.open_site(root / SURVEY_FILE)

    assert not legacy.exists()
    assert s.gpkg_path.is_file()
    assert s.gpkg_path.read_bytes() == b"not a real GeoPackage, but a real filename"
    assert any("Site1.nsgeo.gpkg" in m and GPKG_FILE in m for m in message_log)


def test_an_old_style_package_is_named_not_adopted_when_the_fixed_name_exists(
    qgis_app, tmp_path, message_log
):
    # Both names present: adopting would have to overwrite a package that
    # is already the site's, so neither file is touched. The stray is
    # named in the log rather than ignored -- it may hold picks, and
    # nothing else would ever mention it.
    root = tmp_path / "Kavusan2026"
    root.mkdir()
    s = SiteSession()
    s.new_site(root)
    s.close_site()
    (root / GPKG_FILE).write_bytes(b"the site's own package")
    legacy = root / "Site1.nsgeo.gpkg"
    legacy.write_bytes(b"an older one, left behind")

    s.open_site(root / SURVEY_FILE)

    assert legacy.read_bytes() == b"an older one, left behind"  # untouched
    assert s.gpkg_path.read_bytes() == b"the site's own package"  # and so is this
    assert any("Site1.nsgeo.gpkg" in m for m in message_log)


def test_two_old_style_packages_are_reported_rather_than_guessed_between(
    qgis_app, tmp_path, message_log
):
    # Ambiguous: renaming the wrong one is worse than renaming neither,
    # because the adopted package is the one the site then writes into.
    # Both are named so the user can pick by hand.
    root = tmp_path / "Kavusan2026"
    root.mkdir()
    s = SiteSession()
    s.new_site(root)
    s.close_site()
    (root / "Site1.nsgeo.gpkg").write_bytes(b"one")
    (root / "Trench3.nsgeo.gpkg").write_bytes(b"two")

    s.open_site(root / SURVEY_FILE)

    assert (root / "Site1.nsgeo.gpkg").read_bytes() == b"one"
    assert (root / "Trench3.nsgeo.gpkg").read_bytes() == b"two"
    assert not s.gpkg_path.exists()
    assert any("Site1.nsgeo.gpkg" in m and "Trench3.nsgeo.gpkg" in m for m in message_log), (
        message_log
    )


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


def test_record_cube_writes_the_record_and_marks_dirty(session):
    """Cheap cluster (final review): `session._set_dirty(True)` used to be
    reached directly from `plugin.save_cube`, the only external caller of
    that private method anywhere in the repo -- every other site mutation
    goes through a `SiteSession` method of its own (`save_preset`'s the
    closest parallel); this is that method for cubes."""
    dirty = Spy(session.dirty_changed)
    record = {"grid_id": "A", "preset": "p", "transform": "none", "cell": 0.25}

    session.record_cube("A__test", record)

    assert session.site.cubes["A__test"] == record
    assert session.dirty and dirty.calls[0] == (True,)


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


# ---- bulk removal (#31) -----------------------------------------------------

GRID_B = Grid("B", (600.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5)


def _two_grids(session, folder):
    """Grid A holding FILE__001..003 and grid B holding FILE__004..005."""
    session.add_grid(GRID)
    session.add_grid(GRID_B)
    session.add_lines(_lines(folder, 3))
    b_lines = []
    for i in range(2):
        p = synthetic_dzt(folder / "raw", f"FILE__00{i + 4}.DZT", n_traces=60)
        b_lines.append(Line.open(p, GridPlacement("B", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(b_lines)


def test_keys_on_grid_lists_that_grids_lines_in_survey_order(session, tmp_path):
    _two_grids(session, tmp_path)
    assert session.keys_on_grid("A") == [f"raw/FILE__00{i}.DZT" for i in (1, 2, 3)]
    assert session.keys_on_grid("B") == ["raw/FILE__004.DZT", "raw/FILE__005.DZT"]
    with pytest.raises(KeyError, match="Z"):
        session.keys_on_grid("Z")


def test_remove_lines_takes_every_line_and_its_stack_in_one_change(session, tmp_path):
    _two_grids(session, tmp_path)
    gone = ["raw/FILE__001.DZT", "raw/FILE__003.DZT", "raw/FILE__004.DZT"]
    for key in gone:
        session.append_step(key, build_step("dewow"))
    session.save()
    changed = Spy(session.lines_changed)

    session.remove_lines(gone)

    assert session.keys() == ["raw/FILE__002.DZT", "raw/FILE__005.DZT"]
    assert [session.line_key(ln) for ln in session.site.lines] == session.keys()
    assert not any(key in session.site.stacks for key in gone)
    assert session.dirty
    # One emission for the whole batch: every lines_changed rebuilds the
    # survey tree and the map layers, so forty lines must not mean forty.
    assert len(changed.calls) == 1


def test_remove_lines_with_an_unknown_key_removes_nothing(session, tmp_path):
    _two_grids(session, tmp_path)
    session.save()
    changed = Spy(session.lines_changed)

    with pytest.raises(KeyError, match="NOPE"):
        session.remove_lines(["raw/FILE__001.DZT", "raw/NOPE.DZT"])

    assert len(session.keys()) == 5
    assert not session.dirty
    assert changed.calls == []


def test_remove_lines_with_nothing_to_remove_changes_nothing(session, tmp_path):
    _two_grids(session, tmp_path)
    session.save()
    changed = Spy(session.lines_changed)

    session.remove_lines([])

    assert len(session.keys()) == 5
    assert not session.dirty
    assert changed.calls == []


def test_remove_lines_tolerates_a_key_named_twice(session, tmp_path):
    _two_grids(session, tmp_path)
    session.remove_lines(["raw/FILE__001.DZT", "raw/FILE__001.DZT"])
    assert "raw/FILE__001.DZT" not in session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
    assert len(session.keys()) == 4


def test_remove_lines_closes_the_current_and_previewed_lines_before_saying_so(session, tmp_path):
    _two_grids(session, tmp_path)
    session.open_line("raw/FILE__002.DZT")
    session.set_preview("raw/FILE__003.DZT", 5)
    seen = []

    def _probe(name):
        def _slot(*_):
            # Whatever a listener asks during any emission must be answerable.
            seen.append((name, session.current_key, session.preview_key))
            for key in session.keys():  # noqa: SIM118 -- SiteSession.keys(), not a dict
                session.line_for_key(key)

        return _slot

    session.line_opened.connect(_probe("line_opened"))
    session.preview_changed.connect(_probe("preview_changed"))
    session.lines_changed.connect(_probe("lines_changed"))

    session.remove_lines(["raw/FILE__002.DZT", "raw/FILE__003.DZT"])

    assert seen == [
        ("line_opened", None, None),
        ("preview_changed", None, None),
        ("lines_changed", None, None),
    ]


def test_remove_grid_with_lines_takes_the_grid_and_only_its_lines(session, tmp_path):
    _two_grids(session, tmp_path)
    session.append_step("raw/FILE__001.DZT", build_step("dewow"))
    session.append_step("raw/FILE__004.DZT", build_step("dewow"))
    session.open_line("raw/FILE__002.DZT")
    session.save()
    order = []
    session.line_opened.connect(lambda k: order.append(("line_opened", k)))
    session.grids_changed.connect(lambda: order.append(("grids_changed",)))
    session.lines_changed.connect(lambda: order.append(("lines_changed",)))

    session.remove_grid("A", with_lines=True)

    assert [g.id for g in session.site.grids] == ["B"]
    assert session.keys() == ["raw/FILE__004.DZT", "raw/FILE__005.DZT"]
    assert list(session.site.stacks) == ["raw/FILE__004.DZT"]
    assert session.current_key is None
    assert session.dirty
    assert order == [("line_opened", ""), ("grids_changed",), ("lines_changed",)]


def test_removed_lines_can_be_imported_again_and_saved(session, tmp_path):
    # The point of #31: clear out a bad import and do it again. The same
    # files must import cleanly, without the dropped stacks coming back.
    _two_grids(session, tmp_path)
    session.append_step("raw/FILE__001.DZT", build_step("dewow"))
    session.remove_grid("A", with_lines=True)
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 3))
    session.save()

    reopened = SiteSession()
    reopened.open_site(tmp_path / SURVEY_FILE)
    assert reopened.keys_on_grid("A") == [f"raw/FILE__00{i}.DZT" for i in (1, 2, 3)]
    assert "raw/FILE__001.DZT" not in reopened.site.stacks


def test_remove_grid_with_lines_on_an_empty_grid_says_nothing_about_lines(session, tmp_path):
    session.add_grid(GRID)
    changed = Spy(session.lines_changed)
    session.remove_grid("A", with_lines=True)
    assert session.site.grids == []
    assert changed.calls == []


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


def test_set_selection_clamps_both_ends_independently_into_range(session, tmp_path):
    # Review round 1, Finding 1: the old clamp floored only the low end and
    # capped only the high end, so an out-of-range drag produced an
    # inverted, out-of-range selection, and (-1, -1) -- the documented
    # "cleared" sentinel -- was reachable through here too.
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]  # n_traces == 60, valid indices 0..59
    session.open_line(key)
    sel = Spy(session.selection_changed)

    session.set_selection(key, -5, -3)  # dragged entirely off the left edge
    assert session.selection == (0, 0)

    session.set_selection(key, 5000, 6000)  # dragged entirely off the right edge
    assert session.selection == (59, 59)

    session.set_selection(key, -1, -1)
    # Must never collide with the "cleared" sentinel: only clear_selection()
    # may produce (-1, -1).
    assert session.selection == (0, 0)
    assert session.selection != (-1, -1)

    assert sel.calls == [(key, 0, 0), (key, 59, 59), (key, 0, 0)]


def test_set_profiles_leaves_no_residue_when_the_key_is_unknown(session, tmp_path):
    # Review round 1, Finding 2: profiles/channel were cached before the key
    # was validated, so a failed set_profiles() left profiles_for() lying
    # about a line that does not exist.
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    with pytest.raises(KeyError):
        session.set_profiles("nope", lines[0].load())
    assert session.profiles_for("nope") is None


def test_set_profiles_builds_the_radargram_exactly_once(session, tmp_path, monkeypatch):
    # Review round 1, Finding 3: stack_for()'s creation branch and the
    # explicit attach after it each built a Radargram from the same
    # profiles, doubling an int32->float64 copy of the whole line.
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]

    build_calls: list[object] = []
    original_from_profile = session_module.Radargram.from_profile

    def counting_from_profile(profile):
        build_calls.append(profile)
        return original_from_profile(profile)

    monkeypatch.setattr(
        session_module.Radargram, "from_profile", staticmethod(counting_from_profile)
    )
    session.set_profiles(key, lines[0].load())
    assert len(build_calls) == 1


def test_set_profiles_with_an_empty_list_clears_a_previously_attached_source(session, tmp_path):
    # Review round 1, Finding 6: _attach_source() skipped silently when
    # profiles was falsy, so reloading with no profiles kept rendering the
    # previous line's samples while still emitting line_loaded.
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    session.set_profiles(key, lines[0].load())
    assert session.stack_for(key).source is not None

    session.set_profiles(key, [])
    assert session.stack_for(key).source is None


def test_stack_for_with_insert_false_builds_without_storing(session, tmp_path):
    """Finding 4 (M7 final review): a read used by a rendering path (a
    preview) must be able to get a fully usable stack -- source attached,
    same as the default -- without planting an empty StepStack into
    site.stacks for a line nobody has actually edited."""
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    session.set_profiles(key, lines[0].load())
    site_stack = session.stack_for(key)
    del session.site.stacks[key]  # back to "never touched", for this test only

    peeked = session.stack_for(key, insert=False)

    assert peeked.source is not None
    assert key not in session.site.stacks
    # The default behaviour is completely unchanged: a later real access
    # still creates and keeps its own stack, distinct from the peek.
    kept = session.stack_for(key)
    assert key in session.site.stacks
    assert kept is not peeked
    assert kept is not site_stack  # the original was deleted above, not reused


def test_set_profiles_on_a_preview_only_key_does_not_persist_an_empty_stack(session, tmp_path):
    """Finding 4 (M7 final review): set_profiles is where a hover-triggered
    background load actually lands -- verified by experiment that THIS
    call, not current_radargram's later one, is what plants the stray
    entry in every currently reachable path. A key that is only being
    previewed (not also the current line) must not get one purely because
    its data finished loading."""
    session.add_grid(GRID)
    lines = _lines(tmp_path, 2)
    session.add_lines(lines)
    keys = session.keys()
    session.open_line(keys[0])
    session.set_preview(keys[1], 3)

    session.set_profiles(keys[1], lines[1].load())

    assert keys[1] not in session.site.stacks
    assert session.stack_for(keys[1]).source is not None  # still fully usable for rendering

    # Once the key stops being preview-only -- promoted here -- the next
    # real stack_for() call persists it normally, same as any other line.
    session.open_line(keys[1])
    session.stack_for(keys[1])
    assert keys[1] in session.site.stacks


def test_set_profiles_on_the_current_line_still_persists_its_stack(session, tmp_path):
    """The ordinary case must not regress: loading the WORKING line's data
    keeps creating its stacks entry immediately, exactly as before this
    fix -- only a bare preview (not also current) skips it."""
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    session.open_line(key)

    session.set_profiles(key, lines[0].load())

    assert key in session.site.stacks


def test_line_index_stays_correct_across_every_list_changing_operation(session, tmp_path):
    # Review round 1, Finding 4: line_for_key()/keys() now read a cached
    # key -> Line map instead of re-resolving every line's path on every
    # call; this pins that the map is invalidated everywhere the line list
    # or the objects in it can change.
    session.add_grid(GRID)
    lines = _lines(tmp_path, 2)
    session.add_lines(lines)
    a, b = session.keys()

    # set_line_velocity swaps in a new Line object at the same key.
    session.set_line_velocity(a, VelocityModel.constant(0.07))
    assert session.line_for_key(a).velocity == VelocityModel.constant(0.07)
    assert session.keys() == [a, b]

    # remove_line drops exactly that key and nothing else.
    session.remove_line(a)
    assert session.keys() == [b]
    with pytest.raises(KeyError):
        session.line_for_key(a)

    # open_site rebuilds the index from what was actually saved.
    session.save()
    reopened = SiteSession()
    reopened.open_site(session.json_path)
    assert reopened.keys() == [b]

    # close_site clears it: both keys() and line_for_key() need an open site.
    reopened.close_site()
    with pytest.raises(ProjectError):
        reopened.keys()
    with pytest.raises(ProjectError):
        reopened.line_for_key(b)


def test_close_site_does_not_emit_line_opened_when_nothing_was_current(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    opened = Spy(s.line_opened)
    s.close_site()
    assert opened.calls == []


def test_close_site_emits_line_opened_empty_and_resets_allow_absolute_when_a_line_was_current(
    session, tmp_path
):
    # Review round 1, Finding 5: remove_line() reports the "no line is
    # current" transition, but close_site() silently dropped the current
    # line without telling a widget bound only to line_opened; it also
    # never reset the per-session allow_absolute opt-in the way _install()
    # does.
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    session.open_line(key)
    session.save(allow_absolute=True)  # flip the per-session opt-in on

    opened = Spy(session.line_opened)
    session.close_site()
    assert opened.calls == [("",)]
    # Not otherwise observable: a fresh new_site()/open_site() would reset
    # this anyway via _install(). Checked directly because close_site() must
    # own this reset rather than relying on always being followed by
    # _install().
    assert session._allow_absolute is False


def test_new_site_refuses_an_occupied_folder_without_touching_what_is_there(qgis_app, tmp_path):
    """The guard is the only thing between "New site..." on an existing
    project folder and `save_site` writing an empty Site over it.

    test_new_site_writes_the_survey_file_and_names_the_gpkg_for_the_site
    above already pins that a second `new_site` on the same folder
    *raises* -- deleting the guard outright fails it. What nothing pinned
    is the half that matters: that the survey file on disk is still the
    one that was there. Moving `save_site` above the guard leaves that
    test green (it still raises, just after the damage) and fails this
    one, which is the shape a reordering or an early write would
    actually take.
    """
    first = SiteSession()
    first.new_site(tmp_path)
    first.add_grid(GRID)
    first.save()
    before = (tmp_path / SURVEY_FILE).read_bytes()

    second = SiteSession()
    opened = Spy(second.site_opened)
    with pytest.raises(ProjectError, match="already holds"):
        second.new_site(tmp_path)

    assert (tmp_path / SURVEY_FILE).read_bytes() == before
    assert not second.is_open  # nothing installed, so nothing to save over it later
    assert opened.calls == []
    # And the site that was already there still opens, with its grid.
    reopened = SiteSession()
    reopened.open_site(tmp_path / SURVEY_FILE)
    assert [g.id for g in reopened.site.grids] == ["A"]


def test_new_site_does_not_install_when_the_initial_save_fails(qgis_app, tmp_path, monkeypatch):
    # Review round 1, Finding 7: new_site() installed the site before
    # writing it, so a failed initial save (e.g. a read-only folder) left
    # the session is_open with site_opened never emitted. open_site()
    # already gets this ordering right; new_site() now matches it.
    def boom(*_args, **_kwargs):
        raise OSError("simulated read-only filesystem")

    monkeypatch.setattr(session_module, "save_site", boom)
    s = SiteSession()
    opened = Spy(s.site_opened)
    with pytest.raises(OSError):
        s.new_site(tmp_path)
    assert not s.is_open
    assert opened.calls == []


def test_apply_stack_to_grid_marks_dirty_before_any_stack_changed_slot_runs(session, tmp_path):
    # Review round 1, Finding 8: dirty was set only after the whole loop,
    # so a synchronous stack_changed slot reacting to the first copied
    # line saw session.dirty as False while handling a change that had
    # already dirtied the site.
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    a, b = session.keys()
    session.append_step(a, build_step("dewow"))
    session.save()
    assert not session.dirty

    observed_dirty_during_emit = []
    session.stack_changed.connect(lambda _key: observed_dirty_during_emit.append(session.dirty))
    changed = session.apply_stack_to_grid(a, "A")

    assert changed == [b]
    assert observed_dirty_during_emit == [True]


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


def _capture_log(fn):
    """Run `fn`, returning the (message, level) pairs it logged.

    Levels matter here: the journal branch is a recoverable, temporary
    condition, and must not shout with the same Critical the
    unrecoverable ones use.
    """
    seen: list[tuple[str, int]] = []
    disconnect = connect_message_log(lambda msg, tag, level: seen.append((msg, level)))
    try:
        fn()
    finally:
        disconnect()
    return seen


@pytest.mark.parametrize("journal", ["-wal", "-shm", "-journal"])
def test_a_legacy_package_with_a_sqlite_journal_is_used_where_it_is(qgis_app, tmp_path, journal):
    # Controller review of I5: renaming a SQLite database away from its
    # journal discards everything committed since the last checkpoint, so
    # the adoption must not happen while one is present. All three
    # spellings, because each means the same thing and SQLite looks for
    # every one of them under the database's *current* name.
    #
    # Controller re-review, Important 1: the answer is to USE the package
    # where it is, not to decline and leave the site with nothing. Opening
    # a database with a hot journal is exactly what SQLite recovery is
    # for; only renaming it was ever unsafe. Declining also created a
    # second, empty package on the same open (SiteLayers.ensure_tables),
    # which wedged the adoption shut permanently -- see
    # test_plugin_layers.py for that loop end to end.
    root = tmp_path / "Kavusan2026"
    root.mkdir()
    s = SiteSession()
    s.new_site(root)
    s.close_site()
    legacy = root / "Site1.nsgeo.gpkg"
    legacy.write_bytes(b"a package whose QGIS was killed")
    (root / f"Site1.nsgeo.gpkg{journal}").write_bytes(b"the journal that goes with it")

    seen = _capture_log(lambda: s.open_site(root / SURVEY_FILE))

    assert legacy.read_bytes() == b"a package whose QGIS was killed"  # untouched
    assert s.gpkg_path == legacy  # and used, not abandoned
    assert not (root / GPKG_FILE).exists()
    assert any(
        "Site1.nsgeo.gpkg" in msg and journal in msg and level == int(Qgis.MessageLevel.Warning)
        for msg, level in seen
    ), seen


@pytest.mark.parametrize("journal", ["-wal", "-shm", "-journal"])
def test_a_journal_beside_the_destination_name_also_blocks_adoption(qgis_app, tmp_path, journal):
    # Controller re-review, Important 2: the guard checked the source name
    # and never the destination. Renaming ONTO a name that already has a
    # journal beside it hands the rescued package a foreign one, which
    # SQLite then replays over it. The plugin cannot create that
    # precondition by itself -- but Important 1 is exactly what pushes a
    # user into `mv Site1.nsgeo.gpkg site.nsgeo.gpkg` by hand, and that
    # touches no sidecars.
    root = tmp_path / "Kavusan2026"
    root.mkdir()
    s = SiteSession()
    s.new_site(root)
    s.close_site()
    legacy = root / "Site1.nsgeo.gpkg"
    legacy.write_bytes(b"this site's real package, cleanly closed")
    stray = root / f"{GPKG_FILE}{journal}"
    stray.write_bytes(b"a journal belonging to something else entirely")

    seen = _capture_log(lambda: s.open_site(root / SURVEY_FILE))

    assert legacy.read_bytes() == b"this site's real package, cleanly closed"
    assert s.gpkg_path == legacy  # used where it is, so nothing meets that journal
    assert not (root / GPKG_FILE).exists()
    assert stray.exists()  # never ours to remove
    assert any(
        stray.name in msg and level == int(Qgis.MessageLevel.Warning) for msg, level in seen
    ), seen


# ---- preview key (M7, spec §3.3) --------------------------------------------


@pytest.fixture
def previewable(qgis_app, tmp_path):
    """A session with two lines placed on one grid."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    session = SiteSession()
    session.new_site(tmp_path)
    grid = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)
    session.add_grid(grid)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(lines)
    keys = session.keys()
    session.open_line(keys[0])
    return session, keys


def test_set_preview_records_the_key_and_trace_and_emits_once(previewable):
    session, keys = previewable
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.set_preview(keys[1], 12)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 12
    assert seen == [(keys[1], 12)]


def test_preview_never_moves_the_working_line(previewable):
    """The C2 guard. current_key is what every write resolves through."""
    session, keys = previewable
    opened = []
    session.line_opened.connect(opened.append)

    session.set_preview(keys[1], 12)

    assert session.current_key == keys[0]
    assert session.current_trace == -1
    assert opened == []


def test_preview_never_dirties_the_session(previewable):
    session, keys = previewable
    session.save()
    assert not session.dirty

    session.set_preview(keys[1], 12)
    session.clear_preview()

    assert not session.dirty


def test_repeating_the_same_preview_emits_nothing(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.set_preview(keys[1], 12)

    assert seen == []


def test_clear_preview_emits_the_cleared_sentinel_once(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.clear_preview()
    session.clear_preview()

    assert seen == [("", -1)]
    assert session.preview_key is None
    assert session.preview_trace == -1


def test_display_key_is_the_preview_while_previewing(previewable):
    session, keys = previewable
    assert session.display_key == keys[0]

    session.set_preview(keys[1], 3)
    assert session.display_key == keys[1]

    session.clear_preview()
    assert session.display_key == keys[0]


def test_preview_trace_is_clamped_to_the_previewed_line(previewable):
    session, keys = previewable
    n = session.line_for_key(keys[1]).n_traces

    session.set_preview(keys[1], 10_000)
    assert session.preview_trace == n - 1

    session.set_preview(keys[1], -5)
    assert session.preview_trace == -1


def test_preview_of_an_unknown_key_raises_and_changes_nothing(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 4)

    with pytest.raises(KeyError):
        session.set_preview("no/such/line", 0)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 4


def test_set_trace_still_refuses_a_previewed_line(previewable):
    """set_trace is keyed to the WORKING line; a preview is not one."""
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.trace_changed.connect(lambda k, i: seen.append((k, i)))

    session.set_trace(keys[1], 20)

    assert seen == []
    assert session.current_trace == -1


def test_open_line_ends_the_preview_without_a_second_emission(previewable):
    """Promotion is one render, not two: line_opened drives it."""
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.open_line(keys[1])

    assert session.preview_key is None
    assert session.current_key == keys[1]
    assert seen == []


def test_close_site_clears_the_preview(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)

    session.close_site()

    assert session.preview_key is None
    assert session.preview_trace == -1


def test_removing_the_previewed_line_clears_the_preview(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.remove_line(keys[1])

    assert session.preview_key is None
    assert seen == [("", -1)]


def test_removing_another_line_leaves_the_preview_alone(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)

    session.remove_line(keys[0])

    assert session.preview_key == keys[1]


def test_reopening_the_current_line_still_ends_a_preview(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.open_line(keys[0])  # already the working line -- early return

    assert session.preview_key is None
    assert session.display_key == keys[0]
    assert seen == [("", -1)]


def test_removing_a_line_that_is_both_current_and_previewed(previewable):
    """The reset must cover BOTH fields before EITHER signal: a slot that
    reads display_key during line_opened("") must not see the dead key."""
    session, keys = previewable
    session.set_preview(keys[0], 5)  # keys[0] is already the current line
    assert session.display_key == keys[0]
    seen = []

    def _probe(*_):
        # Whatever a listener asks during either emission must be answerable.
        seen.append((session.display_key, session.preview_key, session.current_key))
        if session.display_key is not None:
            session.line_for_key(session.display_key)

    session.line_opened.connect(_probe)
    session.preview_changed.connect(_probe)
    session.lines_changed.connect(_probe)

    session.remove_line(keys[0])

    assert seen == [(None, None, None)] * 3
    assert session.display_key is None


def test_removing_a_line_emits_line_opened_before_preview_changed(previewable):
    """Order matters: ProfileDock renders its own _working_key when a
    preview ends, so the working key must be dropped first."""
    session, keys = previewable
    session.set_preview(keys[0], 5)
    order = []
    session.line_opened.connect(lambda k: order.append("line_opened"))
    session.preview_changed.connect(lambda k, t: order.append("preview_changed"))

    session.remove_line(keys[0])

    assert order == ["line_opened", "preview_changed"]


# ---- add_pick (M8, spec §4.1, §4.3) ----------------------------------------


@pytest.fixture
def pickable(qgis_app, tmp_path):
    """A session with two placed lines, a real GeoPackage behind it, and
    the first line open as the working line."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.layers import SiteLayers
    from plugin_testing import synthetic_dzt
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(lines)
    keys = session.keys()
    session.open_line(keys[0])
    yield session, layers, keys
    layers.detach()
    project.clear()


def test_add_pick_writes_the_pick_and_says_so_once(pickable):
    session, layers, keys = pickable
    seen = []
    session.picks_changed.connect(lambda: seen.append(1))

    pick = session.add_pick(keys[0], 12, 18.0)

    assert pick.line_key == keys[0]
    assert pick.trace == 12
    assert pick.time_ns == pytest.approx(18.0)
    assert layers.feature_count("picks") == 1
    assert seen == [1]


def test_derived_pick_fields_are_what_add_pick_records(pickable):
    session, _, keys = pickable
    written = []

    class _Store:
        def write_pick(self, pick):
            written.append(pick)

    session.set_pick_store(_Store())
    pick = session.add_pick(keys[0], 7, 12.5)

    assert written == [pick]
    assert session.derived_pick_fields(keys[0], 7, pick.time_ns) == (
        pick.distance_m,
        pick.depth_m,
        pick.velocity_m_ns,
    )
    with pytest.raises(KeyError):
        session.derived_pick_fields("raw/NOPE.DZT", 7, 12.5)


def test_add_pick_refuses_a_line_that_is_not_the_working_line(pickable):
    """Spec §4.3: picking targets the working line, never a preview. The
    guard is here, in the session, for the same reason set_trace's and
    set_selection's are -- so no caller can forget it. M7's reviews found
    three separate attempts by a preview to reach a write; this is the
    structural answer rather than a fourth guard in a widget."""
    session, layers, keys = pickable
    session.set_preview(keys[1], 5)
    seen = []
    session.picks_changed.connect(lambda: seen.append(1))

    with pytest.raises(ValueError, match="working line"):
        session.add_pick(keys[1], 5, 18.0)

    assert layers.feature_count("picks") == 0
    assert seen == []
    assert session.preview_key == keys[1]  # the refusal changed nothing


def test_add_pick_does_not_dirty_the_session(pickable):
    """A pick is written straight to the GeoPackage; survey.nsgeo.json is
    not involved and there is nothing for `Save site` to do. Marking the
    session dirty would prompt for a save that would write nothing."""
    session, layers, keys = pickable
    session.save()
    assert session.dirty is False

    session.add_pick(keys[0], 3, 10.0)

    assert session.dirty is False


def test_add_pick_clamps_the_trace_and_the_time_into_the_record(pickable):
    """ProfileView emits a pick for any left click in the widget, and
    `ViewTransform.time_of_y` does not clamp -- a click in the top margin
    yields a time before the record starts. The trace is clamped the same
    way `set_trace` clamps it."""
    session, layers, keys = pickable
    line = session.line_for_key(keys[0])
    t0 = line.header.position_ns
    t_end = t0 + (line.header.n_samples - 1) * line.header.dt_ns

    low = session.add_pick(keys[0], -5, t0 - 50.0)
    high = session.add_pick(keys[0], 9999, t_end + 50.0)

    assert low.trace == 0
    assert low.time_ns == pytest.approx(t0)
    assert high.trace == line.n_traces - 1
    assert high.time_ns == pytest.approx(t_end)


def test_add_pick_refuses_a_non_finite_time(pickable):
    session, layers, keys = pickable
    with pytest.raises(ValueError, match="finite"):
        session.add_pick(keys[0], 3, float("nan"))
    assert layers.feature_count("picks") == 0


def test_add_pick_derives_distance_depth_velocity_and_the_stack(pickable):
    session, layers, keys = pickable
    from nsgeo.processing import build_step

    session.append_step(keys[0], build_step("dewow", window_ns=4.0))
    line = session.line_for_key(keys[0])
    model = session.resolved_velocity(keys[0])

    pick = session.add_pick(keys[0], 30, 20.0)

    assert pick.distance_m == pytest.approx(float(line.distance_along()[30]))
    assert pick.depth_m == pytest.approx(float(model.depth_at([20.0])[0]))
    assert pick.velocity_m_ns == pytest.approx(float(model.velocity_at([20.0])[0]))
    assert json.loads(pick.stack_json)[0]["step"] == "dewow"
    assert pick.note == ""
    assert pick.feature_id is None
    assert pick.seq is None
    # An ISO-8601 UTC stamp, parseable rather than merely non-empty.
    assert datetime.fromisoformat(pick.created).tzinfo is not None


def test_add_pick_leaves_distance_null_for_a_line_with_no_distance_axis(pickable, tmp_path):
    """A time-triggered acquisition (traces_per_metre <= 0) has no
    distance axis at all -- `Line.distance_along()` raises. Time is the
    truth, so the pick is still authored; distance is simply absent."""
    session, layers, keys = pickable
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    p = synthetic_dzt(tmp_path / "raw", "FILE__003.DZT", n_traces=40, traces_per_metre=0.0)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 1.5, 0.0, 1, p.stem))])
    session.open_line("raw/FILE__003.DZT")

    pick = session.add_pick("raw/FILE__003.DZT", 3, 15.0)

    assert pick.distance_m is None
    assert pick.depth_m is not None  # time -> depth needs no geometry


def test_add_pick_does_not_announce_a_write_that_failed(pickable, monkeypatch):
    """picks_changed is what tells the profile and the map to redraw. If
    the provider refused the feature, emitting it would show a pick that
    is not on disk -- the worst possible report for the one table with no
    other source of truth."""
    session, layers, keys = pickable
    seen = []
    session.picks_changed.connect(lambda: seen.append(1))

    def boom(pick):
        raise RuntimeError("disk full")

    monkeypatch.setattr(layers, "write_pick", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        session.add_pick(keys[0], 3, 10.0)

    assert seen == []


def test_add_pick_without_a_store_says_so_rather_than_silently_dropping_it(qgis_app, tmp_path):
    """A SiteSession built with no SiteLayers -- which most tests in this
    file do -- has nowhere to put a pick. Silence would look exactly like
    a successful pick."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    session.open_line("raw/FILE__001.DZT")

    with pytest.raises(RuntimeError, match="pick store"):
        session.add_pick("raw/FILE__001.DZT", 3, 10.0)


def test_picks_for_reads_back_through_the_store(pickable):
    session, layers, keys = pickable
    session.add_pick(keys[0], 40, 30.0)
    session.add_pick(keys[0], 5, 10.0)

    assert [(p.trace, p.time_ns) for p in session.picks_for(keys[0])] == [(5, 10.0), (40, 30.0)]
    assert session.picks_for(keys[1]) == []


def test_picks_for_is_empty_with_no_store_rather_than_raising(qgis_app, tmp_path):
    """Reading is not authoring: a dock asking "what picks are on this
    line" before any layers exist gets an honest empty answer, where
    add_pick would raise. A read that raised would abort the CI container
    from inside a render slot."""
    session = SiteSession()
    assert session.picks_for("raw/FILE__001.DZT") == []


@needs_real_data
def test_a_pick_on_a_real_line_lands_in_that_files_own_time_window(qgis_app, tmp_path):
    """Spec §7: real data is the primary validation. Every synthetic
    fixture above shares one header; a real GSSI file has its own
    `position_ns`, `dt_ns`, `n_samples` and dielectric, and those four
    are exactly what turn a click position into a clamped time and a
    depth. A clamp computed against the synthetic header would pass all
    of the above and be wrong on every real file.
    """
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.layers import SiteLayers
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)  # module-level constant, not a fresh Grid
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0, 0.0, 1, "real"))
    session.add_lines([line])  # an absolute path is fine here; only save() cares
    key = session.keys()[0]
    session.open_line(key)
    header = session.line_for_key(key).header
    t_end = header.position_ns + (header.n_samples - 1) * header.dt_ns

    middle = session.add_pick(key, line.n_traces // 2, t_end / 2.0)
    past_the_end = session.add_pick(key, line.n_traces + 500, t_end * 10.0)

    assert middle.time_ns == pytest.approx(t_end / 2.0)
    assert middle.depth_m is not None and middle.depth_m > 0.0
    assert past_the_end.trace == line.n_traces - 1
    assert past_the_end.time_ns == pytest.approx(t_end)
    assert layers.feature_count("picks") == 2
    layers.detach()
    project.clear()


def test_remembering_an_unchanged_source_does_not_mark_dirty(session):
    session.add_grid(GRID)
    session.save()
    session.remember_slice_source("A", preset="p", lines=("k1", "k2"))
    assert session.dirty
    session.save()
    session.remember_slice_source("A", preset="p", lines=("k1", "k2"))
    assert not session.dirty
    session.remember_slice_source("A", preset="p", lines=None)
    assert session.dirty


def test_a_remembered_source_round_trips_keeps_gain_and_is_a_copy(session):
    session.add_grid(GRID)
    assert session.slice_source("A") is None and session.grid_gain("A") == 1.0
    session.set_grid_gain("A", 2.0)
    session.remember_slice_source("A", preset="p", lines=("k1",))
    assert session.grid_gain("A") == 2.0
    session.set_grid_gain("A", 3.0)
    got = session.slice_source("A")
    assert got == {"gain": 3.0, "preset": "p", "lines": ["k1"]}
    got["lines"].append("zz")
    assert session.slice_source("A")["lines"] == ["k1"]
    session.set_site_view(grids=("A",))
    view = session.site_view()
    view["grids"].append("zz")
    assert session.site_view() == {"grids": ["A"]}


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_set_grid_gain_refuses_zero_and_negative(session, bad):
    session.add_grid(GRID)
    session.save()
    with pytest.raises(ValueError, match="gain"):
        session.set_grid_gain("A", bad)
    assert session.slice_source("A") is None and not session.dirty


def test_set_site_view_refuses_an_unknown_method(session):
    session.save()
    with pytest.raises(ValueError, match="normalisation"):
        session.set_site_view(normalisation="sharpen")
    assert session.site_view() == {} and not session.dirty


def test_set_site_view_merges_and_is_quiet_when_unchanged(session):
    session.set_site_view(grids=("A",), transform="none")
    session.set_site_view(normalisation="edge")
    assert session.site_view() == {"grids": ["A"], "transform": "none", "normalisation": "edge"}
    session.save()
    session.set_site_view(normalisation="edge")
    assert not session.dirty


def test_removing_a_grid_prunes_its_source_and_its_site_view_entry(session):
    session.add_grid(GRID)
    session.remember_slice_source("A", preset="p", lines=None)
    session.set_site_view(grids=("A", "B"))
    session.remove_grid("A")
    assert session.slice_source("A") is None
    assert session.site_view()["grids"] == ["B"]


def test_removing_a_grid_with_its_lines_prunes_its_source_and_site_view_entry(session, tmp_path):
    # #31's with_lines path must forget the grid's M12 records as well.
    _two_grids(session, tmp_path)
    session.remember_slice_source("A", preset="p", lines=("raw/FILE__001.DZT",))
    session.set_site_view(grids=("A", "B"))
    session.remove_grid("A", with_lines=True)
    assert session.slice_source("A") is None
    assert session.site_view()["grids"] == ["B"]


def test_remember_slice_resolution_merges_fields_and_keeps_the_source(session):
    # #71: each field is remembered on its own, so a later edit adds to the
    # record rather than replacing it, and the preset and lines stay put.
    session.add_grid(GRID)
    session.remember_slice_source("A", preset="p", lines=None)
    session.remember_slice_resolution("A", cell=0.1)
    session.remember_slice_resolution("A", dz_ns=0.2)
    assert session.slice_source("A") == {
        "preset": "p",
        "lines": None,
        "resolution": {"cell": 0.1, "dz_ns": 0.2},
    }
    got = session.slice_resolution("A")
    assert got == {"cell": 0.1, "dz_ns": 0.2}
    got["cell"] = 9.0
    assert session.slice_resolution("A") == {"cell": 0.1, "dz_ns": 0.2}
    assert session.slice_resolution("B") == {}


def test_remembering_an_unchanged_resolution_does_not_dirty(session):
    session.add_grid(GRID)
    session.remember_slice_resolution("A", cell=0.1, t0_ns=2.0)
    session.remember_site_resolution(max_distance_spacings=1.5)
    assert session.dirty
    session.save()
    session.remember_slice_resolution("A", cell=0.1)
    session.remember_slice_resolution("A", t0_ns=2.0, dz_ns=None)
    session.remember_slice_resolution("A")
    session.remember_site_resolution(max_distance_spacings=1.5)
    session.remember_site_resolution()
    assert not session.dirty
    assert session.slice_resolution("A") == {"cell": 0.1, "t0_ns": 2.0}
    session.remember_slice_resolution("A", t1_ns=30.0)
    assert session.dirty


def test_site_resolution_is_remembered_apart_from_each_grid(session):
    session.add_grid(GRID)
    session.set_site_view(grids=("A",), transform="none")
    assert session.site_resolution() == {}
    session.remember_site_resolution(cell=0.2, max_distance_spacings=0.75)
    session.remember_slice_resolution("A", cell=0.1)
    session.remember_site_resolution(dz_ns=0.3)
    assert session.site_resolution() == {"cell": 0.2, "dz_ns": 0.3, "max_distance_spacings": 0.75}
    assert session.slice_resolution("A") == {"cell": 0.1}
    # The site view's other choices stay where they were.
    view = session.site_view()
    assert view["grids"] == ["A"] and view["transform"] == "none"
    got = session.site_resolution()
    got["cell"] = 9.0
    assert session.site_resolution()["cell"] == 0.2


def test_removing_a_grid_drops_its_remembered_resolution(session):
    session.add_grid(GRID)
    session.remember_slice_resolution("A", cell=0.1, max_distance_spacings=1.0)
    session.remember_site_resolution(cell=0.2)
    session.remove_grid("A")
    assert session.slice_resolution("A") == {}
    assert session.slice_source("A") is None
    # The site's own resolution is not the removed grid's to take with it.
    assert session.site_resolution() == {"cell": 0.2}


def test_remembering_a_method_keeps_it_a_string_and_marks_dirty_once(session):
    session.add_grid(GRID)
    session.remember_site_resolution(method="none", smooth_y_m=0.1)
    session.save()
    flips = Spy(session.dirty_changed)
    session.remember_slice_resolution("A", method="idw", max_distance_spacings=1.0, smooth_x_m=0.2)
    session.remember_slice_resolution("A", method="idw")
    assert flips.calls == [(True,)]
    want = {"method": "idw", "max_distance_spacings": 1.0, "smooth_x_m": 0.2}
    assert session.slice_resolution("A") == want
    session.save()
    reopened = SiteSession()
    reopened.open_site(session.json_path)
    assert reopened.slice_resolution("A") == want
    assert isinstance(reopened.slice_resolution("A")["method"], str)
    assert reopened.site_resolution() == {"method": "none", "smooth_y_m": 0.1}
    assert isinstance(reopened.site_resolution()["method"], str)


def test_remembering_the_same_method_again_does_not_mark_dirty(session):
    session.add_grid(GRID)
    session.remember_slice_resolution("A", method="kriging", max_distance_spacings=0.5)
    session.remember_site_resolution(method="kriging", smooth_x_m=0.0)
    session.save()
    session.remember_slice_resolution("A", method="kriging", max_distance_spacings=0.5)
    session.remember_site_resolution(method="kriging", smooth_x_m=0.0)
    assert not session.dirty


# --- line editing (line editing spec §4.2-4.3) --------------------------------


def _zigzag(session, folder):
    """Grid A (11 m along y) with four y lines at offsets 0 .. 1.5, forward
    and reversed alternately, and Grid B (9 m) with two forward lines.
    Returns the keys on A and on B."""
    session.add_grid(Grid("A", (500.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5))
    session.add_grid(Grid("B", (600.0, 700.0), 0.0, 5.0, 9.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(4):
        p = synthetic_dzt(folder / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        fwd = i % 2 == 0
        placement = GridPlacement("A", "y", i * 0.5, 0.0 if fwd else 11.0, 1 if fwd else -1, p.stem)
        lines.append(Line.open(p, placement))
    for i in range(2):
        p = synthetic_dzt(folder / "raw", f"FILE__00{i + 5}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("B", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(lines)
    return session.keys_on_grid("A"), session.keys_on_grid("B")


def _edit(session, key, **kw):
    return LineEdit(key, session.line_for_key(key).placement, **kw)


def test_edit_lines_applies_every_edit_as_one_change(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    session.save()
    lines = Spy(session.lines_changed)
    outcome = session.edit_lines(
        [_edit(session, a[0], offset=2.0), _edit(session, a[1], label="wall line")]
    )
    assert len(lines.calls) == 1 and session.dirty
    assert session.line_for_key(a[0]).placement.offset == 2.0
    assert session.line_for_key(a[1]).placement.label == "wall line"
    assert outcome.changed == (a[0], a[1])


def test_an_edit_that_changes_nothing_emits_nothing(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    session.save()
    lines = Spy(session.lines_changed)
    own = session.line_for_key(a[0]).placement.offset
    outcome = session.edit_lines([_edit(session, a[0], offset=own)])
    assert outcome.changed == () and not outcome.reordered
    assert lines.calls == [] and not session.dirty


def test_a_line_changed_elsewhere_since_the_table_read_it_is_skipped_and_named(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    rev, fwd = a[1], a[0]
    flips = [
        _edit(session, rev).flipped(session.site.frames),
        _edit(session, fwd).flipped(session.site.frames),
    ]
    session.replace_grid(dataclasses.replace(session.grid("A"), size_y=12.0))
    outcome = session.edit_lines(flips)
    assert [(s.key, s.label, s.reason) for s in outcome.skipped] == [
        (rev, "FILE__002", CHANGED_ELSEWHERE)
    ]
    assert outcome.changed == (fwd,)
    p = session.line_for_key(fwd).placement
    assert (p.direction, p.start_along) == (-1, 12.0)  # against today's length
    assert session.line_for_key(rev).placement.start_along == 12.0  # followed the grid, not edited


def test_a_removed_line_is_skipped_not_raised(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    edit = _edit(session, a[0], offset=3.0)
    session.remove_line(a[0])
    outcome = session.edit_lines([edit])
    assert outcome.changed == ()
    assert [(s.key, s.reason) for s in outcome.skipped] == [(a[0], REMOVED)]


def test_moving_a_line_keeps_its_inset_and_joins_the_new_grid_at_the_end(session, tmp_path):
    a, b = _zigzag(session, tmp_path)
    key = a[1]  # reversed, starts at 11.0 = its far edge
    session.append_step(key, build_step("dewow"))
    session.set_line_velocity(key, VelocityModel.constant(0.07))
    fit_id = session.add_velocity_fit(
        key, StoredFit(20.0, 0.09, 0.004, 0.2, 30, ((30, 20.0), (15, 21.0)), "t")
    )
    session.open_line(key)
    outcome = session.move_lines([key], "B")
    p = session.line_for_key(key).placement
    assert (p.grid_id, p.start_along, p.direction) == ("B", 9.0, -1)
    assert outcome.changed == (key,)
    assert session.keys_on_grid("B")[-1] == key and session.keys()[-1] == key
    assert len(session.stack_for(key, insert=False)) == 1
    assert session.line_for_key(key).velocity == VelocityModel.constant(0.07)
    assert fit_id in session.line_for_key(key).velocity_fits
    assert session.current_key == key
    assert key not in session.keys_on_grid("A")
    assert set(session.keys_on_grid("B")) == set(b) | {key}


def test_a_grid_length_change_keeps_fitted_lines_fitted(session, tmp_path):
    session.add_grid(Grid("F", (500.0, 700.0), 0.0, 5.0, 10.5, "EPSG:32616", 0.5))
    lines = []
    for i, (start, direction, scale) in enumerate(
        [(0.0, 1, 1.05), (10.5, -1, 1.05), (0.0, 1, 1.0)]
    ):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__0{i + 1}.DZT", n_traces=601)
        placement = GridPlacement("F", "y", i * 0.5, start, direction, p.stem, scale=scale)
        lines.append(Line.open(p, placement))
    session.add_lines(lines)
    keys = session.keys_on_grid("F")
    original_third = session.line_for_key(keys[2]).placement
    grids, changed = Spy(session.grids_changed), Spy(session.lines_changed)

    report = session.replace_grid(dataclasses.replace(session.grid("F"), size_y=11.0))

    for key, direction in ((keys[0], 1), (keys[1], -1)):
        p = session.line_for_key(key).placement
        assert p.scale == pytest.approx(1.1)
        ends = sorted([p.start_along, p.start_along + direction * p.scale * 10.0])
        assert ends == [pytest.approx(0.0), pytest.approx(11.0)]
    third = session.line_for_key(keys[2]).placement
    assert third == original_third
    assert report.message() == (
        "F is now 11.00 m along y; its 2 fitted line(s) were fitted to the new length."
    )
    assert len(grids.calls) == 1 and len(changed.calls) == 1


def test_a_grid_length_change_names_both_kinds_when_an_unfitted_reversed_line_moves(
    session, tmp_path
):
    session.add_grid(Grid("F", (500.0, 700.0), 0.0, 5.0, 10.5, "EPSG:32616", 0.5))
    lines = []
    for i, (start, direction, scale) in enumerate(
        [(0.0, 1, 1.05), (10.5, -1, 1.05), (10.5, -1, 1.0)]
    ):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__0{i + 1}.DZT", n_traces=601)
        placement = GridPlacement("F", "y", i * 0.5, start, direction, p.stem, scale=scale)
        lines.append(Line.open(p, placement))
    session.add_lines(lines)
    keys = session.keys_on_grid("F")

    report = session.replace_grid(dataclasses.replace(session.grid("F"), size_y=11.0))

    assert session.line_for_key(keys[2]).placement.start_along == pytest.approx(11.0)
    assert report.message() == (
        "F is now 11.00 m along y; its 1 reversed line(s) moved with the far edge, "
        "and its 2 fitted line(s) were fitted to the new length."
    )


def test_a_moved_line_leaves_the_old_grids_remembered_slice_lines(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    session.remember_slice_source("A", preset="p", lines=(a[0], a[1]))
    session.move_lines([a[1]], "B")
    assert session.slice_source("A")["lines"] == [a[0]]


def test_order_reorders_only_the_grids_own_slots(session, tmp_path):
    session.add_grid(Grid("A", (500.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5))
    session.add_grid(Grid("B", (600.0, 700.0), 0.0, 5.0, 9.0, "EPSG:32616", 0.5))
    lines = []
    for name, grid in [("A1", "A"), ("B1", "B"), ("A2", "A"), ("B2", "B"), ("A3", "A")]:
        p = synthetic_dzt(tmp_path / "raw", f"{name}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement(grid, "y", 0.0, 0.0, 1, name)))
    session.add_lines(lines)
    k = {name: f"raw/{name}.DZT" for name in ("A1", "B1", "A2", "B2", "A3")}
    outcome = session.edit_lines([], grid_id="A", order=[k["A3"], k["A1"], k["A2"]])
    assert outcome.reordered
    assert session.keys() == [k["A3"], k["B1"], k["A1"], k["B2"], k["A2"]]
    session.save()
    again = SiteSession()
    again.open_site(session.json_path)
    assert again.keys() == session.keys()


def test_lines_that_arrived_after_the_table_read_go_after_the_reordered_ones(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    outcome = session.edit_lines([], grid_id="A", order=[a[2], a[0]])
    assert outcome.reordered
    assert session.keys_on_grid("A") == [a[2], a[0], a[1], a[3]]


def test_order_without_a_grid_and_a_key_edited_twice_are_refused(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    with pytest.raises(ValueError):
        session.edit_lines([], order=a)
    with pytest.raises(ValueError):
        session.edit_lines([_edit(session, a[0], offset=2.0), _edit(session, a[0], offset=3.0)])
    with pytest.raises(KeyError):
        session.edit_lines([], grid_id="nope")


def test_an_order_naming_a_line_twice_is_refused_before_anything_changes(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    session.save()
    before_lines = list(session.site.lines)
    before_keys = session.keys()
    before_places = [session.line_for_key(k).placement for k in before_keys]
    changed = Spy(session.lines_changed)
    with pytest.raises(ValueError):
        session.edit_lines([], grid_id="A", order=[a[0], a[0], a[2]])
    assert session.site.lines == before_lines
    assert all(x is y for x, y in zip(session.site.lines, before_lines, strict=True))
    assert session.keys() == before_keys
    assert [session.line_for_key(k).placement for k in before_keys] == before_places
    assert session.dirty is False
    assert changed.calls == []


def test_a_grid_length_change_takes_its_reversed_lines_with_the_far_edge(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    grids, lines = Spy(session.grids_changed), Spy(session.lines_changed)
    report = session.replace_grid(dataclasses.replace(session.grid("A"), size_y=10.0))
    starts = [session.line_for_key(k).placement.start_along for k in a]
    assert starts == [0.0, 10.0, 0.0, 10.0]
    assert (
        report.message()
        == "A is now 10.00 m along y; its 2 reversed line(s) moved with the far edge."
    )
    assert len(grids.calls) == 1 and len(lines.calls) == 1


def test_a_width_change_moves_nothing_and_names_lines_left_outside(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    before = [session.line_for_key(k).placement for k in a]
    report = session.replace_grid(dataclasses.replace(session.grid("A"), size_x=1.2))
    assert [session.line_for_key(k).placement for k in a] == before
    assert report.moved == () and report.outside == ("FILE__004",)


def test_a_velocity_only_grid_edit_moves_no_line_and_reports_nothing(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    before = [session.line_for_key(k).placement for k in a]
    session.set_grid_velocity("A", VelocityModel.constant(0.1))
    report = session.replace_grid(
        dataclasses.replace(session.grid("A"), velocity=VelocityModel.constant(0.09))
    )
    assert report.message() == "" and report.moved == () and report.outside == ()
    assert [session.line_for_key(k).placement for k in a] == before


def test_both_axes_on_one_grid_follow_only_their_own_length(session, tmp_path):
    a, _ = _zigzag(session, tmp_path)
    p = synthetic_dzt(tmp_path / "raw", "FILE__009.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "x", 1.0, 5.0, -1, "x 1"))])
    xkey = session.keys()[-1]
    before = [session.line_for_key(k).placement for k in a]
    report = session.replace_grid(dataclasses.replace(session.grid("A"), size_x=4.0))
    assert session.line_for_key(xkey).placement.start_along == 4.0
    assert [session.line_for_key(k).placement for k in a] == before
    assert report.moved == (("x", 4.0, 1),)


def test_move_lines_leaves_lines_already_there_alone(session, tmp_path):
    a, b = _zigzag(session, tmp_path)
    lines = Spy(session.lines_changed)
    outcome = session.move_lines([b[0]], "B")
    assert outcome.changed == () and lines.calls == []
    gone = session.move_lines(["raw/GONE.DZT"], "B")
    assert [(s.key, s.label, s.reason) for s in gone.skipped] == [("raw/GONE.DZT", "GONE", REMOVED)]
    with pytest.raises(KeyError):
        session.move_lines([a[0]], "nope")


def test_line_zero_is_zero_without_a_time_zero_step_and_loads_nothing(session, tmp_path):
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    assert key not in session.site.stacks
    lines[0].path.rename(lines[0].path.with_suffix(".gone"))  # nothing could be loaded

    assert session.line_zero(key) == 0.0
    assert session.line_zero(key, load=True) == 0.0
    assert key not in session.site.stacks  # reading planted no stack


def test_line_zero_loads_the_line_only_when_asked(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))

    assert session.line_zero(key) is None
    assert session.line_zero(key, load=True) == pytest.approx(-0.0433, abs=1e-3)
    assert session.stack_for(key).source is None  # the probe ran on a copy


def test_line_zero_follows_the_attached_source(session, tmp_path):
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    session.set_profiles(key, lines[0].load())
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))

    assert session.line_zero(key) == pytest.approx(-0.0433, abs=1e-3)


def test_line_zero_is_none_not_an_error_when_the_line_cannot_be_read(session, tmp_path):
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))
    lines[0].path.rename(lines[0].path.with_suffix(".gone"))

    assert session.line_zero(key, load=True) is None


def test_a_pick_made_on_a_relabelled_view_is_stored_from_the_lines_zero(pickable):
    session, _, keys = pickable
    key = keys[0]
    session.set_profiles(key, session.line_for_key(key).load())
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))
    zero = session.line_zero(key)
    assert zero == pytest.approx(-0.0433, abs=1e-3)
    written = []

    class _Store:
        def write_pick(self, pick):
            written.append(pick)

    session.set_pick_store(_Store())
    on_view = session.add_pick(key, 30, 5.0, zero_ns=zero)
    on_radar = session.add_pick(key, 30, 5.0 + zero)

    assert on_view.time_ns == pytest.approx(5.0)
    assert on_view.zero_ns == pytest.approx(zero)
    assert on_view.radar_ns == pytest.approx(5.0 + zero)
    for field in ("time_ns", "zero_ns", "depth_m", "velocity_m_ns", "distance_m"):
        assert getattr(on_radar, field) == pytest.approx(getattr(on_view, field)), field
    assert written == [on_view, on_radar]
    # the depth comes from the stored time, measured from the line's zero
    assert on_view.depth_m == pytest.approx(
        session.derived_pick_fields(key, 30, on_view.time_ns)[1]
    )


def test_a_pick_on_a_line_whose_zero_is_unknown_is_stored_on_the_radar_clock(pickable):
    session, _, keys = pickable
    key = keys[0]
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))
    assert session.line_zero(key) is None  # a zero is set but nothing is attached
    session.set_pick_store(type("S", (), {"write_pick": lambda self, p: None})())
    pick = session.add_pick(key, 30, 5.0, zero_ns=-0.04)
    assert pick.zero_ns is None
    assert pick.time_ns == pytest.approx(5.0 - 0.04)


# ---- velocity records (grid velocity from fits, Task 2) ---------------------
def _fit(stamp="t", v=0.09):
    return StoredFit(20.0, v, 0.004, 0.2, 30, ((30, 20.0), (15, 21.0)), stamp)


def _member(session, key, fit_id):
    line = session.line_for_key(key)
    return SourceFit.of(
        key, fit_id, line.placement.label or line.path.stem, line.velocity_fits[fit_id]
    )


def test_fit_ids_are_never_reused_after_a_delete(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    assert session.add_velocity_fit(key, _fit()) == "fit-1"
    assert session.add_velocity_fit(key, _fit()) == "fit-2"
    session.remove_velocity_fit(key, "fit-2")
    assert session.add_velocity_fit(key, _fit()) == "fit-3"
    for i in ("fit-1", "fit-3"):
        session.remove_velocity_fit(key, i)
    assert session.add_velocity_fit(key, _fit()) == "fit-4"
    assert session.line_for_key(key).fit_serial == 4


def test_fit_ids_survive_save_and_load(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    session.add_velocity_fit(key, _fit())
    session.add_velocity_fit(key, _fit())
    session.remove_velocity_fit(key, "fit-2")
    session.save()
    back = SiteSession()
    back.open_site(tmp_path / SURVEY_FILE)
    assert back.add_velocity_fit(key, _fit()) == "fit-3"


def test_deleting_a_member_keeps_the_record_and_the_velocity(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    fit_id = session.add_velocity_fit(key, _fit())
    m = _member(session, key, fit_id)
    source = VelocitySource.from_fits([m], "2026-11-12T00:00:00Z")
    session.apply_line_velocity(key, VelocityModel.constant(0.09), source)
    assert session.member_state(m) == "present"
    session.remove_velocity_fit(key, fit_id)
    line = session.line_for_key(key)
    assert line.velocity == VelocityModel.constant(0.09)
    assert line.velocity_source == source
    assert session.member_state(m) == "deleted"
    assert session.member_fit(m) is None


def test_a_bare_velocity_drops_the_record(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    fit_id = session.add_velocity_fit(key, _fit())
    source = VelocitySource.from_fits([_member(session, key, fit_id)], None)
    session.apply_line_velocity(key, VelocityModel.constant(0.09), source)
    session.apply_grid_velocity("A", VelocityModel.constant(0.09), source)
    assert session.grid("A").velocity_source == source
    session.set_line_velocity(key, VelocityModel.constant(0.1))
    session.set_grid_velocity("A", VelocityModel.constant(0.1))
    assert session.line_for_key(key).velocity_source is None
    assert session.grid("A").velocity_source is None
    assert session.line_for_key(key).velocity == VelocityModel.constant(0.1)


def test_apply_sets_velocity_and_record_with_one_signal(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    fit_id = session.add_velocity_fit(key, _fit())
    source = VelocitySource.from_fits([_member(session, key, fit_id)], None)
    lines, grids = Spy(session.lines_changed), Spy(session.grids_changed)
    session.apply_line_velocity(key, VelocityModel.constant(0.09), source)
    assert len(lines.calls) == 1 and grids.calls == []
    assert session.line_for_key(key).velocity_source == source
    lines.calls.clear()
    session.apply_grid_velocity("A", VelocityModel.constant(0.09), source)
    assert len(grids.calls) == 1  # replace_grid also announces lines, as set_grid_velocity does
    assert session.grid("A").velocity == VelocityModel.constant(0.09)
    assert session.grid("A").velocity_source == source
    session.apply_line_velocity(key, None, None)
    assert session.line_for_key(key).velocity is None
    assert session.line_for_key(key).velocity_source is None


def test_member_state_names_each_way_a_member_goes(session, tmp_path):
    a, b = _zigzag(session, tmp_path)
    key = a[0]
    fit_id = session.add_velocity_fit(key, _fit("t1"))
    m = _member(session, key, fit_id)
    assert session.member_state(m) == "present"
    assert session.member_fit(m) == _fit("t1")
    assert session.member_state(m, "A") == "present"
    session.remove_velocity_fit(key, fit_id)
    assert session.member_state(m) == "deleted"
    fit_id = session.add_velocity_fit(key, _fit("t1"))
    assert fit_id == "fit-2"  # a new id: the old member stays deleted
    session.move_lines([key], "B")
    assert session.member_state(m, "A") == "deleted"
    m2 = _member(session, key, fit_id)
    assert session.member_state(m2) == "present"
    assert session.member_state(m2, "A") == "line moved to grid B"
    assert session.member_state(m2, "B") == "present"
    session.remove_line(key)
    assert session.member_state(m2) == "line removed"
    assert session.member_fit(m2) is None
    # imported again, with a new fit-1 stamped differently
    p = tmp_path / "raw" / "FILE__001.DZT"
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    again = session.add_velocity_fit(key, _fit("t9"))
    assert again == "fit-1"
    m1 = SourceFit(key, "fit-1", "t1", "FILE__001", 20.0, 0.09, 0.004, 0.0)
    assert session.member_state(m1) == "deleted"


def test_member_state_of_a_loose_line_asked_about_a_grid(session, tmp_path):
    from types import SimpleNamespace

    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    fit_id = session.add_velocity_fit(key, _fit())
    m = _member(session, key, fit_id)
    line = session.line_for_key(key)
    # No loose placement type exists yet; a stand-in without a grid id is the case.
    session._lines_by_key[key] = dataclasses.replace(line, placement=SimpleNamespace(label=None))
    assert session.member_state(m, "A") == "line moved off this grid"
    assert session.member_state(m) == "present"


# ---- #180: each slice scope's colours ---------------------------------------------------


def test_slice_colours_default_to_the_plugin_colours(session):
    assert session.slice_colours("grid") == {}
    assert session.slice_colours("site") == {}


def test_set_slice_colours_merges_per_scope_and_is_quiet_when_unchanged(session, tmp_path):
    session.save()
    session.set_slice_colours("grid", own=True)
    session.set_slice_colours("grid", style="<qgis/>")
    session.set_slice_colours("site", own=False)
    assert session.slice_colours("grid") == {"own": True, "style": "<qgis/>"}
    assert session.slice_colours("site") == {"own": False}
    assert session.dirty
    session.save()
    session.set_slice_colours("grid", own=True, style="<qgis/>")
    assert not session.dirty


def test_slice_colours_are_a_copy(session):
    session.set_slice_colours("grid", own=True)
    session.slice_colours("grid")["own"] = False
    assert session.slice_colours("grid") == {"own": True}


def test_set_slice_colours_refuses_an_unknown_scope(session):
    with pytest.raises(ValueError, match="scope"):
        session.set_slice_colours("profile", own=True)


def test_slice_colours_survive_save_and_reopen(session):
    session.set_slice_colours("site", own=True, style="<qgis>s</qgis>")
    session.save()
    reopened = SiteSession()
    reopened.open_site(session.root / SURVEY_FILE)
    assert reopened.slice_colours("site") == {"own": True, "style": "<qgis>s</qgis>"}


def test_site_crs_is_the_first_grids_until_the_site_has_its_own(session):
    assert session.site_crs() is None
    session.add_grid(Grid("A", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32616", 0.5))
    assert session.site_crs() == "EPSG:32616"


def test_a_grid_free_site_takes_its_crs_once_and_is_dirty(session):
    session.save()
    assert session.site_crs() is None and not session.dirty
    session.set_site_crs("EPSG:32632")
    assert session.site_crs() == "EPSG:32632" and session.dirty


def test_set_site_crs_refuses_to_change_a_set_crs(session):
    session.set_site_crs("EPSG:32632")
    session.save()
    with pytest.raises(ValueError, match="the site already uses EPSG:32632"):
        session.set_site_crs("EPSG:32616")
    assert session.site_crs() == "EPSG:32632" and not session.dirty


def test_set_site_crs_refuses_on_a_site_whose_grid_has_a_crs(session):
    session.add_grid(Grid("A", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32616", 0.5))
    with pytest.raises(ValueError, match="the site already uses EPSG:32616"):
        session.set_site_crs("EPSG:32632")


def test_layers_crs_follows_the_site_crs_on_a_grid_free_site(session):
    from nsgeo_qgis.layers import SiteLayers
    from qgis.core import QgsProject

    layers = SiteLayers(session, project=QgsProject.instance())
    try:
        assert layers.crs() is None
        session.set_site_crs("EPSG:32632")
        crs = layers.crs()
        assert crs is not None and crs.authid() == "EPSG:32632"
    finally:
        layers.detach()
        QgsProject.instance().clear()


def _gps_line(folder, name, crs):
    from nsgeo.geometry.track import TrackFix, TrackPlacement

    p = synthetic_dzt(folder / "raw", name, n_traces=60)
    fixes = (TrackFix(0, 0.0, 0.0, 45.2, 10.5), TrackFix(59, 0.0, 5.0, 45.2, 10.5))
    return Line.open(p, TrackPlacement(fixes=fixes, crs=crs))


def _grid_in(crs):
    return Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, crs, 0.5)


def test_adding_gps_lines_pins_the_crs_and_a_later_grid_edit_cannot_move_it(session, tmp_path):
    from nsgeo_qgis.layers import SiteLayers
    from qgis.core import QgsProject

    layers = SiteLayers(session, project=QgsProject.instance())
    try:
        session.add_grid(_grid_in("EPSG:32632"))
        assert session.site.crs is None
        session.add_lines([_gps_line(tmp_path, "G1.DZT", "EPSG:32632")])
        assert session.site.crs == "EPSG:32632"
        session.replace_grid(_grid_in("EPSG:32616"))
        session.site.validate()
        assert session.site_crs() == "EPSG:32632"
        assert layers.crs().authid() == "EPSG:32632"
        session.save()
    finally:
        layers.detach()
        QgsProject.instance().clear()


def test_a_loaded_tape_site_whose_grid_was_edited_pins_the_crs_it_reported(session, tmp_path):
    session.add_grid(_grid_in("EPSG:32616"))
    session.save()
    session.close_site()
    session.open_site(tmp_path / SURVEY_FILE)
    assert session.site.crs is None
    session.replace_grid(_grid_in("EPSG:32632"))
    assert session.site_crs() == "EPSG:32632"
    session.add_lines([_gps_line(tmp_path, "G2.DZT", "EPSG:32632")])
    assert session.site.crs == "EPSG:32632"
    session.site.validate()
    session.save()


def test_removing_the_first_grid_then_adding_gps_lines_pins_the_new_effective_crs(
    session, tmp_path
):
    session.add_grid(_grid_in("EPSG:32616"))
    session.add_grid(Grid("B", (900.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32632", 0.5))
    session.remove_grid("A")
    assert session.site_crs() == "EPSG:32632"
    session.add_lines([_gps_line(tmp_path, "G3.DZT", "EPSG:32632")])
    assert session.site.crs == "EPSG:32632"
    session.site.validate()


def test_a_tape_only_site_follows_its_first_grids_crs_with_no_pin(session):
    session.add_grid(_grid_in("EPSG:32616"))
    session.replace_grid(_grid_in("EPSG:32632"))
    assert session.site.crs is None and session.site_crs() == "EPSG:32632"


def test_gps_lines_on_a_site_with_no_crs_are_refused_and_nothing_is_added(session, tmp_path):
    with pytest.raises(ValueError, match="need the site's CRS"):
        session.add_lines([_gps_line(tmp_path, "G4.DZT", "EPSG:32632")])
    assert session.site.lines == [] and session.site.crs is None


def test_adding_tape_lines_does_not_pin_the_crs(session, tmp_path):
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    session.add_lines(_lines(tmp_path, 1))
    assert session.site.crs is None
