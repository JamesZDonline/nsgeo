# Time Cutoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** A `time_cutoff` processing step that hides every sample after a chosen two-way time, set by dragging a line on the profile.

**Architecture:** The core gains a pure step (`time_cutoff`, which crops rows off the end the way `time_zero` crops them off the front), a new parameter kind `"time"` that marks a parameter as a time on the profile's axis, and `StepStack.result_bypassing(i)`, which evaluates a stack with one step skipped. The plugin draws a draggable line in `ProfileView`. While a cutoff step is selected in the Processing panel, `ProfileDock` renders the stack with that step bypassed, so the samples below the line stay visible (dimmed) and the line can be dragged back down. A drag writes the step's `end_ns` through `session.replace_step`, like every other edit.

**Tech Stack:** Python 3, numpy (core); PyQt via `qgis.PyQt` (plugin); pytest on two tiers (core+pure in `.venv`, QGIS in `.venv-qgis`).

**Spec:** No separate spec file. The design was approved in chat on 2026-10-16 and is restated in full under "Design" below. Executors read this section as the spec.

## Design (approved in chat, 2026-10-16)

What the user said:
- A new processing step that hides everything after a cutoff time, for the part of the record where the signal has attenuated and only noise is left.
- The cutoff is set by dragging a horizontal line on the profile.
- It behaves like every other step: it is set per line, "Apply to grid…" carries it to the rest of the grid, presets hold it, and it is saved with the project.
- Nothing is thrown away. The `.dzt` file is never touched. Deleting the step, or dragging the line lower, brings the samples back.
- While the step is selected in the Processing panel, the samples below the line are shown dimmed so the line can be dragged back down. When anything else is selected, the profile shows the clipped result.

Calls made by Claude and played back to the user without objection:
- When the step is added, the line starts at the bottom of the record, so adding it changes nothing until it is dragged.
- The Processing panel shows the cutoff as a number field in ns, kept in step with the line, so an exact value can be typed.
- While dragging, a label next to the line reads the time, plus the depth when a velocity is set. The line snaps to whole samples.
- The Slices panel needs no change.

Calls made while writing this plan. Check these:
- The step is listed as `time_cutoff`, matching how every other step is named in the list (`time_zero`, `gain_agc`). The chat said "Time cutoff".
- **Correction to the chat:** slices are built from the preset chosen in the Slices panel, not from each line's own stack. A cutoff reaches the slices when it is part of that preset. When it is, the slice time range already clamps to it (`SlicesDock._clamp_z_to_prepared`). So the Slices panel still needs no change, but a cutoff on one line's stack does not, by itself, shorten the slices.
- `end_ns` is a required parameter with no stored default, like `gain_curve`'s points. The front end seeds it with the record's end when the step is added. There is no safe default time a saved file could carry.
- `end_ns` is absolute two-way time on the same axis the profile displays. `time_zero` keeps absolute times (it moves `t0_ns`, it does not re-zero), so the step means the same thing wherever it sits in the stack, and "Apply to grid…" gives every line the same time below the top of its own axis.
- A cutoff later than a line's record is a no-op for that line, not an error. That case is the normal one after "Apply to grid…" across lines of different lengths. A cutoff at or before a line's first sample raises `ValueError`, as `time_zero` does when it would leave no samples.
- A drag that ends without the left button still held (the window lost focus mid-drag) is abandoned. The line goes back to where the drag started and nothing is written, so a drag can never write silently.
- The line is magenta, distinct from the cursor (orange), the selection (blue), the slice band (cyan) and the picks (red-orange).

## Global Constraints

- Core stays numpy-only, with no Qt imports. `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` (6 tests together) must stay green.
- The plugin imports Qt only through `qgis.PyQt`.
- Steps never mutate their input radargram (`test_none_of_the_steps_mutate_their_input`).
- Every slot connected to a signal, and every Qt-invoked override, guards its own body and reports through `_log`, never raises. Read the module docstrings of `profile_view.py` and `profile_dock.py` before touching either file.
- Which parameter is a draggable time is decided by the schema's `kind`, never by the step's name. This is the same rule `plugin.py`'s `_curve_param_name` follows.
- ruff 0.17.1 and mypy 2.4.0, as pinned in CI.

