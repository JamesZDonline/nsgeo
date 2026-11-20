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

