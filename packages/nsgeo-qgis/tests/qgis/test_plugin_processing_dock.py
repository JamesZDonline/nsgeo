from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import available_steps
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.processing_dock import ProcessingDock, dest_index
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import QModelIndex, Qt
from qgis.PyQt.QtWidgets import QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5)))
    session.add_lines(lines)
    key = session.keys()[0]
    session.set_profiles(key, lines[0].load())
    session.open_line(key)
    return session, dock, key


def test_add_menu_lists_the_registry_and_marks_required_steps(opened):
    _, dock, _ = opened
    texts = [a.text() for a in dock.add_menu.actions()]
    assert [t.split(" ")[0] for t in texts] == available_steps()
    assert any(t.startswith("bandpass") and "needs values" in t for t in texts)
    assert not any(t.startswith("dewow") and "needs values" in t for t in texts)


def test_add_menu_action_triggers_add_step(opened):
    """`QMenu.addAction(text, slot)` binds the zero-argument `triggered()`
    overload as an implementation detail of that convenience form, not
    documented API -- and neither venv in this repo has PyQt6 to check
    the other leg. `test_add_menu_lists_the_registry_...` above only reads
    `action.text()`; it never actually fires a menu action, so the dock's
    primary path (click "Add step" -> a step appears) was completely
    unexercised. Triggers two real actions, found by name so a registry
    reordering can't silently repoint the assertions: `dewow` (built
    immediately) and `bandpass` (REQUIRED params, so requested instead).

    A single-line regression this pins directly: swapping the lambda's
    body to `self.add_step(checked)` (passing the bool instead of the
    captured name) would raise inside `required_params`/`get_step` for a
    name that isn't a string, which the slot swallows to stderr -- no
    step would be added and `asked` would stay empty, and both
    assertions below would fail.
    """
    session, dock, key = opened
    asked: list[str] = []
    dock.add_step_requested.connect(asked.append)

    def action_named(name: str):
        return next(a for a in dock.add_menu.actions() if a.text().split(" ")[0] == name)

    action_named("dewow").trigger()
    assert [s.name for s, _ in session.stack_for(key).entries] == ["dewow"]

    action_named("bandpass").trigger()
    assert asked == ["bandpass"]
    assert len(session.stack_for(key)) == 1  # bandpass needs a form first, still not built


