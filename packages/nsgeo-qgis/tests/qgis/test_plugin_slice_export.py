"""Export: the multi-band GeoTIFF, the .npz, and the survey record."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.project import ProjectError, load_site
from nsgeo.render import PercentileClip
from nsgeo.slices import METHODS, SiteLattice, SliceWindow, ZAxis, limit_over_slices, load_cube
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.export_pipeline import ExportBand, ExportCancelled, run_export
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_export import (
    GeoTiffSliceWriter,
    ViewSettings,
    apply_temporal_properties,
    build_overviews,
    commit_partial,
    creation_options,
    cube_record,
    discard_partial,
    grid_export_job,
    partial_path,
    recipe_from_record,
    save_cube_npz,
)
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import NO_TRANSFORM, Resolution, SliceFinish, SourceChoice
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
# "No interpolation, no smoothing": the slice as binned.
NONE = SliceFinish(method="none")

_VIEW = ViewSettings(
    thickness_ns=5.0,
    step_ns=2.5,
    radius_m=0.75,
    palette="amp_heat",
    stretch="shared across the cube",
    coverage=False,
)


def _write(job, path, coverage_to=None):
    """The task's work, synchronously: the bands of the snapshot into the writer."""
    writer, clip = GeoTiffSliceWriter(), PercentileClip()

    def bands(spec):
        return run_export(spec, should_stop=lambda: False, progress=lambda *a: None)

    writer.write_bands(path, job.plan, bands(job.spec), clip=clip)
    if coverage_to is not None:
        writer.write_bands(coverage_to, job.coverage_plan, bands(job.coverage_spec), clip=clip)


def export_slices(
    engine, path, thickness, step, velocity, finish, *, cell=None, pixel=None, coverage_to=None
):
    """Plan, snapshot and write a This-grid file (default: the live cell and pixel)."""
    cell = engine.frame.cell if cell is None else cell
    pixel = cell if pixel is None else pixel
    job = grid_export_job(
        engine, thickness, step, velocity, finish, cell, pixel, coverage=coverage_to is not None
    )
    _write(job, path, coverage_to)
    return job.plan


