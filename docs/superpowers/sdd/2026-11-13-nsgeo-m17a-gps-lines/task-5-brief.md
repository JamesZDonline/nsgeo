### Task 5: GPS lines on the map (plugin)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers_gps.py`
- `test_plugin_layers.py` must stay green, unchanged.

**Interfaces:**
- Consumes: Task 2 (`TrackPlacement.bridges`, `end_runs`, `END_LIMIT_M`) and Task 3 (`session.site_crs`).
- Produces:

```python
# layers.py
TABLES["lines"]   # gains ("placed_by", "str") and ("without_rtk_m", "float"), after "file_name"
TABLES["rtk_gaps"] = (QgsWkbTypes.Type.LineString,
    [("line_key", "str"), ("kind", "str"), ("first_trace", "int"), ("last_trace", "int"), ("metres", "float")])
DERIVED = ("grids", "lines", "marks", "cuts", "rtk_gaps")
LEGEND_ORDER = ("picks", "marks", "cuts", "rtk_gaps", "lines", "grids")
NO_GRID_COLOUR = "#636363"
RTK_GAP_COLOUR = "#e377c2"     # in no grid colour and not the cut colour
def _line_crs(self, line: Line) -> str | None: ...          # a grid line's grid crs; a GPS line's placement crs
def _line_points(self, line: Line, frames: dict[str, Grid]) -> list[QgsPointXY] | None: ...   # was (line, grid, frames); every caller updated
def refill_rtk_gaps(self) -> None: ...
```

- **`refresh()`** clears the derived tables only when the site has neither grids nor lines.
- **`refill_lines`, `refill_marks`, `follow_lines` and the pick placement** treat a line with no grid like any other, through `_line_points`.
- **`_style_lines`** adds the `""` category, labelled `No grid`, in `NO_GRID_COLOUR`, with the same width and dashes as the grid categories.
- **`rtk_gaps` features:**
  - one `bridge` per `Bridge`, along the line's trace positions `first_trace..last_trace`;
  - a `start` feature for a start run over `END_LIMIT_M`, from trace 0 to the first anchor; `end` likewise.
  - It is styled `RTK_GAP_COLOUR`, 0.8 mm, dotted (custom dash 0.5/1.0 mm), and is not selectable.

- [ ] **Step 1: Write the failing tests** (`test_plugin_layers_gps.py`), on synthetic GPS lines built with `synthetic_gps_dzt`, `read_dzg`, `track_from_log` and `session.add_lines`:
  - `test_a_gps_line_with_no_grid_is_drawn_along_its_track`: the vertices equal `trace_coords` in the site CRS. `placed_by == "gps"`, `grid_id == ""`, the tape-only fields are NULL, and `length_m` equals the walked length.
  - `test_a_grid_free_site_draws_its_gps_lines`.
  - `test_a_bridge_is_drawn_in_rtk_gaps`: one `bridge` feature with that bridge's traces and metres.
  - `test_only_long_end_runs_are_drawn`: a 3 m start run gives a `start` feature, and a 0.5 m one none.
  - `test_marks_on_a_gps_line_sit_on_its_track`: a DZX with a mark at scan 50 gives the point `trace_coords[50]`.
  - `test_a_pick_on_a_gps_line_sits_on_its_track`.
  - `test_tape_lines_are_drawn_as_before_with_placed_by_tape`.
  - `test_an_older_package_gains_the_new_fields_and_table`: a package written with the old `lines` fields is rebuilt, and `rtk_gaps` is created.
  - `test_the_second_surveys_dropout_is_drawn` (real data, skips without `GRID2_LINES`): `FILE__039` gives one `bridge`, traces 149 to 246.
- [ ] **Step 2: Run them and see each fail.**
- [ ] **Step 3: Implement** to P12.
- [ ] **Step 4: Run `test_plugin_layers_gps.py`, `test_plugin_layers.py`, `test_plugin_map_link.py` and `test_plugin_pick_tool.py`, then lint and types.**
- [ ] **Step 5: Commit** (`feat(plugin): GPS lines, their gaps, marks and picks on the map (#134)`) and push.

---

