# Task 5 report: Gap over in Edit lines, and the guide

Status: DONE

## Implemented
- `TrackEdit.gap_m` / `gap_auto`; `placed()` applies them (gap_auto wins); `changes()` now compares `gap_m` (typed change, or auto returning a typed line to automatic).
- Edit lines: `COL_GAP` ("Gap over (m)", after Destagger, tooltip GAP_TIP); GPS rows editable ("auto 0.10" / "0.35"; "auto —" when the usual step is 0), tape rows "—" and non-editable, typing there is ignored; empty -> automatic; bad text -> `{text!r} is not a length above 0; unchanged`, cell keeps value.
- Bulk row (Gap over (m), spin 0.01-10 / 2 dp / 0.01 step / 0.10, Set, Automatic): via `_apply(gps_only=True)`, same pending-edit path as Destagger, takes effect on OK; tape rows counted and left alone, status `TAPE_SKIP`.
- `gap_threshold` re-exported from `nsgeo.geometry` + core README row. Session docstring updated.
- Guide: GPS profile paragraph (true distance, one hatched gap, Gap over, auto 6x usual step) and the Edit lines GPS paragraph.

## TDD
RED: pure `test_a_track_edit_sets_gap_over_and_returns_to_automatic` -> TypeError unexpected keyword 'gap_m'; QGIS file -> ImportError cannot import COL_GAP. GREEN: both pass after implementation.

## Results
- QGIS 4 touched files: 126 passed; `-m real_data` on them: 1 passed; core+pure: 2231 passed, 9 skipped, 19 xfailed; ruff check + format clean; mypy clean.

## Tests added
pure: the gap-over TrackEdit test. QGIS (test_plugin_edit_lines_gps.py): automatic cell, typing/clearing, bad values (parametrized), tape dash, bulk Set/Automatic + TAPE_SKIP, no tape note when only GPS selected, extremes reach the profile (0.01 then 100: axis.gap_m and placement), save and reopen. Added `_fine_gps` (60 traces/m, made-up place) and `fine` fixture.

## Existing tests changed
None. No existing test addressed columns by a hard-coded index that broke.

## Self-review
- Gap-over-only edit is not counted as moving picks (`_counts` only counts travel_shift): correct.
- Not run: QGIS 3.44 (only the default qgis_tests.sh target).
## Concerns
None. Guide still carries the hyperbola-fit-along-walked-distance caveat (unchanged), with "until true-distance profiles arrive" removed only from that clause.

## Fix round 1
Changes: extremes test now asserts `s.stack_for(key).source.gap_m == want`; guide: destagger "comes later", hyperbola caveat reworded (RTK stretches; no ground recorded in a gap), bulk Gap over sentence added; new test for `auto —` (distance_along monkeypatched to zeros, since import refuses a standing track); dialog uses `check_gap_m` and the COL_GAP branch joins the elif chain (tape guard stays a separate early return); tape "—" Gap cell carries GAP_TIP (asserted); exact `auto 0.60` assertion.
Covering: test_pure_line_edit.py 21 passed 1 skipped; test_plugin_edit_lines_gps.py + _dialog.py 87 passed (qgis_tests.sh); ruff check/format clean; mypy clean. Core untouched, core+pure not rerun.
