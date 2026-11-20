# Grid Dialog Corners Implementation Plan (#27, #62, #63, #28)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** The **New grid** window places a grid from one table of four corners, filled by typing, by clicking on the map (with snapping) or from a polygon. One **Fit** places the grid. Coordinates in any CRS are converted on the way in. While the window is open, the map shows which corner is which.

**Architecture:** The pure rules go in `nsgeo_qgis/lookup.py`: the UTM zone, the local frame and refusals, roles from a ring, Rotate, and compass labels. `GridDialog` loses its three tabs and gains:
- a corner table with its own "Corners in" CRS
- a polygon row
- typed-size state and a live "off by" column
- an automatic grid CRS (the site's CRS, then the project's, then UTM)

A new `PickPointTool` replaces `DigitiseGridTool`. It has its own 12 px snapping, with points preferred over vertices. `plugin.py` drives it for Pick, Pick all and picking a polygon. A `GridOverlay` owned by the dialog draws role tags, the chosen polygon and the form's grid on the canvas, and disposes of every canvas item when the dialog finishes.

**Tech Stack:** Python 3, numpy; PyQGIS 3.40–4.x through `qgis.core` / `qgis.gui`; PyQt via `qgis.PyQt`; pytest on two tiers (core+pure in `.venv`, QGIS in `.venv-qgis`).

**Spec:** `docs/superpowers/specs/2026-10-23-nsgeo-grid-dialog-corners-design.md`. Read it first:
- §3 lists the user's six decisions and Claude's calls C1–C14 (C6 is withdrawn).
- §4 is the behaviour this plan builds.

The mock-up the user chose (option B) is `.lavish/grid-dialog-corners.html` in the main checkout. It is local only.

## Global Constraints

- QGIS 3.40 to 4.99. Qt only through `qgis.PyQt`. Scoped enums only (`Qgis.SnappingMode.AllLayers`, `Qgis.SnappingType.Vertex`, `Qgis.MapToolUnit.Pixels`, `Qgis.GeometryType.Point`, `Qgis.DistanceUnit.Meters`). No `exec_`.
- `nsgeo-core` is not touched. `lookup.py` stays Qt-free and inside CI's mypy run. Both boundary test files must stay green.
- Every slot connected to a signal, and every Qt-invoked override (`canvasMoveEvent`, `canvasReleaseEvent`, `keyPressEvent`, `paint`), guards its own body. An exception becomes a message in the dialog's status line or the message bar. It is never raised out of a slot. Read `plugin.py`'s module docstring and `digitise_tool.py`'s before touching either file.
- Every canvas item created (snap marker, label, rubber band, custom item) is taken back off the scene on every finishing path. Follow the `dispose()` rule in `digitise_tool.py` and `map_link.py`: idempotent, and `item.scene()` rather than `canvas.scene()`.
- `_validate`'s three CRS guards and `CRS_SCALE_WARN` / `CRS_SCALE_REFUSE` are unchanged.
- The role names are exactly `origin`, `+X`, `+X+Y`, `+Y`, in that row order (`CORNER_ROLES`).
- A typed size never enters the fit. Fit uses only the corners' measured edges (decision 6).
- Fit runs only when Fit is pressed (C1). Fill, picks, Rotate and cell edits never fit.
- Values show 8 decimals in a geographic CRS and 3 in a projected one. Full precision is kept behind the display.
- ruff 0.17.1 and mypy 2.4.0, as pinned in CI.

## Verification commands (exactly these)

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
- qgis: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh`. It takes several minutes; run single files while iterating.
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`

Before Task 1, the coordinator:
- builds the worktree's `.venv` and `.venv-qgis`;
- symlinks the real DZT files into `packages/nsgeo-core/tests/data/local/`;
- checks that `nsgeo.__file__` names the worktree;
- records the baseline pass counts in the ledger.

Before any qgis-tier count is trusted, also run the suite once with an autouse fixture that fails a test when `sys.excepthook` or `sys.unraisablehook` fired during it. A slot exception passes locally and aborts CI.

## Shared test geometry

Several tasks use one real-world grid near Nashville, 20 × 20 m at azimuth 10°. Define it once in `tests/qgis/test_plugin_grid_dialog.py`:

```python
SITE = Grid("S", (518_204.112, 4_000_731.508), 10.0, 20.0, 20.0, "EPSG:32616", 0.5)
SITE_CORNERS = SITE.to_world(np.array([[0, 0], [20, 0], [20, 20], [0, 20]], dtype=float))  # origin, +X, +X+Y, +Y
UTM16, WGS84 = QgsCoordinateReferenceSystem("EPSG:32616"), QgsCoordinateReferenceSystem("EPSG:4326")
```

