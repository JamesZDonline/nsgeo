# Slices: the right clock and preset after a change — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A value the Slices panel keeps for later (a restore's depth shift, its palette, the
slice time carried back from Whole site, an owed resolution, the preset a grid opens on) never
outlives the site, grid or preset change it was made for. A restored cube comes back on the clock
it was saved on, or says in Warnings how it moved.

**Architecture:** Almost all in `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:
- pending values are dropped at known change points (a new site, a source change, a fallback grid);
- one settle sequence (shift → clamp → check → push) runs on every restore path;
- the owed shift carries its direction.

`slices_engine.py` gains one read, the median first break. `slices_plan.py` gains the note
wording. Task 4 is separate small fixes in `processing_dock.py`, `site_scope.py`, `slices_engine.py`
and the tests.

**Tech Stack:** Python, QGIS 3.44 / 4.2 (PyQt5 / PyQt6), pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-nsgeo-slices-clock-preset-design.md`. Read the
sections your task names before you start. Session A's spec,
`docs/superpowers/specs/2026-11-13-nsgeo-slices-wheel-notes-design.md` §3.3 and §6.1, defines the
level limit and the Warnings section this plan builds on.

## Global Constraints

- **Run everything from the worktree root**
  `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-slices-clock-preset`. It has
  its own `.venv` and `.venv-qgis`, and the real data linked under
  `packages/nsgeo-core/tests/data/local/`.
  - One QGIS file: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/<file> -q -p no:xonsh -p no:cacheprovider`
  - Pure and core: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q -p no:xonsh -p no:cacheprovider`
  - Lint, as CI runs it: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **Before you report a task done,** run its own test file(s) and these whole files:
  `test_plugin_slices_dock.py`, `test_plugin_site_scope.py`, and the pure tier. The full QGIS tier
  takes about 15 minutes. The coordinator runs it between tasks, so don't.
- **Each test that pins a bug must fail before its fix.** Run it, see it fail for the reason the
  test names, then fix. Say in your report how each failed. A guard test (one that holds today)
  says so in its docstring.
- **Every Qt slot and override guards its own body** (`try` / `except Exception` / `_log`), as the
  file does throughout.
- **Warnings (session A, spec §6.1):** a message in the Warnings section has no toast as well. The
  panel orders ⛔ ⚠ ⓘ itself (`WarningsPanel.set_entries`).
