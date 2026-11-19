from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step, get_step
from nsgeo.render import row_envelope
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gain_strip import DB_LIMIT, HANDLE_RADIUS, GainStrip, Headroom
from nsgeo_qgis.ui.profile_dock import ProfileDock
from nsgeo_qgis.ui.profile_view import MARGIN_TOP
from nsgeo_qgis.ui.view_transform import ViewTransform
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from plugin_testing import send_double_click as _send_double_click
from plugin_testing import send_move_while_pressed as _send_move_while_pressed
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtGui import QFontMetrics
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMessageBox

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def strip(qgis_app):
    """A bare, parentless, shown `GainStrip` -- exactly the shape
    `test_plugin_profile_view.py`'s `make_view` fixture documents as a
    segfault hazard at interpreter shutdown (a top-level widget GC might
    destroy it while still shown, racing Qt's own teardown). `hide()` +
    `deleteLater()` on teardown is that fixture's own fix, copied here for
    the same reason -- it does not, by itself, fix the separate ordering
    hazard `plugin_testing.send_double_click` exists for; see that
    function's own docstring.
    """
    s = GainStrip()
    s.resize(96, 300 + MARGIN_TOP + 28)
    s.show()
    t = ViewTransform.fit(100, 200, 0.0, 0.5, 600, 300)
    s.set_time_mapping(t, MARGIN_TOP)
    s.set_points([[0.0, 0.0], [100.0, 20.0]], "fixture")
    yield s
    s.hide()
    s.deleteLater()


def test_mappings_round_trip(strip):
    assert strip.time_of_y(strip.y_of_time(37.0)) == pytest.approx(37.0)
    assert strip.db_of_x(strip.x_of_db(12.0)) == pytest.approx(12.0)
    assert strip.y_of_time(0.0) == MARGIN_TOP


def test_dragging_a_handle_moves_its_point_and_emits(strip):
    got = []
    strip.points_changed.connect(got.append)
    x0, y0 = strip.x_of_db(20.0), strip.y_of_time(100.0)
    assert strip.handle_at(QPoint(int(x0), int(y0))) == 1
    QTest.mousePress(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x0), int(y0))
    )
    # Not QTest.mouseMove: see _send_move_while_pressed's docstring above --
    # a move sent while a button is held is not reliably delivered by it in
    # this offscreen environment.
    #
    # Target 24.0, not the brief's original 30.0: Important 2's fix freezes
    # _db_range for the gesture at (-6, 26) (from this fixture's own
    # [0.0, 20.0] points), so 30.0 is now correctly out of the strip's own
    # range and would be clamped to 26.0 instead -- see
    # test_drag_overshoot_is_clamped_and_the_range_does_not_ratchet for
    # that behaviour pinned directly. 24.0 stays a real, in-range move.
    _send_move_while_pressed(strip, QPoint(int(strip.x_of_db(24.0)), int(y0)))
    QTest.mouseRelease(
        strip,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(strip.x_of_db(24.0)), int(y0)),
    )
    assert got and got[-1][1][1] == pytest.approx(24.0, abs=0.5)
    assert strip.points()[1][0] == pytest.approx(100.0, abs=0.5)


def test_double_click_adds_and_right_click_removes(strip):
    got = []
    strip.points_changed.connect(got.append)
    mid = QPoint(int(strip.x_of_db(10.0)), int(strip.y_of_time(50.0)))
    # Not QTest.mouseDClick: see plugin_testing.send_double_click's own
    # docstring -- it corrupts mouse state in this offscreen environment
    # that outlives this test entirely.
    _send_double_click(strip, mid)
    assert len(strip.points()) == 3 and got[-1][1][0] == pytest.approx(50.0, abs=0.5)
    QTest.mouseClick(strip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, mid)
    assert len(strip.points()) == 2
    QTest.mouseClick(
        strip,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(strip.x_of_db(0.0)), int(strip.y_of_time(0.0))),
    )
    assert len(strip.points()) == 2  # never below two


def test_double_click_clears_a_stale_drag_db_range(strip):
    """Fix round 2, item 3. `mouseDoubleClickEvent` cleared `_drag` but not
    `_drag_db_range` -- the one place that pairing wasn't kept in step:
    `mouseMoveEvent`'s own bounds-check branch and `mouseReleaseEvent` both
    already clear both together.

    Unreachable through real Qt event sequencing today, and not just in
    the abstract: verified directly that routing this through
    `plugin_testing.send_double_click` (its leading `MouseButtonPress`,
    hitting no handle at `mid`, resets `_drag_db_range` to `None` itself
    via `mousePressEvent`'s own `hit is not None` branch) clears the
    forced stale value *before* `mouseDoubleClickEvent` ever runs, hiding
    the bug entirely -- a reversion of the fix still passed with that
    approach. Sending only the bare `MouseButtonDblClick` event -- no
    preceding press -- isolates `mouseDoubleClickEvent`'s own clearing
    from that unrelated one, the same way a real double-click's *second*
    physical press is delivered as a `MouseButtonDblClick`, never a
    second `MouseButtonPress` (see `send_double_click`'s own docstring).
    """
    from qgis.PyQt.QtCore import QEvent, QPointF
    from qgis.PyQt.QtGui import QMouseEvent
    from qgis.PyQt.QtWidgets import QApplication

    strip._drag_db_range = (-6.0, 26.0)  # a stale value nothing real produces here
    mid = QPoint(int(strip.x_of_db(10.0)), int(strip.y_of_time(50.0)))
    local, glob = QPointF(mid), QPointF(strip.mapToGlobal(mid))
    ev = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        local,
        glob,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(strip, ev)

    assert strip._drag_db_range is None


def test_profile_dock_shows_the_strip_only_when_asked(qgis_app, tmp_path):
    # A parentless ProfileDock is a top-level widget -- the same hazard
    # test_plugin_profile_view.py's make_view fixture and
    # test_plugin_profile_dock.py's opened/bare fixtures document and guard
    # against (a shown top-level widget destroyed by Python's GC instead of
    # Qt segfaults at interpreter shutdown): torn down explicitly at the end
    # of this test, the same way those fixtures do in their own teardown.
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    assert dock.gain_strip.isHidden()
    dock.show_gain_strip([[-11.0, 0.0], [99.0, 0.0]], "curve-A")
    assert not dock.gain_strip.isHidden()
    assert dock.gain_strip.y_of_time(-11.0) == pytest.approx(
        MARGIN_TOP + dock.view.transform.y_of_time(-11.0)
    )
    changed = []
    dock.gain_points_changed.connect(changed.append)
    dock.gain_strip.set_points([[-11.0, 0.0], [99.0, 12.0]], "curve-A")
    dock.gain_strip.points_changed.emit(dock.gain_strip.points())
    assert changed and changed[0][1][1] == 12.0
    dock.show_gain_strip(None)
    assert dock.gain_strip.isHidden()
    dock.hide()
    dock.deleteLater()


def test_plugin_routes_strip_edits_through_replace_step(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step("dewow")
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(1)
    assert not plugin.profile_dock.gain_strip.isHidden()
    # The owner _sync_gain_strip gave the strip when row 1 was selected:
    # a payload from the curve already on screen, not from another one.
    plugin.profile_dock.gain_strip.set_points(
        [[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]], plugin._gain_owner
    )
    plugin.profile_dock.gain_strip.points_changed.emit(plugin.profile_dock.gain_strip.points())
    assert s.stack_for(key).entries[1][0].params["points"][1] == [50.0, 6.0]
    plugin.processing_dock.list.setCurrentRow(0)
    assert plugin.profile_dock.gain_strip.isHidden()
    # The session is dirty by now (new_site/add_grid/add_lines/the stack
    # edits above); unload() prompts to save, and the offscreen-modal
    # guard in conftest.py fails fast on any unanswered prompt rather than
    # hang -- see test_plugin_survey_dock.py's own unload() tests for the
    # same pattern. Discard: this test does not care whether the site was
    # saved, only that unload() tears the docks down.
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def _plugin_with_time_zero_after_curve(fake_iface, tmp_path, points=None, sample=51):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    s.append_step(key, build_step("gain_curve", points=points or [[0.0, 0.0], [40.0, 12.0]]))
    s.append_step(key, build_step("time_zero", mode="sample", sample=sample))
    plugin.processing_dock.list.setCurrentRow(0)
    return plugin, s, key


def _step_points(s, key, row):
    return s.stack_for(key).entries[row][0].params["points"]


def test_a_gain_curve_ahead_of_time_zero_is_shown_and_written_on_its_own_clock(
    fake_iface, tmp_path, answer_modal
):
    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)
    try:
        zero = plugin.profile_dock.shown_zero_ns()
        assert zero != 0.0
        strip = plugin.profile_dock.gain_strip
        assert np.ravel(strip.points()) == pytest.approx([0.0 - zero, 0.0, 40.0 - zero, 12.0])
        strip.points_changed.emit([[0.0 - zero, 0.0], [30.0 - zero, 12.0]])
        assert np.ravel(_step_points(s, key, 0)) == pytest.approx([0.0, 0.0, 30.0, 12.0])
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()


