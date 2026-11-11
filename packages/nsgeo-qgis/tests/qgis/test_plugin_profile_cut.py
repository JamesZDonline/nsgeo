"""A cut in the profile panel: its section, title, axes and chrome (cut spec §4.3, §4.4)."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import colormap, section_rgba8
from nsgeo_qgis.cut_sections import NO_CUBE_TEXT, NO_SOURCE_TEXT, CutSection
from nsgeo_qgis.render.qimage import rgba_to_qimage
from nsgeo_qgis.ui.profile_dock import PALETTE_ON_CUT_TIP, ProfileDock
from qgis.PyQt.QtWidgets import QMessageBox
from test_plugin_cut_sections import H, shown, site, whole_site  # noqa: F401 -- fixtures
from test_plugin_slices_dock import _ready


@pytest.fixture
def profile(shown):  # noqa: F811
    dock, session, sections = shown
    pd = ProfileDock(session)
    pd.set_cut_sections(sections)
    dock.window_changed.connect(pd.set_slice_band)
    yield pd, dock, session, sections
    pd.hide()
    pd.deleteLater()


def _load(session, key=None):
    key = key or session.keys()[0]
    session.set_profiles(key, session.line_for_key(key).load())
    return key


def test_opening_a_cut_draws_its_section_with_its_title_and_axes(profile):
    pd, dock, session, sections = profile
    key = session.add_cut("A", [(5.0, 1.0), (1.0, 1.0)])  # drawn east to west
    held = dict(pd._held)
    session.open_line(key)
    got = sections.section(key, build_cube=True)
    assert isinstance(got, CutSection)
    assert pd.windowTitle() == "nsgeo Profile · cut: Cut 1 · A · 4.0 m · Kriging"
    t = pd.view.transform
    assert t.n_traces == got.columns.distance_m.size and t.n_samples == got.z.nz
    assert pd.view._distance[0] == 0.0 and pd.view._distance[-1] == pytest.approx(4.0)
    assert pd.view._direction == 1  # never mirrored (cut spec call 5)
    assert pd.view.ruler is None and not t.mirrored
    assert pd._held == held
    assert pd.view._image is not None
    assert (t.t0_ns, t.dt_ns) == (got.z.t0_ns, got.z.dz_ns)


def test_whole_site_scope_says_not_normalised(site):  # noqa: F811
    session = site.session
    key = session.add_cut("B", H)
    whole_site(site)
    session.open_line(key)
    assert site.profile_dock.windowTitle() == (
        "nsgeo Profile · cut: Cut 1 · B · 4.0 m · Kriging · site view, not normalised"
    )


def test_a_preview_has_the_preview_prefix_and_builds_nothing(profile):
    pd, dock, session, sections = profile
    key = session.add_cut("A", H)
    dock.engine.drop_cube()
    session.set_preview(key, 3)
    assert pd.windowTitle().startswith("nsgeo Profile · PREVIEW: cut: Cut 1")
    assert pd.view._message == NO_CUBE_TEXT.format(name="Cut 1", grid="A")
    assert not dock.engine.has_cube
    assert pd.view._image is None
    # With the cube there, a preview draws the section and still builds nothing.
    sections.section(key, build_cube=True)
    session.set_preview(None)
    session.set_preview(key, 4)
    assert pd.view._image is not None
    assert pd.windowTitle() == "nsgeo Profile · PREVIEW: cut: Cut 1 · A · 4.0 m · Kriging"


def test_no_source_shows_the_message_in_the_view(profile):
    pd, dock, session, sections = profile
    key = session.add_cut("B", H)  # B is not the shown grid
    session.open_line(key)
    assert pd.view._message == NO_SOURCE_TEXT.format(name="Cut 1", grid="B")
    assert pd.view._image is None
    assert pd.view.transform is None
    assert "cut: Cut 1" in pd.windowTitle()


def test_a_squared_cube_draws_in_the_slices_palette_with_blank_columns_transparent(profile):
    pd, dock, session, sections = profile
    dock.transform_combo.set_value("amp_square")
    _ready(dock)
    dock.palette_combo.setCurrentText("amp_black_high")
    line = _load(session)
    pd.colormap_combo.setCurrentIndex(1)
    chosen = pd.colormap_combo.currentText()
    session.open_line(line)
    assert pd.colormap_combo.isEnabled()
    key = session.add_cut("A", [(1.0, 1.0), (8.0, 1.0)])  # runs off the 6 m grid
    session.open_line(key)
    got = sections.section(key, build_cube=True)
    assert got.source.unipolar and got.source.palette == "amp_black_high"
    assert not pd.colormap_combo.isEnabled()
    assert pd.colormap_combo.toolTip() == PALETTE_ON_CUT_TIP
    expected = section_rgba8(got.values, pd.percentile, colormap("amp_black_high"), unipolar=True)
    image = pd.view._image
    assert image == rgba_to_qimage(expected)
    inside = np.flatnonzero(got.columns.cells >= 0)
    outside = np.flatnonzero(got.columns.cells < 0)
    assert inside.size and outside.size
    k = got.z.nz // 2
    finite_col = int(inside[np.flatnonzero(np.isfinite(got.values[k, inside]))[0]])
    pixel = image.pixelColor(finite_col, k)
    assert pixel.alpha() == 255
    assert (pixel.red(), pixel.green(), pixel.blue()) == tuple(
        int(v) for v in expected[k, finite_col, :3]
    )
    for col in outside[:3]:
        assert image.pixelColor(int(col), k).alpha() == 0
    # Opening a line gives the combo back, with the choice it had.
    session.open_line(line)
    assert pd.colormap_combo.isEnabled() and pd.colormap_combo.toolTip() == ""
    assert pd.colormap_combo.currentText() == chosen


def test_the_percentile_slider_still_applies_to_a_cut(profile):
    pd, dock, session, sections = profile
    key = session.add_cut("A", H)
    session.open_line(key)
    got = sections.section(key, build_cube=True)
    pd.percentile_slider.setValue(900)
    expected = section_rgba8(
        got.values, 90.0, colormap(got.source.palette), unipolar=got.source.unipolar
    )
    assert pd.view._image == rgba_to_qimage(expected)


def test_the_slice_band_shows_on_a_cut(profile):
    pd, dock, session, sections = profile
    key = session.add_cut("A", H)
    session.open_line(key)
    dock.window_changed.emit(12.0, 14.0)
    assert pd.view._slice_band == (12.0, 14.0)  # a cut is on the cube's clock: not converted


def test_the_depth_axis_uses_the_cut_velocity(profile):
    pd, dock, session, sections = profile
    key = session.add_cut("A", H)
    session.open_line(key)
    assert pd.view._velocity == session.cut_velocity("A")


def test_a_section_change_redraws_the_shown_cut(profile, monkeypatch):
    pd, dock, session, sections = profile
    key = session.add_cut("A", H)
    other = session.add_cut("A", [(1.0, 2.0), (4.0, 2.0)])
    session.open_line(key)
    shown_calls = []
    real = pd._show_cut
    monkeypatch.setattr(pd, "_show_cut", lambda k, **kw: (shown_calls.append(k), real(k, **kw))[1])
    sections.section_changed.emit(other)
    assert shown_calls == []
    sections.section_changed.emit(key)
    assert shown_calls == [key]


def test_velocity_is_greyed_on_a_cut_and_back_on_a_line(fake_iface, tmp_path, answer_modal):
    from test_plugin_loads import _plugin_with_one_line

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin, line = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        session = plugin.session
        assert plugin.act_velocity.isEnabled()
        cut = session.add_cut("A", [(1.0, 1.0), (4.0, 1.0)])
        session.open_line(cut)
        assert not plugin.act_velocity.isEnabled()
        from nsgeo_qgis.plugin import VELOCITY_ON_CUT_TIP

        assert plugin.act_velocity.toolTip() == VELOCITY_ON_CUT_TIP
        assert plugin.act_pick.isEnabled()
        session.open_line(line)
        assert plugin.act_velocity.isEnabled()
        assert plugin.act_velocity.toolTip() != VELOCITY_ON_CUT_TIP
    finally:
        plugin.unload()
