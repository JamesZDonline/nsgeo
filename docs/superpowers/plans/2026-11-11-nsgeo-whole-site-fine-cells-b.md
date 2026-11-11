# Whole Site at Fine Cells, Milestone B (#108): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GeoTIFF export, for This grid and for Whole site, that can be finer than the live view
in its cell and in its pixel.
- It runs in QGIS's background-task list while the panel stays usable.
- It rebuilds every grid at the export cell and measures normalisation again on that data.
- It writes band by band, to a temporary file renamed on success.
- The file is tiled with overviews when large, and gets a QGIS style file beside it.

**Architecture:**
- **The pipeline.** A Qt-free export pipeline (`nsgeo_qgis/export_pipeline.py`) works only from a
  frozen snapshot taken on the GUI thread: prepared lines, grid frames at the export cell, z axes,
  finish settings in metres, the normalisation method, manual gains, and the output lattice at the
  export pixel. It bins, normalises, finishes and composes one band at a time. It never touches a
  live engine or the session.
- **The task.** A `QgsTask` (`nsgeo_qgis/export_task.py`) runs the pipeline and the writer in the
  background, reports "band k of N · grid" to the task list, and lands the result on the GUI
  thread: rename, add the layer, apply the style.
- **The dialog.** A new `ExportDialog` (option B, with a summary) sets the path, the export cell and
  the export pixel. It shows what will be written, checks memory and disk space, and offers to
  replace a target that is open in QGIS.

