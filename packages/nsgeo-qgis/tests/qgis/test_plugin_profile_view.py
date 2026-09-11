from __future__ import annotations

import sys

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.model.survey import Profile
from nsgeo.processing import Radargram
from nsgeo.render import DEFAULT_COLORMAP
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.render.qimage import RadargramImage, rgb_to_qimage
from nsgeo_qgis.ui.profile_view import (
    CURSOR_COLOUR,
    MARGIN_LEFT,
    MARGIN_TOP,
    ProfileView,
)
from nsgeo_qgis.ui.view_transform import ViewTransform
from plugin_testing import REAL_DZT, needs_real_data
from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication


def _rg(n_traces=200, n_samples=128):
    rng = np.random.default_rng(3)
    data = rng.normal(size=(n_samples, n_traces))
    data[20:24, :] += 8.0
    return Radargram(data=data, dt_ns=0.5, t0_ns=-4.0)


def _send_move_while_pressed(
    widget, local_pos: QPoint, held_button=Qt.MouseButton.LeftButton
) -> None:
    """A mouse move sent *while a button is logically held* (i.e. between a
    `QTest.mousePress` and the matching `mouseRelease`) is not reliably
    delivered by `QTest.mouseMove` -- confirmed directly in this
    environment (offscreen QPA): the identical `QTest.mousePress(...)` +
    `QTest.mouseMove(...)` sequence the task brief's own drag-select test
    uses never invokes `mouseMoveEvent` at all when a button is still
    down, though the exact same `QTest.mouseMove` call works fine with no
    button held (as `test_mouse_move_emits_the_trace_under_the_cursor`
    above confirms). Building and sending the `QMouseEvent` directly
    bypasses `QTest`'s cursor-warp-based simulation and reaches the
    widget's real `mouseMoveEvent` every time, which is what a genuine
    OS-level drag actually delivers.
    """
    local = QPointF(local_pos)
    glob = QPointF(widget.mapToGlobal(local_pos))
    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        local,
        glob,
        Qt.MouseButton.NoButton,
        held_button,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, ev)


def test_rgb_to_qimage_owns_its_memory_and_matches_pixels():
    rgb = np.zeros((2, 3, 3), dtype=np.uint8)
    rgb[0, 1] = (255, 0, 0)
    img = rgb_to_qimage(rgb)
    # NOTE: `del rgb` (the brief's own probe) does NOT actually catch a
    # missing `.copy()` in this environment -- confirmed directly by
    # mutating `rgb_to_qimage` to drop `.copy()` and rerunning: the pixel
    # assertions below still passed. PyQt5's raw-buffer QImage constructor
    # evidently keeps its own reference to the buffer object passed in
    # (`rgb.data`, a memoryview), which keeps the ndarray's memory alive
    # regardless of the local name `rgb` being deleted -- so `del` alone
    # never actually exercises the "buffer freed out from under the
    # QImage" hazard this test is named for.
    #
    # Overwriting the array's bytes *in place* (`rgb[:] = ...`, no rebind)
    # is what actually distinguishes a real copy from a shared view: with
    # `.copy()` present, `img`'s pixels are independent storage and must
    # not change; without it, `img` is a window onto the same bytes and
    # the overwrite corrupts it too. Verified both ways directly (see the
    # task report): this fails with `.copy()` removed, passes with it.
    rgb[:] = 99
    del rgb
    assert (img.width(), img.height()) == (3, 2)
    assert QColor(img.pixel(1, 0)).red() == 255 and QColor(img.pixel(0, 0)).red() == 0