- **Leave alone:**
  - the Save cube… / Export row of `slices_dock.py` (M16's PR #190 changes it);
  - `param_form.py`;
  - `first_break_row`'s signature and its 0-for-no-signal return.
- **Real data:** read it through `tests.real_data` (`CAMPUS_LINES`, `GPS_LINES`) and skip cleanly
  when a list is empty (CI). Never read or write the author's own projects.
- **Commits:** one or more per task, message `fix(slices): …` / `test(slices): …` / `docs(guide): …`,
  ending with your own `Co-Authored-By` line. The coordinator pushes.

## Review Focus

Inputs the spec implies that no bug test below exercises. Each has its test in the owning task.
1. **A grid removed while a restore of its cube is still preparing.** The combo falls back to
   another grid, so the restored palette and shift must be dropped, not applied to that grid (Task 1).
2. **The site closed while a restore waits behind a live site task.** The retry runs on a closed
   survey and must stay quiet: no toast, no logged failure (Task 2).
3. **The same old cube picked twice before its preparation lands.** The shift is applied once, and
   there is one note (Task 2).
4. **A restore that both leaves out moved lines and shifts the clock.** Both notes show, and one
   edit clears both (Task 2).
5. **A preset that lost Time zero, on lines with no measurable first break.** There's nothing to
   shift by. The cube must not come back on the wrong clock without a word, so a note says the
   range was left as saved (Task 3).

---

### Task 1: One rule for pending values, and the fallback preset (#162 item 2, #163 item 4, #102, #152)

Spec §2 and §5. Suggested implementer tier: opus (lifetime state).

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`. Change `rebuild_source`,
  `_sync_included`, `_on_source_changed`, `set_included` and `_switch_resumed_grid`, and add
  `_drop_restore_pending`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Produces:
  - `SlicesDock._drop_restore_pending(self) -> None`: forgets what a restore still owes
    (`_pending_z_shift` set to its "nothing owed" value, `_pending_palette = None`). Tasks 2 and
    3 extend it.
  - `SlicesDock._sync_included(self, *, by_hand: bool = False) -> None`.
- **Test style for later tasks:** test `_pending_z_shift` by truthiness (`assert
  dock._pending_z_shift`, `assert not dock._pending_z_shift`). Task 3 changes its type from `bool`
  to `OwedShift | None`.

- [ ] **Step 1: Write the failing tests** (in `test_plugin_slices_dock.py` unless named otherwise)
  - `test_an_edit_while_a_restore_prepares_keeps_its_shift_and_note`, parametrized over
    `signal` in `("lines_changed", "grids_changed", "presets_changed")`, with `docked_zeroed`:
    1. `_prepared_with_owed_record(dock, session)` (engine cleared, so the restore dispatches);
    2. `dock.restore_cube("A__old")`, then `assert dock.engine.is_running`;
    3. `getattr(session, signal).emit()`;
    4. `wait_for_preparation`, then `_assert_shifted_once(dock, errors)`.
  - **Replace** `test_rebuilding_the_source_drops_an_owed_shift` with
    `test_rebuilding_the_source_keeps_what_a_restore_owes_on_the_same_site`: a real restore while
    preparing (as above, with a non-default palette in the record's view), then
    `dock.rebuild_source()`. Then `assert dock._pending_z_shift` and the palette is still pending.
  - `test_a_restored_palette_does_not_carry_into_the_next_survey` (`docked`):
    1. save a record whose `view.palette` is an offered palette other than the current default;
    2. `dock.engine.clear()`, then restore it and `assert dock.engine.is_running`;
    3. `session.save()`, then `session.close_site()`, then `assert dock._pending_palette is None`;
    4. open a second survey in `tmp_path / "second"` (the same grid, three synthetic lines and
       preset `p`), then `wait_for_preparation`;
    5. assert `dock.palette_combo.currentText()` is the default noted before step 1.
  - `test_a_grid_the_combo_falls_back_to_opens_on_the_preset_whole_site_draws_it_with`
    (`docked_two_grids`):
    1. pick `q` on A by hand;
    2. assert `session.slice_source("B")` is `None` or `{}`;
    3. `session.remove_grid("A", with_lines=True)`, then `wait_for_preparation`.

    Then:
    ```python
    assert dock.grid_combo.currentText() == "B"
    assert dock.preset_combo.currentText() == site_scope.default_preset(session, "B") == "p"
    assert dock.engine.choice.preset == "p"
    assert not session.slice_source("B")
    ```
  - `test_a_grid_picked_by_hand_still_carries_the_preset_over` (guard): A on `q`, pick B in the
    combo. B shows `q`, and `session.slice_source("B")["preset"] == "q"`.
  - `test_opening_a_survey_does_not_carry_a_same_named_preset_over`: the first survey shows `q`.
    The second has presets `p` and `q` and no record for its grid. It opens on `p`.
  - **Review Focus 1,** `test_removing_the_grid_while_its_restore_prepares_drops_the_restore`
    (`docked_two_grids`):
    1. save a record of A with a non-default palette;
    2. `dock.engine.clear()`, then restore it;
    3. while it is running, `session.remove_grid("A", with_lines=True)`, then
       `wait_for_preparation`.

    Then `dock._pending_palette is None`, `not dock._pending_z_shift`, and the palette is B's
    default.
  - In `test_plugin_site_scope.py`,
    `test_a_survey_opened_after_closing_one_in_whole_site_starts_at_its_first_slice(plugin, site3_factory)`:
    1. `whole_site(plugin)`, then move the slider to about 60% of its range and `_events()`;
    2. `plugin.session.save()`, then `plugin.session.close_site()` and `_events()`;
    3. assert `dock.scope() == "grid"`, `dock._pending_top_ns is None` and
       `not dock._resolution_owed`;
    4. `plugin.session.open_site(site3_factory().json_path)`, then `wait_for_preparation` and
       `_events()`;
    5. `assert dock.slice_slider.value() == 0`.

- [ ] **Step 2: Run them; every bug test fails, and both guard tests pass**

- [ ] **Step 3: Implement**
  - `_drop_restore_pending()`. Use it in place of the paired `_pending_palette = None` /
    `_pending_z_shift = False` lines in `_on_source_changed`, `set_included` and
    `_switch_resumed_grid`.
  - `rebuild_source`:
    - drop the unconditional clear at its top;
    - before anything else, `new_site = self.session.site is not self._site_seen`; if it is new,
      call `_drop_restore_pending()` first;
    - in the existing branch beside `self._site.forget()`, also set `_pending_top_ns = None` and
      `_resolution_owed = False`. The closing survey's switch back to This grid (`set_scope("grid")`
      → `_resume_grid`) set them in this same call.
  - `_sync_included(by_hand=False)`. In the grid-changed branch, when not `by_hand`:
    `_drop_restore_pending()`, then select `site_scope.default_preset(self.session, grid_id)` inside
    the `_updating` guard (skip it when that is `None` or not offered). Then go on as today.
    `_on_source_changed` passes `by_hand=True`.
  - The docstrings of `_pending_palette` and `_pending_z_shift` say when they are dropped: a new
    site, a source change (by hand, from the site list, or a fallback grid), or their own
    `_on_prepared`. Never a refresh that keeps the source.

- [ ] **Step 4: Run the task's tests, both whole files and the pure tier; all pass**

- [ ] **Step 5: Commit**

---

### Task 2: One settle sequence, #200, and restore notes in Warnings (#162 item 3, #200)

Spec §3 and §8. Suggested implementer tier: opus.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`. Change `_on_prepared`,
  `_apply_owed_z_shift` (replaced), `_run_pending_grid_prepare`, `restore_cube`,
  `_shift_z_by_median_zero`, `show_warnings`, `_mark_cube_unsaved`, `set_scope` and
  `_drop_restore_pending`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`

**Interfaces:**
- Consumes: `_drop_restore_pending()` (Task 1).
- Produces:
  - `SlicesDock._settle_z(self) -> bool`. If This grid owes a shift and no preparation is running,
    it consumes the shift and applies it. Then it clamps (`_clamp_z_to_prepared`). It returns
    whether a shift was owed or the clamp moved a spin, which means the caller must push.
  - `SlicesDock._settle_and_push(self) -> None`: `_settle_z()`, then `_apply_resolution()`. It
    replaces `_apply_owed_z_shift`.
  - `SlicesDock._grid_notes: list[str]`, the restore's ⓘ notes. `show_warnings()` in This grid
    gives `[Entry(REFUSAL, refusal)]` (when there is one) plus `[Entry(NOTE, n) for n in
    _grid_notes]`.
  - A test helper, `_notes(dock) -> list[str]`: the NOTE entries' texts, in order.

- [ ] **Step 1: Point the existing note assertions at Warnings.** `_assert_shifted_once`,
  `_assert_a_clean_old_restore`,
  `test_the_owed_shift_survives_a_switch_to_whole_site_before_the_preparation_lands` and
  `test_restoring_a_cube_drops_a_line_now_on_another_grid_and_says_so` assert the note through
  `_notes(dock)` (exactly once), and assert it is **not** among `errors`. Those four now fail.
  `test_the_owed_shift_helper_steps_aside_while_a_preparation_runs` calls `_settle_and_push()` in
  place of `_apply_owed_z_shift()`, with the same assertions.

- [ ] **Step 2: Write the failing tests**
  - **The push recorder.** `test_an_owed_shift_is_pushed_only_after_it_is_applied` (`docked_zeroed`,
    `monkeypatch`):
    1. `_prepared_with_owed_record(dock, session, clear=False)`;
    2. set `dock._grid_prepare_pending = True` and `dock._resolution_owed = True`;
    3. wrap `dock.engine.set_resolution` to record each `resolution.t0_ns`;
    4. restore, then `dock._run_pending_grid_prepare()`.

    With `median = dock.engine.median_zero()`: `dock.engine.z.t0_ns ≈ 5.0 - median` (abs 1e-3);
    at least one push; every recorded t0 ≈ `5.0 - median`; none ≈ 5.0.
  - `test_an_owed_shift_waits_for_the_preparation_it_is_owed_to`: the same, but with the engine
    cleared (`clear=True`), so `_run_pending_grid_prepare` dispatches. `wait_for_preparation`,
    then the same assertions.
  - **#200,** `test_a_restore_that_waits_for_a_site_task_applies_its_resolution_to_its_own_grid`
    (`docked_mixed_radar`, `monkeypatch`):
    1. save `B__deep` as `test_restoring_a_deep_cube_onto_a_shallower_grid_draws_the_cube_unrefused`
       does, then show A;
    2. patch `type(dock.site_engine).has_live_task` to a property that reads a `live` flag, and set
       it `True`;
    3. `dock.restore_cube("B__deep")`.

    Immediately: `dock.warnings_panel.entries() == ()`, `dock._resolution_owed`, and
    `dock.engine.choice.grid_id == "A"`. Then set the flag `False`, `dock._run_pending_grid_prepare()`,
    `wait_for_preparation` and `processEvents`. Then: B is shown, `z.nz == deep.nz`, `z.dz_ns ≈
    deep.dz_ns`, Warnings empty, `errors == []`.
  - **Parked Ruling 36,** `test_a_restore_owed_a_shift_clears_the_refusal_of_the_grid_left_at_once`:
    1. put a level-limit refusal on grid A (`z1` of 100,000 ns, flushed);
    2. give grid B's lines a preset that sets Time zero;
    3. restore an unmarked record of B (see `_owed_record`).

    Warnings is empty as soon as `restore_cube` returns, before any `wait_for_preparation`. In your
    report, show that this test fails with `restore_cube`'s `self._grid_refusal = None` line
    deleted. (The existing test it sharpens does not.)
  - `test_a_restore_note_goes_when_the_cube_is_left`, parametrized over two ways of leaving: an
    edit (`z1_spin` down one step) and a scope round trip (`set_scope("site")`, then back to
    "grid"). After a shifted restore, `_notes(dock)` has the note. After leaving, it's `[]`.
  - **Review Focus 2,**
    `test_closing_the_site_while_a_restore_waits_for_a_site_task_is_quiet` (`docked_zeroed`,
    `message_log`):
    1. patch `has_live_task` as in the #200 test, set `live` to `True`, and restore `A__old`,
       which defers;
    2. `session.save()`, then `session.close_site()`;
    3. set `live` `False`, then `dock._run_pending_grid_prepare()`.

    Then `errors == []`, `not dock._resolution_owed`, and there's no `could not` in `message_log`.
  - **Review Focus 3,** `test_restoring_the_same_old_cube_twice_before_it_prepares_shifts_once`
    (`docked_zeroed`): with the engine cleared, call `restore_cube("A__old")` twice, then
    `wait_for_preparation`. Then `_assert_shifted_once(dock, errors)`.
  - **Review Focus 4,** `test_a_restore_that_leaves_lines_out_and_shifts_shows_both_notes`: two
    grids whose preset sets Time zero (a variant of `docked_two_grids`), an unmarked record of A,
    and one of its lines moved to B since. Both notes are in `_notes(dock)`, and a `z1` edit clears
    both.

- [ ] **Step 3: Run them; each fails for the reason it names**

- [ ] **Step 4: Implement**
  - `_settle_z()` and `_settle_and_push()`, as in Interfaces. `_on_prepared` replaces its own
    shift-and-clamp lines with `settled = self._settle_z()`, at the same point. It keeps its push
    at the end (`_apply_resolution()` if settled, else `refresh_slice()`).
  - `_run_pending_grid_prepare`, after `prepare()`:
    - **if a preparation is now running:** push now only when no shift is owed and the
      resolution was owed or `engine.z is None` (today's behaviour). The preparation's
      `_on_prepared` settles a shift.
    - **otherwise:** when the resolution was owed, `engine.z is None` or a shift is owed, call
      `_settle_and_push()`.
    - then `_sync_grid_slider()`, as today.
  - `restore_cube`, after `prepare()`:
    - **if it deferred** (`self._grid_prepare_pending` is set): set `_resolution_owed = True`, stop
      the debounce, and settle nothing now;
    - **elif a shift is owed:** stop the debounce;
    - **else:** `flush_debounce()`.

    In the `not self.engine.is_running` block, call `_settle_and_push()` only when it did not
    defer.
  - **Notes.** `_shift_z_by_median_zero` appends its note to `_grid_notes` (no `error.emit`).
    `restore_cube`'s "moved to another grid since it was saved" note does too. Both call
    `show_warnings()`, and a note already present is not added again. `_grid_notes` is reset to `[]`:
    - at the start of a restore that passed its checks;
    - in `_drop_restore_pending()`;
    - in `_mark_cube_unsaved()` when it moves the combo to "(unsaved)";
    - in `set_scope()`.

- [ ] **Step 5: Run the task's tests, both whole files and the pure tier; all pass**

- [ ] **Step 6: Commit**

---

### Task 3: A preset whose clock changed since the save (#162 item 1)

Spec §4. Suggested implementer tier: opus.

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: `restore_cube`; `_shift_z_by_median_zero`,
    renamed `_shift_z_to_clock`; `_settle_z`; `_drop_restore_pending`; the new `OwedShift`.
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`: `median_first_break`.
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`: `clock_change_note`, `no_break_note`.
  - `docs/guide/getting-started.md`: the paragraph on cubes saved before 0.4.0.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`;
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`;
  - `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`.

**Interfaces:**
- Consumes: `_settle_z`, `_grid_notes` (Task 2); `_drop_restore_pending` (Task 1).
- Produces:
  - In `slices_dock.py`:
    ```python
    @dataclass(frozen=True)
    class OwedShift:
        """A restored record's range, still on the clock it was saved on (#162)."""

        to: str  # the clock it moves onto: TIME_BASE_TIME_ZERO or TIME_BASE_RADAR
        cube_id: str
        preset: str
        marked: bool  # False: a record from before #97, with no time_base
    ```
    `_pending_z_shift: OwedShift | None`. `_drop_restore_pending()` sets it to `None`.
  - `SliceEngine.median_first_break(self, threshold: float = 0.2) -> float | None`. It is the
    median, over the prepared lines, of each line's radar-clock first break. That is
    `first_break_ns` on a `Radargram(data=line.data, dt_ns=line.dt_ns, t0_ns=line.t0_ns)`. It skips
    a line with no signal (`_first_break_or_none` is `None`), and returns `None` when nothing is
    prepared or no line has a break.
  - In `slices_plan.py`:
    - `clock_change_note(cube_id: str, preset: str, to: str, shift_ns: float) -> str`, for a marked
      record, in the spec §4 wording;
    - `no_break_note(cube_id: str, preset: str) -> str`: the range was left as saved, because no
      first break was found. `old_cube_note` stays for unmarked records.

- [ ] **Step 1: Write the failing tests**
  - Pure:
    - `test_clock_change_note_names_the_cube_the_preset_and_the_signed_shift`, for both values of
      `to`. The text contains the cube id, the preset and `f"{shift:+.2f} ns"`. "Time zero" appears
      as gained for `TIME_BASE_TIME_ZERO` and as lost for `TIME_BASE_RADAR`.
    - `test_no_break_note_names_the_cube_and_the_preset`.
  - Engine (`test_plugin_slices_engine.py`), `test_median_first_break_is_the_median_band_row`: banded
    synthetic lines (rows 40, 40, 41; see `_banded_dzt` in the dock tests) under a preset without
    Time zero. `median_first_break() == pytest.approx(t0 + 40 * dt)`, and it is `None` before any
    preparation.
  - Dock. Add a fixture `docked_banded_radar`: `_docked_with(tmp_path, PRESET, band_rows=(40, 40,
    41))`.
    - `test_a_radar_record_whose_preset_gained_time_zero_restores_moved_by_the_median_zero`
      (`docked_zeroed`): `_prepared_with_owed_record(dock, session, time_base="radar")`, then
      restore. The z range is moved by `-median_zero` (as `_assert_shifted_once`), and the note is
      `clock_change_note("A__old", "p", TIME_BASE_TIME_ZERO, -median)`.
    - `test_a_time_zero_record_whose_preset_lost_it_restores_moved_by_the_median_first_break`
      (`docked_banded_radar`):
      1. `fb = dock.engine.median_first_break()`, then `assert abs(fb) > dt`;
      2. make a `time_base="time_zero"` record whose z range stays inside the prepared bounds after
         adding `fb`, so the clamp moves nothing;
      3. restore.

      Then `z0 ≈ t0_saved + fb` and `engine.z.t0_ns ≈ t0_saved + fb` (abs 1e-3), and the note is
      `clock_change_note(…, TIME_BASE_RADAR, fb)`.
    - `test_a_marked_record_on_its_own_clock_is_not_moved` (guard): the existing
      `test_a_marked_record_is_not_shifted` and `test_an_old_recipe_without_time_zero_restores_unchanged`
      cover it. Keep them, and assert `_notes(dock) == []` in both.
    - **Review Focus 5,** `test_a_lost_time_zero_with_no_first_break_says_the_range_was_left`
      (`docked_banded_radar`, `monkeypatch` making `median_first_break` return `None`):
      - the range is unchanged;
      - `_notes(dock) == [no_break_note("A__old", "p")]`.
    - **Real data,** parametrized over `campus` (`CAMPUS_LINES[:4]`, a 12 m grid) and `gps`
      (`GPS_LINES[:4]`, a grid at least 31 m long). Each skips when its list is empty.
      - `test_a_real_data_old_record_restores_moved_by_the_median_zero`: built as
        `test_a_real_data_old_record_restores_without_a_coverage_error` is. The engine's range moved
        by `-median_zero`, and `abs(median_zero)` lies in 0.3–0.7 ns (campus) or 1.2–1.7 ns (gps). If
        the measured value falls outside, stop and report rather than widen the band.
      - `test_the_first_break_estimate_matches_time_zero_on_real_lines`: prepare the same four lines
        under `[dewow]`, then read `median_first_break()`. Prepare them under `[time_zero, dewow]`,
        then read `median_zero()`. They agree within one sample (`dt`).
  - Update every existing test that sets or reads `_pending_z_shift` as `True` or `False`.

- [ ] **Step 2: Run them; the gained, lost, no-break and note tests fail**

- [ ] **Step 3: Implement**
  - `restore_cube`:
    - `saved = recipe.time_base or TIME_BASE_RADAR` and `now = time_base_of(<preset's live
      steps>)`;
    - `_pending_z_shift = OwedShift(now, cube_id, recipe.choice.preset, recipe.time_base is not
      None)` when they differ, else `None`.
  - `_shift_z_to_clock(owed) -> bool` (it replaces `_shift_z_by_median_zero`):
    - **to time zero:** `median_zero()`, `retime_ns(t, 0.0, m)`, shift `-m`;
    - **to radar:** `median_first_break()`, `retime_ns(t, m, 0.0)`, shift `+m`.

    With prepared lines but no value, it adds `no_break_note` and returns `False`. With nothing
    prepared, it does nothing and says nothing, as today. Otherwise it remembers the shifted range,
    as today, and adds the note: `old_cube_note(shift)` when `not owed.marked`, else
    `clock_change_note(...)`.
  - The guide gains one sentence after the 0.4.0 cube paragraph: a cube whose preset has gained or
    lost Time zero since it was saved comes back the same way, and the Slices panel's Warnings says
    by how much.

- [ ] **Step 4: Run the task's tests, both whole files, `test_plugin_slices_engine.py` and the
  pure tier; all pass.** The real-data tests run here (the data is linked). Report the two medians
  and the two estimate gaps you measured.

- [ ] **Step 5: Commit**

---

### Task 4: #163 items 3 and 6: a time field before the samples load, and the test gaps

Spec §6. Suggested implementer tier: sonnet.

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`: `input_axis`, `time_axis`,
    `_show_form`, the new `_on_line_loaded`;
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: only the comment that says ProcessingDock never
    reacts to `line_loaded`;
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: `grid_time_bases`, and the
    `SiteScope.warnings` docstring;
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`: `prepared_steps`.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`;
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_fit.py`;
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`.

**Interfaces:**
- Produces:
  - `ProcessingDock.input_axis(self, row: int) -> tuple[float, float, int] | None`. It returns
    `None` when the stack has no source and an enabled `time_zero` entry sits above `row`.
    Otherwise it is unchanged.
  - `ProcessingDock.time_axis(self) -> tuple[float, float, int]`. When `input_axis` is `None`, it
    returns `(0.0, header.dt_ns, header.n_samples)`: on the time-zero clock the record starts at 0
    and has at most that many samples, so a cutoff seeded at its end is a no-op.
  - `SliceEngine.prepared_steps -> tuple[dict[str, Any], ...]`, a property returning `self._steps`.
  - `site_scope.grid_time_bases(session, source, site_engine)`, with `site_engine` now required.

- [ ] **Step 1: Write the failing tests**
  - `test_a_time_field_behind_time_zero_is_unbounded_until_the_samples_load`: a session whose
    line is opened before `set_profiles` (so `stack.source is None`), with a `time_zero` step and
    then a `time_cutoff` step.
    1. Select the cutoff row. The `end_ns` editor's range is not the header's radar-clock range.
       `param_form`'s unbounded case is what a missing `time_range` gives; see
       `test_a_cutoff_without_a_range_is_effectively_unbounded`.
    2. `session.set_profiles(key, line.load())`. The editor's minimum and maximum are now
       `zeroed.t0_ns + zeroed.dt_ns` and `zeroed.t0_ns + zeroed.n_samples * zeroed.dt_ns`, with
       `zeroed = stack.intermediate(0)`.
  - `test_a_cutoff_added_behind_time_zero_before_the_samples_load_crops_nothing`: the same
    unloaded line with a `time_zero` step. `dock.add_step("time_cutoff")`, then load the profiles.
    `stack.result().n_samples == stack.intermediate(0).n_samples`.
  - `test_a_saved_curve_is_drawn_on_the_shown_clock` (`test_plugin_velocity_fit.py`): a line with a
    `time_zero` step and a saved fit.
    1. `before = dock.velocity_curve_points(fit, distance, zero=z)`.
    2. Monkeypatch `dock.shown_zero_ns` to `lambda: z + 1.0`, then take `after` the same way.
    3. Every `after` time is the matching `before` time minus 1.0 (abs 1e-9).

    In your report, show that it fails with the `retime_ns` call removed from
    `velocity_curve_points`.
  - In `test_plugin_site_scope.py`:
    - rewrite `test_grid_time_bases_reads_each_grids_preset` to pass `dock.site_engine` before
      Whole site is entered: no grid has been prepared, so each is read from its preset;
    - add `test_a_grid_with_no_lines_has_no_clock`. A grid with no lines is left out of
      `grid_time_bases`, as a failed one is.

- [ ] **Step 2: Run them; the two processing tests fail, and the velocity test passes (it pins
  today's code)**

- [ ] **Step 3: Implement**
  - `input_axis` and `time_axis`, as in Interfaces. `_show_form` passes neither `time_range` nor
    `time_step` when `input_axis` is `None`.
  - `ProcessingDock` connects `session.line_loaded` to `_on_line_loaded(key)`, a guarded slot. For
    the line it shows, it re-shows the current row's form: reset `self._shown`, then `_show_form`.
    Update `plugin.py`'s comment that says ProcessingDock never reacts to `line_loaded`.
  - `prepared_steps`, used by `grid_time_bases` in place of `provenance().steps`. `grid_time_bases`
    loses its preset-only mode.
  - The `SiteScope.warnings` docstring says that queued and preparing grids are counted from their
    presets.

- [ ] **Step 4: Run the task's tests, `test_plugin_processing_dock.py`, `test_plugin_param_form.py`,
  `test_plugin_time_cutoff.py`, `test_plugin_site_scope.py` and the pure tier
  (`test_no_orphan_signals.py` included); all pass**

- [ ] **Step 5: Commit**

---

## After the tasks (the coordinator)

1. The full QGIS tier, the pure and core tiers, ruff, and green CI on the pushed head.
2. A whole-branch review (opus), then any fix wave.
3. Deploy to its own profile, `ns_geo_clock`, with a sandbox copy of the campus and GPS surveys in
   `~/nsgeo-clock-walk/`. Make the pre-#97 cube there by stripping `time_base` from a copied
   record and its npz.
4. **Human gate:** the walkthrough artifact (spec §10). Stop for the author's results. Merging asks
   first.
