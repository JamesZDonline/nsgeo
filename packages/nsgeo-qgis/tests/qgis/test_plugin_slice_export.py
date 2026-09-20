"""Export: the multi-band GeoTIFF, the .npz, and the survey record."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.project import ProjectError, load_site
from nsgeo.slices import load_cube
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_export import (
    ViewSettings,
    apply_temporal_properties,
    cube_record,
    export_slices,
    save_cube_npz,
    write_coverage,
)
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import Resolution, SourceChoice
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
    session.site.cubes["A__default"] = cube_record(
        session, engine.choice, engine.frame, engine.z, _VIEW, npz
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
