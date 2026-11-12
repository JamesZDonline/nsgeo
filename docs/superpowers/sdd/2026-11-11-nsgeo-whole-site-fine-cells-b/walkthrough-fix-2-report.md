# Fix round 2: report

Commits (all pushed): ae6bf88 (CI/pytest 9.2), then in order: the flag-order test and M2; the mean-step
frame; the add hook and refit after open; the sweep-layer teardown fix. (`git log 8862ded..` has the
hashes.)

## R31 CI (pytest 9.2)
`tests/pure/test_pure_export_pipeline.py`: `band.factors == approx(factors)` and the `!=` check used
nested dicts. Now compared through `_flat` (sorted keys, then flat floats). No other nested `approx`
on the branch (grepped the diff). Confirmed in a throwaway venv under the scratchpad
(`p92/v`, pytest 9.2.0, project venvs untouched): pure + core 1265 passed, 5 skipped.

## R26 frame rule (I1, M1, M3)
`fit_temporal_navigation`: frame = mean step `(last_begin - first_begin) / (n - 1)` ms (float), one
band: its length floored at 1 s; extent starts 2 ms before the first begin and ends at
`start + floor(n * frame) - 1`. Comment now says QGIS counts `ceil(extent / frame)`.
Sweep: 3 band counts (17, 200, 460) x 3 dz (0.0244, 0.0977, 0.2165) x 4 first begins (0, -1.8,
2.0, -11.09) x 5 step/thickness cases (one-level thick, one-level step, abut, overlap, gap) = 180
cases, asserting count == n and frame k -> band k+1 for all k; plus a single zero-length band. Runs
in about 2 s. Seen failing (53) before the rule changed. Layers are shared in a module fixture and
released before exit (see CI below).

## R27 band times from the file (I2, I3)
- `plugin._on_layers_added` on `QgsProject.layersAdded` (connected in `initGui`, disconnected in
  `unload`): only `gdal` raster layers on an existing local `.tif`/`.tiff`; `restore_band_times`
  (one GDAL metadata read); on "set" it remembers the layer and fits the controller. Every failure is
  logged ("nsgeo", Warning) and swallowed. Counts files and files without windows are left alone.
- Export and restore paths keep their direct calls (they need the "untimed" accounting and the plan's
  own windows); the hook then runs a second, identical wire-and-fit. Chosen over removing the direct
  calls because the second pass changes nothing and the direct path is already tested.
- `QgsProject.readProject` -> `QTimer.singleShot(0, _refit_after_open)`, which fits to the last
  nsgeo-timed layer still in the project (`cleared` forgets them).
- **Real-app verification** (QGIS 3.44.7, offscreen, `qgis --profiles-path <scratch>/app2/profiles
  --profile probe --noplugins --code probe_reopen.py`, `PYTHONPATH` to the worktree; script:
  `scratchpad/app2/probe_reopen.py`). The plugin is constructed with the real iface
  (`classFactory(iface).initGui()`). For a 17-band file (dz 0.2165, step 5 levels) and a 200-band file
  (dz 0.0977, step 1 level): add the file with no band times set -> save the project -> clear -> read.
  Result, after the add and after the read (immediately and after settling): controller mode
  Animated, frame count == n, frames 0..n-1 -> bands 1..n. A variant with the readProject
  connection removed (`probe_norefit.py`): after the read the mode is Disabled and the bands are
  wrong, so the refit is what makes it stick. Not checked: the plugin in a full interactive session
  with the actual panel visible beyond what the offscreen app creates (the panel object exists in the
  offscreen app and follows, as the reviewer found).
- Project time-settings setters: dropped. QGIS saves them at whole seconds and the panel restores
  from its own entries, so they did nothing useful. The "saved project reopens set up" claim is gone
  from the docstring; it is true now only through the mechanism above, verified as described.
