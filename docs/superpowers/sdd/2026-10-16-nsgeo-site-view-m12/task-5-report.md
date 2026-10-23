# Task 5 report: the Slices dock's Whole site scope

Implementer: Claude Opus 5.5. Branch `nsgeo-m12`, base 8ea18e3.

Commits, each pushed to `origin/nsgeo-m12` as it was made (no network failures):

- `09654b5` test: share LoadCounter and spin_until through plugin_testing
- `ed839e1` feat(qgis): SliceLayer.update_north_up -- the site lattice through the one layer
- `3ef95d2` feat(qgis): the Slices dock's Whole site scope

## What was implemented

A **This grid / Whole site** switch at the top of M11's Slices dock. *Whole site* shows every
included grid's slice on one map layer (`Site slice (live preview)`), with one depth slider,
a stretch shared across the site, per-grid normalisation and gain, and a site GeoTIFF export.
The dock computes nothing: `SiteEngine` (Task 3) and `site_export` (Task 4) do the work, and
the survey record comes from Task 2.

### Files

| File | What |
|---|---|
| `nsgeo_qgis/ui/site_panel.py` (new, 351) | `SiteRow`, `SiteSourcePanel`, `NormalisationPanel`. Widgets only, as the brief specifies. Two small additions to the brief's API: `SiteSourcePanel.transform()` and `select_grid()`. |
| `nsgeo_qgis/ui/site_scope.py` (new, 904) | Plain functions that turn the session and `SiteEngine` into values: the included grids, each grid's source, the list rows, the seeded resolution, the readout and depth text, velocities, the left-out grids. Also `SiteScope`, the dock's site-scope controller (state, tick, resolution, display limit, panel handlers), and the shared-widget helpers (`show_scope_widgets`, `capture_spins`/`restore_spins`/`set_spins_quietly`). |
| `nsgeo_qgis/ui/slices_dock.py` | 2041 → 2393 lines (**+352**). It now has the scope switch, the new widgets, R-P5's guard, the delegates the brief names, and one-line site branches at the top of a few M11 methods (`refresh_slice`, `_apply_resolution`, `display_limit`, `display_unipolar`, `thickness_step_levels`, `step_slice`, `reannounce_window`, `_mark_cube_unsaved`, `_on_prepared`, `_refresh_source_status`, `prepare`, `rebuild_source`). Apart from those branches, M11's flow is untouched. |
| `nsgeo_qgis/slice_layer.py` | `SITE_LAYER_NAME`. `update` now resamples and delegates to `update_north_up(..., name=LAYER_NAME)`. `name` renames the layer in place, and extent and CRS are synced after `reloadData()` (see the defect below). |
| `nsgeo_qgis/plugin.py` | `_on_slice_changed` has a site branch. `open_line_choice_dialog` uses `line_choice_grid`, `line_choice_keys` and `set_included_for`, with Ruling Z comparing `line_choice_grid()` at `finished`. `export_geotiff` routes to the new `export_site_geotiff`. `unload` calls `dock.dispose_site()` before `engine.dispose()`. |
| `tests/qgis/test_plugin_site_scope.py` (new, 27 tests) | The brief's 14 dock and plugin tests, plus the tests the rulings ask for and a few more (listed under TDD below). |
| `tests/qgis/test_plugin_slice_layer.py` | +3 tests: rename in place, CRS follows, extent follows. |
| `tests/plugin_testing.py`, `tests/qgis/test_plugin_site_engine.py` | `LoadCounter` and `spin_until` moved into the shared helper module, so both files use one copy. Task 3's tests now import them; nothing else changed. |
| `tests/pure/test_no_orphan_signals.py` | Pins `choose_lines_requested` in `SHADOWED` (declared 2, connects 2). The brief names the panel's signal the same as the dock's existing one. Both are connected. |

**Code organisation.** A first draft put the site logic straight into the dock, and it grew by
about 870 lines. As the brief directs, I moved the logic into `SiteScope` in
`ui/site_scope.py`. The dock delegates to it: `_refresh_site_slice`, `_site_source`,
`_on_site_changed` and `_apply_site_resolution` are one-liners. The +352 lines left are mostly
widget construction, the switch, and R-P5.