Add a `project_crs` fixture that sets `QgsProject.instance().setCrs(...)` and restores the original afterwards. It is used wherever a test needs a particular project CRS.

**A real canvas for tests.** Task 4 is the first to need one, so it adds `_real_canvas(fake_iface, crs, extent)` to `tests/qgis/conftest.py`; Tasks 5 and 6 reuse it. It:
- shows the main window offscreen;
- resizes the canvas to 800 × 600;
- sets the destination CRS and the extent;
- processes events.

It asserts `canvas.mapUnitsPerPixel() == pytest.approx(1.0)` when the extent is 800 × 600 m, so that a pixel tolerance cannot pass by accident. To drive a map tool:
- build `QgsMapMouseEvent(canvas, QEvent.Type.MouseMove or MouseButtonRelease, QPoint(px, py), button)`, with the pixel taken from `canvas.getCoordinateTransform().transform(point)`;
- call `canvasMoveEvent` / `canvasReleaseEvent` / `keyPressEvent` directly.

## Review Focus

These are the inputs most likely to hurt a user that the spec's test list does not name. Each one is pinned by a test in the task named.

1. **A polygon layer stored as MultiPolygon.** Shapefiles and most GeoPackages load that way. Fill must read the first ring of the first part (Task 3: `test_fill_reads_a_multipolygon_layer`).
2. **A drawn polygon with a doubled vertex.** A double-click while digitising repeats a vertex. Consecutive duplicates are dropped before the four corners are counted (Task 1: `test_roles_from_ring_ignores_a_repeated_vertex`).
3. **A layer that isn't shown on the map.** Picks never snap to a feature the user cannot see (Task 5: `test_a_layer_not_on_the_canvas_is_never_snapped_to`).
4. **A cell typed or pasted with a comma decimal, or half-filled.** The row reads as empty, the status line names the row, and nothing crashes (Task 2: `test_a_non_number_cell_reports_and_leaves_the_row_empty`).
5. **Rotate on a partly filled table.** Empty rows rotate with the rest, so a two-corner table stays a valid two-corner table (Task 1: `test_rotate_roles_moves_empty_rows_too`; Task 2: `test_rotate_carries_sources_and_swaps_typed_sizes`).

---

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

### Task 2: One corner table and Fit

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`
  - Remove `QTabWidget`, `_build_corner_tab`, `_build_digitise_tab`, `_build_polygon_tab`, `digitise_requested`, `set_digitised`, `use_polygon`, `set_corner_row`, `_corner_arrays`, `residual_label` and the module docstring's "three ways in".
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`. Remove the `digitise_requested.connect` line and `_start_digitise`. Leave `_finish_with_digitise_tool` and `finished`'s stranded-tool cleanup for Task 5.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: Task 1's `CORNER_ROLES`, `corner_frame`, `rotate_roles`, and core's `fit_grid_from_corners` and `Grid.to_world`.
- Produces, on `GridDialog`:
  - **Column constants:** `COL_ROLE, COL_A, COL_B, COL_FROM, COL_PICK, COL_OFF = range(6)` at module level.
  - **Widgets:**
    - `corners_crs` (`QgsProjectionSelectionWidget`, starting on the project CRS, or EPSG:4326 when that is invalid)
    - `corner_table` (4 × 6; the headers read `lon`/`lat` when `corners_crs` is geographic, else `E`/`N`)
    - `pick_buttons: list[QPushButton]`, one cell widget per row, text `Pick`
    - `pick_all_button`, `rotate_button` (`⟳ Rotate`), `clear_button`, `fit_button`, `fit_status: QLabel`
    - `size_hint: QLabel` and `use_measured_button` (`Use these`), both hidden until relevant
  - **Signals:** `pick_requested = pyqtSignal(int)`, `pick_all_requested = pyqtSignal()`, `corners_changed = pyqtSignal()`. `corners_changed` is emitted after any row changes, including after Rotate and Clear.
  - **Methods:**
    - `corner_point(row: int) -> QgsPointXY | None` (in `corners_crs`)
    - `corner_source(row: int) -> str`
    - `set_corner(row: int, point: QgsPointXY, crs: QgsCoordinateReferenceSystem, source: str) -> bool`. It converts `crs` → `corners_crs`. On `QgsCsException` it writes `f"could not convert that point into {authid}"` to `fit_status`, leaves the row unchanged, and returns False.
    - `clear_corners() -> None`, `rotate_corners() -> None`, `fit_corners() -> None`, `use_measured_size() -> None`
    - `sizes_typed() -> tuple[bool, bool]`
    - `measured_size() -> tuple[float | None, float | None] | None` (`None` before any Fit)
    - `corner_offsets() -> list[float | None]` (metres, one per row)

