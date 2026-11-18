# Task 2 report: one settle sequence, #200, and restore notes in Warnings

Branch `nsgeo-slices-clock-preset`, from 3f892b9. Commit d7a2d0c (not pushed).

## What I implemented

`packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:

- **`_settle_z() -> bool`**: if a shift is owed and no preparation is running, it consumes the
  shift and applies it (`_shift_z_by_median_zero`). Then it always clamps
  (`_clamp_z_to_prepared`). It returns `owed or clamped`.
- **`_settle_and_push()`**: `_settle_z()`, then `_apply_resolution()`. It replaces
  `_apply_owed_z_shift`, which is deleted.
- **`_on_prepared`**: its shift and clamp lines become `settled = self._settle_z()`, in the same
  place. The push at the end is now `_apply_resolution()` if `settled`, else `refresh_slice()`.
- **`_run_pending_grid_prepare`** (#162 item 3), after `prepare()`, when `engine.choice` is set:
  - **if a preparation is now running:** it pushes now only when no shift is owed and
    (`owed` or `engine.z is None`). `_on_prepared` settles a shift.
  - **otherwise**, when `owed`, `engine.z is None` or a shift is owed: `_settle_and_push()`.
  - then `_sync_grid_slider()`, as before.

  The old clamp-then-apply-then-shift sequence is gone.
- **`restore_cube`** (#200), after `prepare()`:
  - `deferred = self._grid_prepare_pending`;
  - **deferred:** `_resolution_owed = True`, stop the debounce, settle nothing;
  - **elif a shift is owed, or no preparation is running:** stop the debounce;
  - **else:** `flush_debounce()`.

  Then, if the engine is not running, the palette is dropped as before, and `_settle_and_push()`
  runs only when the restore did not defer. **See deviation D1.**
- **Notes in Warnings (spec §8):**
  - `_grid_notes: list[str]` is declared beside `_grid_refusal`.
  - A new helper, `_add_grid_note(text)`, appends a note unless the same text is already there,
    then calls `show_warnings()`.
  - `_shift_z_by_median_zero` adds its `old_cube_note` through it, with no `error.emit`.
  - `restore_cube`'s "moved to another grid since it was saved" note goes through it too.
  - `show_warnings()` in This grid gives `[Entry(REFUSAL, refusal)]` (when there is one) plus
    `[Entry(NOTE, n) for n in _grid_notes]`.
- **Where `_grid_notes` is reset to `[]`:**
  - at the start of a restore that passed its checks;
  - in `_drop_restore_pending()`, which also re-shows Warnings when it had notes;
  - in `_mark_cube_unsaved()`, when it moves the combo to "(unsaved)", with a re-show;
  - in `set_scope()`, beside `_grid_refusal = None`.

  One addition, D2: `restore_cube`'s `except` path re-shows Warnings.
- **M1-1:** `_switch_resumed_grid` no longer drops the restore values or selects the default
  preset itself. `_sync_included()`'s non-by-hand grid-changed branch does both.
  - **Checked:** `_last_grid_id` still names the grid being left at that call. `_last_grid_id`
    is only written by `_sync_included` and `restore_cube`, and each also moves the combo.
    `_grid_to_resume` returns only a grid different from `grid_combo.currentText()`, so the
    branch is taken.
  - **Pinned by** the existing `test_this_grid_opens_an_unremembered_grid_on_the_preset_the_site_drew_it_with`
    (site scope). It goes from "raw" on A to B, which has no record. Without the branch the
    preset would stay "raw". It passes.
- **M1-2:** each declaration comment now says, in one line, that a site opening or closing drops
  it:
  - `_pending_top_ns` has its own `#:` comment (its group comment no longer lists it);
  - `_resolution_owed`'s comment also names #200.
- **Docstrings updated:**
  - `restore_cube`: a paragraph on the notes, the settle sequence and #200;
  - `_mark_cube_unsaved`, `_drop_restore_pending`, `_shift_z_by_median_zero`, `show_warnings`
    and `_switch_resumed_grid`.
- `_pending_z_shift` stays a bool, and `_shift_z_by_median_zero` keeps its name (for Task 3).

`packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`:

