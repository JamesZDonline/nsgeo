from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import available_steps, build_step, get_step, is_unipolar
from nsgeo.velocity import VelocityModel
from nsgeo_qgis import step_inputs
from nsgeo_qgis.line_edit import LineEdit
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.param_form import RowSpinBox
from nsgeo_qgis.ui.processing_dock import (
    PREVIEW_SUFFIX,
    REFUSAL_COLOUR,
    REFUSAL_TEXT,
    ProcessingDock,
    dest_index,
    needs_dialog,
)
from nsgeo_qgis.ui.warnings_panel import REFUSAL, Entry
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.PyQt.QtCore import QCoreApplication, QModelIndex, Qt
from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import QDialog, QDoubleSpinBox, QMessageBox, QWidgetAction

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


def _menu_layout(menu):
    """The Add step menu as [(heading, [step id, ...]), ...]."""
    layout = []
    for action in menu.actions():
        if isinstance(action, QWidgetAction):
            layout.append((action.defaultWidget().text(), []))
        elif not action.isSeparator():
            layout[-1][1].append(action.data())
    return layout


def _step_actions(menu):
    return [a for a in menu.actions() if not a.isSeparator() and a.data()]


def test_add_menu_is_grouped_in_processing_order(opened):
    """#82: headed groups in the usual processing flow, not the registry's
    ids in alphabetical order. The amplitude transforms are not offered:
    the user makes slices with them, never profiles, and the Slices
    panel's Transform combo offers them there."""
    _, dock, _ = opened
    assert _menu_layout(dock.add_menu) == [
        ("Time", ["time_zero", "time_cutoff"]),
        ("Filters", ["dewow", "bandpass", "trace_stack"]),
        ("Background", ["background_mean", "background_sliding", "background_svd"]),
        ("Migration", ["migrate_fk"]),
        ("Gain", ["gain_curve", "gain_agc", "gain_parametric"]),
    ]


def test_add_menu_offers_every_registered_step_but_the_slice_transforms(opened):
    """Still the registry, not a list: a step added to the core appears here."""
    _, dock, _ = opened
    offered = [name for _, names in _menu_layout(dock.add_menu) for name in names]
    assert sorted(offered) == [n for n in available_steps() if not is_unipolar(get_step(n))]


def test_add_menu_shows_titles_and_an_ellipsis_only_where_a_dialog_opens(opened):
    _, dock, _ = opened
    texts = {a.data(): a.text() for a in _step_actions(dock.add_menu)}
    assert texts["bandpass"] == "Bandpass…"
    assert texts["gain_agc"] == "Automatic gain control"
    # These two add straight away, seeded from the record: no dialog, so no
    # promise of one.
    assert texts["time_cutoff"] == "Time cutoff"
    assert texts["gain_curve"] == "Gain curve"
    assert all(text.endswith("…") == needs_dialog(name) for name, text in texts.items())


def test_add_menu_headings_draw_on_every_style_and_cannot_be_chosen(opened):
    """`QMenu.addSection` leaves its text to the style, and the Windows
    styles draw a bare separator instead (rendered under Qt's "Windows"
    style for #82's mock-up), so the group names would vanish on the
    machines the plugin is demonstrated on. A label drawn by the plugin
    shows on every style."""
    _, dock, _ = opened
    actions = dock.add_menu.actions()
    headings = [a for a in actions if isinstance(a, QWidgetAction)]
    assert [h.defaultWidget().text() for h in headings] == [
        "Time",
        "Filters",
        "Background",
        "Migration",
        "Gain",
    ]
    assert not any(h.isEnabled() for h in headings)
    assert not any(a.isSeparator() and a.text() for a in actions)  # no addSection


def test_add_menu_headings_draw_in_the_text_colour_not_the_disabled_grey(opened):
    """A disabled action disables its label too, and the disabled grey read
    as ghostly in the walkthrough. The heading stays unchoosable but draws
    bold in the menu's ordinary text colour."""
    _, dock, _ = opened
    for heading in (a for a in dock.add_menu.actions() if isinstance(a, QWidgetAction)):
        label = heading.defaultWidget()
        assert not label.isEnabled()
        palette = label.palette()
        drawn = palette.color(QPalette.ColorGroup.Disabled, label.foregroundRole())
        assert drawn == palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText)
        assert label.font().bold()


