# Task 2 report: draggable cutoff line in ProfileView

Implemented: `ViewTransform.snap_cutoff`; in profile_view.py the constants CUTOFF_COLOUR/DIM/GRAB_PX, `cutoff_label`, `cutoff_dragged`, `set_cutoff`, `cutoff_ns`, `_cutoff_y`, `_paint_cutoff`, `_near_cutoff`, press/move/release/hover handling, `clear()` reset, module docstring line. `KNOWN_UNCONSUMED` gains `cutoff_dragged` (Task 3 removes it).

## TDD
- Cycle 1 (pure): 2 snap_cutoff tests -> RED `AttributeError: 'ViewTransform' object has no attribute 'snap_cutoff'` (2 failed, 16 passed) -> GREEN 18 passed.
- Cycle 2 (view): 13 tests. RED 1: collection ImportError on `cutoff_label`; stubbed it to return "" -> RED 2: 13 failed (AttributeError set_cutoff / cutoff_dragged; label `'' == '40.0 ns'`). Note: `-k "cutoff or label"` deselects 4 of the 13 by name, so the RED/GREEN runs used `-k "cutoff or the_label_names or abandons_the_drag or press_away or hovering_the_line or keeps_one_sample"`. GREEN: 13 passed.

## Suites
- whole test_plugin_profile_view.py: 72 passed
- pure tier: 606 passed, 3 skipped (after the KNOWN_UNCONSUMED entry; without it test_no_orphan_signals failed naming cutoff_dragged, as predicted)
- qgis tier: 679 passed (baseline 666 + 13)
- ruff check/format clean; mypy clean (33 files)
- slot-traceback check: profile_view file run with -s, `grep -ci traceback` = 0.

## Files
profile_view.py, view_transform.py, tests/pure/test_pure_view_transform.py, tests/pure/test_no_orphan_signals.py, tests/qgis/test_plugin_profile_view.py

## Self-review / concerns
- Release of a grab emits unguarded (a bare emit; consumers' slots guard themselves).
- A move without the button during a grab restores the starting value and then falls through to normal hover handling.
- Hover calls setCursor on every buttonless move (cheap; keeps pick-mode cursor correct).
- Mutation checks not run.

## Fix round 1
- F1: hover over the line in pick mode now shows CrossCursor (`_near_cutoff(...) and not self._pick_mode`). Test extended: `test_hovering_the_line_shows_a_resize_cursor` asserts CrossCursor on the line in pick mode.
- F2: a left press now abandons a still-set grab first (restores start value, no emit). New test `test_a_new_press_abandons_a_grab_whose_release_was_lost`.
- RED (`-k "resize_cursor or lost"`): 2 failed (`assert 5 == 2` SizeVer vs Cross; `assert 30.5 == 40.0`).
- GREEN: whole file `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py -q -p no:xonsh` -> 73 passed; `-s` pass: 0 tracebacks; ruff check and format clean.