## Verification commands (exactly these)

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`. Baseline at `6a7f112`: 588 passed, 2 skipped.
- qgis: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh`. Baseline: 666 passed, about 7 minutes.
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`

The worktree's own `.venv` and `.venv-qgis` are built, and the real DZT files are symlinked into `packages/nsgeo-core/tests/data/local/`. A real-data test that skips has validated nothing, so check the skip count.

## Review Focus

These are the input classes most likely to hurt a user. Each is pinned by a test in the task named.

1. **Apply to grid onto lines of different lengths.** A cutoff past a shorter line's record must leave that line unchanged and must not raise (Task 1: `test_a_cutoff_past_the_record_is_a_no_op`).
2. **Dragging the line off the top or bottom of the image.** The line must clamp so at least one sample is kept and never more than the record (Task 2: `test_dragging_above_the_record_keeps_one_sample`, `test_snap_cutoff_clamps_into_the_record`).
3. **Switching lines while the cutoff row is selected.** The Processing panel keeps the row index, so the new line's step at that row may not be a cutoff at all. The profile must show what that line's stack actually holds (Task 3: `test_switching_lines_reads_the_new_lines_step_at_the_selected_row`).
4. **Hovering another line on the map while the cutoff is selected.** A preview is never a write target. The line must disappear for the preview, a drag signal must write nothing, and the line must come back on snap-back (Task 3: `test_a_preview_hides_the_line_and_refuses_a_drag`).
5. **A click on the line with no movement, or a drag released where it started.** Neither must dirty the session. A save prompt for an edit the user never made is the failure `_on_gain_points` already guards against (Task 3: `test_a_drag_to_the_same_time_writes_nothing`).

---

### Task 1: The `time_cutoff` step, the `"time"` kind, and `result_bypassing`

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/timecutoff.py`
- Modify: `packages/nsgeo-core/src/nsgeo/processing/__init__.py` (import `timecutoff` beside `timezero` so it registers)
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py`: `ParamSpec.KINDS` and its docstring; `_validate_params`'s numeric branch
- Modify: `packages/nsgeo-core/src/nsgeo/processing/stack.py`: add `result_bypassing`
- Test: create `packages/nsgeo-core/tests/test_steps_timecutoff.py`
- Test: modify `packages/nsgeo-core/tests/test_stack.py`, `test_schema.py`, `test_steps_background.py`, `test_real_files.py`

**Interfaces:**
- Produces: `build_step("time_cutoff", end_ns=<float>)`. The step's `params` is `{"end_ns": float}`. `schema()` returns one `ParamSpec(name="end_ns", kind="time", label="Cutoff", default=REQUIRED, unit="ns", help="Hide every sample at or after this two-way time. Drag the line on the profile to set it.")`.
- Produces: `ParamSpec.KINDS == ("float", "int", "choice", "curve", "time")`. A `"time"` parameter is a float two-way time in ns, on the radargram's own axis. It validates and bounds-checks exactly like `"float"`.
- Produces: `StepStack.result_bypassing(index: int) -> Radargram`. It returns what `result()` would be with step `index` switched off. It raises `IndexError` for an index out of range, with the same message `intermediate` uses.

- [ ] **Step 1: Write the failing step tests** in `test_steps_timecutoff.py`. Use a `make()` helper like the one in `test_steps_timezero_dewow.py`.

```python
def test_keeps_the_rows_before_the_cutoff_and_the_start_time():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=-4.0)
    out = build_step("time_cutoff", end_ns=-4.0 + 37 * 0.5).apply(rg)
    assert out.n_samples == 37
    assert out.t0_ns == rg.t0_ns
    np.testing.assert_array_equal(out.data, rg.data[:37])

def test_a_snapped_boundary_on_a_real_world_axis_keeps_exactly_m_rows():
    # dt and t0 as this repo's real HS350 headers carry them; t0 + m*dt is inexact in binary
    rg = make(n_samples=512, dt_ns=0.21653111279010773, t0_ns=-11.086392402648926)
    for m in (1, 2, 255, 300, 511):
        end = rg.t0_ns + m * rg.dt_ns
        assert build_step("time_cutoff", end_ns=end).apply(rg).n_samples == m

def test_a_cutoff_between_samples_keeps_every_sample_before_it():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=0.0)
    assert build_step("time_cutoff", end_ns=10.2).apply(rg).n_samples == 21  # samples at 0.0 .. 10.0

