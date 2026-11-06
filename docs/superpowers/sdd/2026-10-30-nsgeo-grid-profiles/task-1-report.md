# Task 1 report: pure mapping (mirror, bounds, ruler)

Commit 2f957f4, pushed to origin/nsgeo-grid-profiles.

## Implemented
- ui/ruler.py: trace_to_metres/metres_to_trace (moved verbatim, renamed), trace_units_at, metres_at, is_reversed, Ruler (+key), ruler_for, bounds_on. Module docstring states the column-centre convention.
- ui/view_transform.py: mirrored/bounds fields, fit kwargs, trace_bounds, _column_at (shared unclamped lookup), trace_index_at (clamped), trace_at, traces_between, _visible_data, source_rect (visible part only), target_span, with_window (clamps to trace_bounds), mirror-aware zoomed/panned, one_to_one, resized. R1: bounds validated before the axes check.
- profile_dock.py: old helpers deleted, import from ruler, three call sites updated. ci.yml: ruler.py in the mypy list.
- Tests: new test_pure_ruler.py (6), 12 new in test_pure_view_transform.py (+ `import dataclasses`); existing tests unchanged.

## TDD
- RED ruler: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_ruler.py -q` -> ModuleNotFoundError: No module named 'nsgeo_qgis.ui.ruler' (expected).
- RED VT: test_pure_view_transform.py -> TypeError: ViewTransform.fit() got an unexpected keyword argument 'mirrored' (expected).
- GREEN: core+pure `826 passed, 3 skipped` (baseline 808 + 18).

## Verification
- core+pure: 826 passed, 3 skipped.
- ruff check + format --check: clean. mypy (CI command incl. ruler.py): no issues in 37 files.
- QGIS test_plugin_velocity_fit.py: 51 passed.

## Files
ruler.py (new), view_transform.py, profile_dock.py, ci.yml, tests/pure/test_pure_ruler.py (new), tests/pure/test_pure_view_transform.py.

## Self-review
- Fix made along the way: ruler.py first imported `nsgeo.geometry.grid`, which test_plugin_boundary rejects; now `from nsgeo.geometry import Grid`.
- Choices beyond the brief: traces_between of a zero-width span on a column boundary still returns the column on its screen-right side; _visible_data for an all-blank window returns an empty span at the clamped position.
- No extras added.

## Concerns
None. The profile_dock call sites still use the old non-centre convention (Task 3 territory).

## Fix round 1: traces_between shares the column lookup
- Changed: `traces_between` now takes `sorted((_column_at(x0), _column_at(x1)))` and clamps into the data, so it agrees with `trace_at`/`trace_index_at` on column boundaries. Correction to the report above: a zero-width span returns the column `trace_at` returns (screen-right for forward, the screen-left-edge column when mirrored), not "screen-right" in both.
- New test `test_traces_between_agrees_with_trace_at_on_column_boundaries` (forward and mirrored 1:1, px 0/10/11/799, plus `FIT.traces_between(0.0, FIT.x_of_trace(19)) == (0, 19)`).
- RED (same pytest command on test_pure_view_transform.py before the change): `assert None == (1999, 1999)` from `traces_between(0.0, 0.0)` (mirrored 1:1 window starts at 1200..2000 after clamp; old code was off by one at boundaries).
- GREEN: view_transform + ruler tests `37 passed`; ruff check/format clean; mypy no issues in 37 files.
