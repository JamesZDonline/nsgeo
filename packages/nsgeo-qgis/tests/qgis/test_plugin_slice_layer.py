"""The active slice as a QGIS raster layer."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.render import colormap
from nsgeo.slices import CubeFrame
from nsgeo_qgis import slice_layer
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_layer import LAYER_NAME, SITE_LAYER_NAME, SliceLayer, build_shader
from qgis.core import Qgis, QgsProject, QgsSingleBandPseudoColorRenderer
from qgis.PyQt.QtGui import qAlpha, qRed

FRAME = CubeFrame(origin=(500.0, 700.0), azimuth=0.0, cell=0.5, nx=12, ny=12, crs="EPSG:32616")


@pytest.fixture
def mapped(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    sl = SliceLayer(layers)
    yield sl, session, layers, project
    sl.dispose()
    layers.detach()
    project.clear()


def _values(fill_value=5.0):
    values = np.full((FRAME.ny, FRAME.nx), fill_value, dtype=np.float32)
    values[0, :] = np.nan  # an unsurveyed row
    return values


def test_updating_creates_a_valid_layer_in_the_site_group(mapped):
    sl, _, layers, project = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="x")
    assert sl.layer is not None and sl.layer.isValid()
    assert sl.layer.width() == FRAME.nx and sl.layer.height() == FRAME.ny
    assert project.mapLayer(sl.layer.id()) is not None


def test_the_pixel_values_are_the_slice_values_not_a_rendered_picture(mapped):
    """A float raster, so a reader can query an amplitude rather than a
    colour. Spec 9.4 exports float32 with NaN nodata for the same reason."""
    sl, _, _, _ = mapped
    sl.update(_values(7.5), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    provider = sl.layer.dataProvider()
    centre = sl.layer.extent().center()
    value, ok = provider.sample(centre, 1)
    assert ok and value == pytest.approx(7.5)


def test_a_second_update_repoints_the_same_layer_at_the_new_pixels(mapped):
    """The layer is repointed at a fresh file on every tick rather than
    rebuilt, so a drag does not churn the layer tree."""
    sl, _, _, _ = mapped
    sl.update(_values(1.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    first_id = sl.layer.id()
    sl.update(_values(9.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    assert sl.layer.id() == first_id, "the layer must be updated, not replaced"
    value, ok = sl.layer.dataProvider().sample(sl.layer.extent().center(), 1)
    assert ok and value == pytest.approx(9.0)


def _update(sl, fill_value, limit=10.0):
    sl.update(
        _values(fill_value),
        FRAME,
        limit=limit,
        colormap_name="amp_heat",
        unipolar=True,
        subtitle="",
    )


def _centre(sl):
    return sl.layer.dataProvider().sample(sl.layer.extent().center(), 1)


def test_a_second_update_draws_even_when_the_open_file_cannot_be_replaced(mapped, monkeypatch):
    """Windows will not delete a file QGIS holds open, and GDAL's `Create()`
    deletes first, so rewriting the layer's own source fails there with
    "Permission denied" (found in the 0.1.0 walkthrough). Linux allows it,
    so model the rule: `Create()` raises for the layer's current source."""
    sl, _, _, _ = mapped
    real = slice_layer.gdal.GetDriverByName

    class _WindowsDriver:
        def __init__(self, driver):
            self._driver = driver

        def Create(self, path, *args, **kwargs):  # noqa: N802 -- GDAL's name
            held = sl.layer is not None and Path(sl.layer.source()).resolve()
            if Path(path).exists() and held == Path(path).resolve():
                raise RuntimeError(f"deleting {path} failed: Permission denied")
            return self._driver.Create(path, *args, **kwargs)

    monkeypatch.setattr(
        slice_layer.gdal, "GetDriverByName", lambda name: _WindowsDriver(real(name))
    )
    _update(sl, 1.0)
    _update(sl, 9.0)
    value, ok = _centre(sl)
    assert ok and value == pytest.approx(9.0)


def test_superseded_slice_files_are_removed(mapped):
    sl, _, _, _ = mapped
    for fill in (1.0, 2.0, 3.0, 4.0):
        _update(sl, fill)
    assert list(sl._dir.iterdir()) == [sl.path]
    assert sl.path.exists()