def test_radargram_image_caches_and_rebuilds_on_display_change():
    ri = RadargramImage(_rg())
    img = ri.image
    assert img is ri.image  # cached
    assert (img.width(), img.height()) == (200, 128)
    ri2 = ri.with_display(percentile=95.0)
    assert ri2.rg is ri.rg and ri2.limit < ri.limit
    ri3 = ri.with_display(colormap_name="grey_white_high")
    # NOTE: the brief's own probe here was
    #   `ri3.image.pixel(0, 0) != img.pixel(0, 0) or ri3.colormap_name != DEFAULT_COLORMAP`
    # -- the right-hand disjunct is `"grey_white_high" != "grey_black_high"`,
    # always true regardless of what the left-hand side (the actual pixel
    # comparison) evaluates to, so the assertion could never fail no matter
    # how `with_display`/`colormap`/`to_rgb8` behaved. Dropped the escape
    # hatch and assert the pixel comparison directly. This is safe, not
    # flaky: `_grey()` builds `grey_black_high[i] = 255 - i` and
    # `grey_white_high[i] = i` for every index `i` in 0..255 exactly (both
    # ramps are whole-integer `linspace` steps), so the two tables disagree
    # at every single index -- there is no amplitude value at which the two
    # colormaps could coincide.
    assert ri3.image.pixel(0, 0) != img.pixel(0, 0)
    assert ri3.colormap_name != DEFAULT_COLORMAP


def test_radargram_image_decimates_very_wide_lines():
    ri = RadargramImage(Radargram(data=np.zeros((8, 20_000)), dt_ns=0.5, t0_ns=0.0), max_width=4096)
    assert ri.image.width() <= 4096


def test_radargram_image_with_radargram_keeps_display_settings_swaps_data():
    ri = RadargramImage(_rg(), percentile=90.0, colormap_name="seismic")
    rg2 = _rg(n_traces=64, n_samples=32)
    ri2 = ri.with_radargram(rg2)
    assert ri2.rg is rg2
    assert (ri2.percentile, ri2.colormap_name, ri2.max_width) == (90.0, "seismic", ri.max_width)
    assert (ri2.image.width(), ri2.image.height()) == (64, 32)


@pytest.fixture
def make_view(qgis_app):
    """Constructs a `ProfileView` and guarantees it is torn down before the
    test process moves on, instead of being left for Python's GC to collect
    whenever it happens to run.

    Every `ProfileView` in this file is parentless (no dock/main-window
    owns it, unlike production use -- see `nsgeo_qgis.plugin`), and every
    test but the ones using this fixture used to just construct one, use
    it, and `return`/fall off the end with no teardown at all. Confirmed
    directly this is a real, not theoretical, hazard: a *shown*, parentless
    `ProfileView` destroyed by GC instead of Qt (reliably reproduced by
    running each of this file's tests individually rather than as a whole
    suite -- collecting them into one process hides it, because the
    QApplication then outlives every widget) segfaults inside
    `libQt5Widgets.so` at interpreter/`QgsApplication` shutdown, not a
    Python-level exception -- widget teardown ordering, not this file's own
    logic. `hide()` first (so a *shown* top-level window is never left for
    GC to tear down) and `deleteLater()` (so the QObject is deleted through
    Qt's own object-deletion path rather than Python's `__del__` on a
    C++-owned object) together were verified to take every affected test in
    this file from crashing to not, run individually, one at a time.
    """
    widgets: list[ProfileView] = []

    def _make() -> ProfileView:
        v = ProfileView()
        widgets.append(v)
        return v

    yield _make
    for v in widgets:
        v.hide()
        v.deleteLater()