- Tests: `tests/qgis/test_plugin_band_times_on_add.py` (7): hand-added file timed and fitted; no
  windows left alone; counts left alone; non-tif / non-gdal not read; failure logged and layer still
  added; unloaded plugin does not react; save/clear/read refits (in the test iface with a bare
  navigation object).
- No-canvas nit: `mapCanvas()` of None is skipped quietly.

## R28 guide
"Stepping through depths" rewritten: works with nsgeo installed however the file is added (export,
reopened project, Add Raster Layer); replaces the controller's settings; times are ns as seconds
after midnight 1 January 1970, times before 0 ns show as the last seconds of 31 December 1969
(-1.8 ns is 23:59:58); without nsgeo the file has no time setting, so use the layer's band choice
in **Symbology** or another GIS's band list. The hand-set-up sentence (I3) is gone.

## R29 (M2)
The companion-by-name rule applies only when the file has neither `NSGEO_INTERPOLATION` nor
`NSGEO_SITE_INTERPOLATION`; the `largest_count` tag check stays first. New test: a windowed values
file named `full_coverage.tif` is "set". Old-companion test kept.

## R30 (M5)
The test monkeypatches `export_task.drop_stale_files` to raise and asserts
`not result.ok and result.values_written`. Checked it fails with the two lines swapped (flag False)
and passes after reverting (`PYTHONDONTWRITEBYTECODE=1`; `git diff` of the source clean).

## Also
Bench docstring: `--export-smooth` sets the export rows' smoothing.

## CI
- After the pytest fix the pure jobs are green on every OS and Python.
- plugin-qgis 3.44 failed twice with a segfault at interpreter exit after all tests passed; cause:
  the sweep's module-level cache of `QgsRasterLayer`s outlived `exitQgis()`. Fixed with a module
  fixture that releases them (commit "test: release the sweep's layers before the application exits").
- The next 3.44 run then failed on `test_plugin_refine.py::test_the_gui_thread_keeps_running_during_a_solve`
  ("the solve is too quick to tell anything"), a timing test in code this branch does not touch
  (same family as the intermittent timing failures #165/#166). I re-ran the failed job and it passed: CI on the branch head is green (all jobs).
- Local: pure + core 1265 passed, 5 skipped; QGIS tier 1970 passed (3.44.7); ruff, ruff format and
  the CI mypy line clean.

## Round 3
- N1: `test_the_refit_after_a_read_beats_a_panel_that_reads_after_the_layers` (a `readProject` slot
  connected after the plugin's switches the controller off, as the panel does) plus
  `test_an_unloaded_plugin_does_not_refit_after_a_read`. Checked with the `readProject` connection in
  `initGui` replaced by `pass` (`PYTHONDONTWRITEBYTECODE=1`): the first test fails (Disabled !=
  Animated); restored from a backup copy before committing.
- N2 part 1: `initGui` runs `_on_layers_added` over the layers already in the project (it fits to
  the last timed one). Test: a windowed file added before the plugin starts is timed and the
  controller fitted after `initGui`.
- N2 part 2 / N3: the guide says "installed and enabled", mentions layers already in the project,
  and says a project saved with nsgeo and opened without it steps unreliably (whole-second band
  times), so use the **Symbology** band choice there too. The repair claim was checked first, by a
  test: after Change Data Source (`setDataSource`) the layer is not wired (hook does not run), and
  after save and reopen it is (`test_a_repaired_layer_is_timed_when_the_project_is_next_opened`);
  remove and add again is the hand-add test. I did not add a `dataSourceChanged` hook (the
  controller's instruction was to document, not extend).
- Nits: two docstrings updated (`restore_band_times`, `_fit_temporal_controller`). Not done: the
  unloaded-timer check, the 2 ms lead pin, pruning `_timed_layer_ids`.
- Tests: targeted QGIS files 254 passed; pure + core 1265 passed, 5 skipped. CI: the first commit
  failed lint on one over-long docstring line (my slip); fixed in the next commit, and CI on the
  branch head is green (all jobs).
