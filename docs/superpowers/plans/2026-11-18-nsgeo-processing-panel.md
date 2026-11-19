# Processing panel: gain strip, Difference view and refusals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A step that can't run on the open line stays marked in the Processing panel until it is
fixed. The gain strip only shows the curve the step has, reaches every point and resets to flat.
The Difference view follows the selected step. The panel names its line.

**Architecture:**
- The core's `StepStack` names the step that refused (`StepRefused`).
- `ProcessingDock` checks its own line's result and shows the note in session A's
  `WarningsPanel`.
- `ProfileDock` stops showing another line's picture when a line's steps can't run.
- `GainStrip` caps and clamps at ±120 dB, pins off-record points to the record's edge, measures
  its caption and gains a Reset button.
- `plugin.py`'s gain slots are guarded, snap a refused curve back, handle Reset, and wait for the
  strip's clock.

**Tech Stack:** Python, QGIS 3.44 / 4.2 (PyQt5 / PyQt6), pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-nsgeo-processing-panel-design.md`. Read the sections
your task names before you start. Session A's `ui/warnings_panel.py` is the Warnings box reused here.

## Global Constraints

- **Run everything from the worktree root**
  `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-processing-panel`. It shares
  the main checkout's virtualenvs. Real data is linked under `packages/nsgeo-core/tests/data/local/`.
  `M=/home/jameszd/Documents/Github/archaeo_geophysics` below.
  - One QGIS file: `PYTHONDONTWRITEBYTECODE=1 packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/<file> -q -p no:cacheprovider`
  - Real-data QGIS tests: `PYTHONDONTWRITEBYTECODE=1 packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q -p no:cacheprovider`
  - Core and pure: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src $M/.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh -p no:cacheprovider`.
    `PYTHONPATH` is required: without it, `.venv` imports the main checkout's core.
  - Lint, as CI runs it: `$M/.venv/bin/ruff check . && $M/.venv/bin/ruff format --check .`
- **Before you report a task done,** run:
  - your task's own test files;
  - `test_plugin_processing_dock.py`, `test_plugin_profile_dock.py`, `test_plugin_gain_strip.py`
    and `test_plugin_difference_presets.py`;
  - the core and pure command;
  - lint.

  Don't run the whole QGIS tier (`qgis_tests.sh full`): the coordinator does that, and CI covers it.
- **Each test that pins a bug must fail before its fix.** Run it, see it fail for the reason it
  names, then fix. Say in your report how each one failed. A guard test (one that already passes)
  says so in its docstring, and says which mutation makes it fail.
- **Temporary mutations:**
  - Revert a temporary mutation by hand, and check that `git diff` shows only intended changes
    before you commit.
  - Never use `git stash`: the stash is shared with other sessions.
- **Every Qt slot and override guards its own body** (`try` / `except Exception` / `_log` in the
  UI files, `self.message(...)` in `plugin.py`), as the files already do.
- **The Processing panel must not get wider.** `test_plugin_slices_width.py` pins the Slices
  panel to `ProcessingDock(session).minimumSizeHint().width()`. Every new label word-wraps, with
  `QSizePolicy.Policy.Ignored` horizontally, as `WarningsPanel` does.
- **Leave alone:**
  - the velocity strip and velocity-fit code in `profile_dock.py` (session Q may change it);
  - `param_form.py`;
  - every `plugin.py` slot except the gain slots and `unload()` (M17a, M19a and M16 Plan D have
    open branches there).
- **A note never repeats a toast's job, and a toast never replaces a note.** The toast
  (`ProfileDock.error` → `plugin.message`) still announces each refusal as today. The note is
  added to it (spec §3.1).
- **Real data:** read the campus lines through `plugin_testing.REAL_DZT`, mark tests with
  `needs_real_data`, and pick `FILE__007.DZT` by name (Δt 0.2165 ns). Never read or write the
  author's own projects.
- **Commits:**
  - one or more per task: `feat(processing): …`, `fix(gain-strip): …`, `test(…): …` or
    `docs(guide): …`;
  - end each message with your own `Co-Authored-By` line;
  - the coordinator pushes.

## Review Focus

These are inputs the spec implies that no bug test exercises. Each has its test in the owning
task.
1. **A refusal on a line whose samples arrive later.** Open the line before its profiles load.
   The note appears on `line_loaded`, not only on the next edit (Task 1).
