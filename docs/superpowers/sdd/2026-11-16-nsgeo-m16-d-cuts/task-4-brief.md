### Task 4: Walls in the export and the scene

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py` (`run`, `estimate`, `summary`, `_record`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_scene.py` (`scene_record`: a defaulted `walls` field; `ExportSummary` and `summary_rows` count walls)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview/open_scene.py.txt` and `paraview/README.md.txt`
- Modify: `docs/guide/getting-started.md` (Step 9's list of what is in the folder)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py`, `packages/nsgeo-qgis/tests/pure/test_paraview_scene.py`

**Interfaces:**
- Consumes: Task 3's `line_wall`, `cut_wall`, `wall_points`, `wall_columns`, `write_structured_grid` and `structured_grid_bytes`.
- Produces:
  - **`export.json`** gains `walls: [{"index": int, "name": str, "kind": "line" | "cut", "file": "walls/<index>.vts"}]`. Lines come first, in `source.line_keys` order, named by the line's file stem; cuts follow, in key order, named by the cut's name.
  - **`ExportSummary`** gains `n_walls: int` and `walls_bytes: int`. `export_bytes` includes `walls_bytes`.
  - **`summary_rows`** names the walls, for example "34 walls, about 76 MB".

- [ ] **Step 1: Write the failing tests.**

```python
@needs_real_data
def test_every_line_and_cut_gets_a_wall(site): ...
    # add a cut; run -> walls/0.vts..; export.json["walls"] lists 4 lines then the cut, files exist,
    # each .vts has an "amplitude" array, nz rows, <= 300 columns; z of row k == -depth_k * stretch

@needs_real_data
def test_the_stated_size_includes_the_walls_and_matches_the_files(site): ...
    # summary(...).export_bytes within 2% of the folder's total size after run; the refusal path
    # (monkeypatched free space between cube-only and cube+walls) refuses

def test_wall_files_are_named_by_index_and_the_scene_opens(synth_site): ...
    # a cut named 'a "quoted"/cut é' -> its file is walls/<n>.vts; under NSGEO_PVPYTHON the scene
    # script runs and registers "Cut: a "quoted"/cut é" (skipped without pvpython)

def test_a_cancelled_export_leaves_no_walls_behind(site): ...
    # cancel during the wall writes -> no .partial left, the previous export untouched

def test_scene_record_validates_walls():  # pure
```

  Spell each test out in full, with the asserts its comment names.

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement.**
  - **In `run()`**, after `_write_lines`, write each wall into `partial / "walls"` while `got.lines` and `got.filled` are alive:
    - line walls are `line_wall(line, frame, z)`;
    - cut walls are `cut_wall(filled, frame, frame.to_local(grid.to_world(np.asarray(cut.vertices))))`;
    - depths come from `velocity.depth_at(z.times_ns())`;
    - points come from `wall_points`.
  - **Progress.** Each wall is one progress step, counted into `state["total"]` in `announce`.
  - **Size and refusal.** `estimate()` and the refusal in `run()` add `walls_bytes`: the sum over walls of `structured_grid_bytes(wall_columns(n) * nz, 1)`, where:
    - `n` is the line's trace count from its header, or the cut's `ceil(length / (cell / 2)) + 1`;
    - `nz` is the cube's level count.

    Put the arithmetic in `slices_plan.py` beside `export_size_bytes`.
  - **The scene template.** After the surfaces block, add one `XMLStructuredGridReader` per `INFO["walls"]` entry:
    - `registrationName` is `"Wall: " + name` for a line and `"Cut: " + name` for a cut, handed to ParaView as data, never as code;
    - it is shown coloured by `("POINTS", "amplitude")` with `amp_lut`, then hidden.

    `amp_lut` keeps being set last.
  - **The guide and the export's own README** gain one line: "Walls: every line and every cut, as a curtain coloured like the slices (black is strong), one item each, hidden at first."

- [ ] **Step 4: Run the test files.** Then run the whole QGIS tier once, the core and pure suites, and the lint commands. All pass.

- [ ] **Step 5: Commit and push.**

```bash
git add -u packages/nsgeo-qgis docs/guide/getting-started.md
git commit -m "feat(paraview): walls for every line and cut in the export and the scene (M16 D)"
git push origin nsgeo-m16-d
```

## After Task 4: the walkthrough (human gate)

Use a fresh profile, `ns_geo_m16d`, and a copy of the Sunnyside site. Write the walkthrough as an Artifact with a results database.

1. **Cut picks in a surface.**
   - Draw a cut across the bowl and pick the bowl's reflection on it.
   - Add those picks to Feature1, or build a new surface from line picks and cut picks.
   - The fit counts them, and the surface fills where only the cut had picks.
2. **Another clock.** Switch the grid's preset between time zero and none. The cut picks are reported "made on another clock" and are not used.
3. **Export Grid 1.** The dialog's size row counts the walls. In ParaView, each line and cut is an item under its own name, hidden at first.
   - Show a few.
   - They stand at the slices' depths, coloured like a depth slice.
   - The cut wall agrees with the cut in the profile view.
4. **Deleting the cut.** Delete the cut. Its surfaces turn stale, and a rebuild reports the picks.
5. **The 3-D view.** The cut picks show in the 3-D view.
