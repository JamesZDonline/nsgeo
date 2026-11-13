### Task 3: The export: per-grid 3-D settings, the cube at its own resolution, writing the folder

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`
  - `_clean_slice_source` keeps a `"volume"` entry;
  - a new `_clean_volume` keeps exactly `cell`, `dz_ns`, `transform`, `stretch`, `period_ns`, `blur_m` and `trend_m`, each validated the way `_clean_resolution` validates.
- Modify: `packages/nsgeo-core/tests/test_project.py` (extend `test_slice_sources_and_site_view_round_trip` and `test_a_wrong_typed_inner_value_reads_as_unset`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`: add `volume_record(grid_id) -> dict` and `remember_volume(grid_id, **fields) -> None`. The latter marks the site dirty, like `remember_slice_resolution`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`: add `VolumeChoice` and `volume_choice()`.
- Create: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py`
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_volume_choice.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py`

**Interfaces:**
- Consumes:
  - from Task 1: `fill_levels`, `prepare_volume`, `VolumeSettings`, `VolumeStopped`;
  - from Task 2: `write_image_data`, `write_poly_data`, `image_data_bytes`, `write_scene_files`, `scene_record`;
  - existing: `SliceEngine`, `SourceChoice`, `SliceFinish`, `site_scope.default_preset` / `source_keys` / `transform_value`, `CubeFrame.for_grid`, `ZAxis.from_range`, `plan_line`, `build_cube`, `plan_fill`, `session.picks_for`, `session.resolved_velocity`, `retime_ns`, `time_base_of`.
- Produces:
  - `VolumeChoice(cell: float, dz_ns: float, transform: str, stretch: float = 3.0, settings: VolumeSettings = VolumeSettings())`: frozen, validated, with `to_record() -> dict`.
  - `volume_choice(record: Mapping | None, *, cell_default: float, dz_default: float, transform_default: str) -> VolumeChoice`. This is spec decision 8: the first use takes the defaults, and after that the record wins, field by field.
  - `export_size_bytes(nx: int, ny: int, nd: int) -> int` in `slices_plan.py`: `image_data_bytes((nx, ny, nd), 3)`. Picks and lines are small enough to ignore.
  - `class ParaViewExport` in `paraview_export.py`:
    - `__init__(self, session, dock)`
    - `defaults(grid_id) -> VolumeChoice`. It returns `volume_choice(session.volume_record(grid_id), ...)` with these defaults:
      - `cell_default`: `session.slice_resolution(grid_id)["cell"]` if remembered, else `default_cell(grid.default_spacing, max(0.01, smallest_safe_cell(...)))` (as `SlicesDock._seed_resolution_defaults` does);
      - `dz_default`: the remembered `dz_ns`, else the first line's `header.dt_ns`;
      - `transform_default`: `transform_value(dock.transform_combo.currentText())`.
    - `estimate(grid_id, choice) -> int`
    - `run(grid_id, choice, *, progress: Callable[[int, int], bool]) -> Path`: returns the export folder.
  - `class ParaViewExportCancelled(Exception)`
  - `paraview_folder(session, grid_id) -> Path`: `session.root / "paraview" / safe(grid_id)`, where `safe` maps anything outside `[A-Za-z0-9_-]` to `_`.

- [ ] **Step 1: Write the failing tests.**

```python
# test_pure_volume_choice.py
def test_first_use_takes_the_panel_defaults_then_the_record_wins():
    c = volume_choice(None, cell_default=0.05, dz_default=0.2165, transform_default="amp_square")
    assert (c.cell, c.dz_ns, c.transform, c.stretch) == (0.05, 0.2165, "amp_square", 3.0)
    r = volume_choice({"dz_ns": 0.1, "stretch": "bad"}, cell_default=0.2, dz_default=0.2165,
                      transform_default="amp_square")
    assert (r.cell, r.dz_ns, r.stretch) == (0.2, 0.1, 3.0)
def test_volume_choice_round_trips_through_its_record():
    c = VolumeChoice(0.05, 0.1, "amp_square", 4.0, VolumeSettings(period_ns=3.0))
    assert volume_choice(c.to_record(), cell_default=1, dz_default=1, transform_default="") == c
def test_export_size_matches_three_float32_arrays():
    assert export_size_bytes(400, 320, 450) == image_data_bytes((400, 320, 450), 3)

# test_project.py: a "volume" entry survives save/load; an unknown key in it is dropped;
# a wrong-typed value in it reads as unset.

# test_plugin_paraview_export.py
# Inline real-lines site, as test_plugin_slices_engine.py:229 builds it: four REAL_DZT lines
# on Grid "A", preset with time_zero + amp_square; plus a fake dock carrying engine/site_engine
# SliceEngines and transform_combo.
@needs_real_data
def test_export_writes_the_folder_ParaView_opens(tmp_path): ...
    # files == {"cube.vti", "picks.vtp", "lines.vtp", "export.json", *SCENE_FILES};
    # the cube's WholeExtent matches the frame at choice.cell and the depth axis at choice.dz_ns;
    # export.json "cell_m" == choice.cell; the Slices dock engine's choice/frame/z are unchanged.
@needs_real_data
def test_export_reuses_the_dock_engines_lines_when_the_source_matches(monkeypatch): ...
    # SliceEngine.set_source is never called on a new engine.