def test_add_menu_action_triggers_add_step(opened, drive_dialog):
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

    Since Task 17 the dock also listens to its own `add_step_requested`
    and opens `AddStepDialog` from it, so triggering the `bandpass` action
    really does open a modal. This test drives that dialog (and cancels
    it) rather than leaving it to `_no_unhandled_modals`: that guard's
    AssertionError is raised inside a slot, where PyQt cannot propagate it
    back here -- it printed a traceback, this test passed anyway, and CI's
    PyQt build aborted the process on the same emission. See conftest's
    `_no_swallowed_slot_exceptions`, which now makes that state a failure.
    """
    session, dock, key = opened
    asked: list[str] = []
    dock.add_step_requested.connect(asked.append)
    shown = drive_dialog(QDialog, "exec", lambda d: d.reject())

    def action_named(name: str):
        return next(a for a in _step_actions(dock.add_menu) if a.data() == name)

    action_named("dewow").trigger()
    assert [s.name for s, _ in session.stack_for(key).entries] == ["dewow"]
    assert shown == []  # dewow has no required params: nothing to ask for

    action_named("bandpass").trigger()
    assert asked == ["bandpass"]
    # The request really reached add_step_with_dialog and opened the
    # dialog; cancelling it is what leaves the step unbuilt.
    assert [type(d).__name__ for d in shown] == ["AddStepDialog"]
    assert len(session.stack_for(key)) == 1  # bandpass needs a form first, still not built


def test_add_remove_toggle_and_reorder(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    dock.add_step("background_mean")
    dock.add_step("gain_agc")
    assert [dock.list.item(i).text() for i in range(3)] == [
        "Dewow",
        "Background removal (mean)",
        "Automatic gain control",
    ]
    # The id stays one hover away, to match a project file or a help page.
    assert [dock.list.item(i).toolTip() for i in range(3)] == [
        "dewow",
        "background_mean",
        "gain_agc",
    ]
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


def test_required_steps_are_requested_not_built(opened, drive_dialog):
    """`add_step` must never build a REQUIRED-params step itself.

    The dialog the request opens is driven and cancelled here for the same
    reason as `test_add_menu_action_triggers_add_step` above: the modal
    opens inside a slot, so the guard's AssertionError could not reach
    this test and the emission aborted CI instead.
    """
    session, dock, key = opened
    asked = []
    dock.add_step_requested.connect(asked.append)
    shown = drive_dialog(QDialog, "exec", lambda d: d.reject())
    dock.add_step("bandpass")
    assert asked == ["bandpass"] and len(session.stack_for(key)) == 0
    assert [type(d).__name__ for d in shown] == ["AddStepDialog"]


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


def test_adding_a_time_cutoff_seeds_the_record_end_and_changes_nothing(opened):
    session, dock, key = opened
    t0, dt, n = dock.time_axis()
    dock.add_step("time_cutoff")
    stack = session.stack_for(key)
    assert stack.entries[-1][0].params["end_ns"] == pytest.approx(t0 + n * dt)
    assert stack.result().n_samples == n
    assert dock.list.currentRow() == len(stack) - 1


def test_the_cutoff_spinbox_spans_the_record_as_the_cutoff_step_receives_it(opened):
    session, dock, key = opened
    session.append_step(key, build_step("time_zero", mode="sample", sample=5))
    dock.add_step("time_cutoff")
    zeroed = session.stack_for(key).intermediate(0)
    assert zeroed.n_samples < session.stack_for(key).source.n_samples
    spin = dock.form.editors["end_ns"]
    assert isinstance(spin, QDoubleSpinBox)
    assert spin.minimum() == pytest.approx(zeroed.t0_ns + zeroed.dt_ns)
    assert spin.maximum() == pytest.approx(zeroed.t0_ns + zeroed.n_samples * zeroed.dt_ns)
    assert spin.singleStep() == pytest.approx(zeroed.dt_ns)


def _unloaded(qgis_app, tmp_path):
    """A line opened before its samples arrive (stack.source is None), with a
    time_zero step ahead of anything the test adds."""
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.open_line(key)
    assert session.stack_for(key).source is None
    session.append_step(key, build_step("time_zero", mode="sample", sample=5))
    return session, dock, key, line


def test_a_time_field_behind_time_zero_is_unbounded_until_the_samples_load(qgis_app, tmp_path):
    session, dock, key, line = _unloaded(qgis_app, tmp_path)
    dock.add_step("time_cutoff")
    h = session.line_for_key(key).header
    spin = dock.form.editors["end_ns"]
    # No source, so no clock to bound by: not the radar-clock range of the header.
    assert spin.maximum() != pytest.approx(h.position_ns + h.n_samples * h.dt_ns)
    assert spin.maximum() > 1e6
    session.set_profiles(key, line.load())
    stack = session.stack_for(key)
    zeroed = stack.intermediate(0)
    spin = dock.form.editors["end_ns"]
    assert spin.minimum() == pytest.approx(zeroed.t0_ns + zeroed.dt_ns)
    assert spin.maximum() == pytest.approx(zeroed.t0_ns + zeroed.n_samples * zeroed.dt_ns)


def test_a_cutoff_added_behind_time_zero_before_the_samples_load_crops_nothing(qgis_app, tmp_path):
    session, dock, key, line = _unloaded(qgis_app, tmp_path)
    dock.add_step("time_cutoff")
    session.set_profiles(key, line.load())
    stack = session.stack_for(key)
    assert stack.result().n_samples == stack.intermediate(0).n_samples


def test_a_line_loading_again_leaves_a_bounded_form_alone(opened):
    session, dock, key = opened
    dock.add_step("time_cutoff")
    spin = dock.form.editors["end_ns"]
    spin.lineEdit().setText("7.5")
    session.line_loaded.emit(key)
    assert dock.form.editors["end_ns"] is spin
    assert spin.lineEdit().text() == "7.5"


def test_the_cutoff_spinbox_range_for_a_first_step_is_the_source(opened):
    session, dock, key = opened
    dock.add_step("time_cutoff")
    src = session.stack_for(key).source
    spin = dock.form.editors["end_ns"]
    assert spin.minimum() == pytest.approx(src.t0_ns + src.dt_ns)
    assert spin.maximum() == pytest.approx(src.t0_ns + src.n_samples * src.dt_ns)


def test_the_cutoff_spinbox_falls_back_to_the_source_when_an_earlier_step_fails(
    opened, message_log
):
    session, dock, key = opened
    session.append_step(key, build_step("bandpass", low_mhz=100.0, high_mhz=600.0))
    dock.add_step("time_cutoff")
    src = session.stack_for(key).source
    # Break the earlier step after the fact: a high cut past Nyquist.
    session.replace_step(key, 0, build_step("bandpass", low_mhz=100.0, high_mhz=1e9))
    dock.list.setCurrentRow(0)
    dock.list.setCurrentRow(1)
    spin = dock.form.editors["end_ns"]
    assert spin.maximum() == pytest.approx(src.t0_ns + src.n_samples * src.dt_ns)
    assert any("does not evaluate cleanly" in m for m in message_log)


# ---- migration (#123) ----------------------------------------------------


def test_migration_is_addable_to_a_stack_that_already_corrects_time_zero(opened):
    """The blocker, and it is not migration's fault.

    `build_add_dialog` probed `stack_for(key).source` -- the RAW radargram,
    `t0 = -11.09` on every real file -- while `AddStepDialog._validate`
    applies the candidate step to one trace of it on every keystroke. So
    migration's time-zero refusal fired and OK stayed disabled even with
    `time_zero` already first in the stack. `ProcessingDock.time_axis`
    already defines this quantity as the stack's own `result()`, "exactly
    as the new step's own `apply()` will see it"; the probe was the one
    place reaching for `source`.
    """
    session, dock, key = opened
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))

    dialog = dock.build_add_dialog("migrate_fk")
    dialog.form.set_value("velocity_m_ns", "0.0733")

    assert dialog.form.message.text() == ""
    assert dialog.ok_button.isEnabled()


def test_the_velocity_is_prefilled_from_the_line(opened):
    """`resolve_velocity`'s existing chain, so the prefill is the same
    number the depth axis and every pick already use. With no line
    override and no grid model, that is the header's dielectric: epsr 14
    on these files, which is 0.0801 m/ns."""
    _, dock, _ = opened

    dialog = dock.build_add_dialog("migrate_fk")

    assert dialog.form.values()["velocity_m_ns"] == pytest.approx(0.0801, abs=5e-5)


def test_the_prefill_follows_a_line_velocity_override(opened):
    """A line that carries a measured velocity starts there instead."""
    session, dock, key = opened
    session.set_line_velocity(key, VelocityModel.constant(0.0733))

    dialog = dock.build_add_dialog("migrate_fk")

    assert dialog.form.values()["velocity_m_ns"] == pytest.approx(0.0733)


def test_the_prefill_is_a_seed_not_a_link(opened):
    """Prefill only: once the step exists the value is its own, and a later
    velocity change does not reach back into it."""
    session, dock, key = opened
    session.append_step(key, build_step("migrate_fk", velocity_m_ns=0.0733))

    session.set_line_velocity(key, VelocityModel.constant(0.0900))

    step, _ = session.stack_for(key).entries[0]
    assert step.params["velocity_m_ns"] == pytest.approx(0.0733)


def test_the_step_row_says_when_its_velocity_is_not_this_lines(opened):
    """The hazard in a prefilled value is not being wrong, it is being
    silent: a velocity frozen three lines ago looks identical to one that
    belongs to the open line. 0.0733 against this line's 0.0801 is 8.5%
    apart -- both literals, neither computed from the threshold."""
    session, dock, key = opened
    session.append_step(key, build_step("migrate_fk", velocity_m_ns=0.0733))

    text = dock.list.item(0).text()

    assert "0.0733 m/ns" in text
    assert "this line says 0.0801" in text


def test_the_step_row_says_nothing_when_they_agree(opened):
    """0.0810 against this line's 0.0801 is 1.1% apart -- a different
    number, inside the band, so no read-out. A threshold that fired on any
    difference at all would fire on every step ever added."""
    session, dock, key = opened
    session.append_step(key, build_step("migrate_fk", velocity_m_ns=0.0810))

    text = dock.list.item(0).text()

    assert "0.0810 m/ns" in text
    assert "this line says" not in text


def test_a_step_without_a_velocity_keeps_its_plain_title(opened):
    session, dock, key = opened
    session.append_step(key, build_step("dewow"))

    assert dock.list.item(0).text() == "Dewow"


def _unresolvable(session, monkeypatch):
    """A header with epsr 0 loads fine and makes `resolved_velocity` raise
    when anything asks for the line's velocity."""

    def boom(key):
        raise ValueError("relative dielectric permittivity must be positive, got 0.0")

    monkeypatch.setattr(session, "resolved_velocity", boom)


