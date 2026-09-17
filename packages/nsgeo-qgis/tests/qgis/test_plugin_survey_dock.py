from __future__ import annotations

import json

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from nsgeo_qgis.ui.survey_dock import ROLE_ID, ROLE_KIND, SurveyDock
from plugin_testing import synthetic_dzt
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtWidgets import QFileDialog, QMenu, QMessageBox

GRID = Grid(
    "A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.08)
)


@pytest.fixture
def dock(qgis_app, tmp_path):
    session = SiteSession()
    dock = SurveyDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(
            Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1 if i % 2 == 0 else -1, p.stem))
        )
    session.add_lines(lines)
    return session, dock


def test_tree_mirrors_site_grids_and_lines(dock):
    session, dock = dock
    root = dock.tree.topLevelItem(0)
    assert root.text(0) == session.site_name
    grid_item = root.child(0)
    assert grid_item.data(0, ROLE_KIND) == "grid" and grid_item.data(0, ROLE_ID) == "A"
    assert "0.080" in grid_item.text(0)
    assert grid_item.childCount() == 3
    line_item = grid_item.child(1)
    assert line_item.data(0, ROLE_KIND) == "line"
    assert line_item.data(0, ROLE_ID) == "raw/FILE__002.DZT"
    assert (
        "FILE__002" in line_item.text(0)
        and "0.50" in line_item.text(0)
        and "↓" in line_item.text(0)
    )


def test_tree_follows_session_changes(dock):
    session, dock = dock
    session.remove_line("raw/FILE__003.DZT")
    assert dock.tree.topLevelItem(0).child(0).childCount() == 2
    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    assert dock.tree.topLevelItem(0).childCount() == 2
    assert "empty" in dock.tree.topLevelItem(0).child(1).text(0)


def test_clicking_a_line_opens_it_and_selection_follows_the_session(dock):
    session, dock = dock
    item = dock.item_for_key("raw/FILE__002.DZT")
    dock.tree.itemClicked.emit(item, 0)
    assert session.current_key == "raw/FILE__002.DZT"
    session.open_line("raw/FILE__003.DZT")
    assert dock.tree.currentItem() is dock.item_for_key("raw/FILE__003.DZT")


def test_status_shows_dirty_state(dock):
    session, dock = dock
    assert "modified" in dock.status.text()
    session.save()
    assert "modified" not in dock.status.text()
    assert "survey.nsgeo.json" in dock.status.text()


def test_line_velocity_override_is_marked(dock):
    session, dock = dock
    session.set_line_velocity("raw/FILE__001.DZT", VelocityModel.constant(0.095))
    assert "v 0.095*" in dock.item_for_key("raw/FILE__001.DZT").text(0)


def test_context_actions_remove_lines_and_grids(dock):
    session, dock = dock
    dock.remove_line_action("raw/FILE__001.DZT", confirm=False)
    assert "raw/FILE__001.DZT" not in session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
    with pytest.raises(ValueError):
        dock.remove_grid_action("A", confirm=False)


def test_closing_the_site_empties_the_tree(dock):
    session, dock = dock
    session.close_site()
    assert dock.tree.topLevelItemCount() == 0
    assert dock.status.text() == "no site open"


def test_plugin_wires_the_dock_and_file_actions(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.survey_dock in fake_iface.docks
    assert plugin.survey_dock.allowedAreas() & Qt.DockWidgetArea.LeftDockWidgetArea
    # I1: Task 15's entire profile-dock construction block in `initGui`
    # (and its teardown in `unload`) had no assertion at all -- deleting
    # the four lines that build, wire, add and track `ProfileDock`, or the
    # `for dock in self.docks: ...` teardown loop, both left the full
    # 258-test suite green. The plugin could ship with no profile dock at
    # all and nothing would notice.
    assert plugin.profile_dock in fake_iface.docks
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)
    assert plugin.save_with_prompt() is True
    assert not plugin.session.dirty
    plugin.unload()
    assert plugin.survey_dock is None
    assert fake_iface.docks == [] and plugin.profile_dock is None


