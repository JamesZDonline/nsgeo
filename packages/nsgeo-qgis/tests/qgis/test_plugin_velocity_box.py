"""Drag a box in velocity mode: the view's gesture and the dock's trace, through
the assembled plugin with real Qt mouse events."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.velocity_fit import refit
from plugin_testing import send_move_while_pressed, synthetic_dzt
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from tests.planted import REAL_DT_NS, REAL_NOISE_RATIO, Planted, plant
from tests.synthetic import write_dzt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 1.0, "EPSG:32616", 0.5)
NO_MOD = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton
N_TRACES = 120
APEX = 60
V = 0.07
# The DZT header's start position is -11.086 ns, so the first rows are padded to
# put the planted time axis on the radar's clock.
PAD = 51


def _write_planted(folder, name, *, hyperbola: bool):
    folder.mkdir(parents=True, exist_ok=True)
    planted = [Planted(APEX, 15.0, V)] if hyperbola else []
    data, _, _ = plant(N_TRACES, 512, planted, noise_ratio=REAL_NOISE_RATIO, seed=3)
    data = np.vstack([np.zeros((PAD, N_TRACES)), data])
    scaled = (data * 1e8).astype(np.int32)
    path = folder / name
    write_dzt(path, scaled, traces_per_metre=60.0, range_ns=scaled.shape[0] * REAL_DT_NS)
    return path


@pytest.fixture
def plugin(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    paths = [
        _write_planted(tmp_path / "raw", "FILE__001.DZT", hyperbola=True),
        synthetic_dzt(tmp_path / "raw", "FILE__002.DZT", n_traces=N_TRACES),
    ]
    lines = [
        Line.open(p, GridPlacement("A", "y", float(i), 0.0)) for i, p in enumerate(paths, start=1)
    ]
    s.add_lines(lines)
    for key, line in zip(s.keys(), lines, strict=True):
        s.set_profiles(key, line.load())
    s.open_line(s.keys()[0])
    plugin.profile_dock.view.resize(500, 300)
    plugin.act_velocity.setChecked(True)
    plugin.act_velocity.triggered.emit(True)
    try:
        yield plugin
    finally:
        plugin.unload()


def _view(plugin):
    return plugin.profile_dock.view


def _px(v, trace, ns):
    """Local pixel (x, y) of a trace's centre and a time."""
    t = v.transform
    return t.x_of_trace(trace + 0.5), t.y_of_time(ns)


def _pos(v, x, y):
    r = v.image_rect()
    return QPoint(r.left() + round(x), r.top() + round(y))


def _drag(v, start, end):
    """A real press, move and release between two local pixel positions."""
    QTest.mousePress(v, LEFT, NO_MOD, _pos(v, *start))
    send_move_while_pressed(v, _pos(v, *end), LEFT)
    QTest.mouseRelease(v, LEFT, NO_MOD, _pos(v, *end))


def _box_around(v, traces=(30, 90), ns=(8.0, 30.0)):
    a = _px(v, traces[0], ns[0])
    b = _px(v, traces[1], ns[1])
    return a, b


def _click(v, x, y):
    QTest.mouseClick(v, LEFT, NO_MOD, _pos(v, x, y))