def test_a_stale_file_that_cannot_be_deleted_yet_does_not_stop_updates(mapped, monkeypatch):
    """A file can stay open briefly after the layer moves on (a render
    thread's provider clone). Deleting it is best effort, retried later."""
    sl, _, _, _ = mapped
    _update(sl, 1.0)
    stale = sl.path
    real_remove = os.remove
    refused = []

    def remove(path, *args, **kwargs):
        if Path(path) == stale and not refused:
            refused.append(path)
            raise PermissionError(13, "Permission denied", str(path))
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(slice_layer, "_remove", remove)
    _update(sl, 5.0)
    assert refused, "the stale file's deletion was never attempted"
    value, ok = _centre(sl)
    assert ok and value == pytest.approx(5.0)
    assert stale.exists()
    _update(sl, 7.0)
    assert not stale.exists()
    value, ok = _centre(sl)
    assert ok and value == pytest.approx(7.0)


def test_a_persistently_failing_update_does_not_fill_the_scratch_folder(mapped, monkeypatch):
    """Each failed tick writes a full-size file before the repoint fails.
    The scratch folder must still hold only what the layer reads."""
    sl, _, _, _ = mapped
    _update(sl, 1.0)

    def refuse(self, path):
        raise RuntimeError("cannot open")

    monkeypatch.setattr(SliceLayer, "_repoint", refuse)
    for fill in range(10):
        _update(sl, float(fill))
    assert len(list(sl._dir.iterdir())) <= 2
    assert Path(sl.layer.source()).exists()


def test_a_persistently_failing_update_from_a_corrupt_file_keeps_the_scratch_folder_bounded(
    mapped, monkeypatch
):
    """The faked test above replaces `_repoint`. Here the real one runs and
    meets a file GDAL cannot open, on every tick (#54): the folder must hold
    only the file the layer reads and the last good one `self.path` names,
    each with its sidecars, and the layer must still point at a file that
    exists."""
    sl, _, _, _ = mapped
    _update(sl, 1.0)

    def junk(self, path, *args):
        path.write_bytes(b"this is not a GeoTIFF")

    monkeypatch.setattr(SliceLayer, "_write", junk)
    for fill in range(10):
        _update(sl, float(fill))
    read = Path(sl.layer.source().split("|")[0])
    # The file the layer reads and the one `self.path` names, each with its
    # sidecars (GDAL's `.aux.xml`); nothing from the nine ticks in between.
    keep = (read.name, sl.path.name)
    assert [e.name for e in sl._dir.iterdir() if not e.name.startswith(keep)] == []
    assert len([e for e in sl._dir.iterdir() if e.suffix == ".tif"]) <= 2
    assert read.exists()
    assert not sl.layer.isValid() and read != sl.path  # the real failure shape (#54)
    assert sl.path.exists()  # the last good file: the `self.path` keep-guard