def write_coverage(engine, path):
    """The counts companion alone, as the task would write it."""
    cell = engine.frame.cell
    job = grid_export_job(engine, 10, 5, None, SliceFinish(), cell, cell, coverage=True)
    GeoTiffSliceWriter().write_bands(
        path,
        job.coverage_plan,
        run_export(job.coverage_spec, should_stop=lambda: False, progress=lambda *a: None),
        clip=PercentileClip(),
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
    plan = plan_export(
        engine,
        thickness_levels=10,
        step_levels=5,
        velocity=None,
        cell=engine.frame.cell,
        pixel=engine.frame.cell,
    )
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
    plan = export_slices(engine, path, 10, 5, velocity, SliceFinish())
    ds = gdal.Open(str(path))
    try:
        assert ds.RasterCount == len(plan.bands)
        seventh = ds.GetRasterBand(7).GetDescription()
        assert "ns" in seventh and "m" in seventh
        eighth = ds.GetRasterBand(8).GetDescription()
        assert seventh != eighth
    finally:
        ds.Close()


def test_the_creation_options_are_the_measured_ones(exportable, tmp_path):
    """Spec 9.5: INTERLEAVE=BAND is the difference between a 230-band export being
    unusable and being free (pixel interleaving reads every band to reach one).
    Tiling is a ruling with two regimes: 256-pixel tiles only when BOTH sides are
    at least 1024 pixels; below that, strips. The measured 2.9x waste came from
    512-pixel tiles on a raster barely larger than one tile."""
    from osgeo import gdal

    big = creation_options(1024, 2048)
    assert "TILED=YES" in big and "BLOCKXSIZE=256" in big and "BLOCKYSIZE=256" in big
    for options in (big, creation_options(300, 300)):
        assert "INTERLEAVE=BAND" in options and "COMPRESS=DEFLATE" in options
        assert "PREDICTOR=3" in options and "BIGTIFF=IF_SAFER" in options
    for w, h in ((1023, 4000), (4000, 1023), (300, 300)):
        small = creation_options(w, h)
        assert "TILED=NO" in small
        assert not any(o.startswith("BLOCK") for o in small)

    path = tmp_path / "cube.tif"
    export_slices(exportable, path, 10, 5, None, SliceFinish())
    ds = gdal.Open(str(path))
    try:
        assert ds.GetMetadata("IMAGE_STRUCTURE").get("INTERLEAVE") == "BAND"
        assert ds.GetRasterBand(1).GetBlockSize()[0] == ds.RasterXSize  # stripped, not tiled
        assert np.isnan(ds.GetRasterBand(1).GetNoDataValue())
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Float32
    finally:
        ds.Close()


def test_the_export_is_north_up_and_carries_the_frames_crs(exportable, tmp_path):
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    export_slices(engine, path, 10, 5, None, NONE)
    ds = gdal.Open(str(path))
    try:
        gt = ds.GetGeoTransform()
        assert gt[5] < 0.0 and gt[2] == 0.0 and gt[4] == 0.0
        assert "32616" in ds.GetProjection()
    finally:
        ds.Close()


def test_export_never_needs_a_resident_cube(exportable, tmp_path):
    """Spec 9.4: written band by band. A resident cube is a latency
    optimisation, never a capability (spec 7.4), and export is the
    operation most tempted to forget that."""
    engine = exportable
    engine.set_always_resident(False)
    assert engine.mode == "streaming"
    export_slices(engine, tmp_path / "cube.tif", 10, 5, None, NONE)
    assert not engine.has_cube, "export must not have built a cube behind the user's back"


def test_save_cube_npz_does_not_permanently_promote_a_streaming_engine(exportable, tmp_path):
    """Final review, Important 4. `engine.cube()` caches its result into
    `_cube`, which nothing in "streaming" mode ever reads back (`_slice`'s
    streaming branch calls `stream_slice` directly) and nothing but
    `set_source`/`clear` ever reset again -- so a "Save cube..." click
    used to permanently promote a streaming engine's real memory
    footprint by the whole resident cube, while `_mode` stayed
    "streaming" and `format_status` (branching on `_mode`, not on whether
    a cube happens to be cached) went on reporting only the prepared
    lines."""
    engine = exportable
    engine.set_always_resident(False)
    assert engine.mode == "streaming"
    assert not engine.has_cube

    npz = save_cube_npz(engine, tmp_path / "cube.npz")
    assert npz.exists()

    assert engine.mode == "streaming", "a save alone must not change the residency mode"
    assert not engine.has_cube, (
        "a streaming engine must not be left holding a resident cube after a save"
    )


def test_save_cube_npz_leaves_a_resident_engines_cube_in_place(exportable, tmp_path):
    """The other half of Important 4's fix: a "resident" engine already
    wanted its cube, for faster redraws -- `save_cube_npz` must not drop
    it and force an immediate, wasted rebuild on the very next slice."""
    engine = exportable
    engine.set_always_resident(True)
    engine.slice_at(SliceWindow(4, 14))  # builds the resident cube
    assert engine.mode == "resident"
    assert engine.has_cube

    save_cube_npz(engine, tmp_path / "cube.npz")

    assert engine.has_cube, "a resident engine's own cube must survive a save"


def test_the_temporal_mapping_is_one_nanosecond_to_one_second(exportable, tmp_path):
    """Spec 9.5's named trap. ns -> ms pairs two small units and looks
    right, and silently collapses every band at native dz into the same
    millisecond: 0.2165 ns rounds to 0 ms, adjacent bands get identical
    ranges, and the Temporal Controller's slider does nothing."""
    from nsgeo.slices import window_times_ns
    from qgis.core import Qgis

    engine = exportable
    path = tmp_path / "cube.tif"
    plan = export_slices(engine, path, 4, 1, None, NONE)
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
        ds.Close()


def test_an_amplitude_plan_without_a_finish_still_writes_a_blend(exportable, tmp_path):
    """`finish=None` does not mean coverage: negative amplitudes must survive."""
    from nsgeo_qgis.slice_export import plan_export
    from osgeo import gdal

    engine = exportable
    plan = plan_export(
        engine,
        thickness_levels=10,
        step_levels=5,
        velocity=None,
        cell=engine.frame.cell,
        pixel=engine.frame.cell,
    )
    assert plan.finish is None and not plan.coverage
    bands = _bands(_band_plan(engine, 3), fill=-2.0)
    path = tmp_path / "amp.tif"
    GeoTiffSliceWriter().write_bands(path, _band_plan(engine, 3), bands, clip=PercentileClip())
    ds = gdal.Open(str(path))
    try:
        arr = ds.GetRasterBand(1).ReadAsArray()
    finally:
        ds.Close()
    assert np.isfinite(arr).any()
    assert np.nanmax(arr) == pytest.approx(-2.0)


def test_the_coverage_export_uses_nan_not_zero_for_uncovered_in_frame_cells(exportable, tmp_path):
    """Final review, Minor 8. The dock's own coverage VIEW maps `count ==
    0 -> NaN` (transparent, `refresh_slice`'s coverage branch); this
    companion raster used to write the raw integer counts instead, so an
    uncovered in-frame cell landed as a literal `0.0` sitting against the
    band's own NaN nodata tag. Spec 3's "a zero that means no data reading
    as no reflection" applies to the file as much as to the screen: at
    this fixture's 0.25 m cells and four 1 m-apart parallel lines, most of
    the frame is genuinely uncovered, so this is not an edge case."""
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "coverage.tif"
    write_coverage(engine, path)
    ds = gdal.Open(str(path))
    try:
        band = ds.GetRasterBand(1)
        assert np.isnan(band.GetNoDataValue())
        arr = band.ReadAsArray()
        assert np.isnan(arr).any(), (
            "fixture must have uncovered in-frame cells, or this test cannot discriminate"
        )
        assert not (arr == 0.0).any(), "an uncovered cell must be NaN, never a literal zero"
    finally:
        ds.Close()


def test_a_coverage_export_does_not_touch_the_redraw_time_readout(exportable, tmp_path):
    """The export reads no live engine after its snapshot, so no export is a redraw:
    the status line's redraw time (smoothed, so one wrong measurement lingers for many
    ticks) is exactly what it was."""
    engine = exportable
    # A real redraw first, so `_redraw_ms` holds a small, known value.
    engine.slice_at(SliceWindow(6, 18))
    before = engine._redraw_ms
    assert before is not None

    write_coverage(engine, tmp_path / "coverage.tif")

    assert engine._redraw_ms == before, "an export must not be recorded as a redraw"


def test_the_geotiff_carries_interpolation_metadata(exportable, tmp_path):
    """Ruling AE, reworked (interpolation spec §8): a reader with only the
    `.tif` must see how its values were made. The defaults at this grid's
    0.5 m spacing: kriging out to three quarters of a spacing, no smoothing; and the
    old cells-based radius key is gone."""
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    export_slices(engine, path, 10, 5, None, SliceFinish())
    ds = gdal.Open(str(path))
    try:
        tags = ds.GetMetadata()
        assert tags["NSGEO_INTERPOLATION"] == "kriging"
        assert tags["NSGEO_MAX_DISTANCE_M"] == "0.375"
        assert tags["NSGEO_SMOOTH_X_M"] == "0.0"
        assert tags["NSGEO_SMOOTH_Y_M"] == "0.0"
        assert tags["NSGEO_FRAME_AZIMUTH_DEG"] == str(engine.frame.azimuth)
        assert "NSGEO_FILL_RADIUS_CELLS" not in tags
    finally:
        ds.Close()


def test_the_geotiff_metadata_follows_the_chosen_finish(exportable, tmp_path):
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    finish = SliceFinish(method="idw", max_distance_spacings=1.5, smooth_x_m=0.3, smooth_y_m=0.1)
    export_slices(engine, path, 10, 5, None, finish)
    ds = gdal.Open(str(path))
    try:
        tags = ds.GetMetadata()
        assert tags["NSGEO_INTERPOLATION"] == "idw"
        assert float(tags["NSGEO_MAX_DISTANCE_M"]) == pytest.approx(0.75)
        assert float(tags["NSGEO_SMOOTH_X_M"]) == pytest.approx(0.3)
        assert float(tags["NSGEO_SMOOTH_Y_M"]) == pytest.approx(0.1)
    finally:
        ds.Close()


def test_the_coverage_companion_carries_no_interpolation_metadata(exportable, tmp_path):
    """Coverage counts are exact; there is nothing interpolated to record."""
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "coverage.tif"
    write_coverage(engine, path)
    ds = gdal.Open(str(path))
    try:
        tags = ds.GetMetadata()
        for key in (
            "NSGEO_INTERPOLATION",
            "NSGEO_MAX_DISTANCE_M",
            "NSGEO_SMOOTH_X_M",
            "NSGEO_SMOOTH_Y_M",
            "NSGEO_FILL_RADIUS_CELLS",
        ):
            assert key not in tags
        assert tags["NSGEO_FRAME_AZIMUTH_DEG"] == str(engine.frame.azimuth)
    finally:
        ds.Close()


def test_export_bands_equal_the_finished_slices(exportable, tmp_path):
    """Each band is `engine.finish` of its window, north-up, at the live cell and
    pixel: the file holds what the dock draws."""
    from nsgeo.slices import plan_windows, to_north_up
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    finish = SliceFinish(method="idw", max_distance_spacings=1.0, smooth_x_m=0.25)
    plan = export_slices(engine, path, 10, 5, None, finish)
    windows = list(plan_windows(engine.z, 10, 5))
    assert len(plan.bands) == len(windows)
    ds = gdal.Open(str(path))
    try:
        for index, window in enumerate(windows, start=1):
            want, _gt = to_north_up(engine.finish(*engine.slice_at(window), finish), engine.frame)
            np.testing.assert_allclose(
                ds.GetRasterBand(index).ReadAsArray(), want, atol=1e-5, rtol=1e-5, equal_nan=True
            )
    finally:
        ds.Close()


def test_export_handles_a_rotated_frame_without_dropping_a_band(qgis_app, tmp_path):
    """Cheap cluster (final review): every export test above uses this
    file's `GRID`, at azimuth 0.0 -- the one azimuth at which `to_north_up`
    needs no resample at all. So the exporter's most-argued property -- what
    a rotated frame does to the north-up resample -- was exercised nowhere.
    What matters here is that a rotated export still lands every band on
    the same grid (no truncation error) and that its own bounding box
    genuinely is not fully covered by the rotated frame's cells. That no
    frame cell is lost is `test_a_rotated_export_is_at_the_cell_and_keeps_
    every_cell`'s."""
    from osgeo import gdal

    session = SiteSession()
    session.new_site(tmp_path)
    rotated = Grid("A", (500.0, 700.0), 30.0, 6.0, 6.0, "EPSG:32616", 0.5)
    session.add_grid(rotated)
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    engine = SliceEngine(session)
    try:
        engine.set_source(
            SourceChoice(
                grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
            )
        )
        assert engine.wait_for_preparation(20_000)
        engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
        assert engine.frame.azimuth == 30.0

        path = tmp_path / "rotated.tif"
        plan = export_slices(engine, path, 10, 5, None, NONE)
        ds = gdal.Open(str(path))
        try:
            assert ds.RasterCount == len(plan.bands)
            arr = ds.GetRasterBand(1).ReadAsArray()
            # A rotated frame's own bounding box is not filled by its
            # own cells -- some north-up pixels genuinely fall outside
            # the surveyed (rotated) frame and must read as nodata.
            assert np.isnan(arr).any()
        finally:
            ds.Close()
    finally:
        engine.dispose()


def test_a_rotated_export_is_at_the_cell_and_keeps_every_cell(qgis_app, tmp_path):
    """Spec §3 decision 1: a rotated frame is exported at the cell, read
    bilinearly, and no frame cell is dropped (the nearest-cell gather lost
    15-18% of them at that pitch). With no interpolation, the pixel is the
    cell and the file has a finite pixel for about every covered cell."""
    from osgeo import gdal

    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("A", (500.0, 700.0), 30.0, 6.0, 6.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    engine = SliceEngine(session)
    try:
        engine.set_source(
            SourceChoice(
                grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
            )
        )
        assert engine.wait_for_preparation(20_000)
        engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
        frame = engine.frame
        assert frame.azimuth == 30.0
        covered = int(np.count_nonzero(engine.slice_at(SliceWindow(0, 20))[1] > 0))

        path = tmp_path / "rotated.tif"
        export_slices(engine, path, 10, 5, None, NONE)
        ds = gdal.Open(str(path))
        try:
            assert ds.GetGeoTransform()[1] == pytest.approx(frame.cell)
            band = ds.GetRasterBand(1).ReadAsArray()
        finally:
            ds.Close()
        assert np.isfinite(band).sum() >= 0.9 * covered
    finally:
        engine.dispose()


def test_a_coverage_export_holds_whole_counts(qgis_app, tmp_path):
    """A coverage raster on a rotated frame is resampled with `counts=True`:
    every finite pixel is a whole number of traces >= 1, never a blend."""
    from osgeo import gdal

    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("A", (500.0, 700.0), 30.0, 6.0, 6.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    engine = SliceEngine(session)
    try:
        engine.set_source(
            SourceChoice(
                grid_id="A", preset="p", transform="amp_envelope", line_keys=tuple(session.keys())
            )
        )
        assert engine.wait_for_preparation(20_000)
        engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
        assert engine.frame.azimuth == 30.0
        path = tmp_path / "coverage.tif"
        write_coverage(engine, path)
        ds = gdal.Open(str(path))
        try:
            arr = ds.GetRasterBand(1).ReadAsArray()
        finally:
            ds.Close()
        finite = arr[np.isfinite(arr)]
        assert finite.size > 0
        assert (finite >= 1).all()
        np.testing.assert_array_equal(finite, np.round(finite))
    finally:
        engine.dispose()


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


def test_a_one_level_cube_round_trips_through_a_saved_record(exportable_with_session):
    """Final review, Minor 10. `cube_record` used to write `t1_ns =
    z.t_end_ns` unconditionally, and `z.t_end_ns = t0_ns + (nz - 1) *
    dz_ns` EQUALS `t0_ns` itself when `nz == 1` -- reachable whenever the
    requested span is positive but smaller than one level.
    `Resolution.__post_init__` requires `t1_ns` strictly greater than
    `t0_ns`, so `restore_cube` refused a record this same function had
    just written, for a perfectly legitimate one-level cube."""
    engine, session = exportable_with_session
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=2.3))
    assert engine.z.nz == 1, "fixture must actually reach the nz == 1 edge case"

    npz = save_cube_npz(engine, session.root / "slices" / "A__one_level.npz")
    record = cube_record(
        session,
        engine.choice,
        engine.frame,
        engine.z,
        _VIEW,
        npz,
        line_keys=engine.provenance().line_keys,
    )
    assert record["z"]["t1_ns"] > record["z"]["t0_ns"], (
        "a record naming its own axis must round-trip through Resolution's own validation"
    )

    recipe = recipe_from_record(record)  # must not raise
    assert recipe.resolution is not None
    restored_z = ZAxis.from_range(
        recipe.resolution.t0_ns, recipe.resolution.t1_ns, recipe.resolution.dz_ns
    )
    assert restored_z.nz == 1


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


_OLD_KEYS = {
    "thickness_ns": 5.0,
    "step_ns": 2.5,
    "radius_m": 0.25,
    "palette": "amp_heat",
    "stretch": "shared across the cube",
    "coverage": True,
}


@pytest.mark.parametrize("method", METHODS)
def test_view_settings_round_trip_the_finish(method):
    view = ViewSettings(
        **{**_OLD_KEYS, "radius_m": 0.0},
        method=method,
        max_distance_spacings=1.5,
        smooth_x_m=0.3,
        smooth_y_m=0.4,
    )
    again = ViewSettings.from_dict(view.to_dict())
    assert again == view
    assert again.finish == SliceFinish(method, 1.5, 0.3, 0.4)
    assert set(view.to_dict()) == set(_OLD_KEYS) | {
        "method",
        "max_distance_spacings",
        "smooth_x_m",
        "smooth_y_m",
    }


def test_a_0_2_0_view_record_loads_with_the_new_defaults():
    got = ViewSettings.from_dict(dict(_OLD_KEYS))
    assert got.radius_m == 0.25
    assert got.finish == SliceFinish()


def test_a_view_record_with_a_bad_method_falls_back_to_the_defaults():
    got = ViewSettings.from_dict({**_OLD_KEYS, "method": "bogus", "smooth_x_m": 0.3})
    assert got.finish == SliceFinish(smooth_x_m=0.3)


@dataclass(frozen=True)
class _ViewSettings020:
    """Release 0.2.0's `ViewSettings`: the six fields, as in
    `git show v0.2.0:packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`."""

    thickness_ns: float
    step_ns: float
    radius_m: float
    palette: str
    stretch: str
    coverage: bool

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> _ViewSettings020:
        # Body copied verbatim from 0.2.0.
        return cls(
            thickness_ns=float(doc["thickness_ns"]),
            step_ns=float(doc["step_ns"]),
            radius_m=float(doc["radius_m"]),
            palette=str(doc["palette"]),
            stretch=str(doc["stretch"]),
            # `.get(..., False)`, not `doc["coverage"]` (Task 7): tolerant
            # of a `view` dict that carries the other five fields but not
            # this one -- the same reader-tolerance this module's `Task 7`
            # functions extend to the record as a whole.
            coverage=bool(doc.get("coverage", False)),
        )


@pytest.mark.parametrize("method", METHODS)
def test_a_record_from_this_build_still_loads_in_0_2_0(method):
    view = ViewSettings(**_OLD_KEYS, method=method, max_distance_spacings=1.0)
    got = _ViewSettings020.from_dict(view.to_dict())
    assert got == _ViewSettings020(**_OLD_KEYS)


# ---- milestone B: the file at any pixel (write_bands) ------------------------
def _band_plan(engine, n=3, lattice=None, **extra):
    """An `ExportPlan` of `n` bands on `lattice` (default: the frame's own, at its cell)."""
    from dataclasses import replace

    from nsgeo.slices import frame_lattice
    from nsgeo_qgis.slice_export import plan_export

    plan = plan_export(
        engine,
        10,
        5,
        None,
        finish=engine.finish_settings(SliceFinish()),
        cell=engine.frame.cell,
        pixel=engine.frame.cell,
    )
    lattice = lattice or frame_lattice(plan.frame, plan.frame.cell)
    extra = {"cell": plan.frame.cell, "pixel": lattice.pixel, **extra}
    return replace(plan, bands=plan.bands[:n], lattice=lattice, **extra)


def _bands(plan, fill=None):
    rng = np.random.default_rng(3)
    shape = (plan.lattice.height, plan.lattice.width)
    out = []
    for i in range(len(plan.bands)):
        a = (
            rng.normal(size=shape).astype(np.float32)
            if fill is None
            else np.full(shape, fill, np.float32)
        )
        a[:2, :] = np.nan
        out.append(ExportBand(a, {"A": (1.0 + i, 0.0)}))
    return out


def test_a_large_file_is_tiled_and_a_small_one_is_stripped(exportable, tmp_path):
    from dataclasses import replace

    plan = _band_plan(exportable, n=1)
    small_path = tmp_path / "small.tif"
    GeoTiffSliceWriter().write_bands(small_path, plan, _bands(plan), clip=PercentileClip())
    big_lattice = SiteLattice(500.0, 700.0, 0.01, 1100, 1200, plan.crs)
    big_plan = replace(plan, lattice=big_lattice, pixel=0.01)
    big_path = tmp_path / "big.tif"
    GeoTiffSliceWriter().write_bands(big_path, big_plan, _bands(big_plan), clip=PercentileClip())
    from osgeo import gdal

    small, big = gdal.Open(str(small_path)), gdal.Open(str(big_path))
    try:
        assert small.GetRasterBand(1).GetBlockSize()[0] == small.RasterXSize
        assert big.GetRasterBand(1).GetBlockSize() == [256, 256]
        assert big.GetRasterBand(1).GetOverviewCount() == 0  # overviews are a separate step
    finally:
        small.Close()
        big.Close()


def test_overviews_exist_for_a_tiled_file_and_do_not_bleed(exportable, tmp_path):
    from dataclasses import replace

    from osgeo import gdal

    plan = _band_plan(exportable, n=2)
    plan = replace(plan, lattice=SiteLattice(500.0, 700.0, 0.01, 1100, 1200, plan.crs), pixel=0.01)
    values = np.full((1200, 1100), np.nan, np.float32)
    values[:, :550] = 5.0  # the east half is empty ground
    bands = [ExportBand(values.copy(), {}) for _ in plan.bands]
    path = tmp_path / "o.tif"
    GeoTiffSliceWriter().write_bands(path, plan, bands, clip=PercentileClip())
    build_overviews(path)
    ds = gdal.Open(str(path))
    try:
        band = ds.GetRasterBand(2)
        # 1100 x 1200: factors 2 (550 x 600), 4 (275 x 300); 8 would be 138 x 150 < 256.
        assert band.GetOverviewCount() == 2
        for i, width in enumerate((550, 275)):
            ov = band.GetOverview(i).ReadAsArray()
            assert ov.shape[1] == width
            assert np.isnan(ov[:, width // 2 + 2 :]).all()  # empty ground stays empty
            west = ov[:, : width // 2 - 2]
            assert np.allclose(west, 5.0)  # and the edge is not diluted by it
    finally:
        ds.Close()


def test_a_stripped_file_gets_no_overviews(exportable, tmp_path):
    from osgeo import gdal

    plan = _band_plan(exportable, n=1)
    path = tmp_path / "s.tif"
    GeoTiffSliceWriter().write_bands(path, plan, _bands(plan), clip=PercentileClip())
    build_overviews(path)
    ds = gdal.Open(str(path))
    try:
        assert ds.GetRasterBand(1).GetOverviewCount() == 0
    finally:
        ds.Close()


def test_write_bands_round_trips_values_geotransform_and_metadata(exportable, tmp_path):
    from dataclasses import replace

    from nsgeo.slices import frame_lattice
    from osgeo import gdal

    plan = _band_plan(exportable, n=3)
    lattice = frame_lattice(plan.frame, 0.125)
    plan = replace(plan, lattice=lattice, cell=0.25, pixel=0.125)
    bands = _bands(plan)
    path = tmp_path / "m.tif"
    GeoTiffSliceWriter().write_bands(path, plan, bands, clip=PercentileClip())
    ds = gdal.Open(str(path))
    try:
        assert ds.GetGeoTransform() == pytest.approx(lattice.geotransform)
        assert "32616" in ds.GetProjection()
        md = ds.GetMetadata()
        assert md["NSGEO_RESAMPLING"] == "bilinear"
        assert float(md["NSGEO_CELL_M"]) == 0.25 and float(md["NSGEO_PIXEL_M"]) == 0.125
        assert float(md["NSGEO_FRAME_AZIMUTH_DEG"]) == plan.frame.azimuth
        for i, band in enumerate(bands):
            rb = ds.GetRasterBand(i + 1)
            assert rb.GetDescription() == plan.bands[i].description
            assert np.isnan(rb.GetNoDataValue())
            assert np.array_equal(rb.ReadAsArray(), band.array, equal_nan=True)
    finally:
        ds.Close()


def test_write_bands_refuses_a_plan_without_its_export_settings(exportable, tmp_path):
    from dataclasses import replace

    plan = _band_plan(exportable, n=1)
    for missing in ("lattice", "cell", "pixel"):
        bare = replace(plan, **{missing: None})
        with pytest.raises(ValueError, match="export cell and pixel"):
            GeoTiffSliceWriter().write_bands(
                tmp_path / f"{missing}.tif", bare, _bands(plan), clip=PercentileClip()
            )
        assert not (tmp_path / f"{missing}.tif").exists()


def test_a_counts_plan_writes_without_interpolation_keys(exportable, tmp_path):
    from osgeo import gdal

    plan = _band_plan(exportable, n=1, coverage=True, finish=None)
    path = tmp_path / "c.tif"
    limit = GeoTiffSliceWriter().write_bands(
        path, plan, _bands(plan, fill=3.0), clip=PercentileClip()
    )
    assert limit == pytest.approx(3.0)
    ds = gdal.Open(str(path))
    try:
        md = ds.GetMetadata()
        assert "NSGEO_INTERPOLATION" not in md
        assert md["NSGEO_RESAMPLING"] == "largest_count"  # counts are not blended
    finally:
        ds.Close()


def test_the_returned_stretch_is_the_limit_over_the_written_bands(exportable, tmp_path):
    plan = _band_plan(exportable, n=3)
    bands = _bands(plan)
    clip = PercentileClip()
    got = GeoTiffSliceWriter().write_bands(tmp_path / "l.tif", plan, bands, clip=clip)
    assert got == limit_over_slices((b.array for b in bands), clip)


def test_the_stretch_sample_never_holds_more_than_its_cap(monkeypatch):
    from nsgeo_qgis import slice_export

    monkeypatch.setattr(slice_export, "STRETCH_SAMPLE_CAP", 1000)
    sample = slice_export.StretchSample(n_bands=4)
    rng = np.random.default_rng(0)
    for _ in range(4):
        a = rng.normal(size=(100, 100)).astype(np.float32)
        a[::3] = np.nan
        sample.add(a)
        assert sample.count <= 1000
    assert 0 < sample.count <= 1000
    assert np.isfinite(sample.limit(PercentileClip()))


def test_the_stretch_sample_of_an_empty_export_is_the_clips_own_fallback():
    from nsgeo_qgis.slice_export import StretchSample

    sample = StretchSample(n_bands=1)
    sample.add(np.full((4, 4), np.nan, np.float32))
    assert sample.limit(PercentileClip()) == PercentileClip().limit(np.array([], dtype=float))


def test_the_partial_name_sits_beside_the_target(tmp_path):
    target = tmp_path / "site.tif"
    assert partial_path(target) == tmp_path / "site.partial.tif"


def test_an_interrupted_write_leaves_no_partial_and_no_target(exportable, tmp_path):
    plan = _band_plan(exportable, n=3)
    bands = _bands(plan)

    def interrupted():
        yield bands[0]
        raise ExportCancelled()

    target = tmp_path / "out.tif"
    partial = partial_path(target)
    with pytest.raises(ExportCancelled):
        try:
            GeoTiffSliceWriter().write_bands(partial, plan, interrupted(), clip=PercentileClip())
            commit_partial(partial, target)
        except BaseException:
            discard_partial(partial)
            raise
    assert not partial.exists() and not target.exists()


def test_an_interrupted_write_leaves_an_existing_target_untouched(exportable, tmp_path):
    plan = _band_plan(exportable, n=2)
    target = tmp_path / "out.tif"
    target.write_bytes(b"the previous export")
    partial = partial_path(target)

    def interrupted():
        yield _bands(plan)[0]
        raise ExportCancelled()

    with pytest.raises(ExportCancelled):
        try:
            GeoTiffSliceWriter().write_bands(partial, plan, interrupted(), clip=PercentileClip())
            commit_partial(partial, target)
        except BaseException:
            discard_partial(partial)
            raise
    assert target.read_bytes() == b"the previous export" and not partial.exists()


def test_a_finished_write_commits_over_the_target(exportable, tmp_path):
    plan = _band_plan(exportable, n=1)
    target = tmp_path / "out.tif"
    target.write_bytes(b"old")
    partial = partial_path(target)
    GeoTiffSliceWriter().write_bands(partial, plan, _bands(plan), clip=PercentileClip())
    commit_partial(partial, target)
    assert not partial.exists() and target.stat().st_size > 100
    discard_partial(partial)  # absent: no error


def test_write_bands_reports_each_band_as_it_lands(exportable, tmp_path):
    plan = _band_plan(exportable, n=3)
    seen: list[int] = []
    GeoTiffSliceWriter().write_bands(
        tmp_path / "p.tif", plan, _bands(plan), clip=PercentileClip(), progress_band=seen.append
    )
    assert seen == [1, 2, 3]


def test_write_bands_refuses_a_wrong_number_of_bands_or_a_wrong_shape(exportable, tmp_path):
    plan = _band_plan(exportable, n=3)
    bands = _bands(plan)
    writer = GeoTiffSliceWriter()
    with pytest.raises(ValueError, match="slices"):
        writer.write_bands(tmp_path / "a.tif", plan, bands[:2], clip=PercentileClip())
    with pytest.raises(ValueError, match="more slices"):
        writer.write_bands(tmp_path / "b.tif", plan, bands + bands[:1], clip=PercentileClip())
    wrong = [ExportBand(np.zeros((3, 3), np.float32), {})] * 3
    with pytest.raises(ValueError, match="lattice"):
        writer.write_bands(tmp_path / "c.tif", plan, wrong, clip=PercentileClip())


def test_the_worker_thread_write_path_never_uses_catch_warnings():
    import inspect

    from nsgeo_qgis import site_export, slice_export

    for obj in (
        slice_export.GeoTiffSliceWriter.write_bands,
        site_export.GeoTiffSiteWriter.write_bands,
        slice_export.write_north_up,
        slice_export.build_overviews,
        slice_export.partial_path,
        slice_export.commit_partial,
        slice_export.discard_partial,
        slice_export.StretchSample,
    ):
        assert "catch_warnings" not in inspect.getsource(obj), obj


def test_a_project_custom_crs_is_written_into_the_file(exportable, tmp_path):
    from dataclasses import replace

    from osgeo import gdal
    from qgis.core import QgsApplication, QgsCoordinateReferenceSystem

    custom = QgsCoordinateReferenceSystem()
    custom.createFromProj("+proj=tmerc +lat_0=0 +lon_0=-87 +k=0.9996 +x_0=500000 +y_0=0 +units=m")
    registry = QgsApplication.coordinateReferenceSystemRegistry()
    crs_id = registry.addUserCrs(custom, "nsgeo export test crs")
    authid = f"USER:{crs_id}"
    try:
        assert authid.startswith("USER:")
        plan = _band_plan(exportable, n=1)
        lattice = SiteLattice(500.0, 700.0, 0.25, 24, 24, authid)
        plan = replace(plan, lattice=lattice, pixel=0.25)
        path = tmp_path / "u.tif"
        GeoTiffSliceWriter().write_bands(path, plan, _bands(plan), clip=PercentileClip())
        ds = gdal.Open(str(path))
        try:
            assert (
                "tmerc" in ds.GetProjection().lower() or "transverse" in ds.GetProjection().lower()
            )
        finally:
            ds.Close()
        bad = SiteLattice(500.0, 700.0, 0.25, 24, 24, "USER:999999")
        with pytest.raises(ValueError, match="coordinate system"):
            GeoTiffSliceWriter().write_bands(
                tmp_path / "v.tif", replace(plan, lattice=bad), _bands(plan), clip=PercentileClip()
            )
    finally:
        registry.removeUserCrs(crs_id)


def test_a_stop_during_overviews_raises_and_leaves_the_file_closed(exportable, tmp_path):
    from dataclasses import replace

    plan = _band_plan(exportable, n=2)
    plan = replace(plan, lattice=SiteLattice(500.0, 700.0, 0.01, 1100, 1200, plan.crs), pixel=0.01)
    path = tmp_path / "o.tif"
    GeoTiffSliceWriter().write_bands(path, plan, _bands(plan), clip=PercentileClip())
    with pytest.raises(ExportCancelled):
        build_overviews(path, should_stop=lambda: True)
    path.unlink()  # closed: removable (Windows would refuse an open file)
    assert not path.exists()


def test_coverage_path_is_the_stem_plus_coverage_tif(tmp_path):
    from nsgeo_qgis.slice_export import coverage_path

    assert coverage_path(tmp_path / "site.tif") == tmp_path / "site_coverage.tif"
    assert coverage_path(str(tmp_path / "site.tiff")) == tmp_path / "site_coverage.tif"
