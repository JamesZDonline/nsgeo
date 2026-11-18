# M16 Plan B: Surfaces from Picks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** You select picks on the map and nsgeo builds a surface from them. The surface follows the reflection the picks name, and leaves holes where the radar saw nothing.
- It is stored with the site.
- It shows on the 2-D map, coloured by depth.
- It goes into the ParaView export.
- It is listed in a Surfaces panel, with its fit and whether it needs a rebuild.

**Architecture:**
- **The core** (numpy only) gets `nsgeo.slices.surface`: the builder of spec §5.3 and a mesher. It reads strength and squared amplitude from Plan A's `PreparedVolume`, prepared without the sideways blur.
- **The plugin** gets:
  - an authored, non-spatial `features` table in `site.nsgeo.gpkg`, plus membership through the picks' existing `feature_id` column (`layers.py`);
  - a pure module `surface_plan.py`: the feature record, the refusals and all wording;
  - `surfaces.py`: create, edit, delete, build and staleness. A build reuses the ParaView export's lines and its kept fill, at the grid's own 3-D resolution;
  - `surface_layers.py`: one QGIS mesh layer per built surface;
  - surfaces in the ParaView export and scene;
  - a Surfaces panel, a New surface dialog and a toolbar action.

  Building runs like Plan A's export: on the GUI thread, behind the window-modal `_export_progress` dialog, cancellable.

**Tech Stack:**
- Python 3.9+ and numpy (core).
- QGIS 3.40 / 3.44 / 4.2 with PyQt5 and PyQt6 (plugin), using MDAL's 2DM mesh and ASCII DAT formats.
- pytest.
- ParaView 6.2.1's `pvpython` for one optional test.

**Spec:** `docs/superpowers/specs/2026-11-11-nsgeo-m16-3d-design.md`. Read these parts first:
- §2.2, which holds the trial's recipe and its numbers;
- §4: decisions 4–6 and 8, and calls 1, 6–10, 12, 15 and 17;
- §5.3 and §5.4 (2-D map only), and §9 items 3–5.

The trial's builder is `~/nsgeo-m4-check/m16-paraview-trial/build_features.py`. It is outside the repo because it holds site coordinates. Read it, but never copy coordinates from it.

**Stacked on Plan A.** This branch, `nsgeo-m16-b`, starts from `nsgeo-m16` at 4a04ee4, which is not merged yet. It uses Plan A's:
- `PreparedVolume`, `prepare_volume` and `VolumeSettings`;
- `vtkxml`;
- `ParaViewExport` (its lines, fill cache and 3-D choice);
- `paraview_scene` and the scene templates.

## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** Below, `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - **Core and pure:** `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`. The whole tier takes about 22 minutes, so run single files while iterating.
- **Lint as CI does,** with line length 100:
  - `$R/.venv/bin/ruff check .`
  - `$R/.venv/bin/ruff format --check .`
  - `$R/.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py packages/nsgeo-qgis/nsgeo_qgis/surface_plan.py`

  `surface_plan.py` joins the mypy list. Add it to `.github/workflows/ci.yml` too.
- **The core uses numpy only.** It has a Python 3.9 floor: `from __future__ import annotations`, no `zip(strict=...)` and no `match`. No new dependency anywhere. The pure tier runs 3.9 in CI.
- **No ParaView code lives in a `.py` file inside `packages/`.** Scene code goes in the `.txt` templates in `packages/nsgeo-qgis/nsgeo_qgis/paraview/`.
- **Plugin boundary.** Arithmetic and message text live in the core, `surface_plan.py`, `slices_plan.py` or `paraview_scene.py`, never in widgets.
- **Qt.**
  - Use fully qualified enums.
  - Every Qt-invoked slot guards its body with `try/except Exception`.
  - Every new `pyqtSignal` is connected (`tests/pure/test_no_orphan_signals.py`).
  - Modal dialogs in tests go through `drive_dialog` / `answer_modal` (`tests/qgis/conftest.py`).
- **The site GeoPackage's rules hold for the new table** (`layers.py`, module docstring):
  - **Every write goes through a loaded layer's data provider,** never a second OGR handle.
  - **`picks` and `features` are authored:**
    - nothing ever drops or recreates either of them;
    - a CRS change leaves `features` alone;
    - feature edits go straight to the package, like picks, and never mark the site dirty.
- **Never two line preparations at once:** they segfault. A build gets its lines only through `ParaViewExport`, which already refuses while anything else prepares.
- **Surfaces never change what the Slices panel shows**, and nothing the Slices panel shows makes a surface stale (spec call 9).
- **No site coordinates, real survey files or site pictures are committed.** The parity check in Task 1 runs outside the repo.
- **Commits:**
  - every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - push each one to `origin nsgeo-m16-b` as you make it, with the sandbox turned off (it cannot resolve github.com).
