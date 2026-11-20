# Final fix wave, M16 D

Per item (files under packages/nsgeo-qgis unless noted):
- I1: surface_layers.py connects/disconnects `cuts_changed` to `request_sync`. Test `test_deleting_a_cut_relabels_its_surface_stale_on_the_map` (test_plugin_surface_layers.py). RED with the connect removed (spin_until false); GREEN with it.
- I2: surfaces.py `inputs()`: cuts move into "picks" (`input_hash(picks)` unchanged when no cuts), out of "source". Tests updated: deleted-cut test now `stale == ("picks",)`; dock test asserts the same; new `test_adding_a_cut_pick_to_a_surface_reads_as_its_picks_changing`; new line-only "picks" hash pin. RED with the old hashing (3 failures in the batch), GREEN after.
- M1: ui/surfaces_dock.py opens a cut outlier via `session.open_line(key)` when `key in session.cut_keys()`; deleted cut only selects. Cursor is NOT moved to the pick (a cut pick's column is a record only; the section's column needs the loaded section). Test `test_clicking_a_cut_pick_outlier_opens_its_cut`. RED with the branch disabled (current_key stayed on a line), GREEN after.
- M2: surfaces.py build only takes cuts with `cut.grid_id == grid_id`; others get WHY_NO_CUT. Test `test_a_cut_pick_whose_cut_is_on_another_grid_is_reported_not_placed` (RED with guard off).
- M3: surface_plan.py: `selection_refusal(deleted_cut=)` says "N of these picks is/are on a cut that has been deleted, so it/they cannot be placed."; `selection_label(..., deleted_cuts=)` adds "a deleted cut" / "N deleted cuts"; LABEL_DELETED_CUT removed, `line_label` no longer special-cases it; plugin.py/surfaces.py `check` count deleted cuts. Pure tests in test_pure_surface_plan.py; membership test updated.
- M4: guide and paraview README edited as asked.
- M5: `_write_walls` uses `_cut_paths` (signature now takes grid_id, cut_keys); `estimate` and `summary` share `_sizes`/`_total_bytes`, which the run's refusal also uses. `estimate` kept (tests use it).
- Fold-ins: (a) try narrowed to line_wall/cut_wall; (b) z.nz > nd asserted; (c) vtkxml docstring "All three write"; (d) test renamed `..._size_estimate_is_a_tight_upper_bound`.

Verification: QGIS surface_layers/build/membership/dock/new_surface_dialog 132 passed; paraview_export/dialog/scene3d 139 passed (pvpython set); `-m real_data` 50 passed; core+pure 1980 passed, 9 skipped, 19 xfailed; ruff check, ruff format --check, CI mypy clean. Grep found no other stale pins.
