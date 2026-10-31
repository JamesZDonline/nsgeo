# Final fix wave: report (nsgeo-slices-cleanup)

Status: **DONE**. FIX_BASE 8291686. Commits:

- `1e09ca6` Slices: a z bound set after the empty-range fallback keeps the range shown (#71). This is Item 1.
- `8a3fd0c` Slices: final review fixes (#71, #54). This covers Items 2 to 6.

Both are pushed to `origin nsgeo-slices-cleanup`, and the tree is clean.

Every mutant below was applied by monkeypatch inside scratch probes in
`/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/ccf55f65-8cef-4c6e-a933-979a44fba24a/scratchpad/fixwave_mut/`.
They ran with `PYTHONDONTWRITEBYTECODE=1`, and nothing was edited in place. `git status` showed only the intended files before each commit.

## Item 1: a hand-set z bound lost after the empty-range fallback (Ruling 15)

**Change** (`slices_dock.py`). `_on_resolution_edited` now remembers `self._edited_fields(field, value, remembered)` in both branches. The site branch passes `session.site_resolution()` and the This grid branch passes `session.slice_resolution(grid_id)`.

The new `_edited_fields` method works like this for `t0_ns`/`t1_ns`. If the record holds the other end, and pairing it with the new value would give `t1 <= t0`, the other end's **shown** spin value is added to the same call. Every other field still writes `{field: value}` alone. Clamps, seeds and restores are unchanged and write nothing, because the slot still returns under `_updating`/`_seeding`.

Two docstrings now say that a remembered past-data end stands only until the user edits the other end against the range shown: `_clamp_z_to_prepared` and `SiteScope.seed_z`.

**Tests**

- `test_plugin_slices_dock.py::test_a_bound_set_after_the_empty_range_fallback_keeps_the_range_shown`. Steps:
  1. Set z0 by hand at 60% of the range.
  2. Select a preset whose time cutoff is at 40%, which forces the fallback.
  3. Set z1 by hand at 30%.
  4. Switch B → A and assert both shown bounds.
  5. Save, reopen in a new session and dock, and assert the record is `{t0_ns: shown z0, t1_ns: z1}`, the spins and the engine agree, a slice is drawn, and the survey is clean.
- `test_plugin_site_scope.py::test_a_bound_set_after_the_empty_range_fallback_keeps_the_range_shown_in_the_site`. Steps:
  1. Remember `t0_ns=200` (past the data) and open the survey, so the fallback shows the data's range.
  2. Set z1 = 60 by hand.
  3. Untick C, then re-tick it, and assert both shown bounds and the record.
  4. Save, close, and reopen in a new plugin. Assert the record, the spins, `res_applied.t1_ns`, a drawn site slice, and a clean survey.
- An added guard: `test_plugin_slices_dock.py::test_an_edit_after_a_clamp_that_left_the_range_usable_keeps_the_remembered_end`. When a remembered `t0 = low − 5` is clamped up and the user then sets z1, the record keeps `low − 5`. This pins the "only when empty" condition.

**RED** (before the fix):
- This grid: `assert (-11.086, 33.0863) == (-11.086, 22.108)`. After B → A, z1 snapped back to the data's end.
- Site: `assert (-2.424, 99.5614) == (-2.424, 60.0)`. After the re-tick, z1 snapped back.

**GREEN**: 2 passed. The guard test passes too.

**Mutants**:
- `never` (`_edited_fields` returns only `{field: value}`) fails both new tests.
- `always` (remembers the shown other end whenever it is in the record) fails the guard test.
- Unmutated, all three pass.

The reviewer's probes `test_p1`/`test_p5` match the new tests. Both failed at HEAD with the values above.

## Item 2: the inner restore in `_seed_dz_z_defaults` was untested

**Test**: `test_plugin_slices_dock.py::test_a_hand_resolution_on_an_empty_grid_survives_its_lines_arriving`. Steps:
1. Start a new survey, add grid A with no lines, and build the dock.
2. Set dz = 0.5 and z1 = 30 by hand. The record is then `{dz_ns: 0.5, t1_ns: 30.0}`.
3. Import three lines under A.

Assertions: z0 took the header seed, so the late seed ran. dz and z1 are still 0.5 and 30. After preparing and flushing, the engine has `dz_ns == 0.5` and `t_end_ns ≈ 30` (abs 0.5), a slice is drawn, and the record is unchanged.

There is no code change, so RED comes from a monkeypatch mutant: `_restore_remembered_resolution` is a no-op when its caller is `_seed_dz_z_defaults`, which is the reviewer's mutant.

- **RED** under the mutant: `assert (0.2165, 99.5615) == (0.5, 30.0)`.
- **GREEN** unmutated: passed.

## Item 3: the timing-dependent wait-window test

`test_a_grid_removed_inside_the_wait_window_clamps_the_fallback_grid` now waits for `spin_until(lambda: not dock.site_engine.has_live_task and not dock._resolution_owed, 30_000)` before `_assert_a_slice_is_drawn_on_a`. A comment explains why: the engine already holds A, so the helper's own wait passes at once.

**Mutant check**: `_clamp_z_to_prepared` was made a no-op when called from `_run_pending_grid_prepare`, which drops the owed clamp. The test now fails with `line 'raw/A/FILE__001.DZT' spans -2.425..99.561 ns, which does not cover the cube's -11.086..31.565 ns`. Unmutated, it passes.

## Item 4: an OverflowError blocked opening a survey (`nsgeo/project.py`)

**Change**: one new helper, `_finite(value) -> float | None`. It returns None for a non-number, a bool, NaN or ±inf, and catches `OverflowError`/`ValueError`/`TypeError` from `float()`. Both `_clean_resolution` and the gain cleaner in `_clean_slice_source` now use it. Core stays numpy-free.

**Tests** (`packages/nsgeo-core/tests/test_project.py`):
- A new case `{"cell": 10**400}` (id `huge-int-cell`) in `test_a_bad_remembered_resolution_value_reads_as_unset`.
- A new test, `test_an_integer_too_large_for_a_float_reads_as_unset_and_the_survey_opens`. It sets a gain of `10**400` on A, a cell of `10**400` next to a good dz on B, and a site `t1_ns` of `-(10**400)`. Each reads as unset, the good dz is kept, and the survey loads.

- **RED**: 2 failed with `OverflowError: int too large to convert to float`, at `project.py:234` (resolution) and `project.py:260` (gain).
- **GREEN**: `test_project.py` 61 passed.

## Item 5: `_filled_radius_cells` went stale

**Option chosen**: record it after a successful draw, in **both** the fill and coverage branches. I did not skip the `elif` while coverage is ticked.

`refresh_slice` reads `radius = self.radius_cells()` once, fills with it, and sets `self._filled_radius_cells = radius` just before `slice_changed.emit()`, at the end of the successful path. A failed draw leaves the last successful radius in place.

Unticking coverage redraws through `coverage_check.toggled` at the radius current then. A spacing edit while coverage shows still redraws once, which is harmless. The attribute's comment is updated to match.

**Test**: `test_plugin_slices_dock.py::test_a_coverage_view_is_not_redrawn_on_every_session_signal`. With coverage on, a cell edit to 0.05 plus a flush changes `radius_cells()`. Three `presets_changed` signals then emit no `slice_changed`.

- **RED**: `assert [None, None, None] == []`.
- **GREEN**: passed, and all 18 radius/coverage tests pass.

## Item 6: stale comments and docstrings

- `slices_dock.py`: the `_included_is_default` comment now lists every setter. A non-empty `set_included` clears it. A grid change sets it, and so does a prune that empties the choice (#74). The restore paths (`_restore_remembered_source`, `restore_cube`, `_follow_record_changed_in_site`) set it to whether what they restored means every line.
- `test_plugin_slice_layer.py`: the corrupt-file test's docstring now says the folder holds only the file the layer reads and the last good one `self.path` names, each with its sidecars.
- `docs/superpowers/plans/2026-10-30-nsgeo-slices-cleanup.md`: added the requested line as the first bullet under Task 5's Interfaces. Nothing else in the plan changed.

## Verification

| Check | Result |
|---|---|
| Dock files + slice layer (`test_plugin_slices_dock.py`, `test_plugin_site_scope.py`, `test_plugin_slice_layer.py`) | **207 passed** (the two dock files: 180 → 185) |
| core + pure | **823 passed, 3 skipped** (was 821/3; the skip count is still 3) |
| qgis full suite | **1243 passed** in 10:05 (baseline 1238 + 5 new) |
| lint (`ruff check .` + `ruff format --check .`) | All checks passed; 155 files already formatted |
| types (mypy, the pinned command) | Success: no issues found in 36 source files |

The two dock files alone also passed after Item 1, before its commit: 183 passed.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: Item 1 (`_on_resolution_edited`, new `_edited_fields`, `_clamp_z_to_prepared` docstring), Item 5 (`refresh_slice`, the `_filled_radius_cells` comment), Item 6 (the `_included_is_default` comment)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: the `seed_z` docstring (Ruling 15 note)
- `packages/nsgeo-core/src/nsgeo/project.py`: Item 4
- `packages/nsgeo-core/tests/test_project.py`: Item 4 tests
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`: Items 1, 2 and 5 tests
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`: Item 1 site test, Item 3 wait
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`: Item 6 docstring
- `docs/superpowers/plans/2026-10-30-nsgeo-slices-cleanup.md`: Item 6 line

## Concerns (none blocking)

1. **Ruling 15, taken literally.** If the user's new end is empty even against the shown other end, the record stores that reversed pair as shown. An example is setting z1 below the fallback's z0. This is the same outcome as any user-typed reversed pair today: a `Resolution` error on screen, and the pair dropped on reopen. It is not new.
2. **Three items had no RED against unchanged code, by their nature.** Item 2 and Item 3 have no code fix, and the Item 1 guard test pins a condition. Each was shown to catch its mutant instead, as recorded above.
3. **Two docstrings beyond the brief.** I touched `_clamp_z_to_prepared` and `SiteScope.seed_z`, because "the remembered values stand" is no longer unconditional after Ruling 15. The Item 6 list did not name them.
