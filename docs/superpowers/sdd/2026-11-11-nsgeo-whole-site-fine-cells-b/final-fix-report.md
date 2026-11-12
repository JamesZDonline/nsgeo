# Final fix wave report (milestone B, #108)

Commits (on nsgeo-fine-cells-export, not pushed):
- b52966a fix(export): final review wave (code and tests)
- ec3ef98 docs: coverage advice, replace restore, roadmap line; CI types export_pipeline
- b6da38b docs(export): estimate table with the finishing term

## Per finding
- I1: `commit_partial` unlinks `<target>.aux.xml` and `<target>.ovr` after `os.replace` (values and companion both go through it). Test `test_a_commit_drops_the_old_files_statistics_and_overviews` (RED: aux.xml still existed; GREEN after fix; new statistics read back 9.0).
- I3: `test_a_rotated_export_equals_what_this_grids_live_layer_draws`, 7/30/88 deg x kriging/none; shape, geotransform, NaN mask, values 1e-5. Passed on first run (pin test, no RED, as the reviewer predicted).
- M1: `FINISH_BYTES_PER_CELL = 60` added to `band` (largest grid). Bench with new `--export-smooth 0.1` option on bench_site.py. Rows (estimate vs measured peak, MB): 0.05/0.05 kriging 315 vs 294, min curv 320 vs 302; 0.025/0.025 kriging 1259 vs 1204, min curv 1282 vs 1179. Peak did not move with smoothing (setup sets the peak). 0.0125 rows not re-run (estimate +38 MB by the same term; stated in docstring). 0.025/0.025 still FITS the 1.5 GB budget (1259/1282 MB). I read the brief's "now passes ... STOP" as meaning "no longer passes"; the walkthrough case must fit and does. If the literal reading was intended, this is BLOCKED by that clause: please say.
- M2: GDAL 3.8.4 `BuildOverviews("MAX")` -> "Unsupported resampling method" (checked in both venvs). `build_overviews(..., counts=True)` uses NEAREST; the task passes `counts=plan.coverage`. Tests: `test_a_counts_overview_holds_only_whole_counts` (RED: AVERAGE gave 1.5), `test_the_companions_overviews_are_built_for_counts`.
- M3: "none" drops "measured again" (pure test, RED then GREEN).
- M4: `ExportDialog(writes_coverage=...)`, `target_paths(path, coverage)`; plugin passes it. Test with a companion layer open and coverage off (RED: FF, then GREEN).
- M5: each This grid band now records `NSGEO_WINDOW_NS` (site files already did); `restore_band_times` re-wires a restored layer from its own file ("set" / "counts" / "missing"). Older files without the key come back untimed and the restore message says so. Guide updated. FORMAT ADDITION: a new band key on This grid files, beyond the listed metadata; flag for your approval. Tests: slice_export band-window tests, the cancel/fail restore helper asserts the temporal properties are active (RED then GREEN).
- M6: `_add_export_layer` unlinks the stale `.qml` on write_style failure and appends a Warning sentence to the success message. Test `test_a_style_file_that_cannot_be_written_is_not_left_stale` (RED: qml still there).
- M7: slice_export module docstring, ExportCancelled, OVERVIEW_FACTOR comment, frame_lattice (north-west), SiteLattice docstring, slice_layer comment rewritten.
- M8: `ExportResult.values_written`; limit kept when the values file was replaced. `_finish_half_written` says "the GeoTIFF was written to ..., but the coverage file could not be", adds the new values layer, restores only layers on other files. Tests: task-level companion rename raises; plugin-level replace with companion rename raising.
- M9: guide coverage advice reworded.
- Triage 11: no-bleed test now has 1.0/3.0/7.0 columns at the data edge and asserts means 2.0 and 7.0 (pin; passes).
- Extras: export_pipeline.py on the CI mypy line (passes, 45 files); `~` expanded (test); site dialog live cell from `site.full_lattice.pixel` (new test, RED 0.4 vs 0.2); `SliceEngine.last_solve_ms` removed, its tests read `_last_solve_ms`; README #157 line joined with "; ".

RED not captured separately for the two task-level tests in test_plugin_export_task.py (companion rename, counts flag): they use attributes/args that did not exist before.

## Tiers
- pure: 282 passed, 1 skipped. core: 982 passed, 4 skipped. QGIS full tier: 1760 passed (15:00).
- ruff check clean, ruff format --check clean, CI mypy line (with export_pipeline.py) clean.