- [ ] **Step 1: Delete the tests of removed UI.** Delete these tests; Tasks 3 and 5 add their replacements by name:
  - the polygon-tab and `use_polygon` tests (5)
  - `test_digitised_points_set_origin_and_azimuth`, `test_digitise_tab_instructions_mention_the_right_click_abort`, `test_set_digitised_rejects_coincident_points`
  - every `test_digitise_flow_*` and every test that clicks `digitise_button` (the stranded-tool, hidden-mid-pick, unload-mid-pick and three rubber-band tests)
  - `test_corner_tab_residual_caption_distinguishes_mirrored_from_not_square` (C14 now refuses instead)
  - `test_corner_fit_places_control_points_not_anchored_at_the_local_origin` (non-corner control points are a non-goal)

  Keep the three `test_digitise_tool_*` unit tests until Task 5. In `test_crs_guard_blocks_every_route_to_a_bad_crs`, delete route 2 (the digitise canvas); the rest stands.
- [ ] **Step 2: Write the failing tests.** "Type" a cell with `d.corner_table.item(row, COL_A).setText(...)`, which emits `itemChanged` just as an edit does. Tests set `crs_widget` and `corners_crs` to `UTM16` unless a test says otherwise.
  - `test_the_dialog_has_one_corner_table_and_no_tabs`:
    - `not hasattr(d, "tabs")`
    - `not hasattr(d, "digitise_requested")`
    - the role column reads `["origin", "+X", "+X+Y", "+Y"]`
  - `test_typed_corners_fit_the_grid`: type all four `SITE_CORNERS`, then `fit_corners()`.
    - the origin is within 1e-6 of `SITE.origin`
    - the azimuth is within 1e-6 of 10.0
    - both sizes are within 1e-6 of 20.0
    - `fit_status.text() == "rigid fit RMS 0.000 m from 4 corners"`
    - every offset is < 1e-6
    - every source is `"typed"`
  - `test_a_typed_size_survives_fit_and_the_grid_stays_pinned_at_the_origin`: set `size_x` to 18.0 first, type four corners, then Fit.
    - `size_x` is still 18.0; `size_y` is 20.0; the origin is within 1e-6 of `SITE.origin`
    - offsets are about `[0, 2, 2, 0]`
    - `size_hint` is visible and reads `"the corners measure 20.00 × 20.00 m · your size is kept"`
    - then `use_measured_size()` → `size_x` is 20.0, `sizes_typed()` is `(False, False)` and the hint is hidden
  - `test_fit_does_not_depend_on_typed_sizes`: Fit, note the origin and azimuth, type sizes 7 × 9, then Fit again → the same origin and azimuth.
  - `test_an_existing_grid_opens_with_both_sizes_typed` → `sizes_typed() == (True, True)`.
  - `test_off_by_follows_the_form_without_a_refit`: after Fit, `azimuth.setValue(11.0)`.
    - offsets for rows 1–3 are now > 0.1
    - `fit_status` is unchanged
    - a form origin of (0, 0) blanks every offset
  - `test_fit_refuses_coincident_corners` (the port of `test_digitise_flow_recovers_from_coincident_points`): rows 0 and 1 at one point → `"coincide"` in `fit_status`, and the origin is untouched.
  - `test_fit_refuses_mirrored_corners`: rows 1 and 3 swapped → `"mirrored"` in `fit_status`.
  - `test_fit_needs_a_metric_grid_crs`: `crs_widget` set to EPSG:4326 → `fit_status` contains `"metric CRS"` and nothing changes. Task 4 replaces this rule.
  - `test_a_non_number_cell_reports_and_leaves_the_row_empty`: type `"518204,112"` → `corner_point(0) is None`, and `fit_status` contains `"origin"` and `"not a number"`.
  - `test_changing_corners_in_converts_the_points`: type four rows, then set `corners_crs` to `WGS84`.
    - `corner_point(0)` equals the transform of `SITE_CORNERS[0]` within 1e-9°
    - the headers read `lon`, `lat`
    - setting it back restores the points within 1e-6 m
  - `test_rotate_carries_sources_and_swaps_typed_sizes`: type rows 0 and 2, and set sizes 30 and 20 by hand. Rotate.
    - `corner_point(1)` is the old row 2, and rows 0 and 2 are empty
    - `size_x == 20`, `size_y == 30`, `sizes_typed() == (True, True)`
  - `test_clear_empties_every_row_and_leaves_the_form`: Clear empties the table and keeps the form's values.
  - `test_corners_changed_fires_on_every_row_change`: one emission each for a typed cell, `set_corner`, Rotate and Clear.