# ---- additional coverage: the "Get these right" requirements and the
# signal/slot failure-path hazard (see the module docstring in survey_dock.py
# and plugin.py) that the brief's own test list does not exercise. ----------


def test_time_triggered_lines_appear_in_the_tree_marked_not_omitted(dock, tmp_path):
    # GridPlacement.distance_along raises ValueError for a time-triggered
    # acquisition (traces_per_metre <= 0). Such a line has no geometry, but
    # it is still part of the site: it must show up here, distinguishable
    # from a placeable line, rather than silently vanishing from the tree
    # or taking the whole rebuild down with it.
    session, dock = dock
    p = synthetic_dzt(tmp_path / "raw", "FILE__TIME.DZT", traces_per_metre=0.0)
    line = Line.open(p, GridPlacement("A", "y", 2.0, 0.0, 1, p.stem))
    session.add_lines([line])
    grid_item = dock.tree.topLevelItem(0).child(0)
    assert grid_item.childCount() == 4  # not omitted
    item = dock.item_for_key("raw/FILE__TIME.DZT")
    assert item is not None
    assert "unplaced" in item.text(0)


def test_rebuild_survives_an_unexpected_error_and_leaves_an_honest_empty_tree(dock, monkeypatch):
    # A signal handler's exception never reaches whatever emitted the
    # signal (PyQt prints it to stderr and emit() returns as if nothing
    # happened), so rebuild() must catch its own failures: a half-built
    # tree would look complete and be silently wrong, which is worse than
    # an obviously empty one with a visible error.
    session, dock = dock

    def boom(_line):
        raise RuntimeError("simulated bug while building a line item")

    monkeypatch.setattr(dock, "_line_item", boom)
    session.add_grid(Grid("C", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    assert dock.tree.topLevelItemCount() == 0
    assert "error" in dock.status.text().lower()


def test_remove_line_action_reraises_rather_than_silently_dropping_a_missing_key(dock):
    # Symmetric with remove_grid_action's already-tested ValueError path:
    # a programmatic caller (confirm=False) must see the failure, not have
    # it disappear along with the (nonexistent) line.
    session, dock = dock
    with pytest.raises(KeyError):
        dock.remove_line_action("raw/NOPE.DZT", confirm=False)


def test_new_site_reports_unexpected_errors_without_crashing_or_losing_state(
    fake_iface, tmp_path, monkeypatch
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path))
    )

    def boom(*_a, **_k):
        raise OSError("simulated read-only filesystem")

    monkeypatch.setattr(plugin.session, "new_site", boom)
    plugin.new_site()  # must not raise: this is a QAction.triggered slot
    assert not plugin.session.is_open
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "simulated read-only filesystem" in item.text()
    plugin.unload()


def test_save_with_prompt_reports_unexpected_errors_and_keeps_the_site_dirty(
    fake_iface, tmp_path, monkeypatch
):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)
    assert plugin.session.dirty

    def boom(**_kw):
        raise OSError("simulated disk-full error")

    monkeypatch.setattr(plugin.session, "save", boom)
    assert plugin.save_with_prompt() is False
    assert plugin.session.dirty  # never silently marked clean on a failed save
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "simulated disk-full error" in item.text()
    # No plugin.unload() here: the site is deliberately left dirty, and
    # unload()'s own dirty-session prompt is this file's business, not
    # this test's -- see the test_unload_* tests below, which use
    # answer_modal to drive that prompt directly. Without it, the
    # _no_unhandled_modals guard would fail this test fast rather than
    # hang it, but the point stands: that prompt is a separate concern
    # from save_with_prompt()'s own failure handling, which is what this
    # test exists to pin.


