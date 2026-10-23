# Final fix wave report (nsgeo-time-cutoff)

Commits, both pushed:
- `b5dca3e` fix(plugin): cutoff grab keeps its offset, unloaded lines hide the line, a declined difference falls through (I1, I2, I3)
- `0981d9d` fix(plugin): final-review riders for the time cutoff (riders 1 to 6, plus the R3 pin)

Every RED below came from the QGIS-tier command, one file (or `-k` subset) at a time:
`PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/<file> -q -p no:xonsh [-k ...]`

No probe file was copied into the tree. All the tests are written in the repo's files.

## I1: a grab jumped to the pointer (R6)

Changed, `profile_view.py`:
- The press now records `_cutoff_press_y` and `_cutoff_offset` (line y minus press y) next to `_cutoff_grab`.
- In `_handle_mouse_move`, while `abs(y - press_y) <= DRAG_THRESHOLD_PX` the value is exactly `_cutoff_grab`.
- Beyond that, it is `snap_cutoff(time_of_y(y + offset))`.
- The rule is stateless: a pointer that comes back within the threshold returns the exact start value. That follows R6's "while the pointer is within that distance".

Tests:
- `test_plugin_profile_view.py::test_a_grab_released_where_it_began_emits_the_start_value`: press 4.5 px below the line, wiggle 1 px, release at the press point.
  - RED: `assert 41.5 == 40.0`. The mid-gesture check showed the line jumped on the first move.
- `test_plugin_profile_view.py::test_a_drag_from_off_the_line_moves_it_by_the_pointer_travel`: press 4.5 px off the line, drag 40 px. The expected value, 30.5 ns, was derived by hand in the docstring.
  - RED: `assert [31.5] == [30.5]`.
- `test_plugin_profile_dock.py::test_a_grab_released_where_it_began_leaves_the_session_clean`: the same gesture through a real `ProfileDock`.
  - It runs `session.save()` first, so a write would show as `dirty` turning True. Clean is asserted before and after.
  - It also asserts no `stack_changed`, `end_ns` unchanged, and no "could not move the time cutoff" log.
  - RED: `assert ['raw/FILE__001.DZT'] == []` (`stack_changed` fired).
- `test_plugin_profile_view.py::test_a_wobble_inside_the_threshold_keeps_an_off_grid_value_exactly`: added after the first GREEN.
  - Why: a mutation check showed the dock gesture alone does not pin the threshold. With an on-grid start value, the offset brings the line back to exactly the same float.
  - This test uses an off-grid cutoff (40.2 ns, as a typed value or "Apply to grid" can leave), a 2-px tremor, and a release away from the press point.
  - RED against the threshold-removed mutant: `assert [40.5] == [40.2]`.
- Against the original pointer-absolute logic, restored as a temporary mutant, all four I1 tests fail: `41.5 == 40.0`, `[41.0] == [40.2]`, `[31.5] == [30.5]`, and the dock write.

GREEN: `test_plugin_profile_view.py` and `test_plugin_profile_dock.py` both pass in full.

## I2: the cutoff line over an unloaded line

Changed, `profile_dock.py`, the no-profiles branch of `_show_line`: `self._cutoff_step = None` and `self.view.set_cutoff(None)`, with a comment. `line_loaded`'s render puts the line back.

Tests, in `test_plugin_profile_dock.py`, with a new `one_loaded` fixture (two lines, only the open one loaded, cutoff selected):
- `test_a_preview_of_an_unloaded_line_hides_the_cutoff`:
  - the line is hidden during the preview;
  - an emitted `cutoff_dragged` writes nothing and logs nothing;
  - the line returns on snap-back.
  - RED: `assert 32.22024893760681 is None`.
- `test_opening_an_unloaded_line_hides_the_cutoff_until_it_loads`:
  - the second line has its own cutoff at the selected row, as a saved project would;
  - opening it hides the line;
  - a drag writes onto neither line and logs nothing;
  - once its samples load, the line returns at that line's own time.
  - RED: `assert 32.22024893760681 is None`.

GREEN: the dock file passes in full.

Note: no test catches the `_cutoff_step = None` half of the fix on its own. `_on_cutoff_dragged`'s identity check already refuses a stale step. It stays because the finding prescribes it.

## I3: a declined difference left a stale image (R7)

Changed, `profile_dock.py`, `current_radargram`:
- The difference has its own `try`. On `ValueError`/`IndexError` it calls `_decline_difference(...)` and falls through.
- The cutoff-bypass / `result()` path has its own `try`: `ValueError` emits `error` and returns `None`.
- `_decline_difference` lost its unused `return None`, and its docstring was updated.
- The module docstring paragraph now says a declined difference shows the ordinary view.
- Re-entrancy is unchanged. `difference_cleared`'s echo reaches `set_difference_index(-1)` with the index already -1, so it still stops at the early-out. The comment in the new `try` says so.

