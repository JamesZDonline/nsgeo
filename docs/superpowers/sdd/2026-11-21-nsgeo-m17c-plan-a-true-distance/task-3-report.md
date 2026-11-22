# Task 3 report: trace axis + view transform in metres

Implemented `ui/trace_axis.py` (`TraceAxis`, frozen, eq=False; derived extents/runs cached in init=False fields set in `__post_init__`, which also validates) and the `ViewTransform` axis branches (`axis` field, `fit(axis=)`, `x_of_walk`/`walk_of_x`, `with_walk_window`, `paint_spans`, `true_scale_window` -> `_true_scale_walk`). `axis=None` runs the existing code, untouched (branch at top of each method).

R3: end trace reaches half its own step outward, capped at half a usual step when that step is a gap (uncapped otherwise: interior traces run halfway across any non-gap step, so the ends match).
Zero-length steps: `units_at_walk` falls back to usual-step extrapolation when the ruler's end extrapolation divides by zero; `trace_at_walk` searches only traces with nonzero width.

TDD: RED = collection error `ModuleNotFoundError: nsgeo_qgis.ui.trace_axis` for both test files; then GREEN after implementing. Two of my own tests were wrong first time (a probe at 0.03 on a trace boundary; a window wider than the bounds) and were corrected.
Tests: core+pure full: 2221 passed, 1 failed (boundary test: plugin may only import core's named API) -> fixed by exporting the spacing names from `nsgeo.geometry`; boundary + trace axis + view transform + ruler re-run: 72 passed; core geometry tests pass; ruff check/format clean.

Files: ui/trace_axis.py (new), ui/view_transform.py, tests/pure/test_pure_trace_axis.py (new), tests/pure/test_pure_view_transform.py (appended only), and core `nsgeo/geometry/__init__.py` and core README (re-export check_gap_m, gap_steps, left_out, usual_step from `nsgeo.geometry` with README rows; required by the plugin-boundary and README-names tests, outside the task's file list).

Concerns / notes for Task 4:
- `paint_spans` x0/x1 are the run's extent clipped to the window; first/last are trimmed to the run's traces meeting the window. For an edge-clipped run the image-to-rect mapping must use `axis.drawn()` for the unclipped extent.
- Zoom/pan work in walk metres but `with_window` still clamps in trace units (MIN_TRACE_SPAN, bounds), so at the bounds the walk span can change slightly.
- `_column_at` is not used with an axis (the three public lookups branch before it).

## Fix round (review)
Changes: R3 wording corrected and pinned (3x non-gap end step reaches 1.5 usual outward; lift case asserted outward and inward at half a usual step); the gap-edge test now starts the window at the gap's centre, asserts the edge is in the gap, then zoom/pan/Fit width/1:1; R10: `paint_spans` returns `(x0, x1, c0, c1)` with fractional source columns (tested on a clipped window: c0 == 10.3; mirrored runs the source the other way, documented); `traces_between` axis tests; real mirrored paint_spans assertion; dead test lines removed; zero-length axis refused and 1:1 guarded for a stationary patch (window returned unchanged); `ViewTransform.__post_init__` checks axis size == n_traces; TraceAxis copies the distance and its cached arrays are read-only; zero-end-step fallback commented; `_column_at` asserts `axis is None`.
Note: a run's c is the image column of the drawn extent; a lone asymmetric trace beside a gap (e.g. [gap-capped side narrower]) is stretched over its drawn extent, so c need not equal trace_of_x there. The linearity test covers multi-trace runs only.
Commands: ruff check/format --check clean, mypy clean; test_pure_trace_axis + test_pure_view_transform + test_pure_ruler: 75 passed; core+pure full: 2230 passed, 9 skipped, 19 xfailed.
