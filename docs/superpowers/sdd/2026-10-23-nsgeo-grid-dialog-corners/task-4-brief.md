### Task 4: The grid's CRS chooses itself (#62)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`, and `plugin.py` (`open_grid_dialog` passes `canvas=self.iface.mapCanvas()`)
- Test: `tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: Task 1's `utm_epsg`; Task 2's `fit_corners`; Task 3's `fill_from_polygon`, in one test.
- Produces: `GridDialog.__init__(self, session, grid=None, suggested_velocity=None, parent=None, canvas: QgsMapCanvas | None = None)` and `GridDialog.crs_is_auto() -> bool`. Task 6 also uses `canvas`.

- [ ] **Step 1: Write the failing tests.** Give the dialog a `_real_canvas` (see Shared test geometry), centred on `SITE.origin` in whatever CRS the test names. A test calling `crs_widget.setCrs` stands for the user picking by hand.
  - `test_a_usable_project_crs_is_kept`: project `UTM16` → the grid CRS is `EPSG:32616`, `crs_is_auto()` is true and the hint is empty.
  - `test_a_4326_project_gets_the_canvas_centres_utm_zone`: project and canvas in `WGS84` → `EPSG:32616`. The hint contains `"picked for you"` and `"EPSG:4326"` and `"degrees"`.
  - `test_the_sites_crs_comes_first`: the site already holds a grid in `EPSG:32617`, and the project is `UTM16`. Both are usable at the site; 32617 is about 0.3% off there. The result is `EPSG:32617`, with the hint `"picked for you: the CRS the site's other grids use"`.
  - `test_fit_moves_an_automatic_crs_to_the_corners_zone`: project `UTM16`, corners typed in `WGS84` around lon −70.0, lat 36.0 (zone 16 is about 2.9% off there) → after Fit the CRS is `EPSG:32619` and the fit is in it.
  - `test_a_hand_picked_crs_is_never_replaced`: hand-pick `EPSG:32619` (about 3% off at the site, so automatic mode would replace it), then Fit `SITE_CORNERS` → still `EPSG:32619`, `crs_is_auto()` is false, and OK is disabled by the existing refusal.
  - `test_a_4326_polygon_in_a_4326_project_fits_in_the_right_utm_zone`: project, canvas and `corners_crs` all `WGS84`, and no hand pick. Fill from the 4326 `SITE` polygon (Task 3), then Fit → `EPSG:32616`, with the origin within 1e-3 m of `SITE.origin` and the azimuth within 1e-6 of 10.0.
  - `test_an_existing_grids_crs_is_never_changed`: edit a grid saved in `EPSG:32617` → `crs_is_auto()` is false, and Fit keeps `EPSG:32617`.
  - `test_hand_picking_a_crs_converts_origin_and_azimuth`: set the form to `SITE`, then hand-pick `EPSG:32617`.
    - The origin, transformed back to `UTM16`, is within 1e-3 m of `SITE.origin`.
    - The point 100 m along +Y, rebuilt from the new azimuth and transformed back, is within 1e-2 m of the original.
  - `test_no_canvas_keeps_the_project_crs_and_says_what_will_happen`: project `WGS84`, `canvas=None` → the CRS stays `EPSG:4326` and OK is disabled. The hint contains both `"metres"` and `"a UTM zone will be picked when you fit corners"`.

  `test_crs_guard_blocks_every_route_to_a_bad_crs` must still pass unchanged after Task 2's edit.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** spec §4.4.
  - **CRS state:**
    - `_crs_auto` starts true for a new grid and false for an existing one.
    - Every write the dialog makes to `crs_widget` happens under a `_setting_crs` guard.
    - A `crsChanged` outside that guard is a hand pick. It clears `_crs_auto`, and converts the origin and azimuth from the previous CRS (kept in `_grid_crs`) unless the origin is (0, 0). If that conversion fails, put the previous CRS back and say so in `crs_hint`.
  - **Usability checks:** generalise `_crs_scale_error` to take the point to measure at. Add one helper that runs `_validate`'s three checks at a given location.
  - **The hint:** `crs_hint` shows `_validate`'s problem, if any, followed by the automatic choice's note, if any. The no-canvas case shows both. UTM reasons read `f"picked for you: the project CRS ({authid}) is in {QgsUnitTypes.toString(units)}"`, `f"... is off by {pct:.1f}% here"`, `"... has no authority code"`, or `"picked for you: the project has no CRS"`.
  - **Fit:** with `_crs_auto` set, Fit settles the CRS from the corners' centroid before transforming them. The Task 2 "metric CRS" refusal remains only for a CRS the user picked by hand.
- [ ] **Step 4: Run the file, both tiers, ruff and mypy.** All green.
- [ ] **Step 5: Commit and push.** `feat(plugin): the grid CRS picks itself — the site's, the project's, or a UTM zone; hand picks convert (#62)`

---