def test_a_line_whose_velocity_cannot_be_resolved_still_lists_its_steps(opened, monkeypatch):
    """`rebuild` runs inside a Qt slot, after `list.clear()` and before the
    row buttons are updated. An exception there is swallowed to stderr and
    leaves the panel showing no steps for a line that has them."""
    session, dock, key = opened
    # The synthetic record starts before time zero, which migration refuses
    # (and the list now marks): a Time zero step ahead keeps this row plain.
    session.append_step(key, build_step("time_zero"))
    session.append_step(key, build_step("migrate_fk", velocity_m_ns=0.0733))
    _unresolvable(session, monkeypatch)

    dock.rebuild()

    assert dock.list.count() == 2
    assert dock.list.item(1).text() == "Migration (Stolt f-k)"


def test_a_line_whose_velocity_cannot_be_resolved_still_opens_the_add_dialog(opened, monkeypatch):
    """The prefill is a convenience. A line that cannot supply one must
    still be able to have a step added to it, with the field left blank."""
    session, dock, key = opened
    _unresolvable(session, monkeypatch)

    dialog = dock.build_add_dialog("migrate_fk")

    assert not dialog.ok_button.isEnabled()
    assert dialog.form.editors["velocity_m_ns"].text() == ""


def test_a_cut_shows_that_processing_does_not_apply(opened):
    from nsgeo_qgis.ui.processing_dock import PROCESSING_ON_CUT_TEXT

    session, dock, key = opened
    assert dock.list.count() == 0 or dock.add_button.isEnabled()
    cut = session.add_cut("A", [(1.0, 1.0), (6.0, 1.0)])
    session.open_line(cut)
    assert dock.list.count() == 0
    assert not dock.list.isEnabled()
    assert dock.status.text() == PROCESSING_ON_CUT_TEXT
    assert PROCESSING_ON_CUT_TEXT == "Processing does not apply to a cut."
    for w in (dock.add_button, dock.apply_button, dock.presets_button, dock.diff_button):
        assert not w.isEnabled()
    session.open_line(key)
    assert dock.list.isEnabled()
    assert dock.status.text() == ""
    assert dock.add_button.isEnabled()


