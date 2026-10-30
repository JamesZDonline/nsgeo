### Task 6: The map overlay, and the documentation

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_overlay.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (own the overlay and feed it), `docs/guide/getting-started.md` ("Step 2: Place a grid"), `README.md` (line 37), `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt` (`about` only; the 0.1.0 changelog stays)
- Test: `tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: Task 2's `corners_changed`, `corner_point` and `corner_source`; Task 3's `chosen_polygon`; Task 4's `canvas` parameter and `_real_canvas` helper.
- Produces: `class GridOverlay`.
  - **Construction:** `__init__(self, canvas: QgsMapCanvas)`.
  - **Setters**, each taking points in the canvas CRS:
    - `set_corners(self, corners: Sequence[tuple[QgsPointXY, str] | None]) -> None`
    - `set_polygon(self, ring: Sequence[QgsPointXY] | None) -> None`
    - `set_grid(self, corners: Sequence[QgsPointXY] | None) -> None`, with the four corners in `CORNER_ROLES` order. The arrow runs from `corners[0]` toward `corners[3]`.
  - **Read-back for tests:** the attributes `corners`, `polygon` and `grid` hold the last values set.
  - **Teardown:** `dispose(self) -> None` is idempotent.
- Produces: `GridDialog.overlay: GridOverlay | None`, which is `None` without a canvas.
- **Tag text:** `f"{role} · {source}"` when the source is a polygon vertex (`v<i> <compass>`), else `role`.

- [ ] **Step 1: Write the failing tests**, each with a dialog given a `_real_canvas`.
  - `test_overlay_tags_each_filled_corner`: rows 0 and 2 typed → `overlay.corners` has tags `"origin"` and `"+X+Y"` at the transformed points, and `None` for the empty rows.
  - `test_overlay_tags_polygon_vertices_with_their_labels`: after Fill → `"origin · v0 SW"` and so on.
  - `test_the_chosen_polygon_is_outlined` (#28): `overlay.polygon` equals the feature's ring in the canvas CRS. Choosing no feature clears it.
  - `test_overlay_outline_follows_the_form`: with the form set to `SITE`, `overlay.grid` equals `SITE_CORNERS` in the canvas CRS within 1e-6. Changing `size_x` redraws it with no Fit.
  - `test_overlay_hides_the_grid_until_it_can_be_drawn`: a form origin of (0, 0), a size of 0 or an unusable grid CRS → `overlay.grid is None`.
  - `test_overlay_redraws_on_a_canvas_crs_change`.
  - `test_overlay_stays_while_the_dialog_is_hidden_mid_pick`.
  - `test_overlay_leaves_nothing_behind`, parametrized over OK, Cancel, a close mid-pick and `unload`: the scene item count returns to its baseline from before the dialog opened.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the overlay** following spec §4.8.
  - **Drawing** is your choice: rubber bands plus a custom `QgsMapCanvasItem` for the tags, or one custom item for everything. Use magenta role tags with white text and a blue dashed grid outline, as in the mock-up.
  - **Feeding it:** the dialog creates the overlay when given a canvas. It calls the setters from one `_refresh_overlay` slot, connected to:
    - `corners_changed`
    - the origin, azimuth and size spin boxes
    - `crs_widget`, `corners_crs`, the feature picker
    - `canvas.destinationCrsChanged`
  - **Disposal:** `finished` disposes of the overlay. `open_grid_dialog`'s `clear_if_current` also disposes of it, through a local reference captured beside `dialog`, for a dialog destroyed without `finished`.
- [ ] **Step 4: Rewrite the documentation** following spec §7.
  - Rewrite "Step 2: Place a grid" around:
    - typing, Pick and Pick all (right-click skips, Esc stops);
    - Fill from a polygon, Rotate and Fit;
    - "off by", the size rule and **Use these**;
    - the automatic CRS and its hint.
  - Change the README sentence and `metadata.txt`'s `about` to "placed from corners typed, picked on the map or read from a polygon".
  - Check with `git grep -i digitis -- docs/guide README.md packages/nsgeo-qgis/nsgeo_qgis`. It should return only `metadata.txt`'s 0.1.0 changelog line.
- [ ] **Step 5: Run both tiers, ruff and mypy.** All green.
- [ ] **Step 6: Commit and push.** `feat(plugin): the map shows the corners' roles, the chosen polygon and the grid while the dialog is open; guide rewritten (#27, #28)`

---

## After the tasks (coordinator)

1. Run the final whole-branch review on opus, then one fix wave if needed.
2. **Human gate: build and walkthrough.** Deploy the branch to a new QGIS profile (ask the user which). Publish a walkthrough page on an Artifact with `db`. It uses the user's own GPS corner points and their colleague's grid polygons, first in a 4326 project and then in a UTM project, and covers:
   - typing, Pick, Pick all with a skip, and Fill
   - Rotate
   - the overlay's tags, outline and arrow
   - snapping onto GPS points from a zoomed-out view
   - Fit, rounding the size, and **Use these**
   - the automatic CRS and its hint, and a hand-picked CRS that stays put
   - the finished grid lining up with the GPS points and the overlay maps

   Mark checks that would lose data. The user's data is never committed.
3. Merge only on the user's go. The PR closes #27, #28, #62 and #63.
