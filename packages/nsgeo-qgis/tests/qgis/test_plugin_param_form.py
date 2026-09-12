from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import REQUIRED, ParamSpec, build_step
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui import param_form as param_form_module
from nsgeo_qgis.ui.add_step_dialog import AddStepDialog
from nsgeo_qgis.ui.param_form import ParamForm
from nsgeo_qgis.ui.processing_dock import ProcessingDock
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtWidgets import QComboBox, QDialog, QLineEdit

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


def test_form_builds_editors_from_the_schema(qgis_app):
    f = ParamForm()
    f.set_step("time_zero")
    assert set(f.editors) == {"mode", "sample", "threshold"}
    assert isinstance(f.editors["mode"], QComboBox)
    assert isinstance(f.editors["sample"], QLineEdit)
    assert f.values() == {"mode": "first_break", "sample": 0, "threshold": 0.2}


def test_form_shows_current_values_and_commits_new_ones(qgis_app):
    f = ParamForm()
    f.set_step("gain_agc", build_step("gain_agc", window_ns=12.0).params)
    assert f.editors["window_ns"].text() == "12"  # floats are shown with :g
    got = []
    f.committed.connect(got.append)
    f.set_value("window_ns", "25")
    f.commit()
    assert got == [{"window_ns": 25.0, "target": 1.0, "eps": 1e-12}]


def test_form_reports_bad_input_instead_of_raising(qgis_app):
    f = ParamForm()
    f.set_step("dewow")
    errors = []
    f.error.connect(errors.append)
    f.set_value("window_ns", "abc")
    f.commit()
    assert errors and "window" in errors[0].lower()
    assert "window" in f.message.text().lower()


def test_required_fields_start_blank_and_block_completion(qgis_app):
    f = ParamForm()
    f.set_step("bandpass")
    assert f.editors["low_mhz"].text() == "" and f.editors["taper_frac"].text() == "0.25"
    assert not f.is_complete()
    f.set_value("low_mhz", "100")
    f.set_value("high_mhz", "600")
    assert f.is_complete()
    assert f.build().params["high_mhz"] == 600.0


def test_a_comma_is_reported_not_silently_read_as_a_decimal_point(qgis_app):
    """`"1,000"` and a European `"1,5"` cannot be told apart from the text
    alone (thousands separator vs. decimal comma) -- silently converting
    every comma to a dot would read `"1,000"` as `1.0`, a wrong value with
    no error at all. A comma is reported as bad input instead, same as any
    other character `float`/`int` can't parse.

    Fails under a one-line reversion: restoring
    `.replace(",", ".")` on the stripped text in `_parse_number`'s caller.
    """
    f = ParamForm()
    f.set_step("dewow")
    errors = []
    f.error.connect(errors.append)
    f.set_value("window_ns", "1,000")
    f.commit()
    assert errors and "1,000" in errors[0]


def test_int_field_reports_a_clearer_message_for_a_non_integer_number(qgis_app):
    """`int("3.5")` raises `ValueError`, and the old blanket handler
    reported `"...: '3.5' is not a number"` -- wrong, since 3.5 plainly is
    a number, just not a whole one.

    Fails under a one-line reversion: removing `_parse_number`'s
    int-specific `float(text)` probe, falling straight through to the
    generic "is not a number" message for every failed `int()` call.
    """
    f = ParamForm()
    f.set_step("time_zero")
    errors = []
    f.error.connect(errors.append)
    f.set_value("sample", "3.5")
    f.commit()
    assert errors and "whole number" in errors[0].lower()


def test_set_value_reports_an_unknown_combo_choice_instead_of_guessing(qgis_app):
    """`findData()` returns -1 for a choice that isn't in the combo; the
    old `max(0, -1)` silently landed on index 0 -- the first choice,
    regardless of whether it was the one asked for.

    Fails under a one-line reversion: restoring
    `editor.setCurrentIndex(max(0, editor.findData(text)))` in place of
    the `index < 0` check.
    """
    f = ParamForm()
    f.set_step("time_zero")
    with pytest.raises(ValueError, match="is not one of this field's choices"):
        f.set_value("mode", "not_a_real_mode")