**Tech Stack:** Python 3.9+, numpy (core numpy only), GDAL, QGIS 3.40 / 3.44 / 4.2 (PyQt5 and
PyQt6), pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-nsgeo-whole-site-fine-cells-design.md`. §6 is this
milestone; §3 has the decisions, including A, B and 1–17. Milestone A (#107) is merged (PR #155).
Its decision record, `docs/superpowers/sdd/2026-11-10-nsgeo-whole-site-fine-cells-a/`, explains the
pixel rule, the limits and the coverage rule this milestone builds on.

**Decided since the spec** (author, 2026-11-11, from the mock-up `.lavish/fine-cells-export-dialog.html`):
- Dialog option **B**: the fields plus a read-only "What will be written" summary.
- Progress in **QGIS's background-task list**, which means a `QgsTask`.

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
   and the live view never paused. Pinned in Task 4.
2. **The survey changes while an export runs.** Lines are re-prepared, a grid is moved or the site
   is closed. The export finishes on its snapshot or is cancelled cleanly, never reads a live
   engine, and never crashes. Pinned in Tasks 1 and 4.
3. **The target is already a layer in the project.** On Export the dialog offers to replace it
   (remove the layer, write, add it again with the new style) or to cancel. This applies to the
   coverage companion and the `.qml` too. Pinned in Task 5.
4. **The export does not fit.** When memory or free disk space is not enough, Export is disabled
   before anything starts, with the reason in the summary and the finest cell or pixel that would
   fit. Pinned in Tasks 1 and 5.
5. **A preview site.** In milestone A it could not be exported. Now it exports at full detail
   through the dialog, within the export's own memory budget. The note's tooltip no longer carries
   the old refusal. Pinned in Task 6.

---

### Task 1: The export pipeline, without Qt, plus the memory budget

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/export_pipeline.py`.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/display.py`. Add
  `frame_lattice(frame: CubeFrame, pixel: float) -> SiteLattice`: the north-up lattice anchored on
  the frame's own extent at any pixel, so This grid at `pixel == cell` stays exact. Make
  `_build_north_up_plan` use it. Export it from `nsgeo.slices` and add a README row.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`. Add `EXPORT_BUDGET_BYTES` and
  `export_refusal(...)` copy.
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_export_pipeline.py` (new) and
  `packages/nsgeo-core/tests/test_slices_display.py` (`frame_lattice` only).

**Interfaces (produces):**
- `@dataclass(frozen=True) ExportGrid`:
  - `grid_id: str`
  - `lines: tuple[PreparedLine, ...]`
  - `frame: CubeFrame` (at the export cell)
  - `z: ZAxis` (the grid's own axis)
  - `finish: FinishSettings` (in metres)
  - `spacing_m: float`
  - `gain: float`
  - `world_to_frame: Callable[[np.ndarray], np.ndarray] | None` (None when the frame shares the
    output CRS)
- `@dataclass(frozen=True) ExportSpec`:
  - `grids: tuple[ExportGrid, ...]`
  - `lattice: SiteLattice` (the output at the export pixel)
  - `windows: tuple[tuple[float, float], ...]` (each band's `(top_ns, thickness_ns)` on the site
    axis)
  - `method: str` (normalisation; `"none"` for This grid)
  - `coverage: bool`
- `estimate_export(spec) -> ExportEstimate`:
  - fields `held_bytes`, `file_bytes` (uncompressed, overviews included) and `per_band` (a dict of
    the parts);
  - all through `estimate_memory` and `covered_cells`, plus fill weights at `WEIGHT_BYTES_PER_CELL`,
    taps at 52 B per covered output pixel (`covered_pixels`) and one band's accumulators;
  - binning picks stream or packed cube per grid by `choose_residency` on that estimate.
- `run_export(spec, *, should_stop: Callable[[], bool], progress: Callable[[int, int, str], None]) -> Iterator[ExportBand]`:
  - `ExportBand` holds `array: np.ndarray` (float32 on `spec.lattice`) and
    `factors: dict[str, tuple[float, float]]`.
  - Order of work: band by band. Seams are found once at the export frames. Each band is binned for
    every grid, `normalise(method, binned, seams, gains)` runs on the BINNED values, then each grid
    is finished (kriging or IDW through `plan_fill`/`finish_slice`, minimum curvature through
    `CurvaturePlan.solve(values, should_stop)` and `smooth`) and the result is composed with
    `compose_footprints(spec.lattice, …, counts=spec.coverage)`.
  - `should_stop` is checked between grids and inside the curvature solve, raising
    `ExportCancelled` (re-export the existing one from `slice_export`, or move it here).
  - `progress(band_index, n_bands, grid_id)` is called before each grid of each band.
- `export_refusal(held_bytes: int, budget: int, finest_cell: float | None, finest_pixel: float | None) -> str`
  in `slices_plan.py`. Exact copy:
  `f"This export would hold about {format_bytes(held_bytes)} in memory, more than the {format_bytes(budget)} it is allowed."`
  then `f" A {finest_cell:g} m export cell would fit."` when a cell is given, then
  `f" A {finest_pixel:g} m export pixel would fit."` when a pixel is given.

- [ ] **Step 1: Write the failing tests.**
  - `test_frame_lattice_at_the_cell_reproduces_an_axis_aligned_grid`.
  - `test_frame_lattice_at_half_the_cell_doubles_the_pixels`.
  - `test_export_at_the_live_cell_equals_the_live_composition`: a synthetic two-grid site (one
    rotated, edge match) built with the same core calls as `SiteEngine.slice_at`. Values to 1e-5,
    NaN in the same places, factors equal.
  - `test_export_at_a_finer_cell_measures_normalisation_again`: factors at the export cell differ
    from the live ones where the binned data differs. Pins decision 3.
  - `test_manual_gains_are_carried_as_typed` (decision 11).
  - `test_coverage_export_holds_whole_counts`.
  - `test_should_stop_cancels_within_one_grid`: progress is called with `(k, n, grid)`, and
    `ExportCancelled` is raised before the next grid runs.
  - `test_a_grid_in_another_crs_is_transformed_before_sampling`: a fake `world_to_frame` shifts by a
    known offset.
  - `test_the_estimate_counts_weights_taps_and_one_band` and
    `test_an_export_over_budget_is_refused_with_the_finest_fit` (exact copy).
  - `test_the_pipeline_never_reads_cube_mean` (a contract test: a `SliceCube` subclass whose `mean`
    raises).
  - Real data first: where the local DZT files are present, one test exports the ten local lines'
    grid at 0.05 m and at 0.025 m and checks finite coverage. Skip when they are absent.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** to the interfaces. `run_export` composes through the existing core
  functions only; no new numerics.
- [ ] **Step 4: Measure, then set `EXPORT_BUDGET_BYTES`.**
  - Extend `packages/nsgeo-qgis/scripts/bench_site.py` with `--export CELL PIXEL`.
  - On the walkthrough site's geometry (ten grids, 4–10° and near 90°; synthetic lines laid like
    real ones), at cell 0.025 m with pixel 0.025 and 0.0125, and at cell 0.05 m with pixel 0.05,
    record:
    - peak memory (tracemalloc plus array sizes);
    - time per band, for kriging and for minimum curvature;
    - the estimate against the measured value.
  - Choose band by band if, at those settings, it fits `DEFAULT_BUDGET_BYTES` (1.5 GB). Set
    `EXPORT_BUDGET_BYTES` to that. Otherwise report: grid by grid needs an accumulate-on-disk
    design that is not in this plan.
  - Write the table and the decision in the module docstring (spec §6.2: "measured, then chosen").
- [ ] **Step 5: Run** the pure, core and display tests, plus lint. All pass.
- [ ] **Step 6: Commit:** `feat(export): a Qt-free export pipeline at any cell and pixel, with a memory budget`.

---

### Task 2: The file: tiles, overviews, temporary name, metadata, stretch, style file

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`:
  - `GeoTiffSliceWriter` gains a mode that writes north-up arrays from `ExportBand`;
  - `OPTIONS` moves to `creation_options(width, height)`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py` (`GeoTiffSiteWriter`).
- Create: `packages/nsgeo-qgis/nsgeo_qgis/export_style.py` with
  `write_style(path, *, limit, colormap_name, unipolar) -> Path`. It is GUI-thread only.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`,
  `test_plugin_site_export.py` and a new `test_plugin_export_style.py`.