### Choices where the brief left one

1. **Resolution values are kept per scope.** The two scopes share the Resolution widgets
   (spec 4.1) but not their values. Leaving a scope snapshots cell, cell floor, dz, z0, z1 and
   the time step, and entering restores them. This grid therefore comes back at exactly
   M11's resolution, and the site keeps its own. The site's snapshot is reused only while the
   included set is unchanged; otherwise the site is seeded again.
2. **Cell seed and floor.** M11's rule `max(floor, min(0.5, spacing / 2))` is applied to the
   finest-spaced included grid. The floor is the largest of the grids' `smallest_safe_cell`
   (W7). The lattice limit is left to `SiteEngine.set_resolution`, which refuses with a
   message.
3. **dz, z0 and z1.** Before any grid is ready, they are seeded from the union of the included
   grids' header ranges. Each time the ready set changes, they are re-seeded to the union of
   the ready grids' *prepared* bounds, snapped inside. Once the user edits dz, z0 or z1 in
   site scope, those values are only clamped into that union (M11's
   `_clamp_z_to_prepared` rule) and never re-seeded. This is how I read "seeded from the
   union … with the first-ready clamp M11 uses".
4. **T2-c fallback.** A stored transform that is no longer offered falls back to what This
   grid's transform combo shows ("none" on a fresh dock). The same value is the default when
   nothing is stored.
5. **Residency checkbox hidden in site scope.** Spec 4.8 keeps residency per grid and
   automatic, and the checkbox drives only This grid's engine.
6. **State column.** Shows `ready`, `queued`, `preparing n of m`, `no lines` or `failed: …` from
   the engine. An unticked grid shows `not included`. An included grid not yet handed to the
   engine shows `waiting`.
7. **Lines chosen in site scope** are remembered as an explicit list, as M11's chooser does.
   If they are for This grid's own grid, This grid picks them up on the way back and owes a
   preparation (spec 4.2: one record). Only preset and lines are compared, so a gain edit
   alone never triggers a re-prepare.
8. **This grid's `_on_prepared` while the site shows** is deferred. Its clamp would otherwise
   write into the site's spins. It runs on the way back.
9. **The gain spin** has `keyboardTracking(False)`, so it makes one change per finished edit.
   Each change re-measures the shared stretch.
10. **A failed export** removes the file only if this export wrote it (its mtime moved). If
    the export fails before writing, a file the dialog chose to replace survives. A success
    that leaves a grid out is reported at Warning, naming the grid.
11. **New public API beyond the brief:** `dock.dispose_site()` (used by unload),
    `dock.site_gains()`, `dock.site_left_out()`, and `plugin.export_site_geotiff()`. In grid
    scope, `set_included_for` raises `ValueError` for a grid other than This grid's (the
    plugin's Ruling Z check runs first).

## How each ruling in task-5-rulings.md was met

