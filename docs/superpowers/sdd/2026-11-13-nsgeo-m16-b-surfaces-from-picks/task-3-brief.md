### Task 3: Building a surface: fill, files, fit and staleness

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py`:
  - Extract `fill(grid_id, choice, *, progress) -> FilledGrid` from `run`. It covers everything from the stale `.npy.part` sweep to the opened memmap. `run` then calls it, and behaves exactly as before.
  - Add a module function `place_picks(rows: Sequence[tuple[str, Pick]], lines, prov, frame, velocity) -> list[PlacedPick | None]`, with the math now in `_write_picks`. `_write_picks` uses it.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `slice_sources_changed = pyqtSignal(str)`, emitted by `_update_source` after a real change.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/surfaces.py`, `surface_plan.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surface_build.py`. Use Plan A's `synth_site` (move it to `tests/qgis/conftest.py` or a shared helper) plus a `SiteLayers`, so it runs in CI. Add real-data variants only where a reflection is needed.
- Test: extend `tests/pure/test_pure_surface_plan.py`

**Interfaces:**
- Consumes: Task 1 (`surface_volume`, `build_surface`, `surface_mesh`, `SurfaceSettings`), Task 2 (`Surfaces`, `PickRow`, `FeatureRecord`); Plan A (`ParaViewExport.defaults`, `VolumeChoice.to_record`, `session.remember_volume`, `paraview_folder`'s `_safe`).
- Produces:
  - **`FilledGrid`:** `lines`, `prov`, `frame`, `z`, `velocity`, `filled` (read-only memmap), `skipped_lines`.
  - **`PlacedPick(line_key, trace, x_m, y_m, depth_m)`**
  - **New `Surfaces` methods** (they get their `ParaViewExport` from `export_for`, and raise RuntimeError when it is None):
    - `folder(grid_id) -> Path`: `<site>/surfaces/<safe grid>`.
    - `inputs(feature_id) -> dict[str, str]`, keyed by `INPUTS = ("picks", "settings", "source", "resolution", "fill", "volume", "velocity")`. Each value is a 16-hex sha1 of sorted JSON:
      - `picks`: sorted `(line_key, trace, time_ns, zero_ns)` of the members;
      - `settings`: `SurfaceSettings.to_dict()`;
      - `source`: the preset's name and steps, the transform, each `source_keys` line with `repr(placement)`, and the grid's origin, azimuth, size and CRS;
      - `resolution`: cell and `dz_ns`;
      - `fill`: the finish's method, max distance, search radius and smoothing;
      - `volume`: `period_ns` and `trend_m`;
      - `velocity`: the resolved velocity's `to_dict()`.

      It reads the record and the session only, and prepares nothing.
    - `state(feature_id) -> SurfaceState(built: bool, stale: tuple[str, ...], report: dict | None)`: `stale` lists the inputs that differ from the last build's.
    - `build(feature_ids, *, progress) -> list[BuildReport]`. Every id must be on one grid. Steps:
      1. `choice = export.defaults(grid)` and `session.remember_volume(grid, **choice.to_record())`;
      2. `export.fill`;
      3. one `surface_volume`;
      4. per feature: the members, then `place_picks`, then `build_surface`, then the files.
    - `built(feature_id) -> BuiltSurface | None`: the npz arrays plus the json.
    - `sweep(grid_id)`: deletes the files in the grid's folder that no record's json names, and skips any it cannot delete.
  - **`BuildReport`:** `feature_id`, `name`, `report: dict` (as written to the json), `files`.
  - **The json** (`<id>.json`):
    - `feature_id`, `name`, `grid`, `kind`, `built_utc`, `nsgeo_version`;
    - `inputs` (the dict above);
    - `resolution: {cell, dz_ns}`, `settings`, `offset_m`;
    - `fit: {picks, within_2cm, within_5cm, further, on_holes}`;
    - `outliers: [{line_key, label, distance_m, picked_m, surface_m}]`, where `label` is `placement.label or path.stem`;
    - `skipped: [{line_key, why}]`, for picks that could not be placed;
    - `cells`, `region_cells`, and `files: {npz, 2dm, dat}`.
  - **The files:**
    - **The npz** holds `depth_m`, `strength`, `cell`, `origin`, `azimuth` and `crs`.
    - **The 2DM:**
      - starts with `MESH2D`;
      - has a line `ND i x y z` per vertex, in world coordinates of the grid's CRS (`frame.axes()` and the origin), with z = −depth;
      - has a line `E3T i a b c 1` per triangle.
    - **The DAT:**
      - `DATASET`, `OBJTYPE "mesh2d"`, `BEGSCL`, `ND n`, `NC m`, `NAME "depth (m)"`, `TS 0 0.0`;
      - then one depth per vertex, then `ENDDS`.

    Write each file as `.part` and rename it. Write the json last, so a build is complete exactly when its json names its files.
  - **In `surface_plan.py`:**
    - `STALE_REASONS: dict[str, str]`, one plain phrase per input. For example, `"picks": "its picks changed"` and `"resolution": "the grid's 3-D cell or depth step changed"`.
    - `stale_text(stale) -> str`
    - `fit_rows(report) -> list[tuple[str, str]]`: Picks, Offset, Cover and Built, as in the mockup.
    - `outlier_line(outlier: dict) -> str`
    - `built_message(name, report) -> str`, and `empty_message(name) -> str` for a surface where no cell passed.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_build_writes_its_files_and_reports_its_fit`: 4 picks on the synthetic site's two lines.
    - The json names three files, and all of them exist.
    - The 2DM has as many `ND` lines as the npz has finite cells, and the DAT as many values.
    - `fit.picks == 4`.
  - `test_a_second_build_reuses_the_exports_fill`: patch `nsgeo_qgis.paraview_export.fill_levels` to count calls. Build twice and get one fill. Then an export of the same grid and choice fills nothing.
  - `test_a_cancelled_build_keeps_the_previous_one`: build, then cancel a rebuild partway (`progress` returns False after the fill). The json and its files are unchanged, and no `.part` file is left.
  - `test_picks_on_another_clock_land_on_the_cube_clock`: two picks at the same radar time, written with different `zero_ns`, give the same `PlacedPick.depth_m`. Test it with a preset with `time_zero` and one without.
  - `test_each_input_marks_the_surface_stale_with_its_reason`: parametrized over `INPUTS`. Change exactly that input after a build, and `state().stale` is exactly that one name. The changes are:
    - add a pick;
    - `set_settings`;
    - change a preset step;
    - `remember_volume(cell=…)`;
    - `remember_slice_resolution(method=…)`;
    - `remember_volume(period_ns=…)`;
    - a grid velocity.
  - `test_the_blur_and_the_slices_panel_never_make_a_surface_stale`: after a build, change the volume's `blur_m`, the panel's slice cell and dz (`remember_slice_resolution(cell=…, dz_ns=…)`), the dock's transform combo and its grid. `state().stale == ()`.
  - `test_a_member_deleted_by_hand_marks_the_surface_stale`: delete a member through the picks layer's edit buffer and commit. `stale == ("picks",)`, and building again works.
  - `test_building_remembers_the_grids_3d_choice`
  - `test_a_build_is_refused_while_slices_prepare`: the export's busy message, and nothing is written.
  - `test_sweep_deletes_only_unreferenced_files`
  - In the pure tier: `test_stale_text_names_every_reason` and `test_fit_rows_match_the_mockup`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Keep `ParaViewExport.run`'s behaviour identical: `test_plugin_paraview_export.py` must pass unchanged.
- [ ] **Step 4: Run the new files, `test_plugin_paraview_export.py`, the membership tests, the pure tier and lint.** All pass.
- [ ] **Step 5: Commit and push.** `feat: build surfaces from picks, with files, fit and staleness (M16 B)`.

---

