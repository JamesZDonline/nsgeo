### Task 3: The gain slots (#49, #9, #15, #25 item 4)

Spec §4.4–§5. All in `plugin.py`'s gain slots and `unload()`.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`_sync_gain_strip`, `_resync_gain_strip`,
  `_on_gain_points`, new `_on_gain_reset`, the connection in `initGui` next to
  `gain_points_changed`, `unload()`)
- Modify: `docs/guide/getting-started.md` (the gain strip paragraph)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py` (plugin-level; the existing
  `_plugin_with_time_zero_after_curve` helper and `answer_modal`; the toast is read from
  `fake_iface.messageBar().currentItem().text()`)

**Interfaces:**
- Consumes: `ProfileDock.gain_reset_requested`; `ProcessingDock.input_axis(row) -> tuple[float,
  float, int] | None` (unchanged); `nsgeo_qgis.lookup.identity_curve`.
- Produces:
  - `NsgeoPlugin._on_gain_reset() -> None`;
  - `plugin.RESET_TITLE = "Reset gain curve"`;
  - `plugin.RESET_QUESTION = "Reset the gain curve to a flat 0 dB? Its {n} points will be lost."`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_refused_curve_snaps_back_with_a_toast`:
    - plugin with a gain curve selected;
    - give the strip a refused payload with the current owner (`[[0, 0], [50, 130]]`), and emit
      `points_changed`;
    - `strip.points()` equals the step's own points (on the shown clock);
    - the step is unchanged, and the toast contains `"120"`.
  - `test_reset_asks_and_writes_the_flat_curve`:
    - a curve with a non-zero point;
    - `answer_modal(QMessageBox, "question", Yes)`;
    - emit `profile_dock.gain_reset_requested`;
    - the step's points equal `identity_curve(*processing_dock.input_axis(row))`;
    - the question's text was `RESET_QUESTION.format(n=<len>)`.
  - `test_reset_answered_no_changes_nothing`.
  - `test_reset_of_a_flat_curve_asks_nothing`: all-zero points that differ from the identity get
    the identity with no question. When the points already are the identity, nothing is written
    and the session stays clean.
  - Review Focus 4, `test_reset_behind_time_zero_is_on_the_time_zero_clock`:
    - stack `time_zero(mode="sample", sample=51)`, then `gain_curve`, with samples loaded;
    - Reset (answer Yes);
    - the first point's time is the step input's `t0_ns` (0.0 on the Time zero clock), not the
      header's `position_ns`.
  - `test_the_strip_waits_for_its_clock`:
    - open a line with no profiles and stack `time_zero(sample=51)`, then `gain_curve`; select
      row 1. Process no events between the open and `set_profiles`. If the plugin's loader would
      deliver the samples first, make its `request` a no-op with `monkeypatch`, as
      `test_plugin_map_link.py::test_a_previewed_line_is_requested_from_the_loader` does;
    - `gain_strip.isHidden()`;
    - `set_profiles`: the strip is visible, and its points are on the Time zero clock.
  - `test_each_gain_slot_reports_an_exception`: for each slot, monkeypatch one thing inside it to
    raise `RuntimeError("boom")`, call the slot directly, and expect no exception and a toast
    containing `"boom"`:
    - `_sync_gain_strip`: `profile_dock.show_gain_strip`;
    - `_resync_gain_strip`: `processing_dock.current_row`;
    - `_on_gain_points`: `session.replace_step`;
    - `_on_gain_reset`: `processing_dock.input_axis`.
  - `test_unload_forgets_the_gain_curve`: after `unload()`, `_gain_owner is None` and `_gain_step
    is None`.
  - `test_the_real_strip_stops_at_120_and_resets` (`@needs_real_data`):
    - FILE__007 with a gain curve; drag handle 1 past the strip's right edge (real `QTest` press,
      then `send_move_while_pressed`, then release);
    - the step's dB is exactly 120.0;
    - Reset (Yes) gives `identity_curve` on FILE__007's input axis.
- [ ] **Step 2: Run them.** Expected: FAIL (the strip keeps 130; no reset slot; the strip is shown
  before the samples load; "boom" escapes).
- [ ] **Step 3: Implement it** in `plugin.py`.
  - Each gain slot's body sits in `try` / `except Exception as exc`, reporting through
    `self.message(f"could not … : {exc}", Qgis.MessageLevel.Warning)`. The `None` guards come
    first, as today.
  - `_sync_gain_strip` hides the strip (`show_gain_strip(None)`) when
    `processing_dock.input_axis(row) is None`.
  - On `build_step`'s `ValueError`, `_on_gain_points` toasts it, as today, and then calls
    `profile_dock.show_gain_strip(step.params[name], self._gain_owner,
    profile_dock.step_input_zero_ns(row))`.
  - `_on_gain_reset`, connected to `profile_dock.gain_reset_requested`:
    - it resolves the key, row and step as `_on_gain_points` does, including the `step is
      self._gain_step` identity check;
    - it computes `identity_curve(*axis)` from `input_axis(row)`, and returns when the axis is
      None or the points already equal it;
    - it asks with `QMessageBox.question(self.iface.mainWindow(), RESET_TITLE, …)` only when some
      point's dB is not 0;
    - on Yes, or with no question, it sets `self._gain_step = new` before `replace_step`, as
      `_on_gain_points` does.
  - `unload()` sets `_gain_owner = None` and `_gain_step = None` beside the docks.
- [ ] **Step 4: Run the tests and the four whole files.** Expected: PASS. The existing
  `test_gain_strip_slots_do_not_raise_after_unload` still passes; add `_on_gain_reset()` and
  `_resync_gain_strip("x")` to it.
- [ ] **Step 5: Update the guide.** The gain strip paragraph says:
  - the strip stops at ±120 dB;
  - a point outside the record sits on the strip's edge, where it can be dragged in or
    right-clicked away;
  - **Reset**, at the foot of the strip, puts back a flat 0 dB curve after asking.
- [ ] **Step 6: Commit** `fix(plugin): gain slots report failures, snap a refused curve back, reset, and wait for the strip's clock (#49, #9, #15, #25)`.