def test_a_failed_write_leaves_no_file_behind(mapped, monkeypatch):
    sl, _, _, _ = mapped
    _update(sl, 1.0)

    def fail(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(
        SliceLayer, "_write", lambda self, path, *a: (path.write_bytes(b"x"), fail())[1]
    )
    _update(sl, 2.0)
    assert list(sl._dir.iterdir()) == [sl.path]


def test_the_renderer_survives_a_repoint(mapped):
    """`setDataSource` may reset the renderer; the second update, with an
    unchanged colormap and limit, must still show the pseudocolour one."""
    sl, session, layers, _ = mapped
    session.add_grid(Grid("A", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    _update(sl, 1.0)
    layer_id = sl.layer.id()
    assert layers.group.findLayer(layer_id) is not None
    sl.layer.setName("my renamed preview")
    _update(sl, 9.0)
    assert sl.layer.name() == "my renamed preview"
    renderer = sl.layer.renderer()
    assert isinstance(renderer, QgsSingleBandPseudoColorRenderer)
    assert renderer.classificationMin() == pytest.approx(0.0)
    assert renderer.classificationMax() == pytest.approx(10.0)
    assert sl.layer.id() == layer_id
    assert layers.group.findLayer(layer_id) is not None


def test_a_cell_size_change_resizes_the_same_layer(mapped):
    """The cell slider changes nx and ny. Verified directly against this
    GDAL and QGIS: width() and height() follow a setDataSource() across a
    shape change, so there is no need to tear the layer down."""
    sl, _, _, _ = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    finer = CubeFrame(origin=(500.0, 700.0), azimuth=0.0, cell=0.25, nx=24, ny=24, crs="EPSG:32616")
    sl.update(
        np.full((24, 24), 3.0, np.float32),
        finer,
        limit=10.0,
        colormap_name="amp_heat",
        unipolar=True,
        subtitle="",
    )
    assert (sl.layer.width(), sl.layer.height()) == (24, 24)


def test_nodata_renders_transparent(mapped):
    """The check that actually works. `block.isNoData()` is False on a
    RENDERED block -- the renderer's output is ARGB, so nodata is carried
    by the ALPHA channel, and asserting isNoData here is a false pass
    (verified directly against this build).

    `_values()` sets grid-local row 0 (frame's SOUTHERN edge) to NaN.
    `to_north_up` -- Task 1, verified by its own
    `test_north_up_puts_frame_row_zero_at_the_BOTTOM_of_the_raster` --
    reverses rows so a raster's row 0 is north: grid row 0 therefore lands
    at the raster's LAST row, not its first. The brief's own draft of this
    test checked row 0 for transparency instead of row `ny - 1`, which
    would only pass if that north-up flip were silently undone -- exactly
    the defect Task 1's own docstring calls "the single most likely
    defect in this function". Fixed here rather than in `to_north_up`."""
    sl, _, _, _ = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    block = sl.layer.renderer().block(1, sl.layer.extent(), FRAME.nx, FRAME.ny)
    assert qAlpha(block.color(FRAME.ny - 1, 0)) == 0, "the unsurveyed row must be transparent"
    assert qAlpha(block.color(0, 0)) == 255


def test_the_shader_spans_zero_to_limit_for_unipolar_data(mapped):
    """Spec 8: a unipolar table maps 0 to 0 and the limit to 255, instead
    of wasting half the table and putting the data floor at mid-grey."""
    lut = colormap("amp_black_high")
    shader = build_shader(lut, limit=4.0, unipolar=True)
    items = shader.rasterShaderFunction().colorRampItemList()
    assert items[0].value == pytest.approx(0.0)
    assert items[-1].value == pytest.approx(4.0)
    assert (qRed(items[0].color.rgb()), qRed(items[-1].color.rgb())) == (
        int(lut[0, 0]),
        int(lut[255, 0]),
    )


def test_the_shader_spans_minus_limit_to_plus_limit_for_bipolar_data(mapped):
    lut = colormap("seismic")
    shader = build_shader(lut, limit=4.0, unipolar=False)
    items = shader.rasterShaderFunction().colorRampItemList()
    assert items[0].value == pytest.approx(-4.0)
    assert items[-1].value == pytest.approx(4.0)
    middle = items[len(items) // 2]
    assert abs(middle.value) < 0.05  # zero sits in the middle of a bipolar table


def test_disposing_removes_the_layer_and_the_scratch_file(mapped):
    sl, _, _, project = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    layer_id = sl.layer.id()
    path = sl.path
    sl.dispose()
    assert project.mapLayer(layer_id) is None
    assert not path.exists()


def test_the_layer_rejoins_a_new_group_after_a_site_switch(qgis_app, tmp_path):
    """Fix round 1, Important 3. `SiteLayers.detach()` runs on every
    `site_closed` (every "Open site...") and removes the group NODE
    (never the layer itself, which `SiteLayers` does not track) --
    `update()` used to only ever test `self.layer is None`, which this
    layer already was not, so it neither rejoined a later, brand-new
    group nor regained a node anywhere. Pixels kept being rewritten
    correctly; nobody could see them."""
    project = QgsProject.instance()
    project.clear()
    site1, site2 = tmp_path / "site1", tmp_path / "site2"
    site1.mkdir()
    site2.mkdir()
    session = SiteSession()
    # SiteLayers/SliceLayer built BEFORE any site opens, matching
    # plugin.py's real construction order: SiteLayers only rebuilds its
    # tables/group from `site_opened`/`grids_changed`, which have already
    # fired by the time a fixture calls new_site()/add_grid() first.
    layers = SiteLayers(session, project=project)
    sl = SliceLayer(layers)
    session.new_site(site1)
    session.add_grid(Grid("A", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    try:
        sl.update(
            _values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle=""
        )
        first_group = layers.group
        assert first_group is not None
        assert first_group.findLayer(sl.layer.id()) is not None

        session.close_site()  # SiteLayers.detach(): removes the group NODE
        session.new_site(site2)
        session.add_grid(Grid("A", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
        assert layers.group is not None
        assert layers.group is not first_group

        sl.update(
            _values(9.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle=""
        )
        assert project.mapLayer(sl.layer.id()) is not None
        assert layers.group.findLayer(sl.layer.id()) is not None
    finally:
        sl.dispose()
        layers.detach()
        project.clear()


def test_the_layer_is_recreated_after_being_removed_from_the_project(mapped):
    """Fix round 1, Important 3's other half: after
    `project.removeMapLayer(...)` -- the exact hazard
    `SiteLayers._on_layers_removed` documents -- `sip.isdeleted(self.layer)`
    is `True`, and `update()` used to keep the dead wrapper forever
    (`self.layer is None` stays `False`, so it never rebuilt)."""
    sl, _, _, project = mapped
    sl.update(_values(1.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    old_id = sl.layer.id()
    project.removeMapLayer(old_id)

    sl.update(_values(9.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    assert sl.layer is not None
    assert sl.layer.id() != old_id
    assert project.mapLayer(sl.layer.id()) is not None
    value, ok = sl.layer.dataProvider().sample(sl.layer.extent().center(), 1)
    assert ok and value == pytest.approx(9.0)


# ---- M12: the site lattice through the same layer ---------------------------

#: A 9 x 6 north-up lattice with 0.5 m pixels, west edge 500, north edge 706.
SITE_GT = (500.0, 0.5, 0.0, 706.0, 0.0, -0.5)


def test_update_north_up_renames_the_layer_in_place(mapped):
    """M12 spec 4.5: switching to the whole site renames the one preview
    layer rather than rebuilding it, so the layer tree does not churn."""
    sl, _, _, project = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    first_id = sl.layer.id()
    assert sl.layer.name() == LAYER_NAME

    site = np.full((6, 9), 4.0, dtype=np.float32)
    sl.update_north_up(
        site,
        SITE_GT,
        "EPSG:32616",
        limit=10.0,
        colormap_name="amp_heat",
        unipolar=True,
        subtitle="site",
        name=SITE_LAYER_NAME,
    )
    assert sl.layer.id() == first_id, "renamed in place, not rebuilt"
    assert sl.layer.name() == SITE_LAYER_NAME
    assert (sl.layer.width(), sl.layer.height()) == (9, 6)
    assert sl.layer.extent().xMinimum() == pytest.approx(500.0)
    assert sl.layer.extent().yMaximum() == pytest.approx(706.0)
    value, ok = sl.layer.dataProvider().sample(sl.layer.extent().center(), 1)
    assert ok and value == pytest.approx(4.0)
    assert [lyr.name() for lyr in project.mapLayers().values()].count(SITE_LAYER_NAME) == 1

    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    assert sl.layer.id() == first_id
    assert sl.layer.name() == LAYER_NAME, "This grid's update restores the name"


def test_update_north_up_follows_a_crs_change(mapped):
    """The site and a grid in another CRS share this one layer. Under
    M11's `reloadData()` the layer kept the CRS it was created with;
    0.1.0's `setDataSource` moves it (measured on QGIS 3.44.7), and
    `update_north_up` checks it either way."""
    sl, _, _, _ = mapped
    values = np.full((6, 9), 1.0, dtype=np.float32)
    kwargs = {"limit": 10.0, "colormap_name": "amp_heat", "unipolar": True, "subtitle": ""}
    sl.update_north_up(values, SITE_GT, "EPSG:32616", **kwargs)
    assert sl.layer.crs().authid() == "EPSG:32616"
    sl.update_north_up(values, SITE_GT, "EPSG:32615", **kwargs)
    assert sl.layer.crs().authid() == "EPSG:32615"


def test_the_layer_extent_follows_a_lattice_that_grows(mapped):
    """The site lattice grows as grids become ready, and QGIS draws a
    raster only inside its layer's extent. Under M11's `reloadData()` the
    layer kept the extent it was created with; 0.1.0's `setDataSource`
    moves it (measured on QGIS 3.44.7), and `update_north_up` checks it
    either way."""
    sl, _, _, _ = mapped
    kwargs = {"limit": 10.0, "colormap_name": "amp_heat", "unipolar": True, "subtitle": ""}
    sl.update_north_up(np.full((12, 12), 1.0, np.float32), SITE_GT, "EPSG:32616", **kwargs)
    assert sl.layer.extent().xMaximum() == pytest.approx(506.0)
    sl.update_north_up(np.full((12, 36), 2.0, np.float32), SITE_GT, "EPSG:32616", **kwargs)
    extent = sl.layer.extent()
    assert (extent.xMinimum(), extent.xMaximum()) == (pytest.approx(500.0), pytest.approx(518.0))
    assert (extent.yMinimum(), extent.yMaximum()) == (pytest.approx(700.0), pytest.approx(706.0))


def _site_tick(sl, fill_value, name=SITE_LAYER_NAME):
    sl.update_north_up(
        np.full((6, 9), fill_value, dtype=np.float32),
        SITE_GT,
        "EPSG:32616",
        limit=10.0,
        colormap_name="amp_heat",
        unipolar=True,
        subtitle="site",
        name=name,
    )


def test_the_site_path_never_rewrites_the_file_the_layer_reads(mapped, monkeypatch):
    """The merge of M12 onto 0.1.0: the site lattice reaches the map through
    `update_north_up`, so it must keep 0.1.0's Windows rule too -- a fresh
    file per tick, and nothing left behind but the file the layer reads.
    `Create()` is made to refuse the layer's current source, as Windows
    does, exactly as the This-grid test above models it."""
    sl, _, _, _ = mapped
    real = slice_layer.gdal.GetDriverByName
    refused = []

    class _WindowsDriver:
        def __init__(self, driver):
            self._driver = driver

        def Create(self, path, *args, **kwargs):  # noqa: N802 -- GDAL's name
            held = sl.layer is not None and Path(sl.layer.source()).resolve()
            if Path(path).exists() and held == Path(path).resolve():
                refused.append(path)
                raise RuntimeError(f"deleting {path} failed: Permission denied")
            return self._driver.Create(path, *args, **kwargs)

    monkeypatch.setattr(
        slice_layer.gdal, "GetDriverByName", lambda name: _WindowsDriver(real(name))
    )
    _update(sl, 1.0)
    for fill_value in (3.0, 4.0, 6.0):
        _site_tick(sl, fill_value)
    assert not refused
    assert list(sl._dir.iterdir()) == [sl.path]
    assert sl.layer.name() == SITE_LAYER_NAME
    value, ok = _centre(sl)
    assert ok and value == pytest.approx(6.0)


def test_a_user_rename_survives_site_ticks_but_a_scope_switch_renames(mapped):
    """0.1.0 keeps a user's rename across ticks; M12 renames the layer when
    the scope changes. Both hold: the name is reapplied only when the
    requested one differs from the name this class last gave."""
    sl, _, _, _ = mapped
    _update(sl, 1.0)
    _site_tick(sl, 2.0)
    assert sl.layer.name() == SITE_LAYER_NAME
    sl.layer.setName("my site view")
    _site_tick(sl, 3.0)
    assert sl.layer.name() == "my site view", "a site tick keeps the user's name"
    _update(sl, 4.0)
    assert sl.layer.name() == LAYER_NAME, "leaving the site renames"
    _site_tick(sl, 5.0)
    assert sl.layer.name() == SITE_LAYER_NAME, "entering the site renames"


def _drawn(sl):
    provider = sl.layer.dataProvider()
    block = provider.block(1, sl.layer.extent(), sl.layer.width(), sl.layer.height())
    return np.array(
        [[block.value(r, c) for c in range(block.width())] for r in range(block.height())]
    )


def test_a_rotated_coverage_view_draws_only_whole_counts(mapped):
    """`counts=True` takes the largest corner count, never a blend; the
    same input drawn with counts=False is blended, which is what this pins
    against (a hard-coded False would blend the counts)."""
    sl, _, _, _ = mapped
    frame = CubeFrame(origin=(500.0, 700.0), azimuth=30.0, cell=0.5, nx=16, ny=12, crs="EPSG:32616")
    counts = np.random.default_rng(2).integers(1, 5, size=(frame.ny, frame.nx)).astype(np.float32)
    kwargs = {"limit": 5.0, "colormap_name": "amp_heat", "unipolar": True, "subtitle": ""}
    sl.update(counts, frame, counts=True, **kwargs)
    whole = _drawn(sl)
    finite = whole[np.isfinite(whole) & (whole > -1e30)]
    assert finite.size > 0
    np.testing.assert_array_equal(finite, np.round(finite))
    sl.update(counts, frame, counts=False, **kwargs)
    blended = _drawn(sl)
    blended = blended[np.isfinite(blended) & (blended > -1e30)]
    assert (blended != np.round(blended)).any()


def _smooth(layer) -> bool:
    resampler = layer.resampleFilter().zoomedInResampler()
    return resampler is not None and resampler.type() == "bilinear"


def test_the_slice_layer_is_drawn_smooth_after_every_repoint(mapped):
    """`setDataSource` can rebuild the pipe, so the resampler is set on
    every tick, not once when the layer is made."""
    sl, _, _, _ = mapped
    kwargs = {"limit": 10.0, "colormap_name": "amp_heat", "unipolar": True, "subtitle": ""}
    sl.update(_values(), FRAME, **kwargs)
    assert _smooth(sl.layer)
    sl.layer.resampleFilter().setZoomedInResampler(None)  # as a rebuilt pipe would
    assert not _smooth(sl.layer)
    sl.update(_values(6.0), FRAME, **kwargs)
    assert _smooth(sl.layer)
    sl.layer.setResamplingStage(Qgis.RasterResamplingStage.Provider)
    sl.update(_values(7.0), FRAME, **kwargs)
    assert _smooth(sl.layer)
    assert sl.layer.resamplingStage() == Qgis.RasterResamplingStage.ResampleFilter


def test_the_site_layer_is_drawn_smooth_after_every_repoint(mapped):
    sl, _, _, _ = mapped
    kwargs = {
        "limit": 10.0,
        "colormap_name": "amp_heat",
        "unipolar": True,
        "subtitle": "",
        "name": SITE_LAYER_NAME,
    }
    site = np.full((6, 9), 4.0, dtype=np.float32)
    sl.update_north_up(site, SITE_GT, "EPSG:32616", **kwargs)
    assert _smooth(sl.layer)
    sl.layer.resampleFilter().setZoomedInResampler(None)
    sl.update_north_up(site + 1, SITE_GT, "EPSG:32616", **kwargs)
    assert _smooth(sl.layer)


# ---- #180: the user's own colours ------------------------------------------------------


def _ramp(fill_from, fill_to):
    values = np.tile(np.linspace(fill_from, fill_to, FRAME.nx, dtype=np.float32), (FRAME.ny, 1))
    values[0, :] = np.nan
    return values


def _own_tick(sl, values, style=None, palette="seismic", limit=5.0, unipolar=False):
    sl.update(
        values,
        FRAME,
        limit=limit,
        colormap_name=palette,
        unipolar=unipolar,
        subtitle="",
        own=True,
        own_style=style,
    )


def _range(sl):
    from nsgeo_qgis.own_colours import style_range

    return style_range(sl.layer)


def _computed(sl, limits, extent=None):
    """As if the user picked a computed min/max in Layer Properties."""
    from qgis.core import QgsRasterMinMaxOrigin

    shown = sl.layer.renderer()
    renderer = shown.clone()
    # As the Symbology page builds it: with its range (a clone drops it).
    renderer.setClassificationMin(shown.classificationMin())
    renderer.setClassificationMax(shown.classificationMax())
    origin = renderer.minMaxOrigin()
    origin.setLimits(limits)
    origin.setExtent(extent or QgsRasterMinMaxOrigin.Extent.WholeRaster)
    origin.setStatAccuracy(QgsRasterMinMaxOrigin.StatAccuracy.Exact)
    renderer.setMinMaxOrigin(origin)
    sl.layer.setRenderer(renderer)


def test_own_colours_start_from_the_plugin_palette_and_report_the_style(mapped):
    from nsgeo_qgis.own_colours import style_text
    from qgis.core import QgsRasterMinMaxOrigin

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0))
    renderer = sl.layer.renderer()
    assert isinstance(renderer, QgsSingleBandPseudoColorRenderer)
    assert renderer.minMaxOrigin().limits() == QgsRasterMinMaxOrigin.Limits.NotSet
    assert _range(sl) == (-5.0, 5.0)
    assert seen == [style_text(sl.layer)]


def test_a_given_style_is_applied_and_kept_across_ticks(mapped):
    from nsgeo_qgis.own_colours import seed_style, style_text

    sl, _, _, _ = mapped
    _update(sl, 1.0, limit=8.0)
    seed_style(sl.layer, "amp_heat", 2.5, True)
    mine = style_text(sl.layer)
    _update(sl, 1.0)  # the plugin's colours again, at a new limit
    assert _range(sl) == (0.0, 10.0)
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(0.0, 9.0), style=mine)
    assert _range(sl) == (0.0, 2.5)
    _own_tick(sl, _ramp(0.0, 4.0), style=mine)
    assert _range(sl) == (0.0, 2.5)
    assert seen == [], "applying the user's own style is not an edit"


def test_a_computed_range_is_worked_out_on_every_new_slice(mapped):
    from qgis.core import QgsRasterMinMaxOrigin

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0))
    _computed(sl, QgsRasterMinMaxOrigin.Limits.MinimumMaximum)
    style = seen[-1]
    _own_tick(sl, _ramp(-1.0, 7.0), style=style)
    assert _range(sl) == pytest.approx((-1.0, 7.0))
    _own_tick(sl, _ramp(2.0, 4.0), style=style)
    assert _range(sl) == pytest.approx((2.0, 4.0))


def test_the_users_edit_is_reported_once_and_not_undone(mapped):
    from nsgeo_qgis.own_colours import set_range, style_text

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0))
    assert len(seen) == 1
    set_range(sl.layer, -2.0, 5.0)  # as Layer Properties ▸ Apply would
    assert seen[-1] == style_text(sl.layer)
    edited = seen[-1]
    _own_tick(sl, _ramp(-9.0, 9.0), style=edited)
    _own_tick(sl, _ramp(-9.0, 9.0), style=edited)
    assert _range(sl) == pytest.approx((-2.0, 5.0))
    assert seen.count(edited) == 1 and len(seen) == 2


def test_the_plugin_colours_do_not_report_edits(mapped):
    from nsgeo_qgis.own_colours import set_range

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _update(sl, 1.0)
    set_range(sl.layer, -2.0, 5.0)
    _update(sl, 2.0)
    assert seen == []


def test_switching_back_to_own_colours_restores_the_style(mapped):
    from nsgeo_qgis.own_colours import set_range

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0))
    set_range(sl.layer, -2.0, 5.0)
    mine = seen[-1]
    _update(sl, 1.0)  # Show coverage, or the plugin's colours
    assert _range(sl) == (0.0, 10.0)
    _own_tick(sl, _ramp(-3.0, 3.0), style=mine)
    assert _range(sl) == pytest.approx((-2.0, 5.0))


def test_a_recreated_layer_gets_the_style_back(mapped):
    from nsgeo_qgis.own_colours import set_range

    sl, _, _, project = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0))
    set_range(sl.layer, -2.0, 5.0)
    mine = seen[-1]
    project.removeMapLayer(sl.layer.id())
    _own_tick(sl, _ramp(-3.0, 3.0), style=mine)
    assert _range(sl) == pytest.approx((-2.0, 5.0))
    set_range(sl.layer, -1.0, 1.0)
    assert seen[-1] != mine, "the new layer's edits are heard too"


def test_an_unreadable_saved_style_falls_back_to_the_plugin_palette(mapped):
    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0), style="<not a style")
    assert _range(sl) == (-5.0, 5.0)
    assert len(seen) == 1 and seen[0] != "<not a style"