def test_an_unmoved_gain_strip_across_clocks_writes_nothing(fake_iface, tmp_path, answer_modal):
    # Times whose round trip (t - z) + z is inexact: only the shown-clock
    # comparison stops the write.
    plugin, s, key = _plugin_with_time_zero_after_curve(
        fake_iface, tmp_path, points=[[0.1, 0.0], [40.3, 12.0]], sample=137
    )
    try:
        z = plugin.profile_dock.shown_zero_ns()
        assert (0.1 - z) + z != 0.1
        step = s.stack_for(key).entries[0][0]
        s._set_dirty(False)
        strip = plugin.profile_dock.gain_strip
        strip.points_changed.emit(strip.points())
        assert s.stack_for(key).entries[0][0] is step
        assert not s.dirty
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()


def test_a_strip_deferred_through_a_preview_lands_on_the_working_clock(
    fake_iface, tmp_path, answer_modal
):
    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)
    try:
        dock = plugin.profile_dock
        zero = dock.shown_zero_ns()
        key_b = _add_second_line(s, tmp_path, load=True)
        s.set_preview(key_b, 0)
        s.line_loaded.emit(key)  # the working line finishing a load mid-preview
        s.set_preview(None)
        assert np.ravel(dock.gain_strip.points()) == pytest.approx(
            [0.0 - zero, 0.0, 40.0 - zero, 12.0]
        )
        step = s.stack_for(key).entries[0][0]
        s._set_dirty(False)
        dock.gain_strip.points_changed.emit(dock.gain_strip.points())
        assert s.stack_for(key).entries[0][0] is step
        assert not s.dirty
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()


def test_a_failed_render_keeps_the_clock_of_the_image_on_screen(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)
    try:
        dock = plugin.profile_dock
        zero = dock.shown_zero_ns()
        assert zero != 0.0
        s.append_step(key, build_step("bandpass", low_mhz=100.0, high_mhz=5000.0))
        assert dock.shown_zero_ns() == zero
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()


@pytest.mark.parametrize("pts", [[[0.0], [40.0, 12.0]], [["a", 0.0], [40.0, 12.0]]])
def test_a_malformed_strip_payload_is_reported_not_raised(fake_iface, tmp_path, answer_modal, pts):
    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)
    try:
        step = s.stack_for(key).entries[0][0]
        plugin._on_gain_points(pts)
        assert s.stack_for(key).entries[0][0] is step
    finally:
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
        plugin.unload()


def test_plugin_reports_a_bad_curve_edit_instead_of_raising(fake_iface, tmp_path, answer_modal):
    """`points_changed` is a public signal on a public widget: nothing
    stops a payload reaching `_on_gain_points` that `GainStrip` itself
    would never emit through its own UI (its "never below two" rule guards
    dragging/clicking, not this signal). `build_step`'s own `ValueError`
    ("gain_curve needs at least two control points") must be caught the
    same way `session.replace_step`'s already is -- not escape from this
    signal-connected slot (see the module docstring's own hazard note)
    leaving the step silently unchanged with no explanation.
    """
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(0)
    before = s.stack_for(key).entries[0][0]

    plugin.profile_dock.gain_strip.points_changed.emit([[0.0, 0.0]])  # only one point

    assert s.stack_for(key).entries[0][0] is before  # unchanged, not corrupted
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "at least two" in item.text()

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_clicking_a_handle_without_moving_it_does_not_edit_the_step(fake_iface, tmp_path):
    """m1 (fix round 1 review). `GainStrip.mouseReleaseEvent` emits
    `points_changed` unconditionally whenever a drag ends, even one that
    never moved at all -- a plain click on a handle: press, then release
    at the same position, with no intervening move. Without a no-op guard
    here, that still called `session.replace_step`, dirtying the session
    and earning the user a "save changes?" prompt on unload for an edit
    they never actually made (`ProcessingDock._on_form_committed` already
    guards its own commit the same way, at `current.params == params`).
    """
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(0)
    s.save()  # a clean slate: only a real edit after this should dirty it
    assert not s.dirty
    before = s.stack_for(key).entries[0][0]
    strip = plugin.profile_dock.gain_strip
    t, db = strip.points()[0]  # a real handle's exact position, not a guessed one
    pos = QPoint(int(strip.x_of_db(db)), int(strip.y_of_time(t)))

    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)

    assert s.stack_for(key).entries[0][0] is before  # unchanged object: no replace_step ran
    assert not s.dirty

    plugin.unload()  # session is clean: no save prompt to answer


