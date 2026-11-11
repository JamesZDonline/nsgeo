### Task 4: A whole-site limit, a coarser preview past it, and an export that refuses the preview

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`. Add `SITE_MAX_PIXELS` beside
  `MAX_FRAME_CELLS` (~337), and add `preview_note(...)`, `site_export_refusal(...)` and
  `name_list(...)`.
- Modify: `packages/nsgeo-core/src/nsgeo/slices/site.py`. Add `fitting_lattice(...)` and
  `stretching_grids(...)`, and export them from `__init__.py`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`:
  - `_rebuild_geometry` (~643) never refuses for size;
  - new properties `full_lattice`, `is_preview`, `preview_note` and `export_refusal`;
  - a `max_pixels` attribute, defaulting to `SITE_MAX_PIXELS`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`: `plan_site_export` (~116) raises
  `RuntimeError(site_engine.export_refusal)` when it is set, before planning anything.
- Test: `packages/nsgeo-core/tests/test_slices_site.py`,
  `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py` and
  `packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`.

**Interfaces:**
- Consumes: Task 3's site lattice at the cell.
- Produces:
  - Core:
    - `fitting_lattice(extents: Sequence[tuple[float, float, float, float]], cell: float, crs:
      str, max_pixels: int) -> SiteLattice`: `SiteLattice.covering` at `cell * 2**k` for the
      smallest `k >= 0` whose `n_pixels <= max_pixels`.
    - `stretching_grids(extents: Mapping[str, tuple[float, float, float, float]], pixel: float,
      crs: str, *, most: int = 3) -> list[str]`: the grid ids whose omission alone cuts the
      covering lattice's pixel count by at least 10%, largest cut first, at most `most`. Empty for
      a single grid.
  - Plugin (`slices_plan.py`, pure):
    - `SITE_MAX_PIXELS: int` (set in Step 5).
    - `name_list(names: Sequence[str]) -> str`: `"A"`, `"A and B"`, `"A, B and C"`.
    - `preview_note(pitch: float, cell: float, width_m: float, height_m: float, stretching:
      Sequence[str]) -> str`. Exact copy:
      `f"Preview at {pitch:g} m pixels: the grids are at {cell:g} m, but the area around them ({width_m:.0f} × {height_m:.0f} m) is too big to draw at full detail."`,
      then, when `stretching` is non-empty, `f" Leaving out {name_list(stretching)} would shrink it most."`
    - `site_export_refusal(cell: float, width_m: float, height_m: float, stretching:
      Sequence[str]) -> str`. Exact copy:
      `f"The site can't be exported at full detail yet: the area around the included grids ({width_m:.0f} × {height_m:.0f} m) is too big at a {cell:g} m cell. Choose a coarser cell"`,
      then `f", or leave out {name_list(stretching)}"` when non-empty, then `"."`.
  - `SiteEngine`:
    - `full_lattice: SiteLattice | None`, the lattice at the cell;
    - `lattice: SiteLattice | None`, the one drawn, possibly coarser;
    - `is_preview: bool`;
    - `preview_note: str | None`;
    - `export_refusal: str | None`, set exactly when `is_preview`.
    - `width_m`/`height_m` are `full_lattice.width * full_lattice.pixel` and the same for the
      height. `stretching` comes from the ready grids' extents in the site CRS (`_extent_in`).

- [ ] **Step 1: Write the failing tests.**
  - Core: `test_fitting_lattice_doubles_the_pitch_until_it_fits`, where 3 × 3 m at 0.1 m with
    `max_pixels=300` gives 0.2 m;
    `test_fitting_lattice_keeps_the_cell_when_it_fits`;
    `test_stretching_grids_names_the_outlier_first`, three abutting grids plus one 200 m away, so
    the outlier is named first, alone;
    `test_stretching_grids_is_empty_for_one_grid`.
  - Pure: exact-copy tests for `preview_note`, `site_export_refusal` and `name_list` (one, two and
    three names).
  - QGIS:
    - `test_grids_too_far_apart_draw_a_coarser_preview_and_say_why` replaces the refusal test. C
      at (5000, 5000); `site.max_pixels` lowered so the cell does not fit. Then
      `set_resolution(RES)` does not raise; `site.is_preview`; `site.lattice.pixel ==
      2**k * RES.cell` with `k >= 1`; `site.full_lattice.pixel == RES.cell`; `site.preview_note`
      contains `"Leaving out C"`; and `slice_at` returns an array on `site.lattice`.
    - `test_leaving_the_outlier_out_returns_to_full_detail`.
    - `test_a_site_that_fits_is_not_a_preview`: `site.preview_note is None` and
      `site.export_refusal is None`.
    - In `test_plugin_site_export.py`, `test_exporting_a_preview_site_refuses_and_writes_nothing`:
      `export_site` raises `RuntimeError` matching `"can't be exported at full detail"`, and the
      target path does not exist.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.** `_rebuild_geometry` builds `full_lattice` at the cell. If its
  `n_pixels > self.max_pixels`, it draws `fitting_lattice(...)` and sets the note and refusal;
  otherwise `lattice = full_lattice` and both are None. Gathers and seams follow `lattice` as today.
  Remove the old `MAX_FRAME_CELLS` refusal for the lattice and its message. The per-grid frame cap
  is untouched.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Measure, then set `SITE_MAX_PIXELS`.** Extend `bench_site.py` with
  `--lattice-scale N`, which spaces the ten grids out so the lattice reaches a given pixel count.
  Measure, at about 4, 8, 12, 16 and 24 M pixels at the cell, with kriging and no smoothing:
  - the median time of one `slice_at` compose;
  - the peak transient memory of the compose, with `tracemalloc` on `compose_footprints`.

  Set `SITE_MAX_PIXELS` to the largest of those sizes where the compose takes ≤ 250 ms and
  transient memory is ≤ 400 MB, capped at 16_000_000. Write the table and the choice in the
  constant's comment. If 16 M fails both, say so in the report rather than tune further.
- [ ] **Step 6: Run** `test_slices_site.py`, `test_pure_slices_plan.py`,
  `test_plugin_site_engine.py`, `test_plugin_site_export.py` and `test_plugin_site_scope.py`, plus
  lint. All pass.
- [ ] **Step 7: Commit**: `feat(site): its own pixel limit, a coarser preview past it, and an export that refuses the preview`.

---

