"""The active slice as a QGIS raster layer."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.render import colormap
from nsgeo.slices import CubeFrame
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_layer import SliceLayer, build_shader
from qgis.core import QgsProject
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


def test_a_second_update_refreshes_the_pixels_in_place(mapped):
    """The layer is rewritten and reloaded on every tick rather than
    rebuilt, so a drag does not churn the layer tree. Measured: the
    rewrite plus reloadData is ~2.8 ms at 300x300."""
    sl, _, _, _ = mapped
    sl.update(_values(1.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    first_id = sl.layer.id()
    sl.update(_values(9.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    assert sl.layer.id() == first_id, "the layer must be updated, not replaced"
    value, ok = sl.layer.dataProvider().sample(sl.layer.extent().center(), 1)
    assert ok and value == pytest.approx(9.0)


def test_a_cell_size_change_resizes_the_same_layer(mapped):
    """The cell slider changes nx and ny. Verified directly against this
    GDAL and QGIS: width() and height() follow a reloadData() across a
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
