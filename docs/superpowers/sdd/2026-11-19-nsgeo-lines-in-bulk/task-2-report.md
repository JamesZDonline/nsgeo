# Task 2 report: one line selection, map and Survey panel (#57)

## Built
- map_link.py: `lines_selected = pyqtSignal(list)`; `_on_selection` announces every user change (all sizes, before the one-line open), ignoring changes while `_applying_selection` (depth counter) is up; `select_lines(keys)` (by line_key at call time, no-op if already matching, no announce, no open, unplaced keys ignored).
- ui/survey_dock.py: `line_selection_changed = pyqtSignal(list)`; `itemSelectionChanged -> _on_selection_changed` (quiet counter); `select_lines`; new functions `_rebuild_announcing`, `_select_only_announcing`, `_capture_line_keys`, `_restore_line_selection`, `_select_rows`. Existing functions got one-line calls (rebuild, _capture_state, _restore_selection, _follow_current). Selection set through the model with ClearAndSelect|Rows (modifier-proof); current item (Shift anchor) on the open line, else the first key; grids unfolded.
- plugin.py: two connect lines next to Task 1's.
- layers.py: unchanged.

## Step 1 measurement
QGIS 3.44, real SiteLayers + MapLink: a refill (`lines_changed`) emits NO `selectionChanged` on the lines layer and leaves `selectedFeatureIds()` as it was, i.e. stale ids (features got new ids; e.g. selected [1,2], features now [3,4]). So no guard is needed against the refill reaching `_on_selection`; the stale selection is repaired because the dock announces its selection once after every rebuild and `select_lines` compares/looks up by key. Pinned in `test_a_refill_keeps_or_clears_the_lines_selection_as_measured`. The whole chain is proven by `test_the_selection_survives_a_bulk_velocity_in_both_places` (six lines, both views keep six). Risk: QGIS 4.2 might behave differently; CI will show (that wired test would fail).

## TDD
RED: new MapLink tests failed with AttributeError (`lines_selected` / `select_lines`), 5 failed; GREEN after implementation: test_plugin_map_link.py 60 passed. Dock tests: 9 failed (`no attribute 'select_lines'`), then 116 passed in the file. Wired tests: with the two connect lines commented out all 8 failed, restored: 8 passed.

## Final runs
- three touched files: 184 passed
- `-m real_data`: 47 passed (includes the new real Grid 2 test; files copied into the site's raw folder)
- core+pure: 2046 passed, 9 skipped, 19 xfailed (baseline); ruff clean

## Self-review / concerns
- A held Ctrl cannot be faked in tests (Qt reads the real modifier state), so "modifier cannot toggle rows" is guaranteed by construction (explicit flags), not by a test. The Shift anchor is pinned by `test_a_shift_click_after_select_lines_ranges_from_the_selected_row`.
- Plugin dock tests must `setFloating(True)` before clicking (the dock sits in a never-shown main window; the tree is 90x6 otherwise).
- A rebuild with a captured line selection keeps it even when it differs from the open line (spec §3.4); with none captured the open line wins as before.
- Rebuild exception path: tree.clear() may emit `line_selection_changed([])` once (acceptable).

## Fix round 1
- F1: `SiteLayers._refill` now brackets the `lines` table in a depth counter (`_refilling_lines`, read-only property `refilling_lines`); the old body is `_refill_table`. `MapLink._on_selection` returns early while it is raised (or while `_applying_selection`). `_announce_selection` skips invalid features (stale ids). Pinned by `test_a_refill_that_changes_the_layers_selection_is_not_a_gesture[clears|stale_ids]` (wrapped `_refill_table` removes the selection / selects stale ids; panel and map keep six, nothing logged). RED: with the early-return disabled both params failed; GREEN with it.
- F2: `_select_rows(..., unfold=)`; only `SurveyDock.select_lines` unfolds, a rebuild's restore does not. Pinned by `test_a_rebuild_keeps_a_grid_the_user_folded_and_its_selected_lines`.
- Runs: map_link + survey_dock + line_selection + layers*: 317 passed; core+pure: 2046 passed, 9 skipped, 19 xfailed; ruff clean.
