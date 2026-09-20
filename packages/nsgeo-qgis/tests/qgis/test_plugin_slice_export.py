"""Export: the multi-band GeoTIFF, the .npz, and the survey record."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.project import ProjectError, load_site
from nsgeo.slices import SliceWindow, load_cube
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_export import (
    GeoTiffSliceWriter,
    ViewSettings,
    apply_temporal_properties,
    cube_record,
    export_slices,
    recipe_from_record,
    save_cube_npz,
    write_coverage,
)
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import NO_TRANSFORM, Resolution, SourceChoice
from plugin_testing import synthetic_dzt
from qgis.core import QgsRasterLayer
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
    {"step": "gain_agc", "params": {}, "enabled": True},
]

# `cube_record`'s `view` argument: what the reader had on screen. Not
# exercised by any test's assertions on its own values, so one shared
# instance is enough.
_VIEW = ViewSettings(
    thickness_ns=5.0,
    step_ns=2.5,
    radius_m=0.75,
    palette="amp_heat",
    stretch="shared across the cube",
    coverage=False,
)


@pytest.fixture
def exportable_with_session(qgis_app, tmp_path):
    """A session with four parallel lines in one grid, an engine prepared
    over them, and a resolution set -- Task 2's `sourced` fixture, plus
    the resolution this task's tests all need."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    engine = SliceEngine(session)
    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000), "preparation did not finish"
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    yield engine, session
    engine.dispose()


@pytest.fixture
def exportable(exportable_with_session):
    engine, _session = exportable_with_session
    return engine


def test_the_band_count_is_the_specs_formula(exportable):
    """Spec 9.4: n_bands = (z_range - thickness) / step + 1. Halving the
    step doubles the file, and that is the moment the (thickness, step)
    pair stops being continuous exploration and becomes a finite set."""
    from nsgeo_qgis.slice_export import plan_export

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
    from nsgeo.slices import window_times_ns
    from qgis.core import Qgis

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
    record = cube_record(
        engine.session,
        engine.choice,
        engine.frame,
        engine.z,
        _VIEW,
        npz,
        line_keys=engine.provenance().line_keys,
    )
    assert record["array"] == "slices/A__default.npz"
    assert not Path(record["array"]).is_absolute()
    assert set(record) == {"grid_id", "preset", "transform", "cell", "array", "lines", "z", "view"}
    assert record["z"] == {"t0_ns": 2.0, "t1_ns": 30.0, "dz_ns": 0.5}
    assert record["lines"] == list(engine.provenance().line_keys)


def test_the_record_lines_are_what_was_actually_binned_not_what_was_asked_for(
    exportable_with_session,
):
    """Ruling AF (Task 6 fix round 1). `choice.line_keys` is the REQUEST;
    `engine.provenance().line_keys` is what the cube was actually built
    from. They differ the moment one requested key fails to prepare --
    here, a key naming no line at all -- and `cube_record`'s `lines`
    must be the latter: Task 7's restore path reads it to know which
    lines to re-bin, and a requested-but-never-prepared key in it would
    try to re-bin a line the cube never held."""
    engine, session = exportable_with_session
    requested = (*engine.choice.line_keys, "raw/does-not-exist.DZT")
    bad_choice = SourceChoice(
        grid_id=engine.choice.grid_id,
        preset=engine.choice.preset,
        transform=engine.choice.transform,
        line_keys=requested,
    )
    engine.set_source(bad_choice)
    assert engine.wait_for_preparation(20_000), "preparation did not finish"
    assert engine.choice.line_keys == requested  # the request, unpruned
    assert "raw/does-not-exist.DZT" not in engine.provenance().line_keys  # what actually bound

    npz = save_cube_npz(engine, session.root / "slices" / "A__partial.npz")
    record = cube_record(
        session,
        engine.choice,
        engine.frame,
        engine.z,
        _VIEW,
        npz,
        line_keys=engine.provenance().line_keys,
    )
    assert "raw/does-not-exist.DZT" not in record["lines"]
    assert record["lines"] == list(engine.provenance().line_keys)


def test_a_cube_written_outside_the_project_tree_is_refused(exportable_with_session, tmp_path):
    """The portability guarantee, in the direction that matters: a survey
    file pointing at /home/someone/scratch opens nowhere else."""
    engine, session = exportable_with_session
    outside = tmp_path.parent / "elsewhere" / "cube.npz"
    outside.parent.mkdir(exist_ok=True)
    npz = save_cube_npz(engine, outside)
    with pytest.raises(ProjectError, match="portable"):
        cube_record(
            session,
            engine.choice,
            engine.frame,
            engine.z,
            _VIEW,
            npz,
            line_keys=engine.provenance().line_keys,
        )


