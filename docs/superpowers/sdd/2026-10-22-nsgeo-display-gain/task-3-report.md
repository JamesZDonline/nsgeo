# Task 3 report

Commit 523d7f4, pushed to origin/docs/display-gain-design.

## Implemented
- gain_strip.py: `Headroom`, `set_headroom`, `set_trace`, `headroom`/`trace` properties, `x_of_amplitude`, colours, constants, band/trace/limit painting (each clipped inside limits in own colour, outside in red), blue ZERO_COLOUR, docstring paragraph. `paintEvent` now has try/except(log)/finally. Extra guards beyond the brief: a non-positive/non-finite limit is treated as no headroom; a trace whose length differs from the envelope is ignored; non-finite values are zeroed before drawing.
- profile_dock.py: `_push_headroom`, `_push_trace` (both self-guarded, `_log`), calls at end of `_render`, `_display_changed`, `show_gain_strip`, `_exit_preview` (the bare `show()` branch; the deferred branch goes through show_gain_strip), `_on_trace_changed` (push_trace only).
- docs/guide/getting-started.md bullet replaced verbatim.
- Tests: 14 new in test_plugin_gain_strip.py (FLAT/DEEP defined there per Ruling P3; local `curve_dock` fixture).

## TDD
RED: `pytest test_plugin_gain_strip.py` -> `ImportError: cannot import name 'Headroom'` (collection error). After strip implementation, 7 dock tests failed (`headroom` was None / AttributeError), the expected reason. GREEN: 35 passed.

## Verification
- qgis tier: 805 passed. core+pure: 634 passed, 3 skipped (test_schema.py:51, "required parameters by design", not real-data skips). ruff check/format clean (one format fix applied), mypy clean.

## Step 6 timing
Mean `dock._render()` with strip shown, REAL_DZT[0] tiled to 6301 traces (512 samples), 20 curve replacements: 53.2 ms (budget ~120 ms). Measured via a throwaway test, deleted.

## Notes
- Band/trace/limits are painted unantialiased (a 1 px antialiased line at a fractional x spread to ~89 grey, failing the brief's "darker than 80" probe); the curve is still antialiased.
- No existing test broke.