def test_unload_releases_every_toolbar_and_menu_action(fake_iface, qgis_app):
    # Task 5 fixed this leak for the menu's About action (removePluginMenu
    # alone drops the Python reference but never deletes the underlying
    # QAction). The toolbar actions this task adds are not children of the
    # toolbar itself (QToolBar.addAction does not reparent), so unload()
    # must deleteLater() each of them explicitly too, not just tear down
    # the toolbar that displayed them.
    #
    # Asserting only that the bookkeeping lists end up empty would stay
    # green even if the deleteLater() calls themselves were deleted --
    # deleteLater() is deferred, and (measured directly) a plain
    # processEvents() does not dispatch a DeferredDelete event; only
    # sendPostedEvents(None, QEvent.DeferredDelete) forces it through so
    # sip.isdeleted() can tell "scheduled" apart from "actually deleted".
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.toolbar_actions and plugin.menu_actions
    assert plugin.act_new is not None
    toolbar_action = plugin.toolbar_actions[0]
    menu_action = plugin.menu_actions[0]

    plugin.unload()
    qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert plugin.toolbar_actions == []
    assert plugin.menu_actions == []
    assert plugin.act_new is None
    assert sip.isdeleted(toolbar_action)
    assert sip.isdeleted(menu_action)


def test_line_velocity_requested_reports_that_no_dialog_exists_yet(fake_iface):
    # Finding 2 (review round 1): this signal was emitted by the context
    # menu's "Set velocity override..." action but never connected to
    # anything -- a permanent, silent no-op with no message, no log line,
    # nothing. Now routed to the same message-bar-stub pattern as
    # open_grid_dialog/open_import_dialog.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.survey_dock.line_velocity_requested.emit("raw/FILE__001.DZT")
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "elocity" in item.text()
    plugin.unload()


def test_unload_does_not_offer_a_cancel_that_would_be_ignored(fake_iface, tmp_path, answer_modal):
    # Finding 1 (review round 1): unload() cannot veto QGIS unloading the
    # plugin, so a "Save / Discard / Cancel" prompt whose Cancel answer
    # is then silently discarded would let a user press a button labelled
    # Cancel and lose the site anyway. Pin the button set directly rather
    # than trust that no one re-adds Cancel later.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)
    assert plugin.session.dirty

    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()

    assert len(calls) == 1
    buttons = calls[0][0][3]
    assert buttons & QMessageBox.StandardButton.Save
    assert buttons & QMessageBox.StandardButton.Discard
    assert not (buttons & QMessageBox.StandardButton.Cancel)
    assert plugin.survey_dock is None  # unload proceeded regardless of the answer


def test_unload_saves_a_dirty_site_when_the_user_chooses_save(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)
    session = plugin.session  # plugin.session is None after unload(); keep our own handle
    assert session.dirty

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Save)
    plugin.unload()

    assert not session.dirty
    assert plugin.session is None


def test_unload_warns_explicitly_when_the_chosen_save_then_fails(
    fake_iface, tmp_path, answer_modal, monkeypatch
):
    # Finding 1's other half: Save was chosen, but the save itself fails.
    # unload() cannot retry or abort at that point (QGIS is unloading the
    # plugin regardless), so the failure must be reported as data loss,
    # not merely as "could not save the site" -- a message identical to
    # save_with_prompt()'s normal failure message would not tell the user
    # their edits are gone rather than merely unsaved-for-now.
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)

    def boom(**_kw):
        raise OSError("simulated disk-full error")

    monkeypatch.setattr(plugin.session, "save", boom)
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Save)
    plugin.unload()  # must not raise or hang despite the failed save

    assert plugin.survey_dock is None  # unload still proceeded
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "unsaved changes will be lost" in item.text()


# ---- final review, C4: "New site" and "Open site" must protect unsaved
# work the way unload() already does. Deleting each of their
# `if self.session.dirty and not self.save_with_prompt(ask_first=True)`
# guards left the whole qgis tier green at 357 passed, and so did
# deleting save_with_prompt()'s own `allow_cancel and answer == Cancel ->
# return False`. open_site() had no test at all; new_site()'s one test ran
# against a clean session, so the guard short-circuited before it was ever
# exercised. What is lost is grids, line placements and processing stacks
# -- the survey source of truth. Six tests, mirroring the unload trio
# above: Cancel aborts, Discard proceeds without saving, Save writes
# first. -------------------------------------------------------------


