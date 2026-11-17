# Task 2 report: features table and pick membership (M16 B)

## Implemented
- `surface_plan.py` (pure, in CI mypy list): FeatureRecord, KIND_SURFACE, clean_name, name_refusal, selection_refusal, move_note, remove_refusal, delete_question, plus grid_mismatch_refusal.
- `layers.py`: FEATURES + FEATURES_SPEC; `_ensure_features_table` (created only when absent, missing fields added, unreadable table refused, held in `self._features`, not in `layers`/project, released by `detach`); PickRow; selected_pick_ids, pick_rows, members_by_feature, set_pick_feature (provider.changeAttributeValues), feature_records, write_feature, update_feature, remove_feature (+ new_feature_id/now_iso helpers).
- `session.py`: `features_changed`. `test_no_orphan_signals.py`: added to KNOWN_UNCONSUMED with Task 4 comment (R1).
- `surfaces.py`: Surfaces(session, layers, export_for=None), SelectionCheck, all brief methods; create writes row then picks (row removed on failure); delete clears picks then row.
- `.github/workflows/ci.yml`: surface_plan.py in the mypy list.

## Choices beyond the brief
- `selection_refusal` gained optional kwargs `no_grid=0` (picks with no line/grid/position, checked after cuts, before two grids) and `minimum=3` (1 when adding to an existing surface, which also skips the area test).
- `grid_mismatch_refusal` for add_picks into a surface on another grid.
- Unsaved count = selected fids with no committed readable row (negative fids, deleted rows).
- The features layer is kept out of `self.layers` because existing tests assert `set(layers.layers) == set(TABLES)` and detach removes `layers` from the project.

## TDD
- RED pure: test file against missing module -> `ModuleNotFoundError: No module named 'nsgeo_qgis.surface_plan'`.
- RED QGIS (HEAD sources copied to scratch, new test file): `ImportError: cannot import name 'FEATURES' from 'nsgeo_qgis.layers'`.
- GREEN: pure tier `334 passed, 3 skipped`; new QGIS file 14 passed; with test_plugin_layers.py and test_plugin_session.py: `238 passed in 283s`.
- Lint: ruff check, ruff format --check, mypy (CI list) all clean.
- Note: the pure module was written just before its tests; I moved it aside to observe RED.

## Self-review / concerns
- layers.py grew ~190 lines (features block); not restructured.
- Features layer stays open on the gpkg during other tables' CRS rebuild; the CRS-change test passes, no lock issue seen.
- members_by_feature reads committed rows only; a pick edited in QGIS's buffer is not seen until saved (by design, as follow_lines).
- Push: see commit step output in the controller message.

# Fix round 1 (review findings)

## Changes
- IMPORTANT: `check()` now separates unsaved (negative fids, rows with pending buffer edits/geometry/delete via `SiteLayers.unsaved_among`, rows gone from the table) from saved-but-blank rows (`unreadable_pick_ids`). New `selection_refusal(unreadable=)`: "1 of these picks has no trace or time; edit or delete it in the picks layer." (after unsaved, before cuts).
- Minor 1: `delete` calls new `SiteLayers.clear_pick_feature` (raw provider scan, not `_row_to_pick`).
- Minor 2: `SelectionCheck.left` (what each moved-from surface keeps); `move_note(moving, n, left)` appends "“Bowl” is left with 0 picks, too few to rebuild." when under 3. Move still allowed.
- Minor 3: pending edits in the picks edit buffer count as unsaved (see above).
- Minor 4: path test asserts no component under the site folder contains "Bowl" or "north".
- Minor 5: test for an older `features` table (DROP COLUMN created, kind) gaining fields, rows reading correctly.
- Minor 6: `_provider_reason` fallback for empty provider messages; `write_feature` error now reports `_features_problem` (the ensure failure) instead of blaming a missing grid.
- Minor 7: duplicate fids de-duplicated; `add_picks` emits only on a real change; `settings_json()` shared by `to_row` and `update_feature`; `new_feature_id`/`now_iso` moved to `surface_plan`; `_pick_row` skips blank rows before `_row_to_pick`, so `check()`/`members` log nothing.

## Covering tests
pure: test_unreadable_picks_have_their_own_wording..., test_move_note_says_when_a_surface_is_left_too_small. QGIS: test_a_saved_pick_with_blank_attributes_is_named_as_such_not_as_unsaved, test_checking_a_blank_row_writes_no_log_line, test_delete_clears_a_member_whose_time_was_blanked_after_it_joined, test_moving_every_pick_of_a_surface_says_it_is_left_too_small, test_picks_with_pending_edits_in_the_layer_are_unsaved, test_a_duplicate_fid_is_not_unsaved_and_re_adding_members_changes_nothing, test_an_older_features_table_gains_missing_fields_and_reads_correctly, plus updated move and path tests.

## Command and result
`pytest test_plugin_layers.py test_plugin_session.py test_plugin_surfaces_membership.py tests/pure` (QGIS venv): `581 passed, 3 skipped in 350s`. ruff check/format and mypy (CI list) clean. I did not run these new tests against the old code for a RED; the first failure they pin (blank row read as unsaved) is the reviewer's probe C.