- **Keep up with Plan A.** Before each task, run `git fetch && git merge origin/nsgeo-m16`; Plan A's walkthrough fixes land there. Once Plan A merges, merge `origin/main` instead.
- **Other open branches touch the same files:**
  - `nsgeo-grid-velocity`: where slices get their velocity (`session.py`, `slices_engine.py`, `ui/site_scope.py`). Surfaces take their velocity from the same place the export does (`ParaViewExport`), so that fix reaches both.
  - `nsgeo-own-colours`: `slices_dock.py`, `slice_layer.py`.

## Before Task 1 (coordinator)

- Symlink the real data into `packages/nsgeo-core/tests/data/local/` file by file. Do not link `README.md`, which is tracked. Give `with-dzg/` its own folder of per-file links.
- Record a baseline: the core and pure suites, then QGIS.
- `export NSGEO_PVPYTHON=/home/jameszd/Documents/Software/ParaView-6.2.1-MPI-Linux-Python3.12-x86_64/bin/pvpython`.

## Review Focus

These are the inputs the spec implies but none of its tests feed. Each is pinned by a test in the task named.

1. **No cell passes the strength test** (a faded patch, or a strength test set high). The build succeeds with an empty surface and says so. There is no map layer and no error, and the export still writes a valid file. *Task 1:* `test_a_surface_with_no_cell_passing_is_empty_not_an_error`. *Task 4:* `test_an_empty_surface_has_no_layer_and_exports_cleanly`.
2. **Picks edited in QGIS's own editing mode.**
   - Unsaved picks are refused, with a message saying to save the picks layer first.
   - A member deleted by hand makes its surface stale; it never causes an error.

   *Task 2:* `test_unsaved_picks_are_refused_until_saved`. *Task 3:* `test_a_member_deleted_by_hand_marks_the_surface_stale`.
3. **Cancelling a build, or rebuilding while the surface's layer has its files open** (Windows locks them). The previous build stays whole and on the map. *Task 3:* `test_a_cancelled_build_keeps_the_previous_one`. *Task 4:* `test_a_rebuild_writes_new_files_and_swaps_the_layer`.
4. **A pick above time zero, below the last level, or outside the grid's frame.** The pick is reported as on a hole, never fatal. *Task 1:* `test_a_pick_outside_the_depth_range_or_frame_is_reported_not_fatal`.
5. **Names with quotes, slashes, accents, surrounding spaces, or a name already taken.**
   - Names are trimmed and unique within the site.
   - Files are named by feature id, never by name.
   - The ParaView scene still opens.

   *Task 2:* `test_names_are_unique_trimmed_and_never_used_in_paths`. *Task 4:* `test_scene_opens_with_a_surface_whose_name_has_quotes`.

## Calls this plan makes (the spec left them to the builder, §11)

1. **Built geometry.** Every build is saved in `<site>/surfaces/<safe grid>/` as four files:
   - `<id>-<build>.npz`: the depth grid, the build's own record;
   - `<id>-<build>.2dm`: the mesh, in the grid's CRS, with Z = −depth;
   - `<id>-<build>.dat`: a "depth (m)" dataset, so the map's legend reads in positive metres;
   - `<id>.json`: the provenance and the fit.

   `<build>` is the first 8 characters of the build's key. A rebuild therefore never overwrites a file a map layer has open.

   A 2DM mesh draws in both 2-D and 3-D, so Plan C reuses it. A probe on 3.44 confirmed that QGIS loads a 2DM with an ASCII DAT, an empty one included.
2. **The `features` table** has these columns: `feature_id`, `name`, `grid_id`, `kind`, `settings_json` and `created`.
   - `SiteLayers` holds it as a layer, but never adds it to the project or the Layers panel. Surfaces are edited only through nsgeo.
   - `seq` on the picks stays null; a surface needs no order.
3. **Picks already in another surface move** when they are added to a new one. The New surface dialog says so before anything changes. *Superseded on 2026-11-13 by the user's decision (Ruling R14): a pick can belong to several surfaces; the dialog says which, and nothing moves.*
4. **Picks on cuts are refused** until Plan D.
5. **Building remembers the grid's 3-D choice,** as exporting does (`session.remember_volume`). After that, changing the Slices panel's transform or cell can never change a surface's inputs.
6. **"The volume parameters" in staleness are the wave period and the depth-balance window.** The sideways blur is left out, because a surface never uses it (call 17).
7. **Sub-sample peak:** a parabola through the peak and its two neighbours, clamped to half a step and to the window. It is used for the offset and for tracking alike.
8. **Outliers** are picks more than the window away from the surface, or on a hole.
9. **The feature list** is a Surfaces dock, tabbed with Slices, as in the mockup's option A, which the user chose (Task 5).

---

### Task 1: The surface builder (core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/surface.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/volume.py`: add `PreparedVolume.swing(j0, j1)`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py`, `packages/nsgeo-core/README.md`, `packages/nsgeo-core/tests/test_public_api.py`
- Modify: `packages/nsgeo-core/tests/real_lines.py`: move `_squared_volume` here from `test_slices_volume.py` as `squared_volume()`, cached the same way, and import it back there
- Test: `packages/nsgeo-core/tests/test_slices_surface.py`

