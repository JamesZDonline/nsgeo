## Global Constraints

- **Running tests.** Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.
  `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - Core and pure: `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`.
  - QGIS: `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`.
- **Lint as CI does:** `ruff check .`, `ruff format --check .` (line length 100), and the CI mypy line:
  `$R/.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`.
- **Imports and dependencies.** The core is numpy only. The plugin imports the core only through
  `nsgeo.slices` (`test_plugin_boundary.py`). Every public core name has a row in
  `packages/nsgeo-core/README.md` (`test_public_api.py`).
- **The cube interface (decision 5).** Read cubes only through `SliceCube.slice_levels()` and
  `coverage()`. Size memory only through `estimate_memory(prepared_samples, n_cells, nz, n_covered)`
  with `n_covered = covered_cells(frame, coords)`. Never read `cube.mean`.
- **Thread rules for the export** (the task's `run()` and everything it calls):
  - **Never** call a live `SliceEngine` or `SiteEngine` method; they rewrite caches on every draw.
  - **Never** read the session.
  - **Never** use `warnings.catch_warnings()`; it is process-global and not thread-safe, and
    `SliceLayer._write` uses it on the GUI thread. Silence GDAL's one-time FutureWarning once, at
    import.
  - **Never** use `to_north_up`'s shared `lru_cache`. Build taps directly.
  - **Never** create Qt widgets or layers.
  - A grid in another CRS gets its own `QgsCoordinateTransform`, built inside `run()` from authids
    plus a copied `QgsCoordinateTransformContext` that is snapshotted on the GUI thread.
- **QgsTask traps** (`slices_engine.py:18-111` and the environment-facts memory):
  - keep a strong reference to the task until it ends;
  - handle `addTask()` returning 0;
  - `finished()` guards its whole body, because `QgsTaskWrapper` swallows exceptions silently;
  - cancelling a task still queued runs `finished(False)` synchronously.
- **One export at a time.** A second Export while one runs is refused with a plain message.
- **The write path (spec §6.3).**
  - float32, NaN nodata, DEFLATE with PREDICTOR=3, band-interleaved, `BIGTIFF=IF_SAFER`.
  - Write to `<stem>.partial<suffix>` in the target directory, then `os.replace` it onto the target
    on success. A cancel or failure removes the partial file and leaves an existing target alone.
- **Metadata key names are part of the format.**
  - This grid's file gains `NSGEO_CELL_M`, `NSGEO_PIXEL_M` and `NSGEO_RESAMPLING` (value `bilinear`).
  - The site file gains `NSGEO_SITE_RESAMPLING`.
  - `NSGEO_SITE_CELL_M` and `NSGEO_SITE_PIXEL_M` are the export cell and the export pixel.
  - The per-band `NSGEO_GRID_FACTORS` are the export's own factors.
- **Copy.** User-facing text is plain words: no "lattice", no issue numbers. Exact copy is given
  where it matters.
- **Windows.** QGIS holds files open, so the target, its `.qml` and its coverage companion may not
  be replaceable while loaded. Decision 17 handles it.
- **Commits.** Commit each task, push the branch as you go, and end each message with a
  `Co-Authored-By:` trailer naming your model.

## Review Focus

1. **Cancel mid-band at a fine cell.** Minimum curvature is the slow case. The task stops within
   one grid's band, the partial file is gone, no layer is added, an existing target is untouched,
   and the live view never paused. Pinned in Task 3.
2. **The survey changes while an export runs.** Lines are re-prepared, a grid is moved or the site
   is closed. The export finishes on its snapshot or is cancelled cleanly, never reads a live
   engine, and never crashes. Ruling: closing the site cancels the export, so no layer is added to a
   closed site. Pinned in Tasks 1, 3 and 5.
3. **The target is already a layer in the project.** On Export the dialog offers to replace it
   (remove the layer, write, add it again with the new style) or to cancel. This applies to the
   coverage companion and the `.qml` too. Pinned in Tasks 4 and 5.
4. **The export does not fit.** When memory or free disk space is not enough, Export is disabled
   before anything starts, with the reason in the summary and the finest cell or pixel that would
   fit. Pinned in Tasks 1 and 4.
5. **A preview site.** In milestone A it could not be exported. Now it exports at full detail
   through the dialog, within the export's own memory budget. The note's tooltip no longer carries
   the old refusal. Pinned in Task 5.


## Controller rulings that bind tasks (from the ledger)
- Ruling R1: `ExportCancelled` moves to `export_pipeline.py`; `slice_export.py` imports it from there so `from nsgeo_qgis.slice_export import ExportCancelled` keeps working — the pipeline must stay importable without QGIS for the pure tier — costs a one-line move back if wrong.
- Ruling R2: `ExportGrid.world_to_frame` stays a plain callable in T1. T5's snapshot gives each grid in another CRS a closure over (source authid, target authid, a copy of the project's `QgsCoordinateTransformContext` taken on the GUI thread) that BUILDS a fresh `QgsCoordinateTransform` on every call and raises if it is invalid (as `SiteEngine._transform` does). `run_export` calls it only while building a grid's taps, i.e. inside `run()`, once per grid per export. The helper lives in a Qt module (T5's choice: `site_export.py`), never in `export_pipeline.py` — keeps T1 Qt-free and meets "built inside run()" — costs a refactor of one helper if the reviewer wants a per-run cache.
- Ruling R3: T4 defines a pure frozen `ExportPreview` in `slices_plan.py` (cell, pixel, width, height, bands, slices text, grids or None for This grid, normalisation or None, file_bytes, held_bytes) and `summary_lines(preview) -> list[tuple[str, str]]`. `ExportDialog` takes an injected `preview: Callable[[float, float], ExportPreview]` (cell, pixel → preview) plus `cell_floor: float` and `live_cell: float`; T4's tests use fakes; T5 builds the real callable from `site_export_spec`/`grid_export_spec` + `estimate_export` — the dialog can't wait for T5's builders, and a callable keeps it testable — costs a constructor change if T5 needs more.
- Ruling R4: T4 also owns `finest_fits(held_at: Callable[[float, float], int], cell, pixel, budget) -> tuple[float | None, float | None]` in `slices_plan.py`, pure: finest pixel = the smallest pixel on a 1 mm grid in [pixel, cell] that fits at this cell (None when none fits or pixel == cell); finest cell = the smallest cell on a 1 mm grid above the current one that fits with pixel = cell, searched by doubling then bisection and given up (None) past 8× the current cell. Both assume memory falls as cell/pixel grow. The dialog calls it only when over budget and feeds `export_refusal` — someone has to compute the "finest fit" copy, and pure placement makes it testable — costs a cheaper/rougher search if it proves slow.
- Ruling R5: T2 adds `write_bands(path, plan, bands: Iterable[ExportBand], *, clip, progress_band=None) -> float` to both GeoTIFF writers (returns the measured limit; NaN-safe; a counts plan returns its own limit too). T3 defines `@dataclass(frozen=True) WriterPlan: writer, plan, coverage_plan | None, clip` and calls `writer_plan.writer.write_bands(partial, writer_plan.plan, run_export(spec, …), clip=…)`, then the same for the coverage companion with `coverage_plan` — gives `writer_plan` a definition both tasks share — costs a rename if T5 finds it awkward.
- Ruling R6: `ExportResult` gains `coverage_limit: float | None` so T5 can write the companion's own `.qml` (spec §6.3 "The coverage companion gets its own") — costs one unused field if the companion ends up styled by a fixed rule.
- Ruling R7: the writer keeps a bounded, strided subsample of each band's finite values (total capped at a module constant, 2,000,000 values, split evenly across bands) and measures the limit on that with `clip.limit` after dropping NaN, as `limit_over_slices` does. Under the cap it keeps every value, so a test on a small file pins equality with `limit_over_slices` over the written bands exactly; a second test pins the cap. `PercentileClip` already subsamples to 200,000 — §6.2 forbids holding more than one band of the site picture, and decision 16 asks for "the same percentile rule", not every value — costs a slightly different stretch on huge exports, cosmetic.
- Ruling R8: T3 also produces `running_export() -> ExportTask | None` (the held task) so T5 can cancel it on `site_closed` and say why a second Export is refused — the plan needs both and gave T3 no accessor — costs nothing if wrong.
- Ruling R9: T5 adds one QGIS-tier test: a site export at the live cell and pixel, on a site that is not a preview, equals `SiteEngine.slice_at` band by band (1e-5, NaN in the same places, factors equal). T1's equality test re-builds the composition from core calls; only this pins the real engine against the pipeline, which is the anti-goal "a file whose metadata names settings it was not made with" in practice — costs one slow-ish test.
- Ruling R10: T5 deletes the GUI-thread export paths it replaces (`export_slices`, `export_site`, `write_coverage`, `write_site_coverage`, and the old writer `write` methods) and their tests when grep shows no remaining caller; anything still called stays — dead export paths that bypass the new write rules would invite a second, unsafe way to write a file — costs restoring a helper from git if something external used it.
- Ruling R11: T5 removes milestone A's export refusal (`SiteEngine.export_refusal`/`_export_refusal`, `slices_plan.site_export_refusal`, `plan_site_export`'s refusal, the tooltip's half) once nothing calls them, keeping `is_preview`/`preview_note` working on their own terms — spec decision 10: "milestone B replaces the refusal" — costs a revert if the author wanted the refusal kept for some path.
