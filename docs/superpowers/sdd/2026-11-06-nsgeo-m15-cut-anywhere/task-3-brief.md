### Task 3: Seeing a cut — the section from the Slices panel, in the profile

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/cut_sections.py`
- Modify:
  - `session.py` (cut keys in `open_line`, `set_preview`, `set_trace`, `set_selection`, `resolved_velocity`)
  - `slices_engine.py` (`section_fills`)
  - `loader.py`
  - `ui/processing_dock.py`
  - `ui/profile_dock.py`
  - `ui/profile_view.py` (`set_message`)
  - `render/qimage.py` (`rgba_to_qimage`)
  - `ui/survey_dock.py` ("Open" on a cut)
  - `plugin.py` (build and wire `CutSections`; Velocity enabling)
- Test:
  - Create: `tests/qgis/test_plugin_cut_sections.py`, `tests/qgis/test_plugin_profile_cut.py`
  - Modify: `test_plugin_session_cuts.py`, `test_plugin_loader.py`, `test_plugin_slices_engine.py`, `test_plugin_processing_dock.py`, `test_plugin_survey_dock.py`

**Interfaces:**
- Consumes:
  - Task 1: `section_columns`, `finish_section`, `section_rgba8`.
  - Task 2: `cut_for_key`, `cut_velocity`, `cuts_changed`.
- Produces:
  - `SliceEngine.section_fills(finish: SliceFinish) -> tuple[SliceFill, FillWeights | None]`. Requires a cube. It is the engine's held fill and preview when the key matches, and otherwise builds through `_fill_for(cube.coverage(), frame, settings)`.
  - In `cut_sections.py`:
    - `@dataclass(frozen=True) class CutSource`:
      - `grid_id: str`
      - `scope: str` (`"grid"` or `"site"`)
      - `engine: SliceEngine`
      - `finish: SliceFinish`, `settings: FinishSettings`
      - `palette: str`, `unipolar: bool`
    - `@dataclass(frozen=True) class CutSection`:
      - `key: str`
      - `values: np.ndarray` (nz, n)
      - `z: ZAxis`
      - `columns: SectionColumns`
      - `method: str` (the method drawn)
      - `standing_in: bool`
      - `solved: tuple[int, int]`
      - `source: CutSource`
      - `provenance_json: str`
    - `class CutSections(QObject)`:
      - `section_changed = pyqtSignal(str)`
      - `__init__(self, session: SiteSession, slices_dock: SlicesDock, parent: QObject | None = None)`
      - `source_for(grid_id: str) -> CutSource | None`
      - `section(key: str, *, build_cube: bool) -> CutSection | str` (a `str` is the message to show)
      - `column_at(key: str, distance_m: float) -> int | None`
      - `dispose() -> None`
  - `ProfileDock.set_cut_sections(sections: CutSections) -> None`.
  - `ProfileView.set_message(text: str | None) -> None`.
  - `rgba_to_qimage(rgba: np.ndarray) -> QImage`.
  - `provenance_json` holds, as JSON (spec call 2):
    ```json
    {"kind": "cut", "cut_id": "...", "cut_name": "...", "grid_id": "...",
     "scope": "This grid" | "Whole site (not normalised)",
     "cube": "<Provenance.to_dict()>",
     "resolution": {"cell": 0.05, "dz_ns": 0.2165},
     "finish": {"method": "kriging", "max_distance_m": 0.25, "smooth_x_m": 0.0, "smooth_y_m": 0.1},
     "time_base": "time_zero" | "radar",
     "standing_in_for": "min_curvature"}
    ```
    `standing_in_for` appears only when kriging stands in. `time_base` is `nsgeo.processing.timezero.time_base_of(engine.provenance().steps)` (spec call 18, #97's hand-off).

- [ ] **Step 1: Write the failing session and tolerance tests**
  - In `test_plugin_session_cuts.py`:
    - `test_open_preview_trace_and_selection_accept_cut_keys`:
      - `open_line(cut_key)` emits `line_opened(cut_key)`;
      - `set_preview(cut_key, 7)` emits `preview_changed(cut_key, 7)`;
      - `set_trace(cut_key, 10_000)` keeps 10_000 (no upper clamp, plan call 4);
      - `set_trace(cut_key, -5)` gives −1.
    - `test_resolved_velocity_of_a_cut_is_its_grids` (call 16).
    - `test_line_zero_of_a_cut_is_none_and_logs_nothing` (plan call 13): use `message_log`.
    - `test_removing_the_working_or_previewed_cut_clears_it`: `remove_cut` on the open cut leaves `current_key is None` and emits `line_opened("")`. On a previewed cut it emits `preview_changed("", -1)`.
  - In `test_plugin_loader.py`: `test_opening_or_previewing_a_cut_starts_no_load`.
  - In `test_plugin_layers.py`: `test_opening_a_cut_runs_no_time_zero_follow` (plan call 13). A cut key with a pick row, opened as the working item, never calls `follow_zero` (spy) and logs nothing.
  - In `test_plugin_processing_dock.py`: `test_a_cut_shows_that_processing_does_not_apply`: the list is empty and disabled, and the label is `PROCESSING_ON_CUT_TEXT`; reopening a line restores it.
- [ ] **Step 2: Run them and see them fail. Implement them. Run them and see them pass.**
- [ ] **Step 3: Write the failing engine test** (`test_plugin_slices_engine.py`, with the `sourced` fixture and `_prepare`): `test_section_fills_reuse_the_held_weights`.
  - After the dock-equivalent `finish(...)` call for the same `SliceFinish`, `section_fills` returns the identical fill object.
  - `plan_fill`, monkeypatched to count, is not called again.
  - Under `min_curvature` the second element is the kriging `FillWeights`.
- [ ] **Step 4: Run it and see it fail. Implement `section_fills`. Run it and see it pass.**
- [ ] **Step 5: Write the failing `CutSections` tests** (`test_plugin_cut_sections.py`)
  - **Fixtures.** Use a `docked_two_grids`-style fixture (a `SlicesDock` with grids A and B prepared at cell 0.25), plus the `site3` fixture for Whole site. Draw cuts with `session.add_cut`.
  - **Tests:**
    - `test_this_grid_scope_reads_the_shown_grids_engine` (call 10): a cut on the shown grid gives a `CutSection` with `source.scope == "grid"` and `source.engine is dock.engine`.
    - `test_this_grid_scope_gives_the_message_for_another_grid` (spec test 7): a cut on B while A is shown returns `NO_SOURCE_TEXT.format(name="Cut 1", grid="B")`, even though a site engine for B is still prepared.
    - `test_whole_site_reads_the_grids_site_engine_without_the_gain`: in site scope, `section.values[k]` equals `engine.finish(cube.level(k), cube.coverage(), site_finish)` at the cut's cells for three levels. This is not `SiteEngine._shown`'s output. Patch `normalise` to return `(2.0, 5.0)` and assert that it does not change the section.
    - `test_a_preview_never_builds_a_cube`: on a streaming engine (`has_cube` False), `section(key, build_cube=False)` returns `NO_CUBE_TEXT…` and `has_cube` stays False. `build_cube=True` builds it and returns a section.
    - `test_settings_or_source_changes_redraw_an_open_cut` (spec §4.4): after a first `section(...)`, changing the method, the max distance, smoothing, the cell, or the palette, then letting `slice_changed` fire, emits `section_changed(key)` once. The next `section` reflects the change.
    - `test_an_open_cut_shows_the_message_when_its_engine_goes_away` (Review Focus 4): switching the shown grid, switching scope, and closing the site each give the message or an empty result. Nothing reads the old engine: `engine.cube` is patched to raise after `dispose`.
    - `test_a_cut_past_a_shrunk_grid_edge_shows_blank_columns` (Review Focus 2): a cut from x = 1 to x = 5 on a 6 m grid. After `replace_grid` with `size_x = 3`, the frame-outside columns are NaN, the rest are finite, and `section_changed` fired.
    - `test_minimum_curvature_stands_in_with_kriging` (call 12, before Task 6): with method `min_curvature`, the section has `method == "kriging"`, `standing_in is True`, and values equal to kriging's `finish_section`. `provenance_json` has `"standing_in_for": "min_curvature"`.
    - `test_provenance_names_the_cut_cube_and_finish` (call 2): parse the JSON and check every key in the Interfaces block. `cube.line_keys` equals the engine's prepared keys.
    - `test_column_at_is_the_nearest_column`: `column_at(key, 1.04)` at cell 0.25 (step 0.125) is 8, and it is `None` when there is no source.
- [ ] **Step 6: Run them and see them fail.**
- [ ] **Step 7: Implement `CutSections`.**
  - **The source.** It is resolved per call 10 from `dock.scope()`, `dock.engine` (prepared and `choice.grid_id` matches), `dock.site_engine.ready_grids` / `engine_for`, `dock.grid_finish.value()` / `dock.site_finish.value()`, `dock.palette_combo.currentText()` and `engine.output_unipolar`.
  - **The cache.** One entry per key, with a fingerprint of `(id(engine), engine.choice, engine.frame, engine.z, id(cube), settings, scope, palette, unipolar, the Cut, the grid)`.
  - **Redraws.** It listens to `slices_dock.slice_changed`, `session.cuts_changed`, `session.grids_changed` and `session.site_closed`. A cached key whose fingerprint changed is dropped and `section_changed(key)` is emitted.
  - **The wait cursor.** `build_cube=True` wraps `engine.cube()` in `QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)` / `restoreOverrideCursor` (in `try/finally`).
- [ ] **Step 8: Run them and see them pass.**
- [ ] **Step 9: Write the failing profile tests** (`test_plugin_profile_cut.py`; the dock wired to a `CutSections` over a prepared `SlicesDock`)
  - `test_opening_a_cut_draws_its_section_with_its_title_and_axes`:
    - the title is `nsgeo Profile · cut: Cut 1 · A · 5.0 m · Kriging`;
    - the view's `n_traces` equals the column count and `n_samples` equals `nz`;
    - the distance axis runs from 0 to 5.0, and the direction is +1 for a cut drawn east to west as well (call 5: never mirrored);
    - the ruler is `None`, and the `_held` windows are unchanged.
  - `test_whole_site_scope_says_not_normalised`: the title ends ` · site view, not normalised`.
  - `test_a_preview_has_the_preview_prefix_and_builds_nothing`.
  - `test_no_source_shows_the_message_in_the_view` (spec test 7): `view.set_message` gets `NO_SOURCE_TEXT…` and the image is `None`.
  - `test_a_squared_cube_draws_in_the_slices_palette_with_blank_columns_transparent` (call 17, spec test 8):
    - with `amp_square` and the panel's `amp_black_high`, the image's colour at a finite column matches `colormap("amp_black_high")` for that value;
    - a NaN column's pixels have alpha 0;
    - `colormap_combo` is disabled with `PALETTE_ON_CUT_TIP`;
    - opening a line re-enables it with its previous choice.
  - `test_the_percentile_slider_still_applies_to_a_cut`.
  - `test_the_slice_band_shows_on_a_cut` (call 13, and spec call 18): `window_changed(12.0, 14.0)` draws the band at exactly 12.0–14.0 ns on a cut whose preset sets a time zero, with a cube-zero lookup installed. It is not converted; a line in the same state still is, as #97 tests.
  - `test_velocity_is_greyed_on_a_cut_and_back_on_a_line` (spec test 8, plugin-level, with `_plugin_with_one_line`): `act_velocity` is disabled with `VELOCITY_ON_CUT_TIP` while a cut is current and enabled again for a line. Pick stays enabled.
  - `test_the_depth_axis_uses_the_cut_velocity`: `view._velocity` is `session.cut_velocity("A")`.
  - `test_a_cut_on_a_time_zero_preset_starts_its_axis_at_the_cubes_t0` (spec call 18): with a preset holding an enabled `time_zero`, the view's `t0_ns` equals `section.z.t0_ns`, and `provenance_json`'s `time_base` is `"time_zero"`.
  - `test_a_section_change_redraws_the_shown_cut`: an emitted `section_changed(key)` re-renders; one for another key does not.
  - In `test_plugin_survey_dock.py`: `test_open_on_a_cut_opens_it`.
- [ ] **Step 10: Run them and see them fail.**
- [ ] **Step 11: Implement the profile side.**
  - `_show_line` branches to `_show_cut(key, *, is_preview)`.
  - Every #97 conversion in the dock (`shown_zero_ns`, the cube-zero lookup in `set_slice_band`, pick and fit drawing through `retime_ns`) is skipped for a cut key (plan call 13).
  - Channels, difference, the cutoff handle, the gain strip and the velocity strip stay off or hidden while a cut shows, and come back for a line.
  - `_render` and `_display_changed` redraw a cut through `section_rgba8` → `rgba_to_qimage`.
  - In `plugin.py`, build `CutSections(self.session, self.slices_dock)` after the Slices panel and pass it to the profile with `set_cut_sections`. Dispose it in `unload`. Velocity's enable test is `has_line and not is_cut_key(current_key)`.
  - In `session.py` and `layers.py`, add plan call 13's two guards (`line_zero`, `_follow_key`).
- [ ] **Step 12: Run the touched QGIS files, then core + pure, lint and types.**
- [ ] **Step 13: Commit and push:**
  `git commit -m "feat(cuts): a cut's section from the Slices panel's cube, drawn in the profile (cut spec §4.3, §4.4)"`

---