def test_the_users_resampling_survives_a_tick(mapped):
    from qgis.core import QgsCubicRasterResampler

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0))
    sl.layer.resampleFilter().setZoomedInResampler(QgsCubicRasterResampler())
    sl.layer.emitStyleChanged()  # Layer Properties applies, then says so
    _own_tick(sl, _ramp(-3.0, 3.0), style=seen[-1])
    assert sl.layer.resampleFilter().zoomedInResampler().type() == "cubic"


def test_the_site_path_takes_own_colours_too(mapped):
    from qgis.core import QgsRasterMinMaxOrigin

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    kwargs = {"limit": 4.0, "colormap_name": "seismic", "unipolar": False, "subtitle": ""}
    site = np.tile(np.linspace(-1.0, 3.0, 9, dtype=np.float32), (6, 1))
    sl.update_north_up(site, SITE_GT, "EPSG:32616", name=SITE_LAYER_NAME, own=True, **kwargs)
    assert _range(sl) == (-4.0, 4.0)
    _computed(sl, QgsRasterMinMaxOrigin.Limits.MinimumMaximum)
    sl.update_north_up(
        site * 2,
        SITE_GT,
        "EPSG:32616",
        name=SITE_LAYER_NAME,
        own=True,
        own_style=seen[-1],
        **kwargs,
    )
    assert _range(sl) == pytest.approx((-2.0, 6.0))


