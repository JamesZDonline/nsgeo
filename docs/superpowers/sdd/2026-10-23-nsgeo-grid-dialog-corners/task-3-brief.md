### Task 3: Fill from a polygon (#27, #28's dialog half)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (the polygon row)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`. Delete `corners_from_polygon` and `PolygonCorners`.
- Test: `tests/qgis/test_plugin_grid_dialog.py`. In `tests/pure/test_pure_lookup.py`, delete the four `corners_from_polygon` tests.

**Interfaces:**
- Consumes: Task 1's `roles_from_ring` and `compass_label`; Task 2's `set_corner`, `corners_changed` and `rotate_corners`.
- Produces, on `GridDialog`:
  - **Widgets:** `layer_combo` and `feature_picker` (names kept), `pick_polygon_button` (`Pick on map`), `fill_button` (`Fill`).
  - **Signal:** `pick_polygon_requested = pyqtSignal()`.
  - **Methods:**
    - `fill_from_polygon() -> None`
    - `set_polygon_feature(layer: QgsVectorLayer, fid: int) -> None`, which sets both combos
    - `chosen_polygon() -> tuple[QgsVectorLayer, QgsGeometry] | None`, for Task 6's outline

- [ ] **Step 1: Write the failing tests.** Reuse `_pump` and `_select_sole_feature`, retargeted to the new combos. Build the 4326 layer by transforming `SITE_CORNERS` with `QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance())`.
  - `test_fill_from_a_4326_polygon_gives_the_known_utm_grid`:
    - set `corners_crs` to `WGS84` and `crs_widget` to `UTM16` by hand, then Fill and Fit;
    - the origin is within 1e-3 m of `SITE.origin`;
    - the azimuth is within 1e-6 of 10.0;
    - the sizes are within 1e-3 of 20.0;
    - the sources are `["v0 SW", "v1 SE", "v2 NE", "v3 NW"]`.
  - `test_fill_reads_a_multipolygon_layer`: the same ring in a `MultiPolygon?crs=EPSG:4326` layer gives the same corners.
  - `test_fill_labels_by_compass_in_a_geographic_crs`: the sources above come out the same when `corners_crs` is `WGS84` (the cos φ̄ rule).
  - `test_fill_without_a_feature_reports_a_message`: `fit_status == "select a polygon feature first"`.
  - `test_fill_reports_an_empty_geometry`: the message reads `"this feature has no rings to read corners from"`.
  - `test_fill_refuses_a_five_corner_polygon`: `"expected four corners, got 5"` in `fit_status`, and the rows unchanged.
  - `test_fill_does_not_fit` (C7): the origin stays (0, 0) after Fill.
  - `test_rotate_carries_polygon_labels`: after Fill and Rotate, the sources are `["v1 SE", "v2 NE", "v3 NW", "v0 SW"]`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the polygon row under a divider labelled `or fill all four from a polygon`. `fill_from_polygon` follows spec §4.6:
  - **Reading the ring:** use `asMultiPolygon()[0][0]` when the geometry is multipart, else `asPolygon()[0]`. A missing ring gives the existing message.
  - **Converting:** convert the ring layer CRS → `corners_crs` with the project's transform context. On `QgsCsException`, write a status message and stop.
  - **Roles and compass:** when `corners_crs` is geographic, compute them on `(lon · cos φ̄, lat)`, then map the indices back to the true points.
  - **Filling the rows:** fill through `set_corner` with source `f"v{i} {compass}"`.

  `pick_polygon_button` only emits `pick_polygon_requested`; Task 5 wires it.
- [ ] **Step 4: Run the file, both tiers, ruff and mypy.** All green.
- [ ] **Step 5: Commit and push.** `feat(plugin): fill the corners from a polygon in any CRS; labelled vertices; drop corners_from_polygon (#27)`

---