- **New helpers:**
  - `_notes(dock)`: the NOTE entries' texts, in order;
  - `_record_pushes`: wraps `engine.set_resolution` through monkeypatch and records each `t0_ns`;
  - `_assert_pushed_shifted`;
  - `_site_task_live`: patches `has_live_task` on the site engine's class with a property that
    reads `live[0]`;
  - `_deep_cube_saved_with_a_shown`, extracted from the existing deep-cube test, which now
    uses it;
  - `_two_grids_with(tmp_path, preset)`, which `docked_two_grids` now uses.
- **New fixture:** `docked_two_grids_zeroed`.
- **Step 1, re-pointed** at `_notes(dock)` (exactly once) and "not in `errors`":
  - `_assert_shifted_once`;
  - `_assert_a_clean_old_restore`;
  - `test_the_owed_shift_survives_a_switch_to_whole_site_before_the_preparation_lands` (its
    middle "no note yet" check now covers both errors and notes);
  - `test_restoring_a_cube_drops_a_line_now_on_another_grid_and_says_so`.

  `test_the_owed_shift_helper_steps_aside_while_a_preparation_runs` calls `_settle_and_push()`,
  with the same assertions.
- **Also re-pointed, beyond the brief's four.** They checked the note through `errors` and would
  otherwise become vacuous:
  - the last check of `test_an_old_recipe_keeps_its_shift_while_a_preparation_is_owed` (now
    `_notes(dock).count(note) == 1` and not in errors);
  - five "no note" checks (`not [m for m in errors if "first break" in m]`), now over
    `(*errors, *_notes(dock))`:
    - `test_removing_the_grid_while_its_restore_prepares_drops_the_restore`;
    - `test_the_owed_shift_helper_steps_aside_while_a_preparation_runs`;
    - `test_a_marked_record_is_not_shifted`;
    - `test_an_old_recipe_without_time_zero_restores_unchanged`;
    - `test_an_old_recipe_with_nothing_prepared_is_not_shifted`.
- **`_pending_z_shift` checks:** the tests I touched now check it by truthiness (`is True` /
  `is False` removed), ready for Task 3's `OwedShift | None`.