def test_current_canvas_reads_the_view_it_is_given(mapped):
    from qgis.core import QgsRasterMinMaxOrigin

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    asked = []

    def view(crs):
        asked.append(crs.authid())
        return (500.0, 700.0, 503.0, 706.0)  # the frame's west half

    sl.extent_in = view
    _own_tick(sl, _ramp(0.0, 11.0))
    _computed(
        sl,
        QgsRasterMinMaxOrigin.Limits.MinimumMaximum,
        QgsRasterMinMaxOrigin.Extent.FixedCanvas,
    )
    _own_tick(sl, _ramp(0.0, 11.0), style=seen[-1])
    assert asked and asked[-1] == "EPSG:32616"
    assert _range(sl) == pytest.approx((0.0, 5.0))


def test_leaving_own_colours_puts_back_the_plain_layer(mapped):
    """Review finding 1: the palette must not be drawn through the user's
    brightness, saturation or blending."""
    from qgis.PyQt.QtGui import QPainter

    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0))
    sl.layer.brightnessFilter().setBrightness(-80)
    sl.layer.hueSaturationFilter().setSaturation(-100)
    sl.layer.setBlendMode(QPainter.CompositionMode.CompositionMode_Multiply)
    sl.layer.emitStyleChanged()
    mine = seen[-1]
    _update(sl, 1.0)
    assert sl.layer.brightnessFilter().brightness() == 0
    assert sl.layer.hueSaturationFilter().saturation() == 0
    assert sl.layer.blendMode() == QPainter.CompositionMode.CompositionMode_SourceOver
    assert _range(sl) == (0.0, 10.0) and _smooth(sl.layer)
    _own_tick(sl, _ramp(-3.0, 3.0), style=mine)
    assert sl.layer.brightnessFilter().brightness() == -80
    assert sl.layer.hueSaturationFilter().saturation() == -100


