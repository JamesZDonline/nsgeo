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

