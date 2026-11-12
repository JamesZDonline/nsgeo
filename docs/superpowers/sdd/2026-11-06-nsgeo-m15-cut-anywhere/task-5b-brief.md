# Task 5b — the time-zero hand-off, and the final review's residuals

M15 ("cut anywhere") is built (Tasks 1–6), with its final review and one fix wave done. Two things were left for this task:
- **Part A:** the time-zero (#97) items, deferred from Tasks 3 and 5 because #97 had not merged.
- **Part B:** the final review's residual findings.

#97 is now on main and was merged into this branch at `b2c1961`.

**Authorities:**
- The spec is `docs/superpowers/specs/2026-10-30-nsgeo-cut-anywhere-design.md`. Read call 18 (the clock) and §4.7 (minimum curvature on a cut, amended 2026-11-11 with the 0.5-spacing threshold).
- The plan is `docs/superpowers/plans/2026-11-06-nsgeo-m15-cut-anywhere.md`. Read call 13 and the Global Constraints.
- `constraints.md` sits next to this brief and holds the test and lint commands. Read it.

## The #97 names, confirmed on this branch

- `nsgeo.processing`:
  - `retime_ns(t, from_zero_ns, to_zero_ns)`;
  - `time_base_of(steps) -> str`, which gives `"time_zero"` or `"radar"`;
  - the constants `TIME_BASE_TIME_ZERO` and `TIME_BASE_RADAR`.
- `session.py`:
  - `Pick.zero_ns: float | None = None`;
  - `Pick.radar_ns`;
  - `SiteSession.line_zero(key, *, load=False) -> float | None`;
  - `add_pick(..., zero_ns=...)`.
- `layers.py`: `SiteLayers._on_stack_changed`, `_on_line_opened`, `_on_line_loaded`, `_follow_key(key, *, load)` and `follow_zero(key, zero_ns)`.
- `ui/profile_dock.py`:
  - `set_cube_zero_lookup`, `_cube_zero_lookup` and `_push_slice_band`;
  - `shown_zero_ns()`, which reads `_shown_radargram`.
- The plugin installs `slices_dock.line_zero_in_cube` as the cube-zero lookup.
- A cut pick's `Pick.stack_json` is the section's provenance JSON (`"kind": "cut"`).

## Part A — the clock on a cut (spec call 18, plan call 13)

A cut's times are all on its cube's clock. Nothing on a cut is ever converted by a line's zero.

A1. **Provenance.**
- `CutSections._provenance_json` gains `"time_base"`, set to `time_base_of(<the section's cube provenance>.steps)`.
- A cut pick's `stack_json` carries it with no other change.

A2. **Cut picks** are written with `Pick.zero_ns = None`, so the row's `zero_ns` is NULL. Their `time_ns` is the clicked time as given.

A3. **`SiteSession.line_zero(cut_key)`** returns `None` at once and logs nothing.

A4. **`SiteLayers._follow_key`** returns at once for a cut key, so `follow_zero` never runs on one.

A5. **The profile dock.**
- The dock does no #97 conversion while a cut shows. Its slice band, its pick overlay and its axes use a cut's times as they are.
- `_push_slice_band` draws the band unconverted on a cut. It does not consult `shown_zero_ns()` or the cube-zero lookup. Branch on the cut key; don't rely on the lookup happening to return None.
- `_shown_radargram` is cleared when a cut shows, so `shown_zero_ns()` is 0.0 on a cut. Today a cut shown after a line keeps the line's radargram.

A6. **A pick made on another clock.**
- On a cut, `_refresh_picks` leaves out, and counts, every pick whose provenance `time_base` differs from the shown section's.
- A provenance with no `time_base` reads as `"radar"`.
- The profile title then ends ` · {n} picks on another clock`, after the existing site suffix. Keep the title built in one place.
- The row is never changed. It stays on the map and in the table.

A7. **The guide** (`docs/guide/getting-started.md`, in the cut step or its §4 notes): add one short paragraph at the guide's width and in its voice. It says that turning the preset's time zero on or off after making cut picks leaves those picks out of the profile, and that the title counts them. They stay on the map and come back when the setting is turned back.

**Tests.** Put them in the files named, following each file's fixtures. Use `message_log` where logging is asserted.
- `test_plugin_session_cuts.py`: `test_line_zero_of_a_cut_is_none_and_logs_nothing`.
- `test_plugin_layers.py`: `test_opening_a_cut_runs_no_time_zero_follow`. A cut key with a pick row, opened as the working item, never calls `follow_zero` (use a spy) and logs nothing.
- `test_plugin_profile_cut.py`:
  - extend `test_the_slice_band_shows_on_a_cut` to its full form. On a cut whose preset sets a time zero, with a cube-zero lookup installed that returns a non-zero zero for any key, `window_changed(12.0, 14.0)` draws the band at exactly 12.0–14.0 ns. A line in the same state is still converted, as #97's tests expect;
  - `test_a_cut_on_a_time_zero_preset_starts_its_axis_at_the_cubes_t0`. With a preset holding an enabled `time_zero`, the view's `t0_ns` equals `section.z.t0_ns`, and `provenance_json`'s `time_base` is `"time_zero"`;
  - `test_a_cut_after_a_line_has_no_shown_zero`. Show a line whose stack sets a non-zero zero, then the cut: `shown_zero_ns()` is 0.0.
- `test_plugin_cut_picks.py`:
  - extend `test_a_pick_on_a_cut_lands_on_the_cut_and_records_its_provenance`. Its `time_base` names the cube's clock, and the row's `zero_ns` is NULL;
  - extend `test_the_profile_overlays_cut_picks_at_their_columns`. The overlay is `(column_at(key, distance_m), time_ns)` with no conversion, even when the shown cube's preset sets a time zero;
  - `test_a_pick_made_on_another_clock_is_left_out_and_counted`. Make a cut pick under a preset without `time_zero`, then enable `time_zero` in the preset so the cube is rebuilt. Check that:
    - the pick is not in `view.set_picks`'s list, and the title ends ` · 1 picks on another clock`;
    - the row is unchanged;
    - turning `time_zero` off again brings the pick back;
  - `test_a_line_stack_change_never_rezeroes_cut_picks`. Edit the working line's stack so its zero moves. `follow_zero` rewrites that line's rows only, and the cut picks' `time_ns` and `zero_ns` are unchanged.

A8. **Added by the controller after the merge's QGIS run** (1880 passed, 3 failed at `b2c1961`). These three tests must pass after this task:
- `test_plugin_cut_picks.py::test_a_cut_pick_with_a_null_distance_is_left_alone_across_a_grid_move`;
- `test_plugin_cut_refine.py::test_deleting_the_working_cut_mid_solve_stops_the_worker`;
- `test_plugin_session_cuts.py::test_removing_a_grid_announces_the_dropped_items_in_one_order[True]`.

All three fail on two log lines emitted with a cut key:
- `session.py:1049` "could not find where line cut:… has its time zero", which A3/A4 fix;
- `profile_dock.py:1417` "could not update the velocity fit: no line with key 'cut:…'". Here #97's velocity-fit update now runs on a cut key. Fits are off on cuts, so skip that path for a cut key and leave line behaviour unchanged.

Add a test that showing a cut, and removing its grid while it shows, logs nothing from the velocity-fit update, unless the three tests already pin it.

## Part B — the final review's residuals

Background for B1 to B3 is in the ledger (`progress.md`, the lines starting "Final fix wave re-review" and "Ruling (residual"). The re-reviewer's scratch reproductions are in the controller's scratchpad, `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/6c688425-24a0-4587-bf1d-934c08fd3d6a/scratchpad/`:
- `probe_i1.py`, with its output in `threshold.txt`;
- `qtests/test_scratch_i2.py`, the leak;
- `qtests/test_scratch_rearm.py`, the spurious restart.

Read them as references. Do not run anything from inside that directory, and do not commit them.

B1. **The crop threshold (I1).**
- Set `CROP_MAX_DISTANCE_SPACINGS` to **0.5** (`packages/nsgeo-core/src/nsgeo/slices/section.py`).
- At the default 0.75 spacings, a cut's minimum curvature now solves the whole frame.
- Rewrite the module docstring's threshold paragraph to match the amended spec §4.7:
  - at 0.75 spacings, crops failed 6 of 9 cases across holes (1.08e-3 to 2.75e-3);
  - at 0.5 spacings, every case passed (worst 6.6e-4).
- Correct the matching docstrings in `cut_sections.py`.
- Check the README row's wording.

**State after the merge.** With #97's cube changes, `test_a_cut_through_a_coverage_hole_agrees_with_the_slice[across the hole-0.75]` now fails even its 2e-3 allowance: 1.44e-3 against a range of 0.605, which is 2.4e-3. B1 is the fix. If any case at 0.5 spacings misses 1e-3 on the merged cube, stop and report it with the numbers. Don't loosen the bound, and don't change the threshold again on your own.

Tests in `packages/nsgeo-core/tests/test_slices_section.py`:
- `test_the_threshold_picks_crops_or_the_whole_frame` pins 0.5. Exactly 0.5 spacings uses crops; 0.75 and 1.0 use the whole frame. Keep the rounding case, at 0.5.
- `test_a_cut_through_a_coverage_hole_agrees_with_the_slice`:
  - Restore **1e-3 everywhere**, removing the 2e-3 allowance and its comment.
  - Parametrize the hole over `dropped` = (4, 5) for 1 m, (3, 4, 5, 6) for 2 m, and (2, 3, 4, 5, 6, 7) for 3 m.
  - Cuts across the hole along y at x = 4.0, 10.2 and 17.5, plus the existing diagonal and "beside" paths.
  - Spacings 0.5 (crops) and 0.75 and 1.5 (whole frame).
  - Levels k = 10, 30, …, 170.
  - If the parametrized set takes more than about 60 s on one thread, drop "beside" and the 1.5 case for the 1 m and 3 m holes, and say so in the report.
- Update `test_plugin_cut_refine.py:441`, where the plugin's crops-vs-whole test sets `max_distance_spacings=0.75`, so it still tests both paths.

B2. **The cube leak and the drop trigger (I2).** This is in `packages/nsgeo-qgis/nsgeo_qgis/cut_sections.py`. A streaming engine's cube built for a cut is dropped **only when**:
- a cut whose source is another engine opens;
- the cut is deleted;
- the cut's source engine changes (scope switch, another grid in This grid, a disposed engine); or
- the site closes, or on dispose.

It is **not** dropped when the working item moves to a line. So memory stays bounded to one cut-built cube, and a line visit keeps the solve.

The leak to fix: `self._streamed[key] = engine` overwrites an earlier engine for the same key without releasing it. When the key's recorded engine differs from the new one, drop the old engine's cube if it is streaming and no other entry holds it. Never drop a resident engine's cube (the existing re-check at drop time stays).

Tests in `test_plugin_cut_sections.py`:
- Replace `test_a_streaming_engine_under_budget_builds_then_drops_its_cube_for_a_line` with:
  - `…_keeps_its_cube_across_a_line_visit`: open the cut, open a line, reopen the cut. The cube is still held, the cached section and its solved rows are kept, and the solve resumes rather than restarting at 0;
  - `…_drops_its_cube_when_a_cut_on_another_engine_opens`.
- `test_a_scope_round_trip_with_a_cut_open_holds_one_cube`. With the cut open in the profile, go This grid → Whole site → This grid → Whole site. After each switch, at most one streaming engine holds a cube that a cut built. Use the `site` fixture, as the scratch test does.

B3. **Re-arm only when the centre moves.** `_on_window_changed` re-arms a running solve only when `_centre_level` for the new band differs from the centre the solve was ordered on. `window_changed` fires on every slice refresh, site redraw and `reannounce_window`.

Test `test_a_window_change_that_keeps_the_centre_does_not_restart_the_solve`: a palette change mid-solve (it emits `window_changed` with the same band) does not call `Refiner.start` again. Keep `test_a_rested_window_change_recentres_the_solve_on_the_new_band` green.

B4. **The "being prepared" message in Whole site scope.** `_preparing` reads `site_engine.grid_state(grid_id)` in Site scope, not the grid engine's `is_running`. A grid queued behind another is being prepared too. Read `site_engine.py` for the states, and treat an unknown grid as not preparing.

Test it with real queue states. The current Site-scope test (`test_whole_site_says_the_grid_is_being_prepared_again`) monkeypatches at class level. Replace or add one that drives a queued grid, or set `_states` only if there is no public way, and say which.

B5. **The build-failed reason is never empty.** Use `str(exc) or type(exc).__name__` in `BUILD_FAILED_TEXT`.

Test: a build raising `MemoryError()` shows `…: MemoryError`.

B6. **A failed build retries only when its inputs change.**
- Today a failure waits as `"source"`, so every `slice_changed`, which fires on every slider tick, retries the synchronous GUI-thread build and logs a warning.
- Remember the failure against the engine and its preparation. It is retried only when:
  - the engine object changes;
  - the engine prepares again; or
  - the user opens the cut again (the working item is opened).
- If you need a counter from `SliceEngine`, add a small read-only public property next to `cube_generation`, with a docstring, rather than reading a private attribute.

Test: after a failed build, three `slice_changed` emissions call `engine.cube()` no more times, and the log gains no warning; a re-preparation retries once.

B7. **Docs.**
- `SlicesDock.reannounce_window`'s docstring wrongly says `window_changed` only fires when the window changes. Correct it (`slices_dock.py`, around line 2774).
- In `docs/guide/getting-started.md`, the title example "*Kriging preview · minimum curvature 12 of 463 depths*" quotes a real depth count. Write it without one: name the shape, `n of N depths`, and say what n and N are.

**Not in this task:** `TOO_BIG_TEXT` re-announcing on every `slice_changed` is parked. So are the follow-ups in `final-fix-wave.md`'s "Not in this wave" list. Don't do them.

## Done means

- All tests above are written and pass.
- Core + pure and the full QGIS suite are green, and ruff, `ruff format --check` and mypy (CI's list) are clean.
- Commits are pushed to `origin/nsgeo-m15-cut-anywhere` as you go (`git push`). If the push fails on DNS, retry once and report it.