**Interfaces (produces):**
- `creation_options(width: int, height: int) -> list[str]`.
  - **Ruling:** tile only when both sides are at least 1024 pixels, with `BLOCKXSIZE=BLOCKYSIZE=256`.
    Below that, keep today's strips. The measured 2.9× waste
    (`test_the_creation_options_are_the_measured_ones`) came from 512-pixel tiles on small frames.
    Rewrite that test to pin both regimes.
- `build_overviews(path)`: nodata-aware AVERAGE, factors 2, 4, 8 … while the overview's longer side
  is at least 256. Only for tiled files.
- `partial_path(target) -> Path` gives `<stem>.partial<suffix>`. `commit_partial(partial, target)`
  calls `os.replace`. `discard_partial(partial)`.
- Writers take a `progress_band` callback, set the new metadata keys (Global Constraints), and
  return `limit: float`: the stretch measured over every written band by `limit_over_slices` with
  the panel's clip rule (decision 16).
- `write_style`:
  - builds a renderer with `build_shader` and the limit;
  - calls `apply_smooth_resampling`;
  - saves `<stem>.qml` with `saveNamedStyle`;
  - and is checked to load as the default style when the file is added to a fresh project.

- [ ] **Step 1: Write the failing tests.**
  - Tiled above the threshold, stripped below (check `GetBlockSize`).
  - Overviews exist and do not bleed: an overview pixel over empty ground stays NaN.
  - A writer interrupted mid-band leaves no partial and no target, and an existing target is
    byte-identical.
  - The metadata keys and values round-trip, including `NSGEO_RESAMPLING=bilinear` and the cell and
    pixel.
  - The returned stretch equals `limit_over_slices` over the written bands.
  - The `.qml` loads: the added layer has a pseudocolour renderer at the limit and bilinear zoomed
    in.
  - No `warnings.catch_warnings` in the writer path. Grep-based or by mocking.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both export test files and the style test, plus lint.
- [ ] **Step 5: Commit:** `feat(export): tiled when large, overviews, a temporary name, export metadata and a style file`.

---

### Task 3: The background task

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/export_task.py`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_export_task.py` (new).

