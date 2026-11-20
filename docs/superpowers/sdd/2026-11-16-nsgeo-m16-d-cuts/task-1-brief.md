### Task 1: Picks on cuts join surfaces

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py` (`place_picks`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/surfaces.py` (`check`, `_grid_of`, `inputs`, the fit's skipped reasons)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/surface_plan.py` (`selection_refusal`, the new reasons)
- Modify: `docs/guide/getting-started.md`, the line "Picks on cuts cannot be used yet."
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surface_build.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_surfaces_membership.py`, `packages/nsgeo-qgis/tests/pure/test_pure_surface_plan.py`

**Interfaces:**
- Consumes:
  - `nsgeo.model.cut.Cut` (`key`, `grid_id`, `vertices`, `point_at(distance_m)` in grid metres) and `is_cut_key`;
  - `session.cut_for_key(key)` (raises `KeyError`) and `session.cut_keys_on_grid(grid_id)`;
  - `Grid.to_world(local: np.ndarray) -> np.ndarray`;
  - `CubeFrame.to_local(world)`.
- Produces:
  - `place_picks(rows, lines, prov, frame, velocity, *, cuts: Mapping[str, Cut] | None = None, grid: Grid | None = None) -> list[PlacedPick | None]`. A cut pick is placed when its key is in `cuts`, `grid` is given, and its time base equals `time_base_of(prov.steps)`. Its `trace` is the stored column.
  - `cut_pick_base(pick) -> str` in `surface_plan.py`, implementing call 5.
  - `WHY_OTHER_CLOCK = "they were made on a cut on another clock"` and `WHY_NO_CUT = "their cut has been deleted"` in `surface_plan.py`.
  - `selection_refusal` loses its `on_cuts` parameter.

- [ ] **Step 1: Write the failing tests.**
  - Use the `built_site` fixture. Add a cut along line 0 with `session.add_cut(GRID, [(0.5, 0.5), (0.5, 11.5)])`. The fixture's preset sets time zero, so a placeable cut pick carries `"time_base": "time_zero"`.
  - Write cut picks with `layers.write_pick(Pick(line_key=cut_key, trace=col, distance_m=d, time_ns=t, zero_ns=None, stack_json=json.dumps({"time_base": base}), ...))`, as `conftest.surface_plugin` writes line picks.

```python
def test_a_cut_pick_lands_where_the_line_pick_under_it_lands(built_site):
    # A cut drawn along line 0 (x = 0.5): a cut pick at the same place and moment as a line pick
    # is placed at the same depth and, within half a cell, the same spot.
    ...
    a, b = place_picks([(line_key, line_pick), (cut_key, cut_pick)], got.lines, got.prov,
                       got.frame, got.velocity, cuts={cut_key: cut}, grid=session.grid(GRID))
    assert b.depth_m == pytest.approx(a.depth_m)
    assert math.hypot(b.x_m - a.x_m, b.y_m - a.y_m) <= got.frame.cell / 2

def test_a_surface_builds_from_line_and_cut_picks_together(built_site): ...
    # three line picks + two cut picks -> check() accepts; build -> fit counts five picks

def test_a_cut_pick_on_another_clock_is_reported_not_placed(built_site): ...
    # preset STEPS_ZERO, cut pick with time_base "radar" -> place_picks gives None; the build's
    # skipped list names WHY_OTHER_CLOCK for it; the other picks build

def test_a_deleted_cut_marks_its_surfaces_stale_and_is_reported(built_site): ...
    # build with a cut pick; session.delete_cut(cut_key) (the M15 delete) -> state(...).stale
    # contains "source"; rebuild -> skipped reason WHY_NO_CUT; no raise

def test_a_cut_pick_outside_the_frame_is_reported_on_a_hole(built_site): ...

def test_a_cut_picks_distance_not_its_column_is_its_identity(built_site): ...
    # changing only the stored column (trace) of a cut pick leaves the surface fresh; moving its
    # distance_m marks it stale ("picks")
```

  In `test_pure_surface_plan.py`, replace the cut-refusal assertion with:

```python
def test_cut_picks_are_no_longer_refused():
    assert "cut" not in (selection_refusal(...the same args without on_cuts...) or "")

def test_a_cut_picks_time_base_comes_from_its_provenance():
    assert cut_pick_base(_pick(stack_json='{"time_base": "time_zero"}')) == "time_zero"
    assert cut_pick_base(_pick(stack_json="")) == "radar"
    assert cut_pick_base(_pick(stack_json="not json")) == "radar"
```

  Spell each test out in full, with the asserts its comment names. Find the M15 call that deletes a cut by searching `session.py` for `cuts_changed` emitters.

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement.**
  - **`place_picks`:**
    - a cut pick is placed as the Architecture section says;
    - the time is `p.time_ns`, never retimed;
    - the base comes from `cut_pick_base`, compared with `time_base_of(prov.steps)`;
    - a cut missing from `cuts` gives None.
  - **`Surfaces`:**
    - `_grid_of` answers a cut key with `session.cut_for_key(key).grid_id`, and with None on `KeyError`;
    - `check` stops counting `on_cuts`;
    - the build passes `cuts={k: session.cut_for_key(k) for the member cut keys that still exist}` and `grid=session.grid(grid_id)` to `place_picks`;
    - a None for a cut key gets a reason: `WHY_NO_CUT` when the cut is gone, `WHY_OTHER_CLOCK` when the base differs, else `WHY_NO_DEPTH`.
  - **`inputs()`:**
    - the `picks` entry for a cut pick is `[key, round(distance_m, 4), round(radar_ns, 6)]`;
    - `source` gains `"cuts": sorted([key, vertices or None] for each member cut key)`, so a deleted or redrawn cut marks the surface stale.
  - **The guide:** replace "Picks on cuts cannot be used yet." with a sentence saying picks on cuts join surfaces like picks on lines, as long as they were made on the clock the grid's preset uses now.

- [ ] **Step 4: Run the three test files; they pass.** Run `test_plugin_paraview_export.py` too, since `place_picks` changed, then the lint commands.

- [ ] **Step 5: Commit and push.**

```bash
git add -u packages/nsgeo-qgis docs/guide/getting-started.md
git commit -m "feat(surfaces): picks on cuts join surfaces, on the cube's clock (M16 D)"
git push origin nsgeo-m16-d
```

