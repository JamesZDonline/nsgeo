### Task 1: The scene's arithmetic, and pick depths without preparing

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/scene3d_plan.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py` (a new method beside `place_picks`'s users)
- Modify: `.github/workflows/ci.yml` (mypy list)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_scene3d_plan.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py`

**Interfaces:**
- Consumes:
  - `slices_plan.DEFAULT_STRETCH` (3.0);
  - `ParaViewExport.defaults`, `source_choice` and `_zero_of`;
  - `time_base_of` and `TIME_BASE_TIME_ZERO`, and `retime_ns`, as `place_picks` imports them;
  - `session.grid_depth_velocity(grid_id)`.
- Produces, in `scene3d_plan.py`:
  - `VIEW_NAME: str = "nsgeo 3D"`;
  - `PICK_RADIUS_M: float = 0.06`;
  - `NO_GRID: str = "Add a grid first: the 3-D view shows one grid."`;
  - `BUTTON_TIP: str = "Open QGIS's 3-D view of the grid the Slices panel shows: its picks at depth and its surfaces"`;
  - `PICKS_LAYER_NAME: str = "Picks at depth (3D view)"`;
  - `def scene_stretch(record: Mapping[str, object]) -> float`: the record's `stretch` when it is a finite number above 0, else `DEFAULT_STRETCH`;
  - `def view_title(grid_name: str, stretch: float, n_stale: int) -> str`;
  - `def scene_grid(scope: str, shown: str | None, last: str | None) -> str | None`;
  - `def stretched_z(depth_m: float, stretch: float) -> float`: returns `-depth_m * stretch`;
  - `@dataclass(frozen=True) class CameraPose: x: float; y: float; z: float; distance: float; pitch: float; yaw: float`;
  - `def camera_pose(corners: Sequence[tuple[float, float]], depths: Sequence[float], stretch: float) -> CameraPose`.
- Produces, in `paraview_export.py`:
  - `def ParaViewExport.pick_depths(self, grid_id: str, rows: Sequence[tuple[str, Any]]) -> list[float | None]`: each `(line_key, pick)`'s true depth in metres, as `place_picks` gives it, or None.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_scene3d_plan.py`:

```python
def test_view_title_states_grid_stretch_and_stale_count():
    assert view_title("Grid 1", 3.0, 0) == "nsgeo 3D  ·  Grid 1  ·  depth stretched ×3"
    assert view_title("Grid 1", 2.5, 1) == (
        "nsgeo 3D  ·  Grid 1  ·  depth stretched ×2.5  ·  1 surface stale"
    )
    assert view_title("Grid 1", 3.0, 2).endswith("  ·  2 surfaces stale")

def test_scene_grid_follows_this_grid_and_keeps_the_last_in_whole_site():
    assert scene_grid("grid", "Grid 2", "Grid 1") == "Grid 2"
    assert scene_grid("site", "Grid 2", "Grid 1") == "Grid 1"
    assert scene_grid("site", "Grid 2", None) == "Grid 2"
    assert scene_grid("grid", None, None) is None

def test_scene_stretch_is_the_grids_own_or_the_default():
    assert scene_stretch({"stretch": 2.0}) == 2.0
    for bad in ({}, {"stretch": 0.0}, {"stretch": float("nan")}, {"stretch": "x"}):
        assert scene_stretch(bad) == DEFAULT_STRETCH

def test_camera_frames_the_grid_at_mid_depth():
    pose = camera_pose([(0, 0), (20, 0), (20, 16), (0, 16)], [1.0, 3.0], 3.0)
    assert (pose.x, pose.y) == (10.0, 8.0)
    assert pose.z == pytest.approx(-2.0 * 3.0)
    assert pose.distance == pytest.approx(1.2 * 20.0)
    assert (pose.pitch, pose.yaw) == (45.0, 0.0)
    assert camera_pose([(0, 0), (2, 0), (2, 2), (0, 2)], [], 3.0).z == 0.0
```

- [ ] **Step 2: Run them; they fail** (`ModuleNotFoundError: nsgeo_qgis.scene3d_plan`).

- [ ] **Step 3: Implement `scene3d_plan.py`** to the signatures above.
  - The numbers in titles are formatted with `:g`.
  - `camera_pose` takes the centre of the corners and the mean of the shallowest and deepest of `depths` (0 when there are none), then applies `stretched_z`.

- [ ] **Step 4: Write the failing QGIS tests** in `test_plugin_paraview_export.py`, beside the real-data `site` fixture's tests. Copy `_pick` from `test_plugin_surface_build.py` (`_noop` is already in this file), and import `place_picks`.

```python
@needs_real_data
@pytest.mark.parametrize("steps", [STEPS_ZERO, STEPS_RADAR], ids=["time_zero", "radar_clock"])
def test_pick_depths_match_place_picks_without_preparing(site, steps, monkeypatch):
    session, _, export = site
    session.site.presets["p"] = list(steps)
    key = session.keys()[1]
    rows = [(key, _pick(key, 30, 12.0)), (key, _pick(key, 30, 9.0, zero_ns=3.0))]
    got = export.fill(GRID, export.defaults(GRID), progress=_noop)
    want = [p.depth_m for p in place_picks(rows, got.lines, got.prov, got.frame, got.velocity)]
    del got
    fresh = ParaViewExport(session, site[1])
    monkeypatch.setattr(fresh, "_prepared", lambda *a, **k: pytest.fail("prepared a line"))
    assert fresh.pick_depths(GRID, rows) == pytest.approx(want)

def test_pick_depths_are_none_where_they_cannot_be_found(synth_site):
    session, _, export = synth_site
    key = session.keys()[0]
    rows = [("raw/none.DZT", _pick(key, 5, 10.0)), ("cut:abc", _pick(key, 5, 10.0)),
            (key, _pick(key, 5, float("nan")))]
    assert export.pick_depths(GRID, rows) == [None, None, None]
```

  The real-data test pins "real files first" (spec §9). The synthetic test runs on CI.

- [ ] **Step 5: Run them; they fail** (`AttributeError: ... 'pick_depths'`).

- [ ] **Step 6: Implement `ParaViewExport.pick_depths`.**
  - Take the source with `self.source_choice(grid_id, self.defaults(grid_id))`.
  - Set `on_zero = time_base_of(steps) == TIME_BASE_TIME_ZERO`.
  - For each line pick whose key is in `source.line_keys`:
    - `target = self._zero_of(key, steps)` when `on_zero`, else 0.0;
    - `t = retime_ns(p.time_ns, p.zero_ns or 0.0, target)`.
  - Then `session.grid_depth_velocity(grid_id).depth_at(...)` over all of them in one call.
  - Return None for:
    - a cut key;
    - a key outside the source;
    - a non-finite time or depth;
    - a `_zero_of` that raises (log it once).
  - When the grid has no lines, `defaults` raises `ValueError`; return all None.

- [ ] **Step 7: Run both test files and pass.** Add `scene3d_plan.py` to the mypy list in `ci.yml` and in your local mypy command, then run the lint commands.

- [ ] **Step 8: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/scene3d_plan.py packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py .github/workflows/ci.yml packages/nsgeo-qgis/tests/pure/test_pure_scene3d_plan.py packages/nsgeo-qgis/tests/qgis/test_plugin_paraview_export.py
git commit -m "feat(3d): the 3-D view's title, scene grid, stretch and camera; pick depths without preparing (M16 C)"
git push origin nsgeo-m16-c
```

