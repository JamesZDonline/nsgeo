# Task 3 report: GPS rows in Edit lines

Status: DONE

Changes (packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py):
- Constants GPS_TIP, GPS_SKIP, GPS_BLANK. GPS rows hold a TrackEdit; edit_for returns LineEdit | TrackEdit.
- Render: Offset/Dir/Start/Scale "—", read-only, tooltip; Along "GPS"; Length = walked distance; header axes ignore GPS rows.
- _apply(tape_only=what) counts and skips GPS rows for Offset, Dir, Start (set + snap), Scale; fit_to_edges skips with "Fit to grid edges"; destagger and move apply to all.
- Measure: snapshot holds tape rows only; GPS selection says GPS_SKIP (start and at landing); only-GPS selection starts nothing.
- _live, _changes, blanking of unchanged rows, _counts, dirty colouring and _item_changed branch on TrackEdit.
- A GPS skip note replaces the status line, as the existing fit/drop notes do.

Tests: tests/qgis/test_plugin_edit_lines_gps.py (16 tests). RED: ImportError on GPS_SKIP at collection. GREEN: 16 passed; with every test_plugin_edit_lines*.py + test_plugin_survey_dock.py: 217 passed. ruff check/format clean; CI mypy line clean (dialog is not in CI's mypy list).
Test-side note: the fixture's T2 is reversed so Measure has two directions to compare.

## core+pure result for 9e1f030
`1 failed, 2078 passed, 9 skipped, 19 xfailed in 1112s`. The one failure, packages/nsgeo-core/tests/test_hyperbola_trace_hand_fits.py::test_the_largest_box_traces_within_a_second, is a one-second timing assert run on a 4-core machine shared with another session's QGIS loop; not rerun alone; no core code touched.

## Fix round 1
- I1: GPS Length is now `walked[-1] - walked[0]` (path length without the destagger). New test `test_a_gps_rows_length_does_not_include_its_destagger` opens a dialog on a line made with `open_gps(travel_shift=0.3)` and compares with the destagger-0 cell; verified it FAILS with the old formula (1 failed, 18 passed) and passes now.
- M1: fixture T1 starts at 3.0 so Snap moves it; each tape-only case asserts T1 changed (and T2 too except Start-type cases).
- M2: Measure with no tape target says the GPS note, plus `MEASURE_NO_TARGETS` when tape rows were selected but moved off the grid; comment rewritten. New test pins the two-part status.
- M3: GPS note dropped at Measure start; kept when it lands (test no longer asserts it at start).
- M4: the read-only guard calls `_refresh()`; test `test_typing_into_a_gps_rows_read_only_cell_goes_back_to_the_dash`.
Command: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines*.py -q -p no:cacheprovider` -> `98 passed in 51.03s` (gps file alone: 19 passed). ruff check/format and the CI mypy line clean.
