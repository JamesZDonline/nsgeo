### Task 6: Export — the multi-band GeoTIFF, the `.npz`, and the survey record

The milestone's last mile: what leaves the plugin and what a rebuild reads.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (two buttons)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (the two file dialogs)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py` (new)
- Test: `packages/nsgeo-core/tests/test_project.py` (append: the `cubes` record shape)

**Interfaces:**

- Produces:
  - `SliceBand(window: SliceWindow, description: str)`
  - `ExportPlan(frame, z, crs, bands: tuple[SliceBand, ...], provenance)`
  - `plan_export(engine, thickness_levels, step_levels, velocity) -> ExportPlan`
  - `GeoTiffSliceWriter` with `OPTIONS` and
    `write(path, plan, slices: Iterable[np.ndarray]) -> None`
  - `band_time_range(lo_ns, hi_ns) -> QgsDateTimeRange`
  - `apply_temporal_properties(layer, plan) -> None`
  - `export_slices(engine, path, thickness_levels, step_levels, velocity, radius_cells) -> ExportPlan`
  - `write_coverage(engine, path) -> None`
  - `save_cube_npz(engine, path) -> Path`
  - `ViewSettings(thickness_ns, step_ns, radius_m, palette, stretch, coverage)` with
    `to_dict()` / `from_dict()`
  - `cube_record(session, choice, frame, z, view, npz_path) -> dict[str, Any]`
  - `SlicesDock.save_button`, `SlicesDock.export_button`, signals
    `save_cube_requested = pyqtSignal()` and `export_requested = pyqtSignal()` (connected in
    `plugin.py` here)

---

- [ ] **Step 1: Write the failing export tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`. The fixture is Task 2's
`sourced` fixture, copied into this file (a prepared engine over four synthetic lines) plus a
resolution. The tests:

```python
def test_the_band_count_is_the_specs_formula(exportable):
    """Spec 9.4: n_bands = (z_range - thickness) / step + 1. Halving the
    step doubles the file, and that is the moment the (thickness, step)
    pair stops being continuous exploration and becomes a finite set."""
    engine = exportable
    plan = plan_export(engine, thickness_levels=10, step_levels=5, velocity=None)
    nz = engine.z.nz
    assert len(plan.bands) == (nz - 10) // 5 + 1


def test_every_band_describes_the_window_it_averages_in_both_units(exportable, tmp_path):
    """Spec 9.4: a reader opening the GeoTIFF in five years can see that
    band 7 is 15.0-20.0 ns and band 8 is 17.5-22.5 ns, and that they
    therefore share half their data. The description is the only place
    that survives outside this plugin."""
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    velocity = VelocityModel.constant(0.08)
    plan = export_slices(engine, path, 10, 5, velocity, radius_cells=2)
    ds = gdal.Open(str(path))
    try:
        assert ds.RasterCount == len(plan.bands)
        seventh = ds.GetRasterBand(7).GetDescription()
        assert "ns" in seventh and "m" in seventh
        eighth = ds.GetRasterBand(8).GetDescription()
        assert seventh != eighth
    finally:
        ds = None


def test_the_creation_options_are_the_measured_ones(exportable, tmp_path):
    """Spec 9.5: INTERLEAVE=BAND is the difference between a 230-band
    export being unusable and being free -- pixel interleaving forces a
    read of every band to reach one of them, which is precisely a slice
    viewer's access pattern. TILED=NO because tiling a raster barely
    larger than one tile pads it to 512x512 and wastes 2.9x."""
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    export_slices(engine, path, 10, 5, None, radius_cells=2)
    ds = gdal.Open(str(path))
    try:
        interleave = ds.GetMetadata("IMAGE_STRUCTURE").get("INTERLEAVE")
        assert interleave == "BAND"
        assert ds.GetRasterBand(1).GetBlockSize()[0] == ds.RasterXSize  # stripped, not tiled
        assert np.isnan(ds.GetRasterBand(1).GetNoDataValue())
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Float32
    finally:
        ds = None


def test_the_export_is_north_up_and_carries_the_frames_crs(exportable, tmp_path):
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    export_slices(engine, path, 10, 5, None, radius_cells=0)
    ds = gdal.Open(str(path))
    try:
        gt = ds.GetGeoTransform()
        assert gt[5] < 0.0 and gt[2] == 0.0 and gt[4] == 0.0
        assert "32616" in ds.GetProjection()
    finally:
        ds = None


