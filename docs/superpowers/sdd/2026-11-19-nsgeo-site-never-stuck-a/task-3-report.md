# Task 3 report: #75 Site export

## Already gone (verified in the code)
- Writer duplicates M11: site_export.py:412 `write_north_up(...)` (imported :65); :465 `apply_band_windows(layer, ...)`.
- `NSGEO_SITE_CELL_M` is the export cell: site_export.py:429 `str(plan.cell_m)`.
- Docstring lists the four interpolation keys as absent on the coverage companion: site_export.py:12-14.

## Tests (test_plugin_site_export.py)
- test_the_file_records_the_transform_the_grids_were_prepared_with: failed first with `TypeError: site_export_job() missing 1 required keyword-only argument: 'transform'` (KW lost its transform key, so all 31 tests in the file failed this way before the fix; run: `qgis_tests.sh .../test_plugin_site_export.py -q`).
- test_a_grid_with_no_velocity_exports_null_depths: failed with the same TypeError at that point, so no independent fail-first; it passes after the fix and the code already handled a None velocity (a missing test, not a missing fix).
- test_grids_prepared_with_different_transforms_refuse_to_plan (extra, covers the new RuntimeError): written after the fix, no fail-first run.
- Fixed in place: no-resident-cube test asserts `not has_cube`; CRS assertion compares `QgsCoordinateReferenceSystem.fromWkt(...).authid()` with `site.effective_crs()` (Site.crs is None here); the no-site-axis test uses the fixture.
- `make_site` moved unchanged to conftest.py (lazy SiteEngine import); both copies dropped. The export file's old fixture also prepared the site, so a local helper `prepared_site(make_site, site3, source=None)` does that now.

## mypy
Command copied from ci.yml with site_export.py appended. Reported: (1) qgis.core import-not-found (the lint job has no QGIS; the other listed files are qgis-free), (2) union-attr at `engine_for(grid_id).z`, (3) arg-type ZAxis|None into window_depths_m. No slice_at arg-type appeared. Fixes: (1) `[[tool.mypy.overrides]] module=["qgis","qgis.*"] ignore_missing_imports=true` in packages/nsgeo-core/pyproject.toml (OUTSIDE the brief's file list); (2)(3) plan_site_export collects each ready engine's choice.transform and z once (RuntimeError if engine/choice is missing) and tests `z is None` explicitly. No `# type: ignore`. Result: Success, no issues in 65 files.

## Callers changed
plugin.py `_export_site`: dropped `transform=` and the unused `transform = dock.site_panel.transform()` local. Only other caller is the test file (KW).

## Counts
test_plugin_site_export.py + test_plugin_site_engine.py: 93 passed. `-m real_data`: 46 passed. Pure: 385 passed, 4 skipped. ruff check and format --check clean. Core: 1668 passed, 5 skipped, 19 xfailed.

## Deviations
pyproject.toml mypy override (above). The hand-built SiteEngine in test_a_mixed_site... left as is (not in brief).

Push pending (GitHub auth down).