**Interfaces:**
- Consumes: Task 1's `ExportSpec`, `run_export` and `ExportCancelled`; Task 2's writers,
  `partial_path`, `commit_partial` and `discard_partial`.
- Produces:
  - `class ExportTask(QgsTask)`:
    - constructed with `(description, spec, writer_plan, target: Path, coverage_spec: ExportSpec | None, coverage_target: Path | None, on_done: Callable[[ExportResult], None])`;
    - `run()` writes the file, then the coverage companion, each to its partial path and then
      committed;
    - `setProgress` across both, and `setDescription(f"Exporting {what}: band {k} of {n} · {grid}")`;
    - checks `isCanceled()` through `should_stop`.
  - `finished(ok)` is guarded. It calls `on_done(ExportResult(ok, cancelled, error, target, coverage_target, limit))`
    on the GUI thread in every case, including cancellation while still queued.
  - `start_export(task) -> bool` keeps the task in a module-level holder until `finished`, handles
    `addTask()` returning 0 (calls `on_done` with an error), and refuses a second export while one
    is held (returns False).

- [ ] **Step 1: Write the failing tests.**
  - It runs to completion: the target exists, `on_done` is called once with `ok`, and the holder
    is empty.
  - Cancel mid-run (cancel from a progress callback): no partial and no target, `cancelled=True`.
  - Cancel while queued: `on_done` is called synchronously.
  - An exception in `run` gives `on_done(error=…)`, with no swallowed exception.
  - An exception in `on_done` does not escape `finished`.
  - A second `start_export` while one is held returns False.
  - The live engines are untouched: a spy on a live `SliceEngine` and `SiteEngine` sees no call
    while the task runs.
  - The live panel stays usable: a slice redraw during the task succeeds.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** and lint.
- [ ] **Step 5: Commit:** `feat(export): run exports in QGIS's background-task list`.

---

### Task 4: The export dialog (option B)

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/export_dialog.py`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`, adding the summary text helpers.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_export_dialog.py` (new; driven with
  `drive_dialog`).

**Interfaces:**
- Produces:
  - `class ExportDialog(QDialog)`, modal and opened with `exec()`, with fields:
    - **Save to:** a path field plus a "…" button opening `QFileDialog.getSaveFileName`;
    - **Export cell:** a spin box with three decimals, floored at the largest included grid's
      `smallest_safe_cell` (decision A), defaulting to the live cell;
    - **Export pixel:** a spin box, defaulting to and never above the export cell.
  - A read-only **What will be written** group, recomputed when either spin box changes (debounced
    150 ms):
    - Bands, Picture, Grids (site only), Slices, Normalisation (site only), File and Disk, as in
      the mock-up;
    - Disk is `shutil.disk_usage` of the target's directory.
  - **Export is disabled** with the reason in the group when either:
    - the estimate is over `EXPORT_BUDGET_BYTES` (`export_refusal` copy);
    - or free space is under 1.2 × the file estimate:
      `f"Not enough free disk space: about {need} needed, {free} free."`
  - `result_settings() -> ExportChoice(path, cell, pixel)`.
  - `targets_in_use(project, paths) -> list[QgsMapLayer]`. On Export, when any target, its `.qml`
    or its coverage companion is a project layer, ask (decision 17):
    `"<name> is open in this project. Replace it? The layer is removed and added again when the export finishes."`
    with Replace and Cancel. Use an in-dialog confirmation strip, not a nested modal.
- `summary_lines(spec_preview) -> list[tuple[str, str]]` in `slices_plan.py` holds the summary text,
  so it can be tested in the pure tier.

- [ ] **Step 1: Write the failing tests.**
  - Defaults: the cell and pixel are the live cell.
  - The pixel spin's maximum follows the cell.
  - The cell floor is the largest included grid's safe cell.
  - The summary text is exact for a two-grid site.
  - The site rows are absent in This grid.
  - Over budget: Export is disabled and the exact copy shows the finest fit.
  - Low disk (monkeypatch `disk_usage`): disabled with the exact copy.
  - A target open as a layer: the confirmation strip appears, and Replace accepts while Cancel
    stays.
  - The debounce: rapid spin changes compute the estimate once.
  - The dialog never widens past the QGIS minimum, matching the panel's width rule.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement**, following `VelocityDialog`'s modal pattern (`plugin.py:1951`, with
  `deleteLater` in a `finally`).
- [ ] **Step 4: Run** and lint.
- [ ] **Step 5: Commit:** `feat(export): the export dialog, with a summary, a memory check and a disk check`.

---

### Task 5: Wiring both exports through the dialog and the task

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - `export_geotiff` (~919-1041) and `export_site_geotiff` (~1114-1226) build the dialog, then the
    snapshot, then the task;
  - `_export_progress`, `_bands_are_slow` and `_remove_partial` are removed.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py` and `slice_export.py`:
  - planning helpers take the export cell and pixel;
  - snapshot builders `site_export_spec(...)` and `grid_export_spec(...)` run on the GUI thread and
    read the engines and the session once.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: the preview note's tooltip drops the
    export refusal (spec decision 13/16 and walkthrough D2), and `export_refusal` no longer blocks
    the button.
