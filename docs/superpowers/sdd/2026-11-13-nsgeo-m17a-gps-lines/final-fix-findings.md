# M17a final review — the one fix wave (controller ruling R17)

Fix every item below in one round. Items are quoted or condensed from the final whole-branch review.

## Important 1 — the velocity fit and its guide sentence (plan defect P14)

"ProfileDock._velocity_axis()[2] (distance[1] − distance[0]) is thrown away at every call site
(profile_dock.py:1258, 1284, 1304, 1592). The fit uses x_m = distance[trace] for each clicked point
(profile_dock.py:1253-1266, then fit_hyperbola(x_m, …) ~1407). For a GPS line that is the WALKED
distance at the clicked traces. Effect: the guide says 'a hyperbola fit uses the wheel's spacing at the
start of the line', which is false; the test pins a value nothing uses, so it would pass whatever the
fit does; near a bridge or a lift the walked spacing is spread evenly, which can bias the velocity."

Fix:
- docs/guide/getting-started.md:427-428 — rewrite: the fit measures along the walked distance at the
  clicked traces; fit hyperbolae away from stretches without RTK and lifts until true-distance profiles
  arrive (M17b). Plain but professional, like the rest of the guide.
- packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py:~2243 — replace
  test_the_velocity_fit_on_a_gps_line_uses_the_wheel_spacing with a test that pins the fit's points in
  metres (velocity_points_in_metres(), or whatever the dock exposes) equal to distance_along() at the
  clicked traces, on a GPS line whose middle spacing differs from the wheel's (e.g. a bridge). Show it
  fails if the fit used trace × wheel spacing.

## Important 2 — the Set destagger box steps 1.0 m (must fix)

"plugin.py:2749-2758: QInputDialog.getDouble(...) is called with 7 arguments, so Qt's default step of 1
applies on a ±2 m box. One scroll turns 0.24 into 1.24 (or clamps to 2.0), and OK applies it to every
selected line. This is the hazard class the author filed as #109/#177."

Fix: step 0.01, matching the import dialog's Destagger box (PyQt5's getDouble overload in .venv-qgis
has no `step` keyword — use the full overload with flags then step, if both PyQt5 and PyQt6 accept it,
or a QInputDialog instance with setDoubleStep(0.01) / a small dialog with a QDoubleSpinBox). Keep the
Copy's title, label, range, decimals and starting value. Update
test_plugin_survey_dock.py::test_set_destagger_starts_at_the_shared_value_and_applies_to_all (its
7-tuple unpack) and assert the step is 0.01. It must work on QGIS 3 (Qt 5) and QGIS 4 (Qt 6): use only
qgis.PyQt and API both have; nsgeo_qgis/qtcompat.py holds the project's Qt 5/6 shims — look there first.

## Minor 1 — "Coordinates:" shown twice in the import dialog

"ui/gps_import_dialog.py:154 and :301: the form-row label 'Coordinates:' is followed by crs_label
reading 'Coordinates: EPSG:32632'. The approved mockup shows 'Coordinates:' once, then the authid and
the note." Fix: crs_label shows the authid alone (and the grey note as now); update the assertions in
test_plugin_gps_import_dialog.py.

## Minor 2 — guide text

- getting-started.md:402: "It needs an open site, and no grid" reads as "must have no grid" — say that
  a grid is not needed.
- :114: the greyed-out-until-a-site-is-open list omits **Import GPS lines…**.
- :761: the GeoPackage row omits **rtk_gaps**.

## Cheap extras (same round)

- dzg.py: a dropped (bad-checksum) `$GSSIS` must clear the pending trace, like a dropped GGA, so a later
  GGA never pairs with an older GSSIS (two-fault stale pairing). Add a test: GSSIS 5, (GGA missing),
  corrupt GSSIS 9, GGA → no fix, counted unpaired; show it fails on the old code.
- Rename the stale test `test_version_3_loads_and_4_is_refused` to what it now checks.

## Not in this round

- rtk_gaps layer shown on tape-only sites — a walkthrough question for the author.
- set_site_crs not rolled back if add_lines fails — parked (unreachable through the UI).
