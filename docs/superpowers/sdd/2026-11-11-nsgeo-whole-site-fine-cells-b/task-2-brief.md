### Task 2: The file: tiles, overviews, temporary name, metadata, stretch, style file

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`:
  - `GeoTiffSliceWriter` gains a mode that writes north-up arrays from `ExportBand`;
  - `OPTIONS` moves to `creation_options(width, height)`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py` (`GeoTiffSiteWriter`).
- Create: `packages/nsgeo-qgis/nsgeo_qgis/export_style.py` with
  `write_style(path, *, limit, colormap_name, unipolar) -> Path`. It is GUI-thread only.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`,
  `test_plugin_site_export.py` and a new `test_plugin_export_style.py`.

**Interfaces (produces):**
- `creation_options(width: int, height: int) -> list[str]`.
  - **Ruling:** tile only when both sides are at least 1024 pixels, with `BLOCKXSIZE=BLOCKYSIZE=256`.
    Below that, keep today's strips. The measured 2.9× waste
    (`test_the_creation_options_are_the_measured_ones`) came from 512-pixel tiles on small frames.
    Rewrite that test to pin both regimes.
- `build_overviews(path)`: nodata-aware AVERAGE, factors 2, 4, 8 … while the overview's longer side
  is at least 256. Only for tiled files.
- `partial_path(target) -> Path` gives `<stem>.partial<suffix>`. `commit_partial(partial, target)`
  calls `os.replace`. `discard_partial(partial)`.
- Writers take a `progress_band` callback, set the new metadata keys (Global Constraints), and
  return `limit: float`: the stretch measured over every written band by `limit_over_slices` with
  the panel's clip rule (decision 16).
- `write_style`:
  - builds a renderer with `build_shader` and the limit;
  - calls `apply_smooth_resampling`;
  - saves `<stem>.qml` with `saveNamedStyle`;
  - and is checked to load as the default style when the file is added to a fresh project.

- [ ] **Step 1: Write the failing tests.**
  - Tiled above the threshold, stripped below (check `GetBlockSize`).
  - Overviews exist and do not bleed: an overview pixel over empty ground stays NaN.
  - A writer interrupted mid-band leaves no partial and no target, and an existing target is
    byte-identical.
  - The metadata keys and values round-trip, including `NSGEO_RESAMPLING=bilinear` and the cell and
    pixel.
  - The returned stretch equals `limit_over_slices` over the written bands.
  - The `.qml` loads: the added layer has a pseudocolour renderer at the limit and bilinear zoomed
    in.
  - No `warnings.catch_warnings` in the writer path. Grep-based or by mocking.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both export test files and the style test, plus lint.
- [ ] **Step 5: Commit:** `feat(export): tiled when large, overviews, a temporary name, export metadata and a style file`.

---