def test_the_record_survives_a_save_and_reload_of_the_survey(exportable_with_session, tmp_path):
    engine, session = exportable_with_session
    npz = save_cube_npz(engine, session.root / "slices" / "A__default.npz")
    session.site.cubes["A__default"] = cube_record(
        session,
        engine.choice,
        engine.frame,
        engine.z,
        _VIEW,
        npz,
        line_keys=engine.provenance().line_keys,
    )
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


class _RecordingWriter:
    """A stub `SliceWriter` (Ruling AG, Task 6 fix round 1): records every
    call instead of touching GDAL, so a test can observe the streaming
    property directly rather than only inferring it from `engine.has_cube`."""

    OPTIONS: list[str] = []

    def __init__(self) -> None:
        self.calls: list[tuple[object, object, list[np.ndarray]]] = []

    def write(self, path, plan, slices) -> None:  # noqa: ANN001 -- matches SliceWriter structurally
        self.calls.append((path, plan, list(slices)))


def test_export_slices_streams_through_a_substituted_writer(exportable, tmp_path):
    """Spec 9.6: a writer INTERFACE, not a function that knows GDAL --
    substituting one must be a plugged-in collaborator, not a two-call-
    site refactor (Ruling AG). This also doubles as the cheapest possible
    proof of the band-by-band streaming property: every array the
    generator yields lands in `slices`, one per `plan.bands`, in the
    same north-up-less grid-local shape `engine.slice_at` returns it in
    (the writer, not `export_slices`, is what calls `to_north_up`)."""
    engine = exportable
    writer = _RecordingWriter()
    path = tmp_path / "cube.tif"
    plan = export_slices(engine, path, 10, 5, None, radius_cells=0, writer=writer)
    assert len(writer.calls) == 1
    called_path, called_plan, slices = writer.calls[0]
    assert called_path == path
    assert called_plan is plan
    assert len(slices) == len(plan.bands)
    for array in slices:
        assert array.shape == (engine.frame.ny, engine.frame.nx)


def test_write_coverage_also_accepts_a_substituted_writer(exportable, tmp_path):
    engine = exportable
    writer = _RecordingWriter()
    write_coverage(engine, tmp_path / "coverage.tif", writer=writer)
    assert len(writer.calls) == 1
    _path, plan, slices = writer.calls[0]
    assert len(slices) == 1
    assert plan.radius_cells is None  # coverage is never filled


def test_the_geotiff_carries_fill_radius_and_azimuth_metadata(exportable, tmp_path):
    """Ruling AE (Task 6 fix round 1): the export is a lossy resample at
    ANY fill radius, radius 0 included -- a reader with only the `.tif`
    must be able to see that without this module's source in hand."""
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    export_slices(engine, path, 10, 5, None, radius_cells=3)
    ds = gdal.Open(str(path))
    try:
        tags = ds.GetMetadata()
        assert tags["NSGEO_FILL_RADIUS_CELLS"] == "3"
        assert tags["NSGEO_FRAME_AZIMUTH_DEG"] == str(engine.frame.azimuth)
    finally:
        ds = None


def test_write_raises_when_there_are_too_few_slices(exportable, tmp_path):
    """Important 3 (Task 6 fix round 1): `zip(plan.bands, slices)` is no
    longer `strict=True` (that keyword needs Python 3.10+, below this
    package's `>=3.9` floor), so this explicit count check is what still
    catches a caller handing over too few slices -- the same guarantee
    `strict=True` used to provide in this direction."""
    from nsgeo_qgis.slice_export import plan_export

    engine = exportable
    plan = plan_export(engine, thickness_levels=10, step_levels=5, velocity=None)
    too_few = [np.zeros((engine.frame.ny, engine.frame.nx), dtype=np.float32)]
    with pytest.raises(ValueError, match="expected .* slices"):
        GeoTiffSliceWriter().write(tmp_path / "short.tif", plan, too_few)


def test_write_raises_when_there_are_too_many_slices(exportable, tmp_path):
    """Task 6 fix round 2, Minor 1: `written != len(plan.bands)` alone
    can only ever detect too FEW slices -- `zip` stops consuming at the
    shorter iterable, so `written` never exceeds `len(plan.bands)` and a
    `slices` iterable with a surplus had that surplus silently dropped,
    with no exception. `strict=True` used to catch this direction too
    (`ValueError: zip() argument 2 is longer than argument 1`); the
    explicit `next(iterator, None)` probe after the loop is what restores
    it without `strict=`."""
    from nsgeo_qgis.slice_export import plan_export

    engine = exportable
    plan = plan_export(engine, thickness_levels=10, step_levels=5, velocity=None)
    shape = (engine.frame.ny, engine.frame.nx)
    too_many = [np.zeros(shape, dtype=np.float32) for _ in range(len(plan.bands) + 1)]
    with pytest.raises(ValueError, match="more slices than the plan's"):
        GeoTiffSliceWriter().write(tmp_path / "long.tif", plan, too_many)