@needs_real_data
def test_a_cancelled_export_leaves_the_previous_one_intact(tmp_path):
    # Export once. Export again with progress returning False after 3 calls:
    # ParaViewExportCancelled; the first export's files are unchanged; no "*.partial" remains.
@needs_real_data
def test_picks_land_on_the_cube_clock_with_and_without_time_zero(): ...
    # A pick added at a known reflection's time (on the line's zero) lands in picks.vtp at
    # -depth*stretch where `strength` peaks within 2 levels: once for a preset with time_zero,
    # once for one without.
@needs_real_data
def test_pick_depths_use_the_volume_velocity(): ...
    # Grid velocity with two layers: a pick's true_depth_m == volume depth at its cube time.
@needs_real_data
def test_the_fill_cache_is_reused_and_replaced(tmp_path): ...
    # A second run with only the stretch changed calls fill_levels zero times (monkeypatch spy).
    # A change of dz_ns refills it and leaves one cache file for the grid.
def test_a_second_preparation_is_refused_while_the_dock_is_preparing(): ...
    # dock.engine.has_live_task True and the sources differ: run() raises RuntimeError
    # with "Slices are still preparing".
```

- [ ] **Step 2: Run them and see them fail.** Run the pure, core and QGIS commands on the new and changed files. Expected: FAIL.

- [ ] **Step 3: Implement the settings.** That is `_clean_volume` in `project.py`, `volume_record` and `remember_volume` in `session.py`, and `VolumeChoice` and `volume_choice` in `slices_plan.py`. Then run the pure and core tests and see them pass.

- [ ] **Step 4: Implement `ParaViewExport.run`,** in this order:
  1. **The source.** `SourceChoice(grid_id, default_preset(session, grid_id), choice.transform, source_keys(session, grid_id))`.
  2. **The lines.**
     - Use `dock.engine.prepared_lines()` when `dock.engine.choice` is the same source (`same_source`).
     - Otherwise:
       - refuse while either dock engine has a live task;
       - build `SliceEngine(session)`, call `set_source`, then `wait_for_preparation(timeout_ms=600_000)`;
       - take its prepared lines;
       - `dispose()` it in a `finally`.
  3. **The geometry.**
     - The frame is `CubeFrame.for_grid(grid, choice.cell)`, checked against `MAX_FRAME_CELLS` before anything else.
     - `z` is `ZAxis.from_range(t0, t1, choice.dz_ns)`, where `t0`/`t1` is the intersection of the prepared lines' time ranges (as `prepared_z_bounds` computes it).
     - Then the plans, and `build_cube`.
  4. **The fill and its cache.**
     - Weights: `plan_fill(cube.coverage() > 0, cell, method, max_d, search_r)`, with `FinishSettings` from `SliceFinish().updated(session.slice_resolution(grid_id)).in_metres(grid.default_spacing)`.
     - The cache file is `<site>/paraview/.cache/<safe grid>-<key>.npy`, opened with `np.lib.format.open_memmap`.
     - `key` is the first 16 hex characters of the sha1 of the JSON of: the sorted line keys, the steps, the transform, cell, dz_ns, t0, t1, the FinishSettings fields and the frame.
     - Reuse the file if it exists. Otherwise `fill_levels` into it, mapping `VolumeStopped` to `ParaViewExportCancelled`, and delete the grid's other cache files.
  5. **The volume.** The velocity is `session.resolved_velocity(lines[0].key)`. Call `prepare_volume(filled, z, velocity, cell, choice.settings)`.
  6. **Writing,** into `paraview_folder(...)` plus `.partial`:
     - **`cube.vti`:** `strength`, `amplitude` and `true_depth_m`, streamed deepest slab first and flipped within each slab. Origin `(cell/2, cell/2, -max_depth*stretch)`, spacing `(cell, cell, depth_step*stretch)`.
     - **`picks.vtp`:**
       - from `session.picks_for(key)` for each line;
       - xy is `frame.to_local(line.coords[clamp(trace)])`;
       - the time is moved with `retime_ns(p.time_ns, p.zero_ns or 0.0, target)`, where `target` is the prepared line's `zero_ns` when `time_base_of(steps) == "time_zero"`, else `0.0`;
       - the depth is `velocity.depth_at(t)` and `z = -depth*stretch`;
       - arrays `true_depth_m` and `line_index`.
     - **`lines.vtp`:** each line's local coords at `z = 0`, at most 200 points per line, plus the frame outline.
     - **The scene:** `write_scene_files` with `scene_record(...)`. `amplitude_range` uses the p99 of the amplitude, taken from the slab pass. The slices start at the mid depth, the middle line's x and the mid y.
  7. **Replacing.** Rename any existing folder to `.old`, rename `.partial` to the final name, then remove `.old`. On any exception or cancellation, remove `.partial` and re-raise.

  `progress` counts the fill levels plus the written slabs. A False return raises `ParaViewExportCancelled`.

- [ ] **Step 5: Run the tests and see them pass.** Then run the QGIS files `test_plugin_slices_engine.py` and `test_plugin_slices_dock.py` to check that the dock is untouched, then ruff and mypy.

- [ ] **Step 6: Commit**

```bash
git add -A packages/nsgeo-core/src/nsgeo/project.py packages/nsgeo-core/tests/test_project.py packages/nsgeo-qgis/nsgeo_qgis/session.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py packages/nsgeo-qgis/tests/pure/test_pure_volume_choice.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py
git commit -m "feat: export a grid for ParaView at its own 3-D resolution (M16 A)"
```

---

