# Real-data memory check — milestone B export (#108)

**Goal:** measure what the whole-site export really holds on the author's real ten-grid site at a
0.025 m cell with a 0.0125 m pixel, and compare it with `estimate_export`. The dialog lets that
setting through on this site (the estimate is under the 1.5 GB budget, `EXPORT_BUDGET_BYTES`), but
the estimate has only been checked against the synthetic bench
(`packages/nsgeo-qgis/scripts/bench_site.py --export`, ten 20 m grids). This is a measurement, not
a code change: nothing is committed.

Worktree: `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-fine-cells-export`
(branch `nsgeo-fine-cells-export`). Read `global-constraints.md` in this folder.

## The data (read-only)

- The site's session folder is `<the site copy>/` (`survey.nsgeo.json`,
  `site.nsgeo.gpkg`). Its lines are DZT files under `/mnt/DataStorage/...` (absolute paths in the
  json). **Never write into either location.** Copy `survey.nsgeo.json` and `site.nsgeo.gpkg` (and
  any `-wal`/`-shm` beside it) into a fresh folder under the scratchpad
  `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/0356759e-44aa-46ca-bfe2-a82acefa658a/scratchpad/realdata-mem/`
  and open only the copy.
- The site's exported file `<the site copy>/slices/site.tif` (read it with
  GDAL, read-only) records the 17 band windows the author used (`NSGEO_WINDOW_NS` / band metadata)
  and the per-grid normalisation factors; use those windows.
- The json's `site_view` gives the site's grids (all ten), transform, normalisation and
  interpolation method; `presets` / `slice_sources` give each grid's preset.

## What to run

1. Find how the plugin opens a session and builds the Whole site engine headlessly — the real-data
   tests (`packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`, `test_plugin_slices_engine.py`,
   `tests/plugin_testing.py`) and `scripts/bench_site.py` show the pieces. Build the `SiteEngine`
   (or what the export needs) for the copy with the site_view settings, then
   `site_export.site_export_spec(...)` at (cell 0.025, pixel 0.0125), the json's method and the
   panel's finish, with the 17 windows. Do the same at (0.025, 0.025) as a sanity point.
2. For each: print `estimate_export(spec)` (`held_bytes` and `per_band` parts) and the dialog's
   `held_bytes` if it goes through another path (`slices_plan`/`export_flow` preview).
3. Run `export_pipeline.run_export(spec, should_stop=lambda: False, progress=...)` for the first 3
   bands (consume the generator, then close it) under `tracemalloc`, started after the lines are
   prepared, exactly as `bench_site.py --export` measures (prepared lines excluded: the live
   engines hold them). Also record the process's RSS high-water mark
   (`resource.getrusage(RUSAGE_SELF).ru_maxrss`) before and after as a cross-check, and the time of
   band 0 and of later bands.
4. Run offscreen with the QGIS venv:
   `PYTHONPATH=packages/nsgeo-core/src:packages/nsgeo-qgis QT_QPA_PLATFORM=offscreen /home/jameszd/Documents/Github/archaeo_geophysics/.venv-qgis/bin/python <script>`.
   Keep the script in the scratchpad folder above, not in the repo.
5. Before starting, check `free -m`: if less than 5 GB is available, stop and report BLOCKED
   (the machine has 15.5 GB and a full 2 GB swap; the author's QGIS may be open).

## Report

Write `real-data-memory-report.md` in this folder: the settings used, the estimate (total and
parts) against the measured tracemalloc peak and RSS, for both settings; per-band times; whether
the estimate is at or above the measured peak (it must be: the budget refuses on the estimate);
and anything that differs from the bench. **No site names in anything you write outside this
folder or the scratchpad.** Return only: status, the two estimate-vs-peak pairs, and concerns.
Never dispatch subagents. Never change permissions or settings files.