def test_export_never_needs_a_resident_cube(exportable, tmp_path):
    """Spec 9.4: written band by band. A resident cube is a latency
    optimisation, never a capability (spec 7.4), and export is the
    operation most tempted to forget that."""
    engine = exportable
    engine.set_always_resident(False)
    assert engine.mode == "streaming"
    export_slices(engine, tmp_path / "cube.tif", 10, 5, None, radius_cells=0)
    assert not engine.has_cube, "export must not have built a cube behind the user's back"


def test_the_temporal_mapping_is_one_nanosecond_to_one_second(exportable, tmp_path):
    """Spec 9.5's named trap. ns -> ms pairs two small units and looks
    right, and silently collapses every band at native dz into the same
    millisecond: 0.2165 ns rounds to 0 ms, adjacent bands get identical
    ranges, and the Temporal Controller's slider does nothing."""
    engine = exportable
    path = tmp_path / "cube.tif"
    plan = export_slices(engine, path, 4, 1, None, radius_cells=0)
    layer = QgsRasterLayer(str(path), "cube", "gdal")
    apply_temporal_properties(layer, plan)
    props = layer.temporalProperties()
    assert props.mode() == Qgis.RasterTemporalMode.FixedRangePerBand
    assert props.isActive()
    ranges = props.fixedRangePerBand()
    assert len(ranges) == len(plan.bands)
    # Adjacent bands must be DISTINCT -- the whole point of 1 ns -> 1 s.
    assert ranges[1].begin() != ranges[2].begin()
    lo_ns, _ = window_times_ns(engine.z, plan.bands[0].window)
    epoch = QDateTime(QDate(1970, 1, 1), QTime(0, 0, 0), Qt.TimeSpec.UTC)
    assert ranges[1].begin() == epoch.addMSecs(int(round(lo_ns * 1000.0)))


def test_the_survey_record_keeps_the_cube_path_relative(exportable_with_session, tmp_path):
    """Trap 7, and the one M10 explicitly left for this milestone.
    `save_site` writes `site.cubes` VERBATIM and does not route `array`
    through `project.line_key`, which is what keeps every other path
    relative and inside the project tree. The first writer of a record is
    the one that has to do it."""
    engine, session = exportable_with_session
    npz = save_cube_npz(engine, session.root / "slices" / "A__default.npz")
    record = cube_record(engine.session, engine.choice, engine.frame, engine.z, _VIEW, npz)
    assert record["array"] == "slices/A__default.npz"
    assert not Path(record["array"]).is_absolute()
    assert set(record) == {"grid_id", "preset", "transform", "cell", "array", "lines", "z", "view"}
    assert record["z"] == {"t0_ns": 2.0, "t1_ns": 30.0, "dz_ns": 0.5}
    assert record["lines"] == list(engine.provenance().line_keys)


def test_a_cube_written_outside_the_project_tree_is_refused(exportable_with_session, tmp_path):
    """The portability guarantee, in the direction that matters: a survey
    file pointing at /home/someone/scratch opens nowhere else."""
    engine, session = exportable_with_session
    outside = tmp_path.parent / "elsewhere" / "cube.npz"
    outside.parent.mkdir(exist_ok=True)
    npz = save_cube_npz(engine, outside)
    with pytest.raises(ProjectError, match="portable"):
        cube_record(session, engine.choice, engine.frame, engine.z, _VIEW, npz)


def test_the_record_survives_a_save_and_reload_of_the_survey(exportable_with_session, tmp_path):
    engine, session = exportable_with_session
    npz = save_cube_npz(engine, session.root / "slices" / "A__default.npz")
    session.site.cubes["A__default"] = cube_record(session, engine.choice, engine.frame, engine.z, _VIEW, npz)
    session.save()
    reloaded = load_site(session.json_path)
    assert reloaded.cubes["A__default"]["array"] == "slices/A__default.npz"
    assert load_cube(session.root / reloaded.cubes["A__default"]["array"]).frame == engine.frame


def test_coverage_exports_as_a_companion_single_band_raster(exportable, tmp_path):
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "coverage.tif"
    write_coverage(engine, path)
    ds = gdal.Open(str(path))
    try:
        assert ds.RasterCount == 1
        counts = ds.GetRasterBand(1).ReadAsArray()
        assert np.nanmax(counts) >= 1
    finally:
        ds = None
