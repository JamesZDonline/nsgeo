### Task 1: The fit, in the core

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/track_fit.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/__init__.py` (export the four names below and `TrackFrame`)
- Test: `packages/nsgeo-core/tests/test_track_fit.py`, `packages/nsgeo-core/tests/test_track_fit_real_files.py`

**Interfaces:**
- Produces, in `nsgeo.geometry.track_fit` (and re-exported from `nsgeo.geometry`):
  - `ALONG_DEG = 20.0`, `MIN_VOTE_M = 1.0`
  - `main_direction(tracks: Sequence[np.ndarray]) -> float | None` — the axial azimuth in degrees, `[0, 180)`, clockwise from CRS north; None when the lines share none (§16).
  - `measure_spacing(tracks: Sequence[np.ndarray]) -> float | None` — §16's median gap; None with fewer than two along lines or no main direction.
  - `fit_frame(tracks: Sequence[np.ndarray], spacing: float) -> TrackFrame` — `ValueError` for no tracks, a track with no finite point, or `spacing <= 0`.
  - `@dataclass(frozen=True) class TrackFrame: origin: tuple[float, float]; azimuth: float; size_x: float; size_y: float; lined_up: bool` with `def as_grid(self, grid_id: str, crs: str, spacing: float) -> Grid`.
  - `metres_outside(grid: Grid, xy: np.ndarray) -> tuple[float, bool]` — (metres of trace-to-trace steps whose midpoint lies outside the rectangle, whether any trace lies inside).
- Each track is an `(n, 2)` array of world positions in the site CRS, as `Line.trace_coords(frames)` returns.

- [ ] **Step 1: Write the failing synthetic tests** in `test_track_fit.py`. A helper `zigzag(n_lines, spacing, bearing_deg, length=30.0, wobble=0.03, seed=0)` builds tracks walked alternately up and down at `bearing_deg`, each line a column of points every 0.1 m with seeded cross-wobble of `wobble` m.

```python
def test_a_zigzag_survey_is_fitted_along_its_lines():
    tracks = zigzag(12, 0.5, 30.0)
    assert main_direction(tracks) == pytest.approx(30.0, abs=0.2)
    assert measure_spacing(tracks) == pytest.approx(0.5, abs=0.01)
    frame = fit_frame(tracks, 0.5)
    assert frame.lined_up and frame.azimuth == pytest.approx(30.0, abs=0.2)
    assert frame.size_x == pytest.approx(12 * 0.5, abs=0.05)   # outer means ± half a spacing
    assert frame.size_y == pytest.approx(30.0, abs=0.05)
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    local = np.vstack([grid.to_local(t) for t in tracks])
    assert local[:, 1].min() >= -1e-9 and local[:, 1].max() <= grid.size_y + 1e-9

def test_reversed_lines_and_a_bearing_past_90_fold_to_one_azimuth():
    assert main_direction(zigzag(6, 0.5, 170.0)) == pytest.approx(170.0, abs=0.2)
    assert fit_frame(zigzag(6, 0.5, 170.0), 0.5).azimuth == pytest.approx(350.0, abs=0.2)

def test_one_line_has_no_spacing_and_a_typed_one_makes_it_one_spacing_wide():
    tracks = zigzag(1, 0.5, 10.0)
    assert measure_spacing(tracks) is None
    assert fit_frame(tracks, 0.8).size_x == pytest.approx(0.8, abs=1e-6)

def test_lines_in_every_direction_get_the_smallest_rectangle():
    tracks = zigzag(6, 0.5, 0.0) + zigzag(6, 0.5, 90.0)   # equal lengths, crossing
    assert main_direction(tracks) is None and measure_spacing(tracks) is None
    frame = fit_frame(tracks, 0.5)
    assert not frame.lined_up
    # every trace inside, half a spacing in from each side at the tightest
    ...

def test_short_lines_do_not_vote_and_a_cross_line_is_held_inside():
    ...  # 10 along lines + one 1.5 m line at 60°: direction unchanged; frame holds the cross line

