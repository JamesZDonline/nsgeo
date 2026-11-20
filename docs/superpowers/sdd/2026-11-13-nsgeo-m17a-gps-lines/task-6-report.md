# Task 6 report: GPS lines in the Survey panel, destagger, profiles, guide

Status: DONE (with concerns below).

## Implemented
- session.py: `is_gps_line(key)`, `set_travel_shift(keys, metres)` (all-or-nothing: KeyError unknown key, ValueError "{name} is not a GPS line" for tape lines, ValueError non-finite; no-op when nothing changes; one dirty mark, one lines_changed; key kept).
- survey_dock.py: GPS row text (`label · GPS · walked m [· gap m without RTK]` then existing suffixes), GPS line menu (Open, Set velocity override…, Set destagger…, sep, Remove), GPS-only selection (`Set destagger for {n} GPS lines…`, sep, Remove), mixed selection removal only, `destagger_requested` signal. Note: before this task a GPS line broke `_line_item` (`p.offset`), so the whole tree rebuilt to empty.
- plugin.py: `open_destagger_dialog` (QInputDialog.getDouble "Destagger", -2..2, 2 decimals, starts at shared value else 0; message `destagger set to {m:+.2f} m on {n} GPS line(s)`), wired to the signal; guarded slot.
- Guide: new "Step 3a: Import GPS lines" (named 3a so no later heading/anchor changes; no in-page links break), plus a toolbar-table row; README line in packages/nsgeo-qgis.
- Tests: GPS helpers (`fix`, `gps_line`, `open_gps`, CRS consts) moved from test_plugin_layers_gps.py into tests/plugin_testing.py for reuse.

## Tests
- core+pure: 1647 passed, 5 skipped (baseline held). pure re-run after README wrap: 315 passed, 1 skipped.
- test_plugin_session.py 144 passed; test_plugin_survey_dock.py 91 passed; test_plugin_profile_dock.py 121 passed; test_plugin_layers_gps.py 16 passed.
- ruff check/format clean; mypy (CI list) clean.

## TDD evidence
- RED session: 6 failed with `AttributeError: 'SiteSession' object has no attribute 'set_travel_shift'/'is_gps_line'`; GREEN after implementation (one test fixed for projection convergence: compared moved distance 0.5 m, not pure northing).
- RED dock: 9 failed (`item_for_key` None because tree rebuild failed on GPS lines; menu was "Add grid…"; no `destagger_requested`); GREEN 91 passed.
- Profile tests (P14) pass at once: P14 needs no new code; they pin axis (travel_shift..walked+shift), no ruler, and `_velocity_axis` spacing = wheel 0.1 m while the fixes' middle runs 0.12 m/trace.

## Self-review / concerns
- The profile pins have no RED by design.
- Walked length is `distance[-1]-distance[0]` (includes end run-ons by wheel).
- Pressing OK on the dialog with an unchanged value still shows the message (set_travel_shift is a no-op).
- Test distance tolerance 0.05 m on the profile axis: UTM scale on the made-up 0.1 m fix spacing.
- Not run: full QGIS tier (controller does).
