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

