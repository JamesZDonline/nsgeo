# Task 2 report

Commit 89707a7, pushed.

Implemented in ui/profile_view.py: `set_axes(..., ruler=)` (ruler dropped without distance_along or with fewer than 2 traces), `ruler` property, `window_m`, `set_window_m`, `_distance_caption`, `NO_DATA_HATCH`, hatch + painter-flipped drawImage over `target_span`, ascending `_selection_bounds`, ticks via metres_at/trace_units_at (column centre), `trace_at` gating for hover, pick and velocity clicks, `traces_between` drag-select (blank-only drag clears and emits selection_cleared), fit keeps bounds/mirrored, one_to_one via the transform, clear drops ruler. Module docstring paragraph added.

TDD: RED = test file collection ImportError (cannot import NO_DATA_HATCH), as expected. GREEN = `test_plugin_profile_view.py`: 101 passed.

Full tier: core+pure 827 passed, 3 skipped. QGIS 1181 passed (1165 baseline + 16 new). ruff check and format clean. mypy clean (37 files).

Files: packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py, packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py.

Self-review: make_view supports several views, but the caption test uses `view` as the brief wrote it. Release handling: a drag whose selection ended up cleared (blank-only) takes the click path. The hatch is also painted for unruled views (full-width data, so invisible).

Concerns: none.

## Fix round 1

1. One-trace line with a distance: `_distance_ticks` now returns [] for `n_traces < 2` (after the trace-tick fallback for no distance / 0 traces). New test `test_a_one_trace_line_with_a_distance_paints_its_axes_without_error`. RED: IndexError at ruler.py:30. GREEN after the guard.
2. one_to_one test: the ruled fixture's 360-unit bounds made 1:1 clamp to the full bounds. The test now re-sets axes with a Ruler("A","y",-12,16) (1680 units), zooms 8x, and asserts trace_hi is unchanged, span == width, still mirrored. Mutation check: removing the mirrored branch in `ViewTransform.one_to_one` (old trace_lo anchoring) makes it fail; restored afterwards.
3. Hatch: the test scans 30 pixels, requires all in {BACKGROUND, NO_DATA_HATCH} and at least one NO_DATA_HATCH.
4. Wheel: sends a real QWheelEvent (one notch) at x_of_trace(100.0); asserts the trace under the pointer is unchanged and the span shrank.

Result: `test_plugin_profile_view.py` 102 passed (RED run: 2 failed, 100 passed); ruff check/format and mypy clean.