# ---- a refusal that stays (#197) ------------------------------------------


def _events(n: int = 5) -> None:
    for _ in range(n):
        QCoreApplication.processEvents()


def _refusing_dewow():
    # One sample at the synthetic lines' 0.2165 ns sampling.
    return build_step("dewow", window_ns=0.2)


def _reason(session, key):
    try:
        session.stack_for(key).result()
    except ValueError as exc:
        return str(exc)
    raise AssertionError("the stack did not refuse")


def _refused_dock(opened):
    session, dock, key = opened
    session.append_step(key, build_step("dewow"))
    session.replace_step(key, 0, _refusing_dewow())
    return session, dock, key


def test_a_refused_step_is_noted_under_the_list_and_marked(opened):
    session, dock, key = _refused_dock(opened)
    reason = _reason(session, key)
    assert dock.warnings.isVisibleTo(dock.widget())
    assert dock.warnings.entries() == (
        Entry(REFUSAL, REFUSAL_TEXT.format(title="Dewow", n=1, reason=reason)),
    )
    item = dock.list.item(0)
    assert item.text().startswith("⛔ ")
    assert item.foreground().color() == REFUSAL_COLOUR
    assert "dewow" in item.toolTip()
    assert reason in item.toolTip()
    assert dock.refusal().index == 0


