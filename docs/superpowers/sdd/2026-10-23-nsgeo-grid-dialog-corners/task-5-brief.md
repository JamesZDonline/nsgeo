### Task 5: Pick on the map, with snapping (#63)

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/maptools/pick_tool.py`
- Delete: `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py`, and the three `test_digitise_tool_*` tests
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Test: `tests/qgis/test_pick_tool.py` (new) and `tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: Task 2's `pick_requested`, `pick_all_requested` and `set_corner`; Task 3's `pick_polygon_requested` and `set_polygon_feature`.
- Produces: `SNAP_TOLERANCE_PX = 12` and `class PickPointTool(QgsMapTool)`.
  - **Construction:** `__init__(self, canvas: QgsMapCanvas, mode: str = "point")`, where mode is `"point"` or `"polygon"`.
  - **Signals:**
    - `picked = pyqtSignal(QgsPointXY, str)`: the canvas-CRS point, with the label `f"{display name} · {layer name}"` or `"free click"`
    - `polygon_picked = pyqtSignal(object, int)`: the layer and its feature id
    - `skipped = pyqtSignal()`: right-click
    - `stopped = pyqtSignal()`: Esc
    - `cancelled = pyqtSignal()`: deactivated before `finish()`
  - **Methods and attributes:**
    - `snap(self, map_point: QgsPointXY) -> tuple[QgsPointXY, str]`
    - `snap_label: str`, which is the target under the cursor, or `""`
    - `finish(self) -> None`
    - `dispose(self) -> None`
- Produces, in `plugin.py`: `_start_pick(dialog: GridDialog, rows: list[int]) -> None`, `_start_pick_polygon(dialog: GridDialog) -> None`, and `_finish_with_pick_tool(tool: PickPointTool) -> None`. The last replaces `_finish_with_digitise_tool` and keeps its docstring's reasoning.

- [ ] **Step 1: Write the failing tool tests** in `test_pick_tool.py`. The canvas is `UTM16` over (0, 0)–(800, 600), so 1 px = 1 m. Layers:
  - a `Point?crs=EPSG:32616&field=name:string` memory layer with one feature `G4` at (400, 300), and display expression `"name"`;
  - a polygon layer with a vertex at (414, 300).

  Both are set with `canvas.setLayers`. The tests:
  - `test_a_click_near_a_point_snaps_to_it`: release at (408, 300) → `picked` gives (400, 300) and `"G4 · gps"`.
  - `test_a_click_beyond_the_radius_is_free`: (416, 300) → (416, 300) and `"free click"`.
  - `test_a_point_wins_over_a_nearer_vertex`: (410, 300). The point is 10 px away and the vertex 4 px → (400, 300).
  - `test_a_layer_not_on_the_canvas_is_never_snapped_to`: a second point layer, absent from `canvas.layers()`, at (405, 300) → still (400, 300).
  - `test_the_label_names_the_target_and_the_click_uses_it`: a move to (408, 300) → `snap_label == "G4 · gps"`; the release emits that same label.
  - `test_right_click_skips_and_esc_stops`: one emission each, and neither emits `picked`.
  - `test_switching_tools_cancels_once_unless_finished`: `cancelled` fires once, and does not fire after `finish()`.
  - `test_polygon_mode_emits_the_clicked_feature`.
  - `test_a_disposed_pick_tool_is_disposable_again` (port): the canvas scene's item count is back to its baseline after `dispose()`, twice.
- [ ] **Step 2: Write the failing plugin-flow tests** in `test_plugin_grid_dialog.py`. These are the ports Task 2 deleted. Each restates the old test's comment about why it exists.
  - `test_pick_flow_fills_the_row_and_restores_the_dialog`: click row 1's Pick.
    - The dialog is hidden, the active tool is a `PickPointTool`, and the message bar has one item containing `"+X"`.
    - A release fills row 1 with the snapped point. The dialog is visible again, there is no map tool, and the message bar is empty.
  - `test_pick_all_walks_the_corners_with_skip_and_stop`: click, right-click, click, then Esc → rows 0 and 2 filled, rows 1 and 3 empty, the dialog visible, the bar empty. The bar's text reads `"(1 of 4)"`, then `"(2 of 4)"`, and so on.
  - `test_pick_all_after_four_clicks_does_not_fit`: all rows filled, and the origin still (0, 0).
  - `test_single_pick_right_click_restores_the_dialog_untouched`.
  - `test_switching_map_tools_mid_pick_restores_the_dialog`.
  - `test_open_grid_dialog_releases_a_stranded_map_tool_on_close`.
  - `test_open_grid_dialog_releases_a_stranded_tool_on_accept_without_flashing_the_dialog`.
  - `test_open_grid_dialog_shows_the_existing_dialog_even_if_hidden_mid_pick`.
  - `test_unload_closes_a_dialog_hidden_mid_pick`.
  - `test_completed_picks_leave_no_canvas_items`, `test_an_aborted_pick_leaves_no_canvas_items` and `test_a_dialog_closed_mid_pick_leaves_no_canvas_items`. Each compares the scene item count before and after, and checks that the message bar is empty.
  - `test_a_pick_on_a_4326_canvas_lands_converted`: canvas `WGS84`, `corners_crs` `UTM16` → the row equals the transform of the clicked point within 1e-6 m.
  - `test_pick_polygon_on_map_selects_layer_and_feature`.
- [ ] **Step 3: Run them and see them fail.**
- [ ] **Step 4: Implement the tool** following spec §4.7.
  - **Snapping:** own a `QgsMapCanvasSnappingUtils(canvas)` with a `QgsSnappingConfig` that is enabled, `AllLayers`, `Vertex`, `SNAP_TOLERANCE_PX`, in `Pixels`. Snap with `snapToMap(point, filter)` (not relaxed, so it is synchronous), in two passes:
    1. a `QgsPointLocator.MatchFilter` subclass that accepts only `Qgis.GeometryType.Point` layers;
    2. only if the first pass found nothing, no filter.
  - **The marker and label:** a `QgsSnapIndicator` shows the match. The label is shown with `QToolTip` at the cursor, or with a canvas item that `dispose()` removes.
  - **Release:** use the match from the last move when the release is at the same pixel. Otherwise snap again.
  - **Polygon mode:** the topmost polygon feature under the click, searching only the polygon layers in `canvas.layers()` order.
- [ ] **Step 5: Implement the plugin flow.**
  - **Starting a pick:** `open_grid_dialog` connects the three dialog signals. `_start_pick` hides the dialog, sets the tool and pushes the message with `messageBar().createMessage` and `pushWidget`. The message texts are:
    - single: `f"Click the {role} corner. Right-click or Esc cancels."`
    - Pick all: `f"Pick corners: click the {role} corner ({k} of 4). Right-click skips it, Esc stops."`
    - polygon: `"Click the polygon to use. Right-click or Esc cancels."`
  - **During a pick:** each `picked` calls `dialog.set_corner(row, point, canvas.mapSettings().destinationCrs(), label)`.
  - **Ending a pick:** however a pick ends, `finally` unsets and finishes the tool, pops the message and shows the dialog. That covers the last corner, a single pick's right-click, Esc, `cancelled` and an exception.
  - **When the dialog finishes:** `finished`'s stranded-tool branch now checks for `PickPointTool` and also pops the message.
- [ ] **Step 6: Run both test files, both tiers, ruff and mypy.** All green.
- [ ] **Step 7: Commit and push.** `feat(plugin): pick corners and polygons on the map with snapping; Digitise on map removed (#63)`

---