def test_a_scope_without_a_style_starts_its_own(mapped):
    """Review finding 2: the other scope's own style already on the layer is
    not this scope's; a style of None seeds afresh, at this scope's limit."""
    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0), limit=5.0)
    site = np.tile(np.linspace(-1.0, 3.0, 9, dtype=np.float32), (6, 1))
    sl.update_north_up(
        site,
        SITE_GT,
        "EPSG:32616",
        limit=40.0,
        colormap_name="seismic",
        unipolar=False,
        subtitle="",
        name=SITE_LAYER_NAME,
        own=True,
        own_style=None,
    )
    assert _range(sl) == (-40.0, 40.0)
    assert len(seen) == 2 and seen[0] != seen[1]


def test_the_limit_is_read_only_when_it_is_needed(mapped):
    """The shared stretch is a pass over the whole cube: under the user's own
    colours it is read only to start their style."""
    sl, _, _, _ = mapped
    seen, asked = [], []

    def limit():
        asked.append(1)
        return 5.0

    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0), limit=limit)
    assert len(asked) == 1 and _range(sl) == (-5.0, 5.0)
    _own_tick(sl, _ramp(-3.0, 3.0), style=seen[-1], limit=limit)
    _own_tick(sl, _ramp(-1.0, 1.0), style=seen[-1], limit=limit)
    assert len(asked) == 1
    _update(sl, 1.0, limit=limit)
    assert len(asked) == 2 and _range(sl) == (0.0, 5.0)


def test_an_unreadable_style_starts_again_from_the_real_limit(mapped):
    """Review finding 3: the plugin sends the limit as a callable, so the
    fallback seed is drawn at the palette's real limit, not a placeholder."""
    sl, _, _, _ = mapped
    seen = []
    sl.own_style_changed.connect(seen.append)
    _own_tick(sl, _ramp(-3.0, 3.0), style="<not a style", limit=lambda: 7.0)
    assert _range(sl) == (-7.0, 7.0)
    assert len(seen) == 1
