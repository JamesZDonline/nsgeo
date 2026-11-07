# Task 1 report: Picks follow their line (#35)

## Implemented
- session.py: `SiteSession.derived_pick_fields(key, trace, time_ns)`; `add_pick` builds its derived fields through it.
- layers.py: `follow_lines`, `_on_picks_committed` (bound/unbound with the picks signals), `_tell` (guarded `on_info` call), helpers `_clamped`, `_same_number`, `_SAME`; `refresh()` calls `follow_lines` after the refills in its own try (Critical log on failure); `_on_site_opened` sets `_report_follow` around the refresh; `on_info` replaces `on_warning`; deleted `_warn_if_a_placed_grid_moved`, `_grid_placements`, `_last_grid_placements` and every comment citing them; `_pick_point` docstring rewritten and shares `_clamped`.
- plugin.py: `on_info=` wiring, Finding C comment replaced by one line.
- README Picking section and guide (§4 bullet) rewritten.

## TDD
- RED: `pytest test_plugin_layers.py test_plugin_session.py` -> 15 failed, 162 passed (AttributeError `derived_pick_fields`/`follow_lines`, TypeError `on_info`, position mismatches in follow tests). Expected.
- GREEN: follow-related subset of layers tests 56 passed; then full tiers below.

## Verification
- qgis tier (full): 1493 passed, 0 skipped.
- core + pure: 1004 passed, 3 skipped.
- ruff check + format --check: clean. mypy (command in shared-context, minus line_edit.py which does not exist yet): no issues.

## Files changed
session.py, layers.py, plugin.py, packages/nsgeo-qgis/README.md, docs/guide/getting-started.md, tests/qgis/test_plugin_layers.py, tests/qgis/test_plugin_session.py.

## Existing tests changed
- Deleted the four `on_warning` tests and their comment block (the warning is removed); `_MOVED_GRID` kept.
- `test_picks_survive_multiple_refills_with_attributes_intact`: last geometry assertion now expects the pick on its line (trace 12), per the brief; attributes unchanged. Reason: it pinned "picks are never re-placed".

## Self-review
- Every listed test and deletion done; no remaining references to on_warning / _warn_if / _grid_placements in code.
- Beyond the brief: the guide's Step 6 bullet "Do not drag a pick to a new place..." contradicted the new ruling, so I rewrote it too (one bullet: dragging does not move it; it goes back on save; delete and re-pick to move along the line).
- The `_reopen` test helper in test_plugin_layers.py is shared by the two reopen tests.

## Concerns
- `derived_pick_fields` calls `line.distance_along()` per pick (via `_pick_distance`), so following costs O(picks x traces) per refresh; fine at the table's expected size (hundreds to low thousands), flagged in case picks grow.
- A line with no distance axis logs its "could not be placed" warning on each refresh (refill_lines already does the same).
- layers.py is now ~1800 lines; not split, per instructions.
- The full-tier run overlapped a baseline run started earlier by the controller (CPU contention only).

## Fix round 1 (Important 1: negative trace wrapped to the far end's distance)
- Changed: `SiteSession._pick_distance` returns None for `index < 0` (NumPy would wrap it); added `test_a_pick_with_a_negative_trace_sits_on_the_first_trace_with_no_distance` (trace=-3: point on trace 0, distance NULL).
- Honest note: I added the test and the fix together and did not run the test alone red first.
- Command: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:cacheprovider -p no:xonsh` -> `178 passed in 177.99s`.
- ruff check/format and mypy: clean.
