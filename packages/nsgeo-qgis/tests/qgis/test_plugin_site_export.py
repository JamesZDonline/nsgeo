"""The site GeoTIFF: one file over every included grid, which records what was done."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
from nsgeo.render import PercentileClip
from nsgeo.slices import (
    SiteLattice,
    limit_over_slices,
    window_depths_m,
    window_on,
    window_times_ns,
)
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.export_pipeline import ExportBand, ExportCancelled, run_export
from nsgeo_qgis.site_engine import SiteEngine
from nsgeo_qgis.site_export import (
    GeoTiffSiteWriter,
    apply_site_temporal_properties,
    site_export_job,
)
from nsgeo_qgis.slice_export import (
    band_time_range,
    build_overviews,
    commit_partial,
    discard_partial,
    partial_path,
)
from nsgeo_qgis.slices_plan import Resolution, SiteSource, SliceFinish
from osgeo import gdal
from qgis.core import QgsRasterLayer

RES = Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=60.0)
V_A = VelocityModel(layers=((0.0, 0.10),))
V_B = VelocityModel(layers=((0.0, 0.08), (10.0, 0.12)))
KW = {
    "transform": "amp_envelope",
    "method": "edge",
    "finish": SliceFinish(method="idw", max_distance_spacings=1.5, smooth_x_m=0.2, smooth_y_m=0.3),
    "gains": {"A": 1.0, "B": 2.0, "C": 1.0},
    "velocities": {"A": V_A, "B": V_B, "C": VelocityModel(layers=((0.0, 0.1),))},
}


@pytest.fixture
def make_site():
    made: list[SiteEngine] = []

    def make(site3) -> SiteEngine:
        site = SiteEngine(site3.session)
        made.append(site)
        site.set_source(site3.source())
        assert site.wait_until_idle(60_000), "the site did not finish preparing"
        site.set_resolution(RES)
        return site

    yield make
    for site in made:
        site.wait_until_idle(20_000)
        site.dispose()


@pytest.fixture
def open_tif():
    """`gdal.Open`, every dataset it opened closed at teardown (final review D5).

    A failing test's traceback keeps its locals, a dataset among them, alive
    past `qgis_app`'s `exitQgis()`, and releasing a dataset after GDAL's
    drivers are gone killed the process (exit 139) instead of reporting the
    failure. `Close()` releases it now, whatever still refers to it.
    """
    opened = []

    def open_(path):
        with gdal.ExceptionMgr(useExceptions=True):
            ds = gdal.Open(str(path))
        opened.append(ds)
        return ds

    yield open_
    for ds in opened:
        ds.Close()


def job_for(site, thickness=8, step=24, cell=None, pixel=None, coverage=False, **overrides):
    """What the plugin builds on the GUI thread for an export at `cell` and `pixel`
    (default: the live ones)."""
    kw = {**KW, **overrides}
    cell = RES.cell if cell is None else cell
    pixel = site.lattice.pixel if pixel is None else pixel
    return site_export_job(site, thickness, step, cell, pixel, coverage=coverage, **kw)


def plan_of(site, thickness=8, step=24, **overrides):
    """A plan at the live cell and pixel, as the writer tests need one."""
    return job_for(site, thickness, step, **overrides).plan


def write_job(job, path, coverage_to=None):
    """The task's work, synchronously: the bands of the spec into the writer."""
    writer = GeoTiffSiteWriter()
    clip = PercentileClip()

    def bands(spec):
        return run_export(spec, should_stop=lambda: False, progress=lambda *a: None)

    writer.write_bands(path, job.plan, bands(job.spec), clip=clip)
    if coverage_to is not None:
        writer.write_bands(coverage_to, job.coverage_plan, bands(job.coverage_spec), clip=clip)


def export_site(site, path, thickness, step, *, cell=None, pixel=None, coverage_to=None, **kw):
    """Plan, snapshot and write a site file; return its plan."""
    job = job_for(
        site, thickness, step, cell=cell, pixel=pixel, coverage=coverage_to is not None, **kw
    )
    write_job(job, path, coverage_to)
    return job.plan


def exported(make_site, site3, tmp_path, thickness=8, step=24, **overrides):
    site = make_site(site3)
    path = tmp_path / "site.tif"
    plan = export_site(site, path, thickness, step, **overrides)
    return site, plan, path