def test_decimated_image_paints_the_correctly_scaled_source_rect(make_view):
    """The hazard the task brief calls out by name: `source_rect()` is in
    *unbinned* trace-index units, but a decimated `RadargramImage.image` is
    narrower than `n_traces` pixels. `paintEvent` must scale the rect down
    by `image.width() / n_traces` before using it as a source rect, or a
    zoom into the tail of a wide line samples the wrong (or an
    out-of-bounds, silently-clipped) part of the smaller cached image.

    Real DZT lines (606-666 traces) never exercise this: they are always
    under `max_width`, so a real-file test proves nothing about the scaling
    itself. This builds a line wide enough to decimate, with data chosen so
    each original trace index maps to a distinct, monotonic amplitude, and
    checks that zooming into two different (non-overlapping) trace windows
    reads two distinctly different parts of the cached image, in the
    correct direction, rather than the same (or an undefined) part.
    """
    n_traces, n_samples = 20_000, 8
    data = np.tile(np.arange(n_traces, dtype=float), (n_samples, 1))
    ri = RadargramImage(Radargram(data=data, dt_ns=0.5, t0_ns=0.0), max_width=2000)
    assert (
        ri.image.width() == 2000
    )  # exact: 20_000 / 10 traces per decimated column, no ragged tail

    v = make_view()
    v.resize(800, 300)
    v.show()
    v.set_axes(n_traces, n_samples, 0.0, 0.5)
    v.set_image(ri.image)
    assert v.transform is not None
    t = v.transform

    def mean_grey(trace_lo: float, trace_hi: float) -> float:
        v.transform = t.with_window(trace_lo, trace_hi, t.time_lo, t.time_hi)
        shot = v.grab_image()
        r = v.image_rect()
        samples = [
            QColor(shot.pixel(r.left() + x, r.top() + 5)).value()
            for x in range(5, r.width() - 5, 20)
        ]
        return float(np.mean(samples))

    low = mean_grey(0.0, 100.0)  # near-zero amplitude: colormap's neutral grey
    high = mean_grey(19_900.0, 20_000.0)  # near-maximum amplitude: darkest under grey_black_high

    # grey_black_high maps high amplitude to low pixel values (dark); a low
    # trace-index window (small amplitude) must read distinctly lighter
    # than a high trace-index window (large amplitude). If the sx/sy scale
    # factors were dropped (source rect used directly in *decimated* image
    # pixels, or not scaled at all), both windows would read from
    # out-of-range or identical image columns and this would not hold.
    assert low > high + 50  # a wide margin: expected gap is ~127 grey levels


@pytest.fixture
def view(make_view):
    v = make_view()
    v.resize(800, 300)
    v.show()
    rg = _rg()
    v.set_axes(
        rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns, distance_along=np.arange(rg.n_traces) / 60.0
    )
    v.set_image(RadargramImage(rg).image)
    return v, rg


def test_paints_the_image_inside_the_margins(view):
    v, rg = view
    shot = v.grab_image()
    r = v.image_rect()
    assert r.left() == MARGIN_LEFT and r.top() == MARGIN_TOP
    inside = [
        QColor(shot.pixel(r.left() + 5 + i, r.top() + 5 + j)).value()
        for i in range(20)
        for j in range(20)
    ]
    assert np.std(inside) > 5  # radargram texture, not a flat fill
    margin = QColor(shot.pixel(5, r.top() + 5))
    assert margin.red() == margin.green() == margin.blue()  # axis gutter is neutral


def test_loading_state_when_there_is_no_image(make_view):
    v = make_view()
    v.resize(400, 200)
    v.set_axes(100, 50, 0.0, 0.5)
    v.set_image(None)
    v.grab_image()  # must not raise
    assert v.transform is not None and v.transform.n_traces == 100


@pytest.mark.parametrize(
    ("n_traces", "n_samples"),
    [
        pytest.param(0, 50, id="empty_trace_axis"),
        pytest.param(100, 0, id="empty_sample_axis"),
    ],
)
def test_paint_event_handles_an_empty_axis_without_dividing_by_zero(make_view, n_traces, n_samples):
    """Defect (a) in the task brief: the reference `paintEvent` computed
    `self._image.width() / t.n_traces` (and the symmetric sample-axis
    division) unconditionally, before ever checking whether the axis was
    empty -- a live `ZeroDivisionError` raised from inside a paint event,
    which Qt swallows silently on every repaint (see the module
    docstring), so the widget would just never draw again with no visible
    error. Task 13 makes `n_traces == 0` / `n_samples == 0` a legal,
    constructible `ViewTransform` state deliberately (not something to
    reject), so this must be handled, not converted into "cannot happen".

    An empty axis with a *non-null* `_image` still set is the exact
    combination that reaches the division: `set_image(None)` alone (the
    other loading-state test) never reaches the division line at all,
    since that branch is guarded by `self._image is not None` already.
    """
    v = make_view()
    v.resize(400, 200)
    v.set_axes(n_traces, n_samples, 0.0, 0.5)
    img = QImage(max(1, n_traces), max(1, n_samples), QImage.Format.Format_RGB888)
    img.fill(QColor(0, 0, 0))
    v.set_image(img)
    v.grab_image()  # must not raise ZeroDivisionError
    assert v.transform is not None
    assert (v.transform.n_traces, v.transform.n_samples) == (n_traces, n_samples)