def _plugin_with_a_dirty_site(fake_iface, root):
    """The unload trio's own setup, factored out: a plugin with a real
    site open and one unsaved grid in it."""
    import nsgeo_qgis

    root.mkdir(parents=True, exist_ok=True)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(root)  # writes survey.nsgeo.json with no grids
    plugin.session.add_grid(GRID)
    assert plugin.session.dirty
    return plugin


def _grid_ids_on_disk(root):
    return [g["id"] for g in json.loads((root / SURVEY_FILE).read_text())["grids"]]


def test_new_site_cancelled_leaves_the_dirty_site_exactly_as_it_was(
    fake_iface, tmp_path, answer_modal
):
    plugin = _plugin_with_a_dirty_site(fake_iface, tmp_path)
    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Cancel)

    plugin.new_site()

    # Cancel means cancel: the same site is still open, still dirty, still
    # holding the grid that made it dirty, and nothing was written.
    assert plugin.session.root == tmp_path.resolve()
    assert plugin.session.dirty
    assert [g.id for g in plugin.session.site.grids] == ["A"]
    assert _grid_ids_on_disk(tmp_path) == []
    # And the folder chooser was never reached. That assertion is free
    # rather than absent: conftest's `_no_unhandled_modals` turns an
    # unexpected `QFileDialog.getExistingDirectory` into an AssertionError,
    # and new_site() calls it outside its own try/except, so a guard that
    # let execution through would come straight back out of the call above
    # instead of being caught and reported as "could not create the new
    # site".
    assert len(calls) == 1
    buttons = calls[0][0][3]
    assert buttons & QMessageBox.StandardButton.Save
    assert buttons & QMessageBox.StandardButton.Discard
    # Unlike unload()'s prompt (pinned above as *not* offering Cancel),
    # this one genuinely can abort its own action, so Cancel belongs here.
    assert buttons & QMessageBox.StandardButton.Cancel
    plugin.unload()


def test_new_site_discarding_abandons_the_old_site_without_saving_it(
    fake_iface, tmp_path, monkeypatch, answer_modal
):
    plugin = _plugin_with_a_dirty_site(fake_iface, tmp_path / "first")
    fresh = tmp_path / "second"
    fresh.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(fresh))
    )
    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)

    plugin.new_site()

    assert len(calls) == 1
    assert plugin.session.root == fresh.resolve()
    assert [g.id for g in plugin.session.site.grids] == []
    # Discard has to mean discard just as literally as Cancel means
    # cancel: the abandoned site must not have been quietly saved on the
    # way out.
    assert _grid_ids_on_disk(tmp_path / "first") == []
    plugin.unload()


def test_new_site_saves_the_old_site_first_when_the_user_chooses_save(
    fake_iface, tmp_path, monkeypatch, answer_modal
):
    plugin = _plugin_with_a_dirty_site(fake_iface, tmp_path / "first")
    fresh = tmp_path / "second"
    fresh.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(fresh))
    )
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Save)

    plugin.new_site()

    assert plugin.session.root == fresh.resolve()
    # The grid reached disk before the switch, not after it: the old
    # session object is gone by now, so this is the only place it could
    # have been written.
    assert _grid_ids_on_disk(tmp_path / "first") == ["A"]
    plugin.unload()


def test_open_site_cancelled_leaves_the_dirty_site_exactly_as_it_was(
    fake_iface, tmp_path, answer_modal
):
    plugin = _plugin_with_a_dirty_site(fake_iface, tmp_path / "first")
    other = SiteSession()
    (tmp_path / "second").mkdir()
    other.new_site(tmp_path / "second")
    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Cancel)

    plugin.open_site()

    assert plugin.session.root == (tmp_path / "first").resolve()
    assert plugin.session.dirty
    assert [g.id for g in plugin.session.site.grids] == ["A"]
    assert _grid_ids_on_disk(tmp_path / "first") == []
    # As in the new_site case above: `QFileDialog.getOpenFileName` is
    # forbidden by default in this tier, so "the file chooser was never
    # reached" is asserted by the call not raising.
    assert len(calls) == 1
    buttons = calls[0][0][3]
    assert buttons & QMessageBox.StandardButton.Save
    assert buttons & QMessageBox.StandardButton.Discard
    assert buttons & QMessageBox.StandardButton.Cancel
    plugin.unload()


