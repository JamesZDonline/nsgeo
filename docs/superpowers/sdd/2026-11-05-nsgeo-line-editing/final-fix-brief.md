# Final review fix wave — line editing branch

Branch head 73ec451. The whole-branch review (range 7fa0e96..655fe0e) found no Critical issue and one Important one. The controller also ruled seven more items into this one fix wave. Do all eight. Each item says why it is here.

The spec (docs/superpowers/specs/2026-10-30-nsgeo-line-editing-design.md) is the binding authority. shared-context.md in this directory holds the plan's Global Constraints and verification commands.

## 1. Important — `edit_lines` corrupts `site.lines` when `order` holds a duplicate key

From the reviewer, verbatim:

> `session.py:766-778`. The strict `zip` raises only after the slots have been written. My probe left FILE__001 in the list twice and FILE__003 gone. No dirty mark is set and no `lines_changed` is emitted. The dialog's `accept()` then puts "zip() argument 2 is longer than argument 1" on the status line, with the session already half-changed. A later Save would drop a line from `survey.nsgeo.json` and leave its picks without a line. It is unreachable today, because the dialog's order is always unique. But it is the only path in the branch that can corrupt the survey file, and it breaks the method's own docstring promise ("`ValueError` … before anything changes"). Fix: next to the existing duplicate-edit check, add `if order is not None and len(set(order)) != len(order): raise ValueError(...)`.

Add a session test: `order` with a duplicate raises `ValueError`, and `site.lines`, `keys()`, the dirty flag and the placements are all unchanged afterwards.

## 2. An Edit lines table outlives its site

From the reviewer:

> `plugin.py:1857-1866`. `_edit_lines_dialogs` is keyed by grid id only, and nothing closes the tables when the site closes. After Open site…, right-clicking a grid with the same id (A, Grid1 and so on are common) brings up the old site's table. OK then refuses ("a different site was opened…"), and the edits are lost.

Fix: in the opener, when an existing table for that grid id was opened against a different `json_path` than the session's current one (the dialog records it at open), `reject()` it and build a fresh table.

Add a plugin test: open a table on grid A of site 1, open site 2 (which also has a grid A), then call `open_edit_lines_dialog("A")`. The table shown is a new one that lists site 2's lines.

## 3. Ruling — depth and velocity follow even when a pick's position cannot

From the reviewer:

> `layers.py:642-644`. Picks on a time-triggered line keep a stale depth after a velocity change. Their position is rightly left alone, but `continue` also skips depth and velocity.

Controller ruling: the user's decision 7 says that whenever a line's resolved velocity changes, its picks' `depth_m` and `velocity_m_ns` are worked out again from their time. That outranks §4.4's "untouched" wording, which was about position. So:

- When a line has no points, because it has no grid frame or no distance axis, `follow_lines` still re-derives `depth_m` and `velocity_m_ns` for its picks.
- It leaves their geometry and `distance_m` exactly as they are.
- It still writes only the values that change.

Update Task 1's `test_a_pick_on_a_line_with_no_distance_axis_is_left_as_it_is` to the new rule:

- Rename it to fit, e.g. `test_a_pick_on_a_line_with_no_distance_axis_keeps_its_place_but_follows_the_velocity`.
- Its geometry stays empty.
- Its `depth_m` and `velocity_m_ns` equal `session.derived_pick_fields(key, trace, time)[1:]`, both after the grid move and after a `set_line_velocity` on that line.

Check the README and guide wording about picks still holds; adjust a sentence only if it now says something untrue.

## 4. Ruling — every Qt-invoked slot in the Edit lines dialog guards its whole body

From the reviewer:

> `edit_lines_dialog.py:289-541`. The Edit lines slots catch only `KeyError`/`ProjectError`/`ValueError`, and `move_selected` and `_selection_changed` have no guard.

The plan's Global Constraint is that every slot connected to a signal, and every Qt-invoked override, guards its own body and reports through `_log` or `status`. Keep the specific handlers that give a good message. Add a final broad `except Exception` that reports on `status` (and `_log`) to every slot, including `move_selected` and `_selection_changed`.

## 5. Ruling — a real-DZT test of picks following, and a tolerance that fits real coordinates

Real DZT files are the user's primary validation, and every new QGIS-tier pick test so far is synthetic.

- Add one QGIS-tier test using the real files (`REAL_DZT` / `needs_real_data` in tests/plugin_testing.py, FILE__001–010 in packages/nsgeo-core/tests/data/local).
  - Build a grid at a UTM-sized origin, e.g. `(530000.0, 4300000.0)` in `"EPSG:32616"`, and place a few real lines on it as a zigzag.
  - Write a pick on one line, then in turn:
    - move the grid with `replace_grid`;
    - flip the line with `edit_lines`;
    - move it to a second grid with `move_lines`.
  - After each step, the pick's point equals that line's trace vertex (`line.trace_coords(frames)[trace]`).
  - After each step, a second `follow_lines()` returns 0.
  - The test must RUN, not skip. Say so in the report.
- Change the geometry comparison tolerance in `follow_lines` from `1e-9` to `1e-6` (CRS units; at UTM northings 1e-9 is about one ulp). Keep the attribute tolerance sensible. Say in a comment why it is what it is.

## 6. Ruling — Whole site moves pinned by tests

The reviewer's probes showed these work. Land them as tests in tests/qgis/test_plugin_site_scope.py using `site3`. They cover spec §7's hazard "a line moved while it is in a prepared source on each grid".

- With the site view prepared and idle, `move_lines` one B line to C.
- With a site preparation still running, `move_lines` one B line to A.
- Each case ends with no `"now on grid"` error reported, and every grid's engine holding exactly that grid's lines.

## 7. Ruling — cosmetic batch

- `plugin.py`'s `move_lines` message uses `exc.args[0]` for a `KeyError`, so the bar doesn't show quotes inside quotes.
- Fix the spec citations:
  - line_edit.py:78 (§4.3 → §3 call 8);
  - session.py `move_lines` (call 8 → call 7 and call 1);
  - `replace_grid` (call 6 covers only the message; the rule is decision 4 / §4.3);
  - slices_engine.py:1064 ("(spec §4.5)" → "(line editing spec §4.5)");
  - survey_dock.py:76 (§4.2 → §3 call 7).

## Verification

- Covering files:
  - test_plugin_session.py;
  - test_plugin_layers.py;
  - test_plugin_edit_lines_dialog.py;
  - test_plugin_site_scope.py;
  - test_pure_line_edit.py;
  - plus whichever file holds the real-DZT test.
- Then the whole QGIS tier once: in the background, to a scratchpad log, in bounded waits. Then core+pure, lint and types.
- The controller may still be running a full QGIS tier when you start. If `ps` shows a pytest you did not start, wait for it to finish before starting your own full run, and never kill it.

## Commit and report

- Commit, one commit or a few, with the Co-Authored-By trailer. Push to origin nsgeo-line-editing.
- Write the report to `final-fix-report.md` in this directory:
  - each item, what changed, file:line;
  - the covering tests;
  - the exact commands and their output;
  - RED evidence where a test pins a fix.