def test_metres_outside_counts_only_the_steps_outside():
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32632", 0.5)
    inside_then_out = np.column_stack([np.full(201, 5.0), np.linspace(0.0, 20.0, 201)])
    metres, any_in = metres_outside(grid, inside_then_out)
    assert metres == pytest.approx(10.0, abs=0.1) and any_in
    assert metres_outside(grid, inside_then_out + [30.0, 0.0]) == (pytest.approx(20.0, abs=0.1), False)
```

Fill in the two elided bodies with assertions that pin the stated behaviour (every trace inside; the azimuth of the along lines unchanged by the short and cross lines).

- [ ] **Step 2: Run them to see them fail** (`ModuleNotFoundError: nsgeo.geometry.track_fit`).
- [ ] **Step 3: Implement `track_fit.py`** to §16 of the spec.
  - Direction per track: last finite point minus first; tracks with a chord under `MIN_VOTE_M` do not vote. Axial mean: mean of `(cos 2θ, sin 2θ)` weighted by chord length, halved back; θ measured as azimuth (`atan2(dx, dy)`).
  - Along: within `ALONG_DEG` of the mean. A main direction exists when the along chords sum to more than half of all chords (one voting track always does; an even 50/50 cross-hatch has none).
  - Spacing: each along track's mean position across the main direction, sorted; the median of consecutive differences.
  - Frame, lined up: rotate into (cross, along); along extent = every trace; cross extent = outer along means ∓ `spacing / 2`, widened to hold every trace of a track that is not along. Fold the azimuth so +Y follows the main direction with azimuth in `(-90, 90]`, stored `% 360`. Origin = the world position of local (0, 0).
  - Frame, no main direction: convex hull (monotone chain) of every trace, the minimum-area rectangle over hull-edge angles, grown by `spacing / 2` on all sides, +Y along the longer side, azimuth folded the same way.
  - `metres_outside`: `grid.to_local`, step midpoints outside `[0, size_x] × [0, size_y]` summed by step length; `any_in` from the traces themselves.
- [ ] **Step 4: Run the synthetic tests to pass.**
- [ ] **Step 5: Write the real-data tests** in `test_track_fit_real_files.py`, skipping when `GPS_LINES` / `GRID2_LINES` is empty (reason naming `tests/data/local`, so the `real_data` mark applies). Project every line of a survey with one shared `tests.dzg_data.local_xy` about the first file's first RTK fix, read at run time.

```python
@pytest.mark.skipif(not GPS_LINES, reason="no real GPS survey in tests/data/local")
def test_the_first_survey_fits_along_its_sixty_lines():
    tracks = survey_tracks(GPS_LINES)
    assert len(tracks) == 60
    assert main_direction(tracks) == pytest.approx(3.8, abs=0.5)      # spec §2: bearing 3.8°
    s = measure_spacing(tracks)
    assert s == pytest.approx(0.496, abs=0.01)                         # spec §2: 0.496 m by GPS
    frame = fit_frame(tracks, s)
    assert frame.lined_up and frame.size_x == pytest.approx(60 * s, abs=0.3)
    grid = frame.as_grid("G", "LOCAL", s)
    inside = np.mean(np.vstack([inside_mask(grid, t) for t in tracks]))
    assert inside >= 0.99
    cube = CubeFrame.for_grid(grid, s)
    assert covered_cells(cube, tracks) / cube_cell_count(cube) >= 0.9

@pytest.mark.skipif(not GRID2_LINES, reason="no real second survey in tests/data/local")
def test_the_second_survey_fits_too():
    ...  # main direction exists, 0.45 < spacing < 0.55, lined up, ≥ 99 % of traces inside
```

`inside_mask` and `cube_cell_count` are small helpers in the test file (`cube_cell_count` reads the frame's cell grid size; see `nsgeo.slices.frame.CubeFrame`).
- [ ] **Step 6: Run the real-data tests locally; they must pass, not skip.** Then core + pure, lint and types.
- [ ] **Step 7: Commit and push** (`feat(core): fit a grid to GPS tracks (M17b, #134)`).

---