```

Fixtures: build one `exportable_with_session` fixture returning `(engine, session)` and derive
`exportable` from it, rather than duplicating the four-line setup.

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement `slice_export.py`**

```python
"""What leaves the plugin: a multi-band GeoTIFF, an .npz, and a survey record.

A writer INTERFACE rather than a function that knows about GeoTIFF (spec
9.6). More than one raster model may eventually be wanted -- netCDF
through GDAL's multidimensional API is designed for and not built, for
archival and for readers using xarray -- so adding one later should be a
new implementation rather than a refactor.

Written BAND BY BAND. Spec 9.4 and 7.4 together: a resident cube is a
latency optimisation and never a capability, and export is the operation
most tempted to forget that. `export_slices` pulls one window at a time
from the engine in whatever residency it is already in, and never
promotes it.

Two things here are not incidental, and both were measured:

* `INTERLEAVE=BAND`. Pixel interleaving -- GDAL's default -- forces a read
  of every band to reach one of them, which is exactly a slice viewer's
  access pattern: 105.7 ms to read one band of 95 against 0.45 ms. This
  single option is the difference between a 230-band export being
  unusable and being free.
* `1 ns -> 1 s`, from a 1970-01-01T00:00:00Z epoch, for the temporal axis.
  The obvious choice, ns -> ms, pairs two small units and looks right: at
  the native dz of 0.2165 ns it rounds to 0 ms, every band collapses into
  the same millisecond, and the failure is a layer whose Temporal
  Controller slider does nothing. The band DESCRIPTIONS carry the true ns
  and m ranges regardless, so they remain the authority and the temporal
  encoding is only navigation.
"""
```

Concrete requirements:

- `plan_export(engine, thickness_levels, step_levels, velocity)` builds `SliceBand`s from
  `plan_windows(engine.z, thickness_levels, step_levels)`, each description
  `window_label(engine.z, window, velocity)` — the same function the dock's readout uses, so the
  file and the screen cannot disagree.
- `GeoTiffSliceWriter.OPTIONS = ["INTERLEAVE=BAND", "TILED=NO", "COMPRESS=DEFLATE",
  "PREDICTOR=3", "BIGTIFF=IF_SAFER"]` — spec 9.5, verbatim, and **not** the live layer's set
  (plan Ruling 3).
- `write(path, plan, slices)` creates the dataset once from the first slice's north-up shape,
  then writes each band, sets its `NoDataValue(nan)` and its `Description`, and releases the
  dataset (`ds = None`) before returning. Every array goes through `to_north_up` first, and every
  band must therefore land on the same grid — assert that, because a mismatch would otherwise
  write a truncated band silently.
- `export_slices(engine, path, thickness_levels, step_levels, velocity, radius_cells)` is the
  caller: it plans, then for each band pulls `engine.slice_at(window)`, applies
  `fill(values, coverage, radius_cells)`, and hands it to the writer as a generator — so at most
  one slice is resident at a time. Returns the plan.
- `band_time_range(lo_ns, hi_ns)` returns a `QgsDateTimeRange` from
  `QDateTime(QDate(1970, 1, 1), QTime(0, 0, 0), Qt.TimeSpec.UTC).addMSecs(round(ns * 1000))`.
- `apply_temporal_properties(layer, plan)` sets `setFixedRangePerBand({i + 1: range})`, then
  `setMode(Qgis.RasterTemporalMode.FixedRangePerBand)`, then `setIsActive(True)` — in that
  order, and it needs QGIS 3.38+, which `metadata.txt`'s `qgisMinimumVersion=3.40` already
  guarantees, so there is no fallback path to write.
- `write_coverage(engine, path)` writes a single-band north-up raster of
  `engine.slice_at(window)[1]` for the full axis, with the same options.
- `save_cube_npz(engine, path)` calls `save_cube(engine.cube(), path)` and returns the path
  numpy actually wrote — `np.savez_compressed` APPENDS `.npz`, and M10's `store._npz_path` is a
  fixed point of that rule, so return `_npz_path(path)` rather than `path`.
- `cube_record(session, choice, frame, npz_path)`:

```python
def cube_record(
    session: Any,
    choice: SourceChoice,
    frame: CubeFrame,
    z: ZAxis,
    view: ViewSettings,
    npz_path: Path,
) -> dict[str, Any]:
    """One `Site.cubes` record: the whole recipe, with its path made portable.

    `save_site` writes `site.cubes` VERBATIM -- it does NOT route a
    record's `array` through `project.line_key`, which is what keeps every
    other path in a survey file relative and inside the project tree, and
    what refuses an absolute one. M10's `Site.cubes` docstring records
    that gap and says explicitly that routing it is M11's job, to be done
    by whoever writes the first real record. This is that writer.

    Raises ProjectError for a path outside the project directory, which is
    the behaviour worth having: a survey file pointing at somebody's
    scratch directory opens nowhere else, and it would round-trip through
    save and load without complaint.
    """
    root = Path(session.json_path).parent.resolve()
    return {
        # --- what the cube IS: change any of these and the array changes ---
        "grid_id": choice.grid_id,
        "preset": choice.preset,
        "transform": choice.transform or "none",
        "cell": float(frame.cell),
        "lines": list(choice.line_keys),
        "z": {"t0_ns": z.t0_ns, "t1_ns": z.t_end_ns, "dz_ns": z.dz_ns},
        "array": line_key(npz_path, root),
        # --- how it was BEING READ: changes nothing in the array ---
        "view": view.to_dict(),
    }