def test_dragging_a_point_past_its_neighbour_does_not_corrupt_it(
    fake_iface, tmp_path, answer_modal
):
    """Every point_changed emitted mid-drag runs through NsgeoPlugin's own
    session.replace_step, which -- via stack_changed -> ProcessingDock.
    rebuild() -> step_selected -- calls back into _sync_gain_strip ->
    show_gain_strip() -> GainStrip.set_points(). set_points() re-sorts the
    point list by time; the instant a drag carries a point's time past a
    neighbour's, that resort remaps GainStrip._drag's fixed index onto the
    *neighbour* instead of the point actually under the cursor, and the
    next move silently overwrote the neighbour's (time, dB) with the drag's
    new position -- the neighbour's own value was gone, not merely
    reordered. Verified directly with a plugin-level echo guard first (fix
    round 1's own review caught that that guard, compared unconditionally
    in _sync_gain_strip rather than only during a live drag, hid the strip
    forever after any edit -- see
    test_reselecting_a_curve_row_after_an_edit_still_shows_the_strip); the
    fix now lives at the actual point of contention instead:
    GainStrip.set_points ignores an external payload while self._drag is
    not None, so this same echo simply cannot touch _points mid-drag. A
    single instant jump does not show the original bug (the resort's
    output happens to still agree with the pre-jump order until a second
    move writes through the now-wrong index), so this drags through
    several intermediate positions the way a real, continuous drag would.
    """
    import nsgeo_qgis
    from nsgeo.processing import build_step

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    # Times chosen to stay within this real line's own visible time range
    # (roughly [-11, 100) ns) even after Important 2's fix clamps a drag
    # to it -- unlike the brief's own [0, 50, 100], whose top end sat
    # right at (in fact very slightly past) this line's own time_hi, which
    # would otherwise clamp the "past the neighbour" drag below straight
    # back to the neighbour's own position and prove nothing.
    s.replace_step(
        key, 0, build_step("gain_curve", points=[[0.0, 0.0], [30.0, 10.0], [60.0, 20.0]])
    )
    plugin.processing_dock.list.setCurrentRow(0)
    strip = plugin.profile_dock.gain_strip

    x = strip.x_of_db(10.0)  # dragged point's dB never changes below
    assert strip.handle_at(QPoint(int(x), int(strip.y_of_time(30.0)))) == 1
    QTest.mousePress(
        strip,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(x), int(strip.y_of_time(30.0))),
    )
    for t in (35.0, 45.0, 55.0, 65.0, 75.0):  # crosses the t=60 neighbour partway through
        _send_move_while_pressed(strip, QPoint(int(x), int(strip.y_of_time(t))))
    QTest.mouseRelease(
        strip,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(x), int(strip.y_of_time(75.0))),
    )

    final = s.stack_for(key).entries[0][0].params["points"]
    assert [0.0, 0.0] in final
    assert [60.0, 20.0] in final, f"the (60, 20) neighbour was corrupted: {final}"
    assert any(t > 60.0 and db == pytest.approx(10.0) for t, db in final)

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_reselecting_a_curve_row_after_an_edit_still_shows_the_strip(
    fake_iface, tmp_path, answer_modal
):
    """Fix round 1, Critical 1. The original fix for the neighbour-
    corruption bug above was a plugin-level marker: NsgeoPlugin recorded
    the (key, row, step) it had just written and _sync_gain_strip skipped
    resyncing when it saw that same triple come back through
    stack_changed -> rebuild() -> step_selected. That marker was compared
    unconditionally, not only while a drag was actually live, so it never
    got invalidated by a genuine detour through a different row: edit a
    curve, select another step, select the curve step back -- its step
    object is unchanged since the edit, so the stale marker still matches
    and the strip stays hidden forever, reproduced exactly:

        after selecting gain row, hidden = False
        after edit, stored points: [[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]]
        after selecting dewow row, hidden = True
        BACK on the gain row, hidden = True    <-- expected False

    Fixed by retiring the marker entirely: GainStrip.set_points now
    ignores an external payload only while self._drag is not None (an
    actual live drag), which is the only time resyncing was ever unsafe,
    so _sync_gain_strip can resync unconditionally on every real
    reselection.
    """
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step("dewow")
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(1)
    assert not plugin.profile_dock.gain_strip.isHidden()

    # The owner _sync_gain_strip gave the strip when row 1 was selected:
    # a payload from the curve already on screen, not from another one.
    plugin.profile_dock.gain_strip.set_points(
        [[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]], plugin._gain_owner
    )
    plugin.profile_dock.gain_strip.points_changed.emit(plugin.profile_dock.gain_strip.points())
    assert s.stack_for(key).entries[1][0].params["points"][1] == [50.0, 6.0]

    plugin.processing_dock.list.setCurrentRow(0)  # dewow: no curve, strip hides
    assert plugin.profile_dock.gain_strip.isHidden()

    plugin.processing_dock.list.setCurrentRow(1)  # BACK to the same, unchanged gain_curve step
    assert not plugin.profile_dock.gain_strip.isHidden()

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_a_row_change_mid_drag_never_writes_onto_the_newly_selected_step(
    fake_iface, tmp_path, answer_modal
):
    """Fix round 3, Critical 2. `GainStrip.set_points` refused *any*
    incoming payload while `self._drag is not None` -- right for an echo
    of the strip's own edit, wrong for a payload belonging to a
    *different* step, which the strip had no way to tell apart.
    Meanwhile `NsgeoPlugin._on_gain_points` resolved its write target
    from `processing_dock.current_row()` at write time, a different
    source from the one the strip was loaded from. The strip takes no
    focus (it sets no focus policy, so pressing it never steals the
    keyboard from the processing list), so a plain arrow key moves the
    selection onto another row mid-drag -- and when that row also holds a
    curve step, the strip kept step A's points while every later write
    went to step B. Reproduced exactly, with a real `Qt.Key_Down`:

        row after Key_Down: 1  hidden: False  drag: 1
        B before: [[0.0, 0.0], [40.0, -12.0]]
        B after:  [[0.0, 0.0], [39.067, 6.632]]   <- B's curve replaced by A's

    No error, no log, no undo, and the strip still displayed A, so there
    was no visual cue either; `replace_step` then dirtied the session and
    the corrupted curve reached `survey.json` on save. `hideEvent`'s own
    end-the-gesture rule (the third invariant) cannot cover this: a
    curve -> curve change never hides the strip.
    """
    import nsgeo_qgis
    from nsgeo.processing import build_step

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    # Two curve steps, so the row change below lands on another curve --
    # the one case hideEvent cannot catch. Times stay inside this real
    # line's own visible range (roughly [-11, 100) ns) so nothing is
    # clamped back onto a neighbour.
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [30.0, 10.0]]))
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [40.0, -12.0]]))
    dock = plugin.processing_dock
    strip = plugin.profile_dock.gain_strip
    dock.list.setCurrentRow(0)
    assert not strip.isHidden()
    b_before = [list(pt) for pt in s.stack_for(key).entries[1][0].params["points"]]

    x = int(strip.x_of_db(10.0))  # the dragged point's dB never changes below
    press = QPoint(x, int(strip.y_of_time(30.0)))
    assert strip.handle_at(press) == 1  # step A's second control point
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, press)
    assert strip._drag == 1

    QTest.keyClick(dock.list, Qt.Key.Key_Down)  # the list still has the keyboard
    assert dock.current_row() == 1  # step B is selected now, mid-gesture

    for t in (35.0, 45.0, 55.0):
        _send_move_while_pressed(strip, QPoint(x, int(strip.y_of_time(t))))
    QTest.mouseRelease(
        strip,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(x, int(strip.y_of_time(55.0))),
    )

    after = s.stack_for(key).entries[1][0].params["points"]
    assert after == b_before, f"step B's authored curve was overwritten with step A's: {after}"
    # The gesture ended when the selection left step A, so the moves after
    # the row change wrote nowhere at all -- not onto A either.
    assert s.stack_for(key).entries[0][0].params["points"] == [[0.0, 0.0], [30.0, 10.0]]

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_a_stack_reorder_mid_drag_never_writes_onto_the_step_that_took_the_row(
    fake_iface, tmp_path, answer_modal
):
    """Fix round 3, Critical 2, the owner token's generation. The row
    change above is the reproduction that was reported; it is not the only
    way a different curve can arrive under a live gesture. A stack
    mutation that swaps another step into the *same* row leaves `(key,
    row)` unchanged, so an owner spelled as that pair alone would compare
    equal, `set_points` would refuse the payload as if it were the
    strip's own echo, and every later move of the gesture would go to the
    step that took the row -- the same corruption, one row along, with
    the plugin-side identity barrier unable to catch it (`_sync_gain_strip`
    has by then correctly recorded the new step as the one at that row).
    Verified: with the generation bump removed, this test writes the
    dragged curve onto the reordered step exactly as the `Key_Down`
    reproduction does.

    Reachable by hand today, by the same focus mechanism as the
    `Key_Down` reproduction above -- an earlier draft of this docstring
    said it was not, and the controller disproved it directly. The strip
    has `focusPolicy() == NoFocus` (0) while `ProcessingDock`'s ↑/↓
    buttons have `StrongFocus` (11), so pressing the strip never takes
    the keyboard from a button that already holds it, and a `Key_Space`
    on the focused ↓ button fires `move_selected(1)` with the drag still
    live. Probed end to end on the real plugin: stack rows
    `[[[0,0],[30,10]], [[0,0],[40,-12]]]` came back swapped while
    `strip._drag` was 1. `session.move_step` is driven directly here
    rather than through the button only to keep the test's failure
    pointing at the barrier instead of at Qt's focus handling.
    """
    import nsgeo_qgis
    from nsgeo.processing import build_step

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [30.0, 10.0]]))
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [40.0, -12.0]]))
    dock = plugin.processing_dock
    strip = plugin.profile_dock.gain_strip
    dock.list.setCurrentRow(0)  # step A
    assert not strip.isHidden()

    x = int(strip.x_of_db(10.0))
    press = QPoint(x, int(strip.y_of_time(30.0)))
    assert strip.handle_at(press) == 1
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, press)
    assert strip._drag == 1

    s.move_step(key, 0, 1)  # step B takes row 0; the selected row does not move
    assert dock.current_row() == 0
    assert strip._drag is None  # the gesture ended: its curve is no longer on screen
    assert strip.points() == [[0.0, 0.0], [40.0, -12.0]]  # B's curve, accepted not refused

    for t in (35.0, 45.0, 55.0):
        _send_move_while_pressed(strip, QPoint(x, int(strip.y_of_time(t))))
    QTest.mouseRelease(
        strip,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(x, int(strip.y_of_time(55.0))),
    )

    rows = [e[0].params["points"] for e in s.stack_for(key).entries]
    assert rows == [[[0.0, 0.0], [40.0, -12.0]], [[0.0, 0.0], [30.0, 10.0]]], rows

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_a_gain_write_is_refused_when_the_row_no_longer_holds_the_strips_step(
    fake_iface, tmp_path, answer_modal
):
    """Fix round 3, Critical 2, second barrier. The first barrier lives in
    `GainStrip.set_points`: a payload carrying a different owner token
    ends the gesture instead of being refused, so no later move of that
    gesture can reach a step that is no longer on screen. This is the
    matching plugin-side check, the same belt-and-braces shape
    `ProcessingDock._on_form_committed` already uses against
    `_shown_step`: before writing, the row must still hold the very step
    object `_sync_gain_strip` handed the strip. Identity, not name --
    two `gain_curve` steps in one stack share a name and are not the same
    step.

    `points_changed` is a public signal on a public widget, and
    `_gain_step` is plugin state no invariant of this widget protects, so
    the desync is manufactured here directly (the same way
    `test_a_shrunk_point_list_mid_drag_does_not_raise` manufactures its
    own) rather than via a route today's code happens to make
    unreachable -- the point of a second barrier is that it holds when
    the first one does not.
    """
    import nsgeo_qgis
    from nsgeo.processing import build_step

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [30.0, 10.0]]))
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [40.0, -12.0]]))
    dock = plugin.processing_dock
    dock.list.setCurrentRow(1)
    assert not plugin.profile_dock.gain_strip.isHidden()
    before = s.stack_for(key).entries[1][0]

    # The strip was built from row 1's step; pretend a desync left the
    # plugin holding row 0's step instead -- same name, different object.
    plugin._gain_step = s.stack_for(key).entries[0][0]
    plugin.profile_dock.gain_points_changed.emit([[0.0, 0.0], [70.0, 21.0]])

    assert s.stack_for(key).entries[1][0] is before  # unchanged object: no replace_step ran
    assert s.stack_for(key).entries[0][0].params["points"] == [[0.0, 0.0], [30.0, 10.0]]

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_drag_overshoot_is_clamped_and_the_range_does_not_ratchet(strip):
    """Important 2. `db_of_x` maps against `_db_range()`, which used to be
    `max(24.0, max(dbs) + 6.0)` -- a function of the value the *previous*
    move just wrote. Qt's implicit mouse grab keeps delivering moves to
    the widget that started the drag even once the cursor leaves it
    (ordinary on a 96 px-wide strip), so an unclamped drag fed that
    growing value straight back into the next move's `_db_range()`, a
    feedback loop: verified directly, parking the cursor ~100 px right of
    the strip and jiggling by one pixel ran the gain from 72 dB past
    1,000,000 dB in a few dozen moves, and `GainCurve.apply` overflows
    that to an all-`inf` radargram once dB reaches the thousands.

    Freezing `_db_range` for the gesture (`_drag_db_range`, set on press)
    and clamping the mapped position into the widget's own bounds
    together mean every move far outside the strip maps to the *same*,
    bounded db (the frozen range's own `hi`) -- not a growing one. Checked
    by repeating the identical out-of-bounds move 20 times and confirming
    the 1st and 20th land on the same value, not a ratcheting one.
    """
    x0, y0 = strip.x_of_db(20.0), strip.y_of_time(100.0)  # handle 1: (100.0, 20.0)
    QTest.mousePress(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x0), int(y0))
    )
    far_right = QPoint(int(x0) + 200, int(y0))  # well past the 96px-wide strip's right edge
    _send_move_while_pressed(strip, far_right)
    after_one = strip.points()[1][1]
    for _ in range(19):
        _send_move_while_pressed(strip, far_right)
    after_twenty = strip.points()[1][1]
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, far_right)

    assert after_one == after_twenty == pytest.approx(26.0)  # frozen range's own hi: -6..26
    assert after_twenty < 100.0  # nowhere near the unclamped repro's 1,616,316.7 dB


