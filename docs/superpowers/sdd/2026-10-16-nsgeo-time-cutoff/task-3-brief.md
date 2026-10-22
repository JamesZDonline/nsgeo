### Task 3: Wire the cutoff to the Processing panel and the session

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`: `add_step_with_dialog` seeds a `"time"` parameter
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: one connection, next to `step_selected.connect(self._sync_gain_strip)`
- Modify: `README.md`: the processing bullet names the cutoff
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`, `test_plugin_processing_dock.py`, `test_plugin_param_form.py`; create `packages/nsgeo-qgis/tests/qgis/test_plugin_time_cutoff.py` for the whole-plugin and real-data tests

**Interfaces:**
- Consumes: `StepStack.result_bypassing` and `build_step("time_cutoff", end_ns=...)` from Task 1. `ProfileView.set_cutoff`, `cutoff_ns` and `cutoff_dragged` from Task 2.
- Produces in `profile_dock.py`: the module function `time_param_name(step: Any) -> str | None`, which names the first schema parameter whose `kind == "time"`.
- Produces on `ProfileDock`: the slot `set_selected_step(row: int) -> None`, connected to `ProcessingDock.step_selected` by `plugin.py`.
- Behaviour contract for `ProfileDock`:
  - The *cutoff row* is the selected row, but only when no preview is up, a working line is open, the row is in range for the working line's stack, and the step there has a time parameter. Otherwise it is -1. It is resolved against the live stack at every render, never cached, so a line switch or a stack edit can never leave it pointing at the wrong step.
  - `current_radargram()` checks the difference view first, as now. Next, when there is a cutoff row, it returns `stack.result_bypassing(row)`. Otherwise it returns `stack.result()`. All three sit inside the existing `ValueError` handling.
  - `_render()` ends by calling `view.set_cutoff(<that step's end_ns>)` when there is a cutoff row, and `view.set_cutoff(None)` otherwise. It records the step object it read the value from.
  - `set_selected_step(row)` does nothing when the row is unchanged. A stack edit is already re-rendered by `_on_stack_changed`, and re-rendering on the echoed `step_selected` would render twice per drag. It re-renders only when the old or the new row is a cutoff row.
  - A `cutoff_dragged(end_ns)` commit writes `session.replace_step(working_key, row, build_step(name, **{**params, param: end_ns}))`. It writes only when there is a cutoff row, the step at that row is still the very object `_render` read (identity, as `_on_gain_points` checks), and the value actually differs. A `ValueError` from `build_step` goes to the dock's `error` signal. The new step is recorded before `replace_step`, as `_on_gain_points` does. The slot guards its whole body.
- Produces in `ProcessingDock.add_step_with_dialog`: the no-dialog seeding branch covers required parameters of kind `"curve"` or `"time"`. A `"time"` parameter is seeded with `t0 + n * dt` from `self.time_axis()`, which is the end of the record the new step will receive, so it starts as a no-op.

- [ ] **Step 1: Write the failing dock tests** in `test_plugin_profile_dock.py`. In the `opened` fixture the line is synthetic, 512 samples. Call `session.set_profiles(key, line.load())` first, and build `end = rg.t0_ns + 200 * rg.dt_ns` from `session.stack_for(key).source`.

  - `test_selecting_a_cutoff_step_shows_the_whole_record_with_the_line`: append `time_cutoff(end)`, then `dock.set_selected_step(0)`. `dock.image.rg.n_samples == 512` and `dock.view.cutoff_ns == approx(end)`. After `set_selected_step(-1)`, `n_samples == 200` and `cutoff_ns is None`.
  - `test_steps_after_the_cutoff_still_apply_while_it_is_selected`: the stack is `[time_cutoff(end), gain_agc(window_ns=10.0)]` with row 0 selected. `dock.image.rg.data` equals `stack.result_bypassing(0).data`.
  - `test_dragging_the_line_writes_the_step`: with row 0 selected, `dock.view.cutoff_dragged.emit(end - 10 * dt)`. The stack's `entries[0][0].params["end_ns"]` is approx that value, `session.dirty` holds, and `dock.view.cutoff_ns` still shows it after the re-render.
  - `test_a_drag_to_the_same_time_writes_nothing`: connect a recorder to `session.stack_changed`, then emit `cutoff_dragged(end)`. The recorder is empty.
  - `test_a_drag_with_nothing_selected_writes_nothing`: with row -1, emit, and the params are unchanged.
  - `test_selecting_between_two_ordinary_steps_does_not_rerender`: the stack is `[dewow, background_mean]`. Monkeypatch `dock._render` with a counter. `set_selected_step(0)` then `set_selected_step(1)` leaves the counter at 0.
  - `test_a_preview_hides_the_line_and_refuses_a_drag` (the `previewing` fixture; read it first): give the working line `[time_cutoff]`, select row 0, then preview the other line. `view.cutoff_ns is None`, and an emitted `cutoff_dragged` leaves the working stack unchanged. Snap back, and `cutoff_ns` is back.
  - `test_switching_lines_reads_the_new_lines_step_at_the_selected_row` (the `previewing` fixture has two lines): line A is `[dewow, time_cutoff(endA)]` and line B is `[time_cutoff(endB), dewow]`. Select row 1 on A, which shows the line at `endA`. `session.open_line(B)` with no new `set_selected_step` call: `cutoff_ns is None` and B's image is its clipped result. Then `set_selected_step(0)` gives `cutoff_ns == approx(endB)`.