One addition beyond R7's text (see Concerns):
- A step that fails upstream of a difference fails both the difference and the ordinary result, with the same message.
- R7 as ruled reported it twice.
- The result path now skips an `error` whose text equals the one the decline just showed.

Tests:
- `test_plugin_time_cutoff.py::test_selecting_the_cutoff_with_the_difference_view_on_shows_the_line` (order 1, through the whole plugin):
  - expects the bypass image with all rows, the line at `end`, the button unchecked, the label cleared, and exactly one "sample count" message.
  - RED: `assert_array_equal` failed, 30720/30720 elements mismatched (background_mean's stale difference, not the bypass).
- `test_plugin_time_cutoff.py::test_the_difference_view_over_a_selected_cutoff_keeps_the_line` (order 2): the same expectations.
  - RED: `assert None == 32.22024893760681` (line hidden).
- `test_plugin_profile_dock.py::test_a_declined_difference_falls_back_to_the_ordinary_result` (the `time_zero` case, at dock level):
  - difference on background_mean, then aimed at `time_zero`;
  - expects the ordinary result (472 rows), the label cleared, one message and one `difference_cleared`.
  - RED: `assert_array_equal` failed, 113280/113280 mismatched (the stale difference).
- `test_plugin_profile_dock.py::test_a_step_failing_under_the_difference_view_is_reported_once`:
  - passed before the change;
  - RED against R7 as ruled: `assert (2 == 1)`, two identical "high_mhz (90000.0) exceeds the Nyquist frequency ..." messages;
  - GREEN after the repeat is suppressed.

GREEN: `test_plugin_profile_dock.py`, `test_plugin_time_cutoff.py` and `test_plugin_difference_presets.py` (the existing difference-view tests) all pass.

## Riders

1. **`timecutoff.py` comment.** I rewrote the finiteness-guard comment. The guard stays.
   - Verified directly with `math.ceil((end - (-4.0)) / 0.5 - 1e-9)`:
     - NaN raises `ValueError: cannot convert float NaN to integer`;
     - ±inf raises `OverflowError: cannot convert float infinity to integer`.
   - The comment now says neither is silent, OverflowError escapes a handler that catches `ValueError`, and both would wait for the first render.
   - It is comment-only, so there is no new test. The guard is still pinned by `test_steps_timecutoff.py::test_end_ns_is_required_and_must_be_a_finite_number`.

2. **Label clipping.** New `ProfileView._cutoff_label_rect(r, t)` (the `_selection_bounds` style). The label sits above the line, or below it (`yy + 2`) when `yy - 18 < r.top()`. `_paint_cutoff` draws into it.
   - Test: `test_plugin_profile_view.py::test_the_cutoff_label_stays_inside_the_image_near_its_top`. With one sample kept, the rect is inside `r` and below the line. At 40 ns it is inside and above.
   - RED 1: `AttributeError: ... no attribute '_cutoff_label_rect'`.
   - RED 2, after extracting the helper with the old placement unchanged: `QRectF(56.0, 6.0625, 692.0, 16.0)` not inside `QRectF(56.0, 22.0, 696.0, 264.0)`.
   - GREEN.

3. **`clear()` cursor.** `clear()` now sets Cross in pick mode, else Arrow.
   - Test: `test_plugin_profile_view.py::test_clear_puts_the_normal_cursor_back`. Hover the line (SizeVer), then `clear()` gives Arrow; in pick mode `clear()` gives Cross.
   - RED: `assert 5 == 0` (SizeVerCursor stuck).
   - GREEN.

4. **Press/release guards.** `mousePressEvent` keeps its `transform is None` early-out, then runs `_handle_mouse_press` inside `try / except Exception`, logging "could not handle the mouse press: ...". `mouseReleaseEvent` does the same through `_handle_mouse_release`.
   - The bodies were moved unchanged. One line in the module docstring records both guards.
   - Test: `test_plugin_profile_view.py::test_mouse_press_and_release_report_a_failure_instead_of_leaking_to_qt`. It patches `_near_cutoff` (press) and `clear_selection` (release, on a plain click) to raise. It asserts nothing reaches `sys.excepthook` and a log entry names each.
   - RED (press half): `exception leaked out of mousePressEvent: [(RuntimeError, RuntimeError('simulated'), ...)]`.
   - After guarding the press, RED (release half): the same, from `mouseReleaseEvent`.
   - GREEN.

5. **`_cutoff_row` after close.** It returns -1 when `not self.session.is_open`, with a comment.
   - Test: `test_plugin_profile_dock.py::test_closing_the_site_with_the_cutoff_selected_is_quiet_in_either_order`. A new `processing_first` fixture builds a real `ProcessingDock` before the `ProfileDock` (the reverse of plugin.py) and wires `step_selected` to `set_selected_step`.
   - RED: `assert not ['could not follow the selected step: no site is open']`.
   - GREEN.

6. **Vacuous assertions.**
   - `test_plugin_param_form.py::test_an_unedited_field_commits_the_exact_value_it_was_built_from` now asserts `got == [{"end_ns": exact}]`, then `got == [{"end_ns": exact}, {"end_ns": -10.5}]`. The production code was already right.
     - Mutation check: a `commit()` that emits nothing for an unedited form fails it, `assert [] == [{'end_ns': -10.653...}]`.
     - The old `all(...)` / `got[-1]` pair passes that mutant.
   - The three dock tests (`test_a_drag_to_the_same_time_writes_nothing`, `test_a_drag_with_nothing_selected_writes_nothing`, `test_a_preview_hides_the_line_and_refuses_a_drag`) now also assert no "could not move the time cutoff" entry in `message_log`. The new I1 and I2 dock tests assert the same.
     - Mutation check: `raise RuntimeError("MUTANT")` as the first line inside `_on_cutoff_dragged`'s guard fails all six. Without the log check, each would have passed, because a crash writes nothing.
   - R3 pin, ported from `test_probe_form_echo.py`: `test_plugin_time_cutoff.py::test_a_dragged_cutoff_survives_an_unedited_commit_of_the_form`.
     - It sweeps the record (every 7th sample): drag, check that the form shows the value, then run an unedited `form.commit()`. It asserts no `stack_changed` and `end_ns` unchanged.
     - It also asserts that at least one swept end could not be held exactly in the form's text, so the sweep cannot dodge the hazard.
     - It passes as a pin should. Mutation check: `values()` always parsing the text fails it, "1 samples: '-10.8695' was written back".

All mutants were reverted. `git status` was clean before each commit, and there are no `.pyc` files or probe files in the tree.

## Counts

- Pure + core: `606 passed, 3 skipped` (unchanged; no tests added there).
- QGIS tier, full (`packages/nsgeo-qgis/tests/qgis`, with `-s`): `709 passed in 325.67s`. That is the 694 baseline plus 15 new: 6 in the view file, 6 in the dock file, 3 in the time-cutoff file.
- `-s` traceback check: no `Traceback` anywhere in the full-tier `-s` output.
  - The only stderr is 12 GDAL `ERROR 1: sqlite3_get_table(... 'picks' ...) failed: unable to open database file` lines. These are C-level GDAL messages, not Python exceptions.
  - `test_plugin_layers.py` alone prints 7 of them. It imports only `PICK_COLOUR` from `profile_view`, and this branch has no diff in `layers`/`session`, so they predate this work.
  - The six touched files (view, dock, param_form, time_cutoff, difference_presets, processing_dock), run together with `-s`, gave 215 passed and no traceback.
- Lint: `ruff check .` All checks passed; `ruff format --check .` 134 files already formatted.
- Types (the pinned mypy command): Success: no issues found in 33 source files.

## Concerns

- **Message dedup (I3).** The result path skips an `error` whose text matches the declined difference's.
  - This goes beyond R7's text. Without it, R7 regresses a failing step under an active difference view from one message to two identical ones (pinned by `test_a_step_failing_under_the_difference_view_is_reported_once`).
  - The controller may prefer another way.
- **R7 side effect, previews.** The result path no longer goes through `_decline_difference`.
  - Before, a bad step on a previewed line's result reset the working line's `_difference_index` and emitted `difference_cleared`, a preview changing the working line's state.
  - Now it only reports. I think that is right (spec §3.3: the difference mode returns intact on snap-back), but it is a behaviour change. No test pins either way.
  - An `IndexError` on the result path, which is unreachable because `_cutoff_row` range-checks, would now reach the render slots' broad `except` rather than be mislabelled "the differenced step no longer exists".
- **I1 threshold is stateless.** A drag that goes past the threshold and comes back within 3 px of the press snaps back to the exact start value. This follows R6's wording. If the controller meant "once a drag starts, the threshold no longer applies", the difference shows only for off-grid start values.
- **Test placement.** The `time_zero` decline test is in `test_plugin_profile_dock.py` (dock level), not `test_plugin_difference_presets.py`, to stay inside the listed files.