def test_a_drag_in_velocity_mode_traces_dots_into_the_working_set(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    _drag(v, *_box_around(v))
    pts = dock.velocity_points()
    assert 4 <= len(pts) <= 10
    assert abs(pts[0][0] - APEX) <= 3  # the apex-nearest dot first
    assert "v = " in dock.velocity_readout.text()
    assert dock.save_fit_button.isEnabled()
    assert dock.velocity_fit_result().v_m_ns == pytest.approx(V, rel=0.1)


def test_a_wobble_shorter_than_the_drag_distance_places_one_dot(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    x, y = _px(v, 40, 12.0)
    wobble = QApplication.startDragDistance() - 1
    _drag(v, (x, y), (x + wobble, y))
    pts = dock.velocity_points()
    assert len(pts) == 1
    assert pts[0][0] == v.transform.trace_index_at(round(x))
    assert pts[0][1] == pytest.approx(v.transform.time_of_y(round(y)), abs=0.1)


def test_a_box_replaces_the_working_dots(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    for tr, ns in ((20, 10.0), (25, 12.0), (30, 14.0)):
        _click(v, *_px(v, tr, ns))
    hand = dock.velocity_points()
    assert len(hand) == 3
    _drag(v, *_box_around(v))
    after = dock.velocity_points()
    assert len(after) >= 4
    assert not set(hand) & set(after)


def _enable_step(plugin, name):
    s = plugin.session
    params = {"velocity_m_ns": 0.1} if name == "migrate_fk" else {}
    s.append_step(s.keys()[0], build_step(name, **params))


def _three_hand_dots(plugin):
    v = _view(plugin)
    for tr, ns in ((50, 17.0), (60, 15.0), (70, 17.0)):
        _click(v, *_px(v, tr, ns))
    return plugin.profile_dock.velocity_points()


def test_a_refused_box_keeps_the_hand_dots(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    hand = _three_hand_dots(plugin)
    assert len(hand) == 3
    _enable_step(plugin, "migrate_fk")
    _drag(v, *_box_around(v))
    assert dock.velocity_points() == hand
    assert dock.velocity_note.text().startswith(
        "Cannot trace with Migration (Stolt f-k) on: it has already collapsed the hyperbolas."
    )
    assert "click the points by hand." in dock.velocity_note.text()


@pytest.mark.parametrize(
    "name,title",
    [
        ("amp_abs", "Absolute value"),
        ("amp_square", "Square of the amplitude"),
        ("amp_envelope", "Envelope"),
    ],
)
def test_each_amplitude_transform_refuses_with_its_title(plugin, name, title):
    v, dock = _view(plugin), plugin.profile_dock
    hand = _three_hand_dots(plugin)
    _enable_step(plugin, name)
    _drag(v, *_box_around(v))
    assert dock.velocity_points() == hand
    assert dock.velocity_note.text().startswith(
        f"Cannot trace with {title} on: it removes the edge the tracer follows."
    )


def test_a_difference_view_refuses(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    plugin.session.append_step(plugin.session.keys()[0], build_step("dewow", window_ns=4.0))
    dock.set_difference_index(0)
    hand = _three_hand_dots(plugin)
    _drag(v, *_box_around(v))
    assert dock.velocity_points() == hand
    assert "Cannot trace a difference view. Turn the difference off to trace." in (
        dock.velocity_note.text()
    )


def test_a_box_on_empty_ground_says_why_and_keeps_the_dots(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    hand = _three_hand_dots(plugin)
    _drag(v, *_box_around(v, traces=(5, 40), ns=(60.0, 90.0)))  # noise only
    assert dock.velocity_points() == hand
    note = dock.velocity_note.text()
    assert note
    assert "hyperbola" in note.lower() or "faint" in note.lower() or "few points" in note


def test_a_box_drawn_backwards_or_past_the_edge_is_normalised_and_clipped(plugin):
    v = _view(plugin)
    got = []
    v.velocity_box_drawn.connect(lambda *a: got.append(a))
    a, b = _box_around(v)
    _drag(v, b, a)  # bottom-right to top-left
    w = v.transform.width
    _drag(v, a, (w + 40, b[1]))  # past the image's right edge
    assert len(got) == 2
    for first, last, top, bottom in got:
        assert 0 <= first <= last < N_TRACES
        assert top <= bottom
        assert v.transform.time_lo - 1e-6 <= top and bottom <= v.transform.time_hi + 1e-6
    assert got[0][:2] == (30, 90) or abs(got[0][0] - 30) <= 1
    assert got[1][1] == N_TRACES - 1


def test_a_saved_traced_fit_refits_to_the_velocity_shown(plugin):
    v, dock = _view(plugin), plugin.profile_dock
    _drag(v, *_box_around(v))
    shown = dock.velocity_fit_result()
    assert shown is not None
    dock.save_fit_button.click()
    key = plugin.session.keys()[0]
    stored = next(iter(plugin.session.line_for_key(key).velocity_fits.values()))
    distance = plugin.session.line_for_key(key).distance_along()
    again = refit(stored, distance, dock._line_zero())
    assert round(again.v_m_ns, 4) == round(shown.v_m_ns, 4)
    assert round(stored.v_m_ns, 4) == round(shown.v_m_ns, 4)


def test_a_traced_fit_without_time_zero_shows_the_radar_clock_note(plugin):
    # The tracer follows no Time zero rule (spec §6, revised), so a traced fit
    # gets no note of its own; with no Time zero step it gets the radar-clock
    # note a clicked fit gets.
    v, dock = _view(plugin), plugin.profile_dock
    _drag(v, *_box_around(v))
    assert dock.velocity_points()
    note = dock.velocity_note.text()
    assert note.startswith("Times are from the radar's own zero; the first break is at ")
    assert note.endswith("Add a Time zero step to measure from it.")
    assert "traced edge" not in note
