# M16 Plan A final review fixes: report

Commit 4a04ee4 on nsgeo-m16 (pushed to origin). All ten items done.

## Items, changes, tests

1. Disk guard. `paraview_scene.py`: `fill_margin_bytes` (max 0.5 GB, 10% of cache), `export_margin_bytes`
   (10% of export, clamped 50..250 MB), `fill_refusal`, `export_refusal`, `disk_refusal`; `disk_text`
   shows the refusal. `ParaViewExport.run` refuses (ValueError) before `_fill` (so before any `.part`)
   and again before `partial.mkdir`. Dialog disables both buttons on `disk_refusal`, shows the reason in
   the Disk row (red); a merely tight disk keeps the old warning with Export on. Guide updated.
   Tests: export `test_a_disk_too_full_for_the_fill_is_refused_before_any_part_file`,
   `..._for_the_files_is_refused_and_the_old_export_stays`; dialog
   `test_a_disk_that_cannot_hold_the_fill_and_the_export_turns_both_buttons_off`,
   `test_a_merely_tight_disk_warns_and_leaves_export_on`, `..._room_for_the_files_but_not_the_fill...`,
   `test_a_very_short_disk_says_...` (the old "short disk still exports" test, rewritten);
   pure `test_the_disk_refuses_only_what_cannot_fit_with_its_margin`.
2. Windows folder lock. `launch_paraview` uses a `QProcess` instance (program, arguments, working
   directory = folder parent, `NSGEO_SCENE_DIR` in `systemEnvironment()`), `startDetached()`; handles the
   tuple return (PyQt5 here returns (bool, pid); PyQt6 not installed here, code handles both).
   `open.bat.txt`: no `cd`, `start "" "{{PARAVIEW}}" --script=...` (CRLF kept at write). `open_scene.py.txt`
   already reads `$NSGEO_SCENE_DIR` (checked). `_swap` maps PermissionError on the rename to
   RuntimeError("<folder> is in use, probably by ParaView; close it and export again"), old export intact.
   Tests: `test_paraview_really_starts_in_the_parent_with_the_scene_dir_in_its_environment` (a real
   detached launch of a script that records cwd/env/arg), updated spy test
   `test_export_and_open_launches_paraview_with_the_folder`, `test_a_folder_in_use_is_said_so_and_the_previous_export_stays`,
   pure `test_the_windows_launcher_does_not_hold_the_folder_and_keeps_crlf`. Guide gets one Windows line.
3. Cancel in first fill. The handler calls `traceback.clear_frames` (drops the memmap held by the
   traceback), suppresses OSError on the `.part` unlink, `VolumeStopped` now goes through the same
   cleanup. `run` starts by deleting this grid's `*.npy.part` (`_cache_files(..., ".npy.part")`, same
   exact-name regex). Tests: `test_a_cancel_in_the_first_fill_survives_an_unlink_that_fails`,
   `test_a_stale_part_file_of_this_grid_is_removed_and_another_grids_is_not`,
   `test_a_volume_stopped_after_the_folder_began_cleans_up_like_any_failure`.
   Not testable on Linux: that clear_frames actually frees the Windows file lock (the suppress is what is tested).
4. `_export_progress` docstring rewritten for its one user (`show_now`).
5. Skipped lines: `run` sets `export.skipped_lines` (source keys minus prepared); `export.json` gets
   `skipped_lines` (new default `[]` in `scene_record`); `exported_message`/`how_to_open_message`/
   `launch_failed_message` take `skipped`, text "N lines could not be prepared: a, b, c, and K more";
   plugin shows it at Warning level. Tests: `test_lines_that_fail_to_prepare_are_skipped_named_and_recorded`
   (a corrupted DZT, real engine failure), `test_a_clean_export_skips_nothing`,
   `test_skipped_lines_are_named_in_the_message`, pure `test_skipped_lines_are_named_with_a_count_when_many`,
   `test_skipped_lines_are_recorded_in_the_scene_record`.
6. `export_paraview` refuses with the GeoTIFF wording while `running_export()` is set.
   Test `test_the_button_refuses_while_a_geotiff_export_runs` (no dialog opens).
7. Pick count cached per grid on the `ParaViewExport`; the path field calls `_update_buttons` only
   (`_can_export` remembered). Tests `test_summary_counts_a_grids_picks_once_however_often_it_is_asked`,
   `test_edits_read_each_lines_picks_once_and_a_path_edit_recomputes_nothing`.
8. The four guard tests moved to `synth_site` (no `needs_real_data`). They pass with the real-data lists
   emptied (runner patching `tests.real_data`): `19 passed, 11 skipped` in test_plugin_paraview_export.py,
   the 11 skips being other real-data tests.
9. Guide: "wave period" added to the quick re-export line.
10. `open_scene.py.txt`: when `n_picks == 0` sets `ColorArrayName`/`LookupTable` instead of `ColorBy`.
    pvpython test is parametrized on 0 and 3 picks and asserts no `WARN|`/`ERR|` in stderr and no
    `open_scene:` in stdout. Passes with both; fails with the old code (mutation).

## Mutation checks (PYTHONDONTWRITEBYTECODE=1, restored; script in scratchpad)
15 mutants (each refusal removed, unlink unsuppressed, sweep removed/unscoped, VolumeStopped branch,
swap message, skipped tracking, pick cache, path-edit refresh, dialog disable, launch cwd, env var,
GeoTIFF refusal, zero-picks ColorBy): all KILLED by the named tests.

## Commands and output
- ruff check .: All checks passed!; ruff format --check .: 231 files already formatted;
  mypy (constraints command): Success: no issues found in 53 source files
- pure, NSGEO_PVPYTHON set: 326 passed, 1 skipped
- core: 1226 passed, 4 skipped
- QGIS (paraview_export, paraview_dialog, plugin_loads, site_engine, slices_engine, slices_dock): 370 passed

## Decisions and notes
- Dialog hard limit and run refusal use the same two rules. The export margin is smaller than the fill
  margin (10% of export, 50..250 MB) so a "merely tight" band (under files + fill + 0.5 GB) still exists;
  the brief did not fix the export margin.
- Old test "a short disk warns ... but still exports" asserted the previous behaviour and was rewritten.
- test_plugin_paraview_dialog.py exits with a segfault (rc 139) at interpreter shutdown after all tests pass
  when any test builds a parentless dialog through `_make_dialog`; reproduced on the existing
  `test_editing_the_cell_refreshes_the_size` alone, so it predates this work. In the multi-file run rc was 0.
