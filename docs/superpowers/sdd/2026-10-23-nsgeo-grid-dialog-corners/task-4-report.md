# Task 4 report: the grid's CRS chooses itself (#62)

Status: DONE. Commit 57db966, pushed to origin/nsgeo-grid-dialog.

## Implemented (grid_dialog.py, plugin.py, conftest.py, tests)
- GridDialog(canvas=...), crs_is_auto(); _crs_auto (true for new grid, false for existing), _setting_crs guard, _grid_crs.
- _crs_scale_error(crs, point=None) (None = form origin, skipped at (0,0)); _crs_check(crs, point) runs the three checks (authid/units/scale) and returns (failed check, scale error); _usable_at(crs, lonlat) wraps it for a location. _validate uses _crs_check; thresholds and messages unchanged.
- Auto choice (_choose_crs): site CRS (grids[0].crs), project CRS, UTM zone of the location (utm_epsg). Used at open (canvas centre) and at every Fit (centroid of filled corners, after the half-row check, before the metric refusal). The refusal now only fires for a hand-picked CRS in practice.
- Hand pick (crsChanged outside the guard): clears auto, converts origin + azimuth (bearing of origin -> +100 m along +Y), skipped at origin (0,0); on failure restores the old CRS and shows a message in crs_hint. An auto switch at Fit converts the origin the same way.
- Hint = _validate problem, then a transient hand-pick message, then the auto note, joined with " · ". No canvas: stays on project CRS; the "a UTM zone will be picked when you fit corners" note is shown only when the project CRS is unusable by authid/units (a usable project CRS gets no note) -- my call.
- Off-by (carried item): blank unless _crs_check(grid crs, form origin) passes. Test covers 4326, EPSG:2264, 3857.
- plugin.py: only passes canvas=self.iface.mapCanvas().

## Test helper
conftest: `_real_canvas(fake_iface, crs, extent)` plus a `real_canvas(crs, extent)` fixture that builds a FakeIface per call and closes/deleteLater()s its window afterwards (tests use the fixture). The 1.0 m/px assertion is inside the helper, conditional on a metric CRS and an 800 x 600 extent. resize() alone did not give 800x600 (layout wins, then the canvas frame costs 2 px), so it uses setFixedSize and grows it until mapSettings().outputSize() is exactly 800x600 (asserted).

## Tests: 11 new (70 in file); all 8 brief tests plus hand-pick-cannot-convert and off-by-blank (+ one more brief-named: 4326 polygon).
- RED: 11 failed, 59 passed before implementation (TypeError unexpected kwarg 'canvas' for canvas tests; behavioural failures for hand-pick/off-by tests).
- GREEN: file 70 passed; qgis tier 950 passed (453 s); pure+core 748 passed, 3 skipped; ruff check/format clean; mypy clean.
- Excepthook check: temporary autouse plugin (scratchpad, uncommitted) failing on sys.excepthook / sys.unraisablehook: 70 passed, nothing fired.
- Deviation in test_hand_picking_a_crs_converts_origin_and_azimuth: 100 along +Y in EPSG:32617 is not 100 m on the ground (0.3% scale, 0.33 m off), so the test compares direction (unit step scaled to 100 m) within 1e-2, not the raw 100-unit point.

## Concerns / notes
- Hand-picking a CRS with a non-metre old CRS keeps the azimuth (no 100 m step possible); origin still converts. Picking a geographic CRS converts origin to degrees (3-decimal spinbox, lossy); fine since it is refused anyway.
- If Fit fails after an auto CRS switch, the CRS stays switched (origin converted, so still the same ground point).
- If a candidate CRS cannot place the location, it is treated as unusable ("outside").
- A programmatic setCrs to the CRS already shown emits nothing, so a "hand pick" equal to the current auto CRS leaves crs_is_auto true.

## Fix round 1 (R10: full-precision ground anchor)
Changes (grid_dialog.py): `_anchor` = (metric CRS, E, N, azimuth) at full precision. Written by `_write_numbers` (used by Fit, prefill and conversions) whenever the target CRS is metric; refreshed by `_on_numbers_edited` on a hand edit of origin/azimuth while the grid CRS is metric, dropped by such an edit while it is not. `_convert_grid` now converts from the anchor when present (azimuth = bearing in the new CRS's axes between the transformed origin and the transformed point 100 m along +Y in the anchor's metric CRS, so degrees/feet targets get an azimuth too); with no anchor it falls back to the old best-effort conversion from the boxes. Origin (0,0) still skips (and drops the anchor). Failure behaviour unchanged.
Tests: new parametrised round trip via EPSG:4326 / 2264 / 32617 (origin 1e-3 m, azimuth 1e-6 deg); hand edit in 4326 wins over the anchor; origin reset removed from the off-by test (still passes).
RED (new code swapped for HEAD's): 2 failed (4326, 2264 round trips), 72 passed; 32617 and the hand-edit test pass on old code as expected.
GREEN: grid file 74 passed with the excepthook guard (nothing fired); qgis tier 954 passed; pure+core 748 passed, 3 skipped; ruff and mypy clean.

## Fix round 2 (R11)
Changes (grid_dialog.py): new `_chord(src, dst, ox, oy, az)` = transformed origin plus the bearing in dst's axes to the transformed point one step along +Y in src's axes (100 units projected, 1e-3 degrees geographic); `_convert_grid` uses it from any source, anchor or fallback (the metres-only condition is gone). `_on_numbers_edited(part)` now, in a non-metric CRS with an anchor, re-derives only the edited part (origin edit: boxes' origin into the anchor CRS, anchor azimuth kept; azimuth edit: chord-converted azimuth, anchor origin kept); a transform failure drops the anchor.
Tests: extended the hand-edit test (azimuth 1e-3 of 10.0); new feet origin-move test, azimuth nudge-and-undo in degrees, no-anchor feet fallback azimuth. The feet test compares against an independent transform (10 ft east in the state plane's own axes is not exactly 3.048 m east in UTM).
RED (previous code swapped in): 4 failed, 73 passed. GREEN: grid file 77 passed with the excepthook guard (nothing fired); qgis tier 957 passed; pure+core 748 passed, 3 skipped; ruff and mypy clean.