def test_drag_above_the_strip_keeps_the_handle_reachable(strip):
    """Important 2's second half. Before clamping, a point dragged above
    `y=0` (before `MARGIN_TOP`, i.e. before the visible time axis) painted
    at a negative `y` -- outside `handle_at`'s search, which only checks
    real handle positions, never an out-of-frame one implicitly. A
    two-point curve dragged this way could be neither re-dragged nor
    right-click-removed: permanently stuck. Clamping `y` into
    `_clamped`'s own `[top, top + transform.height]` before it is ever
    written into `_points` means the stored point always maps back to a
    reachable position afterwards.

    Dragging handle 1 (t=100.0, this fixture's own time_hi), not handle 0
    (already at time_lo, where "dragged past the top" and "left alone"
    would look identical): the fix must show up as a real,
    non-degenerate change, not one that happens to match doing nothing.

    Asserted directly against the stored point, not solely through
    `handle_at`'s own hit-radius slack: fix round 2's review found
    `handle_at(QPoint(x, 0))` here used to pass only because this
    fixture's 8px `MARGIN_TOP` gap happens to be smaller than `HIT_RADIUS
    + 1.0` (9px) -- a coincidence that would break if `MARGIN_TOP` ever
    changed, for a reason unrelated to clamping.
    """
    x1, y1 = strip.x_of_db(20.0), strip.y_of_time(100.0)  # handle 1: (100.0, 20.0)
    QTest.mousePress(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x1), int(y1))
    )
    far_above = QPoint(int(x1), int(y1) - 500)  # far above the strip's own top
    _send_move_while_pressed(strip, far_above)
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, far_above)

    # Clamped to this fixture's own time_lo (t0 = 0.0); db unchanged, since
    # the drag never moved horizontally -- not left at some unreachable,
    # off-axis time.
    assert any(
        t == pytest.approx(0.0) and db == pytest.approx(20.0, abs=0.5) for t, db in strip.points()
    )
    assert strip.handle_at(QPoint(int(x1), int(strip.y_of_time(0.0)))) is not None


def test_a_shrunk_point_list_mid_drag_does_not_raise(strip):
    """Important 3. `set_points` now refuses an external payload while a
    drag is live (see `test_reselecting_a_curve_row_...` above), which
    closes the only route this codebase actually has for `_points` to
    change out from under a live `self._drag` index -- but `_points` is
    not a private implementation detail behind a single chokepoint the
    way, say, a dataclass field would be; nothing stops a *future* caller
    reaching it directly. `self._drag >= len(self._points)` is the
    defence for that: simulate exactly this (shrink `_points` directly,
    bypassing `set_points` entirely, the same way an external caller with
    direct attribute access could) and confirm `mouseMoveEvent` aborts the
    gesture cleanly instead of raising `IndexError` inside a slot nothing
    would see fail.
    """
    x0, y0 = strip.x_of_db(20.0), strip.y_of_time(100.0)
    pos = QPoint(int(x0), int(y0))
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert strip._drag == 1
    del strip._points[1]  # a hypothetical external shrink, bypassing set_points' own guard

    _send_move_while_pressed(strip, QPoint(int(x0) + 5, int(y0)))  # must not raise IndexError

    assert strip._drag is None  # the widget noticed and aborted the gesture
    # A real drag's own release always follows its press; without one here
    # the left button stays logically down for the rest of the process --
    # Qt's own mouse grab, not this widget's already-cleared self._drag --
    # confirmed directly to silently swallow an unrelated *later* test's
    # plain QTest.mouseMove in a completely different file, the same class
    # of hazard _send_double_click's own docstring documents for
    # QTest.mouseDClick.
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def test_hiding_mid_drag_ends_the_gesture(strip):
    """Fix round 2, item 1. Nothing delivers a matching `mouseReleaseEvent`
    to a widget hidden mid-drag -- a line load completing mid-drag, or an
    arrow-key row change stealing focus away (this widget sets no focus
    policy of its own, so the processing list keeps focus during a strip
    drag either way). Reproduced directly: press a handle, hide the
    widget, and `self._drag` stayed set indefinitely -- `set_points`'s own
    refusal (the first invariant) then permanently refused every later
    resync. `hideEvent` now clears `_drag`/`_drag_db_range` itself, ending
    the gesture the same way a release would have.
    """
    x0, y0 = strip.x_of_db(20.0), strip.y_of_time(100.0)
    pos = QPoint(int(x0), int(y0))
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert strip._drag is not None

    strip.hide()

    assert strip._drag is None
    assert strip._drag_db_range is None
    # The fixture's own owner, unchanged: this must be honoured because
    # hideEvent ended the gesture, not because the payload belongs to a
    # different curve (the fourth invariant's own route, pinned by
    # test_a_row_change_mid_drag_never_writes_onto_the_newly_selected_step).
    strip.set_points([[0.0, 0.0], [50.0, 5.0]], "fixture")  # honoured now, not refused
    assert strip.points() == [[0.0, 0.0], [50.0, 5.0]]
    # This test's own press is deliberately never followed by a real
    # release (that's the whole scenario: nothing delivers one to a
    # hidden widget) -- but leaving Qt's own mouse grab unbalanced is a
    # second, independent hazard from the one this test targets: verified
    # directly, it silently blocked a later, unrelated test's plain
    # QTest.mouseMove in a different file, the same class of hazard
    # `plugin_testing.send_double_click`'s own docstring documents for
    # `QTest.mouseDClick`. A release delivered here, after hide(), still
    # reaches Qt's own bookkeeping (confirmed directly) even though the
    # widget's own mouseReleaseEvent now finds _drag already None and
    # does nothing with it.
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def test_a_buttonless_move_never_edits_a_stranded_drag(strip):
    """Fix round 2, item 2. `hideEvent` above closes the strand at its
    source, but this is a deliberate second, independent barrier for the
    same silent failure -- reproduced directly before this fix: with
    `_drag` left set (by the pre-fix hide-mid-drag bug, or any future path
    this file cannot foresee) and no button held, a plain hover across the
    strip still rewrote the stranded index's point and emitted
    `points_changed`, which `plugin.py` routes straight into
    `session.replace_step` -- silently editing the user's gain curve on a
    hover. `mouseMoveEvent` now checks `event.buttons()` first, unrelated
    to whether `hideEvent` ever ran.
    """
    got = []
    strip.points_changed.connect(got.append)
    before = strip.points()
    strip._drag = 1  # simulate a stranded index without relying on the hide bug to produce it

    _send_move_while_pressed(
        strip,
        QPoint(int(strip.x_of_db(5.0)), int(strip.y_of_time(30.0))),
        held_button=Qt.MouseButton.NoButton,  # a plain hover: no button held
    )

    assert strip.points() == before
    assert not got


