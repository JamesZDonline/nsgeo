# Task 5 context — what Tasks 1–4 built and what they left for you

Everything below is on the branch. Read the code for exact signatures; this file tells you what
to use and which obligations earlier reviews handed to Task 5.

## Built interfaces

- **Task 1, `nsgeo_qgis/export_pipeline.py`** (Qt-free): `ExportGrid`, `ExportSpec`,
  `estimate_export(spec) -> ExportEstimate(held_bytes, file_bytes, per_band)`,
  `run_export(spec, *, should_stop, progress)` (generator of `ExportBand(array, factors)`),
  `ExportCancelled`. Core `frame_lattice(frame, pixel)` (This grid's output lattice).
  `EXPORT_BUDGET_BYTES` and `export_refusal(...)` in `slices_plan.py`.
- **Task 2, `slice_export.py` / `site_export.py` / `export_style.py` / `slice_layer.py`:**
  `GeoTiffSliceWriter.write_bands(...)`, `GeoTiffSiteWriter.write_bands(...)` (return the
  measured limit); `build_overviews(path, should_stop=None)`; `partial_path`, `commit_partial`,
  `discard_partial`; `coverage_path(target)` (`<stem>_coverage.tif`, the one companion rule);
  `write_style(path, *, limit, colormap_name, unipolar) -> Path` (GUI thread);
  `apply_renderer(layer, colormap_name, limit, unipolar)` in slice_layer.py. `ExportPlan` gained
  the export lattice, cell and pixel, and `write_bands` REFUSES a plan without them.
  `SiteExportPlan` gained `coverage: bool` — the site counts companion's plan MUST set
  `coverage=True` (plus method "none", finish None, gains 1.0, as `write_site_coverage` builds it)
  or its resampling tag reads `bilinear`. Counts files are tagged `largest_count`.
- **Task 3, `export_task.py`:** `WriterPlan(writer, plan, coverage_plan, clip, coverage_clip)`,
  `ExportResult(ok, cancelled, error, target, coverage_target, limit, coverage_limit)`,
  `ExportTask(description, spec, writer_plan, target, coverage_spec, coverage_target, on_done,
  what=None)`, `start_export(task) -> bool` (False only when another export is held, and then
  `on_done` is NOT called; True means `on_done` fires exactly once), `running_export()`.
  It writes both partials (values + overviews, then companion + overviews) before committing
  either; a cancel or failure discards both and leaves both old targets alone.
- **Task 4, `ui/export_dialog.py` + `slices_plan.py`:** `ExportDialog(...)` takes an injected
  `preview: Callable[[float, float], ExportPreview]`, `cell_floor`, `live_cell` (read its
  constructor); `result_settings() -> ExportChoice(path, cell, pixel)`; `layers_to_replace()`;
  `targets_in_use(project, paths)`; `target_paths(path)`. Pure `ExportPreview`, `summary_lines`,
  `finest_fits` in `slices_plan.py`.

## Obligations handed to Task 5 by earlier reviews (each is a requirement)

1. **Snapshot on the GUI thread, once.** `site_export_spec(...)` / `grid_export_spec(...)` read
   the engines and the session once. They hand over the live engines' OWN `PreparedLine`
   objects (not copies): `estimate_export`'s `held_bytes` excludes the lines on that basis.
   This grid: gain 1.0 and method `"none"`.
2. **Grids in another CRS (ruling R2).** Each such grid's `world_to_frame` is a closure over
   (source authid, target authid, a copy of the project's `QgsCoordinateTransformContext` taken
   on the GUI thread) that BUILDS a fresh `QgsCoordinateTransform` on each call and raises a
   plain error if it is invalid (as `SiteEngine._transform` does). Put the helper in
   `site_export.py`. `run_export` calls it only inside `run()`.
3. **Every plan names the export's own settings:** `ExportPlan` gets the export lattice, cell
   and pixel; `SiteExportPlan` gets `cell_m` = export cell and `lattice` = the export lattice.
   Never the live ones (anti-goal: "a file whose metadata names settings it was not made with").
4. **Dialog wiring.** `cell_floor` = the largest included grid's `smallest_safe_cell`. The
   `preview` callable builds specs at (cell, pixel) and calls `estimate_export`; its `file_bytes`
   must include the coverage companion (both partials exist at once). The dialog calls `preview`
   on the GUI thread once per debounce and about 2·log2(range)+1 more times when over budget;
   `estimate_export` re-counts covered cells over every trace per call — MEASURE the call on the
   ten-grid bench geometry (or a real-sized synthetic site) and report it; if one call is over
   ~100 ms, cache the per-grid parts that do not depend on (cell, pixel) or memoise
   `covered_cells` per (grid, cell). Follow the modal pattern: `exec()`, `deleteLater` in a
   `finally`. Site title per the mock-up ("Export site GeoTIFF").
5. **Replacing a target (decision 17).** Remove `layers_to_replace()` from the project BEFORE the
   task starts (Windows locks open files); add the new layers after.
6. **One export at a time.** If `start_export` returns False, say so plainly (a second Export
   while one runs is refused with a plain message).
7. **Cancel on close and on unload.** On `site_closed`, cancel `running_export()`. On plugin
   unload, cancel it too — a reloaded module starts with no held task while the old one may
   still be writing the same partial path. Cancelling a QUEUED task runs `on_done` synchronously
   inside `cancel()`: `on_done` must be safe re-entrantly.
8. **Late cancel.** A cancel landing after the task's last check still commits and returns
   `ok=True`. `on_done` must re-check that the site (or grid) is still open before adding a
   layer; if it is closed, leave the written file on disk and add nothing.
9. **On success:** add the layer and its companion through `_add_exported_layer`; write the
   `.qml` with `write_style` (values: the measured `limit`, the panel's colormap and unipolar;
   companion: `coverage_limit` and the coverage view's own colormap/unipolar rule); apply the
   temporal properties AFTER the layer is added (the `.qml` stores temporal settings, disabled);
   show `f"exported {n} bands to {path} ({cell:g} m cell, {pixel:g} m pixels)"`.
   Cancelled: `"export cancelled"`. Failed: plain error at Critical — `ExportResult.error` is raw
   exception text, so turn it into plain words (keep the raw text in the QGIS log).
10. **Spy on the real snapshot** (Review Focus 2): a test that runs a real export through the
    plugin with a recorder on the live `SliceEngine`/`SiteEngine` instances shows no access off
    the GUI thread while the task runs.
11. **Ruling R9:** a site export at the live cell and pixel, on a site that is not a preview,
    equals `SiteEngine.slice_at` band by band (1e-5, NaN in the same places, factors equal).
12. **Ruling R10:** delete the GUI-thread export paths you replace (`export_slices`, `export_site`,
    `write_coverage`, `write_site_coverage`, the old writer `write` methods and anything only they
    use) and their tests, when grep shows no remaining caller. Anything still called stays.
13. **Ruling R11:** remove milestone A's export refusal (`SiteEngine.export_refusal` /
    `_export_refusal`, `slices_plan.site_export_refusal`, `plan_site_export`'s refusal, the
    tooltip's refusal half in `ui/site_scope.py`) once nothing calls them. `is_preview` currently
    returns `self._export_refusal is not None` (site_engine.py:291-293): re-base it on its own
    terms (e.g. lattice differs from the full lattice), and keep `preview_note` working.
14. **A missing target directory** passes the dialog and would fail in the task: refuse it
    plainly before starting (or create it — your call, say which).

## Known limits (do not fix; just don't contradict)

- Kriging's fill planning is not interruptible (~14 s a grid at 0.025 m); a cancel during band 0
  setup can take that long.
- 0.025 m cell with a 0.0125 m pixel is over the 1.5 GB budget on the author's site and is
  refused by the dialog (finest pixel ~0.021 m).
15. **One companion rule everywhere:** `plugin.py` (~1019, ~1205) and `site_export.py:~411` still
    build `<stem>_coverage.tif` inline; use `coverage_path(target)` wherever you touch them.
