# Task 2 report

Commit: feat(export): tiled when large, overviews, a temporary name, export metadata and a style file

## Implemented
- slice_export.py: `creation_options(w,h)` (tiled 256 only when both sides >= 1024, else strips; OPTIONS removed), `overview_factors`, `build_overviews` (tiled only, AVERAGE, thread-local GDAL config, factors while longer side >= 256), `partial_path/commit_partial/discard_partial`, `StretchSample` (cap `STRETCH_SAMPLE_CAP`=2,000,000 split across bands, strided), `projection_wkt` (osr, no QGIS object; optional `crs_wkt` from GUI thread), shared `write_north_up`, `GeoTiffSliceWriter.write_bands`; ExportPlan gained `lattice, cell, pixel, crs_wkt` (defaults). Import-time FutureWarning filter for GDAL UseExceptions. Old `write` kept, uses creation_options.
- site_export.py: `GeoTiffSiteWriter.write_bands`, `NSGEO_SITE_RESAMPLING=bilinear`, shared `_tag_dataset/_factors` (old write uses them too); SiteExportPlan gained `crs_wkt`.
- export_style.py: `write_style` (GUI thread).
- `progress_band(done)` is called with the count of bands written so far (1..n).

## Tests
RED: pytest on slice export tests -> ImportError cannot import name 'build_overviews' from nsgeo_qgis.slice_export.
GREEN: slice_export + site_export + export_style + slice_export_dialogs: 124 passed. Pure + core boundary/public_api: 271 passed, 1 skipped. ruff check, ruff format --check, CI mypy line: clean.
Also verified in a plain interpreter with -W error::FutureWarning that write_north_up emits no warning (pytest's own -W resets filters per test, so that flag cannot be used in pytest).

## Files
nsgeo_qgis/slice_export.py, site_export.py, export_style.py (new); tests: test_plugin_slice_export.py, test_plugin_site_export.py, test_plugin_export_style.py (new).

## Self-review / concerns
- Old creation-options test left as is (still true for small frames); new test pins both regimes.
- The coverage companion also gets `NSGEO_RESAMPLING`/`NSGEO_SITE_RESAMPLING=bilinear` (the pipeline composes counts bilinearly too).
- `write_style` raises OSError if the raster is unreadable or the qml cannot be written.
- Old `write` paths still use catch_warnings (GUI thread; Task 5 removes them).
- Stretch is on a strided subsample above the cap (R7); equal to limit_over_slices below it.

## Fix round 1
1. Counts tag: `NSGEO_RESAMPLING` / `NSGEO_SITE_RESAMPLING` = `largest_count` on a counts plan. SiteExportPlan gained `coverage: bool = False` (write_site_coverage sets it; Task 3/5 companions must pass `coverage=True`). Tests pin both keys.
2. `projection_wkt(crs)` now uses `QgsCoordinateReferenceSystem(authid).toWkt()`, ValueError when invalid; osr and both `crs_wkt` fields removed. Test registers a real `USER:` CRS and checks the file's projection; an unknown USER id raises.
3. `slice_layer.apply_renderer(layer, colormap_name, limit, unipolar)` extracted; `SliceLayer._apply_renderer` and `write_style` use it.
4. `test_the_creation_options_are_the_measured_ones` rewritten to pin both regimes (docstring states the tiling ruling); the duplicate regime test removed.
5. `write_bands` raises ValueError ("no export cell and pixel") on a plan missing lattice, cell or pixel. SiteExportPlan cannot miss any (non-optional fields), so no site change. Tested.
6. `build_overviews(path, should_stop=None)`: GDAL progress callback returns 0 when stopping; raises ExportCancelled after closing the file. Test removes the file afterwards.

Tests: slice_export + site_export + export_style + slice_layer: 121 passed; pure/core boundary+public_api: 271 passed, 1 skipped; ruff check, format --check and CI mypy clean.
