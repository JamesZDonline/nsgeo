# Final fix wave report (commit 6ef2762, pushed)

Status: DONE. Each new test was run against HEAD (bd668a1) sources and failed for the stated reason; all pass with the fix.

- F1: MIN_MEASURED_SIZE=0.1; Fit refuses with the ruled message (smallest measured size, Corners-in authid); Fill refuses a layer with an invalid CRS. Tests: test_degrees_typed_as_metres_are_refused (was "rigid fit RMS 0.000 m from 4 corners"), test_degrees_typed_as_metres_leave_an_existing_grid_alone (result_grid()==original; same), test_fill_refuses_a_layer_without_a_crs (status was empty).
- F2: _half_filled_row replaced by _unreadable_row (only-one-coordinate, else "{role}: {text!r} is not a number: fix it or clear the row"). Test: test_fit_refuses_a_row_whose_text_did_not_parse (was RMS 0.000 from 3 corners).
- F3: guide Step 2 edited (CRS box + site grids first; "or, failing that"; layer list/feature list unbolded; Rotate; RMS meaning). Also added a sentence on the new refusals. Other Step 2 sentences checked against the code; no other changes needed.
- F4: Fit snapshots CRS/numbers/anchor/auto note/message (_GridSnapshot) and _restore_grid undoes an automatic switch on every refusal (also on exception). _apply_auto_crs records _convert_grid's error in _crs_message and clears a stale one on a switch; a successful Fit that switched also clears it. Tests: test_a_refused_fit_puts_an_automatic_crs_back (was EPSG:32619), test_a_successful_automatic_switch_clears_a_stale_hand_pick_message (stale text stayed), test_an_automatic_switch_that_cannot_convert_says_so (hint was empty).
- F5: _project_reason "outside" branch returns "the project CRS (X) does not reach this location"; _choose_crs already prefixes "picked for you: ", so the prefix is not repeated. Not constructible end to end (no real CRS made the transform raise at a lon/lat), so test_the_project_reason_for_a_crs_that_does_not_reach_the_spot calls the method directly (was "is off by 0.0% here").
- F6: _lonlat returns None for |lat|>90 or |lon|>180; Fit checks a geographic Corners-in CRS up front and refuses with the ruled message, before the automatic CRS is touched. Test: test_metres_typed_under_lon_lat_are_refused_as_such (was "could not convert the corners into EPSG:32616").
- F7: site note only when site CRS != project CRS. Test: test_the_site_note_is_only_shown_when_the_site_differs_from_the_project (note was shown).
- F8: anchor comment, _convert_grid docstring (chord rule), _signed_area centred on the mean. Pure test test_corner_frame_sees_collinear_points_at_utm_magnitudes (0.1 m steps at UTM magnitudes; failed on HEAD, was not reported as "in a line").
- F9: the two vacuous retypes now type a differing value (test_fit_status_keeps_the_last_fit_line_through_row_changes; test_a_persistent_overlay_failure_does_not_replace_the_fit_line, which also first covers the Fit line with an error). These assert existing R6 behaviour, so they pass on HEAD code by nature; confirmed they now bite by mutating _rows_changed to not restore the Fit line: both failed. The "ok" overlay case now answers Discard and unloads. LOCAL removed.

Verification:
- grid dialog file: 131 passed
- qgis tier: 1028 passed in 407.76s
- pure + core: 749 passed, 3 skipped
- ruff check: All checks passed; ruff format --check: 146 files already formatted
- mypy: Success: no issues found in 34 source files
- git grep digitis: only metadata.txt "digitised on the map" (0.1.0 changelog line)

Files: nsgeo_qgis/ui/grid_dialog.py, nsgeo_qgis/lookup.py, docs/guide/getting-started.md, tests/pure/test_pure_lookup.py, tests/qgis/test_plugin_grid_dialog.py.

Concerns: (1) Fit's up-front lon/lat check runs for any geographic Corners-in CRS, so it refuses before the unreadable-row check is reached only if rows parse (order: unreadable row, then lon/lat, then settle). (2) A successful Fit that switched CRS clears _crs_message (my addition, beyond the brief, so a conversion error from that same switch does not linger). (3) F5 only unit-tested directly.