def test_non_finite_float_is_rejected_not_silently_accepted(qgis_app):
    """`float("nan")`/`float("inf")` succeed in plain Python but are not
    valid values for a physical parameter: confirmed directly against the
    real step (not assumed) that `Bandpass(low_mhz=nan, high_mhz=600)`
    raises nothing at all and produces different, finite, arbitrary
    output rather than an error -- so the parser, the one place already
    reporting every other kind of bad input, is the right boundary to
    refuse it instead of quietly forwarding it into a step.

    Fails under a one-line reversion: removing the `math.isfinite(value)`
    check from `_parse_number`'s float branch.
    """
    f = ParamForm()
    f.set_step("dewow")
    errors = []
    f.error.connect(errors.append)
    f.set_value("window_ns", "nan")
    f.commit()
    assert errors and "finite" in errors[0].lower()


def test_non_finite_int_is_rejected_not_silently_accepted(qgis_app):
    """Same hazard as the float case above, on the `int`-kind path: `int("inf")`
    fails, but the whole-number probe (`float(text)`) that produces the
    friendlier "must be a whole number" message also succeeds on `"inf"`
    -- without a finiteness check there, an `int` field would report the
    wrong reason (or none) for a non-finite value.

    Fails under a one-line reversion: removing the `math.isfinite(probe)`
    check from `_parse_number`'s int branch.
    """
    f = ParamForm()
    f.set_step("time_zero")
    errors = []
    f.error.connect(errors.append)
    f.set_value("sample", "inf")
    f.commit()
    assert errors and "finite" in errors[0].lower()


def test_updating_guard_survives_a_nested_clear(qgis_app):
    """`ParamForm._updating` is a depth counter, not a bool, matching
    `ProcessingDock._updating` (Task 16 paid for this exact lesson in that
    class) for the same reason: `set_step()` calls `clear()` before taking
    its own guard, so the two are already nested within one call today. A
    plain set/clear bool would let `clear()`'s own `finally` drop the guard
    while `set_step()`'s surrounding frame still expects it up. Simulated
    directly: mark the guard already up (as an outer caller would leave
    it), run a real `set_step()` through it, and check it is still up
    afterward.

    Fails under a one-line reversion: changing `self._updating += 1` /
    `-= 1` back to `= True` / `= False` in `clear()`.
    """
    f = ParamForm()
    f._updating += 1  # simulate: already inside an outer guarded section
    try:
        f.set_step("dewow")
        assert f._updating  # outer guard must still be active
    finally:
        f._updating -= 1  # tidy up so a later assertion doesn't see a wedged form


def test_curve_values_are_kept_independent_per_parameter(qgis_app, monkeypatch):
    """`_curve_values` used to be `_curve_value`, a single slot shared by
    every curve-kind spec -- a step with two curve params (none exist in
    the real registry today) would silently let the second overwrite the
    first. Faking a two-curve schema and monkeypatching it into `get_step`
    *as imported into `param_form.py`'s own module namespace* drives
    `set_step()`/`values()` end to end without touching the real, global
    `_REGISTRY` at all (no fake step leaks into `available_steps()` for
    any other test) -- and `values()` alone is enough to prove
    independence; nothing here needs a real, buildable step.

    Fails under a one-line reversion: replacing
    `self._curve_values[spec.name] = ...` with a single shared
    `self._curve_value = ...`, so the second spec processed overwrites the
    first's value under both keys.
    """

    class FakeTwoCurveStep:
        name = "fake_two_curves"

        @classmethod
        def schema(cls) -> tuple[ParamSpec, ...]:
            return (
                ParamSpec(name="curve_a", kind="curve", label="Curve A", default=REQUIRED),
                ParamSpec(name="curve_b", kind="curve", label="Curve B", default=REQUIRED),
            )

    monkeypatch.setattr(param_form_module, "get_step", lambda name: FakeTwoCurveStep)

    f = ParamForm()
    f.set_step(
        "fake_two_curves",
        {"curve_a": [[0.0, 0.0], [1.0, 0.0]], "curve_b": [[0.0, 5.0], [1.0, 5.0]]},
    )
    assert f.values() == {
        "curve_a": [[0.0, 0.0], [1.0, 0.0]],
        "curve_b": [[0.0, 5.0], [1.0, 5.0]],
    }


