# Post-walkthrough fix round — milestone B (#108)

Branch `nsgeo-fine-cells-export`, worktree
`/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-fine-cells-export`.
Milestone B (the background GeoTIFF export with its own cell and pixel) is built and the author has
walked it through. This round fixes what the walkthrough found plus the minors parked by the last
review. Read `global-constraints.md` in this folder first: it binds every item here.

## Item 1 — the Temporal Controller steps one band at a time after an export (main item)

**What the author hit:** "I haven't had luck with the temporal controller. It seems like it isn't
set up quite right somehow."

**Root cause (verified headlessly on QGIS 3.44.7):** exported layers map 1 ns to 1 s from the
1970 epoch (`slice_export.band_time_range`) and use `Qgis.RasterTemporalMode.FixedRangePerBand`
(`apply_band_windows`). A 17-band file spans about 45 s. QGIS's Temporal Controller starts with
navigation off and a 1-hour frame, so even when switched on there is one frame covering every band
and it always shows the last band. With the frame set to the band step (e.g. 5 s) frames 0,1,2 show
bands 1,2,3. Probe script:
`/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/0356759e-44aa-46ca-bfe2-a82acefa658a/scratchpad/temporal_probe.py`.
This predates milestone B (M11's This-grid export works the same way); the guide never mentions it.

**Build:**

1. A helper in `slice_export.py`, beside `apply_band_windows`:
   `fit_temporal_navigation(navigation: QgsTemporalNavigationObject, layer: QgsRasterLayer) -> bool`.
   It reads the layer's `temporalProperties().fixedRangePerBand()`; returns False (touching
   nothing) when the layer is not in `FixedRangePerBand` mode or has no ranges. Otherwise:
   - extent = earliest band begin → latest band end;
   - frame duration = the smallest positive gap between consecutive band begins (sorted); with one
     band, that band's length; never below 1 ms;
   - navigation mode Animated (`Qgis.TemporalNavigationMode.Animated`), `setTemporalExtents`,
     `setFrameDuration(QgsInterval(seconds, Qgis.TemporalUnit.Seconds))`, current frame 0;
   - also the project's time settings (`QgsProject.instance().timeSettings()`: temporal range,
     time step and unit) so a saved project reopens set up — only where the API exists on both
     QGIS 3.40+ and 4.x (CI runs 3.44 and 4.2); if one of those calls is missing on either, skip
     it and say so in the report.
   Returns True when it set the controller.
2. **Where it runs:** in `plugin.py`, after a values layer with a time axis is added by an export
   (`_add_export_layer`, after `temporal(layer)`; both This grid and Whole site; also the
   half-written path, which goes through the same helper), and after `_restore_layers` puts back a
   layer whose `restore_band_times` returned `"set"`. The navigation object is
   `self.iface.mapCanvas().temporalController()`; when that is not a `QgsTemporalNavigationObject`
   (a test stub, or no canvas) skip quietly. It runs inside a task's `finished()` path, where
   exceptions vanish: wrap it so a failure is logged to the QGIS log ("nsgeo", Warning) and never
   stops the layer from being added or the message from being shown.
3. **Ruling (controller already in use):** fit it on every export or restore of a timed layer,
   overriding whatever was there. A GPR project has no other temporal layers, and the user has just
   made this file. Cost if wrong: a user with another temporal layer re-sets the controller by hand.