```

The first five keys are the ones `Site.cubes`'s docstring already declares normative, unchanged
and in place; `lines`, `z` and `view` extend it. **Do not bump `SCHEMA_VERSION`** — `load_site`
compares `version != SCHEMA_VERSION` exactly, so bumping would make every existing survey file
fail to load outright (M10 final review, Important 6). No bump is needed: `load_site` checks only
that `cubes` is a dict and then stores each record opaquely (`project.py:264-269`), so added keys
round-trip with no schema change in either direction. Update the `Site.cubes` docstring in
`model/survey.py` to describe the full shape, and delete its "routing `array` through `line_key`
is M11's job" note, which this task discharges.

The split between the two halves is the useful part and is worth keeping legible: everything
above `view` is what the `.npz` was binned from, so two records agreeing there name the same
array; `view` is what the reader had on screen, which changes no pixel in the cube.

- [ ] **Step 4: Add the two buttons and the two dialogs**

In `slices_dock.py`, below `status_label` (spec 9.2 puts the status line *above* the export
buttons): `save_button = QPushButton("Save cube…")` and
`export_button = QPushButton("Export GeoTIFF…")`, each connected with a lambda that drops
`clicked`'s `bool` and emits `save_cube_requested` / `export_requested`. Both disabled unless
`engine.is_prepared`.

In `plugin.py`, connect both to guarded handlers that use `QFileDialog.getSaveFileName`
(defaulting into `session.root / "slices"`), then call `save_cube_npz` + `cube_record` +
`session.site.cubes[...] = record` (the id being the `<grid_id>__<name>` the user chose) +
`session._set_dirty(True)` — or `export_slices` +
`apply_temporal_properties` + add the result to `layers.group` as a `QgsRasterLayer`. Report
every failure through `self.message(...)`; the tests drive the dialogs with the `answer_modal`
fixture, which is the only sanctioned way past the conftest's modal guard.

- [ ] **Step 5: Add the core-side record test**

Append to `packages/nsgeo-core/tests/test_project.py` a test that a `cubes` record with the five
keys round-trips through `save_site`/`load_site` unchanged, and that a record whose `array` is
absolute still round-trips **verbatim** — pinning that `save_site` does not sanitise it, which is
precisely why `cube_record` must.

- [ ] **Step 6: Verify and prove discrimination**

Mutants:

1. `OPTIONS` → drop `INTERLEAVE=BAND`. Expect `test_the_creation_options_are_the_measured_ones`
   to FAIL. Also time reading one band of a 19-band file both ways and record both numbers — the
   option's justification is a measurement, and the report should carry one.
2. `band_time_range` → `addMSecs(round(ns))` (the ns → ms trap). Expect
   `test_the_temporal_mapping_is_one_nanosecond_to_one_second` to FAIL on the
   adjacent-bands-distinct assertion. Confirm it fails at the *native* dz of 0.2165 ns as well as
   at the test's dz.
3. `cube_record` → `"array": str(npz_path)`. Expect
   `test_the_survey_record_keeps_the_cube_path_relative` and
   `test_a_cube_written_outside_the_project_tree_is_refused` to FAIL.
4. `export_slices` → call `engine.cube()` and slice it. Expect
   `test_export_never_needs_a_resident_cube` to FAIL.

- [ ] **Step 7: Full verification, commit, push**

Run all four test commands. Then:

```bash
git add packages/nsgeo-qgis packages/nsgeo-core/tests/test_project.py
git commit -m "feat(slices): multi-band GeoTIFF export, the .npz, and the survey record

Band by band, so export never needs a resident cube. INTERLEAVE=BAND and
1 ns -> 1 s are both measured choices, not defaults. The cubes record
routes its array through project.line_key, which M10 left for the first
writer of a record.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

---