- **R-P5.**
  - On entering site scope, `engine.on_grid_moved = dock._mark_grid_stale`, which only sets
    `_grid_prepare_pending`. On leaving, it is set back to `None`.
  - `prepare()` returns early, recording the pending prepare, when `scope() == "site"` *or*
    `site_engine.has_live_task`. That covers `rebuild_source`'s automatic call on
    `grids_changed`, `lines_changed`, `presets_changed` and site open.
  - `set_scope("grid")` sets the scope first (the site's cancel spins the event loop), calls
    `site_engine.cancel()`, then runs `_run_pending_grid_prepare`. That retries on a 50 ms
    single-shot `QTimer` while `site_engine.has_live_task`, never blocks, and is guarded.
  - `SiteScope.on_changed` (the engine's `on_changed`) refreshes rows and schedules a tick. It
    never prepares This grid.
  - Test `test_editing_a_grid_in_site_scope_never_overlaps_preparations` follows the ruling
    exactly, and both named mutants fail it by `max_concurrent=2`.
  - `test_leaving_the_site_waits_out_a_task_that_outlived_its_cancel` covers the retry path,
    using a 1 ms cancel wait.
- **T3-g.** Step 4 (fill-skipping) is not built. Site ticks are coalesced by a 0 ms single-shot
  `QTimer` owned by `SiteScope`, started only when it is not already active. Every site-scope
  `refresh_slice()` (slider, thickness, step, stretch, palette, coverage) goes through it, so
  at most one tick runs per event-loop pass, with the latest values. The slice shown is always
  the full one. Grid scope keeps M11's direct, uncoalesced `refresh_slice`. Test:
  `test_a_burst_of_slider_moves_draws_once_with_the_last_value`.
- **T3-d.** The State column shows `preparing n of m` from `grid_progress`. Rows are refreshed
  on every `on_changed`, the rows only. Test:
  `test_the_list_shows_each_grids_progress_while_it_prepares`.
- **T2-c.** See choice 4. Test: `test_a_stale_transform_on_disk_falls_back_to_the_dock_s`. It
  sets This grid to `amp_envelope` first, so the fallback is distinguishable from the panel
  simply ignoring an unknown name.
- **The cost of `shared_limit`.**
  - The site limit is cached by thickness levels, the source sent, the resolution applied,
    the ready grids, method, gains, radius and polarity. It is never keyed on the slider.
  - It is invalidated when the ready set changes or a session signal arrives.
  - Test: `test_the_shared_stretch_is_measured_once_not_on_every_slider_move`.
- **T4-a.**
  - The export button is enabled only while ready grids and a lattice exist and no included
    grid is queued, waiting or preparing. Test:
    `test_the_site_export_is_disabled_while_a_grid_prepares`.
  - The success message names included grids that are failed or have no lines. Test:
    `test_the_export_message_names_a_grid_left_out`.
- **T4-b.**
  - If `export_site` raises, the partial file is removed (see choice 10) and no layer is added.
    M11's grid export is unchanged. Test:
    `test_a_failed_site_export_leaves_no_file_and_adds_no_layer`.

## Test results

All counts are from my own runs, on the final production code.

| Run | Result |
|---|---|
| Baseline core+pure (clean HEAD export) | 604 passed, 2 skipped |
| Baseline qgis | 796 passed in 312 s |
| core+pure after | **604 passed, 2 skipped** |
| qgis after | **825 passed in 360 s** (796 + 29 new). The 27th site-scope test, the coverage companion, was added after that run had collected, so it ran on its own: 27 passed. See the final run below. |
| `ruff check .` / `ruff format --check .` | clean (133 files) |
| mypy (the CI command) | Success: no issues found in 34 source files |

**Final run, on the exact tree committed:** core+pure 604 passed, 2 skipped; qgis **826 passed in 352 s** (796 + 30 new); ruff, format and mypy clean.

### The 20-run loop

Seven concurrency and timing tests ran 20 times in a row:

- `test_editing_a_grid_in_site_scope_never_overlaps_preparations`
- `test_flipping_scope_mid_preparation_never_overlaps_and_settles`
- `test_leaving_the_site_waits_out_a_task_that_outlived_its_cancel`
- `test_unload_with_the_site_scope_open_leaves_nothing_running`
- `test_the_list_shows_each_grids_progress_while_it_prepares`
- `test_the_site_export_is_disabled_while_a_grid_prepares`
- `test_a_burst_of_slider_moves_draws_once_with_the_last_value`

**Result: 20 of 20 runs, `7 passed` every time, 14.9–16.6 s per run. No failure, no flake.**

## TDD evidence

**RED.**
- *How it was run:* the new tests ran against HEAD's production code, in a clean
  `git archive HEAD` export with the new test files copied in.
  - First run: collection fails on `ImportError: cannot import name 'SITE_LAYER_NAME'`.
  - With only that constant appended to HEAD's `slice_layer.py`:
    `26 failed, 10 passed, 23 errors`. Every new test fails. The 10 passes are M11's existing
    slice-layer tests. The 23 errors are teardowns reaching `dock.site_engine`, which does not
    exist on HEAD.
- *Order of work:* I wrote the first draft of the implementation before the tests, then
  wrote the tests and demonstrated RED against the pre-change code as above.
  - The production code changed after that only in response to the tests and the mutants:
    - the layer extent sync, found by the extent check;
    - the T2-c test strengthened;
    - the R-P5 test's timing widened.

**GREEN.**
- 37/37 on the new and changed test files at first green, 27 + 13 now.
- Then the full tiers above.

**Failures found on the way to GREEN, both real:**
1. **Stale layer extent after `reloadData()`.** The extent assertion in
   `test_whole_site_draws_one_layer_covering_every_grid` failed: the layer reported 500–506
   while the lattice covered 500–518.
   - A probe (QGIS 3.44.7) showed that after `reloadData()` the provider has the new extent
     and CRS but the layer keeps those it was created with. `setExtent` is exposed.
   - Fixed in `update_north_up` with three tests.
   - This is also a latent M11 defect. Switching This grid between grids at different places
     reloads the same layer, which kept its first extent and CRS (QGIS draws a raster only
     inside its layer extent). M11's walkthrough never moved the extent, only the cell.
2. **The map clears on the first site entry.** The site's engines are separate from This
   grid's (Ruling 1), so nothing is drawable until the site's first grid is ready. The layer
   is cleared and recreated then. Renaming in place, which the test pins, applies once both
   scopes have drawn. That matches spec 4.2 ("draws each grid as soon as it is ready").

## Mutants

Every mutant was run with `PYTHONDONTWRITEBYTECODE=1` after deleting every `__pycache__`.
Each failed at least one test, and each for the reason its test exists.

| # | Mutant | Killing test | Failure |
|---|---|---|---|
| 1 | Brief 1: leaving the site does not cancel the site engine | flipping_scope_mid_preparation | "leaving the site stops its preparation" (`site_engine.is_running`) |
| 2 | Brief 2: window not carried (`top = None`) | switching_scope_keeps_the_window_time | site top −2.424 ns vs This grid's 17.061 ns |
| 3 | Brief 3: gain written to every included grid | gain_spin_scales_only_the_selected_grid | grid A's pixels changed |
| 4 | Brief 4: `set_included_for` → `set_included` in site scope | choose_lines_acts_on_the_selected_grid_only | "only B re-prepares" (0 loads, not 3) |
| 5 | R-P5: hook not set on entering the site | editing_a_grid_in_site_scope_never_overlaps | **`max_concurrent=2`** (5/5 repeats) |
| 6 | R-P5: `prepare()` not deferred | same | **`max_concurrent=2`** (5/5 repeats) |
| 7 | T3-g: tick run immediately, not coalesced | a_burst_of_slider_moves_draws_once | five `slice_at` calls before the event loop ran |
| 8 | T4-a: export enabled while a grid prepares | site_export_is_disabled_while_a_grid_prepares | enabled while busy |
| 9 | T4-b: partial file not removed | a_failed_site_export_leaves_no_file | file exists |
| 10 | T4-a: left-out grid not named | export_message_names_a_grid_left_out | message lacks "C (no lines)" |
| 11 | Export not routed to the site | export_routes_to_the_site_geotiff | dialog titled "Export GeoTIFF" |
| 12 | `update_north_up` ignores `name` | update_north_up_renames_the_layer_in_place | name stays LAYER_NAME |
| 13 | Extent not synced after reload | the_layer_extent_follows_a_lattice_that_grows | xMax 506 vs 518 |
| 14 | CRS not synced after reload | update_north_up_follows_a_crs_change | 32616 vs 32615 |
| 15 | Gain spin keeps Qt's 1.0 step | gain_spin_steps_by_a_useful_increment | singleStep 1.0 |
| 16 | T2-c: stale transform kept | a_stale_transform_on_disk_falls_back | "none" vs "amp_envelope" |
| 17 | Ruling Z dropped (choice always applied) | a_line_choice_is_dropped_when_the_selection_moved | B's lines overwritten |
| 18 | One velocity for every grid's depth | readout_names_each_grids_depth | B shows A's depths |
| 19 | T3-d: no progress in the State column | list_shows_each_grids_progress | only "preparing" seen |
| 20 | Shared limit not cached | shared_stretch_is_measured_once | six measurements on slider moves |
| 21 | This grid ignores the record the site wrote | lines_chosen_in_the_site_for_this_grids_grid | This grid kept four lines |
| 22 | R-P5 retry: no `has_live_task` wait (both checks removed) | leaving_the_site_waits_out_a_task | "This grid waits for it" (`engine.is_running`) |
| 23 | Method not persisted | site_view_survives_save_and_reopen | "none" vs "edge" |
| 24 | Ruling AH: companion failure escapes to the outer handler | coverage_companion_…_failure_is_its_own | "could not export the site GeoTIFF: disk full" |

**About mutants 5 and 6.** At first they were killed only by the follow-up `is_prepared`
assertion, not by the counter.
- A timeline trace showed why. A task the This-grid engine dispatched read its first line
  about 0.2 s after dispatch, and B had only about 0.24 s of work left. The overlap was real
  but lasted 23 ms, and the counter could miss it.
- The test now waits until B has read one line (`grid_progress("B") == (1, 4)`) and uses
  0.2 s per line, leaving about 0.6 s of overlap window. Both mutants now fail on
  `max_concurrent=2`, 5 times out of 5.

## M11 tests changed

None. M11's whole dock suite (`test_plugin_slices_dock.py`) and every other existing qgis-tier
test pass unchanged. The only edits to existing test files are:
- the `LoadCounter`/`spin_until` move into `plugin_testing.py` (Task 3's file now imports them);
- the `SHADOWED` pin;
- three added slice-layer tests.

## Self-review findings

- **Fixed during review.**
  - Gain edits no longer count as a record change. A first draft compared the whole
    `slice_sources` entry, so a gain edit for This grid's own grid would have re-prepared it.
  - `included_grids` makes one pass over the lines instead of one pass per grid.
  - A failed export no longer deletes a pre-existing file it never wrote (mtime guard).
- **Checked and fine.**
  - Refills are guarded (trap 8): the panel's table and transform combo, the method combo, the
    palette refill, and the stretch item rename.
  - Every new slot guards its body.
  - No `QDialog.exec()`.
  - Every new spin has a useful `singleStep`: gain 0.05, radius 0.25.
- **Accepted.**
  - The site's shared limit is re-measured each time a grid becomes ready. That is correct (the
    stretch must include the new grid), but Task 3 measured `shared_limit` at about 3 s on a
    10 × 50 m streaming site. The first preparation of such a site pays that once per grid.
  - The readout shows "not prepared" when the lattice was refused as too large. The refusal
    itself is on the message bar.

## Concerns

1. **Re-ticking a grid re-prepares it.** The plan's walkthrough step "Untick a grid … Tick it
   again. It returns without re-preparing" will not hold.
   - `SiteEngine.set_source` (Task 3) disposes a dropped grid's engine by contract, and the
     dock has no way to keep a grid prepared but undrawn.
   - Meeting the step needs a `SiteEngine` change, for example parking dropped engines that
     have no live task and restoring them when the choice is unchanged. That lies outside this
     task's files and touches the trap-1 module.
   - The alternative is to reword the step. **Controller decision.**
2. **The extent and CRS sync changes M11's `update` behaviour** where it was wrong: switching
   This grid between grids at different places, or in different CRSs. It is worth a look in
   the walkthrough.
3. **The first entry into Whole site clears the map** until the site's first grid is ready
   (finding 2 above). Re-entering is immediate, because cancelled grids keep their prepared
   lines.

## For the manual walkthrough

- Click *Whole site*. The map clears briefly, then each grid appears as its State reads
  `ready`. The State column steps through `preparing n of m`.
- Hover the Fill radius in site scope. The tooltip lists each grid's radius in metres.
- Untick a grid and tick it again. **It re-prepares** (concern 1). The walkthrough step as
  written expects it not to.
- With *Show coverage* on, *Export site GeoTIFF…* also writes `<name>_coverage.tif`. While any
  grid prepares, the button is disabled.
- In *This grid*, switch between two grids at different places on the map. Each should be
  drawn whole, at its own place (the extent fix, concern 2).
- Switch *This grid* → *Whole site* → *This grid*. This grid returns at its own cell size and
  z range, at the same window time.