def test_the_note_is_visible_whichever_row_is_selected(opened):
    session, dock, key = _refused_dock(opened)
    session.append_step(key, build_step("background_mean"))
    dock.list.setCurrentRow(1)
    assert dock.warnings.isVisibleTo(dock.widget())
    dock.list.setCurrentRow(0)
    assert dock.warnings.isVisibleTo(dock.widget())


def test_the_note_clears_when_the_setting_is_fixed(opened):
    session, dock, key = _refused_dock(opened)
    session.replace_step(key, 0, build_step("dewow", window_ns=4.0))
    assert not dock.warnings.isVisibleTo(dock.widget())
    assert dock.refusal() is None
    assert not dock.list.item(0).text().startswith("⛔")
    assert dock.list.item(0).foreground().color() != REFUSAL_COLOUR
    assert dock.list.item(0).toolTip() == "dewow"


def test_the_note_clears_when_the_step_is_removed(opened):
    session, dock, key = _refused_dock(opened)
    session.remove_step(key, 0)
    assert not dock.warnings.isVisibleTo(dock.widget())


def test_the_note_clears_when_the_step_is_turned_off(opened):
    session, dock, key = _refused_dock(opened)
    session.set_step_enabled(key, 0, False)
    assert not dock.warnings.isVisibleTo(dock.widget())
    assert not dock.list.item(0).text().startswith("⛔")


def test_the_note_clears_when_another_line_opens(opened):
    session, dock, _ = _refused_dock(opened)
    session.open_line(session.keys()[1])
    assert not dock.warnings.isVisibleTo(dock.widget())
    assert dock.refusal() is None


def test_the_note_clears_when_the_site_closes(opened):
    session, dock, _ = _refused_dock(opened)
    session.close_site()
    assert not dock.warnings.isVisibleTo(dock.widget())
    assert dock.refusal() is None


def test_an_edit_to_another_step_leaves_the_note(opened):
    session, dock, key = _refused_dock(opened)
    session.append_step(key, build_step("background_mean"))
    assert dock.refusal().index == 0
    session.set_step_enabled(key, 1, False)
    assert dock.warnings.isVisibleTo(dock.widget())
    assert dock.list.item(0).text().startswith("⛔ ")


def test_the_note_appears_when_the_samples_arrive(opened):
    session, dock, _ = opened
    other = session.keys()[1]
    session.append_step(other, _refusing_dewow())
    session.open_line(other)
    assert not dock.warnings.isVisibleTo(dock.widget())
    line = session._lines_by_key[other]
    session.set_profiles(other, line.load())
    assert dock.warnings.isVisibleTo(dock.widget())
    assert dock.refusal().index == 0


def test_two_refusals_note_the_first_then_the_second(opened):
    session, dock, key = opened
    session.append_step(key, _refusing_dewow())
    session.append_step(key, build_step("bandpass", low_mhz=100.0, high_mhz=90_000.0))
    assert dock.refusal().index == 0
    assert "(step 1)" in dock.warnings.entries()[0].text
    session.replace_step(key, 0, build_step("dewow", window_ns=4.0))
    assert dock.refusal().index == 1
    assert "Bandpass (step 2)" in dock.warnings.entries()[0].text


def test_a_preset_that_refuses_is_noted(opened):
    session, dock, _ = opened
    other = session.keys()[1]
    session.append_step(other, _refusing_dewow())
    session.save_preset("one sample", other)
    assert not dock.warnings.isVisibleTo(dock.widget())
    dock.apply_preset_named("one sample")
    assert dock.warnings.isVisibleTo(dock.widget())
    assert dock.refusal().title == "Dewow"


