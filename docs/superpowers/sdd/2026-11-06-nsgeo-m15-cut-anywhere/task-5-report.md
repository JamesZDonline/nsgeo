# Task 5 report: picks on cuts

## Implemented (deferrals honoured: no zero_ns, time_base, another-clock count, follow_zero)
- session.py: `add_cut_pick(key, column, distance_m, time_ns, stack_json)` (working cut only, ValueError otherwise; finite time kept as given; distance clamped to [0, length]; column stored in `trace`), `derived_cut_pick_fields` ((None, None) on KeyError from cut_velocity).
- layers.py: `_pick_point` places a cut pick via `_cut_point` (distance on the cut, to_world, package CRS); `write_pick` says "no cut with key ..."; `follow_lines` hands cut-key rows to `_follow_cut_pick` (position from distance_m, depth/velocity from derived_cut_pick_fields, distance/trace/time never rewritten; gone cut or NULL distance/time left alone; provider writes only).
- plugin.py: `_on_pick_requested` routes cut keys to `_add_cut_pick` (shown section's distance_m[trace] and provenance_json; message string goes to the bar); MapLink gets `on_info` = message bar.
- profile_dock.py: `_refresh_picks` overlays cut picks at (column_at(key, distance_m), time_ns as stored).
- map_link.py: `on_info` ctor arg, `CUT_GONE_TEXT`, `_jump_to_cut_pick` (opens cut, cursor at column_at(distance); gone cut -> on_info, nothing opens).

## TDD
- RED: with source reverted (only the CUT_GONE_TEXT constant added so the file collects): `16 failed in 24.78s` for test_plugin_cut_picks.py (before that, collection ImportError). Only one test file is new.
- GREEN: `16 passed`. Brief tests skipped per deferrals: another-clock, stack-change re-zero. Added two extras (add_cut_pick refusals/clamp; no-velocity -> (None, None)).
- The "cell change" test doubles the cell (the plugin default is 0.2, so 0.2 changed nothing).

## Results
core+pure 1292 passed, 5 skipped; QGIS full 1776 passed (16:55); ruff check + format clean; mypy (CI list) clean.

## Self-review / concerns
- Provenance JSON has no time_base yet (deferred to Task 5b).
- `derived_cut_pick_fields` ignores distance_m (one velocity per cut); kept for the brief's signature.
- Cut overlay uses column_at, which needs a source; with none, no overlay (a message is shown anyway).
- Selecting a pick with NULL distance opens the cut but sets no cursor.
- RED was recorded by reverting src via patch file (no stash).

## Fix round 1
1. layers.py: `_stage_point` and `_stage_fields` (module level) are now the one staging rule for line and cut picks; `_follow_cut_pick` became `_cut_pick_derivation`, returning (point, depth, velocity) or None.
2. CRS rebuild test now asserts the picks layer is EPSG:32617, the cut key survives, and the geometry equals the transformed world point at distance_m.
3. Cell-change test selects the pick after the change and asserts current_trace == column_at != stored trace.
4. Dropped the explicit reopen; the overlay is pinned through section_changed alone.
5. Line-override test captures depth/velocity before the override and asserts them equal after.
6. Vacuous assertion replaced (title still a cut's, overlay empty while no section shows: after the shrink there is no source, so column_at is None); unused monkeypatch removed.
7. `ProfileDock.shown_cut_section(key)`; plugin `_add_cut_pick` uses it and refuses with "the profile shows no section for this cut, so there is no column". New test `test_a_pick_takes_its_distance_from_the_section_on_screen`.
8. Refresh message now "updated {n} pick(s) to sit on their lines and cuts, ..."; test_plugin_layers pin updated.
Results: test_plugin_cut_picks 17 passed; test_plugin_layers 96 passed; test_plugin_profile_cut 14 passed; test_plugin_session_cuts 14 passed; ruff check/format clean; mypy (CI list) clean.