def test_a_cutoff_past_the_record_is_a_no_op():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=0.0)
    assert build_step("time_cutoff", end_ns=50.0).apply(rg) is rg  # exactly the record end
    assert build_step("time_cutoff", end_ns=1e6).apply(rg) is rg

def test_a_cutoff_at_or_before_the_first_sample_is_refused():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=2.0)
    for end in (2.0, -5.0):
        with pytest.raises(ValueError, match="would leave no samples"):
            build_step("time_cutoff", end_ns=end).apply(rg)

def test_end_ns_is_required_and_must_be_a_finite_number():
    with pytest.raises(ValueError, match="end_ns"):
        build_step("time_cutoff")
    with pytest.raises(ValueError, match="must be a number"):
        build_step("time_cutoff", end_ns="late")

def test_the_schema_declares_a_time_parameter_in_ns():
    (spec,) = get_step("time_cutoff").schema()
    assert (spec.name, spec.kind, spec.unit, spec.required) == ("end_ns", "time", "ns", True)
```

- [ ] **Step 2: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_timecutoff.py -q`. Expected: FAIL with `KeyError: unknown step 'time_cutoff'`.

- [ ] **Step 3: Add the `"time"` kind and the step.** In `base.py`, add `"time"` to `KINDS`, describe it in the `ParamSpec` docstring, and change `_validate_params`'s `spec.kind in ("float", "int")` to include `"time"`. In `timecutoff.py`, write `@register class TimeCutoff` with `name = "time_cutoff"`, `__init__(self, end_ns: float)` storing `float(end_ns)`, plus `params`, `schema` and `apply`. `apply` keeps `m = math.ceil((end_ns - t0_ns) / dt_ns - 1e-9)` rows. The tolerance is a billionth of a sample, so a snapped boundary `t0 + m*dt` keeps exactly `m`. When `m >= n_samples`, return `rg` itself. When `m <= 0`, raise `ValueError(f"time_cutoff at {end_ns:g} ns would leave no samples (the record starts at {t0_ns:g} ns)")`. Otherwise return `rg.replace(data=rg.data[:m, :].copy())`. Mirror `timezero.py`'s module docstring and layout. Import the module in `processing/__init__.py`.

- [ ] **Step 4: Run them and see them pass.** Same command. Expected: 7 passed.

- [ ] **Step 5: Write the failing `result_bypassing` tests** in `test_stack.py`, using its `stack_of` helper:

```python
def test_result_bypassing_skips_only_that_step():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("time_cutoff", {"end_ns": 6.0}), ("gain_agc", {"window_ns": 2.0}))
    expected = stack_of(("dewow", {"window_ns": 4.0}), ("gain_agc", {"window_ns": 2.0})).result()
    np.testing.assert_array_equal(st.result_bypassing(1).data, expected.data)
    assert st.result_bypassing(1).n_samples == 64 and st.result().n_samples == 30

def test_result_bypassing_reuses_the_prefix_and_leaves_the_real_chain_alone():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("time_cutoff", {"end_ns": 6.0}), ("gain_agc", {"window_ns": 2.0}))
    st.result_bypassing(1)
    assert st.cache_size == 1  # only the prefix before the bypassed step
    assert st.result().n_samples == 30

def test_result_bypassing_honours_disabled_steps_after_it():
    st = stack_of(("time_cutoff", {"end_ns": 6.0}), ("background_mean", {}))
    st.set_enabled(1, False)
    np.testing.assert_array_equal(st.result_bypassing(0).data, st.source.data)

def test_result_bypassing_rejects_an_out_of_range_index():
    with pytest.raises(IndexError, match="out of range"):
        stack_of(("dewow", {"window_ns": 4.0})).result_bypassing(1)

def test_a_cutoff_round_trips_through_dicts():
    st = stack_of(("time_cutoff", {"end_ns": 6.0}))
    again = StepStack.from_dicts(st.to_dicts())
    assert again.entries[0][0].params == {"end_ns": 6.0}
```

(`source()` in that file is 64 samples at dt 0.2 from t0 0.0, so `end_ns=6.0` keeps 30 rows.)