def test_open_site_discarding_abandons_the_old_site_without_saving_it(
    fake_iface, tmp_path, monkeypatch, answer_modal
):
    plugin = _plugin_with_a_dirty_site(fake_iface, tmp_path / "first")
    other = SiteSession()
    (tmp_path / "second").mkdir()
    other.new_site(tmp_path / "second")
    target = tmp_path / "second" / SURVEY_FILE
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)

    plugin.open_site()

    assert len(calls) == 1
    assert plugin.session.root == (tmp_path / "second").resolve()
    assert _grid_ids_on_disk(tmp_path / "first") == []
    plugin.unload()


def test_open_site_saves_the_old_site_first_when_the_user_chooses_save(
    fake_iface, tmp_path, monkeypatch, answer_modal
):
    plugin = _plugin_with_a_dirty_site(fake_iface, tmp_path / "first")
    other = SiteSession()
    (tmp_path / "second").mkdir()
    other.new_site(tmp_path / "second")
    target = tmp_path / "second" / SURVEY_FILE
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Save)

    plugin.open_site()

    assert plugin.session.root == (tmp_path / "second").resolve()
    assert _grid_ids_on_disk(tmp_path / "first") == ["A"]
    plugin.unload()


# ---- final review, I8: the survey tree's context menu was dead to the
# suite. `menu.exec` could be replaced with `pass` and all 364 tests
# passed, so which actions appear for a site, a grid or a line, and the
# lambda wiring each one to its slot, were unverified -- the same defect
# class as this branch's own "menu whose entire click path was dead while
# 22 tests passed", except that here the path was never even entered.
# Both destructive confirmations survived removal too (364 passed each):
# every existing test calls remove_line_action/remove_grid_action with
# confirm=False, which bypasses the gate outright, so answering anything
# but Yes still removed the line -- and session.remove_line drops the
# line's processing stack with it. ------------------------------------


def _action(menu, text):
    return next(a for a in menu.actions() if a.text() == text)


def _texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _right_click(dock, item):
    """Right-click `item` (or empty space, for None) and return the menu
    that was built for it.

    Goes through the real `customContextMenuRequested` signal rather than
    calling the slot, so the connection is pinned too; the caller must
    have installed `answer_modal(QMenu, "exec", None)` first, since this
    tier forbids the real `QMenu.exec` (it would block forever offscreen).
    """
    pos = dock.tree.visualItemRect(item).center() if item is not None else QPoint(0, 10_000)
    dock.tree.customContextMenuRequested.emit(pos)
    return dock.context_menu


def test_the_context_menu_offers_the_right_actions_for_each_kind_of_item(
    dock, answer_modal, message_log
):
    session, dock = dock
    exec_calls = answer_modal(QMenu, "exec", None)
    root = dock.tree.topLevelItem(0)
    grid_item, line_item = root.child(0), root.child(0).child(0)
    menu = dock.context_menu

    assert _texts(_right_click(dock, root)) == ["Add grid…"]
    # Empty space below the tree is the site's menu too -- there is
    # nowhere else to reach "Add grid…" from when the site has no grids.
    assert _texts(_right_click(dock, None)) == ["Add grid…"]

    assert _texts(_right_click(dock, grid_item)) == [
        "Edit grid…",
        "Import DZT files…",
        "Set velocity…",
        "Remove grid",
    ]
    assert menu.actions()[-2].isSeparator()  # the destructive one stands apart

    assert _texts(_right_click(dock, line_item)) == [
        "Open",
        "Set velocity override…",
        "Remove line from site",
    ]
    assert menu.actions()[-2].isSeparator()

    # exec() was actually reached, at the right place, once per
    # right-click: replacing it with `pass` leaves the menu built and
    # correct but never shown, which is exactly how this path stayed dead.
    assert len(exec_calls) == 4
    assert exec_calls[-1][0] == (
        dock.tree.viewport().mapToGlobal(dock.tree.visualItemRect(line_item).center()),
    )
    # One menu throughout, not one per right-click (see its comment in
    # __init__), and nothing was swallowed: _on_context_menu wraps its
    # whole body in `except Exception -> _log`, so a failure in there --
    # including this tier's own forbidden-modal AssertionError -- would be
    # written to the message log instead of reaching this test.
    assert dock.context_menu is menu
    assert message_log == []