def test_validate_disables_ok_on_any_exception_not_just_valueerror(opened, monkeypatch):
    """`_validate` runs inside a Qt slot (`form.edited` -> `_validate`), so
    an exception it doesn't catch is printed to stderr by PyQt and the
    slot just returns -- `ok_button` is left exactly as it was, and
    `message` is never updated to say why. `step.apply()` is arbitrary
    step code with no promise of raising only `ValueError`; force a
    different exception type to prove the wider catch actually reports it.

    Fails under a one-line reversion: narrowing `except Exception` back to
    `except ValueError` in `_validate` -- the RuntimeError below then
    propagates out of the slot instead, `message` stays `""` (never
    updated), and only the `errors`/message assertion below tells the two
    apart (`ok_button` was already disabled before this call either way).
    """
    from nsgeo.processing.bandpass import Bandpass

    def boom(self: Bandpass, rg: object) -> object:
        raise RuntimeError("synthetic failure, not a ValueError")

    monkeypatch.setattr(Bandpass, "apply", boom)
    _, dock, _ = opened
    dialog = dock.build_add_dialog("bandpass")
    dialog.form.set_value("low_mhz", "100")
    dialog.form.set_value("high_mhz", "600")
    assert not dialog.ok_button.isEnabled()
    assert "synthetic failure" in dialog.form.message.text()


def test_message_label_survives_being_set_twice(qgis_app):
    """`clear()` (called at the top of every `set_step()`) empties every row
    of `QFormLayout` it manages by calling `removeRow(0)` in a loop -- and
    `QFormLayout.removeRow()` genuinely *deletes* the row's widgets (checked
    directly against a live `QFormLayout`: a `QLabel` added via `addRow` and
    then removed this way raises `RuntimeError: wrapped C/C++ object of type
    QLabel has been deleted` the next time anything touches it). If `message`
    were a row of that same layout rather than living in its own outer one,
    the *second* `set_step()` call on one `ParamForm` instance -- ordinary
    use for `ProcessingDock`'s single persistent form, reused across every
    row selection for the dock's lifetime -- would delete `message` out from
    under the first call's `addRow(self.message)`, and the next line to touch
    it (here, `build()`'s `self.message.setText(...)` on a bad value) would
    raise instead of reporting the error normally.

    Fails under a one-line reversion: adding `self._layout.addRow(self.message)`
    back at the end of `set_step()` (i.e. putting `message` inside the row
    layout `clear()` empties, instead of the stable outer one).
    """
    f = ParamForm()
    f.set_step("dewow")
    f.set_step("bandpass")  # second call on the same instance: must not raise
    f.set_value("low_mhz", "abc")
    f.commit()
    assert "low" in f.message.text().lower()


