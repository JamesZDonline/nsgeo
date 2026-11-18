### Task 4: Surfaces on the map and in the ParaView export

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/surface_layers.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/paraview_scene.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/paraview/open_scene.py.txt`
  - `packages/nsgeo-qgis/nsgeo_qgis/paraview/README.md.txt`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surface_layers.py`, and extend `test_plugin_paraview_export.py` and `tests/pure/test_paraview_scene.py` (including its pvpython test).

**Interfaces:**
- Consumes: Task 3 (`Surfaces.records`, `state`, `built`, `sweep`), Task 1 (`surface_mesh`), Plan A (`write_poly_data`, `scene_record`, `ExportSummary`, `summary_rows`).
- Produces:
  - **`SurfaceLayers(session, layers, surfaces, project=None)`:**
    - **`sync()`:**
      - Makes one `QgsMeshLayer` per built surface with at least one cell: the `.2dm` through provider `"mdal"`, plus `addDatasets(.dat)`, with `setCrs` set to the grid's CRS.
      - The active scalar group is "depth (m)". Its colour ramp is inverted Turbo (shallow is warm, as in the ParaView scene), with min and max shared by every built surface of that grid. If the default style has no Turbo, use Spectral and say so in the report.
      - The layer is named by the record's name, plus " (stale)" when `state().stale`. It carries the custom properties `nsgeo/feature_id` and `nsgeo/build`.
      - The layers sit in a "Surfaces" group inside the site group, directly below `picks`.
      - When a build changes, the new layer replaces the old one in the same place. Only after that does it call `surfaces.sweep(grid)`.
      - A layer the user removed is not re-added until that surface builds again.
      - Calls coalesce through a zero-delay single-shot `QTimer`.
    - **`dispose()`** removes its layers and the group.
    - **What calls `sync`:** the plugin connects `features_changed`, `picks_changed`, `slice_sources_changed`, `lines_changed`, `grids_changed` and `presets_changed`, and calls it after every build.
  - **`ParaViewExport(session, dock, surfaces=None)`:** with `surfaces`, `run` also writes `features.vtp`, and every build of the grid is in it, stale ones included.
    - Its points are `(x, y, -depth * stretch)`, meshed with `surface_mesh` at the build's own cell.
    - Its arrays are `true_depth_m` (float32), `feature` (int32, the index into the record's `features`) and `stale` (uint8, per point).
    - `picks.vtp` gains `feature` (int32): the index of the pick's surface, or −1.
    - Without `surfaces`, or with no builds, it still writes a valid empty `features.vtp`.
  - **`paraview_scene`:**
    - `scene_record` requires a new key `features`: a list of `{index, name, stale, picks, within_2cm, on_holes}`.
    - `ExportSummary` gains `n_surfaces` and `n_stale_surfaces`, and `summary_rows` gains a "Surfaces" row, for example "3 (1 stale)".
    - `feature_label(name, stale) -> str` is `"Surface: <name>"`, plus `" (stale)"` when stale.
  - **The scene:** one `XMLPolyDataReader` for `features.vtp`. Then, per feature, a `Threshold` on `POINTS`/`feature` between `i` and `i`, registered under `feature_label`. Each one is hidden at first and coloured by `true_depth_m` with the shared depth colour map. Names reach the script only through `export.json`, never pasted into its code.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_built_surface_is_a_mesh_layer_coloured_by_depth`
  - `test_surfaces_of_one_grid_share_one_depth_range`
  - `test_a_stale_surface_is_labelled_and_keeps_its_last_build`
  - `test_a_rebuild_writes_new_files_and_swaps_the_layer`:
    - the new layer has the new `nsgeo/build`, and sits at the same tree row;
    - the old files are gone after `sync`;
    - if the old files cannot be deleted (patch `Path.unlink` to raise `PermissionError`), `sync` succeeds and the next `sweep` removes them.
  - `test_an_empty_surface_has_no_layer_and_exports_cleanly`
  - `test_deleting_a_surface_removes_its_layer_and_files`
  - `test_closing_the_site_removes_the_surface_layers`
  - `test_a_layer_removed_by_hand_returns_only_after_a_rebuild`
  - `test_the_export_writes_every_built_surface_with_its_stale_flag`: read it back with `tests/vtk_reader.py`.
  - `test_picks_vtp_names_each_picks_surface`
  - `test_scene_opens_with_a_surface_whose_name_has_quotes` (pvpython; skipped without `NSGEO_PVPYTHON`): a surface named `Bowl "north" / é`. The script runs, and the source `Surface: Bowl "north" / é` exists and is hidden.
  - Extend the summary-row and `scene_record` tests for `features`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Add a "Surfaces" paragraph to the export's `README.md.txt`: what each item is, and that a stale surface shows its last build.
- [ ] **Step 4: Run the new files, the ParaView export and scene tests (pvpython on), and lint.** All pass.
- [ ] **Step 5: Commit and push.** `feat: surfaces on the map and in the ParaView scene (M16 B)`.

---

