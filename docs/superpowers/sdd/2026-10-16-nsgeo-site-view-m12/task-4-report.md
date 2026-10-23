# Task 4 report: the site GeoTIFF

## Implemented
`packages/nsgeo-qgis/nsgeo_qgis/site_export.py`: SiteGridRecord, SiteBand, SiteExportPlan, plan_site_export,
SiteWriter protocol, GeoTiffSiteWriter (OPTIONS is M11's list, same object), export_site (one slice_at per band,
lazy generator), apply_site_temporal_properties, write_site_coverage, helper band_window_ns. slice_export.py untouched.
Choices: cell_m = first ready grid's frame.cell; a grid with no velocity gets null depths and no depth text (an
absent grid reads "X no data"); coverage companion is written at the first band's window with method "none" and
description "coverage: traces per cell" via the same writer; band factors are from each band's own SiteSlice
(null if absent); depths/description from each grid's window_on result (trap 5). No new signals or slots.

## Results
- core+pure: 604 passed, 2 skipped. qgis tier: 793 passed (780 + 13 new). ruff check, ruff format --check, mypy: clean.
- TDD: RED = ModuleNotFoundError on nsgeo_qgis.site_export at collection; GREEN = 13 passed (one test, the overhang
  depths test, first failed for lack of a straddling band; fixed the test's step to 3 levels).

## Mutants (PYTHONDONTWRITEBYTECODE=1)
| Mutant | Result |
|---|---|
| 1. per-band factors from the first band | FAILS test_each_band_records_every_grids_factors_and_depths, test_an_absent_grid_is_null_in_the_band_metadata |
| 2. depths from requested (site) window times | FAILS test_depths_come_from_the_window_each_grid_actually_got |
| 3. absent grid factors written [1, 0] | FAILS test_an_absent_grid_is_null_in_the_band_metadata |
Real code passes all 13 after each.

## Sample dump (site3, edge, amp_envelope)
Dataset: NSGEO_SITE_CELL_M=0.25, PIXEL_M=0.25, FILL_RADIUS_SPACINGS=1.5, NORMALISATION=edge, TRANSFORM=amp_envelope,
Z_UNIT=ns, GRIDS=[{"grid_id":"A","preset":"p","velocity":{"layers":[{"top_ns":0.0,"v_m_ns":0.1}]},"gain":1.0,
"line_spacing_m":1.5,"azimuth_deg":0.0,"crs":"EPSG:32616"},{"grid_id":"B",...layers 0.08/10.0:0.12, "gain":2.0},...].
72x24, origin (500,706), pixel 0.25, EPSG:32616.
Band 1 description: "2.0-5.5 ns · A 0.10-0.28 m · B 0.08-0.22 m · C 0.10-0.28 m"
Band 1 metadata: NSGEO_WINDOW_NS=2.0,5.5; NSGEO_GRID_DEPTHS_M={"A":[0.1,0.275],"B":[0.08,0.22],"C":[0.1,0.275]};
NSGEO_GRID_FACTORS={"A":[1.029...,0.0],"B":[1.9916...,0.0],"C":[0.9758...,0.0]}

## Files
site_export.py (new), tests/qgis/test_plugin_site_export.py (new, 13 tests), this report.

## Self-review / concerns
Test for "no resident cube" checks lazy one-per-band pulling and that no engine is resident; mode name "resident" is
M11's. Mutant 2 is caught only by the overhang test (the description test is self-consistent with the plan).

## Fix round 1
Changes (site_export.py and its test only):
1. Ready grid with no site axis: azimuth_deg and crs now come from session.grid(id); cell_m from the first grid that
   has a frame (lattice.pixel if none); z None is treated as absent (null depths, "X no data"). New test
   test_a_ready_grid_with_no_site_axis_exports_as_absent (samples C=128, Resolution(0.25, 0.5, 16.0, 60.0)).
2. Coverage companion plan: method "none", radius_spacings None (key NSGEO_SITE_FILL_RADIUS_SPACINGS omitted, as M11's
   radius_cells=None), every recorded grid gain 1.0 (documented in code). New test reads the companion's metadata back.
3. Coverage test now compares the band with slice_at(..., coverage=True).array (equal_nan) and asserts whole numbers >= 1.
4. New test_every_band_is_nodata_nan_on_read_back; the companion test also checks nodata.
Run: pytest test_plugin_site_export.py -> 16 passed; core+pure 604 passed, 2 skipped; ruff, format, mypy clean.
Mutants (each FAILS, real code restored passes):
- slice_at without coverage=True: FAILS test_the_coverage_companion_is_written_beside_it
- SetNoDataValue removed: FAILS test_every_band_is_nodata_nan_on_read_back and the coverage companion test
- companion keeps method/radius/gains: FAILS test_the_coverage_companion_does_not_claim_processing_it_never_had
- old frame dereference (engine.frame.azimuth): FAILS test_a_ready_grid_with_no_site_axis_exports_as_absent
Note: when a test fails in this file the pytest process exits 139 (segfault at interpreter exit) after printing the F;
passing runs exit cleanly. Not investigated; the qgis tier was not re-run as only these two files changed.