def test_a_strip_hidden_for_want_of_a_transform_reappears_once_profiles_load(
    fake_iface, tmp_path, answer_modal
):
    """m6. `ProcessingDock` never reacts to `session.line_loaded` (only
    `ProfileDock` does, to re-render) -- so a curve step selected while
    `ProfileDock` has no transform yet stayed hidden by `show_gain_strip`'s
    own design (`view.transform is None`), with nothing to re-check it
    once a render eventually supplies one: `_render()` only calls
    `_sync_strip_mapping()`, never `show_gain_strip()`. Fixed by having
    `NsgeoPlugin` re-run `_sync_gain_strip` on `line_loaded` too -- the one
    render-triggering signal that used to reach only `ProfileDock`.

    `dock.view.clear()` constructs the "nothing has rendered yet"
    precondition directly, the same public reset `ProfileDock._clear_
    view_only` itself uses: an end-to-end race producing a transform-less
    `ProfileDock` with a curve row already selected could not be reliably
    reproduced against today's `ProfileDock._open` (its header-only
    branch already supplies a transform immediately on `line_opened`,
    before any profile ever loads, so the specific race this fix guards
    against did not reproduce through the full plugin in the time
    available) -- this drives the exact condition `show_gain_strip`'s own
    docstring names instead of chasing the timing that produces it.
    """
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(0)
    assert not plugin.profile_dock.gain_strip.isHidden()

    plugin.profile_dock.view.clear()  # "nothing has rendered yet"
    plugin.processing_dock.list.setCurrentRow(-1)
    plugin.processing_dock.list.setCurrentRow(0)  # reselect with no transform available
    assert plugin.profile_dock.gain_strip.isHidden()  # correct, for this instant

    s.set_profiles(key, line.load())  # profiles "finish loading"
    assert not plugin.profile_dock.gain_strip.isHidden()  # m6: now re-shown

    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def test_qtest_mousedclick_is_forbidden_in_this_tier(strip):
    """m4 (fix round 1 review). `QTest.mouseDClick` corrupts mouse state
    that outlives the test (see `_send_double_click`'s own docstring
    above) -- `conftest.py`'s `_no_unhandled_modals` now forbids it
    repo-wide, the same way it already forbids a real modal, so a future
    test cannot reintroduce this hazard just by not knowing about it.
    """
    with pytest.raises(AssertionError, match="mouseDClick"):
        QTest.mouseDClick(
            strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(0, 0)
        )


def test_gain_strip_slots_do_not_raise_after_unload(fake_iface, tmp_path):
    """m5 (fix round 1 review). `unload()` nulls `self.session`/
    `self.profile_dock`/`self.processing_dock` but only `deleteLater()`s
    the docks (never disconnects `step_selected`/`gain_points_changed`),
    so a signal already queued when `unload()` ran can still reach these
    slots afterwards. An `assert ... is not None` there would raise
    `AssertionError` inside a slot nothing sees fail (see the module
    docstring's own signal/slot hazard); `_update_enabled`'s own
    None-guard pattern is used instead, so a slot firing late is a
    no-op.

    Calling the slots directly, not through a driven signal: unload()
    already tears down the one thing (the docks) that would let a real
    signal reach them, so there is no real emitter left to drive by the
    time this needs to probe the guard -- unlike the drag tests above,
    where a real widget and a real signal are both still available.
    """
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.unload()

    plugin._sync_gain_strip(0)  # must not raise
    plugin._on_gain_points([[0.0, 0.0], [1.0, 1.0]])  # must not raise
    plugin._on_gain_reset()  # must not raise
    plugin._resync_gain_strip("x")  # must not raise


# ---- headroom under the curve (#10) --------------------------------------

FLAT = [[-11.0, 0.0], [99.0, 0.0]]
DEEP = [[-11.0, 0.0], [40.0, 0.0], [99.0, 30.0]]


def h(env, one_sided=False):
    return Headroom(2.0, 0.0, 0.5, np.asarray(env, dtype=float), one_sided)


def _px(strip, x, row):
    return strip.grab().toImage().pixelColor(int(x), int(strip.y_of_time(0.5 * row)))


def _two_level():
    return np.concatenate([np.full(100, 1.0), np.full(100, 2.4)])


def test_amplitudes_map_to_the_centre_the_limits_and_the_edge(strip):
    strip.set_headroom(h(np.zeros(200)))
    for a, x in [(0, 48.0), (2.0, 78.4), (-2.0, 17.6), (10.0, 86.0), (-10.0, 10.0)]:
        assert strip.x_of_amplitude(a) == pytest.approx(x)


def test_a_depth_past_the_limit_is_painted_red(strip):
    strip.set_headroom(h(_two_level()))
    c = _px(strip, 82, 150)
    assert c.red() > 150 and c.green() < 100
    c = _px(strip, 82, 50)
    assert min(c.red(), c.green(), c.blue()) > 240


def test_inside_the_limits_the_band_is_grey(strip):
    strip.set_headroom(h(_two_level()))
    c = _px(strip, strip.x_of_amplitude(0.25), 50)
    chans = [c.red(), c.green(), c.blue()]
    assert max(chans) - min(chans) <= 3 and max(chans) < 245


def test_a_one_sided_band_leaves_the_negative_side_empty(strip):
    strip.set_headroom(h(np.full(200, 1.0), one_sided=True))
    c = _px(strip, strip.x_of_amplitude(-0.5), 50)
    assert min(c.red(), c.green(), c.blue()) > 240
    c = _px(strip, strip.x_of_amplitude(0.5), 50)
    assert max(c.red(), c.green(), c.blue()) < 245


def test_the_cursor_trace_is_drawn_and_can_be_cleared(strip):
    strip.set_headroom(h(np.zeros(200)))
    strip.set_trace(np.full(200, 1.0))
    x = strip.x_of_amplitude(1.0)

    def darkest():
        return min(_px(strip, x + d, 50).red() for d in (-1, 0, 1))

    assert darkest() < 80
    strip.set_trace(None)
    assert darkest() >= 80


def test_no_headroom_draws_the_curve_alone(strip):
    strip.set_headroom(h(_two_level()))
    strip.set_headroom(None)
    c = _px(strip, 78, 150)
    assert min(c.red(), c.green(), c.blue()) > 240
    assert strip.trace is None