- Test: `test_plugin_slice_export_dialogs.py`, `test_plugin_site_scope.py`,
  `test_plugin_slice_export.py` and `test_plugin_site_export.py`. Rewrite the tests that pin the
  GUI-thread export:
  - WindowModal progress (~668-681);
  - cancel through `processEvents` (~707-754);
  - the wait cursor (~806);
  - the refine-paused path (~628);
  - `_remove_partial`'s mtime rule (~506-525).

  Each becomes the task-based behaviour.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: on success the plugin:
  1. adds the layer and its coverage companion through `_add_exported_layer`;
  2. applies `write_style` with the measured limit, the panel's colormap and unipolar;
  3. applies the temporal properties;
  4. shows `f"exported {n} bands to {path} ({cell:g} m cell, {pixel:g} m pixels)"`.

  On a replaced target, the old layer is removed before the task starts and the new one is added
  after. A cancelled export shows `"export cancelled"`, and a failed one gives its plain error at
  Critical.

- [ ] **Step 1: Write the failing tests.**
  - A site export at a finer cell (0.25 → 0.125 on site3): the file's metadata names the export
    cell and pixel, and its bands differ from a live-cell export where the data does.
  - The live view stays usable during the export: a slice tick runs while the task is held.
  - A preview site (lowered `max_covered`) now exports at full detail.
  - This grid at a finer pixel: the file is twice the width and the height.
  - Cancel from the task list: no file, no layer.
  - The coverage companion is written and styled.
  - A replaced target: the layer is removed, then added again.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the five files above, `test_plugin_site_engine.py`, and the full QGIS tier
  once, plus lint.
- [ ] **Step 5: Commit:** `feat(export): both exports through the dialog and the background task`.

---

### Task 6: Docs, roadmap, guide

**Files:**
- Modify: `docs/guide/getting-started.md`: the export step (the dialog, export cell and pixel,
  background progress, the style file) and a plain coverage explanation (#157 item 6, cheap to do
  here).
- Modify: `README.md`:
  - add #157 to the Wishlist (Slices group);
  - in the PR, "Whole site at fine cells: the export" moves to Done (next release).

- [ ] **Step 1:** Write the guide text in plain words. Mention the style file loading in other QGIS
  projects, and that other GIS software reads the values but chooses its own colours.
- [ ] **Step 2:** Update the README.
- [ ] **Step 3: Commit:** `docs: the export dialog and background export in the guide; roadmap`.

---

## After the tasks (coordinator)

- **Whole-branch review** (opus), then one fix wave.
- **Deploy to a new profile and walk through spec §8.2** (a human gate) on the real ten-grid site:
  - export at 0.025 m, and at 0.05 m with a 0.025 m pixel;
  - cancel one mid-way;
  - keep using the panel during an export;
  - open the files in a fresh QGIS project, where the style applies, and step through depths;
  - if available, open one in another GIS.
- **The build record** and the README roadmap go in the PR.
