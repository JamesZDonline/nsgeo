# M17a final fix wave report

Status: DONE (all items, none NEEDS_CONTEXT).

- Important 1: guide sentence rewritten (walked distance at clicked traces; fit away from RTK gaps/lifts until M17b). Test replaced by test_the_velocity_fit_on_a_gps_line_measures_along_the_walked_distance: pins velocity_points_in_metres() == distance_along() at the clicked traces on a line whose middle is 0.12 m/trace. Also fixed the test helper _open_gps(track=): it built lat from t*m instead of m (the old test never noticed). Mutant (x = distance[0] + trace*wheel) FAILS the new test (6.0 vs 6.2 m...), real code PASSES.
- Important 2: open_destagger_dialog uses the full getDouble overload, `Qt.WindowType(0)` then step 0.01 (PyQt5 docstring shows this overload; flags positional, no step keyword). Test unpack now 9-tuple and asserts step == 0.01. RED: ValueError on 7-vs-9 unpack with old code; GREEN after. Only PyQt5 run here; Qt6 overload (parent,title,label,value,min,max,decimals,flags,step) is the same signature, Qt.WindowType(0) valid on both - not run on QGIS 4.
- Minor 1: crs_label shows authid alone; 7 assertions updated. RED: 6 failed with old code; GREEN 23 passed.
- Minor 2: guide: "a grid is not needed"; Import GPS lines… in the greyed-out list; rtk_gaps in the GeoPackage row.
- Extras: dzg.py: dropped $GSSIS clears pending (counted unpaired like a dropped GGA). New test test_a_dropped_gssis_clears_the_pending_trace: RED before (1 failed, 16 passed), GREEN after. Renamed test_version_3_loads_and_4_is_refused -> test_a_site_loads_and_a_newer_schema_version_is_refused.

Runs: core+pure 1648 passed, 5 skipped (skips unchanged); qgis test_plugin_survey_dock 91, test_plugin_gps_import_dialog 23, test_plugin_profile_dock 121 (all passed); ruff check + format clean; mypy clean (57 files).
Concerns: Qt 6 not exercised locally. Full QGIS tier not run.
