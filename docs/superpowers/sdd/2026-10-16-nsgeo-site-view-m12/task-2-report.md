# Task 2 report: the survey remembers each grid's slice source and the site view

## Implemented
- Core: `Site.slice_sources` / `Site.site_view` (docstring gives shapes); `save_site` writes each only when non-empty; `load_site` raises `ProjectError` for a non-dict top level, drops unknown-grid entries, and cleans entries.
- Session: `slice_source`, `remember_slice_source`, `grid_gain`, `set_grid_gain` (ValueError unless finite and > 0), `site_view`, `set_site_view` (validates normalisation against `NORMALISATION_METHODS`); copy on read; every mutator is a no-op that leaves dirty untouched when nothing changed; `remove_grid` prunes both.
- Dock: `_restore_remembered_source` (in `_sync_included`'s grid-changed branch; preset selected under `_updating`; lines filtered to the grid, survey order; `None` stays default) and `_remember_source` (called from `_on_source_changed` and from `set_included` when changed). `rebuild_source` never remembers. About 45 lines added to the dock, two small methods.

## Judgement choices (load)
- Inner wrong-typed value: that key reads as unset (dropped); a non-object entry is dropped; invalid gain (<=0, non-finite, bool, non-number) dropped. `site_view.grids` is filtered to known grids; non-str entries dropped. Documented in comments and tested.
- A grid switch to a grid with no remembered source remembers that grid's current preset + default lines (the brief's `_on_source_changed` rule), which marks dirty on a user grid switch. Opening a site never does.
- `restore_cube` writes `_included` directly and is not remembered.

## Results
- core+pure: 598 passed, 2 skipped (baseline 587/2). qgis: 737 passed (baseline 723). ruff check, ruff format --check, mypy all clean.

## TDD evidence
- Core: with src reverted, 10 of the new test_project tests FAILED (round trip, defaults, wrong-type x6, unknown grid, inner values); with src restored, 37 passed.
- Session/dock tests were written alongside the implementation (session 74 passed, dock 70 passed); their discrimination is shown by the mutants below.

## Mutants (PYTHONDONTWRITEBYTECODE=1; each then reverted, 144 passed for dock+session)
| Mutant | Failing test |
|---|---|
| 1. `_remember_source()` in rebuild_source's first-computation path | test_plugin_slices_dock.py::test_opening_a_site_does_not_mark_it_dirty |
| 2. remembered lines not filtered to the grid (`tuple(lines)`) | test_a_remembered_line_that_left_the_grid_is_filtered_out |
| 3a. remove_grid not popping slice_sources; 3b. not pruning site_view grids | test_removing_a_grid_prunes_its_source_and_its_site_view_entry (both) |
| 4. `_update_source` always marking dirty | test_remembering_an_unchanged_source_does_not_mark_dirty |

## Existing tests changed
None. No existing dock test asserted that returning to a grid resets its lines.

## Files
core: model/survey.py, project.py, tests/test_project.py. qgis: session.py, ui/slices_dock.py, tests/qgis/test_plugin_session.py, tests/qgis/test_plugin_slices_dock.py (adds `docked_two_grids`).

## Self-review / concerns
- None blocking. Ruff SIM102 and SIM118 hit once each and were fixed (SIM118 via the repo's existing noqa idiom for `SiteSession.keys()`).
- `set_site_view` does not validate `transform` (brief only names normalisation).

## Fix round 1
- Switching test now selects "p" on B before returning, so A's "q" is genuinely restored.
- New test_reopening_a_survey_restores_a_remembered_source_without_dirtying_or_rewriting_it (non-first preset, explicit lines, open_site + fresh dock: not dirty, preset and lines restored, stored record unchanged).
- Ruling T2-b: `restore_cube` calls `_remember_source()` after its `_updating` block. Its only caller is `_on_cube_changed`, which returns early under `_updating`, so no automatic path remembers. New test_picking_a_saved_cube_remembers_its_preset_and_lines_for_that_grid.
- Mutants (PYTHONDONTWRITEBYTECODE=1, dock file): (a) preset restore deleted -> 3 fail (switching, reopening, cube pick); (b) `_updating` guard removed -> reopening test fails; (c) cube remember removed -> cube-pick test fails. All reverted.
- Results: dock+session 146 passed; core+pure 598 passed, 2 skipped; ruff check, format --check, mypy clean. Full qgis tier not re-run (only slices_dock.py and its tests touched).