- [ ] **Step 3: Run them and see them fail.**
- [ ] **Step 4: Implement.**
  - **Layout:** a **Corners** `QGroupBox` holding the "Corners in" row, the table, the button row and `fit_status`, above the existing form. Under the Size row, add a row holding `size_hint` and `use_measured_button`.
  - **Row state:** keep `self._corners: list[tuple[QgsPointXY, str] | None]` (point in `corners_crs`, source). The dialog writes cell text under a `_filling` guard, so its own writes never count as "typed".
  - **Typed sizes:** a `_typed = [False, False]` flag pair, set from `valueChanged` unless the dialog itself is writing the box (`_sizing` guard). `_prefill` marks both as typed.
  - **Fit:** follows spec §4.2, using the grid CRS as it stands. If that CRS has no authid or isn't in metres, write `"set a metric CRS for the grid first"` and stop.
  - **"off by" and the size hint:** recompute them from a temporary `Grid` built from the form whenever a row, the origin, the azimuth, a size, `crs_widget` or `corners_crs` changes.
  - **"Corners in" conversion:** remember the previous `corners_crs` so its change converts the old points into the new one.
- [ ] **Step 5: Run the file**, then the whole qgis tier, ruff and mypy. Expected: all green, with the counts recorded.
- [ ] **Step 6: Commit and push.** `feat(plugin): one corner table and Fit; typed sizes stick; live off-by (#63)`

---

### Task 3: Fill from a polygon (#27, #28's dialog half)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (the polygon row)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`. Delete `corners_from_polygon` and `PolygonCorners`.
- Test: `tests/qgis/test_plugin_grid_dialog.py`. In `tests/pure/test_pure_lookup.py`, delete the four `corners_from_polygon` tests.

**Interfaces:**
- Consumes: Task 1's `roles_from_ring` and `compass_label`; Task 2's `set_corner`, `corners_changed` and `rotate_corners`.
- Produces, on `GridDialog`:
  - **Widgets:** `layer_combo` and `feature_picker` (names kept), `pick_polygon_button` (`Pick on map`), `fill_button` (`Fill`).
  - **Signal:** `pick_polygon_requested = pyqtSignal()`.
  - **Methods:**
    - `fill_from_polygon() -> None`
    - `set_polygon_feature(layer: QgsVectorLayer, fid: int) -> None`, which sets both combos
    - `chosen_polygon() -> tuple[QgsVectorLayer, QgsGeometry] | None`, for Task 6's outline

- [ ] **Step 1: Write the failing tests.** Reuse `_pump` and `_select_sole_feature`, retargeted to the new combos. Build the 4326 layer by transforming `SITE_CORNERS` with `QgsCoordinateTransform(UTM16, WGS84, QgsProject.instance())`.
  - `test_fill_from_a_4326_polygon_gives_the_known_utm_grid`:
    - set `corners_crs` to `WGS84` and `crs_widget` to `UTM16` by hand, then Fill and Fit;
    - the origin is within 1e-3 m of `SITE.origin`;
    - the azimuth is within 1e-6 of 10.0;
    - the sizes are within 1e-3 of 20.0;
    - the sources are `["v0 SW", "v1 SE", "v2 NE", "v3 NW"]`.
  - `test_fill_reads_a_multipolygon_layer`: the same ring in a `MultiPolygon?crs=EPSG:4326` layer gives the same corners.
  - `test_fill_labels_by_compass_in_a_geographic_crs`: the sources above come out the same when `corners_crs` is `WGS84` (the cos φ̄ rule).
  - `test_fill_without_a_feature_reports_a_message`: `fit_status == "select a polygon feature first"`.
  - `test_fill_reports_an_empty_geometry`: the message reads `"this feature has no rings to read corners from"`.
  - `test_fill_refuses_a_five_corner_polygon`: `"expected four corners, got 5"` in `fit_status`, and the rows unchanged.
  - `test_fill_does_not_fit` (C7): the origin stays (0, 0) after Fill.
  - `test_rotate_carries_polygon_labels`: after Fill and Rotate, the sources are `["v1 SE", "v2 NE", "v3 NW", "v0 SW"]`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the polygon row under a divider labelled `or fill all four from a polygon`. `fill_from_polygon` follows spec §4.6:
  - **Reading the ring:** use `asMultiPolygon()[0][0]` when the geometry is multipart, else `asPolygon()[0]`. A missing ring gives the existing message.
  - **Converting:** convert the ring layer CRS → `corners_crs` with the project's transform context. On `QgsCsException`, write a status message and stop.
  - **Roles and compass:** when `corners_crs` is geographic, compute them on `(lon · cos φ̄, lat)`, then map the indices back to the true points.
  - **Filling the rows:** fill through `set_corner` with source `f"v{i} {compass}"`.

  `pick_polygon_button` only emits `pick_polygon_requested`; Task 5 wires it.