def test_the_zero_db_line_is_blue(strip):
    x = round(strip.x_of_db(0.0))
    ys = range(int(strip.y_of_time(0.0)) + 20, int(strip.y_of_time(0.0)) + 41)
    img = strip.grab().toImage()
    assert any(img.pixelColor(x, y).blue() > img.pixelColor(x, y).red() + 40 for y in ys)


@pytest.fixture
def curve_dock(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("gain_curve", points=FLAT))
    yield session, dock, key
    dock.hide()
    dock.deleteLater()


def test_the_strip_receives_the_displayed_envelope_and_the_display_limit(curve_dock):
    _, dock, _ = curve_dock
    dock.show_gain_strip(FLAT, "c")
    hr = dock.gain_strip.headroom
    assert hr is not None
    assert hr.limit == dock.image.limit
    np.testing.assert_array_equal(hr.envelope, row_envelope(dock.image.rg.data, dock.percentile))
    assert hr.t0_ns == dock.image.rg.t0_ns


def test_a_curve_edit_keeps_the_limits_still_and_moves_the_band(curve_dock):
    session, dock, key = curve_dock
    dock.show_gain_strip(FLAT, "c")
    before = dock.gain_strip.headroom
    session.replace_step(key, 1, build_step("gain_curve", points=DEEP))
    after = dock.gain_strip.headroom
    assert after.limit == before.limit
    assert after.envelope[-1] / before.envelope[-1] == pytest.approx(10 ** (30 / 20), rel=1e-6)


def test_the_cursor_trace_follows_the_session_cursor(curve_dock):
    session, dock, key = curve_dock
    session.replace_step(key, 1, build_step("gain_curve", points=DEEP))
    dock.show_gain_strip(DEEP, "c")
    assert dock.gain_strip.trace is None
    rg = dock.image.rg
    # The displayed data is not the bypassed reference: a trace read from
    # `image.reference` would differ at depth.
    assert not np.array_equal(rg.data, dock.image.reference.data)
    session.set_trace(key, 0)
    np.testing.assert_array_equal(dock.gain_strip.trace, rg.data[:, 0])
    session.set_trace(key, 10**6)
    np.testing.assert_array_equal(dock.gain_strip.trace, rg.data[:, -1])


def test_the_difference_view_draws_the_curve_alone(curve_dock):
    _, dock, _ = curve_dock
    dock.show_gain_strip(FLAT, "c")
    assert dock.gain_strip.headroom is not None
    dock.set_difference_index(1)
    assert dock.gain_strip.headroom is None


def test_the_percentile_slider_rescales_the_band(curve_dock):
    _, dock, _ = curve_dock
    dock.show_gain_strip(FLAT, "c")
    dock.percentile_slider.setValue(950)
    hr = dock.gain_strip.headroom
    np.testing.assert_array_equal(hr.envelope, row_envelope(dock.image.rg.data, 95.0))
    assert hr.limit == dock.image.limit


def test_a_strip_shown_after_a_percentile_change_uses_the_new_percentile(curve_dock):
    _, dock, _ = curve_dock
    dock.show_gain_strip(None)
    dock.percentile_slider.setValue(950)
    dock.show_gain_strip(FLAT, "c")
    np.testing.assert_array_equal(
        dock.gain_strip.headroom.envelope, row_envelope(dock.image.rg.data, 95.0)
    )


def test_unipolar_output_gives_a_one_sided_band(curve_dock):
    session, dock, key = curve_dock
    dock.show_gain_strip(FLAT, "c")
    assert dock.gain_strip.headroom.one_sided is False
    session.append_step(key, build_step("amp_envelope"))
    assert dock.gain_strip.headroom.one_sided is True


def _add_second_line(session, tmp_path, *, load):
    p = synthetic_dzt(tmp_path / "raw", "FILE__002.DZT")
    line = Line.open(p, GridPlacement("A", "y", 1.0))
    session.add_lines([line])
    key_b = session.keys()[-1]
    assert key_b != session.keys()[0]
    if load:
        session.set_profiles(key_b, line.load())
    return key_b


def test_a_line_without_profiles_does_not_inherit_the_previous_lines_band(curve_dock, tmp_path):
    session, dock, key = curve_dock
    dock.show_gain_strip(FLAT, "c")
    assert dock.gain_strip.headroom is not None
    key_b = _add_second_line(session, tmp_path, load=False)
    session.append_step(key_b, build_step("gain_curve", points=FLAT))
    session.open_line(key_b)
    assert dock.image is None
    dock.show_gain_strip(FLAT, "c")  # what the plugin's _sync_gain_strip does
    assert dock.gain_strip.headroom is None
    assert dock.gain_strip.trace is None


def test_closing_the_site_takes_the_strips_band_away(curve_dock):
    session, dock, _ = curve_dock
    dock.show_gain_strip(FLAT, "c")
    assert dock.gain_strip.headroom is not None
    session.close_site()
    assert dock.gain_strip.headroom is None
    dock.show_gain_strip(FLAT, "c")
    assert dock.gain_strip.headroom is None


def test_leaving_a_preview_re_pushes_the_band_at_the_current_percentile(curve_dock, tmp_path):
    session, dock, key = curve_dock
    key_b = _add_second_line(session, tmp_path, load=True)
    dock.show_gain_strip(FLAT, "c")
    session.set_preview(key_b, 0)
    dock.percentile_slider.setValue(950)
    session.set_preview(None)
    assert dock.gain_strip.isVisible()
    np.testing.assert_array_equal(
        dock.gain_strip.headroom.envelope, row_envelope(dock.image.rg.data, 95.0)
    )


# ---- Task 2: limits, off-record handles, caption, Reset (#49, #8, #9) ----------


def _press_drag_release(strip, start, end):
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    _send_move_while_pressed(strip, end)
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)


def test_db_limit_matches_the_core():
    """Guard test: `DB_LIMIT` is a copy of the core's bound, so it must track
    the `gain_curve` `points` schema. Fails if `DB_LIMIT` drifts from the
    core's min/max (e.g. mutate `DB_LIMIT = 120.0` to `100.0`)."""
    (spec,) = get_step("gain_curve").schema()
    assert spec.min == -DB_LIMIT and spec.max == DB_LIMIT == 120.0


def test_the_range_never_passes_the_limit(strip):
    strip.set_points([[0, 0], [50, 118]], "o")
    assert strip._db_range()[1] == 120.0
    strip.set_points([[0, 0], [50, -118]], "o")
    assert strip._db_range()[0] == -120.0


def test_a_drag_to_the_edge_stops_at_120_db(strip):
    strip.set_points([[0, 0], [50, 118]], "o")
    got = []
    strip.points_changed.connect(got.append)
    start = QPoint(int(strip.x_of_db(118.0)), int(strip.y_of_time(50.0)))
    assert strip.handle_at(start) == 1
    _press_drag_release(strip, start, QPoint(start.x() + 200, start.y()))
    assert got[-1][1][1] == 120.0
    assert strip.points()[1][1] == 120.0


def test_a_double_click_at_the_edge_adds_at_most_120(strip):
    strip.set_points([[0, 0], [50, 118]], "o")
    got = []
    strip.points_changed.connect(got.append)
    _send_double_click(strip, QPoint(strip.width() - 1, int(strip.y_of_time(80.0))))
    assert len(strip.points()) == 3
    assert max(db for _t, db in got[-1]) == 120.0


PINNED = [[-11.0, 0.0], [50.0, 12.0], [100.0, 0.0]]


def test_a_point_before_the_record_is_pinned_and_reachable(strip):
    strip.set_points(PINNED, "o")
    top = QPoint(int(strip.x_of_db(0.0)), int(strip.y_of_time(0.0)))
    assert strip.handle_at(top) == 0
    px = strip.time_of_y(strip.y_of_time(0.0) + 1) - strip.time_of_y(strip.y_of_time(0.0))
    _press_drag_release(strip, top, QPoint(top.x(), int(strip.y_of_time(20.0))))
    assert strip.points()[0][0] == pytest.approx(20.0, abs=px)


