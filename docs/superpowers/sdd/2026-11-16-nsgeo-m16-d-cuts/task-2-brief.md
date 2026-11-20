### Task 2: Cut picks in the export's picks and in the 3-D view

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py` (`_write_picks`, `_pick_counts`, `pick_depths`, `_record`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_scene.py` (`scene_record`: a defaulted `cuts` field)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/scene3d.py`, which reads the scene grid's cut picks too
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_scene3d.py`, `packages/nsgeo-qgis/tests/pure/test_paraview_scene.py`

**Interfaces:**
- Consumes: Task 1's `place_picks(..., cuts=, grid=)` and `cut_pick_base`.
- Produces:
  - **`picks.vtp`:**
    - it gains an int32 `cut` array: the pick's index in `export.json`'s `cuts`, or −1;
    - `line` is −1 for a cut pick.
  - **`export.json`** gains `cuts: [{"index": int, "key": str, "name": str}]`, one per saved cut on the grid, in key order. `scene_record` validates it and defaults it to `[]`.
  - **`pick_depths`** answers cut keys by Task 1's rule.

- [ ] **Step 1: Write the failing tests.**

```python
def test_cut_picks_are_in_picks_vtp_with_their_cut(built_site): ...
    # one cut with two picks on the grid -> picks.vtp has them with cut == 0 and line == -1,
    # true_depth_m equal to place_picks'; export.json["cuts"] == [{"index": 0, "key": ..., "name": "Cut 1"}]
    # summary(...).n_picks counts them

def test_a_cut_pick_on_another_clock_is_left_out_of_the_export(built_site): ...

def test_the_3d_view_shows_the_grids_cut_picks(scene): ...
    # Plan C's fixture + a cut pick -> one more point in the picks layer at -depth*stretch

def test_scene_record_validates_cuts():
    # pure: missing -> []; wrong keys or misnumbered -> ValueError
```

  Spell each test out in full, with the asserts its comment names.

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement.**
  - `_write_picks` adds the rows of `session.picks_for(k)` for `k` in `session.cut_keys_on_grid(grid_id)`, after the lines' rows. It passes `cuts` and `grid` to `place_picks`, and fills `cut` and `line` as above.
  - `_pick_counts` counts the same rows.
  - `pick_depths` uses Task 1's rule for cut keys.
  - `Scene3D` reads the cut picks of the scene grid as well as the line picks. A cut pick's point is its map position on the picks layer.

- [ ] **Step 4: Run the test files; they pass.** Then run the lint commands.

- [ ] **Step 5: Commit and push.**

```bash
git add -u packages/nsgeo-qgis
git commit -m "feat(paraview,3d): cut picks in picks.vtp, export.json and the 3-D view (M16 D)"
git push origin nsgeo-m16-d
```

