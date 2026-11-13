# Task 4 report

Commit a9b55e2 (local; `git push` FAILED: could not resolve host github.com - sandbox has no network. Needs a push from the controller).

## Implemented
- core site.py: `fitting_lattice`, `stretching_grids`; exported from `nsgeo.slices`; README rows added.
- slices_plan.py: `SITE_MAX_PIXELS = 16_000_000` (table in comment), `name_list`, `preview_note`, `site_export_refusal` (exact copy).
- site_engine.py: `max_pixels`, `full_lattice`, `is_preview`, `preview_note`, `export_refusal`; `_rebuild_geometry` never refuses for size (draws `fitting_lattice`, sets note/refusal); `_covering_lattice` replaced by `_grid_extents`; `held_bytes` adds gathers' taps bytes (ruling 1); cleared in `clear()`.
- site_export.py: `plan_site_export` raises `RuntimeError(export_refusal)` first.
- bench_site.py: `--lattice-scale` (step multiplier; lean run reporting compose median, tracemalloc peak on compose_footprints, gathers bytes; site limit lifted).

## TDD
RED (engine/export tests, before implementation): 5 failed (AttributeError is_preview) - preview, outlier, fits, gathers-taps, export-refusal. Core/pure tests were written together with implementation (no separate RED recorded for those). Mutation probe: disabling the refusal line in plan_site_export fails the export test (reverted). The preview test would fail if the engine raised (set_resolution would raise).
GREEN: all pass.

## Existing tests changed
- test_grids_too_far_apart_..._refused_by_pixel_count replaced by the preview test (per brief); unused MAX_FRAME_CELLS import dropped.
- test_plugin_site_scope::test_this_grid_names_the_memory_the_site_view_still_holds: expected `held` now adds the gathers' taps bytes (held_bytes counts them by ruling 1).
- New: held_bytes grows by exactly taps + weights after a tick.

## Step 5 table (10 x 20 m grids, kriging, no smoothing, 0.25 m cell, 64 samples; idle machine, load ~1.3, 15.9 GB)
| pixels | tick | compose median | transient | gathers |
| 4 M | 95 ms | 12 ms | 40 MB | 3 MB |
| 8 M | 100 | 19 | 80 | 3 |
| 12 M | 107 | 23 | 120 | 3 |
| 16 M | 109 | 29 | 160 | 3 |
| 24 M | 120 | 39 | 240 | 3 |
All meet <=250 ms / <=400 MB, so SITE_MAX_PIXELS = 16_000_000 (the cap). Gathers scale with grid area, reported only.

## Verification
core tests 795 passed, 28 skipped; QGIS files (site_engine, site_export, site_scope, pure plan) 254 passed, 1 skipped; ruff check/format clean; CI mypy clean.

## Concerns
- Push failed (no network).
- `is_preview` is derived from `export_refusal is not None` per the brief.
- Other callers of `site.lattice` in ui/plugin were not changed (Task 5); a preview lattice flows through them unchanged.

# Fix round 1

Changes:
- `SITE_MAX_COVERED_PIXELS = 5_000_000` beside `SITE_MAX_PIXELS` (16 M kept: the lattice-scale regime only grows 10 B/px accumulators). Comments now carry both tables and the corrected gathers sentence (~52 B per covered pixel).
- Core `fitting_lattice(extents, cell, crs, max_pixels, max_covered)` doubles until both limits hold; new module helper `covered_pixels` (sum of ceil(w/p)*ceil(h/p)); raises ValueError for limits that can never fit (`max_pixels < 4` or `max_covered < len(extents)`).
- `SiteEngine.max_covered`; `_rebuild_geometry` computes everything first and assigns `_site_z/_lattice/_full_lattice/_preview_note/_export_refusal` together at the end.
- Size-neutral copy for `preview_note` and `site_export_refusal`; exact-copy tests updated. `held_bytes` docstring names the gathers' taps.
- bench_site.py `--dense C...` (core only): two grids at 30 deg, 0.05 m cell.
- New tests: core covered-only doubling, never-fit guard, stretching order + `most`; engine `test_covered_pixels_alone_force_the_preview`. Existing engine/export tests set `max_covered` explicitly.

Dense table (`bench_site.py --dense 2 4 6 8`, idle, load ~0.5; repeat in brackets):
| covered | lattice | compose | transient | gathers |
| 2.0 M | 2.2 M | 81 ms | 69 MB | 104 MB |
| 4.0 M | 4.5 M | 167 ms | 138 MB | 208 MB |
| 5.0 M | 5.6 M | 239 ms | 173 MB | 260 MB |
| 6.0 M | 6.7 M | 241 ms (repeats 283, 262) | 207 MB | 312 MB |
| 8.0 M | 8.9 M | 353 ms | 277 MB | 416 MB |
6 M passed once, failed twice at 250 ms, so the choice is 5 M.

Verification: core 798 passed, 28 skipped; QGIS (engine, export, scope, pure plan) 255 passed, 1 skipped (`PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest <those four files> -q`); ruff check/format and CI mypy clean. No background loops left.

# Fix round 2

- Stretching test: NEAR now listed before FAR. Mutant (deleted `cuts.sort(...)`) now FAILS the test (1 failed, 38 passed); reverted (site.py diff clean).
- README `fitting_lattice` row names both limits.
- slices_plan.py comment: combined corner (16 M lattice, 5 M covered: 244-245 ms, 225 MB) and the ruling that coverage ticks (~1.8x, ~420 ms) are accepted.
- Run: `PYTHONPATH=packages/nsgeo-core/src .venv/bin/python -m pytest test_slices_site.py test_public_api.py -q` -> 52 passed, 5 skipped; ruff check/format clean.

# Fix round 3

`covered_pixels` is now exported from `nsgeo.slices` (+ README row) and site_engine.py imports it from `nsgeo.slices` with its neighbours (no `nsgeo.slices.site` import). Run: test_plugin_boundary.py 5 passed; test_public_api.py 13 passed; test_plugin_site_engine.py 55 passed; ruff check/format and CI mypy clean.
