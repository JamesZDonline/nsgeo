# Task 4 report: Difference view and the panel's line (#13, #48, #20 item 4, #33)

Commits: c6b16ad (fix(processing): ... #13, #33; code, guide line, plugin and processing tests), 3332c87 (test(profile-dock): #20 item 4). Not pushed.

## Implemented (processing_dock.py)
- `LINE_LABEL_TEXT`, `PREVIEW_SUFFIX` constants; `self.line_label` (RichText, word-wrap, Ignored/Minimum policy) above the button row.
- `_update_line_label()` (guarded, html.escape on name and grid id), called at the end of `rebuild()` next to `_check_refusal()` and from `_on_preview_changed` (connected to `session.preview_changed`). Empty with no line or a cut key; suffix when `session.preview_key` is set, differs from the working key and is not a cut.
- `_on_rows_moved`: after `move_step`, `_emit_difference(True)` when the button is checked (#13).
- docs/guide/getting-started.md: one paragraph in Step 5.

## Tests
- test_plugin_difference_presets.py: #13 reorder, #48 time zero (guard), close site (guard), #33 multi-selection (`_feature_id` copied; the plugin's lines layer is populated in the fixture, no skip).
- test_plugin_profile_dock.py: `test_clear_resets_the_difference_view` (guard).
- test_plugin_processing_dock.py: names its line, names the previewed line, escaped/never widens (shows dock, measures, cleans up in finally).

## TDD RED (before the fix; only the two constants existed)
- #13: `AssertionError: assert 'Difference: ... gain control' == 'Difference: ...emoval (mean)'`
- #33 test and the three label tests: `AttributeError: 'ProcessingDock' object has no attribute 'line_label'`
- #48, close-site and `_clear` tests passed (guards), as expected.
## GREEN
- difference_presets 16 passed; profile_dock 124 passed; processing_dock 50 passed; slices_width 11 passed; map_link 54 passed; gain_strip 77 passed.
- ruff check and format --check clean (whole tree check only; formatted only my four files).

## Mutations (temporary edits, reverted with `git checkout`)
- #48: `return None` after `_decline_difference(declined)` in `current_radargram`'s `except ValueError`: `test_selecting_time_zero_with_difference_on_shows_the_result` FAILS (`Arrays are not equal`, 100% mismatched).
- `_clear`: deleted `self._difference_index = -1` and the label reset: `test_clear_resets_the_difference_view` FAILS (`assert 1 == -1`).
- The closing-the-site test is a guard on `_open("")`'s reset; I did not mutate it (brief asked for only the two above).

## Self-review / concerns
- The width test only shows the Ignored policy holds with a 300-char name; I did not separately mutate the policy.
- Core+pure: started, reached 54% with no failures, then stopped (machine contention, other sessions pytest running); my diff touches no core or pure file. Not completed.
- `git diff` showed only intended files; no stash used.

## Fix round 1
1. `session.lines_changed` now connects to the guarded `_update_line_label`. New tests `test_the_label_follows_the_open_line_to_another_grid` (move_lines to grid B) and `test_the_label_follows_a_rename_of_the_open_line` (edit_lines label). RED before the fix: `assert '· grid B' in '<b>FILE__001</b> · grid A'` and `assert '<b>RENAMED</b>' in '<b>FILE__001</b> · grid A'`. GREEN after.
2. Wrap pinned by new `test_the_line_label_wraps` (wordWrap() and heightForWidth(120) > 2 lines). Mutation `setWordWrap(False)`: it fails (`assert False` on wordWrap()). The width test docstring now claims only the Ignored policy and escaping; mutation Ignored -> Preferred makes it fail (`assert 2982 == 458`). Both mutations reverted by hand.
3. `_on_rows_moved` body guarded with try/except Exception and `_log`.
Runs (all pass): processing_dock 53, difference_presets 16, slices_width 11, profile_dock 124, gain_strip 77. ruff check and format clean on the two files.
Core+pure: my earlier run was stopped at 54% with no failures (machine contention); not completed. My diff touches no core or pure file.