- [ ] **Step 6: Run them and see them fail** with `AttributeError: 'StepStack' object has no attribute 'result_bypassing'`. Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_stack.py -q`.

- [ ] **Step 7: Implement `StepStack.result_bypassing`.** Start from `self.intermediate(index - 1)` (or `self._source` when `index == 0`), so the cached prefix is reused and only the real chain is ever cached. Then apply each later enabled step in order, without caching.

- [ ] **Step 8: Run it and see it pass.** Same command.

- [ ] **Step 9: Update the registry-wide tests the new step and kind touch.** In `test_schema.py`, `_placeholder` returns `1.0` for `"time"` as well as `"float"`. `test_only_the_two_known_steps_have_required_params` becomes `test_only_the_known_steps_have_required_params` and adds `"time_cutoff": ("end_ns",)` to the expected dict; keep its docstring's point and add one line on why. In `test_steps_background.py`, `_STEP_PARAMS` gains `"time_cutoff": {"end_ns": 10.0}`. Then add one real-data test to `test_real_files.py`:

```python
def test_a_cutoff_after_time_zero_keeps_the_first_rows_of_a_real_profile():
    h = read_header(FILES[0])
    rg = Radargram(data=read_samples(FILES[0])[0].astype(float), dt_ns=h.dt_ns, t0_ns=h.position_ns)
    stack = StepStack()
    stack.source = rg
    stack.append(build_step("time_zero", mode="first_break", threshold=0.25))
    zeroed = stack.result()
    stack.append(build_step("time_cutoff", end_ns=zeroed.t0_ns + 300 * zeroed.dt_ns))
    out = stack.result()
    assert out.n_samples == 300 and out.t0_ns == zeroed.t0_ns
    np.testing.assert_array_equal(out.data, zeroed.data[:300])
    assert stack.result_bypassing(1).n_samples == zeroed.n_samples
```

- [ ] **Step 10: Run the whole core + pure tier, lint and types.** Expected: 588 + the new tests passed, 2 skipped (the real-data tests must not be among the skips). ruff and mypy clean.

- [ ] **Step 11: Commit and push.**

```bash
git add packages/nsgeo-core
git commit -m "feat(core): time_cutoff step, the time parameter kind, and StepStack.result_bypassing"
git push
```

---

### Task 2: The draggable cutoff line in `ProfileView`

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`: add `ViewTransform.snap_cutoff`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`

**Interfaces:**
- Produces: `ViewTransform.snap_cutoff(time_ns: float) -> float`. It returns `t0_ns + m * dt_ns` with `m = round((time_ns - t0_ns) / dt_ns)`, clamped to `[1, n_samples]`. So the line always sits on a sample boundary, keeps at least one sample, and never passes `t_end`.
- Produces in `profile_view.py`: the constants `CUTOFF_COLOUR = QColor(214, 39, 140)`, `CUTOFF_DIM = QColor(250, 250, 250, 170)` and `CUTOFF_GRAB_PX = 5`, and the module function `cutoff_label(end_ns: float, velocity: VelocityModel | None) -> str`. It returns `f"{end_ns:.1f} ns"`, and appends `f" · {depth:.2f} m"` when a velocity is given, with `depth = float(velocity.depth_at(np.array([end_ns]))[0])`.
- Produces on `ProfileView`:
  - `cutoff_dragged = pyqtSignal(float)`. It is emitted once, on the left-button release that ends a drag of the line, carrying the snapped end time in ns.
  - `set_cutoff(end_ns: float | None) -> None`. `None` hides the line. A non-finite value is logged and treated as `None`, the same as `set_slice_band`. If a drag is in progress, it is abandoned: no emit, and the new value is taken.
  - `cutoff_ns -> float | None`, a read-only property. It is the value drawn now, live during a drag.
  - `_cutoff_y(t: ViewTransform) -> float | None`, the line's local y, factored out like `_slice_band_bounds` so tests can assert on it without pixels. The time is clamped into `[t.t0_ns, t.t_end]` before `t.y_of_time`.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_view_transform.py`:

