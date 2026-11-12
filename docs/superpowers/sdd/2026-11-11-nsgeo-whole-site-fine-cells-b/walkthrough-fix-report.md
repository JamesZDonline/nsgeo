# Post-walkthrough fix round: report

## Item 1: Temporal Controller

- `slice_export.fit_temporal_navigation(navigation, layer) -> bool`, beside `apply_band_windows`.
  Returns False and touches nothing for a layer not in `FixedRangePerBand` or with no ranges.
  Otherwise: Animated mode, extent, frame duration (smallest positive gap between band starts;
  one band: its length; at least 1 ms), current frame 0, and the project's time settings
  (`timeSettings().setTemporalRange / setTimeStep / setTimeStepUnit`).
- **Finding (1.4):** the brief's extent rule (first begin to last end) does NOT give one frame per
  band. QGIS counts frames as `floor(extent / frame) + 1`. Abutting windows gave n+1 frames, and
  overlapping windows gave n+2 (the last band showed for the spare frames). The bands' starts are
  rounded to the millisecond (0.2165 ns x 5 = 1082.5 ms), so they drift off a whole number of
  frames too. The rule that works for all three cases: the extent ends one millisecond short of
  `n_bands * frame` after the first start (`begins[0] + n * frame_ms - 1`). Frame k then shows
  band k+1 for every band, frame count == band count, for abutting, overlapping and gapped
  windows (and with 5 ns steps). Pinned by tests that use `bandForTemporalRange` with
  `dateTimeRangeForFrameNumber`.
  Consequence: the extent is NOT the layer's full range, so the guide's hand setup ("Set to full
  range") gives a controller with up to two spare final frames for overlapping bands (they show
  the last band). Harmless; the guide paragraph does not promise otherwise.
- Plugin: `_fit_temporal_controller(layer)` in `plugin.py`, called after `temporal(layer)` in
  `_add_export_layer` (so This grid, Whole site and the half-written path) and in
  `_restore_layers` when `restore_band_times` returns `"set"`. Skips quietly when the canvas's
  `temporalController()` is not a `QgsTemporalNavigationObject`; any exception is logged to
  "nsgeo" at Warning and never stops the layer or the message. Fits on every export or restore
  (override ruling).
- API availability: `Qgis.TemporalNavigationMode.Animated`, `QgsTemporalNavigationObject.setNavigationMode /
  setTemporalExtents / setFrameDuration / setCurrentFrameNumber`, `QgsProjectTimeSettings.setTemporalRange /
  setTimeStep / setTimeStepUnit`, `Qgis.TemporalUnit.Seconds` all exist on 3.44.7 (verified). I could
  not run 4.2 here; I used no call the brief called out as doubtful, and nothing was skipped. If one of
  the three time-settings setters is missing on 4.x, CI will say so.
- Whether the Temporal Controller panel follows a programmatic change: could not tell headlessly
  (no panel in the offscreen test iface, only the navigation object). The object signals its
  changes (`temporalExtentsChanged`, `temporalFrameDurationChanged`), which the panel widget
  listens to, but this was not observed.
- Tests: `tests/qgis/test_plugin_temporal_navigation.py` (10: six window cases, one band, project
  settings, not-FixedRangePerBand, no ranges); in `test_plugin_slice_export_dialogs.py`: export fits,
  cancelled replace fits the restored layer, a failing fit does not stop the layer (logged), a canvas
  without a navigation object is skipped quietly; in `test_plugin_site_scope.py`: Whole site export
  fits. In the test iface the canvas has no controller; tests install a
  `QgsTemporalNavigationObject(canvas)` (parented, as an unparented one segfaulted at teardown).
- Guide: "Stepping through depths" paragraph in Step 7.

## Item 2: Memory row

`slices_plan.summary_lines` adds `("Memory", "about X of the Y allowed")` before File, kept when over
budget. Pure tests (exact rows, over-budget row) and the dialog tests updated; the guide's sentence
about the box now lists it.

## Item 3

1. `export_task`: values file now goes through `replace_partial`, the flag is set, then
   `drop_stale_files` (best effort: an `OSError` is logged to "nsgeo" at Warning). `commit_partial`
   stays as the two composed (used for the companion). Tests: stale-file unlink raising gives ok;
   unlink raising then companion failing still reports values_written; direct `commit_partial` logs
   rather than raises.
2. `restore_band_times`: a file whose stem ends `_coverage` is counts (also when the tag is absent).
   Two tests (old tagged-`bilinear` companion is counts; a plain file with no windows stays missing).
3. `ExportCancelled` docstring lists the real raisers (`run_export` check sites,
   `build_overviews`, `ExportTask.run` before the commit); the writers do not raise it.
4. Half-written message: restore note now comes before the style notes, which go last as whole
   sentences. New test with a style-file failure; `_assert_no_stray_punctuation` added to the old one.
5. `bench_site.py` docstring: "no smoothing" now says `--export-smooth` re-runs the export rows with it.
6. Comment in `plugin.py` rewritten.
7. `site_export.py` module docstring fixed.
8. Test: a cancelled replace whose old file has no window metadata says "cube is back without
   the time slider setting" (already passing; pins existing behaviour).

## Checks
QGIS tier (3.44.7): 1782 passed. Pure + core: 1265 passed, 5 skipped. Ruff
check/format and the CI mypy line (CI's list includes `line_edit.py` and `export_pipeline.py`;
the brief's copy of it did not): clean.