- **New tests:** the nine named in the brief (one parametrized twice), plus one more, D2:
  - `test_an_owed_shift_is_pushed_only_after_it_is_applied`
  - `test_an_owed_shift_waits_for_the_preparation_it_is_owed_to`
  - `test_a_restore_note_goes_when_the_cube_is_left[edit|scope]`
  - `test_a_restore_that_fails_past_its_checks_takes_the_last_notes_down` (D2)
  - `test_closing_the_site_while_a_restore_waits_for_a_site_task_is_quiet` (Review Focus 2)
  - `test_restoring_the_same_old_cube_twice_before_it_prepares_shifts_once` (Review Focus 3)
  - `test_a_restore_that_leaves_lines_out_and_shifts_shows_both_notes` (Review Focus 4)
  - `test_a_restore_that_waits_for_a_site_task_applies_its_resolution_to_its_own_grid` (#200)
  - `test_a_restore_owed_a_shift_clears_the_refusal_of_the_grid_left_at_once` (Ruling 36)

## Deviations, with reasons

- **D1: `restore_cube`'s "else: `flush_debounce()`" now runs only while a preparation is
  running.**
  - **The literal reading pushes twice.** A no-shift restore whose source the engine already
    holds is not running and not deferred. Read literally, it would `flush_debounce()` (push 1)
    and then `_settle_and_push()` (clamp, push 2).
  - **Why that matters:** `set_resolution` drops every plan and the cube (`_rebuild_geometry`),
    and `refresh_slice` runs twice. That is a real cost on a large grid, and a refused apply
    toasts twice.
  - **What I did instead:** in that case the debounce is stopped, and `_settle_and_push()` is the
    one push, clamped first, as spec §3 asks of "a restore that needs no preparation".
  - **Unchanged:** every other branch behaves as the brief says. Deferred: owed, stop, nothing.
    Shift owed: stop. Running with no shift: flush.
- **D2: `restore_cube`'s `except` path calls `show_warnings()`.**
  - **Why:** the brief resets `_grid_notes` at the start of a restore that passed its checks. If
    that restore then raised (in `apply_view`, say), `_grid_notes` was `[]` but the panel still
    showed the last cube's note, while the combo said "(unsaved)".
  - **Covered by** `test_a_restore_that_fails_past_its_checks_takes_the_last_notes_down`. It
    patches `apply_view` to raise. It fails without the line (`1 failed`) and passes with it.
  - A restore refused at its checks still keeps the notes, per the brief. The dock is left
    entirely as it was.
- **D3: "a note already present is not added again"** is the `_add_grid_note` helper, compared
  by text, as ruled.
- **D4: `_drop_restore_pending` calls `show_warnings()` only when it had notes.**
  - **Why it re-shows at all:** otherwise a site close or `set_included` would leave a stale note
    on show.
  - **Why only then:** it never touches the panel otherwise. That matters most in Whole site,
    where `rebuild_source` calls it before the site has rebuilt.
- **`_run_pending_grid_prepare` keeps today's `engine.choice is not None` guard** around both
  branches. A closed survey (choice None) pushes nothing. Review Focus 2 relies on this.

## TDD evidence

### RED

Command, before any source change:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:xonsh -p no:cacheprovider -rA --tb=line -k "owed_shift or old_recipe or old_record or restore_note or closing_the_site_while or same_old_cube_twice or leaves_lines_out or waits_for_a_site_task or restore_owed_a_shift or drops_a_line_now or deep_cube or marked_record or failed_line_does_not_drop or removing_the_grid_while or edit_while_a_restore or clears_the_refusal"
20 failed, 9 passed, 202 deselected in 10.17s
```

How each failed, and why that was expected:

- **The re-pointed note checks:**
  - **Tests:** `_assert_shifted_once` and `_assert_a_clean_old_restore` (11 tests, the
    real-data one included), `test_restoring_a_cube_drops_a_line_now_on_another_grid_and_says_so`
    and `test_the_owed_shift_survives_…`.
  - **Failure:** `AssertionError: []`, at `_notes(dock).count(note) == 1`. The note was a toast,
    so Warnings had none.
- **`test_the_owed_shift_helper_steps_aside_while_a_preparation_runs`:** `AttributeError:
  'SlicesDock' object has no attribute '_settle_and_push'`.
- **`test_an_owed_shift_is_pushed_only_after_it_is_applied`:** `AssertionError: [5.0, 7.425]`.
  - **The bug (#162 item 3):** `_run_pending_grid_prepare` pushed the radar-clock t0 (5.0)
    before the shifted one. The median zero is −2.425 ns.
- **`test_an_owed_shift_waits_for_the_preparation_it_is_owed_to`:** `AssertionError:
  [5.0, 7.425]`.
  - **The bug, while running:** the unshifted range was pushed while the preparation ran, and
    `_on_prepared` shifted it afterwards.
- **`test_a_restore_note_goes_when_the_cube_is_left[edit]` and `[scope]`:**
  `assert [] == ['This cube w...by +2.42 ns.']`, at the precondition. No note was ever in
  Warnings.
- **`test_restoring_the_same_old_cube_twice_before_it_prepares_shifts_once`:**
  `AssertionError: []` from `_assert_shifted_once`'s note check.
  - **The shift itself:** once, and correct before the fix. The docstring says it is a guard on
    the shift, and that only the note's place is new.
- **`test_a_restore_that_leaves_lines_out_and_shifts_shows_both_notes`:** `AssertionError: []`
  (no notes in Warnings).
- **`test_a_restore_that_waits_for_a_site_task_applies_its_resolution_to_its_own_grid`:**
  ```
  assert (Entry(kind='refusal', text='Too many levels: dz 0.0541 ns from 0 to 89.9683 ns makes
  1,664 levels; this cube allows 1,024 (twice the 512 samples in each line). Narrow z0–z1 or
  raise dz.'),) == ()
  ```
  That is the #200 bug exactly: the deferred restore flushed B's deep cube against A's level
  limit.
- **Passed before the fix (investigated):**
  - **`test_closing_the_site_while_a_restore_waits_for_a_site_task_is_quiet`.** It is a guard,
    and its docstring says so. Why it holds before:
    - A closed survey offers no source, so the retry's `prepare()` calls `set_source(None)`,
      which returns quietly.
    - `engine.choice` is None, so nothing is pushed.
    - Task 1's new-site drop already clears `_resolution_owed`.

    It guards the new deferral (`_resolution_owed = True`) against outliving the survey.
  - **`test_a_restore_owed_a_shift_clears_the_refusal_of_the_grid_left_at_once`.** A guard by
    design (Ruling 36), and its docstring says so. Its sharpness is shown by mutation below.
  - **The other seven** are existing tests whose "no note" checks hold before and after.

### GREEN

The same command after the implementation:

```
29 passed, 202 deselected in 10.87s
```

The added test, D2: `1 failed` without the `except`-path `show_warnings()`, `1 passed` with it.

## Ruling 36 mutation evidence

The mutant deleted `self._grid_refusal = None` (the line under "A refusal belonged to the grid
that was showing.") from `restore_cube`. The file was backed up first and restored afterwards;
`cmp` against the backup was identical, and nothing mutated was committed.

```
-k "restore_owed_a_shift_clears_the_refusal or restore_onto_another_grid_clears_the_refusal"
E  Left contains one more item: Entry(kind='refusal', text='Too many levels: dz 0.2165 ns from 0
   to 100,000 ns makes 461,894 levels; this cube allows 1,024 (twice the 512 samples in each
   line). Narrow z0–z1 or raise dz.')
FAILED test_a_restore_owed_a_shift_clears_the_refusal_of_the_grid_left_at_once
1 failed, 1 passed
```

- **The new test fails:** a restore that owes a shift pushes nothing until its preparation
  lands, so only that line takes A's refusal down.
- **The existing `test_a_restore_onto_another_grid_clears_the_refusal_of_the_one_left` passes**
  with the line deleted. It waits for the preparation, and that preparation's apply clears the
  refusal.

## Whole files, pure tier, lint (final code)

```
test_plugin_slices_dock.py (-W default):  232 passed in 78.31s
test_plugin_site_scope.py (-W default):   173 passed in 422.86s
pure + core tier:                          1682 passed, 5 skipped in 258.02s
ruff check . && ruff format --check .:     All checks passed! / 233 files already formatted
```

The output was pristine: no warning lines in either QGIS file run.

The pure tier ran before the last two edits, the `except` line in `restore_cube` and a test
comment. That tier never imports `slices_dock.py`, so the result stands.

## Self-review

- **Brief coverage:** every Interface, Step 1 item, Step 2 test and Step 4 bullet is in place,
  plus M1-1 and M1-2. Deviations D1 to D4 are above.
- **Slot guards:** no new Qt slot or override.
  - `show_warnings` already guards itself.
  - `_settle_z` and `_settle_and_push` run inside guarded callers: `_on_prepared`,
    `_run_pending_grid_prepare`, and `restore_cube`'s `try`.
  - `_mark_cube_unsaved`'s new lines are inside its existing `try`.
  - `_drop_restore_pending` calls `show_warnings` (guarded), and its callers are guarded too.
- **`_updating`:** no new widget writes. The z writes are the existing ones in
  `_shift_z_by_median_zero` and `_clamp_z_to_prepared`, both raised and signal-blocked.
- **YAGNI:** `_add_grid_note` exists because two call sites share the dedupe-and-show rule.
  There is no scope check in `_settle_z`: every caller is This-grid only (`_on_prepared` and
  `_run_pending_grid_prepare` return in site scope, and a restore in site scope always defers).
- **Tests verify behaviour:**
  - The push recorder reads `set_resolution` calls, not internals.
  - The notes are read from `warnings_panel.entries()`, which is what the user sees.
  - Private flags (`_resolution_owed`, `_pending_z_shift`, `_grid_prepare_pending`) are checked
    only where the brief asks.

## Concerns and observations

1. **`test_an_owed_shift_waits_for_the_preparation_it_is_owed_to` does not dispatch where the
   brief says.** The brief expects `_run_pending_grid_prepare` to dispatch. With the engine
   cleared and no site task live, the restore's own `prepare()` dispatches first.
   - `_run_pending_grid_prepare` then finds that preparation running. Its `prepare()` is a no-op
     for the same source.
   - So the test exercises the "a preparation is now running" branch, as intended, and fails
     before the fix (`[5.0, 7.425]`).
   - I followed the brief's steps literally, and the docstring says which call dispatches.
   - Holding the restore's preparation back for real would need `has_live_task` patched during
     the restore. The #200 test already covers that path, without a shift.
2. **A deferred restore still drops its palette (existing behaviour, not changed here).**
   `restore_cube` clears `_pending_palette` whenever the engine is not running, and a deferral
   leaves it not running. A cube restored behind a live site task comes back on the computed
   default palette, not its own. The deferral is R-P5's, hard to hit by hand. Not in this
   task's brief. It could be filed or folded into Task 3/4 if wanted.
3. **D1 changes the brief's literal branch** for the no-shift, no-preparation restore; see above.
   I can switch to the literal form (a double push) if the coordinator prefers it. I did not run
   the suite on that form.

---

## Fix round 1 (commit 482b1db): a waiting restore keeps its palette (the coordinator's ruling on concern 4)

**Rulings received:**
- **Accepted:** D1 (one settle, not flush + settle); the `except`-path `show_warnings()`; the six
  re-pointed note checks; concerns 3 and 5 as reported.
- **To fix in this task:** concern 4, a restore that waits for a site task dropping its palette.

### What changed

`slices_dock.py`:

- **`restore_cube`:** `_pending_palette` is cleared only when the restore did not defer:
  `if not self.engine.is_running and not deferred:` clears the palette, then
  `_settle_and_push()`. A waiting restore keeps the palette for the `_on_prepared` of the
  preparation it is owed. The no-op-prepare clear is unchanged.
- **`_run_pending_grid_prepare`:** after `prepare()`, if no preparation is running,
  `_pending_palette = None`.
  - **Why it is needed:** without it the fix would bring back the fix-round-1 staleness on
    another path. The restore waits for a source the engine already holds, so the owed
    preparation is a no-op and no `_on_prepared` follows. The palette `apply_view` set stands,
    but the pending value would then wait for some later, unrelated preparation to apply it.
  - With a palette pending, this is the only place that clears it.
  - Otherwise `_pending_palette` is already None here, so the line changes nothing.
- **`_pending_palette`'s declaration comment** now names both rules.

`test_plugin_slices_dock.py`:

- `_deep_cube_saved_with_a_shown(..., palette=...)`: with `palette=None` it saves with an offered
  palette that is not B's default (`_another_palette`, read while B is on show). B's source is
  unipolar, so the existing default (`amp_black_high`) is B's own default. A first attempt with
  a bipolar palette (`seismic`) failed for the wrong reason, as not offered, and was replaced
  before any source change.
- New tests:
  - `test_a_restore_that_waits_for_a_site_task_keeps_its_palette`, on `docked_mixed_radar`, as
    the coordinator specified.
  - `test_a_waiting_restore_whose_source_is_prepared_leaves_no_palette_pending`, on `docked`.
    It covers the `_run_pending_grid_prepare` half: no palette is held for an owed preparation
    that turns out a no-op.

### RED (before the source change)

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:xonsh -p no:cacheprovider --tb=short -k "waits_for_a_site_task_keeps_its_palette or waiting_restore_whose_source_is_prepared or waits_for_a_site_task_applies or deep_cube"
E   AssertionError: assert 'amp_black_high' == 'amp_white_high'
E   AssertionError: held for the owed preparation
E   assert None == 'amp_white_high'
FAILED ...::test_a_restore_that_waits_for_a_site_task_keeps_its_palette
FAILED ...::test_a_waiting_restore_whose_source_is_prepared_leaves_no_palette_pending
2 failed, 2 passed, 230 deselected in 2.60s
```

- **Test 1:** B was drawn on its default palette, not the cube's. This is the bug.
- **Test 2:** the waiting restore had already dropped the palette it should hold.

### GREEN

The same command, with `or palette` added to `-k`:

```
7 passed, 227 deselected in 2.79s
```

### Each half is needed

`restore_cube`'s change alone, with the `_run_pending_grid_prepare` lines removed (the file was
backed up and restored, and `cmp` was identical):

```
E   AssertionError: assert 'amp_white_high' is None
1 failed, 1 passed
```

Test 2 catches the stale palette; test 1 still passes.

### Whole files, pure tier, lint (after this fix)

```
test_plugin_slices_dock.py (-W default):  234 passed in 78.69s
test_plugin_site_scope.py (-W default):   173 passed in 431.70s
nsgeo-qgis pure tier:                      305 passed, 1 skipped in 20.55s
pure + core tier:                          1682 passed, 5 skipped in 219.74s
ruff check . && ruff format --check .:     All checks passed! / 233 files already formatted
```

There were no warning lines in the QGIS runs.

---

## Fix round 2 (commit 1584a6b): review I2-1 (Important) and M2-1 (plan-mandated, ruled fix now)

### What changed

`slices_dock.py`:

- **I2-1, `_mark_cube_unsaved`:** it clears and re-shows `_grid_notes` whenever any are present,
  whatever the combo reads. The combo still moves to "(unsaved)" only when it named a cube.
  - **This closes route (b)** (the coordinator's ruling). An edit inside the preparation window,
    or during a #200 wait, marks the cube unsaved before its shift lands. The shift then moves the
    edited spins, and its note may appear. The next edit takes it down.
- **I2-1, route (a), the choice:** the refused restore's `except` path clears the previous cube's
  notes outright (`_grid_notes = []`, then `show_warnings()`). The combo leaves the cube it named
  just below, so that cube's notes go with it.
  - **I chose this** over "the next edit clears it": the note goes at once, and one path covers a
    restore refused at its checks and one that fails past them.
  - The round-1 `except` line (re-show only) is replaced by this.
- **M2-1, `_settle_and_push`:** it returns early when `self._pending_z_shift and
  self.engine.is_running`. The range is still on the radar's clock, and that preparation's
  `_on_prepared` shifts, clamps and pushes it.
- **Comments:** `_grid_notes`' declaration and `_mark_cube_unsaved`'s docstring now say this.

`test_plugin_slices_dock.py`:

- **M2-1:** `test_the_owed_shift_helper_steps_aside_while_a_preparation_runs` now takes
  `monkeypatch`.
  - **The push recorder** starts before the restore.
  - **Right after `_settle_and_push()`** it asserts `pushed == []`.
  - **After the preparation lands**, it also runs `_assert_pushed_shifted`: every push is the
    shifted t0, and none is 5.0.
- **I2-1, route (b):** `test_an_edit_while_a_restore_prepares_leaves_no_note_past_the_next_edit`.
  - **Steps:** pick `A__old` through the combo with the engine cleared; `z1_spin.stepDown()`
    before the wait; wait; step again; `_notes(dock) == []`.
  - **After the wait** it asserts the late note is present. This is a precondition, so the test
    cannot pass without reaching the hazard. The ruling allows the note there. If a later change
    stops the note appearing, this precondition fails and the test needs a look.
- **I2-1, route (a):** `test_a_restore_refused_at_its_checks_takes_the_last_notes_down`.
  - **Steps:** pick `A__old` (note shown), then pick `A__gone`, whose preset no longer exists.
  - **Asserts:** the combo reads "(unsaved)" and `_notes(dock) == []`.
- **`test_an_old_recipe_keeps_its_shift_while_a_preparation_is_owed`, last check, re-pointed.**
  - **Before:** `_notes(dock).count(note) == 1` after a user edit of z0/z1.
  - **Now:** `_notes(dock) == []`, since the edit takes the note down.
  - **Stronger, not weaker:** a second shift in the later `_on_prepared` would add the note
    back, and the old dedupe-count could not see that.

### RED (before the source change)

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:xonsh -p no:cacheprovider --tb=short -rA -k "helper_steps_aside or keeps_its_shift_while_a_preparation_is_owed or leaves_no_note_past_the_next_edit or refused_at_its_checks_takes or fails_past_its_checks"
E   AssertionError: pushed while the shift was still owed
E   assert [5.0] == []
E   assert ['This cube w...by +2.42 ns.'] == []      (x3)
PASSED  ...::test_a_restore_that_fails_past_its_checks_takes_the_last_notes_down
FAILED  ...::test_the_owed_shift_helper_steps_aside_while_a_preparation_runs
FAILED  ...::test_an_old_recipe_keeps_its_shift_while_a_preparation_is_owed
FAILED  ...::test_an_edit_while_a_restore_prepares_leaves_no_note_past_the_next_edit
FAILED  ...::test_a_restore_refused_at_its_checks_takes_the_last_notes_down
4 failed, 1 passed, 231 deselected in 3.09s
```

Each failed for its reason:
- **The helper:** pushed the radar-clock t0 5.0 while the shift was owed (M2-1).
- **The keeps-its-shift test and route (b):** the clock note outlived an edit made with the box
  already reading "(unsaved)".
- **Route (a):** the refused restore left the last cube's note up.
- **The round-1 test of a failure past the checks still passes.** The same `except` path now
  clears outright.

### GREEN

The same command, also covering the other note tests (`restore_note_goes`,
`leaves_lines_out`):

```
8 passed, 228 deselected in 3.32s
```

### Whole files, pure tier, lint (after round 2)

```
test_plugin_slices_dock.py (-W default):  236 passed in 81.09s
test_plugin_site_scope.py (-W default):   173 passed in 445.41s
pure + core tier:                          1682 passed, 5 skipped in 258.55s
ruff check . && ruff format --check .:     All checks passed! / 233 files already formatted
```

There were no warning lines in the QGIS runs.