def test_add_remove_toggle_and_reorder(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    dock.add_step("background_mean")
    dock.add_step("gain_agc")
    assert [dock.list.item(i).text() for i in range(3)] == ["dewow", "background_mean", "gain_agc"]
    dock.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert session.stack_for(key).entries[1][1] is False
    dock.list.setCurrentRow(2)
    dock.move_selected(-1)
    assert [s.name for s, _ in session.stack_for(key).entries] == [
        "dewow",
        "gain_agc",
        "background_mean",
    ]
    assert dock.list.currentRow() == 1
    dock.remove_selected()
    assert [s.name for s, _ in session.stack_for(key).entries] == ["dewow", "background_mean"]


def test_required_steps_are_requested_not_built(opened):
    session, dock, key = opened
    asked = []
    dock.add_step_requested.connect(asked.append)
    dock.add_step("bandpass")
    assert asked == ["bandpass"] and len(session.stack_for(key)) == 0


def test_selection_emits_and_rebuild_keeps_it(opened):
    session, dock, key = opened
    got = []
    dock.step_selected.connect(got.append)
    dock.add_step("dewow")
    dock.add_step("gain_agc")
    dock.list.setCurrentRow(1)
    assert got[-1] == 1
    session.set_step_enabled(key, 0, False)  # triggers rebuild
    assert dock.list.currentRow() == 1


def test_updating_guard_survives_a_nested_rebuild(opened):
    """`_updating` guards `_on_item_changed`/`_on_current_row` against the
    list edits `rebuild()` itself makes. Task 17 connects `step_selected`
    (emitted at the end of `rebuild()`) to a parameter form that can write
    back to the session, which can trigger a *nested* `rebuild()` while
    the outer one is still running. A plain set/clear boolean can't tell
    "the inner call finished" from "the whole guard is done": the inner
    call's own `finally` would clear the flag out from under the still-
    running outer call. Simulated directly (without building Task 17's
    form): mark a rebuild already in progress, run a full one through it,
    and check the guard is still up afterwards -- exactly the state the
    outer frame would be left in if this were the inner of two nested
    calls.

    Fails under exactly one single-line reversion: changing
    `self._updating += 1` / `self._updating -= 1` in `rebuild()` back to
    `self._updating = True` / `= False`.
    """
    _, dock, _ = opened
    dock._updating += 1  # simulate: already inside an outer rebuild
    try:
        dock.rebuild()
        assert dock._updating  # outer guard must still be active
    finally:
        dock._updating -= 1  # tidy up so later tests don't see a wedged dock


def test_dest_index_matches_qt_rows_moved_semantics():
    assert dest_index(start=0, row=3) == 2  # moved down past two rows
    assert dest_index(start=3, row=0) == 0  # moved up to the top
    assert dest_index(start=1, row=1) == 1


def test_on_rows_moved_uses_dest_index_not_the_raw_row(opened):
    """`_on_rows_moved` must translate Qt's `row` through `dest_index`
    before calling `session.move_step`. `QTest` cannot drive a real
    internal `QListWidget` drag under the offscreen platform (verified
    directly: synthetic mouse press/move/release on the viewport produces
    no `rowsMoved` at all) -- but the model can be driven directly instead
    of the mouse: `model().moveRow(parent, 0, parent, 3)` is a real move
    (verified directly: it returns `True` and emits a real `rowsMoved`,
    while `dest=1`/`dest=2` -- the tie and one-past-it -- both return
    `False` and emit nothing), which exercises the actual
    `rowsMoved -> _on_rows_moved` connection end to end rather than
    fabricating the slot's call.

    Fails under exactly one single-line substitution: replacing
    `self.session.move_step(key, start, dst)` with
    `self.session.move_step(key, start, row)` -- every downward drag
    would then land one slot too far, and no other test would notice.
    """
    session, dock, key = opened
    for name in ("dewow", "background_mean", "gain_agc", "time_zero"):
        dock.add_step(name)
    parent = QModelIndex()
    moved = dock.list.model().moveRow(parent, 0, parent, 3)
    assert moved
    assert [s.name for s, _ in session.stack_for(key).entries] == [
        "background_mean",
        "gain_agc",
        "dewow",
        "time_zero",
    ]


def test_apply_to_grid_copies_to_the_other_lines(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    changed = dock.apply_to_grid(confirm=False)
    assert len(changed) == 2
    for other in changed:
        assert session.stack_for(other).to_dicts() == session.stack_for(key).to_dicts()
    assert "2 line" in dock.status.text()


def test_status_message_clears_when_the_line_switches(opened):
    """ "applied to 2 line(s) in grid A" is the one piece of state this
    dock keeps locally rather than reading from the session; left alone
    it survives a switch to a line it says nothing true about. Fails if
    `rebuild()`'s `self.status.setText("")` is removed.
    """
    session, dock, key = opened
    dock.add_step("dewow")
    dock.apply_to_grid(confirm=False)
    assert dock.status.text() != ""
    other = session.keys()[1]
    session.open_line(other)
    assert dock.status.text() == ""


def test_switching_lines_shows_that_lines_stack(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    other = session.keys()[1]
    session.open_line(other)
    assert dock.list.count() == 0
    session.open_line(key)
    assert dock.list.count() == 1


def test_no_line_disables_the_controls(qgis_app):
    dock = ProcessingDock(SiteSession())
    assert not dock.add_button.isEnabled()
    assert not dock.apply_button.isEnabled()
    assert not dock.remove_button.isEnabled()
    assert not dock.up_button.isEnabled()
    assert not dock.down_button.isEnabled()


def test_apply_button_click_confirms_before_applying(opened, answer_modal):
    """`apply_button.clicked` carries a `bool checked` argument. Connecting
    it straight to `apply_to_grid` (whose only parameter is `confirm: bool
    = True`) would let Qt's own argument-trimming hand that `checked`
    value to `confirm` -- verified directly: a `clicked` signal wired to a
    one-bool-defaulted-parameter slot is invoked with `checked=False` --
    which would silently skip the confirmation prompt on every real click
    and overwrite every other line in the grid with no way to back out.
    Pins the wiring that avoids that: a real click must still ask, and
    declining must leave every other line's stack untouched and say so
    rather than leave the caption blank.
    """
    session, dock, key = opened
    dock.add_step("dewow")
    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.No)
    dock.apply_button.click()
    assert len(calls) == 1
    other = session.keys()[1]
    assert len(session.stack_for(other)) == 0
    assert "cancelled" in dock.status.text()
