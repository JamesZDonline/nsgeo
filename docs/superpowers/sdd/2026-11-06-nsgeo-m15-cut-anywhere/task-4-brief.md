### Task 4: Drawing a cut, and the map working on cuts

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/maptools/cut_tool.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (the Cut toggle, `_on_cut_drawn`, `currentLayerChanged`)
  - `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
  - `packages/nsgeo-qgis/tests/qgis/conftest.py` (`FakeIface`)
- Test:
  - Create: `tests/qgis/test_cut_tool.py`, `tests/qgis/test_plugin_cut_drawing.py`, `tests/qgis/test_plugin_map_link_cuts.py`

**Interfaces:**
- Consumes:
  - Task 2: `add_cut`, `cut_for_key`.
  - Task 3: `open_line` on cut keys, `CutSections.section` / `column_at`, `SectionColumns.world`, `Cut.locate`, `Grid.to_local`.
- Produces:
  - `class CutTool(QgsMapTool)`:
    - `drawn = pyqtSignal(list)` (a list of `QgsPointXY` in canvas CRS, at least one point)
    - `failed = pyqtSignal(str)`
    - `dispose() -> None`
  - `MapLink.set_cut_mode(on: bool) -> None`, `MapLink.cut_mode -> bool`, `MapLink.set_sections(sections: CutSections) -> None`.
  - `FakeIface.activeLayer()`, `FakeIface.setActiveLayer(layer)` (emits `currentLayerChanged`), `FakeIface.currentLayerChanged`.

- [ ] **Step 1: Write the failing tool tests** (`test_cut_tool.py`, with `send_map_mouse` and `send_map_key` on `real_canvas`)
  - `test_left_clicks_add_points_and_right_click_finishes`: three left clicks then a right-click emit `drawn` once with 3 points.
  - `test_enter_finishes_and_backspace_removes_the_last_point`.
  - `test_esc_cancels_and_leaves_nothing_behind` (spec test 6): after two clicks and Esc, no `drawn`, and the rubber band is empty. The key is consumed (`e.ignore()`, per `pick_tool.py`'s trap).
  - `test_the_tool_stays_on_for_the_next_cut`: after one `drawn`, three more clicks and Enter emit again.
  - `test_an_exception_in_an_event_becomes_failed`.
- [ ] **Step 2: Run them and see them fail. Implement `CutTool`. Run them and see them pass.**
  - Follow `PickPointTool`'s structure: guarded events, `QgsRubberBand` for the drawn path plus a moving segment, and an idempotent `dispose`.
- [ ] **Step 3: Write the failing drawing-flow tests** (`test_plugin_cut_drawing.py`, a plugin on `real_iface` with one grid and lines)
  - `test_the_cut_toggle_follows_the_site_and_makes_the_cuts_layer_current` (decision 11):
    - Cut is disabled with no site;
    - after a site opens, checking it sets the map tool and makes `iface.activeLayer()` the cuts layer;
    - unchecking unsets the tool.
  - `test_drawing_a_cut_adds_marks_unsaved_refills_and_opens_it` (§4.1):
    - draw 2 points inside grid A;
    - then `session.cut_keys()` has one key, `dirty` is True, the cuts layer has one feature, `current_key` is that key, and the tool is still active.
  - `test_a_first_click_outside_every_grid_is_refused`: the message bar shows `OUTSIDE_TEXT`, and no cut is added.
  - `test_one_point_or_two_on_the_same_spot_is_refused` (spec test 4): `TOO_FEW_TEXT`.
  - `test_a_first_click_inside_two_grids_takes_the_first_in_survey_order` (Review Focus 3).
  - `test_a_cut_drawn_on_a_geographic_canvas_lands_in_grid_metres` (Review Focus 1): canvas in EPSG:4326, grid in EPSG:32616. The stored vertices equal `grid.to_local(transformed points)` within 1e-6 m.
  - `test_another_map_tool_unchecks_cut`.
- [ ] **Step 4: Run them and see them fail. Implement the plugin side** (`act_cut`, `_toggle_cut_tool`, `_on_cut_drawn`; plan call 10's `setActiveLayer`). **Run them and see them pass.**
- [ ] **Step 5: Write the failing map-link tests** (`test_plugin_map_link_cuts.py`)
  - **Fixture.** The `linked` fixture is extended with a `CutSections` over a prepared engine. The grid has lines 0.5 m apart, rotated 10.497°. A cut runs obliquely, within hover reach of a line along most of its length.
  - **Tests:**
    - `test_cut_mode_hover_previews_the_cut_not_the_nearby_line` (spec test 10): after settling 0.1 m from a line and on the cut, `preview_key` is the cut key and the column equals `column_at(key, Cut.locate(...)[0])`.
    - `test_line_mode_ignores_cuts`: the same spot previews the line, as today.
    - `test_changing_mode_mid_hover_leaves_no_stale_preview`: `set_cut_mode(False)` while previewing a cut clears the preview.
    - `test_the_working_cut_stays_open_when_another_layer_becomes_current` (§4.3): with a cut working, `set_cut_mode(False)` keeps `current_key`. Hovering a line then previews it, and selecting a line opens it.
    - `test_selecting_a_cut_opens_it`: select its feature in the cuts layer, and `current_key` is the cut key.
    - `test_tracking_works_both_ways_along_a_cut`:
      - map to profile: moving the pointer along the working cut calls `set_trace` with increasing columns;
      - profile to map: `session.set_trace(key, 20)` puts the marker at `columns.world[20]` in canvas CRS, within 1e-6 map units.
    - `test_the_marker_and_band_follow_a_selection_on_a_cut`.
    - `test_hover_on_a_geographic_canvas_finds_the_right_column` (Review Focus 1).
    - `test_hovering_a_cut_while_a_line_works_never_writes_to_the_cut` (spec test 9): with a line working and a cut previewed, a pick request for the cut key raises `ValueError` in the session, and no row is added.
    - `test_the_plugin_follows_the_current_layer` (plan call 10, with the extended `FakeIface`):
      - `setActiveLayer(cuts)` turns cut mode on, and any other layer turns it off;
      - after a CRS rebuild replaces the cuts layer object, setting the new one still turns it on.
- [ ] **Step 6: Run them and see them fail.**
- [ ] **Step 7: Implement the map-link changes** (plan calls 9 and 10):
  - a cut-geometry cache from the cuts layer (`cut_key`), invalidated with the lines cache and on `cuts_changed`;
  - `_hit_test` branches on `cut_mode`;
  - `_track_displayed_line`, `_set_marker` and `_set_band` handle cut keys;
  - `selectionChanged` on the cuts layer opens the cut;
  - in `plugin.py`, `iface.currentLayerChanged` → `map_link.set_cut_mode(...)`, also synced on `site_opened`.
- [ ] **Step 8: Run them and see them pass. Then run the touched QGIS files, core + pure, lint and types.**
- [ ] **Step 9: Commit and push:**
  `git commit -m "feat(cuts): the Cut tool, and the map working on cuts while the cuts layer is current (cut spec §4.1, §4.3, decision 11)"`

---

