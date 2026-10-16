"""The site GeoTIFF: one file over every included grid, which records what was done."""

from __future__ import annotations

import json

import numpy as np
import pytest
from nsgeo.slices import window_depths_m, window_on, window_times_ns
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.site_engine import SiteEngine
from nsgeo_qgis.site_export import (
    GeoTiffSiteWriter,
    apply_site_temporal_properties,
    band_window_ns,
    export_site,
    plan_site_export,
    write_site_coverage,
)
from nsgeo_qgis.slice_export import GeoTiffSliceWriter, band_time_range
from nsgeo_qgis.slices_plan import Resolution
from osgeo import gdal
from qgis.core import QgsRasterLayer

RES = Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=60.0)
V_A = VelocityModel(layers=((0.0, 0.10),))
V_B = VelocityModel(layers=((0.0, 0.08), (10.0, 0.12)))
KW = {
    "transform": "amp_envelope",
    "method": "edge",
    "radius_spacings": 1.5,
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


def exported(make_site, site3, tmp_path, thickness=8, step=24, **overrides):
    site = make_site(site3)
    path = tmp_path / "site.tif"
    kwargs = {**KW, **overrides}
    plan = export_site(site, path, thickness, step, **kwargs)
    return site, plan, path


def pull(site, plan, band, **overrides):
    kw = {**KW, **overrides}
    lo, hi = window_times_ns(plan.site_z, band.window)
    top = plan.site_z.t0_ns + band.window.k0 * plan.site_z.dz_ns
    thickness = band.window.n_levels * plan.site_z.dz_ns
    return site.slice_at(
        top,
        thickness,
        radius_spacings=kw["radius_spacings"],
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


def test_each_band_is_exactly_what_slice_at_shows(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(path)
    for i, band in enumerate(plan.bands):
        expected = pull(site, plan, band).array
        got = ds.GetRasterBand(i + 1).ReadAsArray()
        assert np.array_equal(np.isnan(got), np.isnan(expected))
        assert np.array_equal(got, expected, equal_nan=True)
    assert np.isfinite(got).any()


def test_the_dataset_records_transform_method_and_every_grid(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    md = open_tif(path).GetMetadata()
    assert md["NSGEO_SITE_TRANSFORM"] == "amp_envelope"
    assert md["NSGEO_SITE_NORMALISATION"] == "edge"
    assert float(md["NSGEO_SITE_CELL_M"]) == 0.25
    assert float(md["NSGEO_SITE_PIXEL_M"]) == site.lattice.pixel
    assert float(md["NSGEO_SITE_FILL_RADIUS_SPACINGS"]) == 1.5
    assert md["NSGEO_SITE_Z_UNIT"] == "ns"
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
    plan = plan_site_export(site, 8, 3, **KW)
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


def test_export_never_builds_a_resident_cube(site3, make_site, tmp_path):
    site = make_site(site3)
    live = 0
    peak = 0
    real = site.slice_at

    def counted(*a, **k):
        nonlocal live
        live += 1
        return real(*a, **k)

    site.slice_at = counted  # type: ignore[method-assign]

    class Stub:
        def write(self, path, plan, slices):
            nonlocal live, peak
            n = 0
            for _ in slices:
                # Pulled lazily: exactly one slice per band consumed so far.
                n += 1
                peak = max(peak, live - n)
            assert n == len(plan.bands)

    plan = export_site(site, tmp_path / "s.tif", 8, 24, writer=Stub(), **KW)
    assert live == len(plan.bands)
    assert peak == 0
    assert all(site.engine_for(g).mode != "resident" for g in "ABC")


def test_the_coverage_companion_is_written_beside_it(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    out = write_site_coverage(site, path, plan)
    assert out == tmp_path / "site_coverage.tif"
    ds = open_tif(out)
    assert ds.RasterCount == 1
    assert (ds.RasterXSize, ds.RasterYSize) == (site.lattice.width, site.lattice.height)
    assert ds.GetGeoTransform() == pytest.approx(site.lattice.geotransform)
    arr = ds.GetRasterBand(1).ReadAsArray()
    top, thickness = band_window_ns(plan.site_z, plan.bands[0].window)
    counts = site.slice_at(
        top, thickness, radius_spacings=1.5, method="none", manual={}, coverage=True
    ).array
    assert np.array_equal(arr, counts, equal_nan=True)
    finite = arr[np.isfinite(arr)]
    assert finite.size and (finite >= 1).all() and (finite == np.round(finite)).all()
    assert np.isnan(ds.GetRasterBand(1).GetNoDataValue())


def test_the_coverage_companion_does_not_claim_processing_it_never_had(
    site3, make_site, tmp_path, open_tif
):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(write_site_coverage(site, path, plan))
    md = ds.GetMetadata()
    assert md["NSGEO_SITE_NORMALISATION"] == "none"
    assert "NSGEO_SITE_FILL_RADIUS_SPACINGS" not in md
    assert [g["gain"] for g in json.loads(md["NSGEO_SITE_GRIDS"])] == [1.0, 1.0, 1.0]
    factors = json.loads(ds.GetRasterBand(1).GetMetadata()["NSGEO_GRID_FACTORS"])
    assert all(f == [1.0, 0.0] for f in factors.values())
    # the values file keeps what it did
    main = open_tif(path).GetMetadata()
    assert main["NSGEO_SITE_NORMALISATION"] == "edge"
    assert "NSGEO_SITE_FILL_RADIUS_SPACINGS" in main


def test_every_band_is_nodata_nan_on_read_back(site3, make_site, tmp_path, open_tif):
    site, plan, path = exported(make_site, site3, tmp_path)
    ds = open_tif(path)
    for i in range(1, ds.RasterCount + 1):
        assert np.isnan(ds.GetRasterBand(i).GetNoDataValue())


def test_a_ready_grid_with_no_site_axis_exports_as_absent(
    site3_factory, make_site, tmp_path, open_tif
):
    """R-P3: C ends at ~16.4 ns, so at t0=16 it has no axis (frame and z are None)."""
    site3 = site3_factory(samples={"C": 128})
    site = SiteEngine(site3.session)
    try:
        site.set_source(site3.source())
        assert site.wait_until_idle(60_000)
        site.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=16.0, t1_ns=60.0))
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


def test_the_writer_reuses_m11s_creation_options():
    assert GeoTiffSiteWriter.OPTIONS is GeoTiffSliceWriter.OPTIONS


def test_the_writer_refuses_a_wrong_number_of_slices(site3, make_site, tmp_path):
    site = make_site(site3)
    plan = plan_site_export(site, 8, 24, **KW)
    writer = GeoTiffSiteWriter()
    with pytest.raises(ValueError, match="slices"):
        writer.write(tmp_path / "a.tif", plan, iter([pull(site, plan, plan.bands[0])]))
    slices = [pull(site, plan, b) for b in plan.bands]
    with pytest.raises(ValueError, match="more slices"):
        writer.write(tmp_path / "b.tif", plan, iter([*slices, slices[0]]))


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
    plan = export_site(site, other, 8, 24, left_out=left, **KW)
    md = open_tif(other).GetMetadata()
    assert md["NSGEO_SITE_LEFT_OUT"] == '{"D":"no lines","E":"failed: no line could be prepared"}'
    companion = open_tif(write_site_coverage(site, other, plan)).GetMetadata()
    assert json.loads(companion["NSGEO_SITE_LEFT_OUT"]) == left
