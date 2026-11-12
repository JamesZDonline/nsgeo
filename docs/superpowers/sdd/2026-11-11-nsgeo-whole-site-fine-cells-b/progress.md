# SDD ledger — plan: docs/superpowers/plans/2026-11-11-nsgeo-whole-site-fine-cells-b.md

Spec: docs/superpowers/specs/2026-11-10-nsgeo-whole-site-fine-cells-design.md (§3 decisions, §6 milestone B).
Branch nsgeo-fine-cells-export, worktree .worktrees/nsgeo-fine-cells-export, start 98a4efd (main b628ce3).
Author chose subagent-driven 2026-11-11. Implementers sonnet, reviewers opus (author's standing tiers).

## Pre-flight scan

### Pairs sharing a file or interface

| Pair | Produces → consumes | Found |
|---|---|---|
| T1↔T2 | T1 `ExportBand(array, factors)` → T2 writers write north-up arrays from it | Agrees. But T1 says re-export or move `ExportCancelled`; it lives in `slice_export.py`, which imports `qgis.core`, and T1's pipeline must be Qt-free (pure tier). → R1 |
| T1↔T2 | T2's stretch "limit_over_slices over every written band" vs §6.2 "no more than one band of the full site picture held" | `limit_over_slices` concatenates every finite value; at 7.8 M px × 40 bands that is GBs. → R7 |
| T1↔T3 | T1 `ExportSpec`, `run_export`, `ExportCancelled` → T3 `ExportTask.run()` | Agrees on names. `ExportGrid.world_to_frame` is a Callable built on the GUI thread (T5 snapshot), yet Global Constraints require the `QgsCoordinateTransform` to be built inside `run()`. → R2 |
| T1↔T4 | T1 `estimate_export`, `export_refusal(held, budget, finest_cell, finest_pixel)` → T4 dialog's refusal | T4 needs an estimate at any (cell, pixel) while the dialog is open, but the spec builders that make an `ExportSpec` are T5's. Nobody computes `finest_cell`/`finest_pixel`. `summary_lines(spec_preview)` names an undefined type. → R3, R4 |
| T2↔T3 | T2 writers, `partial_path`/`commit_partial`/`discard_partial` → T3 | T3's constructor takes `writer_plan`, never defined; the coverage companion needs its own plan (method none, no finish, gains 1.0). → R5 |
| T2↔T5 | T2 `write_style(path, *, limit, colormap_name, unipolar)` → T5 applies after commit; coverage companion "gets its own" style | `ExportResult` carries one `limit`; the companion's own stretch has no field. → R6 |
| T3↔T5 | T3 `start_export`, holder, `ExportResult` → T5; T5 must cancel on `site_closed` and refuse a 2nd export | T3 exposes no way to reach the held task. → R8 |
| T4↔T5 | T4 `ExportDialog`, `result_settings()`, `targets_in_use` → T5 | Agrees once R3 fixes the dialog's inputs (T5 supplies the real preview callable and cell floor). |
| T1↔T5 | T1 `ExportSpec` → T5 `site_export_spec`/`grid_export_spec` | Agrees. T1's equality test with the live composition is pure-tier (re-built with core calls); no test pins the real `SiteEngine` against the pipeline. → R9 |
| T5↔(A code) | Milestone A's `SiteEngine.export_refusal`, `slices_plan.site_export_refusal`, `plan_site_export`'s refusal; GUI-thread `export_slices`/`export_site`/`write_coverage`/`write_site_coverage` | T5 removes their callers; plan is silent on the functions themselves. → R10, R11 |
| T5↔T6 | T5 behaviour → T6 guide text | Agrees. |

### Each task against itself

| Task | Found |
|---|---|
| T1 | Self-consistent: tests name every interface it produces; `EXPORT_BUDGET_BYTES = DEFAULT_BUDGET_BYTES` if the measurement fits, else BLOCKED report. Files: creates export_pipeline.py, touches display.py, slices_plan.py, bench_site.py (Step 4 names it; Files list doesn't — fine). |
| T2 | Self-consistent. "No `warnings.catch_warnings`" test vs today's writers that use it: the task changes them, consistent. |
| T3 | Self-consistent apart from `writer_plan` (R5). |
| T4 | `summary_lines(spec_preview)` type undefined (R3). "The panel's width rule": implementer finds the existing test. |
| T5 | Self-consistent; its test list matches its interface list. |
| T6 | Self-consistent. |

### Rulings

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

## Tasks
Task 1: dispatched (base 98a4efd, implementer agent aec853113b37685ee, sonnet)
Task 1: implementer BLOCKED on the budget only (commit 6483fbf, unpushed). Measured peak, ten grids: 0.05/0.05 ≈ 300 MB; 0.025/0.025 ≈ 1.2 GB; 0.025/0.0125 ≈ 2.77 GB (taps 1575 MB, weights 614, band 401). Estimates 0–6% over measured.
- Ruling R12: band by band, EXPORT_BUDGET_BYTES = DEFAULT_BUDGET_BYTES (1.5 GB), final. The spec §8.2 walkthrough cases (0.025/0.025, 0.05/0.025) fit; 0.025/0.0125 is refused before it starts by the dialog's memory check with the finest pixel that fits (Review Focus 4 — the plan's own path for "does not fit"). Not 3 GB: the live engines hold up to 1.5 GB of their own in the same QGIS process. Not strips/grid-by-grid: a design the plan excludes; spec §10 leaves the order of work to the builder. Follow-up for the author: lifting the ceiling (per-grid taps rebuilt per band, or strip/grid-by-grid composition) for pixels under ~0.7× a 0.025 cell and for ~120 m sites at 0.025 m, where the fill weights alone pass 1.5 GB — costs: those exports refuse with a plain reason until a follow-up lands.
- Ruling R13: the implementer's three deviations stand pending review — world_to_frame called twice per grid inside run_export (R2's point was "inside run()", not "once"); held_bytes excludes prepared lines (shared with the live engines); residency judged against the budget left — each is the reviewer's to challenge.
Task 1: implementer DONE after R12 (ee7ff34, amended from 6483fbf; pushed). Finest fitting pixel by estimate: 0.021 m at a 0.025 m cell, 0.016 m at a 0.05 m cell. Review dispatched (opus, agent a274695741b7c7e04).
Task 1: review Approved, spec ✅, 0 Critical/Important. R13 deviations accepted by the reviewer on the merits.
Task 1: ⚠️ resolved: unpushed → pushed (ee7ff34 on origin). Carried forward: T5 snapshot must share the live engines' PreparedLine objects (held_bytes excludes lines); This grid passes gain 1.0 and method "none"; T4's finest-fit bisection calls estimate_export (covered_cells over every trace) on the GUI thread — measure there; kriging plan_fill is not interruptible (~14 s a grid at 0.025 m) so a cancel in band 0 can take that long (T3/T5 know).
Task 1: minor (deferred): window bounds + pixel centres copied verbatim from SiteEngine._gather (export_pipeline.py:290-293, :341-345) — share a Qt-free helper.
Task 1: minor (deferred): CRS test says "never per band" with a one-band spec — use two windows.
Task 1: minor (deferred): stop-inside-the-solve test can pass if the solve polls only twice — spy on CurvaturePlan.solve/SolveStopped.
Task 1: minor (deferred): pytest.approx on a dict of tuples is exact equality (test :193, _same :162) — compare numbers.
Task 1: minor (deferred): real-data threshold mean() > 0.95 can be .all().
Task 1: minor (deferred): docstrings wrong — OVERVIEW_FACTOR comment (:129), frame_lattice "south-west" (display.py:281, it is north-west), SiteLattice "whole multiples of pixel" (site.py:51).
Task 1: minor (deferred): previous band's layers/array kept alive through the next band — del after yield.
Task 1: minor (deferred): coverage-only estimate counts fill weights it never builds (:226).
Task 1: minor (deferred): no-Qt import test checks PyQt5 only — add PyQt6.
Task 1: minor (deferred): export_pipeline.py passes the CI mypy config — add it to the CI mypy line.
Task 1: note: reviewer corrects the report — compose_footprints takes layers one at a time, so lazily built per-grid taps would cap the taps term (follow-up already in the docstring; costs re-tapping each band and a per-band transform).
Task 1: complete (commits 98a4efd..ee7ff34, review clean)
Task 2: dispatched (base ee7ff34, implementer agent a706bdf67c247eb66, sonnet)
Task 2: implementer DONE (4e374dc, pushed). Concerns: progress_band(done) counts bands written 1..n; coverage companion also tagged RESAMPLING=bilinear; crs_wkt field (default None) on both plans — T5 must fill it on the GUI thread; write_style raises OSError; old write() still uses catch_warnings until T5.
Task 2: review dispatched (opus, agent a89a8a85d35d6ddc7)
Task 2: review Needs fixes — spec ❌ (coverage files tagged bilinear; creation-options test not rewritten), Important 3 (false bilinear tag on counts; osr CRS route breaks USER: custom CRSs; write_style duplicates SliceLayer._apply_renderer).
- Ruling R14: a counts file's resampling key is `NSGEO_RESAMPLING=largest_count` (This grid) / `NSGEO_SITE_RESAMPLING=largest_count` (site companion) — the key names how the file was made (§5.4: the largest count among in-frame positive-weight corners); omitting it loses that — costs a key-value rename if the author prefers another word.
- Ruling R15: the writer resolves the CRS with `QgsCoordinateReferenceSystem(authid).toWkt()` (allowed off the GUI thread — R2 builds CRS objects in run() too; the thread rules forbid widgets and layers, not CRSs), raising a plain error when invalid; the osr route and the `crs_wkt` field go — one route, which handles USER: CRSs as today's path does — costs re-adding a field if a QGIS version proves unsafe off-thread.
- Ruling R16 (⚠️ confirmed as gaps): `write_bands` refuses a plan without its export lattice/cell/pixel instead of falling back to the live cell (the anti-goal "metadata names settings it was not made with"); `build_overviews` takes an optional `should_stop` and passes GDAL a progress callback that cancels (raises ExportCancelled), so a cancel during overviews is prompt (Review Focus 1) — costs one parameter each.
Task 2: minor (deferred): overview test skips the edge columns with a constant field (NEAREST would pass) — use distinct edge values; measured mixed column = 2.0 from 1.0/3.0.
Task 2: minor (deferred): GDAL UseExceptions FutureWarning in test output (pytest resets filters) — add a pytest filterwarnings entry.
Task 2: minor (deferred): StretchSample docstring overclaims (per-band share, not total); stride can alias row width — offset/per-row stride.
Task 2: minor (deferred): Close() in finally can replace an in-flight ExportCancelled with RuntimeError.
Task 2: minor (deferred): This-grid finish/azimuth tags written by two copies (write_bands.tag_dataset vs old write) — goes with R10.
Task 2: minor (deferred): write_bands not on the SliceWriter/SiteWriter Protocols.
Task 2: minor (deferred): two assertions check nothing (test_plugin_site_export.py:379 self-identity; style test mapLayers non-empty).
Task 2: minor (deferred): catch_warnings test lists functions by hand — check module-wide excluding old write.
Task 2: carried to T3/T5: progress_band(done) is 1..n, return ignored (cancel via the band iterator); discard_partial must also run when build_overviews fails; the .qml saves all categories incl. temporal (disabled) → apply temporal properties after adding the layer (today's order).
Task 2: fix round 1 implemented (dafee9f, pushed); carried to T3/T5: SiteExportPlan.coverage=True must be set on the site counts plan or the companion is tagged bilinear. Re-review dispatched (sonnet, agent aeb04632e5517f521).
Task 2: fix round 1/5 (6 addressed, 0 open — counts tag largest_count, Qgs CRS route, apply_renderer, creation-options test, refuse missing settings, overview stop; commits 4e374dc..dafee9f)
Task 2: minor (deferred): no end-to-end test that write_site_coverage / old GeoTiffSiteWriter.write tag the companion largest_count (check T3/T5 wiring of coverage=True).
Task 2: complete (commits ee7ff34..dafee9f, review clean)
- Ruling R17: ExportTask writes BOTH partials (values file, then coverage companion) before committing either; any cancel or failure discards both partials and leaves both existing targets alone; overviews are built on the partial before commit — committing the values file and then failing on the companion would leave a new file beside an old companion, a mismatched pair — costs a second partial on disk at once (the companion is one band, small).
- Ruling R18: `setDescription` is not documented thread-safe; the worker stashes the latest (band, n, grid) on the task and calls `setProgress` (thread-safe); a GUI-thread slot on `progressChanged` sets the description. The implementer may use `setDescription` from run() directly only if QGIS's source shows it safe — costs nothing if wrong but a race if ignored.
Task 3: dispatched (base dafee9f)
Task 3: implementer agent ac71d9c6052524094 (sonnet)
Task 3: implementer DONE_WITH_CONCERNS (89556aa, pushed). Concerns: start_export True ⇒ on_done fires once (addTask 0 → on_done error, True); False only when one is held (no on_done); extra kwarg what; R18 via progressChanged slot, progress nudged 0.01 band per grid; 2nd os.replace failure after the 1st is unavoidable non-atomicity; tests fake run_export/build_overviews; RED by mutation only (module written before tests).
Task 3: review dispatched (opus, agent a927305dc18a6fd78)
Task 3: review Needs fixes — spec ❌ (§6.2 description doesn't follow grid/band at real band counts: setProgress emits only on 0.1% steps; reproduced at 120 bands), Important: (1) that; (2) unscoped QgsTask.CanCancel / QgsTask.Queued break PyQt6 / QGIS 4.2 CI leg; (3) engine-spy test vacuous (faked pipeline, unsound spy) and no real-stack cancel test for Review Focus 1.
Task 3: minor (deferred): success test can't tell the two files apart — limit/coverage_limit and clip/coverage_clip swaps survive (R6 unpinned).
Task 3: minor (deferred): failed companion commit after values commit returns ok=False, limit=None — T5 can't restyle the replaced values file.
Task 3: minor (deferred): `what or description` gives "Exporting Exporting slices".
Task 3: minor (deferred): mismatched coverage spec/target/plan accepted silently — validate on the GUI thread.
Task 3: minor (deferred): unguarded discard_partial calls in finally — a Windows PermissionError on the first leaves the second.
Task 3: minor (deferred): neither failure log is asserted (on_done raise; run() failure).
Task 3: minor (deferred): SiteExportPlan imported only for annotations — TYPE_CHECKING; writer/clip typed Any.
Task 3: minor (deferred): RED shown by mutation after the fact, not test-first.
Task 3: carried to T5: cancel running_export() on site_closed AND plugin unload (a reloaded module has _held=None while the old task writes); a cancel after the last check still commits ok=True → on_done re-checks the site is open before adding a layer; cancelling a queued task runs on_done re-entrantly inside cancel(); `error` is raw text → plain copy in T5; walkthrough: does the task list visibly repaint the description.
Task 3: fix round 1 implemented (d4ad545, pushed): describe pyqtSignal; scoped enums; vacuous spy deleted, real-stack min-curv cancel test with __getattribute__ recorder. Carried to T5: spy against the real snapshot.
Task 3: fix round 1/5 (3 addressed, 0 open — describe signal, scoped enums, real-stack cancel test; commits 89556aa..d4ad545)
Task 3: complete (commits dafee9f..d4ad545, review clean)
Task 4: dispatched (base d4ad545, implementer agent af14e514d9a5e7b7d, sonnet)
Task 4: implementer DONE_WITH_CONCERNS (84f33c7, pushed). Concerns: pixel spin 4 decimals (0.0125 must be typeable); finest cell strictly above current → 0.025/0.0125 reports "0.026 m cell would fit" though 0.025/0.025 fits; dialog appends the Disk row itself; preview called on GUI thread once per debounce + ~2·log2 extra when over budget; T5 removes layers_to_replace() before the task, deleteLater in finally; tests need the make-fixture teardown (flush DeferredDelete) or a late-destroyed dialog segfaults after exitQgis; pure helpers written before their tests (no RED).
- Ruling R4a (amends R4): the finest cell is searched from the current cell INCLUSIVE with pixel = cell; when the current cell fits at pixel = cell the cell sentence is dropped (None) and only the pixel advice shows — R4's "above the current one" made 0.025/0.0125 advise "a 0.026 m export cell", which is noise when 0.025/0.025 already fits — costs nothing.
Task 4: review dispatched (opus, agent a192832408fcdf93e), told R4a
Task 4: review Needs fixes — spec ❌ (R4a not met; low-disk copy names the bare estimate as "needed" while refusing at 1.2×; reason label sits outside the group), Important 2 (R4a; disk copy).
- Ruling R19 (⚠️ confirmed gap): one companion-naming rule — `coverage_path(target) -> Path` beside `partial_path` in slice_export.py, `<stem>_coverage.tif` as today's code (plugin.py:1019/1205, site_export.py:411); the dialog's `target_paths` and Task 5 both use it — the dialog's `{stem}_coverage{suffix}` would miss an open companion for a `.tiff` target and Windows would lock it — costs nothing.
Task 4: minor (deferred): finest_fits hangs for cell < 0.0005 (cell_mm == 0) — guard with ValueError.
Task 4: minor (deferred): no guard around refresh_now — a raising preview leaves Export disabled with a stale summary and no reason.
Task 4: minor (deferred): Disk row and disk copy built in the dialog, not pure in slices_plan.
Task 4: minor (deferred): typing a path re-runs the full preview (incl. finest_fits) — only Disk depends on the path.
Task 4: minor (deferred): relative paths and ~ not handled; target_paths has no direct test.
Task 4: minor (deferred): pixel spin shows 0.0500 beside 0.050; title fixed "Export GeoTIFF" (mock-up: "Export site GeoTIFF"); _set_rows doesn't hide removed labels; File row drops "tiled with overviews" (accepted).
Task 4: minor (deferred): tests — isinstance assert checks nothing (:314); debounce tests rely on 260 ms qWait vs 150 ms timer; pure helpers no RED; unreachable _on_export timer branch.
Task 4: carried to T5: cell_floor = largest included grid's smallest_safe_cell; preview cost on the GUI thread (2·log2+1 calls when over budget, covered_cells per grid per call) — measure; one export at a time; deleteLater in finally; remove layers_to_replace() before the task; site window title; a missing target directory passes the dialog and fails later.
Task 4: fix round 1 implemented (c63981b, 135682e docstring wrap; pushed)
Task 4: re-review dispatched (sonnet, agent a778ed891975cebf4); push retried OK
Task 4: fix round 1/5 (4 addressed, 0 open — R4a inclusive, disk copy 1.2×, reason in group, coverage_path; commits 84f33c7..135682e)
Task 4: complete (commits d4ad545..135682e, review clean)
Task 5: context file task-5-context.md written (built interfaces + 14 obligations carried from T1–T4 reviews and rulings)
Task 5: dispatched (base 135682e, implementer agent a228d2bf2af3623a6, sonnet)
Task 5: implementer DONE (0e77de4, pushed). Full QGIS tier 1693 passed before a last write_style edit (catches any exception); 73 re-run. Preview: ~105 ms per estimate → covered-cell cache: 1 ms per pixel change, ~105 ms per new cell. Concerns: other-CRS transforms point by point; plan_export keeps cell/pixel optional defaulting to live; snapshot builders before tests; removed SlicesDock.refining_paused; new export_flow.py, site_export_job, grid_export_job.
Task 5: review dispatched (opus, agent aa02d6b2e603095a9); push retried OK
Task 5: review Needs fixes — spec ❌ obligation 5 (replace path drops layers: coverage-off re-export removes the companion's layer for good; cancel/failure never restores removed layers), obligation 3 partial (plan_export silent live-cell default), obligation 9 tests can't catch a wrong limit/colormap. Important: I1, I2, I3.
- Ruling R20 (I1): remove only the layers whose source is a file this job writes (values file + its .qml; companion + its .qml only when this job writes the companion); on cancel or failure, add each removed layer back from its unchanged file (same name, its .qml applies) and say so in the message. Not `takeMapLayer`: a held layer keeps the file open, which is what decision 17 avoids on Windows — costs the layer's tree position and any unsaved in-session style edit after a cancel.
- Ruling R21 (I2): `plan_export`'s `cell` and `pixel` become keyword-only and required; the tests that relied on the default pass `engine.frame.cell` — Task 2 closed the live fallback on purpose — costs three test edits.
Task 5: minor (deferred): rotated This-grid test weakened to finite >= 0.9 × covered (test_plugin_slice_export.py:597); reviewer verified export == to_north_up(engine.finish) at 0/7/30/88°, kriging and none — restore the equality pin.
Task 5: minor (deferred): site dialog's live cell from dock.cell_spin (plugin.py:1077) — wrong after a refused resolution; use site.full_lattice.pixel (This grid uses engine.frame.cell).
Task 5: minor (deferred → known limit): other-CRS grids transform point by point with no stop check (4.4 µs/pt ≈ 18 s per 50 m grid at 0.025 m) — chunk with a stop check, or list it beside kriging's fill planning.
Task 5: minor (deferred): companion colour map swaps a bipolar palette for amp_black_high (plugin.py:1187) — not the coverage view's rule (palette + unipolar); say so or match.
Task 5: minor (deferred): write_style failure only logged (decision 13 promises a style file); unreopenable layer Warning followed by Info "exported…".
Task 5: minor (deferred): duplication — window_ns == band_window_ns; CountsClip third copy of counts stretch; two near-identical _ExportJob build closures; "already running" text twice; lattice_at computed up to 3× per site job.
Task 5: minor (deferred): R10 leftovers — SliceEngine.last_solve_ms no production caller; slice_layer.py:395 cites removed GeoTiffSliceWriter.write.
Task 5: minor (deferred): This grid's on_done doesn't check the grid still exists — state the ruling (finishes on its snapshot).
Task 5: minor (deferred): addTask 0 → Critical posted, then "exporting… keep working" after it.
Task 5: minor (deferred): _ExportJob.spec / coverage_spec typed Any.
Task 5: minor (deferred): over-budget finest-cell search ≈ 10+ new cells × 105 ms ≈ 1 s GUI stall per refresh — time it.
Task 5: ⚠️ full QGIS tier not re-run after the last write_style edit — run it in the fix round.
Task 5: fix round 1 implemented (e87fa53, pushed); full QGIS tier 1696 passed after the last edit.
Task 5: re-review dispatched (sonnet, agent a3eab4e7c8188a2da)
Task 5: fix round 1/5 (3 addressed, 1 open — new breakage in the restore path: a layer that can't be put back is skipped silently or reported with the wrong message, an exception aborts the rest of the batch; "as before" overstates (no temporal properties, no tree position); commits 0e77de4..e87fa53)
Task 5: minor (deferred): stale "plan_export keeps cell/pixel optional" line in the Task 5 report's concerns.
Task 5: fix round 2 implemented (337bcfa, pushed): per-layer restore with try/except, lost layers named, 'as before' dropped (wording only).
Task 5: re-review round 2 dispatched (sonnet, agent a7844ec8c76b0e708); controller ran CI mypy + ruff at 337bcfa
Task 5: fix round 2/5 (1 addressed, 0 open — restore failures named, per-layer try/except, wording; commits e87fa53..337bcfa)
Task 5: minor (deferred): lost-layer note says "add it again from its file" even for several layers (grammar).
Task 5: complete (commits 135682e..337bcfa, review clean)
Task 6: dispatched (base 337bcfa, implementer agent a596b1774629379c9, sonnet)
Task 6: implementer DONE (03d9554, pushed). Concerns: companion written only when Show coverage is ticked (guide says so); old refusal text replaced by a pointer; coverage wording not checked against binning.
Task 6: review dispatched (sonnet, agent a4cbafd4e7dc885da)
Task 6: review Needs fixes — Important 1: guide says "a cell with 0 had no line cross it"; uncovered cells are blank (NaN), never 0.
Task 6: minor (deferred): "a low number means one or two traces, rests on little" — at a 0.025 m cell 1–2 traces is normal; tie to cell size or compare with neighbours.
Task 6: minor (deferred): guide doesn't say the coverage companion gets its own style file.
Task 6: minor (deferred): README #157 line indented as a continuation of the Slices bullet — make it its own bullet.
Task 6: fix round 1 implemented (c84c715, pushed); re-review dispatched (sonnet, agent a68fbc8f4468837dd)
Task 6: fix round 1/5 (1 addressed, 0 open — coverage blank-cell wording; commits 03d9554..c84c715)
Task 6: complete (commits 337bcfa..c84c715, review clean)
All tasks complete. origin/main moved to d8acb01 (#160 placement corrections, #153 scopes agree, #154, #156); overlapping files: guide, README, slices_plan.py, site_scope.py, slices_dock.py, test_pure_slices_plan.py, test_plugin_site_scope.py. Merging main before the final review.
Merge of origin/main (d8acb01) in progress: controller resolved the two textual conflicts (README Done rows + link refs #157/#159, In progress removed; test_pure_slices_plan.py takes main's `method="kriging"` assertion and keeps the export tests). Semantic conflict: #154 made `estimate_memory(..., *, method)` required and counts the curvature plan; export_pipeline.py:199 calls it without `method` → needs an implementer (also check the export's own SOLVE term for double counting).
Merge: implementer dispatched to fix estimate_memory method + double counting and conclude the merge (sonnet, agent a73443e55efb8ab57); BLOCKED if 0.025/0.025 min-curv estimate passes 1.5 GB.
Merge: concluded as 791623b (pushed). Tests pure 281, core 982, QGIS 1741 passed; lint clean. Export min-curv estimate unchanged (export holds one CurvaturePlan per grid, no kriging preview; bench peaks agree).
Final review: dispatched (opus, agent ae9033928ea829a81) over d8acb01..791623b with final-review-ledger.md for triage.
Final review: With fixes. Critical 0. Important: I1 stale .aux.xml/.ovr sidecars survive os.replace → GDAL serves old statistics/overviews (verified GDAL 3.8.4); I2 R12 narrows spec §1/decision A for 120 m sites (finest ≈0.041 m cell; 0.05/0.025 refused at 120 m) — needs the author's decision, an issue, a README line; I3 rotated This-grid export not pinned vs to_north_up. Minor M1–M9. Triage: fix-before-merge = minor 6 (docstrings), 11 (overview edge test), 35 (=I3), 48 (=M9); rest can wait or moot.
- Ruling R22: I2 goes to the author as a decision (human gate before merge), not into the fix wave — it changes a spec promise; the fix wave does not touch the budget — costs nothing if the author accepts; a design if not.
- Ruling R23: the fix wave takes I1, I3, M1–M9, triage items 6 and 11, plus cheap can-wait items 10 (export_pipeline.py on the CI mypy line), 32 (expanduser), 36 (site live cell from full_lattice.pixel), 41 (R10 leftovers), 50 (README bullet) — one dispatch, as the process requires; M1 stops and reports if the 0.025/0.025 bench estimate passes 1.5 GB — costs one larger fix diff.
Final review: fix wave dispatched (sonnet, agent a874d06d934dace93). I2 put to the author.
Final fix wave: DONE_WITH_CONCERNS (b52966a, ec3ef98, b6da38b; pushed). Pure 282, core 982, QGIS 1760 passed; lint + CI mypy (export_pipeline added) clean. 0.025/0.025 estimate now 1259 MB kriging / 1282 MB min-curv (≤ 1.5 GB, ≥ measured peak). Counts overviews NEAREST (GDAL 3.8.4 has no MAX).
- Ruling R24: accept the new This-grid band key `NSGEO_WINDOW_NS` (site files already carry it; additive; it lets a restored layer get its time slider back) — key names are part of the format, so the author is told — costs a key to drop if the author objects.
Final fix wave re-review (opus): all findings ADDRESSED, no new Critical/Important. Residual minors parked (no second fix wave):
- parked — sidecar unlink inside commit_partial runs before values_written is set; an unlink error after os.replace is reported as a plain failure — Ruling: park; sidecars are not held open, and the fix (flag right after os.replace, best-effort unlinks) goes into any post-walkthrough fix round — costs a misleading message in a near-impossible case.
- parked — restore_band_times treats pre-branch companions as timed (no largest_count key) — Ruling: park; needs an old-version file open plus a cancelled replace — costs a stray time window on such a layer.
- parked — ExportCancelled docstring "raised by the writers"; half-written message punctuation ".;"; bench docstring "no smoothing" beside the re-run; plugin.py:1084 comment; site_export.py module docstring says NSGEO_SITE_RESAMPLING always bilinear; no plugin-level test of the "without the time slider" message — Ruling: park all for the post-walkthrough round — cosmetic or test-only.
Final review: clean. Deployed: profile ns_geo_export (copy of ns_geo) linked to this worktree. Walkthrough page drafted (scratchpad walkthrough-b).
Walkthrough published: https://claude.ai/artifact/HSTEtjgo8v9VjV4W1VsLFp (db collection results, empty at publish; 24 checks incl. Z1 the 120 m decision and Z2 the format keys). Decision record committed to docs/superpowers/sdd/2026-11-11-nsgeo-whole-site-fine-cells-b/ (7cedf3f, 551b237). Workspace kept until after the walkthrough (fix rounds may follow); retire it before removing the worktree.
Walkthrough (author, 2026-11-11 evening): 20 pass (D1 marked later: "looks good, not sure how much difference it made"), E3 + F3 skipped, B2 "fail", Z1 + Z2 pass. B2 = not a bug: the 2.8 GB seen was the File row (31.3 M px × 17 bands × 4/3); the real site's grids cover ~1400 m² vs the bench's ~4000 m², so 0.025/0.0125 fits there and 0.01 is refused — my page quoted bench numbers. E3 = Temporal Controller defaults (off, 1-hour frame) put every band in one frame (verified headlessly); pre-existing since M11. Missing coverage = Show coverage was off (author re-exported: present).
- Z1 accepted → #167 filed; spec decision A amended + README Wishlist (8862ded, pushed). Z2 keys accepted.
- Ruling R25: post-walkthrough round = Temporal Controller fitted on export/restore + guide; Memory row in the summary; the parked minors; then an opus review; then a real-data memory check at 0.025/0.0125 on a copy of the site (QGIS closed) — author said "go ahead with your plan" — costs one more walkthrough of the controller.
Walkthrough fix round: BASE 8862ded; brief walkthrough-fix-brief.md; implementer dispatched (sonnet).
Walkthrough fix round: implementer DONE_WITH_CONCERNS (7f0ce65 e10d92a 6a92efb 2025658 d2b8ba2, pushed). QGIS 1782, pure+core 1265 (5 skipped); lint + CI mypy clean. Concerns: extent rule changed (extent ends 1 ms short of n·frame after the first start, else n+1/n+2 frames); 4.2 not run; panel follow not observed; test-first loose on small items. Review dispatched (opus).
Walkthrough fix round: review dispatched (opus, read-only) on 8862ded..d2b8ba2; real-data memory check dispatched (sonnet) — QGIS closed, 9 GB available.
Real-data memory check: DONE (real-data-memory-report.md). Kriging, background normalisation, 17 windows, 3 bands run. 0.025/0.0125: estimate 1309.8 MB vs tracemalloc peak 1239.3 MB (+5.7%); 0.025/0.025: 535.9 vs 464.6 MB (+15%). Band 0 ~50 s (setup), later bands 0.3–0.8 s. Estimate holds on real data at the gated setting. Not covered: min-curvature solve term on real data (site uses kriging).
Walkthrough fix review (opus): spec ❌ quality ❌ — Critical 0, Important 3 (I1 min-gap frame drifts on long small-step exports: 288/4500 swept cases fail; I2 saved project does not reopen set up — panel mode not saved, QGIS saves layer band ranges at whole seconds; I3 guide's by-hand set-up impossible, file has no band times), Minor 5. Panel follows programmatic change (verified in the real app). CI red since 551b237: pytest 9.2 nested approx at test_pure_export_pipeline.py:164.
- Ruling R26: mean-step frame, extent 2 ms early, ceil count; one band ≥1 s — the reviewer's sweep shows zero failures — costs nothing visible.
- Ruling R27: no time-scale change; band times come from the file's NSGEO_WINDOW_NS whenever a layer is added (layersAdded hook: export, restore, project open, by hand) + controller re-fit that survives project read; verified in the real app — format stays, author already chose the keys (Z2) — costs a hook on every raster added (cheap metadata read, guarded).
- Ruling R28–R31: guide rewritten to what is true; M2 name rule only without an interpolation key; M5 test made able to fail; CI pytest 9.2 fix.
Walkthrough fix round 2: brief walkthrough-fix-2-brief.md; implementer resumed (SendMessage).
Walkthrough fix round 2: DONE_WITH_CONCERNS (ae6bf88 52192a7 6bb83a0 efdfcda 50935c0, pushed). Pure+core 1265, QGIS 1970; CI green on 50935c0 after one re-run (refine timing flake, untouched code). Reopen verified in the real app (offscreen --code) at 17 and 200 bands; project time setters dropped; export/restore fit directly and via the hook. Re-review dispatched (opus).
Walkthrough fix round 2 re-review (opus): all 11 findings ADDRESSED; no new Critical/Important; 3 new Minors (N1 reopen test passes without the refit; N2 repaired layers / plugin enabled on an open project not timed, guide overclaims; N3 guide: project opened without nsgeo keeps whole-second times, say "installed and enabled").
- Ruling R32: one small round 3 by the same implementer: the reviewer's refit-pinning test (N1), time already-open layers when the plugin starts (N2, cheap: same handler over mapLayers()), guide wording for repaired layers and projects opened without nsgeo (N2, N3); I check the diff myself, no further review — costs a minor slip to the PR review.