def test_the_note_never_widens_the_panel(opened):
    """Fails if WarningsPanel's labels lose the Ignored horizontal policy (an
    unbroken token wider than the panel then sets the minimum), and fails if
    they lose both it and setWordWrap(True). The dock is shown and its events
    processed before both measurements: an unshown dock keeps a cached minimum
    and hides the mutant. It is hidden and deleted at the end."""
    _, dock, _ = opened
    try:
        dock.show()
        _events()
        width = dock.minimumSizeHint().width()
        long = "x" * 120 + " " + " ".join(["words"] * 80)
        dock.warnings.set_entries([Entry(REFUSAL, long[:400])])
        _events()
        assert dock.warnings.isVisibleTo(dock.widget())
        assert dock.minimumSizeHint().width() == width
    finally:
        dock.hide()
        dock.deleteLater()
        _events()


def test_the_line_label_wraps(opened):
    """Spec 7: the label wraps. Fails if `setWordWrap(True)` goes: at a
    narrow width a long name of words then needs no more than one line."""
    session, dock, key = opened
    try:
        dock.show()
        _events()
        one_line = dock.line_label.fontMetrics().height()
        dock.line_label.setText("<b>" + " ".join(["word"] * 80) + "</b>")
        assert dock.line_label.wordWrap()
        assert dock.line_label.heightForWidth(120) > 2 * one_line
    finally:
        dock.hide()
        dock.deleteLater()
        _events()