2. **Two refusing steps.** Only the first is noted, because the later one never runs. Fixing the
   first moves the note to the second (Task 1).
3. **A preset or Apply to grid brings a refusing setting onto the open line.** The note appears
   with no edit in the panel (Task 1).
4. **Reset on a curve behind Time zero** writes the flat curve on the Time zero clock (the step's
   input), not the radar's (Task 3).
5. **A zoomed profile.** A point outside the zoomed window but inside the record is not pinned to
   the edge; only points outside the record are (Task 2).

---

### Task 1: A refusal that stays (#197)

Spec §3. The core names the refusing step; the Processing panel shows it under the list and marks
its row; the Profile panel stops showing another line's picture when a line's steps can't run.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/stack.py` (`_ensure`, `result_bypassing`,
  new class), `packages/nsgeo-core/src/nsgeo/processing/__init__.py` (export)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (`__init__` layout, `rebuild`,
  `_on_line_loaded`, new check)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`_show_line`'s branch with
  profiles, `_on_line_loaded`, new helper, two constants)
- Modify: `docs/guide/getting-started.md` (the "A setting that cannot work…" paragraph)
- Test: `packages/nsgeo-core/tests/test_stack.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Produces:
  - `nsgeo.processing.StepRefused(ValueError)`, built as `StepRefused(message: str, index: int,
    title: str)`. It has `.index` (0-based) and `.title`, `str(e) == message`, and it survives a
    pickle round trip;
  - `ProcessingDock.warnings: WarningsPanel`;
  - `ProcessingDock.refusal() -> StepRefused | None`;
  - `processing_dock.REFUSAL_TEXT`, `processing_dock.REFUSAL_COLOUR`;
  - `profile_dock.STEPS_REFUSED_TEXT`, `profile_dock.PREVIEW_STEPS_REFUSED_TEXT`.
- Consumes: `ui.warnings_panel.WarningsPanel`, `Entry`, `REFUSAL` (unchanged).

- [ ] **Step 1: Write the failing core tests** in `test_stack.py`:
  - `test_a_refusing_step_is_named_by_index_and_title`: a stack of `dewow` (default) then
    `bandpass(low_mhz=100.0, high_mhz=90_000.0)` on a synthetic radargram with dt 0.2165 ns.
    `pytest.raises(StepRefused)` on `result()`. `e.index == 1`, `e.title == "Bandpass"` (use the
    step's own `title`), `"Nyquist" in str(e)`, and `isinstance(e, ValueError)`.
  - `test_a_refusal_in_a_bypass_chain_is_named_too`: the same through `result_bypassing(0)`;
    `e.index == 1`.
  - `test_a_step_refusal_pickles`: `pickle.loads(pickle.dumps(e))` keeps the message, index and
    title.
  - `test_difference_and_no_source_stay_plain_value_errors`:
    - `difference(i)` on a sample-count-changing `time_zero` raises a `ValueError` that is not a
      `StepRefused`;
    - `result()` with no source raises a `ValueError` that is not a `StepRefused`.
- [ ] **Step 2: Run them** with the core and pure command, `-k refus or pickles or plain_value`.
  Expected: FAIL (`ImportError: StepRefused`).
- [ ] **Step 3: Implement `StepRefused`** in `stack.py`.
  - `__init__(self, message: str, index: int, title: str)` calls `super().__init__(message)`.
  - `__reduce__` returns `(type(self), (str(self), self.index, self.title))`.
  - `_ensure` and `result_bypassing` wrap each `step.apply(...)`: an existing `StepRefused`
    re-raises unchanged; another `ValueError` becomes `StepRefused(str(exc), i, step.title)`,
    raised `from exc`.
  - Export it from `nsgeo.processing` and add it to `__all__`.
- [ ] **Step 4: Run the core tests.** Expected: PASS, and the whole core and pure command still
  passes, with every existing message assertion unchanged.
- [ ] **Step 5: Commit** `feat(processing): the step stack names the step that refused`.
- [ ] **Step 6: Write the failing panel tests** in `test_plugin_processing_dock.py`, on the
  `opened` fixture (synthetic lines, Δt 0.2165 ns):
  - `test_a_refused_step_is_noted_under_the_list_and_marked`:
    - add `dewow`, then replace it with `build_step("dewow", window_ns=0.2)`;
    - `dock.warnings` is visible, and its one entry is `REFUSAL` with text
      `REFUSAL_TEXT.format(title="Dewow", n=1, reason=<the core's message>)`;
    - row 0's text starts with `"⛔ "`, its foreground is `REFUSAL_COLOUR`, and its tooltip
      contains both `"dewow"` (the step's name, as today) and the reason.
  - `test_the_note_is_visible_whichever_row_is_selected`: with a second step added below, select
    row 1; the note is still visible.
  - `test_the_note_clears_when_the_setting_is_fixed`: replace with `window_ns=4.0`. The note is
    hidden, and row 0 has no ⛔ and its old colour.
  - `test_the_note_clears_when_the_step_is_removed`, `..._turned_off` (`set_step_enabled(key, 0,
    False)`), `..._when_another_line_opens` (open `session.keys()[1]`) and
    `..._when_the_site_closes`.
  - `test_an_edit_to_another_step_leaves_the_note`: with the refusing Dewow above
    `background_mean`, turn `background_mean` off. The note stays.
  - Review Focus 1, `test_the_note_appears_when_the_samples_arrive`:
    - open `keys()[1]` with no profiles and a refusing Dewow in its stack: no note;
    - `session.set_profiles(...)`: the note shows.
  - Review Focus 2, `test_two_refusals_note_the_first_then_the_second`:
    - Dewow 0.2 at row 0 and `bandpass(high_mhz=90_000.0)` at row 1: the note names step 1;
    - fix the Dewow: the note names step 2 (Bandpass).
  - Review Focus 3, `test_a_preset_that_refuses_is_noted`:
    - save the current stack as a preset on `keys()[1]` with Dewow 0.2;
    - `apply_preset_named` it on the open line: the note shows.
  - `test_the_note_never_widens_the_panel`:
    - measure `dock.minimumSizeHint().width()`;
    - set a 400-character refusal with a 40-character unbroken token through the real path (a
      step whose message is long), or call `dock.warnings.set_entries` directly;
    - the width is unchanged.
  - `test_the_real_one_sample_dewow_is_noted` (`@needs_real_data`):
    - FILE__007, Dewow `window_ns=0.2`;
    - the note's text is exactly: "Dewow (step 1) can't run on this line: Dewow window 0.2 ns is
      one sample at this line's 0.217 ns sampling; use 0.33 ns or more. The profile won't update
      until this is fixed."
- [ ] **Step 7: Run them.** Expected: FAIL (`AttributeError: warnings` / import of
  `REFUSAL_TEXT`).
- [ ] **Step 8: Implement the panel note** in `processing_dock.py`.
  - The constants:
    - `REFUSAL_TEXT = "{title} (step {n}) can't run on this line: {reason} The profile won't
      update until this is fixed."`. `reason` is the core's message with exactly one final full
      stop: add one when it lacks it.
    - `REFUSAL_COLOUR = QColor(163, 18, 44)`.
  - `self.warnings = WarningsPanel(body)` goes between `self.list` and `self.form_area`.
  - A private `_check_refusal()` runs at the end of `rebuild()` and from `_on_line_loaded` when
    the key is the panel's own:
    - no key, a cut key, or `stack.source is None`: no refusal;
    - otherwise `stack.result()`. A `StepRefused` is the refusal; any other exception is logged
      and gives none.
  - It stores the refusal (read back by `refusal()`), then updates the rows and `self.warnings`:
    - each row's text is `row_label(...)`, with `"⛔ "` in front on the refusing row;
    - the refusing row's foreground is `REFUSAL_COLOUR`, and its tooltip is
      `f"{step.name}\n\n{note}"`. The other rows keep the default foreground and the `step.name`
      tooltip;
    - the item edits run under `self._updating`, since `itemChanged` fires on them.
- [ ] **Step 9: Run the panel tests.** Expected: PASS.
- [ ] **Step 10: Commit** `feat(processing): a step that can't run stays noted under the list (#197)`.
- [ ] **Step 11: Write the failing profile tests** in `test_plugin_profile_dock.py`. Build two
  lines (`FILE__001` placed, then `FILE__002` with a `GridPlacement` label), with profiles set.
  - `test_opening_a_line_whose_steps_refuse_shows_why_not_the_last_picture`:
    - open line A, which renders;
    - give line B `bandpass(low_mhz=100.0, high_mhz=90_000.0)` and open it;
    - `dock.view._image is None` and `dock.view._message == STEPS_REFUSED_TEXT`.
  - `test_a_preview_of_a_line_whose_steps_refuse_says_so`:
    - with A working and B refusing, `session.set_preview(keyB, 3)`;
    - `view._image is None` and `view._message == PREVIEW_STEPS_REFUSED_TEXT.format(name=<B's
      label>)`.
  - `test_back_from_a_preview_to_a_refusing_line_shows_why`:
    - A working, preview B;
    - make A's steps refuse;
    - `session.set_preview(None)`: `view._message == STEPS_REFUSED_TEXT`.
  - `test_a_bad_edit_on_the_open_line_keeps_its_last_picture` (a guard test, which passes
    today): A renders, then a refusing step is appended; `view._image` is unchanged. The
    docstring says it fails if the new helper also runs on `stack_changed`.
- [ ] **Step 12: Run them.** Expected: the first three FAIL (the old image is still set).
- [ ] **Step 13: Implement the profile message** in `profile_dock.py`.
  - The constants:
    - `STEPS_REFUSED_TEXT = "This line's steps can't run. See the Processing panel."`;
    - `PREVIEW_STEPS_REFUSED_TEXT = "{name}'s steps can't run. Select it to see why in the
      Processing panel."`.
  - A private `_show_steps_refused(key: str, *, is_preview: bool) -> None` does what
    `_show_line`'s no-profiles branch does to take the old picture down:
    - `_cutoff_step = None`, `_shown_radargram = None`, `view.set_cutoff(None)`;
    - `_set_axes_holding` from the header, then `view.set_image(None)`;
    - then `view.set_message(...)`. This comes after the axes, because `set_axes` resets the
      message to "loading…".
  - `name` is the label `_show_line` already computes.
  - It is called when `self.image is None` after `_render()`:
    - in `_show_line`'s branch with profiles (pass its `is_preview`);
    - in `_on_line_loaded` (preview when `key == self._preview_key`).
  - It is never called from `_on_stack_changed`.
- [ ] **Step 14: Run the profile tests and the four whole files.** Expected: PASS.
- [ ] **Step 15: Update the guide.** In `docs/guide/getting-started.md`, the paragraph "A setting
  that cannot work …" says:
  - the reason stays in a Warnings box under the step list, with the step marked ⛔, until the
    setting is fixed, the step is removed or turned off, or another line opens;
  - the Profile panel says so when a line's steps can't run.
- [ ] **Step 16: Commit** `fix(profile): a line whose steps can't run says so instead of showing the last picture` and `docs(guide): …`.

### Task 2: The gain strip widget (#49, #8, #9)

Spec §4.1–§4.4 (the strip's half). It is all in `GainStrip`, plus one relay signal and one
docstring in `ProfileDock`.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py` (`_db_range`, `mouseMoveEvent`,
  `mouseDoubleClickEvent`, `handle_at`, `paintEvent`, new button, the module docstring)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (relay signal in `__init__`;
  `show_gain_strip`'s docstring, #25 item 3)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py` (strip-level, on the `strip`
  fixture: transform `fit(100, 200, 0.0, 0.5, 600, 300)`, so the record is 0–100 ns)

**Interfaces:**
- Produces:
  - `gain_strip.DB_LIMIT = 120.0`;
  - `GainStrip.reset_requested = pyqtSignal()` and `GainStrip.reset_button: QToolButton`;
  - `GainStrip.caption_texts() -> tuple[str, str | None, str]`, the (low, "dB" or None, high)
    the paint draws;
  - `ProfileDock.gain_reset_requested = pyqtSignal()`, relayed from the strip.
- The record's extent is read from the strip's own transform: `transform.t0_ns` to
  `transform.t_end`. No new setter.

- [ ] **Step 1: Write the failing tests:**
  - `test_db_limit_matches_the_core`: `DB_LIMIT` equals both bounds of `gain_curve`'s `points`
    schema (`get_step("gain_curve").schema()`, min −120 and max 120).
  - `test_the_range_never_passes_the_limit`:
    - `set_points([[0, 0], [50, 118]])`: `_db_range()[1] == 120.0`;
    - `[[0, 0], [50, -118]]`: `_db_range()[0] == -120.0`.
  - `test_a_drag_to_the_edge_stops_at_120_db`:
    - the issue's repro: points `[[0, 0], [50, 118]]`;
    - drag handle 1 well past the right edge;
    - the emitted point's dB is exactly 120.0, and `strip.points()[1][1] == 120.0`.
  - `test_a_double_click_at_the_edge_adds_at_most_120`: points `[[0, 0], [50, 118]]`. A
    double-click (`plugin_testing.send_double_click`) in empty strip at the right edge adds a point
    of exactly 120.0 dB. Today the range's high end is 124, so it adds 124.
  - `test_a_point_before_the_record_is_pinned_and_reachable`:
    - `set_points([[-11.0, 0.0], [50.0, 12.0], [100.0, 0.0]], "o")`;
    - `handle_at` at `(x_of_db(0.0), y_of_time(0.0))` is 0;
    - a press there, a move to `y_of_time(20.0)` and a release leave point 0 at time ≈ 20 (within
      one pixel's time).
  - `test_a_pinned_point_can_be_right_clicked_away`: same points; a right-click at the pinned
    handle leaves 2 points, with the −11 point gone.
  - `test_a_point_after_the_record_is_pinned_to_the_bottom`: `[[0, 0], [50, 6], [130, 0]]`;
    `handle_at` at `(x_of_db(0.0), y_of_time(100.0))` is 2.
  - Review Focus 5, `test_a_point_outside_a_zoomed_window_is_not_pinned`:
    - `set_time_mapping(t.with_window(0, 100, 20.0, 60.0), MARGIN_TOP)`, points `[[0, 0], [40, 6],
      [80, 0]]`;
    - `handle_at` at the window's bottom edge with point 2's dB x finds nothing.
  - `test_the_caption_fits_at_the_test_font` and `..._at_a_large_font` (`strip.setFont` with point
    size 16):
    - the low and high texts are always present and whole;
    - their `QFontMetrics.horizontalAdvance` widths, plus the middle text's when it is not None,
      fit in `strip.width() - 4`;
    - at the large font, with points at ±120, the middle is None.
  - `test_reset_emits_reset_requested`: `reset_button.click()` emits once;
    `reset_button.isVisible()` while the strip is shown with a transform.
  - `test_profile_dock_relays_reset`: on a `ProfileDock`, clicking `gain_strip.reset_button`
    emits `gain_reset_requested` once.
- [ ] **Step 2: Run them.** Expected: FAIL (an import of `DB_LIMIT`; `_db_range` gives 124; the
  edge handle is not found; the caption doesn't fit).
- [ ] **Step 3: Implement it** in `gain_strip.py`.
  - **`_db_range` and the writes:** `_db_range` caps at ±`DB_LIMIT` (spec §4.1). The frozen range
    during a drag is unchanged. `mouseMoveEvent` and `mouseDoubleClickEvent` clamp the dB they
    write to ±`DB_LIMIT`.
  - **Pinned points:** one private helper gives each point its drawn position. A point earlier
    than `transform.t0_ns` sits at `y_of_time(t0_ns)`, a point later than `transform.t_end` at
    `y_of_time(t_end)`, each at its own dB x.
    - `handle_at` and the handle painting use the helper. The polyline still uses the true
      positions (spec §4.2).
    - An off-record handle draws as a triangle (▲ at the top edge, ▼ at the bottom), with the
      same pen and fill as a round handle.
  - **The caption:** `caption_texts()` picks the texts with `QFontMetrics(self.font())` (spec
    §4.3). `paintEvent` draws the low text left-aligned from x = 2, the high text right-aligned
    to `width() - 2` and the middle text centred, all in the caption row (y 0–14).
  - **Reset:**
    - `self.reset_button = QToolButton(self)` with text `"Reset"`, tooltip `"Reset the gain curve
      to a flat 0 dB"`, emitting `reset_requested`;
    - laid out, in `resizeEvent` and `set_time_mapping`, centred in the band from `self._top +
      transform.height` to `self.height()`;
    - hidden when there is no transform, or when that band is shorter than the button's
      `sizeHint().height()`.
  - Add a fifth paragraph to the module docstring for the limit and the pinned handles.
- [ ] **Step 4: Relay and docstring** in `profile_dock.py`.
  - `gain_reset_requested = pyqtSignal()`, connected next to the `points_changed` relay.
  - Correct `show_gain_strip`'s sentence about a `None` owner (spec §5, #25 item 3). A `None`
    owner with real points ends a gesture only when the strip shows a real owner, and callers
    always pass a real token. Leave the signature as it is.
- [ ] **Step 5: Run the strip tests and the four whole files.** Expected: PASS. The existing
  `test_drag_overshoot_is_clamped_and_the_range_does_not_ratchet` still holds (its range is −6 to
  26).
- [ ] **Step 6: Commit** `fix(gain-strip): stop at ±120 dB, reach off-record points, fit the caption, add Reset (#49, #8, #9)`.

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

### Task 4: The Difference view and the panel's line (#13, #48, #20 item 4, #33)

Spec §6 and §7.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (`_on_rows_moved`, a line label
  at the top, `preview_changed` and `rebuild` updating it)
- Modify: `docs/guide/getting-started.md` (one line in the Processing section)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py` (plugin fixture, two
  lines), `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`

**Interfaces:**
- Consumes: `velocity_records.line_label(line)`; `session.preview_key`; `session.preview_changed`
  (str, int); `session.grid_for_line(line)`.
- Produces:
  - `ProcessingDock.line_label: QLabel`;
  - `processing_dock.LINE_LABEL_TEXT = "<b>{name}</b>{grid}"`, with `grid` being `" · grid {id}"`
    or `""`;
  - `processing_dock.PREVIEW_SUFFIX = " · the profile is previewing {name}"`.
  - Names are escaped with `html.escape`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_drag_reorder_reaims_the_difference_view` (#13; the plugin fixture):
    - add `dewow`, `background_mean` and `gain_agc`; select row 1; Difference on;
    - `pd.list.model().moveRow(QModelIndex(), 1, QModelIndex(), 3)`;
    - `pd.list.currentRow() == 2`;
    - `prd.difference_label.text() == "Difference: Background removal (mean)"`;
    - `prd.image.rg.data` equals `stack.difference(2).data`.
  - `test_selecting_time_zero_with_difference_on_shows_the_result` (#48, the issue's exact
    repro):
    - `time_zero(mode="sample", sample=40)`, then `dewow`; row 1; Difference on; then select
      row 0;
    - the button is unchecked and the label is empty;
    - `prd.image.rg.data` equals `stack.result().data`.

    It is a guard test: it passes on main. Its docstring says so, and says it fails when
    `current_radargram`'s `except ValueError` branch returns None after `_decline_difference`.
    Run that mutation once, and report it.
  - `test_clear_resets_the_difference_view` (#20 item 4; the `opened` profile-dock fixture with
    profiles and two steps):
    - `set_difference_index(1)`, then call `dock._clear()` directly;
    - `_difference_index == -1`, the label is empty, and `difference_cleared` fired once;
    - the docstring says no real path reaches it today, because `close_site` goes through
      `_open("")` first, and that it fails without the reset in `_clear`.
  - `test_closing_the_site_with_difference_on_unchecks_it` (the plugin fixture): Difference on,
    then `s.close_site()`; the button is unchecked and the label is empty.
  - `test_the_panel_names_its_line` (the processing `opened` fixture):
    - `dock.line_label.text()` contains `<b>FILE__001</b>` and `· grid A`;
    - after `session.close_site()` (no line open), it is empty.
  - `test_the_panel_names_the_previewed_line_too`:
    - `session.set_preview(keys[1], 3)`: the label ends with `PREVIEW_SUFFIX.format(name=
      "FILE__002")`;
    - `set_preview(None)`: the suffix is gone.
  - `test_a_line_name_is_escaped_and_never_widens_the_panel`:
    - a line whose label is `"<b>" + "x" * 300`;
    - the text holds `&lt;b&gt;`;
    - `minimumSizeHint().width()` is unchanged.
  - `test_steps_added_during_a_multi_selection_land_on_the_open_line` (#33; the plugin fixture):
    - select both line features on `plugin.layers.layers["lines"]` (copy `_feature_id` from
      `test_plugin_map_link.py`);
    - `pd.add_step("dewow")`: it is on `keys[0]`, and the label names `FILE__001`;
    - select only `keys[1]`'s feature: the list is empty and the label names `FILE__002`;
    - `s.stack_for(keys[0])` still holds the Dewow.
- [ ] **Step 2: Run them.** Expected:
  - the #13 test FAILS: the label says "Automatic gain control";
  - the label tests FAIL (`AttributeError: line_label`);
  - the #48, `_clear` and close tests pass (guards).
- [ ] **Step 3: Implement it** in `processing_dock.py`.
  - `_on_rows_moved` calls `self._emit_difference(True)` after `move_step` when
    `diff_button.isChecked()`.
  - `self.line_label` is a rich-text `QLabel` above the button row: word-wrapped, with an Ignored
    horizontal policy.
  - `_update_line_label()` runs at the end of `rebuild()` and on `session.preview_changed`
    (guarded):
    - it is empty with no line or on a cut key;
    - the preview suffix appears when `session.preview_key` is set and differs from the
      working key.
- [ ] **Step 4: Run the tests and the four whole files,** plus `test_plugin_slices_width.py` and
  `test_plugin_map_link.py`. Expected: PASS.
- [ ] **Step 5: Update the guide.** Add one line in the Processing section: the panel names, at
  its top, the line its steps belong to, and the line a map hover is previewing.
- [ ] **Step 6: Commit** `fix(processing): Difference follows a dragged step; the panel names its line (#13, #33)` and `test(…): pin #48 and #20 item 4`.

### Task 5: Split the step-input queries out of `processing_dock.py` (#21)

The user chose a split on 2026-11-19. There is no behaviour change. The queries that say what a
step receives move to their own module. The "Time zero clock not known yet" rule, which Task 3
copied into `plugin.py`, gets one home.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/step_inputs.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`. `input_axis`, `time_axis`,
  `probe_radargram` and `seed_params` become one-line delegates, with short docstrings that point
  to `step_inputs`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`. `_sync_gain_strip`'s inline clock check
  becomes `step_inputs.clock_unknown(stack, row)`. Nothing else in this file changes.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (one new test). Every
  existing test stays unchanged.

**Interfaces:**
- Produces, in `nsgeo_qgis.step_inputs`:
  - `clock_unknown(stack: StepStack, row: int) -> bool`. True when `stack.source is None` and an
    enabled `time_zero` sits in `stack.entries[:row]`.
  - `input_axis(session: SiteSession, key: str, row: int) -> tuple[float, float, int] | None`.
  - `time_axis(session: SiteSession, key: str) -> tuple[float, float, int]`.
  - `probe_radargram(session: SiteSession, key: str) -> Radargram | None`.
  - `seed_params(session: SiteSession, name: str, key: str) -> dict[str, Any] | None`.

  Each body, its log messages (the `"input_axis: …"`, `"probe_radargram: …"` and
  `"seed_params: …"` texts) and its long docstring move verbatim.
  `input_axis` uses `clock_unknown`.
- Consumes: nothing new.
- The `ProcessingDock` methods keep their names and signatures, so callers in `plugin.py` and the
  tests don't change.

- [ ] **Step 1: Write the guard test.** In `test_plugin_processing_dock.py`, add
  `test_the_clock_rule_has_one_answer` (a guard test; its docstring names the mutation).
  - It is parametrized over all eight cases: samples loaded or not × Time zero enabled or not ×
    the curve's row above or below the Time zero.
  - In every case, `step_inputs.clock_unknown(stack, row)` must be True exactly when
    `dock.input_axis(row) is None`.
  - It fails if `input_axis` keeps a private copy of the rule that differs, for example by
    ignoring `enabled`.
- [ ] **Step 2: Move the code.** No logic edits. Run `git diff --stat`: it should show about 150
  lines leaving `processing_dock.py` and arriving in `step_inputs.py`.
- [ ] **Step 3: Run the tests.** Run:
  - every QGIS file that calls these methods: `test_plugin_processing_dock.py`,
    `test_plugin_param_form.py` and `test_plugin_gain_strip.py`;
  - the four whole files;
  - the real-data run;
  - the pure tier (`packages/nsgeo-qgis/tests/pure`, with the core and pure command's
    `PYTHONPATH`);
  - lint (`ruff check .`, and `ruff format --check` on the changed files only).

  Expected: every one passes, and no existing test was edited.
- [ ] **Step 4: Commit** `refactor(processing): the step-input queries move to step_inputs.py (#21)`.

### After Task 5: #21

Comment on #21 with the split. Close it when the branch merges.