4. **Bands that don't abut.** The site export's windows come from `plan_windows(site_z,
   thickness_levels, step_levels)`, so step and thickness can differ: overlapping windows (step <
   thickness), gaps (step > thickness), and abutting ones, on the native dz (0.2165 ns) grid.
   Pin with tests, using QGIS's own `temporalProperties().bandForTemporalRange(layer,
   navigation.dateTimeRangeForFrameNumber(k))`, that frame k shows band k+1 for every band, frame
   count == band count, in all three cases. If QGIS's choice for overlapping windows does not give
   one-to-one stepping with this frame rule, find the rule that does (e.g. offset the extent) and
   say what you found in the report — do not paper over it.
5. **Tests:** helper tests on a real small GeoTIFF (`tmp_path`) and a real
   `QgsTemporalNavigationObject` for the three window cases plus one band, plus the "not
   FixedRangePerBand → False, untouched" case. A plugin-level test that an export (site and This
   grid, following the existing export tests in `tests/qgis/test_plugin_export_*.py` /
   `test_plugin*.py`) leaves the canvas's navigation object fitted — find how existing plugin tests
   reach `iface`; if the test iface has no real canvas controller, inject one the way those tests
   inject other collaborators. A restore test (cancelled replace puts the layer back and fits).
6. **Guide** (`docs/guide/getting-started.md`, the export part of Step 7, around lines 500–550):
   a short paragraph "Stepping through depths": after an export nsgeo sets QGIS's Temporal
   Controller up for the new file, one band per step; open it with View → Panels → Temporal
   Controller (or its clock button); the times it shows are nanoseconds written as seconds after
   midnight on 1 January 1970 (00:00:05 is 5 ns); for a file added by hand in another project, set
   it up the same way: animated mode, "Set to full range" from the layers, and a step equal to the
   band step in seconds. Keep the guide's plain style (short sentences, no jargon, bold UI names).

## Item 2 — the dialog always shows the memory the export needs

**What the author hit:** the walkthrough quoted bench numbers; the dialog's only figure was the
File size, so a fitting export looked like a missed refusal. Add a **Memory** row to
`slices_plan.summary_lines`, just before File:
`f"about {format_bytes(preview.held_bytes)} of the {format_bytes(EXPORT_BUDGET_BYTES)} allowed"`.
Keep it when over budget too (the refusal text stays as it is). Update the tests that pin the rows
(`tests/pure/test_pure_slices_plan.py`, the dialog tests) and the guide's sentence about what the
box lists, if it lists rows.

## Item 3 — parked minors from the final review

1. `export_task.py` / `slice_export.commit_partial`: set the values-written flag right after the
   values file's `os.replace`, and make the `.aux.xml`/`.ovr` unlinks best-effort (an unlink error
   is logged, not turned into a failed export). Test: an unlink that raises after the replace still
   gives `ok=True` (or the half-written path, as the code's states require) and the new file.
2. `restore_band_times`: a coverage companion written before this branch has no `largest_count`
   key and is wrongly treated as timed. Also treat a file named by the companion rule
   (`coverage_path`'s `<stem>_coverage.tif`) as counts. Test it.
3. `ExportCancelled` docstring (`export_pipeline.py` ~line 104): say exactly what raises it now
   (check the code).
4. The half-written message's ".;" punctuation (`plugin.py`, `_finish_half_written` and the
   style notes it joins): fix so no ".;" or ". ." can appear; pin with the existing test.
5. `packages/nsgeo-qgis/scripts/bench_site.py` docstring says "no smoothing" beside the
   `--export-smooth` re-run: make it true.
6. `plugin.py` ~line 1084, the comment "The cell the picture is drawn at (the box can show one a
   refused resolution left)." — rewrite plainly (the site's own lattice pixel, not the Cell size
   box, which can still show a value a refused resolution left behind).
7. `site_export.py` module docstring says `NSGEO_SITE_RESAMPLING` is always `bilinear`; it is
   `largest_count` for the coverage companion.
8. A plugin-level test of the "without the time slider" restore message (`plugin.py` ~1441–1483).

## Rules

- No site names anywhere (code, tests, docs, commits). The repo is public.
- Commit in small commits, messages ending with the line
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; push each to origin as you go
  (a "Could not resolve host" push failure is transient: retry).
- Run before reporting (`R=/home/jameszd/Documents/Github/archaeo_geophysics`, from the worktree):
  - pure + core: `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q -p no:xonsh -p no:cacheprovider`
  - QGIS: `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh -p no:cacheprovider`
  - lint and CI's mypy line exactly as `.github/workflows/ci.yml` runs them.
  (Check the test paths above against the repo; adjust if they differ and say so.)
- Never dispatch subagents. Do not edit anything under `.superpowers/` except your report.
- Do not touch the README or the spec (already updated this round).

## Report

Write the full report to `walkthrough-fix-report.md` in this folder: per item what changed, the
tests added, the Temporal Controller findings (item 1.4, and whether the Temporal Controller panel
follows a programmatic change on 3.44 if you could tell), any API missing on 3.40/4.x, and test
counts. Return only: status (DONE / DONE_WITH_CONCERNS / BLOCKED), commit hashes, a one-line test
summary, and concerns.
