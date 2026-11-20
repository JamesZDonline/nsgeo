# Task 4 report: walls in the export and the scene

## Implemented
- slices_plan.walls_size(nz, line_traces, cut_lengths, cell) -> (n_walls, bytes); pure; uses wall_columns + structured_grid_bytes; a wall under 2 columns or a non-finite cut length counts 0 (R13).
- paraview_scene: scene_record `walls` (default [], validated: keys, 0.. order, kind line|cut, file walls/<index>.vts); ExportSummary n_walls, walls_bytes (default 0); the "Also" row says "34 walls, about 76 MB" after picks and lines (no new dialog row: the dialog's row table is fixed, and widgets are out of the file list).
- paraview_export: estimate/summary/run-refusal add the walls' bytes (same rule via _walls_size); announce counts walls into the progress total; _write_walls writes walls/<n>.vts (lines in key order, then cuts in cuts-list order, index contiguous over written walls), amplitude array, z = -depth*stretch, cut_wall reads the memmapped cube level by level; ValueError/OverflowError -> one _log line, wall skipped (still one progress step).
- open_scene.py.txt: XMLStructuredGridReader per INFO["walls"], "Wall: "/"Cut: " + name as data, ColorBy amplitude, hidden; amp_lut still set last. README.md.txt and docs/guide getting-started table: the Walls line.
- Core public API (not in the brief, forced by tests/pure/test_plugin_boundary.py): nsgeo.slices now exports cut_wall, line_wall, wall_columns, wall_points; core README rows added (test_public_api demands them). The plugin imports from nsgeo.slices.
- Core test: test_a_long_cut_wall_is_capped_at_300_columns (carried from Task 3 review).

## TDD
- RED (pure): test_pure_volume_choice collection ImportError "cannot import name 'walls_size'"; test_paraview_scene: 2 failed (TypeError unexpected keyword n_walls; no `walls` key) before the scene code.
- RED (QGIS): with paraview_export.py reset to HEAD: 4 failed, 1 passed (`-k wall`): walls list [] vs 5 expected, n_walls 0 vs 5/3, no walls dir. The cancel test passes on HEAD only vacuously (the last step there is a slab, still cancels cleanly); its value is the walls case.
- Core cap test passes on first run (pins existing behaviour; no RED possible).
- GREEN: `-k wall` 5 passed, with NSGEO_PVPYTHON set.

## Measured size
test_the_stated_size...: written folder total 12,271,618 B vs stated export_bytes 12,255,288 (walls_bytes 9,050,912): -0.13%, within 2%. Real DZT, 4 lines + 1 cut. Refusal test: free space = cube-only need + walls/2 refuses; need(all)+1 writes.

## pvpython
test_wall_files_are_named_by_index_and_the_scene_opens RAN (not skipped) with NSGEO_PVPYTHON=.../ParaView-6.2.1.../pvpython: in the 144-passed run (-rs printed no skips). Cut named `a "quoted"/cut é` registered as "Cut: ..." and hidden; "Wall: <stem>" for lines.

## Test runs
- test_plugin_paraview_export + test_plugin_scene3d + test_plugin_surface_build: 144 passed, 0 skipped (pvpython set).
- qgis_tests.sh ... -m real_data: 47 passed.
- core+pure: 1976 passed, 1 failed (test_plugin_boundary: plugin imported nsgeo.slices.walls), fixed by exporting; then re-ran pure+public_api+walls tests (403 passed, README test fixed after), boundary+public_api 22 passed, and the export wall tests again (5 passed, pvpython one skipped as env unset in that quick run).
- ruff check, ruff format --check, mypy (CI command) clean. Whole QGIS tier not run (R1).

## Stale tests updated
test_plugin_paraview_export: two folder file-list pins gained "walls"; six `{p.name: p.read_bytes() for p in folder.iterdir()}` snapshots (would fail on the walls dir) now use a recursive _snapshot helper; the first-export test's size check compares estimate with the whole folder (estimate now includes walls), not cube.vti.

## Self-review
- Cancel: step() raises inside the try; partial removed (test asserts no .partial and previous export byte-identical, walls included). No second cube copy: cut_wall samples the memmap per level, line_wall uses prepared data.
- Concern: wall levels are z.nz (all cube levels, including any before time zero), per the brief, while cube.vti has nd levels from time zero; row z follows -depth(t)*stretch, so levels before zero stand above ground. Matches brief; walkthrough should look.
- Concern: estimate counts all source lines, run counts prepared ones; a skipped line makes the stated size slightly high (upper bound).
- Concern: Task 3 had not exported the wall API from nsgeo.slices; added here.

## Files
docs/guide/getting-started.md; packages/nsgeo-core/README.md; packages/nsgeo-core/src/nsgeo/slices/__init__.py; packages/nsgeo-core/tests/test_slices_walls.py; packages/nsgeo-qgis/nsgeo_qgis/{paraview_export,paraview_scene,slices_plan}.py; nsgeo_qgis/paraview/{open_scene.py.txt,README.md.txt}; tests/pure/{test_paraview_scene,test_pure_volume_choice}.py; tests/qgis/test_plugin_paraview_export.py

## Fix round 1

### Changes
- C1 (core): `nsgeo.slices.walls.wall_amplitude(wall, window, *, squared, first=0)` puts a wall on the volume's amplitude scale by calling the volume's own `_rms_levels` (same window arithmetic and edge padding) down each column, then sqrt; no sideways blur; NaN stays NaN; squares first unless `squared`. The export passes squared=True for cut walls, `prov.transform == SQUARED_TRANSFORM` for line walls, and the same `window` the volume uses. `SQUARED_TRANSFORM` and the new functions are exported from `nsgeo.slices` (plugin-boundary rule) and listed in the core README.
- I2: walls are built on exactly the levels cube.vti keeps. first = z.nz - nd; the amplitude window is applied on ALL levels and then rows [first:] are kept (so the top rows equal what the cube computes with its pre-zero levels as context); depths use depth[first:]; estimate, summary and run size walls with nd. Deviation from the brief's wording: cut walls sample the full `filled` and slice after the window, instead of `filled[first:]`, because the cube's window looks at the levels before time zero. The sampled array is (nz, n), not a copy of the cube.
- M8: `cut_wall_columns(path, cell)` is the one column rule, used by `cut_wall` and by `walls_size` (which now takes the cuts' paths, not lengths); `_cut_lengths` became `_cut_paths`.
- I3: write-pass cancel test cancels at done >= total - n_walls - 1 and asserts .partial exists and .partial/walls does not.
- M4: the no-walls test records the walls listing at the cancel and asserts 0..3.vts.
- M5: cube.vti size within 5% of export_size_bytes(nx, ny, nd) kept beside the whole-folder check.
- M7: skipped-line test asserts the walls are exactly the prepared line's.

### RED / GREEN
- RED (before the export used wall_amplitude and nd; shown on the same new tests): test_walls_are_on_the_cubes_amplitude_scale[amp_square]: line wall median 1.27e7 vs cube 4.0e3 (assert 12739840 <= 8054); [amp_envelope]: cut wall median 2.35e7 vs 5.2e3; test_walls_stand_on_the_levels_the_cube_has_with_no_time_zero: "assert 512 == 460" (wall had z.nz rows, cube nd).
- Core tests (test_a_wall_is_put_on_the_volumes_amplitude_scale etc.) were written beside the new function, so they have no separate RED.
- I3, M4, M5, M7 are test tightenings: they pass on the code; the review's probe showed I3's old rule cancelled at (490, 491) with walls/0 and walls/1 already in .partial, which the new assertion on `.partial/walls` would catch.
- GREEN: `-k "amplitude_scale or no_time_zero or write_pass or no_walls or fail_to_prepare or writes_the_folder or wall"`: 10 passed, 1 skipped (pvpython unset in that run).

### Measured (real DZT, 4 lines + 1 cut, cell 0.25 m)
Cube median / share above amplitude_range top (cube: 1.00%):
- amp_square, before: cube 4.0e3; line walls ~1.3e7, 76-80% above; cut wall ~2.3e7, 100% above.
- amp_square, after: line walls 3.7e3-4.4e3, 1.0-1.6% above; cut wall 3.8e3, 1.4% above.
- amp_envelope, before: line walls ~5.7e3 (about right), cut wall 2.3e7 (squared), 100% above.
- amp_envelope, after (cube 5.2e3): line walls 5.3e3-6.3e3, 1.3-2.0% above; cut wall 4.9e3, 1.6% above.
Test tolerances: medians within 2x of the cube's; above-range share under 3% (the walls are not blurred sideways, so a little more than the cube's 1%; measured max 2.0%); a line wall and the cut agree within 2x under both transforms.
I2 no-time-zero: walls now have nd rows, z max <= 0, top and bottom equal the cube's.

### Verification
- test_slices_walls + public_api + pure volume-choice: 41 passed (core, before the export changes).
- test_plugin_paraview_export + test_plugin_scene3d with NSGEO_PVPYTHON set: 103 passed, no skips (the pvpython scene test ran).
- `qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data`: 50 passed.
- WHOLE core+pure: 1980 passed, 9 skipped, 19 xfailed.
- ruff check, ruff format --check, CI mypy (spot run: nsgeo + slices_plan): clean.
- Not fixed, per the coordinator: M6 (sorted-key order, R16), M9.

## Fix round 2

- Stale pin: test_plugin_paraview_dialog.py::test_the_dialog_lists_what_will_be_written expected "0 picks, 3 lines". It now builds the same `ParaViewExport.summary` the dialog reads, asserts n_walls == 3 and walls_bytes > 0, and pins the exact text `0 picks, 3 lines, 3 walls, about <format_bytes(walls_bytes)>`.
- No-walls case: the pure test test_summary_rows_name_the_walls_and_their_size already pins "1 pick, 4 lines" with n_walls=0; a dialog fixture with no walls would need a site with no lines, so not duplicated here.
- Grep of every test for `also_label`, `summary_rows`, `ExportSummary`: the other hits (test_plugin_export_dialog, test_plugin_slice_export_dialogs, test_plugin_site_scope) are the GeoTIFF export dialog's own, unrelated `summary_rows` ("Bands", "Grids", ...); test_plugin_paraview_export and test_paraview_scene already pass with the new text.
- Commands: `qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_dialog.py` -> 36 passed; ruff check clean; ruff format --check: 276 files already formatted.
