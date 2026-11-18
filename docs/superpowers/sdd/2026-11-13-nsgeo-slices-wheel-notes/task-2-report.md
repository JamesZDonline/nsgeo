# Task 2 report: Warnings section

## Implemented
- New `ui/warnings_panel.py` (Entry, REFUSAL/WARNING/NOTE, ICONS, WarningsPanel; Ignored-width wrapped labels).
- `SlicesDock`: `warnings_panel` after `position_group`, `_grid_refusal`, `show_warnings()` (guarded), `_set_cell_floor(grid_id)`; `site_note` removed; frame-cap refusal now a standing refusal (no toast); cleared on grid change and scope switch; `restore_cube` raises the floor first.
- `SiteScope`: `drawn`, `warnings()` replaces `show_note`; engine-refusal branch of `apply_resolution` no longer toasts; `_then` removed.
- `SiteEngine.geometry_problem`; `_rebuild_geometry` wraps `_rebuild_geometry_now`; reporting variant logs and records the problem; `clear()` resets it.
- `preview_note` new copy.

## Deviations (flagged)
- Brief's geometry-failure test monkeypatches `_rebuild_geometry` itself, so `_rebuild_geometry_reporting` also records `geometry_problem`; and `refresh_slice` treats a site with a `geometry_problem` as not drawn (`drawn` requires `geometry_problem is None`), otherwise the REFUSAL never shows over a stale lattice.
- Ruling 1 applied to the clock-warning test (drawn: [WARNING, NOTE] (panel order); not drawn: [REFUSAL, WARNING]).

## TDD
RED was not captured before implementing (tests and code were written in one pass). Checked after the fact that the floor test fails without the `restore_cube` floor line (`assert 0.05 == 0.15 +- 0.001`); the geometry-failure test failed twice on first run (no problem recorded; then refusal hidden while "drawn") and drove both deviations above.
GREEN: four QGIS files + pure tier, see reply for final counts.

## GREEN
Command: `QT_QPA_PLATFORM=offscreen ../../.venv-qgis/bin/python -m pytest -p no:xonsh packages/nsgeo-qgis/tests/qgis/test_plugin_{warnings_panel,slices_dock,site_scope,site_engine}.py -q`
Output: `413 passed in 393.13s`
Pure: `../../.venv/bin/python -m pytest -p no:xonsh packages/nsgeo-qgis/tests/pure -q` -> `301 passed, 1 skipped`
ruff check and ruff format clean.
Ruling 1 fix: the test now asserts panel order (drawn: WARNING, NOTE; not drawn: REFUSAL, WARNING).

## Fix round 1
Changes:
- Both dock tests now call `_ready(dock)`; the width tests use `"x" * 400` and assert the panel is visible at measure time (dock and site tests).
- Coming-and-going test: long entry first, bar to max, then `set_entries([])`, waits 100 ms (`processEvents` alone did not shrink the range), asserts the scroll value changed, dz kept focus and 0.75.
- (a) `restore_cube` sets the cell floor before `if recipe.resolution is not None`.
- (b) Reporting wrapper no longer records the problem; the geometry-failure test patches `_rebuild_geometry_now`.
- (c) Renamed the four tests; (d) added a `clear()` resets `geometry_problem` assertion.
Mutation checks:
- Removing `setSizePolicy` from warnings_panel: both width tests fail (`3626 == 475`, `3626 == 415`). Restored.
- Guard mutated to `bar.valueChanged.connect(guard.let_go)`: coming-and-going fails (`dz_spin.hasFocus()` False). Restored.
Tests: slices_dock, site_scope, site_engine, warnings_panel whole with `-p no:xonsh`: `413 passed in 363.46s`. ruff check/format clean.