def test_the_label_follows_the_open_line_to_another_grid(opened):
    session, dock, key = opened
    session.add_grid(Grid("B", (900.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    session.move_lines([key], "B")
    assert "· grid B" in dock.line_label.text()
    assert "· grid A" not in dock.line_label.text()


def test_the_label_follows_a_rename_of_the_open_line(opened):
    session, dock, key = opened
    session.edit_lines([LineEdit(key, session.line_for_key(key).placement, label="RENAMED")])
    assert "<b>RENAMED</b>" in dock.line_label.text()


@needs_real_data
def test_the_real_one_sample_dewow_is_noted(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    path = next(p for p in REAL_DZT if p.name == "FILE__007.DZT")
    line = Line.open(path, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    session.append_step(key, build_step("dewow", window_ns=0.2))
    assert dock.warnings.entries()[0].text == (
        "Dewow (step 1) can't run on this line: Dewow window 0.2 ns is one sample at "
        "this line's 0.217 ns sampling; use 0.33 ns or more. The profile won't update "
        "until this is fixed."
    )


def test_the_panel_names_its_line(opened):
    session, dock, key = opened
    text = dock.line_label.text()
    assert "<b>FILE__001</b>" in text
    assert "· grid A" in text
    session.close_site()
    assert dock.line_label.text() == ""


def test_the_panel_names_the_previewed_line_too(opened):
    session, dock, key = opened
    keys = session.keys()
    session.set_preview(keys[1], 3)
    assert dock.line_label.text().endswith(PREVIEW_SUFFIX.format(name="FILE__002"))
    session.set_preview(None)
    assert "previewing" not in dock.line_label.text()
    assert "<b>FILE__001</b>" in dock.line_label.text()


def test_a_line_name_is_escaped_and_never_widens_the_panel(qgis_app, tmp_path):
    """Fails if the name is not html-escaped, if the label loses the Ignored
    horizontal policy (a long unbroken name then sets the minimum). Word wrap
    is pinned by `test_the_line_label_wraps`, not here. Shown and measured
    like the note's width test, and hidden and deleted at the end."""
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0, 0.0, -1, "<b>" + "x" * 300))
    session.add_lines([line])
    try:
        dock.show()
        _events()
        width = dock.minimumSizeHint().width()
        session.open_line(session.keys()[0])
        _events()
        assert "&lt;b&gt;" in dock.line_label.text()
        assert dock.line_label.isVisibleTo(dock.widget())
        assert dock.minimumSizeHint().width() == width
    finally:
        dock.hide()
        dock.deleteLater()
        _events()


@pytest.mark.parametrize("loaded", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("above", [False, True])
def test_the_clock_rule_has_one_answer(qgis_app, tmp_path, loaded, enabled, above):
    """Guard test (it passes today and pins the refactor): the dock's
    `input_axis` and the gain strip's `step_inputs.clock_unknown` give the
    same answer for every combination of samples loaded, Time zero enabled
    and the row above or below the Time zero. It fails if `input_axis` keeps
    a private copy of the rule that differs, for example one that ignores
    `enabled`."""
    session, dock, key, line = _unloaded(qgis_app, tmp_path)
    session.set_step_enabled(key, 0, enabled)
    if loaded:
        session.set_profiles(key, line.load())
    stack = session.stack_for(key)
    row = 0 if above else 1
    assert step_inputs.clock_unknown(stack, row) == (dock.input_axis(row) is None)
    # Only an unloaded line behind an enabled Time zero has an unknown clock.
    assert step_inputs.clock_unknown(stack, row) == (not loaded and enabled and not above)


def _refusing_bandpass():
    return build_step("bandpass", low_mhz=100.0, high_mhz=90_000.0)


def test_difference_on_an_early_step_checks_only_the_chain_it_shows(opened):
    """Final review: with Difference on row 0, a refusal at row 1 is not
    noted (the profile does not run it); it is noted, naming step 2, when
    Difference goes off. Fails if `_paint_refusal` runs `stack.result()`
    while the Difference view is on."""
    session, dock, key = opened
    session.append_step(key, build_step("dewow"))
    session.append_step(key, _refusing_bandpass())
    dock.list.setCurrentRow(0)
    dock.diff_button.setChecked(True)
    assert dock.refusal() is None
    assert dock.warnings.entries() == ()
    dock.diff_button.setChecked(False)
    assert dock.refusal().index == 1
    assert dock.refusal().title == "Bandpass"
    assert "(step 2)" in dock.warnings.entries()[0].text


def test_difference_checks_the_chain_up_to_the_row_it_is_aimed_at(opened):
    session, dock, key = opened
    session.append_step(key, build_step("dewow"))
    session.append_step(key, _refusing_bandpass())
    session.append_step(key, build_step("dewow"))
    dock.list.setCurrentRow(2)
    dock.diff_button.setChecked(True)
    assert dock.refusal().index == 1  # the chain shown runs through step 2
    dock.list.setCurrentRow(0)
    assert dock.refusal() is None  # aimed at row 0: nothing refuses above it


def test_difference_on_a_row_below_a_refusal_names_that_step(opened):
    session, dock, key = opened
    session.append_step(key, _refusing_bandpass())
    session.append_step(key, build_step("dewow"))
    dock.list.setCurrentRow(1)
    dock.diff_button.setChecked(True)
    assert dock.refusal().index == 0
    assert "(step 1)" in dock.warnings.entries()[0].text


def _stepped_line(tmp_path, data, load=True):
    """A site with one line made of `data` (rows, traces), opened. Returns
    (session, dock, key, line)."""
    from tests.synthetic import write_dzt

    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    path = tmp_path / "raw" / "FILE__001.DZT"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_dzt(path, data)
    line = Line.open(path, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    if load:
        session.set_profiles(key, line.load())
    session.open_line(key)
    return session, dock, key, line


def _arrival_at(k, n=512, traces=40):
    import numpy as np

    data = np.zeros((n, traces), dtype=np.int32)
    data[k:, :] = 1_000_000
    return data


def test_the_row_field_is_bounded_by_the_input(opened):
    session, dock, key = opened
    session.append_step(key, build_step("time_zero", mode="sample", sample=5))
    dock.list.setCurrentRow(0)
    spin = dock.form.editors["sample"]
    assert isinstance(spin, RowSpinBox)
    assert spin.minimum() == 0 and spin.maximum() == 511


def test_the_row_field_of_a_later_step_is_bounded_by_what_it_receives(opened):
    session, dock, key = opened
    session.append_step(key, build_step("time_zero", mode="sample", sample=5))
    session.append_step(key, build_step("time_zero", mode="sample", sample=1))
    dock.list.setCurrentRow(1)
    assert dock.form.editors["sample"].maximum() == 511 - 5


def test_switching_to_sample_starts_at_the_first_break(qgis_app, tmp_path):
    session, dock, key, _ = _stepped_line(tmp_path, _arrival_at(37))
    session.append_step(key, build_step("time_zero", mode="first_break"))
    dock.list.setCurrentRow(0)
    stack = session.stack_for(key)
    before = stack.zero_ns()
    dock.form.set_value("mode", "sample")
    step = stack.entries[0][0]
    assert step.params["mode"] == "sample" and step.params["sample"] == 37
    assert stack.zero_ns() == before
    assert dock.form.editors["sample"].value() == 37  # the field shows what was written
    assert dock.form.values()["sample"] == 37


def test_switching_to_sample_uses_the_steps_threshold(qgis_app, tmp_path):
    import numpy as np

    data = np.zeros((512, 40), dtype=np.int32)
    data[30:, :] = 300_000  # a weak early arrival, between 0.2 and 0.5 of the peak
    data[60:, :] = 1_000_000
    session, dock, key, _ = _stepped_line(tmp_path, data)
    session.append_step(key, build_step("time_zero", mode="first_break", threshold=0.5))
    dock.list.setCurrentRow(0)
    dock.form.set_value("mode", "sample")
    assert session.stack_for(key).entries[0][0].params["sample"] == 60
    # and a lower threshold on the same record picks the weak arrival
    session.replace_step(key, 0, build_step("time_zero", mode="first_break", threshold=0.2))
    dock.list.setCurrentRow(-1)
    dock.list.setCurrentRow(0)
    dock.form.set_value("mode", "sample")
    assert session.stack_for(key).entries[0][0].params["sample"] == 30


def test_switching_to_sample_with_no_arrival_keeps_the_row_and_says_so(qgis_app, tmp_path):
    import numpy as np

    session, dock, key, _ = _stepped_line(tmp_path, np.zeros((512, 40), dtype=np.int32))
    session.append_step(key, build_step("time_zero", mode="first_break"))
    dock.list.setCurrentRow(0)
    dock.form.set_value("mode", "sample")
    step = session.stack_for(key).entries[0][0]
    assert step.params["mode"] == "sample" and step.params["sample"] == 0
    assert dock.form.message.text().startswith("Couldn't find the first break")
    assert "row 0" in dock.form.message.text()


def test_an_edit_that_stays_in_sample_mode_is_not_reseeded(qgis_app, tmp_path):
    session, dock, key, _ = _stepped_line(tmp_path, _arrival_at(37))
    session.append_step(key, build_step("time_zero", mode="sample", sample=100))
    dock.list.setCurrentRow(0)
    spin = dock.form.editors["sample"]
    spin.stepBy(1)
    assert session.stack_for(key).entries[0][0].params["sample"] == 101


def test_the_row_form_gets_its_bound_when_the_samples_arrive(qgis_app, tmp_path):
    session, dock, key, line = _stepped_line(tmp_path, _arrival_at(37), load=False)
    session.append_step(key, build_step("time_zero", mode="sample", sample=5))
    dock.list.setCurrentRow(0)
    assert dock.form.editors["sample"].maximum() > 1_000_000
    session.set_profiles(key, line.load())
    assert dock.form.editors["sample"].maximum() == 511


def test_time_zero_still_adds_without_a_dialog(opened):
    assert not needs_dialog("time_zero")


def test_a_switch_to_sample_before_the_samples_load_says_so_and_keeps_the_row(qgis_app, tmp_path):
    session, dock, key, _ = _stepped_line(tmp_path, _arrival_at(37), load=False)
    session.append_step(key, build_step("time_zero", mode="first_break", threshold=0.2))
    dock.list.setCurrentRow(0)
    dock.form.set_value("mode", "sample")
    step = session.stack_for(key).entries[0][0]
    assert step.params["mode"] == "sample" and step.params["sample"] == 0
    assert dock.form.message.text().startswith("Couldn't find the first break")


def test_a_switch_to_sample_behind_a_refusing_step_says_so(qgis_app, tmp_path):
    session, dock, key, _ = _stepped_line(tmp_path, _arrival_at(37))
    session.append_step(key, build_step("bandpass", low_mhz=1.0, high_mhz=1e9))
    session.append_step(key, build_step("time_zero", mode="first_break"))
    with pytest.raises(ValueError):
        session.stack_for(key).intermediate(0)
    dock.list.setCurrentRow(1)
    dock.form.set_value("mode", "sample")
    step = session.stack_for(key).entries[1][0]
    assert step.params["mode"] == "sample" and step.params["sample"] == 0
    assert dock.form.message.text().startswith("Couldn't find the first break")


def test_editing_the_threshold_in_first_break_mode_does_not_seed(qgis_app, tmp_path):
    session, dock, key, _ = _stepped_line(tmp_path, _arrival_at(37))
    session.append_step(key, build_step("time_zero", mode="first_break", sample=9))
    dock.list.setCurrentRow(0)
    edit = dock.form.editors["threshold"]
    edit.setText("0.3")
    edit.editingFinished.emit()
    params = session.stack_for(key).entries[0][0].params
    assert params == {"mode": "first_break", "sample": 9, "threshold": 0.3}
    assert dock.form.message.text() == ""
