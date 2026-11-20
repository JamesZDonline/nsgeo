# Task 1 report: picks on cuts join surfaces

## Implemented
- `place_picks(..., *, cuts=None, grid=None)`: a cut pick is placed from `cut.point_at(distance_m)` -> `grid.to_world` -> `frame.to_local`; time is `p.time_ns` (never retimed); base from `cut_pick_base` vs `time_base_of(prov.steps)`; missing cut / grid / other clock / no distance -> None; `trace` = stored column.
- `surface_plan.py`: `cut_pick_base`, `WHY_OTHER_CLOCK`, `WHY_NO_CUT`; `selection_refusal` lost `on_cuts`.
- `surfaces.py`: `_grid_of` answers cut keys (None on KeyError); `check` stops counting cuts; build passes `cuts`/`grid` and gives WHY_NO_CUT / WHY_OTHER_CLOCK / WHY_NO_DEPTH; `inputs()` cut picks hash `[key, round(distance,4), round(radar_ns,6)]`, `source` gains `"cuts"`.
- Guide sentence replaced.
- Not in the brief but required: `Surfaces.line_label` raised KeyError for a cut key (outlier labels in `_write`); it now returns the cut's name, or "a deleted cut".
- Test updates: pure refusal tests lose `on_cuts`; membership `test_picks_on_a_cut_are_refused` became `test_picks_on_a_cut_that_is_gone_cannot_be_placed` (an unknown cut key is now "not on a line of a grid").

## TDD
RED: pure test file and build test file failed at collection (ImportError: cannot import name 'cut_pick_base' / 'WHY_NO_CUT'), expected as the symbols did not exist. GREEN after implementing: pure 18 passed. First QGIS run: 5 of 6 cut tests failed with KeyError in `line_label` (found, fixed); one failed on my test's clock (line pick retimed by the line's zero; cut time corrected to 10.0 - zero). Final: 3 QGIS files 114 passed (170 s).

## Verification
- `qgis_tests.sh` surface_build + surfaces_membership + paraview_export: 114 passed.
- `qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data`: 44 passed.
- ruff check / format --check: clean; mypy (core + surface_plan.py, slices_plan.py; the venv mypy): clean.
- core+pure: see final line below.

## Notes
- `ruff format` run on `packages docs` accidentally touched docs/superpowers; reverted with `git checkout -- docs/superpowers` before commit.
- The outside-frame test asserts `on_holes + at_edge >= 1` with a cut running to 20 m on a 12 m grid.
- core+pure: 1960 passed, 9 skipped, 19 xfailed.

## Fix round 1
- I1: outside-frame test now asserts the cut pick's own outlier (line_key == cut, reason "hole") and that place_picks puts it at y >= ny*cell. RED: mutation clamping y onto the grid -> test failed; GREEN restored.
- I2: "cuts" added to the source hash only when the surface has member cuts. New test compares a line-only surface's source hash with the five-key dict. RED (always-add mutation): failed.
- I3: `session.cuts_changed` added to SurfacesDock._signals; dock test (cut pick surface, remove_cut -> row "stale"). RED (signal removed): failed.
- M1: kept cut names out of the line range and named them as cuts: `selection_label(..., cuts=())` gives "(lines A to B; cuts Cut 1, Cut 2)"; pure test added; plugin comment fixed and plugin splits labels by is_cut_key.
- M3: unit test with Grid origin (500,700) azimuth 30 and its CubeFrame; RED with to_world dropped: failed.
- M4: radar-clock test (radar cut pick placed, time_zero left out; build skip reports WHY_OTHER_CLOCK).
- M6: LABEL_DELETED_CUT moved to surface_plan.py.
- Commands: qgis_tests.sh on surface_build, surfaces_membership, surfaces_dock, paraview_export: 145 passed; pure surface_plan 18 passed; ruff check and format --check on the 7 changed files clean.

## Fix round 2
- test_plugin_new_surface_dialog.py: renamed to `test_cut_picks_open_the_dialog_unrefused_but_picks_on_a_removed_line_are_refused`. The cut is bent ((1,1),(5,1),(5,5)) with picks at 1, 4, 6 m so they are not collinear; asserts the refusal label is empty (Create also waits for a name, so the button is not asserted) and the removed-line half still reads "not on a line of a grid" with Create off.
- Grep of tests for `on_cuts` / "on a cut" / "later version": no other stale expectation (membership test already updated in the first commit).
- Run: new_surface_dialog file 12 passed; ruff check and format --check clean.
