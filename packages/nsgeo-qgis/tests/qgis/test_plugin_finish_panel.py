"""The Interpolation panel (interpolation spec §8)."""

from __future__ import annotations

import pytest
from nsgeo_qgis.slices_plan import METHOD_LABELS, SliceFinish
from nsgeo_qgis.ui.finish_panel import FinishPanel, busy_cursor
from plugin_testing import connect_message_log
from qgis.PyQt.QtWidgets import QApplication


@pytest.fixture
def panel(qgis_app):
    p = FinishPanel(metres_label=True)
    yield p
    p.deleteLater()


def _record(panel):
    got = []
    panel.edited.connect(lambda field, value: got.append((field, value)))
    return got


def test_the_panel_starts_at_the_defaults(panel):
    assert panel.title() == "Interpolation"
    assert panel.value() == SliceFinish()
    labels = [panel.method_combo.itemText(i) for i in range(panel.method_combo.count())]
    assert labels == list(METHOD_LABELS.values())
    keys = [panel.method_combo.itemData(i) for i in range(panel.method_combo.count())]
    assert keys == list(METHOD_LABELS)


def test_the_spins_have_the_pinned_ranges_steps_and_suffixes(panel):
    d = panel.max_distance_spin
    assert (d.minimum(), d.maximum(), d.decimals(), d.singleStep()) == (0.0, 10.0, 2, 0.25)
    assert d.suffix() == " × line spacing"
    for spin in (panel.smooth_x_spin, panel.smooth_y_spin):
        assert (spin.minimum(), spin.maximum(), spin.decimals(), spin.singleStep()) == (
            0.0,
            5.0,
            2,
            0.05,
        )
        assert spin.suffix() == " m"


def test_set_value_is_quiet_and_round_trips(panel):
    got = _record(panel)
    want = SliceFinish("idw", 1.25, 0.3, 0.45)
    panel.set_value(want)
    assert got == []
    assert panel.value() == want


def test_a_user_edit_emits_the_field_and_value(panel):
    got = _record(panel)
    panel.method_combo.setCurrentIndex(panel.method_combo.findData("idw"))
    panel.max_distance_spin.setValue(1.25)  # off the 0.75 default, so it is an edit
    panel.smooth_x_spin.setValue(0.3)
    panel.smooth_y_spin.setValue(0.4)
    assert got == [
        ("method", "idw"),
        ("max_distance_spacings", 1.25),
        ("smooth_x_m", 0.3),
        ("smooth_y_m", 0.4),
    ]


def test_max_distance_is_disabled_for_none(panel):
    assert panel.max_distance_spin.isEnabled()
    panel.method_combo.setCurrentIndex(panel.method_combo.findData("none"))
    assert not panel.max_distance_spin.isEnabled()
    panel.set_value(SliceFinish("kriging"))
    assert panel.max_distance_spin.isEnabled()
    panel.set_value(SliceFinish("none"))
    assert not panel.max_distance_spin.isEnabled()


def test_the_metres_label_follows_the_spacing(panel):
    panel.set_spacing(0.5)
    assert panel.max_distance_metres.text() == "= 0.375 m"
    panel.max_distance_spin.setValue(1.0)
    assert panel.max_distance_metres.text() == "= 0.5 m"
    panel.set_spacing(None)
    assert panel.max_distance_metres.text() == ""


def test_there_is_no_metres_label_unless_asked_for(qgis_app):
    p = FinishPanel(metres_label=False)
    assert not hasattr(p, "max_distance_metres")
    p.set_spacing(0.5)  # a no-op, not an error


def test_the_tooltips_are_the_pinned_copy(panel):
    assert panel.method_combo.toolTip() == (
        "How cells that no line crossed are filled from the cells around them.\n"
        "Kriging: a weighted average that follows how values vary with distance; "
        "the usual choice.\n"
        "Inverse distance: a weighted average in which nearer cells count more.\n"
        "Minimum curvature: the smoothest surface through the lines. It carries the trend on past "
        "the outer lines, so grid edges and seams can show values beyond the data. It is slower, "
        "so at a fine cell you see kriging while the depth moves and minimum curvature once it "
        "rests.\n"
        "None: show only the cells a line crossed."
    )
    assert panel.max_distance_spin.toolTip() == (
        "Cells farther than this from any line are left blank, so the edge of the survey or a "
        "missing line is never filled in.\n"
        "Three quarters of a line spacing closes the gap between neighbouring lines, with room "
        "for a line that wandered; lower it toward half a spacing to fill less, or raise it if a "
        "line strayed and left a blank stripe."
    )
    for axis, spin in (("X", panel.smooth_x_spin), ("Y", panel.smooth_y_spin)):
        assert spin.toolTip() == (
            f"Blurs the slice along the grid's {axis} axis by this distance (the standard "
            "deviation of a Gaussian), after filling. 0 is off.\n"
            "Only smoothing changes the cells a line crossed."
        )


def test_busy_cursor_is_restored_after_an_exception(qgis_app):
    with pytest.raises(RuntimeError), busy_cursor():
        assert QApplication.overrideCursor() is not None
        raise RuntimeError("boom")
    assert QApplication.overrideCursor() is None


def test_a_slot_that_raises_in_its_own_body_is_logged(panel, monkeypatch):
    def broken():
        raise RuntimeError("sync broke")

    monkeypatch.setattr(panel, "_sync", broken)
    messages: list[str] = []
    disconnect = connect_message_log(lambda msg, tag, level: messages.append(msg))
    try:
        panel.method_combo.setCurrentIndex(panel.method_combo.findData("idw"))
        panel.max_distance_spin.setValue(0.75)
    finally:
        disconnect()
    assert any("sync broke" in m for m in messages)