def test_a_restored_recipe_reproduces_the_identical_slice(exportable_with_session):
    """The only definition of "reproducible" worth having.

    Not "the fields came back" -- a recipe that restores every field and
    still produces a different picture has failed at the one thing it is
    for. So: slice, save, wipe the engine, restore from the record alone,
    slice again, and demand the same numbers.

    This is also the test that catches a field quietly dropped from the
    record, which is otherwise invisible: a missing z range just means
    the restored cube silently uses whatever the dock happened to have.
    """
    engine, session = exportable_with_session
    window = SliceWindow(6, 18)
    before, coverage_before = engine.slice_at(window)

    npz = save_cube_npz(engine, session.root / "slices" / "A__first.npz")
    view = ViewSettings(
        thickness_ns=5.0,
        step_ns=2.5,
        radius_m=0.75,
        palette="amp_heat",
        stretch="shared",
        coverage=False,
    )
    record = cube_record(
        session,
        engine.choice,
        engine.frame,
        engine.z,
        view,
        npz,
        line_keys=engine.provenance().line_keys,
    )
    session.site.cubes["A__first"] = record
    session.save()

    # Everything the dock held is gone; the record is all that is left.
    engine.clear()
    assert not engine.is_prepared

    recipe = recipe_from_record(load_site(session.json_path).cubes["A__first"])
    engine.set_source(recipe.choice)
    assert engine.wait_for_preparation(20_000)
    engine.set_resolution(recipe.resolution)
    after, coverage_after = engine.slice_at(window)

    np.testing.assert_array_equal(coverage_before, coverage_after)
    np.testing.assert_array_equal(np.isfinite(before), np.isfinite(after))
    both = np.isfinite(before)
    np.testing.assert_allclose(before[both], after[both], rtol=1e-6, atol=1e-7)
    assert recipe.view == view


def test_a_recipe_restores_the_exact_line_set_not_the_whole_grid(exportable_with_session):
    """A cube built from 22 of 26 lines is not the same cube as one built
    from all 26, and the difference is invisible in a picture. The record
    carries the line keys for exactly this reason."""
    engine, session = exportable_with_session
    subset = tuple(session.keys())[:2]
    engine.set_source(SourceChoice("A", "p", "amp_envelope", subset))
    assert engine.wait_for_preparation(20_000)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    npz = save_cube_npz(engine, session.root / "slices" / "A__subset.npz")
    record = cube_record(
        session,
        engine.choice,
        engine.frame,
        engine.z,
        _VIEW,
        npz,
        line_keys=engine.provenance().line_keys,
    )

    recipe = recipe_from_record(record)
    assert recipe.choice.line_keys == subset
    assert len(recipe.choice.line_keys) < len(session.keys())


def test_a_record_written_by_an_older_build_still_loads(exportable_with_session):
    """The five-key record `Site.cubes`'s docstring described before this
    milestone must not become unreadable. `load_site` stores records
    opaquely, so an old one arrives here intact and the reader -- not the
    schema -- is what has to tolerate it."""
    old = {
        "grid_id": "A",
        "preset": "p",
        "transform": "amp_envelope",
        "cell": 0.25,
        "array": "slices/A__old.npz",
    }
    recipe = recipe_from_record(old)
    assert recipe.choice.grid_id == "A"
    assert recipe.choice.line_keys == ()  # unknown, not invented
    assert recipe.resolution is None  # unknown: the dock keeps what it has
    assert recipe.view is None


def test_a_recipe_with_no_transform_restores_the_bipolar_choice(exportable_with_session):
    """`cube_record` spells "no transform" as `"none"`; `SourceChoice`
    spells it `NO_TRANSFORM` (`""`). This is the one place the two
    spellings meet -- but neither round-trip test above ever restores a
    `NO_TRANSFORM` choice (both fixtures use "amp_envelope" throughout),
    so neither actually exercises this mapping. This one does."""
    engine, session = exportable_with_session
    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform=NO_TRANSFORM, line_keys=engine.choice.line_keys
        )
    )
    assert engine.wait_for_preparation(20_000)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    npz = save_cube_npz(engine, session.root / "slices" / "A__bipolar.npz")
    record = cube_record(
        session,
        engine.choice,
        engine.frame,
        engine.z,
        _VIEW,
        npz,
        line_keys=engine.provenance().line_keys,
    )
    assert record["transform"] == "none"

    recipe = recipe_from_record(record)
    assert recipe.choice.transform == NO_TRANSFORM


def test_a_record_with_a_broken_field_is_refused_by_name(exportable_with_session):
    bad = {
        "grid_id": "A",
        "preset": "p",
        "transform": "amp_envelope",
        "cell": 0.25,
        "array": "slices/x.npz",
        "lines": [],
        "view": {},
        "z": {"t0_ns": 30.0, "t1_ns": 2.0, "dz_ns": 0.5},  # reversed
    }
    with pytest.raises(ValueError, match="z"):
        recipe_from_record(bad)