- [ ] **Step 2: Run them and see them fail** with `AttributeError: 'ProfileDock' object has no attribute 'set_selected_step'`.

- [ ] **Step 3: Implement the `ProfileDock` half** to the behaviour contract above. Connect `self.view.cutoff_dragged` to the commit slot in `__init__`. If Task 2 added a `KNOWN_UNCONSUMED` entry, remove it. Add a paragraph to the module docstring covering the cutoff row and why it is resolved live.

- [ ] **Step 4: Run them and see them pass.**

- [ ] **Step 5: Write the failing seeding and form tests.**
  - In `test_plugin_processing_dock.py`, `test_adding_a_time_cutoff_seeds_the_record_end_and_changes_nothing`: with a loaded line, call `dock.add_step("time_cutoff")`. That takes the real path: `required_params` → `add_step_requested` → `add_step_with_dialog`. No dialog opens; the conftest modal guard would fail the test if one did. `t0, dt, n = dock.time_axis()` is captured before the add. The new step's `end_ns == approx(t0 + n * dt)`, `stack.result().n_samples == n`, and the new row is selected.
  - In `test_plugin_param_form.py`, `test_a_time_param_is_a_number_field_with_its_unit`: `set_step("time_cutoff", {"end_ns": 40.0})`. The editor is a `QLineEdit` reading `"40"`, and its row label is `"Cutoff (ns)"`. Set it to `"35.5"` and commit, and `committed` carries `{"end_ns": 35.5}`.

- [ ] **Step 6: See them fail, implement the seeding, see them pass.** The form test may pass with no form change, because a `"time"` parameter already falls through to the line-edit branch. Confirm that it fails if `"time"` is removed from `KINDS`, so it is not vacuous, then restore it.

- [ ] **Step 7: Write the failing whole-plugin and real-data tests** in the new `test_plugin_time_cutoff.py`. Use the `fake_iface` and `answer_modal` fixtures, following `test_plugin_routes_strip_edits_through_replace_step` in `test_plugin_gain_strip.py`, including its `unload()` with `Discard`.
  - `test_selecting_the_cutoff_row_in_the_processing_panel_shows_the_line`: build the plugin with `classFactory`, then `processing_dock.add_step("dewow")` and `add_step("time_cutoff")`. The add selects row 1, and `profile_dock.view.cutoff_ns` is not `None`. `processing_dock.list.setCurrentRow(0)` gives `None`.
  - `test_typing_a_cutoff_moves_the_line`: with row 1 selected, set the form's `end_ns` editor to a value 50 samples before the end and commit. `profile_dock.view.cutoff_ns` follows it.
  - `@needs_real_data test_a_real_line_clips_where_the_line_is_dropped`: a session on `REAL_DZT[0]` with `[time_zero(first_break, 0.25), time_cutoff]` seeded by `add_step`, and row 1 selected. Emit `profile_dock.view.cutoff_dragged(zeroed.t0_ns + 300 * zeroed.dt_ns)`, then select row 0. The image is 300 rows. The working stack's `to_dicts()` round-trips through `StepStack.from_dicts` with the same `end_ns`. Build the line from the real file the way `test_plugin_profile_view.py`'s real-data test does. Placement and grid can follow `test_plugin_gain_strip.py`'s `GRID` and `GridPlacement`.

- [ ] **Step 8: See them fail, add the one connection in `plugin.py`, see them pass.** Then update `README.md`'s processing bullet. It currently reads "covering time-zero, dewow, three gain steps including a draggable manual gain curve, bandpass, and background removal…". Add "a time cutoff dragged on the profile".

- [ ] **Step 9: Run both tiers in full, plus lint and types.** Record the counts. The real-data tests must not be among the skips.

- [ ] **Step 10: Commit and push.**

```bash
git add packages/nsgeo-qgis README.md
git commit -m "feat(plugin): drag the time cutoff on the profile, seeded at the record end"
git push
```

---