def test_add_step_dialog_shows_header_facts_and_validates_against_nyquist(qgis_app, tmp_path):
    p = synthetic_dzt(tmp_path, "L.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    from nsgeo.processing import Radargram

    rg = Radargram.from_profile(line.load()[0])
    d = AddStepDialog("bandpass", header=line.header, radargram=rg)
    assert "HS350US" in d.facts.text() and "Nyquist" in d.facts.text()
    assert not d.ok_button.isEnabled()
    d.form.set_value("low_mhz", "100")
    d.form.set_value("high_mhz", "5000")  # above the ~2309 MHz Nyquist
    assert not d.ok_button.isEnabled() and "Nyquist" in d.form.message.text()
    d.form.set_value("high_mhz", "600")
    assert d.ok_button.isEnabled()
    step = d.result_step()
    assert step.name == "bandpass" and step.params["low_mhz"] == 100.0


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    return session, dock, key


def test_dock_form_edits_the_selected_step_through_replace_step(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    dock.list.setCurrentRow(0)
    assert dock.form.step_name == "dewow"
    before = session.stack_for(key).entries[0][0]
    dock.form.set_value("window_ns", "7.5")
    dock.form.commit()
    after = session.stack_for(key).entries[0][0]
    assert after is not before and after.params["window_ns"] == 7.5


def test_dock_adds_required_steps_through_the_dialog(opened):
    session, dock, key = opened
    dialog = dock.build_add_dialog("bandpass")
    dialog.form.set_value("low_mhz", "100")
    dialog.form.set_value("high_mhz", "600")
    dock.append_from_dialog(dialog)
    assert [s.name for s, _ in session.stack_for(key).entries] == ["bandpass"]


def test_dock_seeds_a_curve_step_with_the_identity(opened):
    session, dock, key = opened
    dock.add_step_with_dialog("gain_curve")
    step = session.stack_for(key).entries[0][0]
    t0, dt, n = dock.time_axis()
    assert step.params["points"] == [[t0, 0.0], [t0 + dt * (n - 1), 0.0]]
    assert t0 == pytest.approx(-11.086, abs=1e-3)


def test_time_axis_follows_a_preceding_step_that_changes_the_sample_axis(opened):
    """A `time_zero` step ahead of a new curve step changes both `t0_ns`
    and `n_samples` (nsgeo.processing.timezero crops the leading rows), so
    the axis a step appended now will actually run against is the stack's
    post-crop *result*, not its raw, pre-crop source. Task 18's brief
    parked exactly this mismatch (a gain_curve seeded on the wrong axis
    when a time_zero precedes it) as a design decision for this task; this
    pins the fix directly against ground truth computed independently of
    `time_axis()` itself: `source.t0_ns + 5 * source.dt_ns`, not a second
    call to the method under test.

    mode="sample", sample=5 crops exactly 5 rows regardless of the
    synthetic data's own content, so this does not depend on where a
    first-break picker would land.
    """
    session, dock, key = opened
    source = session.stack_for(key).source
    session.append_step(key, build_step("time_zero", mode="sample", sample=5))
    t0, dt, n = dock.time_axis()
    assert dt == source.dt_ns
    assert n == source.n_samples - 5
    assert t0 == pytest.approx(source.t0_ns + 5 * source.dt_ns)
    # Reverting time_axis() to read stack.source directly (this task's
    # `ProcessingDock.time_axis` before the fix) would report the RAW,
    # pre-crop source's own t0 here instead of the cropped one.
    assert t0 != pytest.approx(source.t0_ns)


def test_time_axis_falls_back_to_source_when_evaluating_the_stack_would_raise(opened):
    """`StepStack.result()` raises `ValueError` when ANY step already in
    the stack is misconfigured -- a bandpass whose high cut exceeds
    Nyquist, here (the exact scenario `ProfileDock`'s own docstring names
    for `current_radargram()`). That is a problem with the bandpass step,
    not a reason `time_axis()` -- used only to seed a brand-new step's
    identity default -- should raise too and block adding one: it must
    fall back to the stack's raw source, exactly as it did before this
    task looked at `result()` at all.
    """
    session, dock, key = opened
    source = session.stack_for(key).source
    session.append_step(key, build_step("bandpass", low_mhz=100.0, high_mhz=5000.0))
    with pytest.raises(ValueError):
        session.stack_for(key).result()  # confirms the stack really is broken
    t0, dt, n = dock.time_axis()
    assert (t0, dt, n) == (source.t0_ns, source.dt_ns, source.n_samples)
    dock.add_step_with_dialog("gain_curve")  # must not raise
    assert [s.name for s, _ in session.stack_for(key).entries] == ["bandpass", "gain_curve"]


def test_time_axis_logs_when_it_falls_back_to_source(opened, message_log):
    """m2 (fix round 1 review). The `ValueError` fallback above used to be
    silent: when it fires, a new curve step's seed lands on the raw source
    axis while `ProfileView` keeps its last good (possibly quite
    different) transform, so the user gets a strip whose endpoints sit off
    the drawn axis (and, per Important 2, are then unreachable once
    dragged there) with nothing said. A one-line `_log(...)` costs
    nothing.
    """
    session, dock, key = opened
    session.append_step(key, build_step("bandpass", low_mhz=100.0, high_mhz=5000.0))
    dock.time_axis()
    assert any("time_axis" in m and "raw source" in m for m in message_log)


def test_add_step_with_dialog_opens_a_real_modal_and_accepts(opened, drive_dialog):
    """`add_step_with_dialog` on a step whose REQUIRED params are not all
    curves (`bandpass`, unlike `gain_curve`) opens a real `AddStepDialog`
    through `exec()` -- this is the one path in this module none of the
    tests above reach, since they all build the dialog directly and skip
    the modal loop. Offscreen, an un-driven `exec()` would hang the whole
    suite (see `conftest.py`'s `_no_unhandled_modals` for why every test
    tier forbids it by default); `drive_dialog` fills the dialog in and
    accepts it exactly as a user would, in place of a real click.
    """
    session, dock, key = opened

    def fill_and_accept(dialog: AddStepDialog) -> None:
        dialog.form.set_value("low_mhz", "100")
        dialog.form.set_value("high_mhz", "600")
        dialog.accept()

    drive_dialog(QDialog, "exec", fill_and_accept)
    dock.add_step_with_dialog("bandpass")
    assert [s.name for s, _ in session.stack_for(key).entries] == ["bandpass"]


def test_add_step_with_dialog_cancel_adds_nothing(opened, drive_dialog):
    """The stack must stay empty *because* the dialog was rejected, not
    merely because an unfilled form can't build a step: fill both required
    fields first (so `result_step()` would return a real, buildable
    `bandpass` step), then reject. If `add_step_with_dialog` appended the
    step unconditionally instead of gating on `exec()`'s result, this
    would fail -- run directly (not merely named): with the driver
    below and the gate removed from `add_step_with_dialog`,
    `len(session.stack_for(key))` comes back `1`, not `0`.
    """
    session, dock, key = opened

    def fill_and_reject(dialog: AddStepDialog) -> None:
        dialog.form.set_value("low_mhz", "100")
        dialog.form.set_value("high_mhz", "600")
        dialog.reject()

    drive_dialog(QDialog, "exec", fill_and_reject)
    dock.add_step_with_dialog("bandpass")
    assert len(session.stack_for(key)) == 0


def test_committing_one_field_does_not_rebuild_the_others(opened):
    """`_on_form_committed` -> `session.replace_step` -> `stack_changed` ->
    `rebuild()` -> `rebuild()`'s unconditional `step_selected.emit(...)` ->
    `_show_form` reports the *same* row this form already shows, straight
    back to the form that just committed. Rebuilding on that echo would
    call `self.form.clear()`, destroying every editor -- including
    `high_mhz`'s, which was not touched by this commit at all -- and
    replacing it with a fresh widget the user is not focused in.

    Fails under a one-line reversion: deleting the
    `if shown == self._shown and step is self._shown_step: return`
    early-out in `_show_form` (both halves -- see
    `test_removing_the_selected_row_shows_the_step_that_slides_into_it`
    below for why the `(key, row)` half alone is not enough), so every
    echo rebuilds the row unconditionally.
    """
    session, dock, key = opened
    dialog = dock.build_add_dialog("bandpass")
    dialog.form.set_value("low_mhz", "100")
    dialog.form.set_value("high_mhz", "600")
    dock.append_from_dialog(dialog)
    dock.list.setCurrentRow(0)
    high_editor = dock.form.editors["high_mhz"]

    dock.form.set_value("low_mhz", "150")
    dock.form.commit()

    assert session.stack_for(key).entries[0][0].params["low_mhz"] == 150.0
    assert dock.form.editors["high_mhz"] is high_editor


def test_typing_in_a_field_survives_an_unrelated_stack_change(opened):
    """The same hazard as `test_committing_one_field_does_not_rebuild_the_others`,
    but triggered by a stack change that has nothing to do with the row
    being edited (toggling a *different* step's checkbox) rather than by
    this form's own commit -- the more realistic version of "a user typing
    a value and having the field reset out from under them": the user is
    still mid-keystroke (no `editingFinished`/`commit()` at all here), and
    something elsewhere in the dock still causes a `stack_changed` ->
    `rebuild()` while the edited row's own index does not change.

    Fails under the same one-line reversion as the test above.
    """
    session, dock, key = opened
    dock.add_step("dewow")
    dock.add_step("gain_agc")
    dock.list.setCurrentRow(1)
    assert dock.form.step_name == "gain_agc"
    window_editor = dock.form.editors["window_ns"]
    window_editor.setText("12")  # mid-typing: textChanged only, no editingFinished yet

    session.set_step_enabled(key, 0, False)  # unrelated row, still triggers stack_changed

    assert dock.form.editors["window_ns"] is window_editor
    assert window_editor.text() == "12"


def test_removing_the_selected_row_shows_the_step_that_slides_into_it(opened):
    """The positive complement the two tests above don't cover: a row
    whose *content* actually changed must still be re-shown, not just a
    row whose content didn't. `(key, row)` alone cannot tell "same row,
    same step" (an echo -- the case above) from "same row, a *different*
    step now sits there": add `dewow` (row 0) and `gain_agc` (row 1),
    select row 0 (form shows `dewow`), then `remove_selected()` deletes
    the selected row -- `dewow` -- so `gain_agc` slides up to fill row 0.
    `currentRow` stays 0 (still a valid index), but the step actually at
    row 0 is now a different object entirely.

    Fails under a one-line reversion: dropping the `step is
    self._shown_step` half of `_show_form`'s guard back to comparing
    `(key, row)` alone -- the form then keeps showing `dewow`'s stale
    editors over a stack that no longer has a `dewow` step at all, and
    the next edit through them would silently resurrect `dewow` in place
    of `gain_agc`.
    """
    session, dock, key = opened
    dock.add_step("dewow")
    dock.add_step("gain_agc")
    dock.list.setCurrentRow(0)
    assert dock.form.step_name == "dewow"

    dock.remove_selected()

    assert [s.name for s, _ in session.stack_for(key).entries] == ["gain_agc"]
    assert dock.list.currentRow() == 0
    assert dock.form.step_name == "gain_agc"
    assert set(dock.form.editors) == {"window_ns", "target", "eps"}