```python
def test_snap_cutoff_rounds_to_the_nearest_sample_boundary():
    t = ViewTransform.fit(100, 200, -4.0, 0.5, 400, 300)
    assert t.snap_cutoff(20.3) == pytest.approx(20.5)  # (20.3 + 4) / 0.5 = 48.6 -> 49
    assert t.snap_cutoff(20.2) == pytest.approx(20.0)

def test_snap_cutoff_clamps_into_the_record():
    t = ViewTransform.fit(100, 200, -4.0, 0.5, 400, 300)
    assert t.snap_cutoff(-100.0) == pytest.approx(-3.5)  # one sample kept
    assert t.snap_cutoff(1e6) == pytest.approx(t.t_end)
```

- [ ] **Step 2: See them fail, implement `snap_cutoff`, see them pass.** Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py -q`.

- [ ] **Step 3: Write the failing view tests** in `test_plugin_profile_view.py`. Use the existing `view` and `make_view` fixtures. The `view` fixture is 200 traces by 128 samples, dt 0.5, t0 -4.0, so the record runs from -4.0 to 60.0 ns. Use `_send_move_while_pressed` for any mid-drag move; plain `QTest.mouseMove` is never delivered while a button is down (see `test_drag_selects_a_trace_range`'s docstring).

  - `test_the_cutoff_line_sits_at_its_time`: `set_axes(100, 200, 0.0, 0.5)`, `set_cutoff(40.0)`, then `_cutoff_y(t) == approx(t.y_of_time(40.0))` and `cutoff_ns == 40.0`.
  - `test_a_cutoff_past_the_record_is_drawn_at_its_bottom_edge`: `set_cutoff(1e6)` puts the y at `t.y_of_time(t.t_end)`.
  - `test_set_cutoff_none_hides_it_and_a_non_finite_one_is_logged` (uses the `message_log` fixture): `None` gives `_cutoff_y(...) is None`; `float("nan")` gives `None` plus one log entry.
  - `test_the_cutoff_dims_the_samples_below_it`: paint a solid black `QImage` (`QImage(200, 128, QImage.Format.Format_RGB32)` filled with black) with `set_cutoff(30.0)`. In `grab_image()`, at `x = r.left() + 20` (clear of the right-aligned label), a pixel 10 px below the line is lighter than one 10 px above, and a pixel on the line row has a red channel of at least 150.
  - `test_the_label_names_the_time_and_the_depth`: `cutoff_label(40.0, None) == "40.0 ns"` and `cutoff_label(40.0, VelocityModel.constant(0.08)) == "40.0 ns · 1.60 m"`.
  - `test_dragging_the_cutoff_emits_the_snapped_time_once_on_release`: `set_cutoff(40.0)`. Press left at `(r.left() + 100, r.top() + round(_cutoff_y))`. Move to local y `y2 = round(t.y_of_time(20.3))`, then release there. `cutoff_dragged` fired exactly once with `approx(t.snap_cutoff(t.time_of_y(y2)))`. `range_selected` and `selection_cleared` never fired. `cutoff_ns` equals the emitted value.
  - `test_dragging_above_the_record_keeps_one_sample`: the same press, a move to local y `-50`, then release. The emitted value is `approx(-4.0 + 0.5)`.
  - `test_a_press_away_from_the_line_still_selects_a_range`: `set_cutoff(40.0)`, then repeat `test_drag_selects_a_trace_range`'s gesture at `r.top() + 50`, which is far from the line. `range_selected == [(28, 86)]` and `cutoff_dragged` never fired.
  - `test_pick_mode_wins_over_the_cutoff_grab`: `set_pick_mode(True)`, then press on the line. `pick_requested` fired once and `cutoff_dragged` never fired after the release.
  - `test_a_move_without_the_button_abandons_the_drag`: press on the line, move with the button held (`cutoff_ns` changes), then `send_hover` with no button held. `cutoff_ns` is back to `40.0`. A following release emits nothing.
  - `test_set_cutoff_during_a_drag_abandons_it`: press on the line, move, then `set_cutoff(30.0)`, then release. Nothing is emitted and `cutoff_ns == 30.0`.
  - `test_hovering_the_line_shows_a_resize_cursor`: `send_hover` on the line gives `cursor().shape() == Qt.CursorShape.SizeVerCursor`. Hovering away gives `ArrowCursor`, or `CrossCursor` in pick mode.
  - `test_clear_forgets_the_cutoff`: `clear()` gives `cutoff_ns is None`.

- [ ] **Step 4: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py -q -p no:xonsh -k "cutoff or label"`.

