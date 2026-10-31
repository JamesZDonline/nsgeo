# Task 1 report: one reading of a grid's line choice (#74)

Commit d118488, pushed to origin/nsgeo-slices-cleanup.

## Implemented
- site_scope.source_keys: returns every line when the filtered remembered list is empty (docstring updated).
- LineChoiceDialog._refresh: OK enabled iff `_included` non-empty; tooltip "Tick at least one line." while disabled, "" otherwise.
- SlicesDock.restore_cube: empty `recipe.choice.line_keys` restores `_default_included(grid)` with `_included_is_default=True`; docstring paragraph rewritten.

## TDD
RED (the brief's -k command): 3 failed in dialog/dock first (OK never disabled twice; old cube restored `()`).
The site-scope tests first PASSED pre-fix, because switching This grid back to A rewrites the record as `lines: None`
(test setup dodged the hazard). Re-ordered so the record is written while This grid shows B, the site is read first, and
This grid comes back to A afterwards: then all 3 failed (`() == (4 keys)`, `() == (2 keys)`, `engine_for("A") is None`).
GREEN: same files, full: 128 passed (83s).

## Results
- three files in full: 128 passed
- core+pure: 808 passed, 3 skipped
- ruff check + format --check: clean (mypy not run; no files in its set touched)

## Files
ui/site_scope.py, ui/line_choice_dialog.py, ui/slices_dock.py; tests test_plugin_line_choice_dialog.py, test_plugin_site_scope.py, test_plugin_slices_dock.py.

## Existing tests corrected (named in commit)
- test_a_cube_record_with_no_lines_key_is_remembered_as_every_line: asserted `included_keys() == ()`; now every line.
- test_the_export_message_names_a_grid_left_out and test_the_site_file_records_an_included_grid_it_left_out: faked "no lines" with remembered `lines=()`; now they `set_site_view(grids=A,B,C)` and `remove_lines` C's lines (a grid with no lines is otherwise dropped from the included set).

## Self-review / concerns
- Brief's step "This grid has left and come back to A" cannot show the bug, as the grid switch itself rewrites the record to None; tests reordered as above, still covering both scopes.
- Only 3 files run in full, not the whole qgis tier (coordinator said so).

## Fix round 1
Finding: This grid's live choice emptied by removal pruned to `()` in `_sync_included`.
RED: new `test_a_live_choice_emptied_by_removal_reads_as_every_line_in_both_scopes` (This grid on A, set_included, remove_lines) failed: `() == (FILE__003, FILE__004)` on `included_keys()`. The record-unchanged assertion held (remove_lines writes no record).
Fix: prune branch of `_sync_included` falls back to `_default_included` with `_included_is_default=True` when pruning empties a non-empty set; docstring cites #74.
GREEN: the three files in full, same command as before: 129 passed (85s). Ruff check/format clean.
Commit: see git log (separate commit, pushed).
