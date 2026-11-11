# Final fix wave — whole site at fine cells, milestone A

Branch nsgeo-whole-site-fine-cells, worktree /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-whole-site-fine-cells, head 08310e2 (origin/main merged in). Spec: docs/superpowers/specs/2026-11-10-nsgeo-whole-site-fine-cells-design.md (§5.3, §5.4, §5.5). Fix ALL items below in one pass; one or more commits.

## 1. The "leave out X" advice must be true (Important)

Today `stretching_grids` (packages/nsgeo-core/src/nsgeo/slices/site.py:159) ranks grids only by how much leaving each out shrinks the LATTICE, and `SiteEngine._rebuild_geometry` (site_engine.py ~692-697) passes those names into `preview_note` and `site_export_refusal`. When the COVERED-pixel limit is what forces the preview, the named grid does not lift it — real data: Nashville (7 grids) at 0.025 m says "leave out Grid4" but without Grid4 covered is still 9.68 M; the walkthrough site at 0.0125/0.015 m says "leave out Grid8" but is still a preview without it.

Controller ruling (binding):
- Name a grid only if leaving it out ALONE would let the site draw at full detail at the current cell under BOTH limits (`max_pixels` and `max_covered`): i.e. `fitting_lattice(remaining extents, cell, crs, max_pixels, max_covered).pixel == cell`. Order the qualifying grids largest lattice cut first (as now), at most 3. If none qualifies, the sentence/clause is omitted. Change `stretching_grids`' signature as needed (e.g. add `max_pixels`, `max_covered`), keep it pure, update its README row if its meaning changes, and update every caller.
- Both messages also name the FINEST cell that fits both limits, rounded UP to 0.01 m, found by stepping up from the current cell (an estimate from the pixel counts' 1/cell² scaling is a fine starting point, but verify with `fitting_lattice(...).pixel == candidate`). New exact copy (pure functions in packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py; add the parameter `finest: float`):
  - `preview_note`: `f"Preview at {pitch:g} m pixels: the grids are at {cell:g} m, but the site ({width_m:.0f} × {height_m:.0f} m) is too big to draw at full detail. It draws in full at a {finest:g} m cell or coarser."` + optional `f" Leaving out {name_list(stretching)} would also let it draw in full."`
  - `site_export_refusal`: `f"The site can't be exported at full detail yet: the site ({width_m:.0f} × {height_m:.0f} m) is too big at a {cell:g} m cell. Choose a cell of {finest:g} m or coarser"` + optional `f", or leave out {name_list(stretching)}"` + `"."`
- Tests: update the exact-copy tests; a core test where only the covered limit binds and the lattice-cut outlier does NOT qualify (no name); one where leaving out an outlier alone does qualify (named); a test of the finest-cell search (result fits; result − 0.01 m does not, unless it equals the current cell); an engine test with `max_covered` forcing the preview that asserts the note gives the finest cell and names no non-qualifying grid.

## 2. Coverage on a preview must not hide survey lines (Important)

When Whole site is a preview at pitch p = cell·2^k (k ≥ 1), `compose_footprints(..., counts=True)` (site.py ~253) samples each grid's counts with `sample_counts`, which reads only the 2×2 cells around each preview pixel's centre, so whole one-cell-wide lines are never read (probe: axis-aligned 20 m grid, lines one cell wide every 0.5 m: 20/40 lines shown at 4×, 10/40 at 8×, 0/40 at 2× with the grid origin offset 0.025 m). Spec §5.4: no trace count may be hidden by the pixel rule.

Controller ruling (binding): when the site is a preview at 2^k × the cell, coverage ticks first MAX-POOL each grid's counts over a 2^k-cell neighbourhood (a pure core helper, e.g. `max_pool_counts(counts: np.ndarray, n: int) -> np.ndarray` in resample.py or site.py, exported and README-listed if public; implement with `np.fmax` over shifted copies so NaN — i.e. zero counts — is ignored; choose the neighbourhood so every cell lies within the pooled reach of some preview pixel's 2×2 corners), then `sample_counts`. Amplitude ticks are untouched. Apply it where the site composes coverage (site_engine `slice_at` coverage path → compose), keyed off `is_preview` / the lattice pitch vs the cell. Tests: the probe above as a core test (all 40 lines reach some pixel at 2×, 4×, 8×, with and without a 0.025 m origin offset; must fail without the pooling) and an engine-level coverage test on a forced preview.

## 3. Coverage export must not be chosen by `finish is None` (Minor, plan defect — fix now)

`slice_export.py:270` picks the counts sampler with `counts=plan.finish is None`, and `ExportPlan.finish` defaults to None while `plan_export`'s docstring (~149-150) says finish "changes no band, only metadata" — a future amplitude plan without a finish would blank every non-positive amplitude. Add an explicit field to `ExportPlan` (e.g. `coverage: bool = False`) set by `write_coverage`, use it in the writer, update the docstring, and add a test that an amplitude plan with `finish=None` still writes a blend (negative values survive).

## 4. Small items

- display.py ~:260 comment still says "about 17 bytes a pixel" — it is ~52 B per point (two cached plans can hold hundreds of MB for very large rotated frames); say so.
- test_plugin_site_scope.py ~:3173 `assert dock.engine.wait_for_preparation(20_000) or True` can never fail — replace with a real prepare-and-wait.
- resample.py module docstring (~:17-19): say that coverage takes the largest count among the in-frame corners with POSITIVE weight.

## Verification

Run: test_slices_resample.py, test_slices_site.py, test_slices_display.py, test_public_api.py (core); test_pure_slices_plan.py and test_plugin_boundary.py (pure); test_plugin_site_engine.py, test_plugin_site_scope.py, test_plugin_site_export.py, test_plugin_slice_export.py, test_plugin_slice_export_dialogs.py (QGIS); ruff check/format; CI mypy. Each new test must fail on the defect it names (probe with temporary edits, reverted; PYTHONDONTWRITEBYTECODE=1).