- [ ] **Step 5: Implement the overlay and the gesture in `profile_view.py`.**
  - Painting: `_paint_cutoff(p, r, t)` is called in `paintEvent` right after `_paint_slice_band` and before `_paint_selection`, so the selection, picks and cursor stay on top. It fills `CUTOFF_DIM` from the line down to `r.bottom()`, draws a 2-px `CUTOFF_COLOUR` line across `r`, and draws `cutoff_label(self.cutoff_ns, self._velocity)` right-aligned just above the line, inside `r`.
  - Precedence on a left press: pick (pick mode or Shift), as today. Then the cutoff grab, when a cutoff is shown, the press is inside the image (`0 <= x < t.width` and `0 <= y < t.height`) and `abs(y - _cutoff_y) <= CUTOFF_GRAB_PX`. Then the existing range-select arming. A cutoff grab records the starting value and does not arm `_press`, so its release can neither commit nor clear a selection.
  - A move during a grab: if `event.buttons()` lacks the left button, abandon (the I3 pattern in `_handle_mouse_move`). Otherwise set the value to `t.snap_cutoff(t.time_of_y(y))` and `update()`.
  - A left release during a grab ends it and emits `cutoff_dragged(self.cutoff_ns)`. Always emit; the no-op guard lives in the dock (Task 3).
  - Hover with no grab: set `SizeVerCursor` near the line. Otherwise restore the cursor `set_pick_mode` would set.
  - `clear()` resets the cutoff and any grab.
  - Extend the module docstring's opening line to name the cutoff line among the overlays.

- [ ] **Step 6: Run them and see them pass.** Then run the whole `test_plugin_profile_view.py` file, and the pure tier for `test_no_orphan_signals.py`. `cutoff_dragged` has no consumer until Task 3, so if that test fails here, add a one-line `KNOWN_UNCONSUMED` entry naming Task 3, and remove it in Task 3.

- [ ] **Step 7: Lint, types, commit, push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui packages/nsgeo-qgis/tests
git commit -m "feat(plugin): a draggable cutoff line on the profile view"
git push
```

---

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

### Task 4: Build and walkthrough (human gate, not a code task)

The user's rule: deploy and a manual walkthrough come before any merge decision. This task ends when the user reports back. It never ends by merging.

- [ ] **Step 1: Verify the branch head from clean.** Run both tiers, lint, types and the 6 boundary tests, and record every count.
- [ ] **Step 2: Deploy to a new QGIS profile `ns_geo_cutoff`** with `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo_cutoff`, run from this worktree. That leaves `ns_geo` and `ns_geo_m12`, and the walkthroughs they serve, untouched. Check the symlink with `ls -la` on the profile's plugins directory.
- [ ] **Step 3: Publish a walkthrough page** as a claude.ai Artifact with the `db` capability, the same pattern as M9's and M12's walkthrough pages. Each check has a pass/fail plus notes. Checks:
  - adding `time_cutoff` puts the line at the bottom and changes nothing;
  - dragging it up on a real line, where the signal dies out, and the time/depth label while dragging;
  - selecting another step shows the clipped profile, and reselecting shows the dimmed tail again;
  - dragging back down recovers samples;
  - typing an exact value in the Processing panel;
  - "Apply to grid…", then opening another line;
  - saving and reopening the project;
  - a preset holding the cutoff used for slices, where the slice range stops at the cutoff;
  - hovering another line on the map mid-session;
  - whether the zoom resetting when switching between the cutoff step and another step is acceptable. It resets because the row count changes and `_render` refits.
- [ ] **Step 4: Report the walkthrough to the user and wait for their results.** Fix rounds go back through Tasks 1–3's test-first discipline. Merging is offered only afterwards, via superpowers:finishing-a-development-branch, and asked, never assumed.

## Follow-ups (not in this plan)

- **Help pages:** the `nsgeo-help-pages` branch's `test_every_registered_step_has_a_page_unless_pending` will fail once both branches are on main, because there is no `time_cutoff.html` yet. Whichever branch merges second adds `"time_cutoff"` to its `PENDING` set, or writes the page.
- **M12 (`nsgeo-m12`):** it touches `plugin.py` in other regions. Expect a small textual merge at the `step_selected` connections and nothing semantic.
- **metadata.txt changelog:** it is per release, so it waits for the next version bump.