def test_cursor_is_drawn_at_the_trace(view):
    v, rg = view
    v.set_cursor(100)
    shot = v.grab_image()
    r = v.image_rect()
    x = int(r.left() + v.transform.x_of_trace(100.5))
    column = [QColor(shot.pixel(x, r.top() + y)) for y in range(10, r.height() - 10, 7)]
    assert any(c.red() > 200 and c.blue() < 120 for c in column), CURSOR_COLOUR.name()


def test_mouse_move_emits_the_trace_under_the_cursor(view):
    v, rg = view
    got = []
    v.trace_hovered.connect(got.append)
    r = v.image_rect()
    QTest.mouseMove(v, QPoint(r.left() + r.width() // 2, r.top() + 20))
    assert got and got[-1] == v.transform.trace_index_at(r.width() // 2) == 100


def test_wheel_zooms_about_the_cursor_and_emits_view_changed(view):
    v, rg = view
    changed = []
    v.view_changed.connect(lambda: changed.append(1))
    r = v.image_rect()
    before = v.transform
    v.zoom_at(2.0, r.width() // 2, r.height() // 2)
    assert changed and v.transform.trace_hi - v.transform.trace_lo == pytest.approx(100.0)
    v.fit()
    assert (v.transform.trace_lo, v.transform.trace_hi) == (before.trace_lo, before.trace_hi)


def test_wheel_event_survives_a_degenerate_zoom_factor_instead_of_leaking_to_qt(view, monkeypatch):
    """Defect (b) in the task brief: `ViewTransform` raises on non-finite
    input, and `wheelEvent` feeds it a computed factor (`1.25 ** steps`)
    straight from raw event data with no validation. `wheelEvent` is a
    Qt-invoked virtual method override, not an ordinary Python call: an
    exception escaping it is reported to `sys.excepthook` and otherwise
    vanishes -- confirmed directly (see the task report) that PyQt5 does
    exactly this rather than propagate or abort, so "no exception reached
    the test" is not by itself proof of anything. Installing a capturing
    `sys.excepthook` before dispatching a real `QWheelEvent` and asserting
    it was *not* called is what actually distinguishes "the guard caught
    it" from "the guard doesn't exist and Qt quietly ate it".

    An `angleDelta().y()` of -100_000_000 makes `steps` around -833_333;
    `1.25 ** steps` underflows to exactly `0.0` in IEEE 754 double
    arithmetic (confirmed directly), which then raises `ZeroDivisionError`
    inside `ViewTransform.zoomed` -- not the `ValueError` the brief's
    framing of this defect might suggest, which is exactly why the guard
    in `wheelEvent` must catch `Exception` broadly.
    """
    v, rg = view
    before = v.transform
    excepthook_calls: list[tuple] = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: excepthook_calls.append(a))

    ev = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 0),
        QPoint(0, -100_000_000),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(v, ev)

    assert not excepthook_calls, f"exception leaked out of wheelEvent: {excepthook_calls}"
    assert v.transform == before  # degenerate zoom rejected, last good transform kept

    # the widget must still be responsive afterwards, not stuck:
    v.zoom_at(2.0, 100, 100)
    assert v.transform.trace_hi - v.transform.trace_lo == pytest.approx(100.0)


def test_mouse_move_survives_a_broken_pan_transform_instead_of_leaking_to_qt(view, monkeypatch):
    """The `mouseMoveEvent` half of defect (b). There is no realistic mouse
    delta that makes `ViewTransform.panned` raise (widths/heights are
    always >= 1, and `d.x()`/`d.y()` are ordinary finite pixel deltas), so
    this forces the failure `panned()` is guarded against directly, by
    monkeypatching it to raise -- exercising the guard itself rather than
    hunting for a real-world input that happens to trigger it, which the
    brief's own defect note does not claim exists either ("a bad factor or
    delta *would* produce one", not "does under normal use").
    """
    v, rg = view
    before = v.transform
    excepthook_calls: list[tuple] = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: excepthook_calls.append(a))

    def boom(self, dx, dy):
        raise ValueError("simulated non-finite pan")

    monkeypatch.setattr(ViewTransform, "panned", boom)

    r = v.image_rect()
    QTest.mousePress(
        v,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 100, r.top() + 50),
    )
    assert v._pan_last is not None  # sanity: the press really armed panning
    _send_move_while_pressed(
        v, QPoint(r.left() + 150, r.top() + 60), held_button=Qt.MouseButton.MiddleButton
    )

    assert not excepthook_calls, f"exception leaked out of mouseMoveEvent: {excepthook_calls}"
    assert v.transform == before  # panned() never returned; last good transform kept


