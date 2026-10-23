### Task 4: The site GeoTIFF

Spec §4.7: one file covering every included grid, with a band per slice, values as shown, and a
record of what was done. Built and tested against `SiteEngine` directly. Task 5 wires the button.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`

**Interfaces:**
- Consumes:
  - Task 3's `SiteEngine` (`site_z`, `lattice`, `slice_at`, `engine_for`, `ready_grids`);
  - Task 1's `window_on`;
  - M11's `plan_windows`, `window_times_ns`, `window_depths_m`, `band_time_range`, and
    `GeoTiffSliceWriter.OPTIONS`, which is reused, not copied.
- Produces:
  - `@dataclass(frozen=True) class SiteGridRecord: grid_id: str; preset: str; velocity: dict[str,
    Any] | None; gain: float; line_spacing_m: float; azimuth_deg: float; crs: str`. `velocity` is
    `VelocityModel.to_dict()`, so layered models survive.
  - `@dataclass(frozen=True) class SiteBand: window: SliceWindow; description: str; depths:
    dict[str, tuple[float, float] | None]`. `window` is on `site_z`. The description reads, for
    example, `12.0-16.0 ns · A 0.60-0.80 m · B 0.52-0.70 m · C no data`, derived from each grid's
    actual `window_on` result (trap 5).
  - `@dataclass(frozen=True) class SiteExportPlan: lattice: SiteLattice; site_z: ZAxis; bands:
    tuple[SiteBand, ...]; transform: str; method: str; cell_m: float; radius_spacings: float;
    grids: tuple[SiteGridRecord, ...]`.
  - `plan_site_export(site_engine, thickness_levels: int, step_levels: int, *, transform: str,
    method: str, radius_spacings: float, gains: Mapping[str, float], velocities: Mapping[str,
    VelocityModel | None]) -> SiteExportPlan`.
  - `export_site(site_engine, path: str | Path, thickness_levels: int, step_levels: int, *,
    transform, method, radius_spacings, gains, velocities, writer: SiteWriter | None = None) ->
    SiteExportPlan`. It pulls one `slice_at` per band and holds no cube, as M11 does.
  - `class GeoTiffSiteWriter` with `write(path, plan, slices: Iterable[SiteSlice]) -> None`.
  - `apply_site_temporal_properties(layer: QgsRasterLayer, plan: SiteExportPlan) -> None`.
  - `write_site_coverage(site_engine, path: str | Path, plan: SiteExportPlan) -> Path`. This
    writes `<stem>_coverage.tif` with one band: the composed coverage at the first band's window.
  - Metadata keys (Ruling 6). Values are strings, and the JSON is compact.
    - Dataset: `NSGEO_SITE_TRANSFORM`, `NSGEO_SITE_NORMALISATION`, `NSGEO_SITE_CELL_M`,
      `NSGEO_SITE_PIXEL_M`, `NSGEO_SITE_FILL_RADIUS_SPACINGS`, `NSGEO_SITE_Z_UNIT` (`"ns"`), and
      `NSGEO_SITE_GRIDS` (a JSON list of the `SiteGridRecord`s as objects).
    - Per band, as band metadata: `NSGEO_WINDOW_NS` (`"lo,hi"`), `NSGEO_GRID_DEPTHS_M` (a JSON
      object, id → `[lo, hi]` or `null`), and `NSGEO_GRID_FACTORS` (a JSON object, id → `[a, b]`
      or `null`).

- [ ] **Step 1: Write the failing tests** (reuse Task 3's `site3` fixture; move it to
  `tests/qgis/conftest.py` if needed):

```python
def test_the_file_lands_on_the_site_lattice(site3, tmp_path): ...        # geotransform, size, CRS
def test_there_is_a_band_per_planned_window(site3, tmp_path): ...
def test_each_band_is_exactly_what_slice_at_shows(site3, tmp_path): ...    # normalised, filled
def test_the_dataset_records_transform_method_and_every_grid(site3, tmp_path): ...
def test_each_band_records_every_grids_factors_and_depths(site3, tmp_path): ...
def test_an_absent_grid_is_null_in_the_band_metadata(site3, tmp_path): ...
def test_band_descriptions_name_each_grids_depths(site3, tmp_path): ...
def test_temporal_ranges_follow_the_ns_windows(site3, tmp_path): ...
def test_export_never_builds_a_resident_cube(site3, tmp_path): ...          # stub writer
def test_the_coverage_companion_is_written_beside_it(site3, tmp_path): ...
```

- [ ] **Step 2: Run them; all fail.**
- [ ] **Step 3: Implement.** Follow `slice_export.GeoTiffSliceWriter.write` for GDAL exception
  handling, the band count probe after the loop, and NaN nodata. Unlike it, there is no resample:
  `SiteSlice.array` is already on the lattice.
- [ ] **Step 4: Green.**
- [ ] **Step 5: Mutants.** Each must fail at least one test:
  1. per-band factors taken from the first band;
  2. depths derived from the requested window instead of `window_on`'s;
  3. an absent grid written as `[1, 0]` instead of `null`.
- [ ] **Step 6: Commit and push.** `feat(qgis): the site GeoTIFF, which records what was done`

---

