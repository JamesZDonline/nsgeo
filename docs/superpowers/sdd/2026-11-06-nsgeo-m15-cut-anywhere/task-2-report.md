# Task 2 report: cuts in the session, the cuts layer and the Survey panel

## Implemented
- session.py: `cuts_changed`; `cut_keys`, `cut_keys_on_grid`, `cut_for_key`, `add_cut` (name `Cut {highest+1}`), `rename_cut`, `remove_cut`, `cut_velocity` (call 16). `remove_grid` drops the grid's cuts and emits `cuts_changed` after `grids_changed`. Cuts live in `site.cuts` (loaded by `load_site`), so `_install` needs no extra state; `keys()` stays lines-only.
- layers.py: `cuts` table (LineString; cut_key, name, grid_id, length_m) in TABLES/DERIVED, `LEGEND_ORDER = (picks, marks, cuts, lines, grids)`, `refill_cuts` in `refresh`'s loop, `_style_cuts` (solid 0.6 mm #e6550d, labelled `name`), `cuts_changed` -> `refresh`.
- survey_dock.py: Cuts item (kind "cuts") before a grid's lines, cut items (kind "cut", id = key); rebuild on `cuts_changed`; `item_for_key`/identity find cuts; cut context menu (Rename cut…, separator, Delete cut); `_remove`/`_removal_text`/`_selected_targets`/`_count_phrase` take cut keys; delete prompt and grid-removal addition use the exact text.

## TDD
RED (session): `AttributeError: 'SiteSession' object has no attribute 'cuts_changed'` (test_plugin_session_cuts.py, first test).
RED (layers): 6 failed, `KeyError: 'cuts'`.
RED (dock, implementation reverted from HEAD for the run): `5 failed, 1 passed, 59 deselected`.
GREEN: session_cuts 7 passed; layers cut tests 6 passed; survey dock + session_cuts 72 passed. The close-prompt test (test_plugin_loads.py) passes on the session work, as the brief expects.
Six existing layers tests pinned the four-table group (`["picks","marks","lines","grids"]`, `== 4` layers) and were updated to the five-table order.

## Verification
- core + pure: 1291 passed, 5 skipped
- QGIS full suite: 1686 passed (941.92 s)
- ruff check, ruff format --check: clean; mypy CI list: no issues in 46 files

## Files
packages/nsgeo-qgis/nsgeo_qgis/{session.py, layers.py, ui/survey_dock.py}; tests: tests/qgis/test_plugin_session_cuts.py (new), test_plugin_layers.py, test_plugin_survey_dock.py, test_plugin_loads.py.

## Self-review / concerns
- Grid-removal text is literal to the spec: "Its 1 cut are deleted too" in the singular (spec says `cut(s)`; only the noun changes). It is a separate paragraph of the prompt, not appended to the first sentence, since multi-item prompts are bullet lists.
- Rename: a cancelled or blank name is a silent no-op (blank is not an error to the user).
- A selection mixing cuts and lines offers Remove only (no Edit/Move); grids still removed only when nothing but grids is selected.
- Multi-cut/mixed delete prompts use the generic text plus "Picks on a cut stay on the map."; the exact single-cut text is used for one cut.
- Clicking a cut item opens nothing (Task 3).
- time-zero (#97) merge: changes are additive in separate blocks of session.py/layers.py (new methods after `resolved_velocity`, a new table entry, a new refill tuple).

## Fix round: grid-removal prompt agrees in number
Change (survey_dock.py `_removal_text`): one cut reads "Its 1 cut is deleted too; its picks stay on the map."; n > 1 reads "Its {n} cuts are deleted too; their picks stay on the map."
Covering test: `test_removing_a_grid_with_cuts_says_so` pins both forms (2 cuts, then 1).
Command: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py -q -p no:cacheprovider -p no:xonsh` -> `65 passed in 9.60s`. `ruff check .` all passed; `ruff format --check .` 187 files already formatted.

## Fix round 1 (review findings)
1. `_selected_targets`: any selected line gives line keys only; cut keys only when no line is selected; grids only when nothing else is. New tests: `test_a_range_of_lines_never_sweeps_in_the_cuts_it_crosses` (case a), `test_a_fresh_shift_click_on_a_line_beside_a_cut_removes_lines_only` (case b), `test_with_only_cuts_selected_delete_deletes_them`. RED check with the old selection logic restored: (a) and (b) failed, the cuts-only test passed.
2. `cut_velocity`: grid velocity, else `VelocityModel.from_dielectric(first line's header.epsr)`, ignoring line overrides; docstring updated. Tests: `test_cut_velocity_is_the_grids_then_the_first_lines_header` (asserts the header model directly; overrides on the second and the first line change nothing) and `test_cut_velocity_takes_the_first_lines_header_when_dielectrics_differ` (9.0 vs 25.0).
3. survey_dock.py constants: DELETE_CUT_TEXT, CUT_ONE_PICK_TEXT, CUT_PICKS_TEXT, CUTS_ONLY_PICKS_TEXT, GRID_CUTS_ONE_TEXT, GRID_CUTS_TEXT, GRID_CUT_PICK_TAIL, GRID_CUT_PICKS_TAIL; the delete tests use them. The grid-removal tests pin literal text on purpose.
4. Grid removal counts the cuts' picks (`_grid_cuts_text`): "Its 1 cut is deleted too; its 3 picks stay on the map." / "Its 2 cuts ... their 4 picks stay ..." / zero picks ends with "."; several grids start "Their". For a single grid it is appended to the question sentence. Tests: `test_removing_a_grid_with_cuts_says_so` (zero, plural, 1 pick, singular) and `test_removing_several_grids_with_cuts_says_their`.
5. Stale comments fixed (layers.py x2, `_selected_targets` docstring).
Commands: survey_dock + session_cuts `77 passed in 10.44s`; layers `96 passed in 196.76s`; `ruff check .` and `ruff format --check .` clean.
