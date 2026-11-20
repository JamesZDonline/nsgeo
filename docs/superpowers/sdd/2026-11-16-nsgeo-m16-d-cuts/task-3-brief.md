### Task 3: Walls in the core, and a StructuredGrid writer

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/walls.py`
- Modify: `packages/nsgeo-core/src/nsgeo/vtkxml.py`
- Modify: `packages/nsgeo-core/tests/vtk_reader.py`, which reads `.vts` too
- Test: `packages/nsgeo-core/tests/test_slices_walls.py`, `packages/nsgeo-core/tests/test_vtkxml.py` (or the file that tests the writers today)

**Interfaces:**
- Consumes:
  - `PreparedLine`;
  - `CubeFrame` (`to_local`, `axes`, `origin`, `cell`);
  - `ZAxis.times_ns()`;
  - `resample.bilinear_taps(frame, world)` and `resample.sample(level, taps)`.
- Produces, in `walls.py`:
  - `MAX_WALL_COLUMNS: int = 300`;
  - `@dataclass(frozen=True) class Wall: local: np.ndarray  # (n, 2) frame-local metres along the wall; values: np.ndarray  # (nz, n) float32, NaN where nothing was recorded`;
  - `def wall_columns(n: int) -> int`, which is `min(n, MAX_WALL_COLUMNS)` for n ≥ 2, and raises `ValueError` below 2;
  - `def line_wall(line: PreparedLine, frame: CubeFrame, z: ZAxis) -> Wall`:
    - traces at `np.linspace(0, n_traces - 1, wall_columns(n_traces))`, rounded and unique;
    - values linearly interpolated from the line's samples at `z.times_ns()`, the line's axis being the cube's clock, as in `plan_line`;
    - NaN outside the line's time range;
  - `def cut_wall(filled: np.ndarray, frame: CubeFrame, path_local: np.ndarray) -> Wall`:
    - `filled` is (nz, ny, nx);
    - `wall_columns(...)` points evenly spaced along the path by distance, where `n` is `ceil(length / (cell / 2)) + 1`;
    - `sample(filled[k], taps)` for each level `k`;
  - `def wall_points(wall: Wall, depth_m: np.ndarray, stretch: float) -> np.ndarray`, which returns (nz, n, 3) with z = `-depth_m[k] * stretch`.
- Produces, in `vtkxml.py`:
  - `def write_structured_grid(path: Path, points: np.ndarray, point_data: dict[str, np.ndarray]) -> int`:
    - `points` is (nj, ni, 3) and each array is (nj, ni);
    - it writes appended raw binary like the other writers, with `WholeExtent="0 ni-1 0 nj-1 0 0"`;
    - it returns the bytes written;
  - `def structured_grid_bytes(n_points: int, n_arrays: int) -> int`, which is exact, as `image_data_bytes` is.

- [ ] **Step 1: Write the failing tests.** Use the real lines from `tests/real_lines.py` (`prepared_lines`, `AXIS`), as the volume tests do.

```python
def test_a_line_wall_follows_the_line_at_the_cubes_levels():
    line = prepared_lines([0], to_world)[0]
    frame = CubeFrame.for_grid(GRID, CELL); z = AXIS
    wall = line_wall(line, frame, z)
    assert wall.values.shape == (z.nz, wall_columns(line.data.shape[1]))
    k = z.nz // 2; t = z.times_ns()[k]
    i = int(round((t - line.t0_ns) / line.dt_ns))
    assert wall.values[k, 0] == pytest.approx(line.data[i, 0], rel=0.05)  # near a sample
    assert np.allclose(wall.local[0], frame.to_local(line.coords[:1])[0])

def test_a_long_line_wall_is_capped_at_300_columns(): ...
def test_a_cut_wall_samples_the_filled_cube_along_the_cut(): ...
    # a filled cube with a known ramp in x -> the wall's values follow the ramp along a cut in x
def test_a_cut_wall_is_nan_where_the_cube_has_no_data(): ...
def test_wall_points_stand_at_stretched_depth(): ...
def test_structured_grid_round_trips_and_its_size_is_exact(tmp_path):
    pts = np.random.default_rng(0).random((4, 5, 3)); amp = np.arange(20.0).reshape(4, 5)
    n = write_structured_grid(tmp_path / "w.vts", pts, {"amplitude": amp})
    doc = read_vtk_xml(tmp_path / "w.vts")
    assert np.allclose(doc["points"].reshape(4, 5, 3), pts)
    assert np.allclose(doc["point_data"]["amplitude"].reshape(4, 5), amp)
    assert doc["WholeExtent"] == (0, 4, 0, 3, 0, 0)
    assert n == (tmp_path / "w.vts").stat().st_size == structured_grid_bytes(20, 1)
```

  Spell each test out in full, with the asserts its comment names.

- [ ] **Step 2: Run them; they fail.**

- [ ] **Step 3: Implement `walls.py`, `write_structured_grid` and `structured_grid_bytes`.** Teach `vtk_reader.read_vtk_xml` the `StructuredGrid` element (`WholeExtent`, points). Points and the `amplitude` array are written as float32.

- [ ] **Step 4: Run the core suite; it passes.** Then run the lint commands.

- [ ] **Step 5: Commit and push.**

```bash
git add packages/nsgeo-core
git commit -m "feat(core): line and cut walls on the cube's levels; a StructuredGrid writer (M16 D)"
git push origin nsgeo-m16-d
```

