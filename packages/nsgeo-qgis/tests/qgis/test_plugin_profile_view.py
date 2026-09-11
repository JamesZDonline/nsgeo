from __future__ import annotations

import math
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
    BACKGROUND,
    CURSOR_COLOUR,
    MARGIN_LEFT,
    MARGIN_TOP,
    PICK_COLOUR,
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
    # An exact width, not `<= 4096`: a 1-px-wide image would satisfy `<=`
    # too. `decimate_columns(20_000, 4096)` blocks at `ceil(20_000/4096) = 5`
    # traces per column, giving `ceil(20_000/5) = 4000` columns exactly (no
    # ragged tail: 20_000 / 5 is exact) -- computed independently of
    # `RadargramImage`/`decimate_columns` themselves.
    ri = RadargramImage(Radargram(data=np.zeros((8, 20_000)), dt_ns=0.5, t0_ns=0.0), max_width=4096)
    assert ri.image.width() == 4000


def test_decimation_ragged_tail_scaling_error_is_bounded_at_fit_zoom():
    """m4: a ragged tail (n_traces not an exact multiple of
    decimate_columns' block size) makes paintEvent's `sx = image.width() /
    n_traces` an *average* scale factor rather than the true per-column
    block size, `1 / block`. Not fixed (see the comment in `paintEvent`):
    only reachable on lines wider than `max_width` (8192), and real lines
    are 606-666 traces. Quantifies the resulting error instead of leaving
    it as an unverified claim, so a future change that makes it *worse*
    would be caught, and pins the concrete numbers the review measured.
    """
    n_traces, max_width = 20_001, 2000
    ri = RadargramImage(
        Radargram(data=np.zeros((8, n_traces)), dt_ns=0.5, t0_ns=0.0), max_width=max_width
    )
    block = math.ceil(n_traces / max_width)  # decimate_columns' own block size
    assert (block, ri.image.width()) == (11, 1819)  # the review's own measured numbers
    true_sx = 1.0 / block
    approx_sx = ri.image.width() / n_traces
    # error in image pixels across the *whole* width at fit zoom: sub-pixel.
    assert abs(approx_sx - true_sx) * n_traces == pytest.approx(0.7272727272727927, abs=1e-6)
    assert abs(approx_sx - true_sx) * n_traces < 1.0


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
    logic.

    m1 correction: neither `deleteLater()` here actually deletes any of
    these widgets -- measured directly with `sip`: `sip.isdeleted(v)` stays
    `False` through `deleteLater()` and even `QApplication.processEvents()`
    afterwards (it only becomes `True` after
    `QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`,
    which nothing here calls -- every widget built by this fixture leaks
    for the rest of the process, harmlessly). What actually removes the
    segfault hazard is a *different*, immediate side effect of
    `deleteLater()`: it transfers sip's ownership of the widget from Python
    to C++ (`sip.ispyowned(v)`: `True` before the call, `False` after), so
    Python's GC no longer considers itself responsible for destroying a
    C++-owned top-level widget at interpreter shutdown -- there is nothing
    left for it to race Qt's own teardown over. `hide()` removes the same
    hazard independently, by a different route: a top-level window GC
    might still destroy is only dangerous while *shown*, so never leaving
    one shown removes the hazard regardless of who ends up deleting it.
    Both are applied; five-run exit-code sweeps of one previously-crashing
    test confirmed each alone is already sufficient (`hide()` only: 0/0/0/0/0;
    `deleteLater()` only: 0/0/0/0/0), so an explicit
    `sendPostedEvents(None, DeferredDelete)` flush -- which would actually
    delete the widgets -- was measured and is not needed for correctness
    here, only for an object count that nothing in this file checks.
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