**Interfaces:**
- Consumes: `PreparedVolume`, `prepare_volume`, `VolumeSettings` (`nsgeo.slices.volume`); `plan_curvature` (`nsgeo.slices.curvature`); `smooth` (`nsgeo.slices.smooth`).
- Produces, all exported from `nsgeo.slices`:
  - **Constants:**
    - `JOINS = ("min_curvature", "idw")`;
    - `HULL_MARGIN_M = 0.3`, `OFFSET_SEARCH_M = 0.05`, `JUMP_M = 0.06`, `JOIN_REACH_M = 2.0`;
    - `IDW_MIN_DISTANCE_M = 0.05`, with IDW power 2;
    - `FIT_CLOSE_M = 0.02`, `FIT_NEAR_M = 0.05`.
  - **`SurfaceSettings(join="min_curvature", window_m=0.02, strength=1.0, smoothing_m=0.0)`:**
    - frozen;
    - validated: `join` in `JOINS`, `window_m` finite and > 0, `strength` and `smoothing_m` finite and ≥ 0;
    - `to_dict()`, and `from_dict(doc)`, which lays valid fields over the defaults and ignores the rest, as `VolumeSettings.from_dict` does.
  - **`picks_span_an_area(x_m, y_m, *, tolerance_m=0.01) -> bool`:** False for fewer than 3 points, or when every point lies within `tolerance_m` of the line through the two farthest apart.
  - **`surface_volume(filled, z, velocity, cell, settings: VolumeSettings, *, slab_levels=64, progress=None) -> PreparedVolume`:** `prepare_volume` with `blur_m=0.0` (call 17).
  - **`PreparedVolume.swing(j0, j1) -> np.ndarray`:** the filled squared amplitude on the uniform depth axis, levels `j0..j1`, `(j1 - j0, ny, nx)` float32. It is interpolated between source levels as `_amplitude` does, and is NaN off `covered`.
  - **`build_surface(vol, x_m, y_m, depth_m, settings, *, max_levels=64) -> Surface`:**
    - `x_m` and `y_m` are frame-local metres; `depth_m` is on the volume's depth scale.
    - It raises ValueError when:
      - `vol.settings.blur_m != 0`;
      - the lengths differ;
      - a depth is not finite;
      - `picks_span_an_area` is False.
  - **`Surface`** (frozen):
    - `depth_m` (ny, nx) float32, NaN for a hole or outside the region;
    - `strength` (ny, nx) float32;
    - `guide_m` (ny, nx) float32, the joined picks, NaN outside the region;
    - `region` (ny, nx) bool;
    - `offset_m: float`: the median of swing minus pick, so > 0 means the picks sit above the swing;
    - `cell: float`;
    - `fit: SurfaceFit`.
  - **`SurfaceFit`** (frozen): `within_close`, `within_near`, `further`, `on_holes: int`, and `outliers: tuple[Outlier, ...]`, in input order.
  - **`Outlier(index: int, picked_m: float, surface_m: float | None)`:** `None` means the pick is on a hole.
  - **`surface_mesh(depth_m, cell, jump_m=JUMP_M) -> tuple[points (n, 3) float64 as x, y, depth; triangles (m, 3) int64; cells (n,) int64 flat ids]`**

