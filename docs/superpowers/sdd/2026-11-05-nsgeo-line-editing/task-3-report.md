# Task 3 report: slices see the new positions

Commit de3529f on nsgeo-line-editing (pushed). Status: DONE.

## Implemented
- slices_engine.py: `_placements` (label-free, captured in set_source next to `_grid_fp`, emptied in set_source's reset and clear()); `_without_label`, `had_line`, `placements_changed` (uses line_edit.same_placement tolerance for GridPlacement), `_on_grid` helper, `_on_lines_changed` (connected right after grids_changed, disconnected in dispose()). Hook set -> `_hand_over_the_move`; else set_source with the choice narrowed to keys still on its grid, guarded and reported as "could not re-prepare after a line moved: ...". set_source's job loop skips and reports a key now on another grid.
- slices_dock.py: `_sync_included` prunes to `_default_included(grid_id)`; new elif in `rebuild_source` (placed before the #72 finish-moved elif) re-prepares when a line moved onto a default-choice grid; `restore_cube` drops moved keys, falls back to default when none remain, emits the "moved to another grid since it was saved" message after prepare. Added `from pathlib import Path`.
- Imports `GridPlacement` via `nsgeo.geometry` (the boundary test forbids `nsgeo.geometry.placement`).

## Tests
New: 7 engine, 4 dock, 1 site-scope, as in the brief (dock tests use `docked_two_grids`, which already has grid B).
RED (impl reverted via patch, never stash): 8 failed, 4 passed. Failures: no re-preparation on placement edit (`1 == 1+1`), moved key still in choice/prepared lines/included_keys, hook never called, no "now on grid" report, restore kept the moved line, site view never queued B. The 4 passes are pinned negatives (outside-source, label-only, imported-stale, length change once; the last already holds because grids_changed re-prepares once).
GREEN: three focused files 323 passed; whole QGIS tier 1523 passed (13m16s, run before the cosmetic import-path change; three focused files re-run after). core+pure 1015 passed, 3 skipped. ruff check/format, mypy clean.
Existing tests changed: none.

## R-P5 / trap 1 / refiner
No new way to start a preparation: with `on_grid_moved` set (site scope's This grid = `_mark_grid_stale`; SiteEngine's per-grid engines re-queue) the slot only calls `_hand_over_the_move`, exactly as a grid move does. Without the hook it calls set_source, which cancels-and-confirms first. Hook test asserts nothing runs and the engine is cleared; site-scope test asserts only B is queued. The refiner needed nothing: the re-prepare goes through set_source/clear(), which the grid-move path already uses; test_plugin_refine* stayed green in the full tier.

## Self-review
- Complete against brief. Slot order is as specified (engine slots before the dock's rebuild_source).
- A line removed in the same change as a move is tolerated (`_on_grid` returns False on KeyError).
- Dock `restore_cube` leaves keys absent from the site alone, for set_source to name (as before).

## Concerns
None blocking. The full-tier run predates the one-line import change; the boundary test it fixed is in core+pure (green) and the three slices files were re-run.

## Fix round 1: a reorder is not a change of lines (Important 1)

Finding on order: a cube does not depend on `line_keys` order except float rounding. `nsgeo/slices/binning.py` `accumulate` (l.129-147), `build_cube` (l.186-) and `stream_slice` (l.205-) add each line's contribution into shared `total`/`count` arrays (`+=` / `np.add.reduceat`). So I compared as sets.
Changes:
- `SourceChoice.same_source(other)` in slices_plan.py (grid, preset, transform, set of keys).
- slices_dock.py: `_refresh_source_status` compares keys as sets; `prepare()`'s no-op guard uses `same_source`.
- site_engine.py `set_source`: `choice.same_source(old.get(grid_id))`, so a reorder no longer re-queues a Whole site grid.
- slices_engine.py `_on_lines_changed` narrows in survey order (`session.keys()`), so reorder plus edit leaves the engine choice in the dock's order.
Tests (test_plugin_slices_dock.py): `test_a_reorder_alone_is_no_change_to_a_default_source` (no preparation, choice untouched, status "prepared · 3 lines"), `test_a_reorder_with_an_offset_edit_re_prepares_once_and_reads_prepared`. RED without the source change: both failed ("stale · the lines changed since this was prepared"; choice in old order). GREEN with it.
Runs: whole QGIS tier 1525 passed (14:00); core+pure 1015 passed, 3 skipped; ruff check and format clean; mypy clean.
No Whole-site-specific test added for the reorder (covered by the shared `same_source`, and the site-scope file stays green).