def pull(site, plan, band, **overrides):
    kw = {**KW, **overrides}
    lo, hi = window_times_ns(plan.site_z, band.window)
    top = plan.site_z.t0_ns + band.window.k0 * plan.site_z.dz_ns
    thickness = band.window.n_levels * plan.site_z.dz_ns
    return site.slice_at(
        top,
        thickness,
        finish=kw["finish"],
        method=kw["method"],
        manual=kw["gains"],
    )


def test_the_file_lands_on_the_site_lattice(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(path)
    lat = site.lattice
    assert (ds.RasterXSize, ds.RasterYSize) == (lat.width, lat.height)
    assert ds.GetGeoTransform() == pytest.approx(lat.geotransform)
    assert "32" in ds.GetProjection() or "UTM" in ds.GetProjection().upper()
    assert plan.lattice == lat


def test_there_is_a_band_per_planned_window(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(path)
    assert len(plan.bands) > 1
    assert ds.RasterCount == len(plan.bands)


def test_a_live_cell_export_equals_the_live_slice_band_by_band(
    site3, make_site, tmp_path, open_tif
):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(path)
    assert not site.is_preview
    for i, band in enumerate(plan.bands):
        shown = pull(site, plan, band)
        got = ds.GetRasterBand(i + 1).ReadAsArray()
        assert np.array_equal(np.isnan(got), np.isnan(shown.array))
        np.testing.assert_allclose(got, shown.array, atol=1e-5, rtol=1e-5, equal_nan=True)
        factors = json.loads(ds.GetRasterBand(i + 1).GetMetadata()["NSGEO_GRID_FACTORS"])
        for grid_id, ab in shown.factors.items():
            assert factors[grid_id] == pytest.approx(list(ab), abs=1e-5)
        assert {g for g, v in factors.items() if v is not None} == set(shown.factors)
    assert np.isfinite(got).any()


def test_a_grid_in_another_crs_exports_as_the_live_site_draws_it(
    site3_factory, make_site, tmp_path, open_tif
):
    """The snapshot gives that grid a transform built inside the task (R2); the
    file still equals the live composition, and the grid is where it should be."""
    site3 = site3_factory(crs={"B": "EPSG:32617"})
    site, plan, path = exported(make_site, site3, tmp_path)
    assert site.engine_for("B").frame.crs == "EPSG:32617"
    job = job_for(site)
    assert [g.world_to_frame is not None for g in job.spec.grids] == [False, True, False]
    ds = open_tif(path)
    for i, band in enumerate(plan.bands):
        shown = pull(site, plan, band)
        got = ds.GetRasterBand(i + 1).ReadAsArray()
        assert np.array_equal(np.isnan(got), np.isnan(shown.array))
        np.testing.assert_allclose(got, shown.array, atol=1e-4, rtol=1e-4, equal_nan=True)


def test_the_dataset_records_transform_method_and_every_grid(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    md = open_tif(path).GetMetadata()
    assert md["NSGEO_SITE_TRANSFORM"] == "amp_envelope"
    assert md["NSGEO_SITE_NORMALISATION"] == "edge"
    assert float(md["NSGEO_SITE_CELL_M"]) == 0.25
    assert float(md["NSGEO_SITE_PIXEL_M"]) == site.lattice.pixel
    assert md["NSGEO_SITE_Z_UNIT"] == "ns"


def test_the_site_geotiff_carries_interpolation_metadata(site3, make_site, tmp_path, open_tif):
    """The file records the finish it was drawn with (interpolation spec §8),
    the old fill radius key gone."""
    site, plan, path = exported(make_site, site3, tmp_path)
    md = open_tif(path).GetMetadata()
    assert md["NSGEO_SITE_INTERPOLATION"] == "idw"
    assert float(md["NSGEO_SITE_MAX_DISTANCE_SPACINGS"]) == 1.5
    assert float(md["NSGEO_SITE_SMOOTH_X_M"]) == 0.2
    assert float(md["NSGEO_SITE_SMOOTH_Y_M"]) == 0.3
    assert "NSGEO_SITE_FILL_RADIUS_SPACINGS" not in md
    assert plan.finish == KW["finish"]
    grids = json.loads(md["NSGEO_SITE_GRIDS"])
    assert [g["grid_id"] for g in grids] == ["A", "B", "C"]
    by_id = {g["grid_id"]: g for g in grids}
    assert by_id["B"]["velocity"] == V_B.to_dict()  # layered models survive
    assert by_id["B"]["gain"] == 2.0
    assert by_id["A"]["preset"] == "p"
    assert by_id["A"]["line_spacing_m"] == site3.session.grid("A").default_spacing
    assert by_id["A"]["azimuth_deg"] == 0.0
    assert by_id["A"]["crs"] == site.lattice.crs
    assert ", " not in md["NSGEO_SITE_GRIDS"]


def test_each_band_records_every_grids_factors_and_depths(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(path)
    all_factors = []
    for i, band in enumerate(plan.bands):
        md = ds.GetRasterBand(i + 1).GetMetadata()
        lo, hi = window_times_ns(plan.site_z, band.window)
        assert md["NSGEO_WINDOW_NS"] == f"{lo},{hi}"
        factors = json.loads(md["NSGEO_GRID_FACTORS"])
        want = pull(site, plan, band).factors
        assert set(factors) == {"A", "B", "C"}
        for g, ab in want.items():
            assert factors[g] == pytest.approx(list(ab))
        all_factors.append(factors)
        depths = json.loads(md["NSGEO_GRID_DEPTHS_M"])
        for g in "ABC":
            engine = site.engine_for(g)
            top = plan.site_z.t0_ns + band.window.k0 * plan.site_z.dz_ns
            gw = window_on(engine.z, top, band.window.n_levels * plan.site_z.dz_ns)
            assert depths[g] == pytest.approx(
                list(window_depths_m(engine.z, gw, KW["velocities"][g]))
            )
    # Normalisation is per slice: the factors differ from band to band.
    assert any(f != all_factors[0] for f in all_factors[1:])


def test_an_absent_grid_is_null_in_the_band_metadata(site3_factory, make_site, tmp_path, open_tif):
    site3 = site3_factory(samples={"C": 100})
    site, plan, path = exported(make_site, site3, tmp_path, thickness=8, step=40)
    ds = open_tif(path)
    last = len(plan.bands)
    md = ds.GetRasterBand(last).GetMetadata()
    assert json.loads(md["NSGEO_GRID_DEPTHS_M"])["C"] is None
    assert json.loads(md["NSGEO_GRID_FACTORS"])["C"] is None
    assert json.loads(md["NSGEO_GRID_FACTORS"])["A"] is not None
    first = ds.GetRasterBand(1).GetMetadata()
    assert json.loads(first["NSGEO_GRID_DEPTHS_M"])["C"] is not None
    assert json.loads(first["NSGEO_GRID_FACTORS"])["C"] is not None


def test_band_descriptions_name_each_grids_depths(site3_factory, make_site, tmp_path, open_tif):
    site3 = site3_factory(samples={"C": 100})
    site, plan, path = exported(make_site, site3, tmp_path, thickness=8, step=40)
    ds = open_tif(path)
    for i, band in enumerate(plan.bands):
        text = ds.GetRasterBand(i + 1).GetDescription()
        assert text == band.description
        lo, hi = window_times_ns(plan.site_z, band.window)
        assert text.startswith(f"{lo:.1f}-{hi:.1f} ns")
        for g, depths in band.depths.items():
            if depths is None:
                assert f"{g} no data" in text
            else:
                assert f"{g} {depths[0]:.2f}-{depths[1]:.2f} m" in text
    assert "C no data" in plan.bands[-1].description
    assert "C no data" not in plan.bands[0].description
    assert " · " in plan.bands[0].description


def test_depths_come_from_the_window_each_grid_actually_got(site3_factory, make_site, tmp_path):
    """Trap 5: a window overhanging a grid's end is thinner there."""
    site3 = site3_factory(samples={"C": 100})
    site = make_site(site3)
    plan = plan_of(site, 8, 3)
    # Find a band that overhangs C's axis end but is not absent.
    c = site.engine_for("C").z
    c_end = c.t0_ns + (c.nz - 1) * c.dz_ns
    overhang = [
        b
        for b in plan.bands
        if b.depths["C"] is not None and window_times_ns(plan.site_z, b.window)[1] > c_end
    ]
    assert overhang, "the fixture should produce a band overhanging C"
    b = overhang[0]
    top = plan.site_z.t0_ns + b.window.k0 * plan.site_z.dz_ns
    gw = window_on(c, top, b.window.n_levels * plan.site_z.dz_ns)
    assert b.depths["C"] == pytest.approx(window_depths_m(c, gw, KW["velocities"]["C"]))


def test_temporal_ranges_follow_the_ns_windows(site3, make_site, tmp_path):
    site, plan, path = exported(make_site, site3, tmp_path)
    layer = QgsRasterLayer(str(path), "site")
    assert layer.isValid()
    apply_site_temporal_properties(layer, plan)
    ranges = layer.temporalProperties().fixedRangePerBand()
    assert len(ranges) == len(plan.bands)
    for i, band in enumerate(plan.bands):
        want = band_time_range(*window_times_ns(plan.site_z, band.window))
        assert ranges[i + 1].begin() == want.begin()
        assert ranges[i + 1].end() == want.end()
    assert ranges[2].begin() > ranges[1].begin()


def test_the_export_reads_no_live_engine_and_builds_no_resident_cube(site3, make_site, tmp_path):
    """The snapshot is taken first; after it nothing calls a live engine, so the
    task cannot race the live view (Review Focus 2)."""
    site = make_site(site3)
    job = job_for(site)

    def forbidden(*args, **kwargs):
        raise AssertionError("the export reached a live engine")

    site.slice_at = forbidden  # type: ignore[method-assign]
    for grid_id in "ABC":
        engine = site.engine_for(grid_id)
        for name in ("slice_at", "finish", "_slice", "cube"):
            setattr(engine, name, forbidden)
    write_job(job, tmp_path / "s.tif")
    assert all(site.engine_for(g).mode != "resident" for g in "ABC")


def test_the_snapshot_hands_over_the_engines_own_prepared_lines(site3, make_site):
    site = make_site(site3)
    job = job_for(site)
    for grid in job.spec.grids:
        live = site.engine_for(grid.grid_id).prepared_lines()
        assert len(grid.lines) == len(live)
        assert all(a is b for a, b in zip(grid.lines, live))


def test_the_coverage_companion_is_written_beside_it(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(
        make_site, site3, tmp_path, coverage_to=tmp_path / "site_coverage.tif"
    )
    out = tmp_path / "site_coverage.tif"
    ds = open_tif(out)
    assert ds.RasterCount == 1
    assert (ds.RasterXSize, ds.RasterYSize) == (site.lattice.width, site.lattice.height)
    assert ds.GetGeoTransform() == pytest.approx(site.lattice.geotransform)
    arr = ds.GetRasterBand(1).ReadAsArray()
    top = plan.site_z.t0_ns + plan.bands[0].window.k0 * plan.site_z.dz_ns
    thickness = plan.bands[0].window.n_levels * plan.site_z.dz_ns
    counts = site.slice_at(
        top, thickness, finish=KW["finish"], method="none", manual={}, coverage=True
    ).array
    assert np.array_equal(arr, counts, equal_nan=True)
    finite = arr[np.isfinite(arr)]
    assert finite.size and (finite >= 1).all() and (finite == np.round(finite)).all()
    assert np.isnan(ds.GetRasterBand(1).GetNoDataValue())


def test_the_coverage_companion_does_not_claim_processing_it_never_had(
    site3, make_site, tmp_path, open_tif
):
    site, plan, path = exported(
        make_site, site3, tmp_path, coverage_to=tmp_path / "site_coverage.tif"
    )
    ds = open_tif(tmp_path / "site_coverage.tif")
    md = ds.GetMetadata()
    assert md["NSGEO_SITE_NORMALISATION"] == "none"
    assert [g["gain"] for g in json.loads(md["NSGEO_SITE_GRIDS"])] == [1.0, 1.0, 1.0]
    factors = json.loads(ds.GetRasterBand(1).GetMetadata()["NSGEO_GRID_FACTORS"])
    assert all(f == [1.0, 0.0] for f in factors.values())
    # the values file keeps what it did
    main = open_tif(path).GetMetadata()
    assert main["NSGEO_SITE_NORMALISATION"] == "edge"
    assert main["NSGEO_SITE_INTERPOLATION"] == "idw"


def test_the_site_coverage_companion_has_no_interpolation_metadata(
    site3, make_site, tmp_path, open_tif
):
    """Raw counts were neither interpolated nor smoothed, so the companion
    says nothing of either (interpolation spec §8)."""
    exported(make_site, site3, tmp_path, coverage_to=tmp_path / "site_coverage.tif")
    md = open_tif(tmp_path / "site_coverage.tif").GetMetadata()
    assert not [k for k in md if "INTERPOLATION" in k or "MAX_DISTANCE" in k or "SMOOTH" in k]


def test_every_band_is_nodata_nan_on_read_back(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(path)
    for i in range(1, ds.RasterCount + 1):
        assert np.isnan(ds.GetRasterBand(i).GetNoDataValue())


def test_a_ready_grid_with_no_site_axis_exports_as_absent(
    site3_factory, make_site, tmp_path, open_tif
):
    """R-P3: C ends at ~18.84 ns (each line reads 0 at its first break), so at
    t0=18.5 it has no axis (frame and z are None)."""
    site3 = site3_factory(samples={"C": 128})
    site = SiteEngine(site3.session)
    try:
        site.set_source(site3.source())
        assert site.wait_until_idle(60_000)
        site.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=18.5, t1_ns=60.0))
        assert site.engine_for("C").z is None
        path = tmp_path / "r.tif"
        plan = export_site(site, path, 4, 8, **KW)
        ds = open_tif(path)
        assert ds.RasterCount == len(plan.bands) >= 2
        for i in range(1, ds.RasterCount + 1):
            band = ds.GetRasterBand(i)
            md = band.GetMetadata()
            assert json.loads(md["NSGEO_GRID_DEPTHS_M"])["C"] is None
            assert json.loads(md["NSGEO_GRID_FACTORS"])["C"] is None
            assert json.loads(md["NSGEO_GRID_FACTORS"])["A"] is not None
            assert "C no data" in band.GetDescription()
        grids = {g["grid_id"]: g for g in json.loads(ds.GetMetadata()["NSGEO_SITE_GRIDS"])}
        assert grids["C"]["crs"] == site3.session.grid("C").crs
        assert float(ds.GetMetadata()["NSGEO_SITE_CELL_M"]) == 0.25
    finally:
        site.wait_until_idle(20_000)
        site.dispose()


def test_an_included_grid_left_out_is_recorded_and_absent_otherwise(
    site3, make_site, tmp_path, open_tif
):
    """Final review M4 (Ruling F-2): `NSGEO_SITE_LEFT_OUT`, a compact JSON
    object of grid id to state, present only when an included grid is left
    out. The coverage companion leaves the same grids out, so says so too."""
    site, _, path = exported(make_site, site3, tmp_path)
    assert "NSGEO_SITE_LEFT_OUT" not in open_tif(path).GetMetadata()
    left = {"D": "no lines", "E": "failed: no line could be prepared"}
    other = tmp_path / "left_out.tif"
    export_site(site, other, 8, 24, left_out=left, coverage_to=tmp_path / "left_out_coverage.tif")
    md = open_tif(other).GetMetadata()
    assert md["NSGEO_SITE_LEFT_OUT"] == '{"D":"no lines","E":"failed: no line could be prepared"}'
    companion = open_tif(tmp_path / "left_out_coverage.tif").GetMetadata()
    assert json.loads(companion["NSGEO_SITE_LEFT_OUT"]) == left


def test_a_preview_site_exports_at_full_detail(site3, make_site, tmp_path, open_tif):
    """Milestone A refused here. The export has its own lattice at the export
    cell, so a site drawn as a preview still writes in full."""
    site = make_site(site3)
    site.max_pixels = 100  # the 0.25 m site is far over it: a preview
    site.max_covered = 10**9
    site.set_resolution(RES)
    assert site.is_preview
    path = tmp_path / "site.tif"
    plan = export_site(site, path, 8, 24, pixel=RES.cell)
    full = site.full_lattice
    ds = open_tif(path)
    assert (ds.RasterXSize, ds.RasterYSize) == (full.width, full.height)
    assert plan.lattice == full and plan.lattice != site.lattice
    assert float(ds.GetMetadata()["NSGEO_SITE_PIXEL_M"]) == RES.cell


def test_a_finer_export_cell_and_pixel_are_what_the_file_names(
    site3, make_site, tmp_path, open_tif
):
    """0.25 m live, exported at 0.125 m: the file is twice the width and the height,
    names the export cell and pixel, and its bands are not the live ones."""
    site = make_site(site3)
    live = tmp_path / "live.tif"
    fine = tmp_path / "fine.tif"
    export_site(site, live, 8, 24)
    export_site(site, fine, 8, 24, cell=0.125, pixel=0.125)
    a, b = open_tif(live), open_tif(fine)
    assert (b.RasterXSize, b.RasterYSize) == (2 * a.RasterXSize, 2 * a.RasterYSize)
    md = b.GetMetadata()
    assert float(md["NSGEO_SITE_CELL_M"]) == 0.125 and float(md["NSGEO_SITE_PIXEL_M"]) == 0.125
    assert md["NSGEO_SITE_RESAMPLING"] == "bilinear"
    coarse = a.GetRasterBand(1).ReadAsArray()
    finer = b.GetRasterBand(1).ReadAsArray()
    assert np.isfinite(finer).any()
    assert not np.array_equal(finer[::2, ::2], coarse, equal_nan=True)
    factors_live = json.loads(a.GetRasterBand(1).GetMetadata()["NSGEO_GRID_FACTORS"])
    factors_fine = json.loads(b.GetRasterBand(1).GetMetadata()["NSGEO_GRID_FACTORS"])
    assert factors_live != factors_fine  # normalisation was measured again at the new cell


# ---- milestone B: write_bands -----------------------------------------------
def _site_bands(plan, grids=("A", "B", "C"), fill=None):
    rng = np.random.default_rng(5)
    shape = (plan.lattice.height, plan.lattice.width)
    out = []
    for i in range(len(plan.bands)):
        a = (
            rng.normal(size=shape).astype(np.float32)
            if fill is None
            else np.full(shape, fill, np.float32)
        )
        a[:1, :] = np.nan
        out.append(ExportBand(a, {g: (1.0 + i, 0.5) for g in grids if g != "C"}))
    return out


def test_write_bands_records_the_export_cell_pixel_resampling_and_its_own_factors(
    site3, make_site, tmp_path, open_tif
):
    site = make_site(site3)
    plan = plan_of(site)
    plan = replace(plan, cell_m=0.5)
    bands = _site_bands(plan)
    path = tmp_path / "w.tif"
    GeoTiffSiteWriter().write_bands(path, plan, bands, clip=PercentileClip())
    ds = open_tif(path)
    md = ds.GetMetadata()
    assert md["NSGEO_SITE_RESAMPLING"] == "bilinear"
    assert float(md["NSGEO_SITE_CELL_M"]) == 0.5
    assert float(md["NSGEO_SITE_PIXEL_M"]) == plan.lattice.pixel
    assert md["NSGEO_SITE_TRANSFORM"] == "amp_envelope"
    assert ds.GetGeoTransform() == pytest.approx(plan.lattice.geotransform)
    for i, band in enumerate(bands):
        rb = ds.GetRasterBand(i + 1)
        assert np.array_equal(rb.ReadAsArray(), band.array, equal_nan=True)
        factors = json.loads(rb.GetMetadata()["NSGEO_GRID_FACTORS"])
        assert factors == {"A": [1.0 + i, 0.5], "B": [1.0 + i, 0.5], "C": None}
        assert rb.GetMetadata()["NSGEO_WINDOW_NS"]
        assert rb.GetDescription() == plan.bands[i].description


def test_the_site_stretch_is_the_limit_over_the_written_bands(site3, make_site, tmp_path):
    site = make_site(site3)
    plan = plan_of(site)
    bands = _site_bands(plan)
    clip = PercentileClip()
    got = GeoTiffSiteWriter().write_bands(tmp_path / "l.tif", plan, bands, clip=clip)
    assert got == limit_over_slices((b.array for b in bands), clip)


def test_a_large_site_file_is_tiled_and_gets_overviews(site3, make_site, tmp_path, open_tif):
    site = make_site(site3)
    plan = plan_of(site)
    plan = replace(
        plan,
        bands=plan.bands[:1],
        lattice=SiteLattice(0.0, 2000.0, 1.0, 1100, 1100, plan.lattice.crs),
    )
    path = tmp_path / "big.tif"
    GeoTiffSiteWriter().write_bands(path, plan, _site_bands(plan), clip=PercentileClip())
    build_overviews(path)
    rb = open_tif(path).GetRasterBand(1)
    assert rb.GetBlockSize() == [256, 256]
    assert rb.GetOverviewCount() == 2


def test_the_site_counts_companion_writes_through_the_same_writer(
    site3, make_site, tmp_path, open_tif
):
    site = make_site(site3)
    plan = plan_of(site)
    counts = replace(
        plan,
        bands=plan.bands[:1],
        method="none",
        finish=None,
        grids=tuple(replace(g, gain=1.0) for g in plan.grids),
        coverage=True,
    )
    bands = _site_bands(counts, fill=2.0)
    limit = GeoTiffSiteWriter().write_bands(
        tmp_path / "c.tif", counts, bands, clip=PercentileClip()
    )
    assert limit == pytest.approx(2.0)
    md = open_tif(tmp_path / "c.tif").GetMetadata()
    assert md["NSGEO_SITE_NORMALISATION"] == "none" and "NSGEO_SITE_INTERPOLATION" not in md
    assert md["NSGEO_SITE_RESAMPLING"] == "largest_count"  # counts are not blended


def test_an_interrupted_site_write_leaves_no_partial_and_an_old_target_alone(
    site3, make_site, tmp_path
):
    site = make_site(site3)
    plan = plan_of(site)
    bands = _site_bands(plan)
    target = tmp_path / "site.tif"
    target.write_bytes(b"previous")
    partial = partial_path(target)

    def interrupted():
        yield bands[0]
        raise ExportCancelled()

    with pytest.raises(ExportCancelled):
        try:
            GeoTiffSiteWriter().write_bands(partial, plan, interrupted(), clip=PercentileClip())
            commit_partial(partial, target)
        except BaseException:
            discard_partial(partial)
            raise
    assert target.read_bytes() == b"previous" and not partial.exists()


def test_the_site_writer_reports_each_band_and_refuses_a_wrong_count(site3, make_site, tmp_path):
    site = make_site(site3)
    plan = plan_of(site)
    bands = _site_bands(plan)
    seen: list[int] = []
    GeoTiffSiteWriter().write_bands(
        tmp_path / "p.tif", plan, bands, clip=PercentileClip(), progress_band=seen.append
    )
    assert seen == list(range(1, len(bands) + 1))
    with pytest.raises(ValueError, match="slices"):
        GeoTiffSiteWriter().write_bands(tmp_path / "q.tif", plan, bands[:-1], clip=PercentileClip())
    with pytest.raises(ValueError, match="more slices"):
        GeoTiffSiteWriter().write_bands(
            tmp_path / "r.tif", plan, bands + bands[:1], clip=PercentileClip()
        )


def test_a_mixed_site_records_each_grids_time_base_and_its_own(site3, tmp_path, open_tif):
    site3.session.site.presets["raw"] = [{"step": "dewow", "params": {}, "enabled": True}]
    site = SiteEngine(site3.session)
    try:
        site.set_source(
            SiteSource(
                transform="amp_envelope",
                grids=(site3.choice("A", "p"), site3.choice("B", "raw")),
            )
        )
        assert site.wait_until_idle(60_000)
        site.set_resolution(RES)
        path = tmp_path / "mixed.tif"
        coverage = tmp_path / "mixed_coverage.tif"
        plan = export_site(site, path, 8, 24, coverage_to=coverage)
        companion = open_tif(coverage).GetMetadata()
    finally:
        site.wait_until_idle(20_000)
        site.dispose()
    assert {g.grid_id: g.time_base for g in plan.grids} == {"A": "time_zero", "B": "radar"}
    assert companion["NSGEO_SITE_TIME_BASE"] == "mixed"
    ds = open_tif(path)
    md = ds.GetMetadata()
    assert md["NSGEO_SITE_TIME_BASE"] == "mixed"
    assert {g["grid_id"]: g["time_base"] for g in json.loads(md["NSGEO_SITE_GRIDS"])} == {
        "A": "time_zero",
        "B": "radar",
    }


def test_a_uniform_site_records_its_one_time_base(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(path)
    assert ds.GetMetadata()["NSGEO_SITE_TIME_BASE"] == "time_zero"