**The algorithm** follows spec §5.3 and the trial's `build_features.py`. These are the details the signatures leave open:
- **A pick's cell** is `(floor(y / cell), floor(x / cell))`. A pick outside the frame takes no part in the guide or the offset, and the fit counts it on a hole.
- **The region** is the counter-clockwise convex hull of the in-frame picks, grown by `HULL_MARGIN_M`, intersected with `vol.covered`. A cell is inside when its signed distance to every hull edge is at least −0.3 m (the trial's `inside_hull`).
- **The guide:**
  - For `min_curvature`: the mean pick depth per cell, then `plan_curvature(populated, cell, JOIN_REACH_M).apply(values)`. Where that is NaN, the mean pick depth is used.
  - For `idw`: weights of `1 / max(distance, IDW_MIN_DISTANCE_M)**2` over every in-frame pick, at the cell centres.
- **The offset** is measured on the swing (squared amplitude). In each pick's own covered cell, take the levels within `OFFSET_SEARCH_M` of the pick, take the refined argmax, and subtract the pick depth. The offset is the median of these. A pick with no level in reach is left out, and with none at all the offset is 0.0.
- **Tracking, in each region cell:**
  1. The target is the guide plus the offset.
  2. Among the levels within `window_m` of the target, take the swing's argmax (NaN counts as −inf).
  3. Refine that depth, and clamp it to the target ± window.
  4. Keep the cell when `strength[k] >= settings.strength` at the integer level `k`; otherwise it is a hole. A cell with no level in its window is a hole.
- **The 3×3 median:** a `nanmedian` over the kept cells only, written only to kept cells. Then subtract the offset. Then, if `smoothing_m > 0`, apply `smooth(depth, cell, s, s)`.
- **Memory.** Read the volume in slabs of at most `max_levels` levels, covering only the depths the offsets and windows touch plus one level either side. Keep only the region's columns. Never hold a whole cube.
- **The fit** compares each pick with the surface in its cell: on a hole; within 2 cm; within 5 cm; or further. Outliers are picks on a hole or more than `window_m` away.
- **The mesh** has a vertex at every kept cell centre, `((ix + 0.5) * cell, (iy + 0.5) * cell, depth)`. Each quad gives two triangles, as the trial's `mesh`: (dy, dx) offsets (0,0),(0,1),(1,1) and (0,0),(1,1),(1,0). A triangle is dropped when a vertex is missing or its depth spread exceeds `jump_m`.

- [ ] **Step 1: Write the failing synthetic tests** in `test_slices_surface.py`. The fixture `_dipping()` has these parts:
  - **The frame:** 40 × 30 cells at 0.1 m, `ZAxis.from_range(0.0, 40.0, 0.1)`, and `VelocityModel.constant(0.1)`, so depth is 0.05 × t.
  - **The reflector:** squared amplitude of a Ricker wavelet with a 2.5 ns period, centred at depth `0.5 + 0.01 * x`, on a floor of 1e-4.
  - **A weak patch:** cells x 2.0–2.5 m, y 1.0–1.5 m, at 0.02 × the amplitude.
  - **An uncovered strip:** the last 3 columns, all NaN.

  The volume is `surface_volume(...)`. Picks sit 2 cm above the swing at 12 cells spread over x 0.5–3.5 m and y 0.5–2.5 m.

  The tests:
  - `test_settings_defaults_validation_and_round_trip`: the defaults are `("min_curvature", 0.02, 1.0, 0.0)`; `join="kriging"` raises; `from_dict({"window_m": -1, "strength": 2})` gives window 0.02 and strength 2.0.
  - `test_build_refuses_a_blurred_volume`: a `prepare_volume` with `blur_m=0.1` raises ValueError.
  - `test_fewer_than_three_or_collinear_picks_are_refused`: 2 picks raise, 5 picks on one line raise, and `picks_span_an_area` agrees.
  - `test_surface_follows_a_dipping_reflector_and_returns_to_the_picks`: `abs(offset_m - 0.02) <= 0.005`. Every kept cell outside the weak patch is within 0.005 m of `0.5 + 0.01 * x - 0.02`. `fit.within_close == 12`.
  - `test_weak_patch_is_a_hole_and_the_median_never_fills_it`: every cell of the patch is NaN. A single weak cell surrounded by kept cells also stays NaN.
  - `test_uncovered_cells_are_outside_the_region`
  - `test_tracking_never_leaves_its_window`: add a reflector 3× stronger, 4 cm below. The surface stays within `window_m + one depth step` of `guide_m` everywhere.
  - `test_refinement_finds_a_peak_between_levels`: centre the wavelet halfway between two levels. Kept depths are within 0.1 × the step of the truth.
  - `test_a_pick_outside_the_depth_range_or_frame_is_reported_not_fatal`: add one pick at depth −0.01, one 0.5 m below the last level and one at x = −1. The build succeeds, all three are outliers with `surface_m is None`, and the other picks are unchanged.
  - `test_a_surface_with_no_cell_passing_is_empty_not_an_error`: with `strength=1e9`, `depth_m` is all NaN, `on_holes == 12`, and `surface_mesh` returns 0 points and 0 triangles.
  - `test_mesh_never_joins_cells_more_than_6_cm_apart`: a hand-made 3×3 depth grid with one step of 0.07 m.
  - `test_smoothing_is_off_by_default_and_never_fills_holes`

- [ ] **Step 2: Write the failing real-data tests** (`@needs_real_files`). Use `squared_volume()` from `tests/real_lines.py`, made into a surface volume with `surface_volume`.

  The fixture `_reflector_picks(vol)`:
  1. Take the depth level below 0.3 m where the largest share of covered cells on the data rows (`y = 0.25 + 0.5 i`) have strength ≥ 1.5.
  2. Then, at 15 cells on those rows between x = 4 and x = 16 m, take the refined swing peak within ±0.05 m of that level.

  These 15 points are "picks on a real reflector".

  The tests:
  - `test_real_picks_on_a_reflector_land_within_2_cm`: every pick whose cell is kept is within 2 cm, and at least 12 of 15 are kept.
  - `test_real_holes_are_where_strength_fails`: every kept cell has `strength >= settings.strength`. Raising the test to 2.0 leaves no fewer holes.
  - `test_real_surface_never_leaves_its_window`: as in the synthetic test.
  - `test_real_one_ns_shift_is_recovered_as_the_offset`: shift every pick 0.0355 m up (1 ns at 0.071 m/ns). The offset grows by 0.0355 ± 0.005, and the kept depths at the pick cells move with the picks.
  - `test_real_pick_on_another_reflection_is_reported`: one pick moved 0.15 m deeper is listed in `fit.outliers`.
  - `test_real_joins_differ_as_described`:
    - the `min_curvature` guide equals the binned pick depth at every populated cell (±1e-6);
    - the `idw` guide's sum of squared second differences over the region exceeds the `min_curvature` guide's (it spikes at each pick).

- [ ] **Step 3: Run them and see them fail.** Run `test_slices_surface.py` with the core command. Expect `ImportError` on `nsgeo.slices.surface`.
- [ ] **Step 4: Implement** `surface.py` and `PreparedVolume.swing`. Update the exports, the core README tables and `EXPECTED_PUBLIC`.
- [ ] **Step 5: Run the tests, `test_slices_volume.py`, `test_public_api.py`, ruff and mypy.** All pass.
- [ ] **Step 6: The parity check on the trial's data.** Do not commit any of it. Write `~/nsgeo-m4-check/m16-paraview-trial/core_parity.py`:
  - **Input:** it loads `filled_hq.npy` (455 × 320 × 400, `t0 = -0.476` ns, `dz = 0.1` ns, 0.071 m/ns, 0.05 m cells) and the 88 bowl picks, exactly as `build_features.py` reads them.
  - **The build:** `build_surface` with `min_curvature`.
  - **The output:** the fit, the offset, and whether the south-west picks (lines 23–24) sit on holes.

  Its acceptance is spec §7: **at least 82 of 88 within 2 cm**, and the offset about 3.6 cm. If it misses, call 17 rules: change the recipe until it meets the trial's numbers, and record what changed in the report. Put the printed numbers in the report, not in the repo.
- [ ] **Step 7: Commit and push.** `feat(core): the surface builder from picks (M16 B)`.

---

### Task 2: The features table and membership

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/surface_plan.py` (pure: no qgis import)
- Create: `packages/nsgeo-qgis/nsgeo_qgis/surfaces.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `features_changed = pyqtSignal()`
- Modify: `.github/workflows/ci.yml`: mypy list
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_surface_plan.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surfaces_membership.py`. Build its site the way `test_plugin_layers.py` does: a real `SiteLayers` on a real package, with two grids and picks written through `write_pick`.

**Interfaces:**
- Consumes: `SurfaceSettings` and `picks_span_an_area` (Task 1); `SiteLayers.write_pick`, `_row_to_pick` and `_attr`; `session.grid_for_line` and `line_for_key`; `is_cut_key`.
- Produces:
  - **In `surface_plan.py`:**
    - `FeatureRecord(feature_id: str, name: str, grid_id: str, kind: str, settings: SurfaceSettings, created: str)`: frozen, with `to_row() -> dict[str, str]` and `from_row(row) -> FeatureRecord`. A bad `settings_json` reads as the defaults.
    - `KIND_SURFACE = "surface"`
    - `clean_name(text) -> str`: trims and collapses whitespace.
    - `name_refusal(name, taken: Iterable[str], own: str | None = None) -> str`: "" when the name is fine. Names compare case-folded; `own` is the record being renamed. Empty, taken, and over 80 characters are refused.
    - `selection_refusal(*, n: int, unsaved: int, on_cuts: int, grids: Collection[str], spans_area: bool) -> str`. Checks run in this order: none selected, unsaved, on cuts, two grids, fewer than 3 or in a straight line. The wording is the mockup's (`.lavish/surfaces.html`, "When the selection can't make a surface").
    - `move_note(moving: Mapping[str, int], n: int) -> str`: for example, "4 of them are in “Bowl”; they will move to this surface, and “Bowl” will need a rebuild." *(Superseded by R14: replaced by `also_note`, which only says the picks are also in another surface.)*
    - `remove_refusal(left: int) -> str`: refuses leaving fewer than 3.
    - `delete_question(name: str, n_picks: int) -> str`
  - **In `layers.py`:**
    - `FEATURES = "features"`, with the spec `[("feature_id","str"), ("name","str"), ("grid_id","str"), ("kind","str"), ("settings_json","str"), ("created","str")]`.
    - The table is created with `QgsWkbTypes.Type.NoGeometry` from `ensure_tables`, only when it is absent. It is never in `TABLES` and never rebuilt. Missing fields on an older table are added with `provider.addAttributes`.
    - `PickRow(fid: int, pick: Pick, point: tuple[float, float] | None)`: `point` is the row's map position in the package CRS.
    - `selected_pick_ids() -> list[int]`
    - `pick_rows(fids) -> list[PickRow]`
    - `members_by_feature() -> dict[str, list[PickRow]]`: one scan; a `feature_id` naming no record is ignored.
    - `set_pick_feature(fids, feature_id: str | None) -> None`: committed rows only, through `changeAttributeValues`; raises RuntimeError on failure.
    - `feature_records() -> list[FeatureRecord]`
    - `write_feature(record)`
    - `update_feature(feature_id, *, name=None, settings=None)`
    - `remove_feature(feature_id)`
  - **In `surfaces.py`, `Surfaces(session, layers, export_for: Callable[[], ParaViewExport] | None = None)`:** `export_for` is first used in Task 3, where the plugin passes a factory bound to the Slices dock.
    - `records() -> list[FeatureRecord]`
    - `check(fids, *, into: str | None = None) -> SelectionCheck(refusal: str, grid_id: str | None, moving: dict[str, int], n: int)`
    - `create(name, fids, settings=SurfaceSettings()) -> FeatureRecord`
    - `rename(feature_id, name)`
    - `set_settings(feature_id, settings)`
    - `add_picks(feature_id, fids)`
    - `remove_picks(feature_id, fids)`
    - `delete(feature_id)`
    - `members(feature_id) -> list[PickRow]`

    Each refused change raises ValueError with the `surface_plan` text. Each completed one emits `session.features_changed` after the write.
    - **Order of writes in `create`:** the row first, then the picks. If the picks fail, remove the row and re-raise.
    - **Order of writes in `delete`:** clear the picks first, then remove the row.

- [ ] **Step 1: Write the failing pure tests:**
  - `test_record_round_trips_and_bad_settings_read_as_defaults`
  - `test_names_are_trimmed_and_unique_case_folded`, covering `"  Bowl  "`, `"bowl"` against `"Bowl"`, renaming to its own name, `""`, and 81 characters.
  - `test_selection_refusals_come_in_order`
  - `test_move_note_names_each_surface_once`
- [ ] **Step 2: Write the failing QGIS tests:**
  - `test_the_features_table_is_created_once_and_survives_a_crs_change`: the table exists after `ensure_tables`. A row survives `replace_grid` with a new CRS (which rebuilds every spatial table), with its rows and fids unchanged. The table is not in the project's layers.
  - `test_a_package_without_the_features_table_gains_it_with_picks_intact`
  - `test_create_sets_feature_id_on_exactly_the_selected_picks`, and `seq` stays null.
  - `test_picks_already_in_a_surface_move_and_the_check_says_so`
  - `test_delete_clears_membership_and_keeps_every_pick`: the pick count and every row's time are unchanged.
  - `test_picks_from_two_grids_are_refused`
  - `test_fewer_than_three_or_collinear_picks_are_refused`
  - `test_picks_on_a_cut_are_refused`
  - `test_unsaved_picks_are_refused_until_saved`: add a pick through `startEditing` and `addFeature`, select it, and check that it is refused. After `commitChanges` it is accepted.
  - `test_removing_below_three_picks_is_refused`
  - `test_names_are_unique_trimmed_and_never_used_in_paths`: a name `Bowl "north" / é` is stored as typed (trimmed). Creating a second "bowl " is refused.
  - `test_a_feature_and_its_picks_survive_closing_without_save`: create, rename, close the site without Save site, reopen. Everything is as last edited, and `session.dirty` was never set by these edits.
  - `test_features_changed_follows_each_write`
- [ ] **Step 3: Run them and see them fail.**
- [ ] **Step 4: Implement** `surface_plan.py`, the `layers.py` additions, `features_changed`, and `surfaces.py` (membership only). `detach()` releases the features layer along with the others.
- [ ] **Step 5: Run the new files, `test_plugin_layers.py`, `test_plugin_session.py`, the pure tier and lint.** All pass.
- [ ] **Step 6: Commit and push.** `feat: surfaces' features table and pick membership (M16 B)`.

---

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

### Task 4: Surfaces on the map and in the ParaView export

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/surface_layers.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/paraview_export.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/paraview_scene.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/paraview/open_scene.py.txt`
  - `packages/nsgeo-qgis/nsgeo_qgis/paraview/README.md.txt`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surface_layers.py`, and extend `test_plugin_paraview_export.py` and `tests/pure/test_paraview_scene.py` (including its pvpython test).

**Interfaces:**
- Consumes: Task 3 (`Surfaces.records`, `state`, `built`, `sweep`), Task 1 (`surface_mesh`), Plan A (`write_poly_data`, `scene_record`, `ExportSummary`, `summary_rows`).
- Produces:
  - **`SurfaceLayers(session, layers, surfaces, project=None)`:**
    - **`sync()`:**
      - Makes one `QgsMeshLayer` per built surface with at least one cell: the `.2dm` through provider `"mdal"`, plus `addDatasets(.dat)`, with `setCrs` set to the grid's CRS.
      - The active scalar group is "depth (m)". Its colour ramp is inverted Turbo (shallow is warm, as in the ParaView scene), with min and max shared by every built surface of that grid. If the default style has no Turbo, use Spectral and say so in the report.
      - The layer is named by the record's name, plus " (stale)" when `state().stale`. It carries the custom properties `nsgeo/feature_id` and `nsgeo/build`.
      - The layers sit in a "Surfaces" group inside the site group, directly below `picks`.
      - When a build changes, the new layer replaces the old one in the same place. Only after that does it call `surfaces.sweep(grid)`.
      - A layer the user removed is not re-added until that surface builds again.
      - Calls coalesce through a zero-delay single-shot `QTimer`.
    - **`dispose()`** removes its layers and the group.
    - **What calls `sync`:** the plugin connects `features_changed`, `picks_changed`, `slice_sources_changed`, `lines_changed`, `grids_changed` and `presets_changed`, and calls it after every build.
  - **`ParaViewExport(session, dock, surfaces=None)`:** with `surfaces`, `run` also writes `features.vtp`, and every build of the grid is in it, stale ones included.
    - Its points are `(x, y, -depth * stretch)`, meshed with `surface_mesh` at the build's own cell.
    - Its arrays are `true_depth_m` (float32), `feature` (int32, the index into the record's `features`) and `stale` (uint8, per point).
    - `picks.vtp` gains `feature` (int32): the index of the pick's surface, or −1.
    - Without `surfaces`, or with no builds, it still writes a valid empty `features.vtp`.
  - **`paraview_scene`:**
    - `scene_record` requires a new key `features`: a list of `{index, name, stale, picks, within_2cm, on_holes}`.
    - `ExportSummary` gains `n_surfaces` and `n_stale_surfaces`, and `summary_rows` gains a "Surfaces" row, for example "3 (1 stale)".
    - `feature_label(name, stale) -> str` is `"Surface: <name>"`, plus `" (stale)"` when stale.
  - **The scene:** one `XMLPolyDataReader` for `features.vtp`. Then, per feature, a `Threshold` on `POINTS`/`feature` between `i` and `i`, registered under `feature_label`. Each one is hidden at first and coloured by `true_depth_m` with the shared depth colour map. Names reach the script only through `export.json`, never pasted into its code.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_built_surface_is_a_mesh_layer_coloured_by_depth`
  - `test_surfaces_of_one_grid_share_one_depth_range`
  - `test_a_stale_surface_is_labelled_and_keeps_its_last_build`
  - `test_a_rebuild_writes_new_files_and_swaps_the_layer`:
    - the new layer has the new `nsgeo/build`, and sits at the same tree row;
    - the old files are gone after `sync`;
    - if the old files cannot be deleted (patch `Path.unlink` to raise `PermissionError`), `sync` succeeds and the next `sweep` removes them.
  - `test_an_empty_surface_has_no_layer_and_exports_cleanly`
  - `test_deleting_a_surface_removes_its_layer_and_files`
  - `test_closing_the_site_removes_the_surface_layers`
  - `test_a_layer_removed_by_hand_returns_only_after_a_rebuild`
  - `test_the_export_writes_every_built_surface_with_its_stale_flag`: read it back with `tests/vtk_reader.py`.
  - `test_picks_vtp_names_each_picks_surface`
  - `test_scene_opens_with_a_surface_whose_name_has_quotes` (pvpython; skipped without `NSGEO_PVPYTHON`): a surface named `Bowl "north" / é`. The script runs, and the source `Surface: Bowl "north" / é` exists and is hidden.
  - Extend the summary-row and `scene_record` tests for `features`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Add a "Surfaces" paragraph to the export's `README.md.txt`: what each item is, and that a stale surface shows its last build.
- [ ] **Step 4: Run the new files, the ParaView export and scene tests (pvpython on), and lint.** All pass.
- [ ] **Step 5: Commit and push.** `feat: surfaces on the map and in the ParaView scene (M16 B)`.

---

### Task 5: The Surfaces panel, the New surface dialog, the toolbar action and the guide

**The mockup review is done** (spec call 15; `.lavish/surfaces.html`, 2026-11-13). The user chose:
- **layout A,** with the list and the details together in the panel;
- **every grid's surfaces listed,** with a Grid filter that defaults to All grids;
- **clicking an outlier** selects that pick on the map **and** opens its line in the Profile panel (`session.open_line(key)`), at the pick's trace.

Follow the mockup's wording for the dialog, the refusals, the fit rows and the delete question.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/surfaces_dock.py`, `packages/nsgeo-qgis/nsgeo_qgis/ui/new_surface_dialog.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
    - a toolbar action "Surface from picks…", enabled while a site is open;
    - the dock, tabbed with Slices in `_tabify_slices_dock`;
    - "Surfaces" in the Panels menu;
    - `Surfaces` and `SurfaceLayers` made when a site opens and disposed when it closes;
    - the build flow behind `_export_progress`, with `refining_paused`, as `export_paraview` does;
    - `ParaViewExport(..., surfaces=...)` in `export_paraview`.
  - `docs/guide/getting-started.md`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_surfaces_dock.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_new_surface_dialog.py`

**Interfaces:**
- Consumes: Tasks 2–4; `_export_progress`, `busy_cursor` and `refining_paused` from Plan A; `Surfaces.check` for the dialog's live refusal and move note.
- Produces:
  - **`NewSurfaceDialog(check: SelectionCheck, n_label: str, parent=None)`:**
    - Fields: a name box, and Settings folded with their values shown (join, window in cm, strength, smoothing in m).
    - Create and build is disabled while any refusal stands.
    - `name()` and `settings()` read the result.
    - Return in a spin box does not accept, using Plan A's event filter.
  - **`SurfacesDock(session, surfaces, parent=None)`:**
    - **Signals:** `new_requested`, `build_requested(list)`, `select_picks_requested(list)`.
    - **Widgets:**
      - a Grid filter;
      - a table (Name, Grid, Picks, Fit as within-2-cm/picks, a state column reading "stale" or "not built");
      - the buttons New from selected picks…, Rebuild, Rename… and Delete…;
      - a group for the selected surface: its stale reason, Select its picks, Add selected picks, Remove selected picks, Settings, the fit rows and the outlier list.
    - **Behaviour:**
      - Rebuild acts on every selected surface. The plugin groups the ids by grid and builds each group in turn, under one progress dialog.
      - Changing a setting saves it at once (`set_settings`), and the surface shows as stale.
      - Clicking an outlier selects that pick on the map, opens its line in the Profile panel and moves to the pick's trace. A pick whose line is no longer in the site is only selected.
      - It refreshes on the same signals as `SurfaceLayers`.
      - Its contents sit in a `QScrollArea(widgetResizable=True)`, and long sentences go in tooltips (the dock-size rule in the environment notes).

- [ ] **Step 1: Write the failing tests:**
  - `test_the_toolbar_action_opens_the_dialog_on_the_selected_picks`
  - `test_with_no_picks_selected_it_says_how_to_select`
  - `test_the_dialog_shows_the_refusal_and_disables_create`
  - `test_the_dialog_states_picks_that_will_move`
  - `test_return_in_a_spin_box_does_not_create`
  - `test_create_and_build_adds_the_surface_and_its_layer`
  - `test_the_panel_lists_surfaces_with_fit_and_state`
  - `test_changing_a_setting_marks_it_stale_and_rebuild_clears_it`
  - `test_clicking_an_outlier_selects_its_pick_and_opens_its_line`
  - `test_delete_asks_first_and_keeps_the_picks`
  - `test_rename_refuses_a_taken_name`
  - `test_the_panels_menu_lists_surfaces`
  - `test_the_export_includes_surfaces_from_the_plugin`
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** In the guide, add two things:
  - **"Making a surface from picks":** pick only where the reflection is clear, and the same part of the wave each time; select, build, read the fit, rebuild after changes.
  - **A line in "Where your data lives":** surfaces are saved as you go in `site.nsgeo.gpkg`, like picks; built surfaces and exports are regenerable files in the site folder.
- [ ] **Step 4: Run the whole QGIS tier, the pure and core tiers, lint and the zip build.** All pass.
- [ ] **Step 5: Commit and push.** `feat: the Surfaces panel and New surface (M16 B)`.

---

### Task 6: Final review, deploy, walkthrough

- [ ] **Step 1:** Run every suite and lint:
  - core, pure and all of QGIS;
  - ruff and mypy;
  - the zip build (`packages/nsgeo-qgis/scripts/build_zip.py`);
  - the pvpython tests, with `NSGEO_PVPYTHON` set.
- [ ] **Step 2:** Run a whole-branch review on the most capable model (`git diff origin/nsgeo-m16...HEAD`). Fix its findings in one wave, give the fixes one scoped re-review, re-run Step 1, and push.
- [ ] **Step 3: Deploy** to a new QGIS profile `ns_geo_m16b`: `cp -a` from `ns_geo_m16`, plus a `dev_link` to this worktree. Copy the walkthrough site with the sqlite backup API, to `~/nsgeo-m16b-walk/`. Probe that the branch's code loads.
- [ ] **Step 4 (human checkpoint): the walkthrough** on Sunnyside Grid 1, recorded on an Artifact page with a results database. It covers spec §9 walkthrough steps 2, 3, 5, and step 4's 2-D half (3-D is Plan C):
  1. Select the 88 bowl picks and build "Bowl".
     - The fit is at least 82 of 88 within 2 cm.
     - The south-west is a hole.
     - The offset is stated.
     - Record the build's time, once with the export's fill already kept and once without (spec §6).
  2. Switch the join to inverse distance, rebuild and compare. Switch it back.
  3. The surface shows on the map, coloured by depth, under the picks.
  4. Make "Higher line" and "Lower line", and judge whether their depth relationship reads.
  5. Move a pick between surfaces, and delete one surface. No pick is lost, and the moved-from surface shows as stale with its reason.
  6. Change the Slices panel's grid, cell and depth step. No surface goes stale. Change Grid 1's 3-D cell in the export dialog, and they all do.
  7. Export Grid 1 for ParaView. Each surface is listed and can be shown, stale ones labelled, coloured on the picks' depth scale.
  8. Close QGIS without Save site and reopen. The surfaces and their membership are as last edited.
- [ ] **Step 5:** Commit the walkthrough results and the decision record. Update the README roadmap (Plan B → Done at merge). The merge decision goes to the user. Plan A merges first.