def test_a_pinned_point_can_be_right_clicked_away(strip):
    strip.set_points(PINNED, "o")
    top = QPoint(int(strip.x_of_db(0.0)), int(strip.y_of_time(0.0)))
    QTest.mouseClick(strip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, top)
    assert len(strip.points()) == 2
    assert all(t != -11.0 for t, _db in strip.points())


def test_a_point_after_the_record_is_pinned_to_the_bottom(strip):
    strip.set_points([[0, 0], [50, 6], [130, 0]], "o")
    pos = QPoint(int(strip.x_of_db(0.0)), int(strip.y_of_time(100.0)))
    assert strip.handle_at(pos) == 2


def test_a_point_outside_a_zoomed_window_is_not_pinned(strip):
    """Guard test: pinning is against the record (`t0_ns`/`t_end`), not the
    zoomed window. Fails if `_drawn` compares a point's time with the
    window's `time_lo`/`time_hi` instead (the point at 80 ns would then be
    pinned to the window's bottom edge and found there)."""
    t = ViewTransform.fit(100, 200, 0.0, 0.5, 600, 300)
    strip.set_time_mapping(t.with_window(0, 100, 20.0, 60.0), MARGIN_TOP)
    strip.set_points([[0, 0], [40, 6], [80, 0]], "o")
    pos = QPoint(int(strip.x_of_db(0.0)), int(MARGIN_TOP + strip._transform.height))
    assert strip.handle_at(pos) is None


def _caption_fits(strip):
    low, mid, high = strip.caption_texts()
    fm = QFontMetrics(strip.caption_font())
    used = fm.horizontalAdvance(low) + fm.horizontalAdvance(high)
    if mid is not None:
        used += fm.horizontalAdvance(mid)
    assert used <= strip.width() - 4
    assert low and high
    return low, mid, high


def test_the_caption_fits_at_the_test_font(strip):
    _caption_fits(strip)


def test_the_caption_fits_at_a_large_font(strip):
    font = strip.font()
    font.setPointSize(16)
    strip.setFont(font)
    strip.set_points([[0, -120], [100, 120]], "o")
    fm = QFontMetrics(strip.font())
    full = sum(fm.horizontalAdvance(x) for x in ("-120", "dB", "120"))
    assert full > strip.width() - 4  # the precondition: all three cannot fit
    low, mid, high = _caption_fits(strip)
    assert (low, high) == ("-120", "120")
    assert mid is None


def _rects_ok(strip):
    rects = [r for r in strip.caption_rects() if r is not None]
    for a, b in zip(rects, rects[1:], strict=False):
        assert a.right() <= b.left(), (a, b)
    for r in rects:
        assert r.left() >= 0 and r.right() <= strip.width(), r


@pytest.mark.parametrize("pts", [[[0, -3.89], [50, 19.26]], [[0, -13.16], [50, 43.84]]])
@pytest.mark.parametrize("size", [None, 16])
def test_the_caption_never_overprints_on_ordinary_values(strip, pts, size):
    """Any drag gives a float dB; the ends are whole numbers and the three
    texts are laid out without overlap, inside the strip."""
    if size is not None:
        font = strip.font()
        font.setPointSize(size)
        strip.setFont(font)
    strip.set_points(pts, "o")
    low, mid, high = strip.caption_texts()
    assert len(low) <= 4 and len(high) <= 4
    _rects_ok(strip)
    if size is not None:
        fm = QFontMetrics(strip.font())
        full = sum(fm.horizontalAdvance(x) for x in (low, "dB", high))
        assert full + 8 > strip.width() - 4  # precondition: dB cannot fit at this font
        assert mid is None


def test_the_caption_shrinks_its_font_when_the_numbers_alone_do_not_fit(strip):
    font = strip.font()
    font.setPointSize(30)
    strip.setFont(font)
    strip.set_points([[0, -120], [100, 120]], "o")
    fm = QFontMetrics(strip.font())
    assert fm.horizontalAdvance("-120") + fm.horizontalAdvance("120") > strip.width() - 4
    assert strip.caption_font().pointSizeF() < 30
    low, _mid, high = strip.caption_texts()
    assert (low, high) == ("-120", "120")
    _rects_ok(strip)


def test_dB_is_centred_in_the_gap_between_the_numbers(strip):
    strip.set_points([[0, 0], [100, 20]], "o")
    low_r, mid_r, high_r = strip.caption_rects()
    assert mid_r is not None
    gap_mid = (low_r.right() + high_r.left()) / 2
    assert mid_r.center().x() == pytest.approx(gap_mid, abs=1.0)


def test_the_round_values_are_whole_dB(strip):
    strip.set_points([[0, -3.89], [50, 19.26]], "o")
    assert strip._db_range() == (-10.0, 26.0)  # floor(-9.89), ceil(25.26)


def test_reset_emits_reset_requested(strip):
    got = []
    strip.reset_requested.connect(lambda: got.append(1))
    edge = MARGIN_TOP + strip._transform.height
    # the precondition: the button has room, so a failure below names its cause
    assert strip.height() - edge - (HANDLE_RADIUS + 2) >= 14
    assert strip.reset_button.isVisible()
    strip.reset_button.click()
    assert got == [1]


def test_profile_dock_relays_reset(qgis_app):
    dock = ProfileDock(SiteSession())
    try:
        got = []
        dock.gain_reset_requested.connect(lambda: got.append(1))
        dock.gain_strip.reset_button.click()
        assert got == [1]
    finally:
        dock.hide()
        dock.deleteLater()


def test_reset_starts_below_the_handles(strip):
    edge = MARGIN_TOP + strip._transform.height
    assert strip.reset_button.geometry().top() >= edge + HANDLE_RADIUS + 2
    assert strip.reset_button.geometry().bottom() <= strip.height()


def test_a_press_just_below_the_last_samples_handle_grabs_the_handle(strip):
    edge = MARGIN_TOP + strip._transform.height
    last = strip._transform.t_end - strip._transform.dt_ns
    strip.set_points([[0.0, 0.0], [last, 12.0]], "o")
    pos = QPoint(int(strip.x_of_db(12.0)), int(edge + 3))
    assert strip.handle_at(pos) == 1
    assert strip.childAt(pos) is not strip.reset_button
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert strip._drag == 1
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def test_a_pinned_bottom_handle_lies_inside_the_record(strip):
    edge = MARGIN_TOP + strip._transform.height
    strip.set_points([[0.0, 0.0], [50.0, 6.0], [130.0, 3.0]], "o")
    x = int(strip.x_of_db(3.0))
    body = QPoint(x, int(edge - 6))
    assert strip.handle_at(body) == 2
    assert strip.childAt(QPoint(x, int(edge - 1))) is not strip.reset_button
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, body)
    assert strip._drag == 2
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, body)


def test_a_failing_move_or_double_click_is_logged_not_raised(strip, monkeypatch):
    import nsgeo_qgis.ui.gain_strip as gs

    logged = []
    monkeypatch.setattr(gs, "_log", lambda msg, *a, **k: logged.append(msg))
    x0, y0 = strip.x_of_db(20.0), strip.y_of_time(100.0)
    QTest.mousePress(
        strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x0), int(y0))
    )
    monkeypatch.setattr(strip, "db_of_x", lambda x: 1 / 0)
    try:
        _send_move_while_pressed(strip, QPoint(int(x0) - 10, int(y0)))
        assert logged
        n = len(logged)
        _send_double_click(strip, QPoint(int(x0) - 10, int(strip.y_of_time(30.0))))
        assert len(logged) > n
    finally:
        QTest.mouseRelease(
            strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(0, 0)
        )


# ---- the gain slots: refusal, Reset, the strip's clock, failures (#49 #9 #15 #25) ----


def _finish(plugin, answer_modal):
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()


def _toast(fake_iface):
    item = fake_iface.messageBar().currentItem()
    return "" if item is None else item.text()


def test_a_refused_curve_snaps_back_with_a_toast(fake_iface, tmp_path, answer_modal):
    """#49: a payload the core refuses (130 dB) used to stay drawn on the strip
    while the step kept its old points."""
    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)
    try:
        strip = plugin.profile_dock.gain_strip
        before = s.stack_for(key).entries[0][0]
        shown = plugin.profile_dock.shown_zero_ns()
        zero = plugin.profile_dock.step_input_zero_ns(0)
        strip.set_points([[0.0, 0.0], [50.0, 130.0]], plugin._gain_owner)
        strip.points_changed.emit(strip.points())
        assert s.stack_for(key).entries[0][0] is before
        assert np.ravel(strip.points()) == pytest.approx(
            np.ravel(plugin._points_on_clock(before.params["points"], zero, shown))
        )
        assert "120" in _toast(fake_iface)
    finally:
        _finish(plugin, answer_modal)


