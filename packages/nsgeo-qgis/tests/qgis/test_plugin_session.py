from __future__ import annotations

import json

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.project import ProjectError
from nsgeo.velocity import VelocityModel
from nsgeo_qgis import session as session_module
from nsgeo_qgis.session import GPKG_FILE, SURVEY_FILE, SiteSession
from plugin_testing import synthetic_dzt
from qgis.core import Qgis, QgsApplication

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
    log = QgsApplication.messageLog()

    def _on_message(msg, tag, level):
        seen.append((msg, int(level)))

    log.messageReceived.connect(_on_message)
    try:
        fn()
    finally:
        log.messageReceived.disconnect(_on_message)
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
