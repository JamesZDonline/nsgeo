# Task 2 report: cut picks in the export and the 3-D view

Implemented: picks.vtp gains int32 `cut` (line = -1 on cut picks); export.json `cuts` ([{index,key,name}], every saved cut on the grid in key order, even with no picks); scene_record validates/defaults `cuts`; _pick_counts/summary count cut picks; pick_depths answers cut keys (cut on grid_id, cut_pick_base == time_base_of(steps), stored time, no zero read); guide bullet "Which picks" rewritten (R3).
Scene3D needed NO change (R4): cut picks carry a map point on the picks layer, so pick_depths answering them is enough.

TDD: RED before implementation: pure test_scene_record_validates_cuts (KeyError 'cuts'); test_cut_picks_are_in_picks_vtp_with_their_cut (KeyError 'cut'); the empty-cuts test (KeyError 'cuts'); test_pick_depths_answer_cut_keys... (None != depth); test_the_3d_view_shows_the_grids_cut_picks (spin_until never reached 5 points). test_a_cut_pick_on_another_clock_is_left_out passed already (Task 1's place_picks refuses it; it guards the export path).
GREEN: pure test_paraview_scene 22 passed 3 skipped; qgis export+scene3d+surface_build 138 passed; `-m real_data` 44 passed; ruff check/format clean; mypy (ci list subset) clean; core+pure see below.
Stale-test grep: no test pins picks.vtp array list or export.json exact keys other than the new ones.
Files: paraview_export.py, paraview_scene.py, docs/guide/getting-started.md, three test files.
Core+pure: 1961 passed, 9 skipped, 19 xfailed. Three QGIS files re-run: 138 passed. Committed and pushed.

## Fix round 1
Changes: I1 `session.cuts_changed` added to Scene3D._signals; M1 `cut_pick_on_clock(pick, steps)` in surface_plan.py (distance not None and base == preset base), used by place_picks, pick_depths, surfaces.py (and _pick_counts); M2 cuts list built once in `run`, passed to `_write_picks` and `_record` so scene_record validates it; M3 `_write_picks` grid and cut_keys required; M4 `-1 if p.line_key in cuts else order[...]`; M5 other-clock test writes one on- and one off-clock pick, asserts one point, cut == [0], its depth, n_picks 1; M6 `_pick_counts` counts only on-clock cut picks (summary n_picks == picks.vtp points, asserted in the M5 test); M7 scene test asserts the cut pick's x/y equal cut.point_at -> grid.to_world; M8 time_base_of computed once in pick_depths (now only via the predicate / on_zero).
RED (before code): pure test_a_cut_pick_is_on_the_clock... = ImportError on cut_pick_on_clock; M5/M6 test `assert 2 == 1` (summary n_picks); the cuts_changed test failed (`assert False`, picks layer stayed at 5).
GREEN: qgis export+scene3d+surface_build 139 passed; pure test_paraview_scene + test_pure_surface_plan 41 passed 3 skipped; `-m real_data` 44 passed; ruff check clean, ruff format --check clean on changed files, mypy clean.
Note: the M7 x/y assert passed immediately (it pins existing behaviour).