- [ ] **Step 4: Run the file, both tiers, ruff and mypy.** All green.
- [ ] **Step 5: Commit and push.** `feat(plugin): fill the corners from a polygon in any CRS; labelled vertices; drop corners_from_polygon (#27)`

---

### Task 4: The grid's CRS chooses itself (#62)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`, and `plugin.py` (`open_grid_dialog` passes `canvas=self.iface.mapCanvas()`)
- Test: `tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: Task 1's `utm_epsg`; Task 2's `fit_corners`; Task 3's `fill_from_polygon`, in one test.
- Produces: `GridDialog.__init__(self, session, grid=None, suggested_velocity=None, parent=None, canvas: QgsMapCanvas | None = None)` and `GridDialog.crs_is_auto() -> bool`. Task 6 also uses `canvas`.

- [ ] **Step 1: Write the failing tests.** Give the dialog a `_real_canvas` (see Shared test geometry), centred on `SITE.origin` in whatever CRS the test names. A test calling `crs_widget.setCrs` stands for the user picking by hand.
  - `test_a_usable_project_crs_is_kept`: project `UTM16` → the grid CRS is `EPSG:32616`, `crs_is_auto()` is true and the hint is empty.
  - `test_a_4326_project_gets_the_canvas_centres_utm_zone`: project and canvas in `WGS84` → `EPSG:32616`. The hint contains `"picked for you"` and `"EPSG:4326"` and `"degrees"`.
  - `test_the_sites_crs_comes_first`: the site already holds a grid in `EPSG:32617`, and the project is `UTM16`. Both are usable at the site; 32617 is about 0.3% off there. The result is `EPSG:32617`, with the hint `"picked for you: the CRS the site's other grids use"`.
  - `test_fit_moves_an_automatic_crs_to_the_corners_zone`: project `UTM16`, corners typed in `WGS84` around lon −70.0, lat 36.0 (zone 16 is about 2.9% off there) → after Fit the CRS is `EPSG:32619` and the fit is in it.
  - `test_a_hand_picked_crs_is_never_replaced`: hand-pick `EPSG:32619` (about 3% off at the site, so automatic mode would replace it), then Fit `SITE_CORNERS` → still `EPSG:32619`, `crs_is_auto()` is false, and OK is disabled by the existing refusal.
  - `test_a_4326_polygon_in_a_4326_project_fits_in_the_right_utm_zone`: project, canvas and `corners_crs` all `WGS84`, and no hand pick. Fill from the 4326 `SITE` polygon (Task 3), then Fit → `EPSG:32616`, with the origin within 1e-3 m of `SITE.origin` and the azimuth within 1e-6 of 10.0.
  - `test_an_existing_grids_crs_is_never_changed`: edit a grid saved in `EPSG:32617` → `crs_is_auto()` is false, and Fit keeps `EPSG:32617`.
  - `test_hand_picking_a_crs_converts_origin_and_azimuth`: set the form to `SITE`, then hand-pick `EPSG:32617`.
    - The origin, transformed back to `UTM16`, is within 1e-3 m of `SITE.origin`.
    - The point 100 m along +Y, rebuilt from the new azimuth and transformed back, is within 1e-2 m of the original.
  - `test_no_canvas_keeps_the_project_crs_and_says_what_will_happen`: project `WGS84`, `canvas=None` → the CRS stays `EPSG:4326` and OK is disabled. The hint contains both `"metres"` and `"a UTM zone will be picked when you fit corners"`.

  `test_crs_guard_blocks_every_route_to_a_bad_crs` must still pass unchanged after Task 2's edit.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** spec §4.4.
  - **CRS state:**
    - `_crs_auto` starts true for a new grid and false for an existing one.
    - Every write the dialog makes to `crs_widget` happens under a `_setting_crs` guard.
    - A `crsChanged` outside that guard is a hand pick. It clears `_crs_auto`, and converts the origin and azimuth from the previous CRS (kept in `_grid_crs`) unless the origin is (0, 0). If that conversion fails, put the previous CRS back and say so in `crs_hint`.
  - **Usability checks:** generalise `_crs_scale_error` to take the point to measure at. Add one helper that runs `_validate`'s three checks at a given location.
  - **The hint:** `crs_hint` shows `_validate`'s problem, if any, followed by the automatic choice's note, if any. The no-canvas case shows both. UTM reasons read `f"picked for you: the project CRS ({authid}) is in {QgsUnitTypes.toString(units)}"`, `f"... is off by {pct:.1f}% here"`, `"... has no authority code"`, or `"picked for you: the project has no CRS"`.
  - **Fit:** with `_crs_auto` set, Fit settles the CRS from the corners' centroid before transforming them. The Task 2 "metric CRS" refusal remains only for a CRS the user picked by hand.
- [ ] **Step 4: Run the file, both tiers, ruff and mypy.** All green.
- [ ] **Step 5: Commit and push.** `feat(plugin): the grid CRS picks itself — the site's, the project's, or a UTM zone; hand picks convert (#62)`

---

### Task 5: Pick on the map, with snapping (#63)

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/maptools/pick_tool.py`
- Delete: `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py`, and the three `test_digitise_tool_*` tests
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Test: `tests/qgis/test_pick_tool.py` (new) and `tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: Task 2's `pick_requested`, `pick_all_requested` and `set_corner`; Task 3's `pick_polygon_requested` and `set_polygon_feature`.
- Produces: `SNAP_TOLERANCE_PX = 12` and `class PickPointTool(QgsMapTool)`.
  - **Construction:** `__init__(self, canvas: QgsMapCanvas, mode: str = "point")`, where mode is `"point"` or `"polygon"`.
  - **Signals:**
    - `picked = pyqtSignal(QgsPointXY, str)`: the canvas-CRS point, with the label `f"{display name} · {layer name}"` or `"free click"`
    - `polygon_picked = pyqtSignal(object, int)`: the layer and its feature id
    - `skipped = pyqtSignal()`: right-click
    - `stopped = pyqtSignal()`: Esc
    - `cancelled = pyqtSignal()`: deactivated before `finish()`
  - **Methods and attributes:**
    - `snap(self, map_point: QgsPointXY) -> tuple[QgsPointXY, str]`
    - `snap_label: str`, which is the target under the cursor, or `""`
    - `finish(self) -> None`
    - `dispose(self) -> None`
- Produces, in `plugin.py`: `_start_pick(dialog: GridDialog, rows: list[int]) -> None`, `_start_pick_polygon(dialog: GridDialog) -> None`, and `_finish_with_pick_tool(tool: PickPointTool) -> None`. The last replaces `_finish_with_digitise_tool` and keeps its docstring's reasoning.

- [ ] **Step 1: Write the failing tool tests** in `test_pick_tool.py`. The canvas is `UTM16` over (0, 0)–(800, 600), so 1 px = 1 m. Layers:
  - a `Point?crs=EPSG:32616&field=name:string` memory layer with one feature `G4` at (400, 300), and display expression `"name"`;
  - a polygon layer with a vertex at (414, 300).

  Both are set with `canvas.setLayers`. The tests:
  - `test_a_click_near_a_point_snaps_to_it`: release at (408, 300) → `picked` gives (400, 300) and `"G4 · gps"`.
  - `test_a_click_beyond_the_radius_is_free`: (416, 300) → (416, 300) and `"free click"`.
  - `test_a_point_wins_over_a_nearer_vertex`: (410, 300). The point is 10 px away and the vertex 4 px → (400, 300).
  - `test_a_layer_not_on_the_canvas_is_never_snapped_to`: a second point layer, absent from `canvas.layers()`, at (405, 300) → still (400, 300).
  - `test_the_label_names_the_target_and_the_click_uses_it`: a move to (408, 300) → `snap_label == "G4 · gps"`; the release emits that same label.
  - `test_right_click_skips_and_esc_stops`: one emission each, and neither emits `picked`.
  - `test_switching_tools_cancels_once_unless_finished`: `cancelled` fires once, and does not fire after `finish()`.
  - `test_polygon_mode_emits_the_clicked_feature`.
  - `test_a_disposed_pick_tool_is_disposable_again` (port): the canvas scene's item count is back to its baseline after `dispose()`, twice.
- [ ] **Step 2: Write the failing plugin-flow tests** in `test_plugin_grid_dialog.py`. These are the ports Task 2 deleted. Each restates the old test's comment about why it exists.
  - `test_pick_flow_fills_the_row_and_restores_the_dialog`: click row 1's Pick.
    - The dialog is hidden, the active tool is a `PickPointTool`, and the message bar has one item containing `"+X"`.
    - A release fills row 1 with the snapped point. The dialog is visible again, there is no map tool, and the message bar is empty.
  - `test_pick_all_walks_the_corners_with_skip_and_stop`: click, right-click, click, then Esc → rows 0 and 2 filled, rows 1 and 3 empty, the dialog visible, the bar empty. The bar's text reads `"(1 of 4)"`, then `"(2 of 4)"`, and so on.
  - `test_pick_all_after_four_clicks_does_not_fit`: all rows filled, and the origin still (0, 0).
  - `test_single_pick_right_click_restores_the_dialog_untouched`.
  - `test_switching_map_tools_mid_pick_restores_the_dialog`.
  - `test_open_grid_dialog_releases_a_stranded_map_tool_on_close`.
  - `test_open_grid_dialog_releases_a_stranded_tool_on_accept_without_flashing_the_dialog`.
  - `test_open_grid_dialog_shows_the_existing_dialog_even_if_hidden_mid_pick`.
  - `test_unload_closes_a_dialog_hidden_mid_pick`.
  - `test_completed_picks_leave_no_canvas_items`, `test_an_aborted_pick_leaves_no_canvas_items` and `test_a_dialog_closed_mid_pick_leaves_no_canvas_items`. Each compares the scene item count before and after, and checks that the message bar is empty.
  - `test_a_pick_on_a_4326_canvas_lands_converted`: canvas `WGS84`, `corners_crs` `UTM16` → the row equals the transform of the clicked point within 1e-6 m.
  - `test_pick_polygon_on_map_selects_layer_and_feature`.
- [ ] **Step 3: Run them and see them fail.**
- [ ] **Step 4: Implement the tool** following spec §4.7.
  - **Snapping:** own a `QgsMapCanvasSnappingUtils(canvas)` with a `QgsSnappingConfig` that is enabled, `AllLayers`, `Vertex`, `SNAP_TOLERANCE_PX`, in `Pixels`. Snap with `snapToMap(point, filter)` (not relaxed, so it is synchronous), in two passes:
    1. a `QgsPointLocator.MatchFilter` subclass that accepts only `Qgis.GeometryType.Point` layers;
    2. only if the first pass found nothing, no filter.
  - **The marker and label:** a `QgsSnapIndicator` shows the match. The label is shown with `QToolTip` at the cursor, or with a canvas item that `dispose()` removes.
  - **Release:** use the match from the last move when the release is at the same pixel. Otherwise snap again.
  - **Polygon mode:** the topmost polygon feature under the click, searching only the polygon layers in `canvas.layers()` order.
- [ ] **Step 5: Implement the plugin flow.**
  - **Starting a pick:** `open_grid_dialog` connects the three dialog signals. `_start_pick` hides the dialog, sets the tool and pushes the message with `messageBar().createMessage` and `pushWidget`. The message texts are:
    - single: `f"Click the {role} corner. Right-click or Esc cancels."`
    - Pick all: `f"Pick corners: click the {role} corner ({k} of 4). Right-click skips it, Esc stops."`
    - polygon: `"Click the polygon to use. Right-click or Esc cancels."`
  - **During a pick:** each `picked` calls `dialog.set_corner(row, point, canvas.mapSettings().destinationCrs(), label)`.
  - **Ending a pick:** however a pick ends, `finally` unsets and finishes the tool, pops the message and shows the dialog. That covers the last corner, a single pick's right-click, Esc, `cancelled` and an exception.
  - **When the dialog finishes:** `finished`'s stranded-tool branch now checks for `PickPointTool` and also pops the message.
- [ ] **Step 6: Run both test files, both tiers, ruff and mypy.** All green.
- [ ] **Step 7: Commit and push.** `feat(plugin): pick corners and polygons on the map with snapping; Digitise on map removed (#63)`

---

### Task 6: The map overlay, and the documentation

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_overlay.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (own the overlay and feed it), `docs/guide/getting-started.md` ("Step 2: Place a grid"), `README.md` (line 37), `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt` (`about` only; the 0.1.0 changelog stays)
- Test: `tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: Task 2's `corners_changed`, `corner_point` and `corner_source`; Task 3's `chosen_polygon`; Task 4's `canvas` parameter and `_real_canvas` helper.
- Produces: `class GridOverlay`.
  - **Construction:** `__init__(self, canvas: QgsMapCanvas)`.
  - **Setters**, each taking points in the canvas CRS:
    - `set_corners(self, corners: Sequence[tuple[QgsPointXY, str] | None]) -> None`
    - `set_polygon(self, ring: Sequence[QgsPointXY] | None) -> None`
    - `set_grid(self, corners: Sequence[QgsPointXY] | None) -> None`, with the four corners in `CORNER_ROLES` order. The arrow runs from `corners[0]` toward `corners[3]`.
  - **Read-back for tests:** the attributes `corners`, `polygon` and `grid` hold the last values set.
  - **Teardown:** `dispose(self) -> None` is idempotent.
- Produces: `GridDialog.overlay: GridOverlay | None`, which is `None` without a canvas.
- **Tag text:** `f"{role} · {source}"` when the source is a polygon vertex (`v<i> <compass>`), else `role`.

- [ ] **Step 1: Write the failing tests**, each with a dialog given a `_real_canvas`.
  - `test_overlay_tags_each_filled_corner`: rows 0 and 2 typed → `overlay.corners` has tags `"origin"` and `"+X+Y"` at the transformed points, and `None` for the empty rows.
  - `test_overlay_tags_polygon_vertices_with_their_labels`: after Fill → `"origin · v0 SW"` and so on.
  - `test_the_chosen_polygon_is_outlined` (#28): `overlay.polygon` equals the feature's ring in the canvas CRS. Choosing no feature clears it.
  - `test_overlay_outline_follows_the_form`: with the form set to `SITE`, `overlay.grid` equals `SITE_CORNERS` in the canvas CRS within 1e-6. Changing `size_x` redraws it with no Fit.
  - `test_overlay_hides_the_grid_until_it_can_be_drawn`: a form origin of (0, 0), a size of 0 or an unusable grid CRS → `overlay.grid is None`.
  - `test_overlay_redraws_on_a_canvas_crs_change`.
  - `test_overlay_stays_while_the_dialog_is_hidden_mid_pick`.
  - `test_overlay_leaves_nothing_behind`, parametrized over OK, Cancel, a close mid-pick and `unload`: the scene item count returns to its baseline from before the dialog opened.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement the overlay** following spec §4.8.
  - **Drawing** is your choice: rubber bands plus a custom `QgsMapCanvasItem` for the tags, or one custom item for everything. Use magenta role tags with white text and a blue dashed grid outline, as in the mock-up.
  - **Feeding it:** the dialog creates the overlay when given a canvas. It calls the setters from one `_refresh_overlay` slot, connected to:
    - `corners_changed`
    - the origin, azimuth and size spin boxes
    - `crs_widget`, `corners_crs`, the feature picker
    - `canvas.destinationCrsChanged`
  - **Disposal:** `finished` disposes of the overlay. `open_grid_dialog`'s `clear_if_current` also disposes of it, through a local reference captured beside `dialog`, for a dialog destroyed without `finished`.
- [ ] **Step 4: Rewrite the documentation** following spec §7.
  - Rewrite "Step 2: Place a grid" around:
    - typing, Pick and Pick all (right-click skips, Esc stops);
    - Fill from a polygon, Rotate and Fit;
    - "off by", the size rule and **Use these**;
    - the automatic CRS and its hint.
  - Change the README sentence and `metadata.txt`'s `about` to "placed from corners typed, picked on the map or read from a polygon".
  - Check with `git grep -i digitis -- docs/guide README.md packages/nsgeo-qgis/nsgeo_qgis`. It should return only `metadata.txt`'s 0.1.0 changelog line.
- [ ] **Step 5: Run both tiers, ruff and mypy.** All green.
- [ ] **Step 6: Commit and push.** `feat(plugin): the map shows the corners' roles, the chosen polygon and the grid while the dialog is open; guide rewritten (#27, #28)`

---

## After the tasks (coordinator)

1. Run the final whole-branch review on opus, then one fix wave if needed.
2. **Human gate: build and walkthrough.** Deploy the branch to a new QGIS profile (ask the user which). Publish a walkthrough page on an Artifact with `db`. It uses the user's own GPS corner points and their colleague's grid polygons, first in a 4326 project and then in a UTM project, and covers:
   - typing, Pick, Pick all with a skip, and Fill
   - Rotate
   - the overlay's tags, outline and arrow
   - snapping onto GPS points from a zoomed-out view
   - Fit, rounding the size, and **Use these**
   - the automatic CRS and its hint, and a hand-picked CRS that stays put
   - the finished grid lining up with the GPS points and the overlay maps

   Mark checks that would lose data. The user's data is never committed.
3. Merge only on the user's go. The PR closes #27, #28, #62 and #63.
