### Task 1: Pure rules in `lookup.py`

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (add the API below. Leave `corners_from_polygon` alone; Task 3 deletes it.)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`

**Interfaces:**
- Produces: `CORNER_ROLES: tuple[str, str, str, str] = ("origin", "+X", "+X+Y", "+Y")`.
- Produces: `utm_epsg(lon: float, lat: float) -> int | None`.
  - Zone = `floor((lon + 180) / 6) % 60 + 1`.
  - Returns `32600 + zone` when `lat >= 0`, else `32700 + zone`.
  - Returns `None` when `abs(lat) > 84` or either value is not finite.
- Produces: `@dataclass(frozen=True) class CornerFrame` with fields:
  - `rows: tuple[int, ...]`: the filled row indices, ascending.
  - `local: np.ndarray`: (n, 2) metres.
  - `world: np.ndarray`: (n, 2), the points as given.
  - `size_x: float | None` and `size_y: float | None`: measured, or `None` when the axis has no filled edge.
- Produces: `corner_frame(points: Sequence[tuple[float, float] | None]) -> CornerFrame`. It takes four slots in `CORNER_ROLES` order, with `None` for an empty row.
  - X edges are rows (0, 1) and (3, 2). Y edges are rows (0, 3) and (1, 2). Each size is the mean of that axis's filled edges.
  - Local positions are (0, 0), (sx, 0), (sx, sy), (0, sy).
  - An axis is *needed* when a filled row's local coordinate on it is non-zero: rows 1 and 2 need X, rows 2 and 3 need Y.
  - It raises `ValueError` with these exact messages, checked in this order:
    1. `"expected four corner slots, got {n}"`
    2. `"fit needs at least two corners"`
    3. `"two corners coincide"`: a filled edge shorter than 1e-6
    4. `"these corners don't fix the size along X: pick two corners joined by an X edge"`, and the same for Y
    5. `"these corners lie in a line"`: three or more rows, |shoelace area| < 1e-9 × (largest edge)²
    6. `"these corners are mirrored: check which corner is +X and which is +Y"`: three or more rows whose shoelace area, taken in row order, is negative
- Produces: `roles_from_ring(ring: Sequence[tuple[float, float]]) -> tuple[list[tuple[float, float]], list[int]]`. It returns the four points in `CORNER_ROLES` order, and each one's index in the cleaned ring.
  - Cleaning drops consecutive duplicates and the closing vertex. Anything other than four vertices raises `ValueError(f"expected four corners, got {n}")`.
  - Roles are taken in anticlockwise order (reverse a clockwise ring), so +X is the next vertex and +Y the previous one.
  - The origin is the vertex whose origin→+Y bearing, `degrees(atan2(dx, dy))` folded to (−180, 180], has the smallest absolute value. Ties go to the lower vertex index.
- Produces: `rotate_roles(rows: Sequence[T]) -> list[T]`, which returns `[rows[1], rows[2], rows[3], rows[0]]` and is generic over the row type.
- Produces: `compass_label(point: tuple[float, float], centre: tuple[float, float]) -> str`. It returns one of `N NE E SE S SW W NW`, from the bearing `atan2(dx, dy)`. N covers [−22.5°, 22.5°), and each label after it covers the next 45°.

- [ ] **Step 1: Write the failing tests.** Build the world corners from a `Grid`, so the expected values come from the core's own geometry:

```python
G = Grid("A", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
W = [tuple(p) for p in G.to_world(np.array([[0, 0], [5, 0], [5, 11], [0, 11]], dtype=float))]
def _pts(*rows): return [W[i] if i in rows else None for i in range(4)]

@pytest.mark.parametrize("lon, lat, epsg", [(-86.8, 36.1, 32616), (-84.0, 10.0, 32617),
    (-84.000001, 10.0, 32616), (180.0, 0.0, 32601), (-180.0, 0.0, 32601), (179.99, 0.0, 32660),
    (0.5, -0.0001, 32731), (0.5, 84.0, 32631)])
def test_utm_epsg_picks_the_zone(lon, lat, epsg): assert utm_epsg(lon, lat) == epsg

@pytest.mark.parametrize("lon, lat", [(0.0, 84.01), (0.0, -84.01), (float("nan"), 0.0)])
def test_utm_epsg_is_none_where_utm_is_undefined(lon, lat): assert utm_epsg(lon, lat) is None

@pytest.mark.parametrize("rows", [(0, 1), (0, 3), (0, 1, 2), (1, 2, 3), (0, 1, 2, 3)])
def test_corner_frame_recovers_the_grid(rows):
    f = corner_frame(_pts(*rows)); fit = fit_grid_from_corners(f.local, f.world)
    assert f.rows == rows and fit.origin == pytest.approx(G.origin, abs=1e-9)
    assert fit.azimuth == pytest.approx(30.0, abs=1e-9) and fit.residual_rms < 1e-9

def test_corner_frame_measures_each_axis_from_its_own_edges():
    assert (corner_frame(_pts(0, 1)).size_x, corner_frame(_pts(0, 1)).size_y) == (pytest.approx(5.0), None)
    pts = _pts(0, 1, 2, 3); x_hat, _ = G.axes(); pts[2] = tuple(np.asarray(pts[2]) + 0.4 * x_hat)
    assert corner_frame(pts).size_x == pytest.approx(5.2, abs=1e-9)  # mean of 5.0 and 5.4
```

Also add:
- `test_corner_frame_refuses_corners_that_do_not_fix_the_grid`, parametrized:
  - rows `(0,)` → `"at least two corners"`
  - rows `(0, 2)`, `(1, 3)` and `(1, 2)` → `"don't fix the size along X"`
- `test_corner_frame_refuses_coincident_corners`: rows 0 and 1 at the same point → `"coincide"`.
- `test_corner_frame_refuses_mirrored_corners`, for four corners with `W[1]` and `W[3]` swapped, and for rows (0, 1, 3) swapped the same way → `"mirrored"`.
- `test_corner_frame_refuses_corners_in_a_line`: three collinear points in rows 0, 1, 2 → `"in a line"`.
- `test_roles_from_ring_puts_the_origin_where_plus_y_points_north`: the closed ring `W + [W[0]]` → `idx == [0, 1, 2, 3]` and points `== W`. The +Y bearings for each candidate origin are 30°, −60°, −150° and 120°.
- `test_roles_from_ring_default_plus_y_is_within_45_degrees_of_north`, parametrized over grid azimuths 0, 30, 100, 200 and 300: the returned origin → +Y bearing satisfies |bearing| ≤ 45°.
- `test_roles_from_ring_is_winding_independent`: the reversed ring → points `== W`, `idx == [3, 2, 1, 0]`.
- `test_roles_from_ring_ignores_a_repeated_vertex`: `[W[0], W[1], W[1], W[2], W[3], W[0]]` → four corners.
- `test_roles_from_ring_refuses_anything_but_four_corners`: three vertices → `"got 3"`; five distinct → `"got 5"`.
- `test_rotate_roles_keeps_the_frame_right_handed`: `rotate_roles(W) == [W[1], W[2], W[3], W[0]]`, and `corner_frame` of it fits with residual < 1e-9.
- `test_rotate_roles_moves_empty_rows_too`: `["a", None, "c", None]` → `[None, "c", None, "a"]`, and four rotations return the input.
- `test_compass_label`, parametrized over `(dx, dy)` → label:
  - `(0,1)` N, `(1,1)` NE, `(1,0)` E, `(1,-1)` SE, `(0,-1)` S, `(-1,-1)` SW, `(-1,0)` W, `(-1,1)` NW
  - `(0.38, 1)` N and `(0.42, 1)` NE, either side of 22.5°

- [ ] **Step 2: Run them and see them fail** with ImportError: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -q`.
- [ ] **Step 3: Implement the API above** in `lookup.py`. Each function's docstring states its rule, and says why mirrored corners are refused rather than fitted. The reason is the anti-goal: a reflection-forbidding fit returns a plausible frame with only a large RMS to show for it.
- [ ] **Step 4: Run the pure tests and mypy**, using the verification commands. Expected: all pass, and mypy is clean.
- [ ] **Step 5: Commit and push.** `feat(plugin): pure corner rules — UTM zone, local frame, roles from a ring, rotate, compass`

---

