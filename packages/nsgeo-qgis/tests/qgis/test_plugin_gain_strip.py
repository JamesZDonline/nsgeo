from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gain_strip import GainStrip
from nsgeo_qgis.ui.profile_dock import ProfileDock
from nsgeo_qgis.ui.profile_view import MARGIN_TOP
from nsgeo_qgis.ui.view_transform import ViewTransform
from plugin_testing import send_double_click as _send_double_click
from plugin_testing import send_move_while_pressed as _send_move_while_pressed
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import QPoint, Qt
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
    s.set_points([[0.0, 0.0], [100.0, 20.0]])
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
    dock.show_gain_strip([[-11.0, 0.0], [99.0, 0.0]])
    assert not dock.gain_strip.isHidden()
    assert dock.gain_strip.y_of_time(-11.0) == pytest.approx(
        MARGIN_TOP + dock.view.transform.y_of_time(-11.0)
    )
    changed = []
    dock.gain_points_changed.connect(changed.append)
    dock.gain_strip.set_points([[-11.0, 0.0], [99.0, 12.0]])
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
    plugin.profile_dock.gain_strip.set_points([[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]])
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

    plugin.profile_dock.gain_strip.set_points([[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]])
    plugin.profile_dock.gain_strip.points_changed.emit(plugin.profile_dock.gain_strip.points())
    assert s.stack_for(key).entries[1][0].params["points"][1] == [50.0, 6.0]

    plugin.processing_dock.list.setCurrentRow(0)  # dewow: no curve, strip hides
    assert plugin.profile_dock.gain_strip.isHidden()

    plugin.processing_dock.list.setCurrentRow(1)  # BACK to the same, unchanged gain_curve step
    assert not plugin.profile_dock.gain_strip.isHidden()

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
    strip.set_points([[0.0, 0.0], [50.0, 5.0]])  # must be honoured now, not refused
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