def test_shift_click_and_pick_mode_request_picks(view):
    v, rg = view
    picks = []
    v.pick_requested.connect(lambda t, time_ns: picks.append((t, time_ns)))
    r = v.image_rect()
    p = QPoint(r.left() + 40, r.top() + 30)
    QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, p)
    assert len(picks) == 1 and picks[0][0] == v.transform.trace_index_at(40)
    assert picks[0][1] == pytest.approx(v.transform.time_of_y(30))
    v.set_pick_mode(True)
    QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    assert len(picks) == 2


def test_drag_selects_a_trace_range(view):
    """NOTE on `_send_move_while_pressed`: the brief's own reference test
    used plain `QTest.mouseMove` for the drag step. Confirmed directly
    (see the task report) that in this environment (offscreen QPA), a
    `QTest.mouseMove` sent while a button is still logically down (i.e.
    between `QTest.mousePress` and the matching `mouseRelease`) is never
    delivered to `mouseMoveEvent` at all -- as given, this test's drag
    step is a silent no-op and `sel` would stay empty regardless of
    whether drag-selection actually works. Swapped in a directly
    constructed and sent `QMouseEvent` for that one step only; the press
    and release endpoints (which do not depend on a mid-drag move) are
    unchanged.
    """
    v, rg = view
    sel = []
    v.range_selected.connect(lambda a, b: sel.append((a, b)))
    r = v.image_rect()
    QTest.mousePress(
        v,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 100, r.top() + 50),
    )
    _send_move_while_pressed(v, QPoint(r.left() + 300, r.top() + 50))
    QTest.mouseRelease(
        v,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 300, r.top() + 50),
    )
    assert sel == [(28, 86)]  # floor(100/696*200), floor(300/696*200)


def test_depth_axis_uses_the_velocity_model(view):
    v, rg = view
    v.set_velocity(VelocityModel.constant(0.1))
    labels = v.depth_tick_labels()
    # NOTE: the brief's own probe here was
    #   `labels and labels[0].startswith("-") or labels[0] == "0"`
    # `and`/`or` precedence makes this `(labels and labels[0].startswith("-"))
    # or (labels[0] == "0")` -- if `labels` were ever empty, the left disjunct
    # is `[]` (falsy) and evaluation falls through to `labels[0] == "0"`,
    # indexing an empty list: `IndexError`, not a clean assertion failure.
    # Split into two assertions so an empty result fails cleanly instead.
    assert labels
    assert labels[0].startswith("-") or labels[0] == "0"  # top of the record is above time zero


@needs_real_data
def test_real_file_renders_at_full_resolution(make_view):
    h = read_header(REAL_DZT[0])
    rg = Radargram.from_profile(Profile(data=read_samples(REAL_DZT[0])[0], header=h))
    ri = RadargramImage(rg)
    assert (ri.image.width(), ri.image.height()) == (rg.n_traces, 512)
    v = make_view()
    v.resize(900, 320)
    v.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns)
    v.set_image(ri.image)
    v.grab_image()
