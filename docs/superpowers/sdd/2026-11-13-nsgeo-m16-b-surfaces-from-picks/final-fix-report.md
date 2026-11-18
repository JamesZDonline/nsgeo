# M16 B final fix wave: report

Commit 12371a6 on nsgeo-m16-b, pushed to origin (head was 027d082).

## Changes per item
- I2/R12 (surface.py): `_track` returns a third array, True where the argmax is the window's first or last level and the next level outside has a larger swing (NaN-safe, False when no level lies outside). `build_surface` carries it per pick; `_fit` counts those as `at_edge` (reason "edge"), so they never reach within_close/near. Tests: test_a_pick_beyond_the_window_with_a_stronger_swing_outside_is_at_the_edge (fails before, passes after).
- R13: `_guide` no longer fills min_curvature gaps with the mean; `region &= isfinite(guide)`. Test: test_cells_beyond_the_curvature_joins_reach_are_outside_the_region (fails before).
- I1/R11: `panel_values` rounds the record end UP to 4 decimals; `_compute` remembers the choice after the per-record loop. Deviation: the dialog's depth step spin also rounds to 4 decimals (native dt 0.21653 -> 0.2165), which alone marked surfaces stale ("resolution") after an untouched dialog export, so `_compute` builds with dz rounded to 4 decimals (identical to what the dialog writes back; no-op for dialog-set values). test_building_remembers_the_grids_3d_choice updated for this. Tests: test_building_then_exporting_at_the_dialogs_defaults_keeps_surfaces_fresh (real dialog, stale == (), one fill_levels call), test_a_refused_build_remembers_nothing.
- M1: one `members_by_feature()` per sync, per `_surface_states`, per `_write_features`; `_surface_states` checks the json's npz file exists instead of loading every npz. Test: test_a_sync_scans_the_picks_once_however_many_surfaces.
- M2: `SiteLayers.features_available()`; sweep skipped when false. Test: test_an_unreadable_features_table_never_sweeps_the_builds_away.
- M4: outlier heading "Picks the surface doesn't follow (n): on a hole, at the window's edge, or more than W cm off"; far lines now end "beyond the window"; guide step 4 reworded. Pure tests updated.
- M5: guide note that the grid's 3-D settings need Save site.
- M7: `SiteLayers.picks_in_open_transaction()` (transactionMode() != Disabled, else autoTransaction(), hasattr-guarded); create/add/remove/delete refuse with IN_TRANSACTION_REFUSAL. Tests: membership refused inside the transaction; no hazard with editing alone or grouping alone.
- M8: only "database is locked" gets the picks advice; "locked a portion of the file" gets FILE_LOCKED_TEXT. Pure test.
- M9: `build` skips too-small surfaces, records the refusals in `Surfaces.refused` (plugin adds them to the reported failures); all too small still raises. Test: test_one_too_small_surface_never_blocks_its_grids_rebuild.
- M10: `remove_picks` returns the count; the dock shows NOTHING_TO_REMOVE on 0. Test: test_removing_picks_that_are_not_in_the_surface_says_so.
- layers.py addAttributes and write_pick use `_provider_reason` (no new test).

## Commands and results
- core surface tests under -W error: 39 passed, 1 xfailed; whole core: 1265 passed, 4 skipped, 1 xfailed.
- pure tier: 346 passed, 4 skipped.
- ruff check and format: clean; mypy (CI list): no issues.
- whole QGIS tier, one process, NSGEO_PVPYTHON set: 2432 passed, 1 warning (gdal FutureWarning), 25:59.

## Parity (outside repo, core_parity.py)
- Bowl: 88 picks, offset 3.52 cm (at limit 29, reliable). Fit: within 2 cm 60, 2-5 cm 0, further 0, at edge 26, on holes 2, outliers 28, sum 88.
- R5: kept 14057 vs trial 14035; both 14021; agreement 99.6%; median |delta depth| 0.097 cm (p95 0.226, max 4.16); south-west holes mine 49.5% vs trial 50.3%. Unchanged. R13 neutral (surface cells identical).

## Concerns
- The dz rounding in `_compute` (above) is beyond the brief's letter; it changes build resolution by under 0.02%.
- M9's refusals travel via a `Surfaces.refused` attribute rather than the return value.