def test_vertical_scaling_reconciles_an_image_shorter_than_n_samples(make_view):
    """m5: `sy = self._image.height() / t.n_samples` is verified only in
    one direction by the horizontal decimation test above -- mutating `sy`
    alone to `1.0` survives the whole suite, because `decimate_columns`
    only ever bins *columns*: on every path built through `RadargramImage`,
    `image.height() == n_samples` always, so `sy` is identically `1.0` on
    every reachable path there. `set_image`/`set_axes` are independent
    public methods, though, and nothing stops a caller from setting an
    image whose height genuinely differs from the axes' sample count.

    Builds a 2-row image directly (bypassing `RadargramImage`, which could
    never produce this mismatch), set against axes declaring 8 samples --
    `sy = 2 / 8 = 0.25` -- and checks that two different time sub-windows
    read the two different image rows in the correct direction. If `sy`
    were `1.0`, both windows would read starting from image row 0..window's
    unscaled `y`, i.e. entirely out of the 2-row image's bounds for the
    lower window, producing indistinguishable (blank/clamped) output
    instead of white-then-black.
    """
    rgb = np.zeros((2, 20, 3), dtype=np.uint8)
    rgb[0, :] = (255, 255, 255)  # image row 0: white -- represents samples [0, 4)
    rgb[1, :] = (0, 0, 0)  # image row 1: black -- represents samples [4, 8)
    img = rgb_to_qimage(rgb)
    assert (img.width(), img.height()) == (20, 2)

    v = make_view()
    v.resize(800, 300)
    v.show()
    v.set_axes(20, 8, 0.0, 1.0)  # n_samples=8, dt_ns=1.0 -> time range [0, 8)
    v.set_image(img)
    assert v.transform is not None
    t = v.transform

    def mean_luma(time_lo: float, time_hi: float) -> float:
        v.transform = t.with_window(t.trace_lo, t.trace_hi, time_lo, time_hi)
        shot = v.grab_image()
        r = v.image_rect()
        samples = [
            QColor(shot.pixel(r.left() + x, r.top() + r.height() // 2)).value()
            for x in range(5, r.width() - 5, 20)
        ]
        return float(np.mean(samples))

    top_half = mean_luma(0.0, 4.0)  # samples [0, 4) -> image row 0 (white)
    bottom_half = mean_luma(4.0, 8.0)  # samples [4, 8) -> image row 1 (black)

    assert top_half > 200  # reads the white row
    assert bottom_half < 55  # reads the black row


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
    # I6: the old probe was `margin.red() == margin.green() == margin.blue()`,
    # commented "axis gutter is neutral" -- but DEFAULT_COLORMAP is
    # grey_black_high, so *every* radargram pixel already satisfies r==g==b;
    # painting the image straight over both margins (`drawImage(QRectF(r),
    # ...)` -> `drawImage(QRectF(self.rect()), ...)`) still passes this
    # check. Asserting the exact BACKGROUND colour is what actually pins
    # "nothing but background was painted here": real (random) radargram
    # data landing on precisely (250, 250, 250) is not a realistic tie.
    margin = QColor(shot.pixel(5, r.top() + 5))
    assert margin == BACKGROUND


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


@pytest.fixture
def message_log(qgis_app):
    """Captured `QgsMessageLog` messages, for the life of this test only.

    `QgsApplication.messageLog()` is a session-scoped singleton: a
    connection left dangling would keep accumulating every later test's
    messages into this test's own list for the rest of the (also
    session-scoped) `qgis_app` fixture. Disconnected on teardown.
    (Mirrors `tests/qgis/test_plugin_layers.py`'s fixture of the same name.)
    """
    from qgis.core import QgsApplication

    log = QgsApplication.messageLog()
    messages: list[str] = []

    def _on_message(msg: str, tag: str, level: int) -> None:
        messages.append(msg)

    log.messageReceived.connect(_on_message)
    yield messages
    log.messageReceived.disconnect(_on_message)


def test_set_axes_rejects_a_mismatched_distance_along_and_logs_it(make_view, message_log):
    """C1a: `distance_along` of the wrong length used to reach
    `_distance_ticks` unvalidated, raising `ValueError: fp and xp are not
    of the same length` from `np.interp` -- inside `paintEvent`, where an
    escaping exception is the segfault hazard C1 is about (see below).
    `set_axes` now rejects the mismatch up front, applies the rest of the
    axes anyway, and logs instead of storing the bad array.
    """
    v = make_view()
    v.resize(800, 300)
    v.set_axes(200, 128, -4.0, 0.5, distance_along=np.arange(100) / 60.0)
    v.set_image(RadargramImage(_rg()).image)
    v.grab_image()  # must not raise
    assert v.transform is not None  # the rest of the axes were still applied
    assert v._distance is None  # the mismatched array was rejected, not stored
    assert any("distance_along" in m for m in message_log)


def test_set_axes_rejects_a_non_positive_dt_ns_and_logs_it(make_view, message_log):
    """C1c: `dt_ns == 0` is finite (`ViewTransform.__post_init__` checks
    finiteness only, not positivity) and only explodes later, inside
    `source_rect()` (`(time_lo - t0_ns) / dt_ns`) -- unreachable from real
    data today (`parse_header`/`Radargram.__post_init__` both already
    reject `dt_ns <= 0`), but `set_axes` is a public entry point with no
    caller between it and a header value, so it enforces its own contract.
    """
    v = make_view()
    v.resize(800, 300)
    before = v.transform
    v.set_axes(200, 128, 0.0, 0.0)
    assert v.transform is before  # rejected outright; nothing was changed
    v.grab_image()  # must not raise
    assert any("dt_ns" in m for m in message_log)


def test_paint_event_survives_an_empty_trace_axis_with_a_matching_empty_distance_array(make_view):
    """C1b: the empty-trace-axis state defect (a) was fixed to make safe --
    `n_traces == 0` is Task 13's own legal, deliberate empty-axis state.
    A *correctly* length-matched (both zero) `distance_along` passes
    `set_axes`'s C1a length check (0 == 0) and used to still reach
    `np.interp` with an empty `xp`, raising `ValueError: array of sample
    points is empty` from inside `_distance_ticks`, called from
    `paintEvent` -- the task's own named defect (a) was only half closed.

    Calls `_distance_ticks` directly, not only through `grab_image()`:
    `paintEvent`'s own outer `except Exception` (C1's generic mechanism)
    would otherwise also catch a `ValueError` escaping this specific guard,
    making `grab_image()` alone unable to tell "this guard exists" apart
    from "some *other* guard caught it instead" -- confirmed directly by
    mutating this guard away: `grab_image()` alone still did not raise
    (paintEvent's own catch-all covered for it), but calling
    `_distance_ticks` directly did raise, which is the assertion below.
    """
    v = make_view()
    v.resize(400, 200)
    v.set_axes(0, 50, 0.0, 0.5, distance_along=np.array([]))
    assert v.transform is not None
    assert v.transform.n_traces == 0
    assert v._distance_ticks(v.transform) == []  # must not raise ValueError
    v.grab_image()  # must not raise either, end to end


def test_paint_event_survives_an_unexpected_exception_across_two_repaints(view, monkeypatch):
    """C1, the generic mechanism: `paintEvent` must survive *any* exception
    raised while painting, not only the three specific inputs (C1a/b/c)
    rejected earlier at their own source, and specifically survive a
    *second* repaint after the first -- an exception that truly escapes
    `paintEvent` uncaught (through PyQt's C++/Python virtual-method
    boundary) only warns on the first repaint and segfaults the process on
    the next one (confirmed directly, including the exact diagnostic Qt
    prints first: "QPaintDevice: Cannot destroy paint device that is being
    painted"). Forces the failure via monkeypatching rather than hunting
    for another real input, the same reasoning as
    `test_mouse_move_survives_a_broken_pan_transform_instead_of_leaking_to_qt`.

    What this test can and cannot distinguish, measured directly rather
    than assumed (see the task report for the full investigation): removing
    *both* `except Exception` and `finally: painter.end()` together (the
    full pre-C1 shape) reproduces the segfault reliably, on the second
    `grab_image()` call below. Removing only one of the two does not --
    each independently keeps `painter.end()` called before any exception
    can reach that C++ boundary (`finally` runs regardless of which
    exception type escaped the `except`; a locally-scoped `painter` with no
    other reference is destructed, calling `end()` implicitly, the moment
    `paintEvent` returns even with no `finally` at all if `except` already
    caught the exception). So this test cannot tell "both present" apart
    from "either one present"; it can only tell "both present" apart from
    "neither present", which is exactly the shape defect (a) originally
    shipped in and C1 fixed.
    """
    v, rg = view

    def boom(self, p, r, t):
        raise RuntimeError("simulated paint failure")

    monkeypatch.setattr(ProfileView, "_paint_axes", boom)
    v.grab_image()  # first repaint: must not raise
    v.grab_image()  # second repaint: an exception that escaped uncaught would crash here


def test_cursor_is_drawn_at_the_trace(view):
    v, rg = view
    v.set_cursor(100)
    shot = v.grab_image()
    r = v.image_rect()
    # m3: a single exact pixel column with zero tolerance (mutation
    # sensitivity was fine -- the `+ 0.5` removal is killed -- but a pen
    # width or device-pixel-ratio change would break this for no
    # behavioural reason). A +-1px window is just as sensitive to the real
    # mutation and not brittle to a 1px rendering shift.
    x = int(round(r.left() + v.transform.x_of_trace(100.5)))
    found = any(
        QColor(shot.pixel(x + dx, r.top() + y)).red() > 200
        and QColor(shot.pixel(x + dx, r.top() + y)).blue() < 120
        for dx in (-1, 0, 1)
        for y in range(10, r.height() - 10, 7)
    )
    assert found, CURSOR_COLOUR.name()


def test_mouse_move_emits_the_trace_under_the_cursor(view):
    v, rg = view
    got = []
    v.trace_hovered.connect(got.append)
    r = v.image_rect()
    # m2: the old probe was `r.width() // 2` = 348, and `348 / 696` is
    # *exactly* 0.5 in IEEE 754 -- `trace_of_x(348) == 100.0` exactly, one
    # ULP from flipping `trace_index_at` to 99 (confirmed:
    # `trace_index_at(nextafter(348, 0)) == 99`), and coupled to this
    # fixture's specific 800px width for no reason connected to what the
    # test names. `r.width() // 3` = 232 is `1/3` of 696 exactly but lands
    # on 66.666..., nowhere near an integer boundary.
    QTest.mouseMove(v, QPoint(r.left() + r.width() // 3, r.top() + 20))
    assert got and got[-1] == v.transform.trace_index_at(r.width() // 3) == 66


def test_wheel_zooms_about_the_cursor_and_emits_view_changed(view):
    v, rg = view
    changed = []
    v.view_changed.connect(lambda: changed.append(1))
    r = v.image_rect()
    before = v.transform
    anchor_x, anchor_y = r.width() // 2, r.height() // 2
    # m10: the span-halving assertion below is satisfied by `zoomed(factor,
    # 0.0, 0.0)` too (an anchor-ignoring mutation survived) -- it only
    # checks that *some* zoom happened, never that it happened *about the
    # cursor*. The defining property of an anchor-preserving zoom is that
    # the trace under the anchor pixel is the same trace before and after;
    # a zoom that ignores the anchor and always zooms toward the origin
    # moves that trace instead.
    anchor_trace_before = before.trace_of_x(anchor_x)
    v.zoom_at(2.0, anchor_x, anchor_y)
    assert changed and v.transform.trace_hi - v.transform.trace_lo == pytest.approx(100.0)
    assert v.transform.trace_of_x(anchor_x) == pytest.approx(anchor_trace_before)
    v.fit()
    assert (v.transform.trace_lo, v.transform.trace_hi) == (before.trace_lo, before.trace_hi)


def test_wheel_event_zooms_about_the_cursor(view):
    """I1: `wheelEvent` had no positive test at all -- mutating
    `if steps: self.zoom_at(...)` to `if False: ...` passed the whole
    suite. The only test that dispatches a real `QWheelEvent`
    (the degenerate-factor guard test) asserts `not excepthook_calls` and
    `v.transform == before`, both of which are exactly what a do-nothing
    `wheelEvent` also produces -- it cannot distinguish "the guard caught a
    bad input" from "the feature does nothing". This dispatches an
    ordinary, single-notch wheel tick (`angleDelta = (0, 120)`, the
    standard delta) at a known anchor and asserts the resulting window
    against hard-coded numbers, independently derived from
    `ViewTransform.zoomed`'s own documented formula (not by calling
    `zoom_at`/`wheelEvent` themselves to produce the expected value).
    """
    v, rg = view
    r = v.image_rect()
    assert (r.left(), r.top()) == (56, 8)  # the numbers below assume this fixture's exact geometry
    ev = QWheelEvent(
        QPointF(404, 140),
        QPointF(404, 140),
        QPoint(0, 0),
        QPoint(0, 120),  # one standard wheel notch
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(v, ev)
    t = v.transform
    # steps = 120/120.0 = 1.0; factor = 1.25**1.0 = 1.25; anchor (348, 132)
    # local, i.e. widget point (404, 140) with this fixture's margins.
    assert (t.trace_lo, t.trace_hi) == (pytest.approx(20.0), pytest.approx(180.0))
    assert (t.time_lo, t.time_hi) == (pytest.approx(2.4), pytest.approx(53.6))


def test_middle_drag_pans_the_view(view):
    """I2: middle-button pan had no positive test either -- deleting
    `self.transform = self.transform.panned(d.x(), d.y())` from
    `_handle_mouse_move` passed the whole suite, for the same reason as I1:
    the only test dispatching a middle-button drag
    (`test_mouse_move_survives_a_broken_pan_transform_instead_of_leaking_to_qt`)
    monkeypatches `panned` to raise and asserts nothing changed, which also
    holds if `panned` is never called at all.

    First zooms in (fit zoom clamps a pan to nothing, since the window
    already spans the full data extent -- `with_window`'s
    `n_traces - t_span` clamp is `0` there), then drags the middle button
    by a known pixel delta and asserts the resulting window against
    hard-coded numbers, independently derived from `ViewTransform.panned`'s
    own documented formula.
    """
    v, rg = view
    r = v.image_rect()
    v.zoom_at(2.0, r.width() // 2, r.height() // 2)
    assert (v.transform.trace_lo, v.transform.trace_hi) == (
        pytest.approx(50.0),
        pytest.approx(150.0),
    )
    assert (v.transform.time_lo, v.transform.time_hi) == (pytest.approx(12.0), pytest.approx(44.0))
    QTest.mousePress(
        v,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 200, r.top() + 100),
    )
    _send_move_while_pressed(
        v, QPoint(r.left() + 250, r.top() + 120), held_button=Qt.MouseButton.MiddleButton
    )
    t = v.transform
    # panned(dx=+50, dy=+20) on a (trace_lo=50, trace_hi=150, time_lo=12,
    # time_hi=44) window: dt = -50/696*100, ds = -20/264*32.
    assert t.trace_lo == pytest.approx(42.81609195402299)
    assert t.trace_hi == pytest.approx(142.816091954023)
    assert t.time_lo == pytest.approx(9.575757575757576)
    assert t.time_hi == pytest.approx(41.57575757575758)


def test_stuck_pan_is_not_armed_by_a_later_non_middle_release(view):
    """I3: `_pan_last` was only ever cleared by a *middle-button*
    `mouseReleaseEvent`, and `_handle_mouse_move` checked `_pan_last is not
    None` before consulting any button state at all. A middle-press
    (arming panning) followed by an unrelated left click left `_pan_last`
    set after the left release, so the *next* mouse move -- with no
    button held at all -- was read as an in-progress pan and moved the
    view. Measured by the reviewer: middle-press, left-press, left-release,
    one button-less move -- panned 14.4 traces on a view zoomed to a
    100-trace window.

    Fixed by checking `event.buttons() & MiddleButton` in the move handler
    itself (authoritative regardless of which release path got there,
    including one this widget cannot see coming, like losing focus
    mid-drag), rather than trying to clear `_pan_last` from every place
    that might need to.
    """
    v, rg = view
    r = v.image_rect()
    v.zoom_at(2.0, r.width() // 2, r.height() // 2)  # give panning room to move
    before = v.transform
    QTest.mousePress(
        v,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 200, r.top() + 100),
    )
    assert v._pan_last is not None
    QTest.mousePress(
        v,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 200, r.top() + 100),
    )
    QTest.mouseRelease(
        v,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 200, r.top() + 100),
    )
    assert v._pan_last is not None  # only a *middle* release clears it directly -- still armed
    # A plain, button-less move must not pan the view. `QTest.mouseMove`
    # cannot be used for this step: the middle button was never released
    # (that omission is the point -- see the docstring), so Qt's own
    # tracked button state still shows it held, and a plain
    # `QTest.mouseMove` would silently not be delivered at all for the
    # same reason `_send_move_while_pressed` exists (a `QTest.mouseMove`
    # while any button is logically down is not reliably delivered in this
    # environment) -- which would make this assertion pass for the wrong
    # reason (the handler never ran) rather than because the guard
    # actually held. Sending the event directly with `buttons=NoButton`
    # bypasses that and is also the more faithful simulation of what this
    # finding is really about: a move that arrives with no button
    # information Qt's own release bookkeeping ever confirmed.
    _send_move_while_pressed(
        v, QPoint(r.left() + 400, r.top() + 100), held_button=Qt.MouseButton.NoButton
    )
    assert v.transform == before
    assert v._pan_last is None  # the move itself recognises the stale arm and clears it


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


def test_drag_right_to_left_still_emits_a_normalised_range(view):
    """I9 (live behaviour gap, not just coverage): dragging backwards --
    from a higher trace to a lower one -- was untested end to end. Without
    `set_selection`'s `min(a, b), max(a, b)` normalisation, dragging from
    trace 86 back to trace 28 would store `(86, 28)` as-is: `_paint_selection`
    would `fillRect` a negative width (drawing nothing) and
    `range_selected` would hand a downstream consumer a reversed range.
    Same trace range as `test_drag_selects_a_trace_range`, dragged in the
    opposite direction, and it must emit the identical, normalised result.
    """
    v, rg = view
    sel = []
    v.range_selected.connect(lambda a, b: sel.append((a, b)))
    r = v.image_rect()
    QTest.mousePress(
        v,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 300, r.top() + 50),
    )
    _send_move_while_pressed(v, QPoint(r.left() + 100, r.top() + 50))
    QTest.mouseRelease(
        v,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 100, r.top() + 50),
    )
    assert sel == [(28, 86)]  # normalised the same as the forward drag, not (86, 28)


def test_set_selection_normalises_reversed_bounds(view):
    v, rg = view
    v.set_selection(86, 28)
    assert v._selection == (28, 86)


def test_selection_bounds_use_the_trace_after_b_for_the_right_edge(view):
    """I9: `_paint_selection`'s right edge is `x_of_trace(b + 1)`, not
    `x_of_trace(b)` -- the selection is inclusive of trace `b`, so its
    right edge is the *start* of the next trace. `_selection_bounds`
    makes this a plain value a test can assert on directly, instead of
    only being provable by locating a 1-trace-wide sliver of a dashed
    line in a rendered image.
    """
    v, rg = view
    v.set_selection(20, 40)
    x0, x1 = v._selection_bounds(v.transform)
    assert x0 == pytest.approx(v.transform.x_of_trace(20))
    assert x1 == pytest.approx(v.transform.x_of_trace(41))  # b + 1, not b
    assert x1 != pytest.approx(v.transform.x_of_trace(40))  # what the mutation would give


def test_selection_is_actually_rendered(view):
    """Lightweight consumption check alongside the bounds unit test above:
    proves `_paint_selection` actually uses `_selection_bounds` to draw
    something, rather than the bounds being correct but unused (or the
    whole render call removed)."""
    v, rg = view
    v.clear_selection()
    cleared = v.grab_image()
    v.set_selection(20, 40)
    selected = v.grab_image()
    r = v.image_rect()
    x0 = int(round(r.left() + v.transform.x_of_trace(20))) + 2
    assert cleared.pixel(x0, r.top() + 30) != selected.pixel(x0, r.top() + 30)


def test_pick_positions_use_the_trace_centre_and_the_time(view):
    """I9: `_pick_positions`' computation, in isolation. Mirrors
    `_selection_bounds`'s reasoning above."""
    v, rg = view
    v.set_picks([(100, 10.0)])
    [(x, y)] = v._pick_positions(v.transform)
    assert x == pytest.approx(v.transform.x_of_trace(100.5))
    assert y == pytest.approx(v.transform.y_of_time(10.0))


def test_set_picks_renders_a_marker_at_the_correct_position(view):
    """I9: `set_picks()` was never called by any test in the suite, so
    `_paint_picks` never ran with a non-empty list -- both `x = r.left()`
    and `y = r.top()` pinning mutations (every pick drawn in the top-left
    corner) survived. Renders one pick and searches a small neighbourhood
    of its *expected*, independently-computed position for `PICK_COLOUR`,
    and separately confirms nothing pick-coloured sits in the corner a
    pinning mutation would draw at instead.
    """
    v, rg = view
    v.set_picks([(100, 10.0)])
    shot = v.grab_image()
    r = v.image_rect()
    x = int(round(r.left() + v.transform.x_of_trace(100.5)))
    y = int(round(r.top() + v.transform.y_of_time(10.0)))

    def is_pick_coloured(px: int, py: int) -> bool:
        c = QColor(shot.pixel(px, py))
        return c.red() > 180 and c.green() < 120 and c.blue() < 80

    found = any(is_pick_coloured(x + dx, y - 4 + dy) for dx in range(-4, 5) for dy in range(-4, 5))
    assert found, PICK_COLOUR.name()
    corner = any(
        is_pick_coloured(r.left() + dx, r.top() + dy) for dx in range(5) for dy in range(5)
    )
    assert not corner  # a "pinned to r.left()/r.top()" mutation would draw here instead


def test_right_button_release_does_not_end_or_commit_a_left_drag(view):
    """I4: `mouseReleaseEvent`'s generic branch used to run for *any*
    released button, not just the left one `mousePressEvent` arms
    `_press`/`_dragging` for. Measured by the reviewer: left-press at
    x=100, drag to x=300, then press-and-release the *right* button --
    `range_selected` fired `(28, 86)` from a button that never started the
    selection. A right-button click landing mid-drag must leave the drag
    alone: no emission, and the drag must still be completable afterwards
    by the left button that actually started it.
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
    assert v._dragging  # the drag is genuinely in progress before the right click lands
    QTest.mousePress(
        v,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 300, r.top() + 50),
    )
    QTest.mouseRelease(
        v,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 300, r.top() + 50),
    )
    assert sel == []  # not committed by the right button
    assert v._press is not None  # the left-button drag is still in progress
    QTest.mouseRelease(
        v,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(r.left() + 300, r.top() + 50),
    )
    assert sel == [(28, 86)]  # the left button that actually started it still commits it


def test_depth_axis_uses_the_velocity_model(view):
    """I7: the brief's own probe here, corrected for the and/or precedence
    bug (see the note kept below), still only checked `labels[0] == "0"` --
    which the reviewer showed both the real and a velocity-bypassed
    (`depths = times` directly) computation satisfy, since both axes
    happen to include a "0" tick with this fixture's numbers. That leaves
    the whole test proving only that setting a velocity produces *some*
    labels, not that the model was actually used.

    `rg` here (`_rg()`) is t0_ns=-4.0, n_samples=128, dt_ns=0.5, so time
    runs [-4.0, 60.0]. With `VelocityModel.constant(0.1)`,
    depth = 0.05 * time_ns, giving depths [-0.2, 3.0] ->
    nice_ticks step 1.0 -> ticks 0,1,2,3. With the model bypassed (depths
    == times directly), nice_ticks(-4, 60) steps at 20 -> ticks 0,20,40,60
    -- a completely different list, not just a different `labels[0]`.
    Asserting the exact label list is independent of `nice_ticks` itself
    (an already-tested pure function; the property under test is that
    `_depth_ticks` feeds it *depths*, not raw times) and distinguishes the
    two cases completely, not just at one index.
    """
    v, rg = view
    v.set_velocity(VelocityModel.constant(0.1))
    labels = v.depth_tick_labels()
    # NOTE: the brief's own probe here was
    #   `labels and labels[0].startswith("-") or labels[0] == "0"`
    # `and`/`or` precedence makes this `(labels and labels[0].startswith("-"))
    # or (labels[0] == "0")` -- if `labels` were ever empty, the left disjunct
    # is `[]` (falsy) and evaluation falls through to `labels[0] == "0"`,
    # indexing an empty list: `IndexError`, not a clean assertion failure.
    assert labels == ["0", "1", "2", "3"]

    # tick *positions* are untested by the label list alone (`out.append((...,
    # 0.0))` also survives a labels-only check): each depth tick's y must be
    # the transform's own y_of_time at that depth's interpolated time, not a
    # pinned constant. Values below computed independently (np.linspace/
    # depth_at/y_of_time), not by calling `_depth_ticks` itself.
    ys = [y for _, y in v._depth_ticks(v.transform)]
    assert ys == [pytest.approx(expected) for expected in (16.5, 99.0, 181.5, 264.0)]


def test_time_ticks_use_the_actual_time_range_and_positions(view):
    """I8: `_time_ticks` (factored out of `_paint_axes`, mirroring
    `_depth_ticks`/`_distance_ticks`) had no dedicated return value to
    assert on before this refactor -- two of the review's seven `_paint_axes`
    survivors are specifically `nice_ticks(t.time_lo, t.time_hi) ->
    nice_ticks(0.0, 1.0)` and `y = r.top() + y_of_time(tick) -> y = r.top()`.
    Hard-coded values, independently derived (see the task report): this
    fixture's time range at fit zoom happens to share numbers with the
    depth-tick test above (a fixture coincidence, not a reason to skip
    asserting them here -- this method has its own mutations neither of the
    other two tick methods exercise).
    """
    v, rg = view
    ticks = v._time_ticks(v.transform)
    assert [label for label, _ in ticks] == ["0", "20", "40", "60"]
    ys = [y for _, y in ticks]
    assert ys == [pytest.approx(expected) for expected in (16.5, 99.0, 181.5, 264.0)]


def test_time_ticks_are_actually_rendered_in_the_left_margin(view):
    """Consumption check alongside the value test above: `for tick in
    self._time_ticks(t): ...` -> `for tick in []` would leave
    `_time_ticks` itself correct but never drawn."""
    v, rg = view
    shot = v.grab_image()
    r = v.image_rect()
    tick_y = int(round(r.top() + 99.0))  # the "20" tick
    between_ticks_y = tick_y + 20  # no tick mark expected here
    assert QColor(shot.pixel(r.left() - 2, tick_y)).red() < 150
    assert QColor(shot.pixel(r.left() - 2, between_ticks_y)).red() > 200


def test_distance_ticks_are_actually_rendered_at_the_bottom(view):
    v, rg = view
    shot = v.grab_image()
    r = v.image_rect()
    ticks = v._distance_ticks(v.transform)
    assert ticks  # non-empty: distance_along was provided by the fixture
    _, x = ticks[1]  # skip the first, which can sit right at the left edge
    # Qt's non-antialiased line rasteriser maps a float pen position by
    # truncation, not rounding (measured directly: a tick at local x=208.8
    # draws its full-strength column at pixel 264, not round(264.8) = 265,
    # which only catches a 1px antialiasing bleed at the line's very top).
    tick_x = int(r.left() + x)
    assert QColor(shot.pixel(tick_x, r.bottom() + 2)).red() < 150


def test_distance_ticks_fall_back_to_trace_ticks_without_distance_along(make_view):
    """I8: `_distance_ticks`'s no-distance branch (`return []`) survived
    all 18 tests because the `view` fixture always supplies
    `distance_along` -- nothing exercised this branch at all."""
    v = make_view()
    v.resize(800, 300)
    v.set_axes(200, 128, -4.0, 0.5)  # no distance_along
    ticks = v._distance_ticks(v.transform)
    assert ticks  # "return []" would make this empty
    assert v._distance_unit_label() == "trace"


def test_distance_unit_label_reflects_whether_distance_is_set(view):
    """I8: `unit = "m" if self._distance is not None else "trace"` was a
    local variable in `_paint_axes`, invisible to any test except by
    reading rendered text pixel-by-pixel. Factored into
    `_distance_unit_label()` for the same reason as `_time_ticks`;
    `unit = ... "trace"` (pinned, ignoring `self._distance`) survived all
    18 tests."""
    v, rg = view
    assert v._distance_unit_label() == "m"  # fixture provides distance_along
    v.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns)  # no distance_along this time
    assert v._distance_unit_label() == "trace"


def test_direction_arrow_reflects_set_direction(view):
    """I8: `arrow = "→" if self._direction == 1 else "←"` pinned to "→",
    and `set_direction()` becoming a no-op (`self._direction = direction`
    -> `= 1`), both survived all 18 tests -- Task 15 wires
    `set_direction(int(line.placement.direction))`, so a reversed line
    would render with the wrong arrow and nothing would notice."""
    v, rg = view
    assert v._direction_arrow() == "→"
    v.set_direction(-1)
    assert v._direction_arrow() == "←"


def test_set_axes_and_fit_emit_view_changed(make_view):
    """m9: `set_axes`/`fit` emitting `view_changed` was untested (both
    removals survive); only `zoom_at`'s emission is covered, via
    `test_wheel_zooms_about_the_cursor_and_emits_view_changed`."""
    v = make_view()
    v.resize(800, 300)
    changed = []
    v.view_changed.connect(lambda: changed.append(1))
    v.set_axes(200, 128, -4.0, 0.5)
    assert len(changed) == 1
    v.fit()
    assert len(changed) == 2


def test_one_to_one_sets_a_trace_per_pixel_column_and_emits_view_changed(make_view):
    """m9: `one_to_one()` was never called by any test at all.

    Needs `n_traces > width` (696 for this fixture's 800px resize) -- the
    `view` fixture's 200-trace radargram would have `with_window`'s own
    `n_traces - t_span` clamp cap the requested 696-trace span back down to
    200 (there simply aren't 696 traces to show one-per-pixel), which would
    make a `trace_hi - trace_lo == width` assertion pass at 200 == 200 by
    coincidence of clamping, not because one_to_one asked for `width`.
    """
    v = make_view()
    v.resize(800, 300)
    v.set_axes(1000, 128, -4.0, 0.5)
    changed = []
    v.view_changed.connect(lambda: changed.append(1))
    v.one_to_one()
    assert changed
    assert v.transform.trace_hi - v.transform.trace_lo == pytest.approx(v.transform.width)
    assert v.transform.trace_lo == pytest.approx(0.0)  # anchored at the window's left


def test_clear_resets_state_and_paints_safely(view):
    """m9: `clear()` was never called by any test at all."""
    v, rg = view
    v.set_cursor(5)
    v.set_selection(1, 2)
    v.set_picks([(1, 2.0)])
    v.clear()
    assert v.transform is None
    assert v._cursor == -1
    assert v._selection == (-1, -1)
    assert v._picks == []
    v.grab_image()  # must not raise


def test_resize_after_axes_are_set_updates_the_transform(make_view):
    """I5: mutating `resizeEvent`'s `self.transform =
    self.transform.resized(...)` to `pass` survived all 18 tests -- every
    existing fixture calls `resize()` *before* `set_axes`, so
    `self.transform` is still `None` at the only resize that ever happens
    in the whole suite, and the `if self.transform is not None:` branch
    never runs at all.

    Not cosmetic: a stale `transform.width` after a real resize (docking
    the view, then widening the window) scales every pointer x by the
    wrong factor. Measured by the reviewer: widening 800px -> 1000px
    (`image_rect().width()` 696 -> 896) makes a hover at local x=800 report
    trace 199 (`800/696*200`, clamped) using the stale width, instead of
    the correct 178 (`800/896*200`) the new width gives.
    """
    v = make_view()
    v.resize(800, 300)
    v.show()
    v.set_axes(200, 128, -4.0, 0.5)  # transform now set, unlike every other fixture's resize
    assert v.transform.width == 696
    v.resize(1000, 300)
    QApplication.processEvents()  # a resize on an unshown/unexposed widget can otherwise be queued
    assert v.transform.width == 896  # updated, not left at the stale 696
    assert (
        v.transform.trace_index_at(800) == 178
    )  # 800/896*200, not the stale 800/696*200 (229.9, clamped to 199)


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