def _curve_row_ctx(plugin, s, key, row):
    from nsgeo_qgis.lookup import identity_curve

    return identity_curve(*plugin.processing_dock.input_axis(row))


def test_reset_asks_and_writes_the_flat_curve(fake_iface, tmp_path, answer_modal):
    from nsgeo_qgis import plugin as plugin_mod

    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)
    try:
        asked = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
        n = len(_step_points(s, key, 0))
        plugin.profile_dock.gain_reset_requested.emit()
        assert _step_points(s, key, 0) == _curve_row_ctx(plugin, s, key, 0)
        assert len(asked) == 1
        args = asked[0][0]
        assert args[1] == plugin_mod.RESET_TITLE
        assert args[2] == plugin_mod.RESET_QUESTION.format(n=n)
    finally:
        _finish(plugin, answer_modal)


def test_reset_answered_no_changes_nothing(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)
    try:
        before = s.stack_for(key).entries[0][0]
        asked = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.No)
        plugin.profile_dock.gain_reset_requested.emit()
        assert len(asked) == 1  # it did ask: without the slot nothing is asked
        assert s.stack_for(key).entries[0][0] is before
    finally:
        _finish(plugin, answer_modal)


def test_reset_of_a_flat_curve_asks_nothing(fake_iface, tmp_path, answer_modal):
    from nsgeo_qgis.lookup import identity_curve

    plugin, s, key = _plugin_with_time_zero_after_curve(
        fake_iface, tmp_path, points=[[0.0, 0.0], [20.0, 0.0], [40.0, 0.0]]
    )
    try:
        # No answer_modal for the question: an unanswered modal fails the test.
        plugin.profile_dock.gain_reset_requested.emit()
        want = identity_curve(*plugin.processing_dock.input_axis(0))
        assert _step_points(s, key, 0) == want
        # Already the identity: nothing is written, the session stays clean.
        before = s.stack_for(key).entries[0][0]
        plugin.profile_dock.gain_reset_requested.emit()
        assert s.stack_for(key).entries[0][0] is before
    finally:
        _finish(plugin, answer_modal)


def test_reset_behind_time_zero_is_on_the_time_zero_clock(fake_iface, tmp_path, answer_modal):
    import nsgeo_qgis
    from nsgeo_qgis.lookup import identity_curve

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    s.append_step(key, build_step("gain_curve", points=[[5.0, 0.0], [40.0, 12.0]]))
    plugin.processing_dock.list.setCurrentRow(1)
    try:
        header_t0 = s.line_for_key(key).header.position_ns
        t0, _dt, _n = plugin.processing_dock.input_axis(1)
        assert t0 == 0.0 and header_t0 != 0.0  # the clocks differ
        asked = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
        plugin.profile_dock.gain_reset_requested.emit()
        assert len(asked) == 1
        # The whole curve, on the clock of what the step receives (Time zero's),
        # not the header's position_ns.
        assert _step_points(s, key, 1) == identity_curve(*plugin.processing_dock.input_axis(1))
        assert _step_points(s, key, 1)[0][0] == t0
    finally:
        _finish(plugin, answer_modal)


def test_the_strip_waits_for_its_clock(fake_iface, tmp_path, answer_modal, monkeypatch):
    import nsgeo_qgis
    from nsgeo_qgis.loader import LineLoader

    monkeypatch.setattr(LineLoader, "request", lambda self, k: None)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.open_line(key)  # no profiles yet
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [40.0, 12.0]]))
    plugin.processing_dock.list.setCurrentRow(1)
    try:
        assert plugin.profile_dock.gain_strip.isHidden()
        s.set_profiles(key, line.load())
        strip = plugin.profile_dock.gain_strip
        assert not strip.isHidden()
        zero = plugin.profile_dock.shown_zero_ns()
        input_zero = plugin.profile_dock.step_input_zero_ns(1)
        want = plugin._points_on_clock(_step_points(s, key, 1), input_zero, zero)
        assert np.ravel(strip.points()) == pytest.approx(np.ravel(want))
    finally:
        _finish(plugin, answer_modal)


def test_each_gain_slot_reports_an_exception(fake_iface, tmp_path, answer_modal, monkeypatch):
    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("boom")

    try:
        bar = fake_iface.messageBar()
        cases = [
            (plugin.profile_dock, "show_gain_strip", lambda: plugin._sync_gain_strip(0)),
            (plugin.processing_dock, "current_row", lambda: plugin._resync_gain_strip(key)),
            (
                s,
                "replace_step",
                lambda: plugin._on_gain_points([[0.0, 0.0], [30.0, 5.0]]),
            ),
            (plugin.processing_dock, "input_axis", plugin._on_gain_reset),
        ]
        for obj, attr, call in cases:
            if hasattr(bar, "clearWidgets"):
                bar.clearWidgets()
            with monkeypatch.context() as m:
                m.setattr(obj, attr, boom)
                call()
            assert "boom" in _toast(fake_iface), attr
    finally:
        _finish(plugin, answer_modal)


def test_unload_forgets_the_gain_curve(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_time_zero_after_curve(fake_iface, tmp_path)
    assert plugin._gain_owner is not None and plugin._gain_step is not None
    _finish(plugin, answer_modal)
    assert plugin._gain_owner is None and plugin._gain_step is None


@needs_real_data
def test_the_real_strip_stops_at_120_and_resets(fake_iface, tmp_path, answer_modal):
    """Guard test (real FILE__007): a real drag far past the strip's edge
    writes exactly 120.0 dB, and Reset gives the identity on the file's
    input axis. Fails under these mutations (checked): removing BOTH
    `GainStrip._limited` and the `DB_LIMIT` cap in `GainStrip._db_range`
    (the step then holds 118.0; removing either one alone still reaches
    120, so each is pinned by the strip tests in this file instead); and
    making `_on_gain_reset` return before `replace_step` (the Reset half).
    """
    import nsgeo_qgis
    from nsgeo_qgis.lookup import identity_curve

    path = next(p for p in REAL_DZT if p.name == "FILE__007.DZT")
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    line = Line.open(path, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [40.0, 118.0]]))
    plugin.processing_dock.list.setCurrentRow(0)
    strip = plugin.profile_dock.gain_strip
    dock = plugin.profile_dock
    try:
        dock.show()
        strip.show()
        pts = strip.points()
        start = QPoint(int(strip.x_of_db(pts[1][1])), int(strip.y_of_time(pts[1][0])))
        assert strip.handle_at(start) == 1
        end = QPoint(strip.width() + 400, start.y())
        QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        _send_move_while_pressed(strip, end)
        QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        assert _step_points(s, key, 0)[1][1] == 120.0
        answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Yes)
        dock.gain_reset_requested.emit()
        assert _step_points(s, key, 0) == identity_curve(*plugin.processing_dock.input_axis(0))
    finally:
        dock.hide()
        dock.deleteLater()
        from qgis.PyQt.QtWidgets import QApplication

        QApplication.processEvents()
        _finish(plugin, answer_modal)


def test_a_refusing_step_above_the_curve_adds_no_log_noise_per_write(
    fake_iface, tmp_path, answer_modal, message_log
):
    """Every drag move echoes through `_sync_gain_strip`; deciding "is the
    clock known" by evaluating the stack logged "input_axis: stack does not
    evaluate cleanly" on each one when a step above the curve refuses."""
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    # A step above the curve that cannot run on this line (past the record).
    s.append_step(key, build_step("time_zero", mode="sample", sample=100000))
    s.append_step(key, build_step("gain_curve", points=[[0.0, 0.0], [40.0, 12.0]]))
    plugin.processing_dock.list.setCurrentRow(1)
    try:
        message_log.clear()
        for _ in range(5):
            plugin._sync_gain_strip(1)
        assert [m for m in message_log if "does not evaluate" in m] == []
    finally:
        _finish(plugin, answer_modal)