def test_every_context_menu_action_is_wired_to_the_slot_it_names(dock, answer_modal, message_log):
    session, dock = dock
    answer_modal(QMenu, "exec", None)
    # Both destructive actions are triggered for real below; No is the
    # answer, so this test proves the wiring and the next two prove the
    # gate.
    questions = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.No)
    root = dock.tree.topLevelItem(0)
    grid_item, line_item = root.child(0), root.child(0).child(0)
    key = dock.key_of(line_item)
    fired: list[tuple[str, object]] = []
    dock.add_grid_requested.connect(lambda: fired.append(("add_grid", None)))
    dock.edit_grid_requested.connect(lambda g: fired.append(("edit_grid", g)))
    dock.import_requested.connect(lambda g: fired.append(("import", g)))
    dock.grid_velocity_requested.connect(lambda g: fired.append(("grid_velocity", g)))
    dock.line_velocity_requested.connect(lambda k: fired.append(("line_velocity", k)))

    _action(_right_click(dock, root), "Add grid…").trigger()
    menu = _right_click(dock, grid_item)
    for text in ("Edit grid…", "Import DZT files…", "Set velocity…", "Remove grid"):
        _action(menu, text).trigger()
    menu = _right_click(dock, line_item)
    for text in ("Open", "Set velocity override…", "Remove line from site"):
        _action(menu, text).trigger()

    assert fired == [
        ("add_grid", None),
        ("edit_grid", "A"),
        ("import", "A"),
        ("grid_velocity", "A"),
        ("line_velocity", key),
    ]
    assert session.current_key == key  # "Open" went through _open_line
    assert len(questions) == 2  # "Remove grid" and "Remove line from site"
    assert [g.id for g in session.site.grids] == ["A"]
    assert key in session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
    assert message_log == []


def test_removing_a_line_from_the_menu_takes_no_for_an_answer(dock, answer_modal, message_log):
    session, dock = dock
    key = "raw/FILE__001.DZT"
    session.append_step(key, build_step("dewow"))
    answer_modal(QMenu, "exec", None)
    no = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.No)

    _action(_right_click(dock, dock.item_for_key(key)), "Remove line from site").trigger()

    assert len(no) == 1
    assert key in session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
    # The stack matters as much as the line: session.remove_line() drops
    # the line's processing stack with it, and a stack is authored work
    # that nothing else on disk holds until the next save.
    assert [entry[0].name for entry in session.stack_for(key).entries] == ["dewow"]
    assert message_log == []

    # ...and Yes still removes it, so the assertions above are about the
    # answer rather than about the action never doing anything.
    yes = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
    _action(_right_click(dock, dock.item_for_key(key)), "Remove line from site").trigger()
    assert len(yes) == 1
    assert key not in session.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
    assert key not in session.site.stacks


def test_removing_a_grid_from_the_menu_takes_no_for_an_answer(dock, answer_modal, message_log):
    session, dock = dock
    # A grid with no lines in it: remove_grid refuses one that still has
    # lines for an unrelated reason, which would make "nothing was
    # removed" true whatever the answer was.
    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    answer_modal(QMenu, "exec", None)
    no = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.No)
    b_item = dock.tree.topLevelItem(0).child(1)
    assert dock.grid_id_of(b_item) == "B"

    _action(_right_click(dock, b_item), "Remove grid").trigger()

    assert len(no) == 1
    assert [g.id for g in session.site.grids] == ["A", "B"]
    assert message_log == []

    yes = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
    b_item = dock.tree.topLevelItem(0).child(1)
    _action(_right_click(dock, b_item), "Remove grid").trigger()
    assert len(yes) == 1
    assert [g.id for g in session.site.grids] == ["A"]
