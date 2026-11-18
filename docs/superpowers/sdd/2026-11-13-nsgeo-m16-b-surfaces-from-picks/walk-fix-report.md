
# Walkthrough fix round 1: a pick in several surfaces; build messages stay (Ruling R14)

## Changes
- `surface_plan.py`: `feature_ids(value)`, `join_feature_ids(ids)`, `also_note(also, n)`; `move_note` removed (no callers left).
- `layers.py`: `members_by_feature` lists a pick under each known id; `set_pick_feature` replaced by `add_pick_feature` / `remove_pick_feature` / `clear_pick_feature(id)`, all through one `_edit_pick_features` (raw provider read, one `changeAttributeValues`, unchanged rows not written, returns rows changed).
- `surfaces.py`: `SelectionCheck(refusal, grid_id, also, n)` (`moving`/`left` gone); create adds, add_picks writes/signals only on change, remove_picks removes only this id (fewer-than-3 refusal kept), delete takes only its id out. Transaction guard unchanged.
- UI: new-surface dialog and Surfaces dock show "N of these picks are also in “X”" (informational).
- Export: `picks.vtp` `feature` = first built surface of the pick's list, else -1; new int32 `n_surfaces`. Scene README updated.
- `plugin.message(..., duration=6)`; surface-build results and failures use `duration=0`. Other messages untouched.
- Docs: spec §4 call 8 and guide amended.
- Tests: moves-pinning tests replaced; added create-from-A-keeps-A, remove-from-B, delete-A, hand-edited column (" a ; ;b;a " -> a,b), CRS rebuild keeps multi-membership, no-op add emits nothing, export `feature`/`n_surfaces`, dialog/panel "also in", message duration 0 (and 6 otherwise). Two build tests and one monkeypatched `message` lambda adapted.

## Tests
- Pure + core: `.venv/bin/python -m pytest packages --ignore=packages/nsgeo-qgis/tests/qgis` -> 1670 passed, 8 skipped, 1 xfailed.
- Whole QGIS tier, one process: 2583 passed (34 min).
- ruff check, ruff format --check, mypy (CI list): clean.

## Concerns
- None blocking. Existing sites with a single id in `feature_id` need no migration. A hand edit that writes a dangling id is ignored on read, as before.

## Fix report (review findings)
- Important: new `test_a_built_surface_stays_fresh_when_another_takes_its_picks` (built_site): A built, B created from its picks -> A built and fresh, `inputs(A)` unchanged; B built then a pick removed -> A fresh, B stale `("picks",)`.
- `also_note`: "This pick is also in …" for one selected; "1 of these picks is also in …"; pinned in the pure test.
- `seq` comment in layers.py and one line in spec call 8: one `seq` cannot order a pick in two ordered features.
- No-op add test asserts `add_pick_feature(...) == 0`.
- Plan: call 3 and the `move_note` line marked superseded by R14.
- Tests: pure tier 346 passed, 4 skipped; touched QGIS files (membership, build, dialog, dock) 94 passed; ruff check/format clean.
