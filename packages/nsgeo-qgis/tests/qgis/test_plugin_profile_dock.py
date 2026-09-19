from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.render import PercentileClip
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.profile_dock import ProfileDock, velocity_source
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QStyle

GRID = Grid(
    "A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.08)
)


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=240)
    line = Line.open(p, GridPlacement("A", "y", 0.0, 0.0, -1, "FILE__001"))
    session.add_lines([line])
    key = session.keys()[0]
    session.open_line(key)
    yield session, dock, key, line
    # A parentless ProfileDock is a top-level widget, the same hazard
    # test_plugin_profile_view.py's `make_view` fixture documents for a
    # parentless, shown ProfileView: torn down explicitly (hide() then
    # deleteLater()) rather than left for Python's GC to race Qt's own
    # widget teardown at interpreter shutdown. In production the dock is
    # parented to the QGIS main window (see plugin.py), which is what
    # actually controls destruction order there.
    dock.hide()
    dock.deleteLater()


@pytest.fixture
def bare(qgis_app, tmp_path):
    """A `ProfileDock` with no site open yet, for tests that need to build
    their own line (a time-triggered one) instead of the `opened` fixture's
    placed one. Torn down the same way `opened` is, for the same reason.
    """
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    yield session, dock, tmp_path
    dock.hide()
    dock.deleteLater()


def test_opening_shows_axes_and_loading_before_samples_arrive(opened):
    """C2: the three central M5 observables (the image reaching the
    widget, the depth axis existing, t0 coming from the header) had no
    assertion that would fail if any of them broke -- `dock.image is not
    None` proves the dock *built* an image, nothing about whether the
    widget the user is looking at ever received it. Each line below is
    paired with the one mutant a review confirmed it kills: dropping
    `view.set_image(...)` entirely, dropping `view.set_velocity(...)`
    entirely, and replacing `header.position_ns` with `0.0` all used to
    leave the whole file green.
    """
    session, dock, key, line = opened
    assert "FILE__001" in dock.windowTitle()
    assert f"{line.n_traces} traces" in dock.windowTitle()
    assert dock.view.transform is not None and dock.view.transform.n_traces == 240
    # before set_profiles: header-derived axes, velocity and distance must
    # already be on the *view*, not just computed and discarded.
    assert dock.view.transform.n_samples == line.header.n_samples
    assert dock.view.transform.t0_ns == pytest.approx(line.header.position_ns)
    assert dock.view._velocity is not None and dock.view.depth_tick_labels()
    assert dock.view._distance is not None  # metres, not a trace-index fallback
    assert dock.image is None
    session.set_profiles(key, line.load())
    # after set_profiles: the radargram must reach the widget itself, not
    # just get built and held on the dock.
    assert dock.image is not None
    assert dock.view.transform.n_samples == 512
    assert dock.view._image is not None


def test_display_gain_rerenders_without_touching_the_stack(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    before = dock.image
    dock.percentile_slider.setValue(950)
    assert dock.percentile == pytest.approx(95.0)
    assert dock.image is not before and dock.image.rg is before.rg
    assert "95.0" in dock.percentile_label.text()
    dock.colormap_combo.setCurrentText("seismic")
    assert dock.image.colormap_name == "seismic"
    assert len(session.stack_for(key)) == 0


def test_percentile_slider_direction_is_gain_intuitive(opened):
    """M5 follow-up (Finding 1): dragging the display-gain slider toward
    its right-hand end must produce a LOWER percentile -- a lower
    percentile clips more of the signal, saturating more samples to
    black/white, which is "more gained" in the user's own words. The
    slider's `value()`/`setValue()` are unaffected by
    `setInvertedAppearance` (Qt's own contract), so this cannot be pinned
    by calling `setValue()` with numbers taken from the implementation --
    that would only prove `percentile == value / 10.0`, true before this
    fix too. Instead this asks Qt's own `QStyle.sliderValueFromPosition`
    -- the same function a real mouse drag resolves a handle's pixel
    position through -- what value results at each physical end of the
    widget, independently of this file's own percentile arithmetic.
    """
    _, dock, _, _ = opened
    slider = dock.percentile_slider
    span = 200  # arbitrary groove length in pixels; only 0 vs. span matters
    value_at_right_end = QStyle.sliderValueFromPosition(
        slider.minimum(), slider.maximum(), span, span, slider.invertedAppearance()
    )
    value_at_left_end = QStyle.sliderValueFromPosition(
        slider.minimum(), slider.maximum(), 0, span, slider.invertedAppearance()
    )

    slider.setValue(value_at_right_end)
    percentile_at_right_end = dock.percentile
    slider.setValue(value_at_left_end)
    percentile_at_left_end = dock.percentile

    assert percentile_at_right_end < percentile_at_left_end


def test_percentile_slider_range_reaches_fifty_percent(opened):
    """M5 follow-up (Finding 1): the old floor of 90.0 % was arbitrary and
    the user wants to go lower. `PercentileClip` only requires
    `0 < percentile <= 100`, so 50.0 is confirmed against the actual
    validator here rather than assumed.
    """
    _, dock, _, _ = opened
    slider = dock.percentile_slider

    PercentileClip(percentile=50.0)  # does not raise -- confirms the contract

    assert slider.minimum() == 500
    slider.setValue(slider.minimum())
    assert dock.percentile == pytest.approx(50.0)


def test_percentile_label_reports_the_true_percentile_at_both_ends(opened):
    """M5 follow-up (Finding 1): the label must keep showing the honest
    percentile the user reads, at both the widened floor and the
    ceiling -- never a made-up "gain" number.
    """
    _, dock, _, _ = opened
    slider = dock.percentile_slider

    slider.setValue(slider.minimum())
    assert dock.percentile == pytest.approx(50.0)
    assert "50.0" in dock.percentile_label.text()

    slider.setValue(slider.maximum())
    assert dock.percentile == pytest.approx(100.0)
    assert "100.0" in dock.percentile_label.text()


def test_stack_changes_rerender_and_axes_follow_the_result(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("time_zero", mode="sample", sample=40))
    assert dock.view.transform.n_samples == 472
    assert dock.image.rg.n_samples == 472


def test_step_errors_surface_as_a_signal_not_an_exception(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    errors = []
    dock.error.connect(errors.append)
    session.append_step(key, build_step("bandpass", low_mhz=100.0, high_mhz=90_000.0))
    assert errors and "Nyquist" in errors[0]
    assert dock.image is not None  # previous image kept


def test_velocity_label_names_its_source(opened):
    session, dock, key, line = opened
    assert velocity_source(session, key) == "Grid A"
    assert "0.080" in dock.velocity_label.text() and "Grid A" in dock.velocity_label.text()
    session.set_line_velocity(key, VelocityModel.constant(0.095))
    assert velocity_source(session, key) == "line override"
    assert "0.095" in dock.velocity_label.text()


def test_velocity_label_falls_back_to_the_header_dielectric(opened):
    """The third tier of `resolve_velocity` (line override, then grid, then
    the header's dielectric) is not exercised by the brief's own test above
    at all -- both its cases stop at "grid" or "line override". Removes
    the grid's velocity model (the header written by `synthetic_dzt` fixes
    `rhf_epsr` at 14.0, an independently known literal, not one computed
    from `velocity_source`/`resolve_velocity` themselves) and checks both
    the label's source name and the resolved number -- 0.299792458 /
    sqrt(14) =~ 0.080, computed independently of `VelocityModel.from_dielectric`.
    """
    session, dock, key, line = opened
    grid = session.grid_for_line(line)
    session.replace_grid(dataclasses.replace(grid, velocity=None))
    assert velocity_source(session, key) == "header ε 14"
    assert "header ε 14" in dock.velocity_label.text()
    assert "Grid A" not in dock.velocity_label.text()
    assert "0.080" in dock.velocity_label.text()


def test_rerender_with_the_same_shape_keeps_the_current_zoom(opened):
    """`_render` restores the *previous* transform after `set_axes` resets
    it to a fresh fit, but only when the radargram's shape did not change
    -- otherwise a display-gain change or an unrelated stack event (a
    channel switch on another line, e.g.) would silently discard whatever
    the user had zoomed or panned to. `dewow` never changes the sample or
    trace count (unlike `time_zero`, which the test above already covers),
    so this is the "shape unchanged" side of that same mechanism.
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    r = dock.view.image_rect()
    dock.view.zoom_at(2.0, r.width() / 2, r.height() / 2)
    zoomed = dock.view.transform
    assert zoomed.trace_hi - zoomed.trace_lo < 240  # sanity: this really is zoomed in
    session.append_step(key, build_step("dewow", window_ns=4.0))
    assert dock.view.transform is zoomed  # the exact same window, not a fresh fit


def test_cursor_and_selection_follow_the_session_and_vice_versa(opened):
    """I5: the brief's own test checked both directions for the cursor
    (session -> view via `set_trace`, view -> session via
    `trace_hovered.emit`) but only one direction for the selection
    (view -> session via `range_selected.emit`) -- deleting
    `self.view.set_selection(a, b)` from `_on_selection_changed` still
    passed. Added the missing session -> view direction, with *different*
    bounds than the view -> session step above: reusing (5, 9) would make
    `session.set_selection`'s own no-op-on-unchanged-value guard skip the
    emit entirely (the selection would already be (5, 9) from the previous
    line), which would pass vacuously regardless of whether the round trip
    actually ran.
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.set_trace(key, 12)
    assert dock.view._cursor == 12
    dock.view.trace_hovered.emit(30)
    assert session.current_trace == 30
    dock.view.range_selected.emit(5, 9)
    assert session.selection == (5, 9)
    session.set_selection(key, 40, 45)
    assert dock.view._selection == (40, 45)


def test_a_plain_click_on_the_view_clears_the_session_selection(opened):
    """The author's walkthrough (a FAILED check): clearing the QGIS map
    selection did not clear the profile's own range selection, because
    nothing in the UI called `SiteSession.clear_selection()`.
    `ProfileView.selection_cleared` -- a plain click, no drag -- closes
    that gap."""
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.set_selection(key, 5, 9)
    assert session.selection == (5, 9)  # sanity: really set

    dock.view.selection_cleared.emit()

    assert session.selection == (-1, -1)


def test_channel_combo_hidden_for_single_channel_files(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    assert dock.channel_combo.isHidden()


def test_closing_the_site_clears_the_view(opened):
    """I5: the brief's own test never loaded samples before closing the
    site, so `dock.image is None` was satisfied by an image that had never
    been created in the first place -- deleting `self.image = None` from
    `_clear_view_only` still passed. Loading samples first makes the
    assertion prove something.
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    assert dock.image is not None  # sanity: there is something to clear
    session.close_site()
    assert dock.view.transform is None and dock.image is None


def test_time_triggered_line_shows_a_trace_axis_instead_of_raising(bare):
    """`Line.distance_along()` raises `ValueError` for a time-triggered
    acquisition (`traces_per_metre <= 0`) -- `SurveyDock`'s tree marks such
    a line "unplaced" rather than omit it or crash (see
    `test_time_triggered_lines_appear_in_the_tree_marked_not_omitted` in
    `test_plugin_survey_dock.py`); the profile view has the same hazard the
    other way around, since `_on_line_opened`/`_render` both feed
    `distance_along()`'s result straight to `ProfileView.set_axes` as its
    bottom-axis distance array. `_on_line_opened` is a slot connected to
    `session.line_opened` -- an exception escaping it here would just be
    swallowed by PyQt (see the module docstring), leaving no axes shown at
    all and no visible error. This proves the fallback: axes still appear,
    labelled by trace index, with the line successfully open.
    """
    session, dock, tmp_path = bare
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__TIME.DZT", traces_per_metre=0.0)
    line = Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__TIME"))
    session.add_lines([line])
    key = session.keys()[0]
    session.open_line(key)  # must not raise, and must not silently no-op either
    assert "FILE__TIME" in dock.windowTitle()
    assert dock.view.transform is not None and dock.view.transform.n_traces == line.n_traces
    assert dock.view._distance is None


def test_switching_lines_does_not_inherit_the_previous_lines_window(opened):
    """`_render`'s "keep the current pan/zoom across a re-render" mechanism
    (see `test_rerender_with_the_same_shape_keeps_the_current_zoom` above)
    is gated on *two* conditions ANDed together: the old transform's
    `n_traces` matches the new radargram's, AND its `n_samples` does too.
    Every other test in this file changes shape (if at all) only via
    `time_zero`, which crops samples but never traces -- so mutating the
    `n_traces` half of that gate to an unconditional `True` survives the
    whole suite, because the `n_samples` half already blocks the restore
    by itself whenever a *sample* mismatch is what's actually varying.

    Isolates the `n_traces` half by opening a second line with the *same*
    sample count (`synthetic_dzt` always writes 512) but a different trace
    count. Without that guard, the second line's view would incorrectly
    inherit the first line's stale, differently-scaled trace window
    instead of a fresh fit.
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    assert dock.view.transform.n_traces == 240
    p2 = synthetic_dzt(session.root / "raw", "FILE__002.DZT", n_traces=300)
    line2 = Line.open(p2, GridPlacement("A", "y", 0.5, 0.0, 1, "FILE__002"))
    session.add_lines([line2])
    key2 = next(k for k in session.keys() if k != key)  # noqa: SIM118 -- SiteSession.keys(), not a dict
    session.set_profiles(key2, line2.load())
    session.open_line(key2)
    assert dock.view.transform.n_traces == 300  # not the first line's stale 240


def test_stack_change_on_a_different_line_is_ignored(opened):
    """`session.stack_changed` is emitted for *whichever* line's stack was
    touched, not only the currently open one -- unlike `trace_changed`/
    `selection_changed`, which `SiteSession.set_trace`/`set_selection`
    themselves already gate on the current key before ever emitting.
    `_on_stack_changed`'s own `key != self._key` guard is what stops an
    unrelated line's edit from re-rendering the one actually on screen;
    removing it survives the rest of the suite, since every other stack
    mutation here happens on the line that is already open.

    `_render()` always builds a *new* `RadargramImage` object
    (`with_radargram` never returns the same instance), so an unwanted
    re-render is observable even though the re-rendered data is identical:
    `dock.image` changing identity is proof something ran that should not
    have.
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    before = dock.image
    p2 = synthetic_dzt(session.root / "raw", "FILE__002.DZT", n_traces=240)
    line2 = Line.open(p2, GridPlacement("A", "y", 0.5, 0.0, 1, "FILE__002"))
    session.add_lines([line2])
    key2 = next(k for k in session.keys() if k != key)  # noqa: SIM118 -- SiteSession.keys(), not a dict
    session.set_profiles(key2, line2.load())
    session.append_step(key2, build_step("dewow", window_ns=4.0))
    assert dock.image is before  # the open line's own view must not react


def test_line_loaded_for_a_different_line_is_ignored(opened):
    """The same reasoning as the stack-change test above, but for
    `session.line_loaded`: a background loader can finish loading a line
    that is not the one currently open (pre-fetching an adjacent line,
    e.g.), and `_on_line_loaded`'s `key != self._key` guard is what stops
    that from re-rendering the view showing a different line.
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    before = dock.image
    p2 = synthetic_dzt(session.root / "raw", "FILE__002.DZT", n_traces=240)
    line2 = Line.open(p2, GridPlacement("A", "y", 0.5, 0.0, 1, "FILE__002"))
    session.add_lines([line2])
    key2 = next(k for k in session.keys() if k != key)  # noqa: SIM118 -- SiteSession.keys(), not a dict
    session.set_profiles(key2, line2.load())  # a different, unopened line finishes loading
    assert dock.image is before  # key's own view must not react to key2's load


def test_hover_with_no_line_open_is_a_silent_no_op(bare, message_log):
    """`_hovered` is a slot on `ProfileView.trace_hovered`; with no line
    open, `self._key` is `None`. Removing its `if self._key is None: return`
    guard does not crash even so (`session.set_trace(None, ...)` fails with
    `KeyError` from inside `_hovered`'s own broad `except Exception` --
    session's own `if key != self._current_key: return` guard happens to
    let a `None`/`None` comparison straight through instead of catching
    it), so nothing raises either way and the test suite's other checks
    cannot tell the guard apart from "the fallback exception handler saved
    it anyway". The one thing that *does* differ is whether anything gets
    logged at all: the guard returns silently; its absence logs a warning.
    """
    session, dock, tmp_path = bare
    dock.view.trace_hovered.emit(7)  # no line open: must be a true no-op
    assert not message_log


def test_set_difference_index_shows_what_a_step_actually_removed(opened):
    """`set_difference_index`/`current_radargram`'s difference branch has no
    test at all otherwise -- Task 19 is what will give it a UI, but the
    method and the branch already exist and ship in this task. Mutating
    `if self._difference_index >= 0: return stack.difference(...)` to
    `if False: ...` (always falling through to `stack.result()`) survives
    the whole suite: nothing else ever sets a difference index. Checks the
    actual pixel *data*, not just the label text (the label is set from
    `self._difference_index` directly in `_render`, independently of
    whether `current_radargram()` returned the right radargram, so it
    cannot by itself prove the data is the difference).
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow", window_ns=4.0))
    stack = session.stack_for(key)
    before_data = stack.source.data
    after_data = stack.intermediate(0).data
    expected_diff = before_data - after_data

    dock.set_difference_index(0)
    assert dock.difference_label.text() == "Difference: dewow"
    np.testing.assert_array_equal(dock.image.rg.data, expected_diff)

    dock.set_difference_index(-1)
    assert dock.difference_label.text() == ""
    np.testing.assert_array_equal(dock.image.rg.data, after_data)


def test_switching_lines_clears_the_cursor_and_selection(opened):
    """C1: `SiteSession.open_line` resets `_current_trace`/`_selection` to
    their cleared sentinels but emits neither `trace_changed` nor
    `selection_changed` for that reset -- only `line_opened` -- and
    `ProfileView.set_axes` (called from `_open` either way) touches
    neither `_cursor` nor `_selection`. Left unfixed, a review measured
    this directly on the real M4 site (a 608 -> 666 trace switch): the
    view kept painting an orange cursor and a blue selection band from the
    *previous* line while the session already reported `-1`/`(-1, -1)` --
    the widget holding state the session had already discarded, which is
    exactly what routing all state through `SiteSession` exists to
    prevent.
    """
    session, dock, key, line = opened
    session.set_trace(key, 120)
    dock.view.range_selected.emit(5, 9)
    assert dock.view._cursor == 120 and dock.view._selection == (5, 9)  # sanity: really set
    p2 = synthetic_dzt(session.root / "raw", "FILE__002.DZT", n_traces=300)
    line2 = Line.open(p2, GridPlacement("A", "y", 0.5, 0.0, 1, "FILE__002"))
    session.add_lines([line2])
    key2 = next(k for k in session.keys() if k != key)  # noqa: SIM118 -- SiteSession.keys(), not a dict
    session.open_line(key2)
    assert dock.view._cursor == -1
    assert dock.view._selection == (-1, -1)


def test_fit_button_restores_the_full_extent_after_a_zoom(opened):
    """I2: `fit_button.clicked` is wired straight to `ProfileView.fit`, but
    nothing in the suite ever clicked it -- deleting the `connect()` call
    survived. Zooms in first so `fit_button.click()` has something to
    visibly undo.
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    assert dock.view.transform.trace_hi - dock.view.transform.trace_lo < 240  # really zoomed in
    dock.fit_button.click()
    assert dock.view.transform.trace_lo == pytest.approx(0.0)
    assert dock.view.transform.trace_hi == pytest.approx(240.0)


def test_one_to_one_button_sets_a_trace_per_pixel_window(opened):
    """I2: same gap as the fit button, for `one_to_one_button`. A line
    narrower than the view (the `opened` fixture's 240 traces, in a
    ~800px-wide image area) would make one-to-one indistinguishable from
    fit -- `with_window` clamps the requested one-trace-per-pixel span
    back down to `n_traces` either way (this is the real M5 behaviour: the
    review noted "1:1" looks like a no-op on these lines). Opens a second,
    much wider line so the two buttons' effects are actually distinguishable.
    """
    session, dock, key, line = opened
    p2 = synthetic_dzt(session.root / "raw", "FILE__WIDE.DZT", n_traces=2000)
    wide = Line.open(p2, GridPlacement("A", "y", 0.5, 0.0, 1, "FILE__WIDE"))
    session.add_lines([wide])
    key2 = next(k for k in session.keys() if k != key)  # noqa: SIM118 -- SiteSession.keys(), not a dict
    session.open_line(key2)
    dock.one_to_one_button.click()
    t = dock.view.transform
    assert t.trace_hi - t.trace_lo == pytest.approx(t.width)
    assert t.trace_lo == pytest.approx(0.0)


def test_a_preview_starting_does_not_shift_the_toolbar_buttons(qgis_app, tmp_path):
    """The author's walkthrough: 'The preview label text should be on the
    right of the fit and 1:1 buttons so it doesn't shift them around when
    it loads.'

    Finding 7 (M7 walkthrough re-review, third round): Findings 2 and 5
    both tried to fit a preview label INSIDE this row -- reordered past a
    stretch, it still shifted the buttons at a realistic dock width;
    given a fixed width instead, it raised the dock's own minimum width
    and clipped its neighbours permanently; made to elide gracefully
    (`_ElidingLabel`), it elided all the way to an EMPTY STRING at 900px,
    silently dropping the spec §3.3 cue the whole feature exists to give.
    There was never room in this row for it, at any width worth using.
    The preview marker moved to the window title instead (see
    `test_the_title_marks_a_preview_and_clears_on_snap_back`), which costs
    the row nothing -- so this test's job shrinks to confirming exactly
    that: with the toolbar back to its pre-M7 widget set, nothing in it
    moves when a preview starts, at the 900px width the author actually
    uses.
    """
    session = SiteSession()
    dock = ProfileDock(session)
    dock.setFixedWidth(900)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    # The second line's label is deliberately far longer than any real
    # file stem this plugin has ever opened, so the test does not depend
    # on a particular name happening to fit -- it now names the WINDOW
    # TITLE, which can hold it regardless, rather than a toolbar label.
    labels = ["FILE__001", "a genuinely very long survey line name indeed"]
    lines = []
    for i, label in enumerate(labels):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=240)
        line = Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, -1, label))
        session.add_lines([line])
        lines.append(line)
    keys = session.keys()
    session.open_line(keys[0])
    for key, line in zip(keys, lines):
        session.set_profiles(key, line.load())
    # QTest.qWait, not a bare processEvents() and not no wait at all: this
    # offscreen QPA build warns "This plugin does not support
    # propagateSizeHints()" on every dock construction, and a box
    # layout's cross-widget geometry here measurably needs a real trip
    # through the event loop to settle -- confirmed directly, twice: a
    # single processEvents() (and separately, qWait(0)) both read a
    # stale, pre-settle geometry and passed for the wrong reason, and
    # reading immediately with no wait at all reads a degenerate,
    # not-yet-laid-out geometry and also passes vacuously. qWait(50) was
    # stable over repeated local reruns.
    QTest.qWait(50)
    assert dock.width() == 900, f"the width constraint did not take: {dock.width()}"
    before_fit = dock.fit_button.x()
    before_one_to_one = dock.one_to_one_button.x()
    velocity_text_width = dock.velocity_label.fontMetrics().horizontalAdvance(
        dock.velocity_label.text()
    )
    assert velocity_text_width > 0  # sanity: really populated, like production
    assert dock.velocity_label.width() >= velocity_text_width  # not squeezed, even before
    assert "PREVIEW" not in dock.windowTitle()

    session.set_preview(keys[1], 5)
    QTest.qWait(50)

    assert dock.fit_button.x() == before_fit
    assert dock.one_to_one_button.x() == before_one_to_one
    assert dock.velocity_label.width() >= velocity_text_width  # still not squeezed
    # The cue spec §3.3 requires is visible -- not merely "a method was
    # called" -- and it is the actual, un-elided line name: the whole
    # point of moving it out of the toolbar row.
    assert "PREVIEW" in dock.windowTitle()
    assert "a genuinely very long survey line name indeed" in dock.windowTitle()
    dock.hide()
    dock.deleteLater()


def test_the_toolbar_minimum_width_is_back_to_pre_m7(qgis_app):
    """Findings 2 and 5's fixed-width/eliding-label machinery is gone
    entirely now (Finding 7) -- `minimumSizeHint().width()` should be
    close to the ~658px Finding 5 already measured with `_ElidingLabel`
    in place (measured here: 662px -- a plain, empty `QLabel("")` costs a
    few px more than `_ElidingLabel`'s `Ignored` policy did, which is
    expected and harmless), and nowhere near the ~1098px either
    `setFixedWidth` version reached. The toolbar's widget set is now
    IDENTICAL to what it was before any of this episode:
    `difference_label` is back to a plain, unreserved `QLabel`, and there
    is no preview label in the row at all any more."""
    session = SiteSession()
    dock = ProfileDock(session)
    assert dock.minimumSizeHint().width() <= 700
    dock.hide()
    dock.deleteLater()


def test_pick_requested_relays_key_trace_and_time(opened):
    """I2/I6: `view.pick_requested.connect(self._pick)` and `_pick`'s own
    re-emission of `self.pick_requested` are both wired but nothing in the
    suite ever emitted a pick -- deleting either survived. Confirms the
    positive path: a pick on the view reaches the dock's own signal,
    carrying the currently open line's key alongside the trace and time.
    """
    session, dock, key, line = opened
    picks = []
    dock.pick_requested.connect(lambda k, t, ns: picks.append((k, t, ns)))
    dock.view.pick_requested.emit(10, 5.0)
    assert picks == [(key, 10, 5.0)]


def test_velocity_label_reports_unknown_source_when_no_known_tier_matches(opened, monkeypatch):
    """I3: the old identity-based fallback assumed whatever remained
    unmatched was the header tier, so a future `resolve_velocity` that
    adds a fourth tier (GitHub issue #4's plan, e.g. a site-level default)
    would have been silently mislabelled "header ε ..." instead of
    reporting that it does not recognise the source. Simulates exactly
    that by monkeypatching `resolve_velocity` to return a model equal to
    none of the three known candidates (the line has no override, grid A's
    velocity is 0.08 m/ns, and the header's dielectric resolves to about
    0.080 m/ns too -- 0.5 m/ns matches none of them).
    """
    session, dock, key, line = opened
    import nsgeo_qgis.ui.profile_dock as profile_dock_module

    monkeypatch.setattr(
        profile_dock_module,
        "resolve_velocity",
        lambda line, grid: VelocityModel.constant(0.5),
    )
    assert velocity_source(session, key) == "unknown source"


def test_velocity_label_recognises_an_equal_but_different_velocity_object(opened, monkeypatch):
    """I3: `==`, not `is`, is what makes `velocity_source` robust to a
    `resolve_velocity` that returns a *copy* of the resolved tier's model
    rather than the original object -- a difference invisible to any test
    that only calls the real `resolve_velocity`, which never copies today
    (so reverting this comparison back to `is` still passes every other
    test in this file). Monkeypatches `resolve_velocity` to return an
    equal-but-distinct copy of grid A's velocity model, simulating exactly
    that, without needing to mutate `nsgeo.velocity` itself: an `is` check
    would miss it (no candidate is the *same object*) and fall through to
    "unknown source"; `==` still recognises it as "Grid A".
    """
    session, dock, key, line = opened
    grid = session.grid_for_line(line)
    copy_of_grid_velocity = dataclasses.replace(grid.velocity)  # equal value, distinct object
    assert copy_of_grid_velocity is not grid.velocity and copy_of_grid_velocity == grid.velocity
    import nsgeo_qgis.ui.profile_dock as profile_dock_module

    monkeypatch.setattr(
        profile_dock_module,
        "resolve_velocity",
        lambda line, grid: copy_of_grid_velocity,
    )
    assert velocity_source(session, key) == "Grid A"


def test_refresh_velocity_returns_silently_once_the_site_is_closed(opened, message_log):
    """I4: the `not self.session.is_open` half of `_refresh_velocity`'s
    guard is not redundant with the `except KeyError` below it, even
    though nothing in today's call graph reaches this state (`close_site`
    always emits `line_opened("")` -- clearing `dock._key` via `_open` --
    before `site_closed`). Forces the otherwise-unreachable state directly
    to prove the two halves are behaviourally different:
    `session.resolved_velocity` raises `ProjectError` (not a `KeyError`)
    once the site is closed, so without this half the call falls into the
    broad `except Exception` and logs a Critical message instead of
    returning quietly.
    """
    session, dock, key, line = opened
    session.close_site()
    dock._working_key = key  # force the otherwise-unreachable state directly
    dock._refresh_velocity()
    assert not message_log


# ---- preview rendering (M7, spec §3.3) --------------------------------------


@pytest.fixture
def previewing(qgis_app, tmp_path):
    """Two lines on one grid, both loaded, the first open. `opened` has
    only one line, and a preview needs somewhere else to point.

    Both lines are loaded (`set_profiles`, the same idiom `opened`-based
    tests use) rather than left with an empty stack: a preview over a
    line with nothing to render would never reach `_render()`, and could
    not exercise the one hazard `_effective_difference_index` exists to
    guard -- `stack.difference(i)` evaluated against a previewed line's
    stack that does not have `i` steps on it.
    """
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=240)
        line = Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, -1, p.stem))
        session.add_lines([line])
        lines.append(line)
    keys = session.keys()
    session.open_line(keys[0])
    for key, line in zip(keys, lines):
        session.set_profiles(key, line.load())
    yield dock, session, keys
    # Parentless top-level widget: torn down explicitly rather than left
    # for Python's GC to race Qt's widget teardown. See `opened`.
    dock.hide()
    dock.deleteLater()


def test_preview_renders_the_previewed_line_not_the_working_one(previewing):
    dock, session, keys = previewing
    before = dock.image

    session.set_preview(keys[1], 5)

    assert dock._key == keys[1]
    assert session.current_key == keys[0]
    assert dock.image is not None and dock.image is not before
    label = session.line_for_key(keys[1]).path.stem
    assert label in dock.windowTitle()


def test_the_title_marks_a_preview_and_clears_on_snap_back(previewing):
    """Finding 7 (M7 walkthrough re-review, third round): the preview
    marker lives in the window title now, not a toolbar label -- spec
    §3.3 only requires that the profile state which line it is showing
    and whether that is a preview, and the title already does both, at
    no layout cost."""
    dock, session, keys = previewing
    assert "PREVIEW" not in dock.windowTitle()

    session.set_preview(keys[1], 5)
    assert "PREVIEW" in dock.windowTitle()
    assert session.line_for_key(keys[1]).path.stem in dock.windowTitle()

    session.clear_preview()
    assert "PREVIEW" not in dock.windowTitle()
    assert dock._key == keys[0]


def test_the_tooltip_carries_the_preview_hint_and_clears_with_it(previewing):
    """Finding 7(e) (M7 walkthrough re-review, third round): '— select it
    on the map to work on it' does not belong in a title -- a title is
    read at a glance, that hint is read on purpose -- so it lives as the
    dock's tooltip instead, set only while a preview is showing and
    cleared the instant it ends, the same lifecycle as the `PREVIEW`
    title marker itself."""
    dock, session, keys = previewing
    assert dock.toolTip() == ""

    session.set_preview(keys[1], 5)
    assert "select it on the map to work on it" in dock.toolTip()

    session.clear_preview()
    assert dock.toolTip() == ""


def test_moving_along_a_previewed_line_does_not_rerender_per_move(previewing, monkeypatch):
    """Finding 1 (M7 walkthrough re-review, Important -- blocks): Tweak 1
    makes MapLink emit session.set_preview on every mouse move so the
    cursor tracks a previewed line smoothly, without waiting for the
    dwell. Before this fix, `_on_preview_changed` routed EVERY one of
    those into `_enter_preview` -> `_show_line` -> a full radargram
    rebuild (`self.image = None` then `_render()`), even when the key had
    not changed and only the trace moved. Measured end to end: 50 moves
    along a previewed 1300-trace line, 16.8 ms/move -- the exact renderer
    thrash the dwell exists to prevent, now happening on our side
    instead.

    Counts renders (via `_render`), not merely the cursor moving -- a
    test that only asserts the cursor tracked would pass with the bug
    present, since `_enter_preview` also moves the cursor on its way to
    rebuilding everything else.
    """
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)  # first entry: one real render, expected
    assert dock._preview_key == keys[1]
    renders = []
    monkeypatch.setattr(dock, "_render", lambda: renders.append(1))

    for trace in range(10, 20):
        session.set_preview(keys[1], trace)

    assert renders == []  # zero rebuilds for ten more moves on the same line
    assert dock.view._cursor == 19  # but the cursor tracked every one of them


def test_the_gain_strip_hides_during_a_preview_and_comes_back(previewing):
    dock, session, keys = previewing
    dock.show_gain_strip([[0.0, 1.0], [1.0, 2.0]], owner=("x", 0, 0))
    assert dock.gain_strip.isVisible()

    session.set_preview(keys[1], 5)
    assert not dock.gain_strip.isVisible()

    session.clear_preview()
    assert dock.gain_strip.isVisible()


def test_a_hidden_gain_strip_stays_hidden_after_a_preview(previewing):
    dock, session, keys = previewing
    assert not dock.gain_strip.isVisible()

    session.set_preview(keys[1], 5)
    session.clear_preview()

    assert not dock.gain_strip.isVisible()


def test_the_difference_index_survives_a_preview_round_trip(previewing):
    dock, session, keys = previewing
    session.append_step(keys[0], build_step("dewow", window_ns=4.0))
    dock.set_difference_index(0)
    assert dock._difference_index == 0
    assert "dewow" in dock.difference_label.text()

    # keys[1] has an EMPTY stack, so index 0 does not exist on it. If the
    # render used the stored index instead of the effective one this would
    # raise IndexError inside a slot -- qFatal() in the LTR container.
    session.set_preview(keys[1], 5)
    assert dock._effective_difference_index == -1
    assert dock._difference_index == 0
    assert dock.difference_label.text() == ""
    assert dock.image is not None

    session.clear_preview()
    assert dock._effective_difference_index == 0
    assert "dewow" in dock.difference_label.text()


def test_snap_back_restores_the_working_lines_cursor_and_selection(previewing):
    dock, session, keys = previewing
    session.set_trace(keys[0], 9)
    session.set_selection(keys[0], 3, 11)

    session.set_preview(keys[1], 5)
    session.clear_preview()

    assert dock.view._cursor == 9
    assert dock.view._selection == (3, 11)


def test_hovering_the_profile_during_a_preview_does_not_move_the_working_trace(
    previewing,
):
    """The C2 guard at the widget level."""
    dock, session, keys = previewing
    session.set_trace(keys[0], 9)
    session.set_preview(keys[1], 5)

    dock.view.trace_hovered.emit(40)

    assert session.current_trace == 9
    assert session.current_key == keys[0]


def test_a_click_while_previewing_does_not_disturb_the_working_lines_selection(previewing):
    """Spec §3.3: a preview is never a write target. `clear_selection()`
    has no key argument of its own to structurally reject a call arriving
    while a different line is on screen -- unlike `set_trace`/
    `set_selection`, which `_hovered`/`_range_selected` route through with
    `self._key` and let the session's own `current_key` check no-op them
    (see `_selection_cleared`'s own reasoning) -- so this is guarded
    explicitly instead, the same way `_channel_changed` already is."""
    dock, session, keys = previewing
    session.set_selection(keys[0], 3, 11)
    session.set_preview(keys[1], 5)
    assert dock._key == keys[1]  # sanity: really previewing

    dock.view.selection_cleared.emit()

    assert session.selection == (3, 11)  # the working line's selection, untouched


def test_previewing_the_working_line_is_not_a_preview(previewing):
    dock, session, keys = previewing

    session.set_preview(keys[0], 5)

    assert "PREVIEW" not in dock.windowTitle()
    assert dock._key == keys[0]


def test_opening_a_line_while_previewing_ends_the_preview(previewing):
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)

    session.open_line(keys[1])

    assert "PREVIEW" not in dock.windowTitle()
    assert dock._key == keys[1]


def test_closing_the_site_while_previewing_clears_the_preview_marker(previewing):
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)

    session.close_site()

    assert "PREVIEW" not in dock.windowTitle()
    assert dock._key is None


def test_removing_the_current_line_while_previewing_another_keeps_the_dock_in_sync(previewing):
    """Finding 2 (M7 final review): remove_line() resets ONLY the dropped
    key's own current/preview fields, so removing the CURRENT line while a
    DIFFERENT line is being previewed leaves session.preview_key (and the
    map marker) still naming that other line. Before this fix, `_open("")`
    dropped `_preview_key` unconditionally regardless, so the dock went
    blank and the banner vanished while session.display_key -- what the
    map still shows -- kept naming the previewed line: this dock desyncing
    from the session it is supposed to mirror."""
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)
    assert dock._key == keys[1]

    session.remove_line(keys[0])

    assert session.display_key == keys[1]
    assert dock._key == keys[1]
    assert "PREVIEW" in dock.windowTitle()


def test_a_shift_click_on_a_preview_authors_no_pick(previewing):
    dock, session, keys = previewing
    emitted = []
    dock.pick_requested.connect(lambda k, t, ns: emitted.append((k, t, ns)))
    session.set_preview(keys[1], 5)

    dock.view.pick_requested.emit(20, 15.0)

    assert emitted == []


def test_a_channel_change_is_refused_while_previewing(previewing):
    """Review finding 1 (M7 Task 2): `session.set_channel` has no
    `current_key` guard of its own, unlike `set_trace`/`set_selection` --
    before `_key` meant "displayed", this path could never reach a line
    that was not the working one, so nothing guarded it here. Checks both
    halves of the fix: the session is untouched, and the control that
    would have caused it is disabled, not just silently ignored.
    """
    dock, session, keys = previewing
    before = session.channel(keys[1])

    session.set_preview(keys[1], 5)
    assert not dock.channel_combo.isEnabled()
    dock._channel_changed(0)

    assert session.channel(keys[1]) == before

    session.clear_preview()
    assert dock.channel_combo.isEnabled()


def test_a_gain_strip_request_mid_preview_is_deferred_and_honoured_on_exit(previewing):
    """Review finding 2 (M7 Task 2): the strip writes on drag, so showing
    a curve that belongs to a line not on screen is the C2 configuration
    -- reachable when the working line's own curve arrives (via
    `show_gain_strip`) while a preview is up. The request must not show
    the strip early, but must not be lost either: `_exit_preview` has to
    honour the newest points once the preview ends.
    """
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)

    dock.show_gain_strip([[0.0, 1.0], [1.0, 2.0]], owner=("x", 0, 0))
    assert not dock.gain_strip.isVisible()

    session.clear_preview()

    assert dock.gain_strip.isVisible()
    assert dock.gain_strip.points() == [[0.0, 1.0], [1.0, 2.0]]


def test_a_deferred_strip_is_dropped_when_the_preview_is_promoted(previewing):
    """Review finding 4 (M7 Task 2): the deferred payload belongs to the
    line that WAS working. Replaying it after promotion puts another
    line's curve on the strip, and a drag there writes through
    session.current_key."""
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)
    dock.show_gain_strip([[0.0, 1.0], [1.0, 2.0]], owner=("a", 0, 0))
    assert not dock.gain_strip.isVisible()

    session.open_line(keys[1])  # promotion -- _open, not _exit_preview
    assert dock._deferred_strip is None

    session.set_preview(keys[0], 3)  # a later, unrelated preview
    session.clear_preview()
    assert not dock.gain_strip.isVisible()


def test_a_deferred_strip_is_dropped_when_the_site_closes(previewing):
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)
    dock.show_gain_strip([[0.0, 1.0], [1.0, 2.0]], owner=("a", 0, 0))

    session.close_site()

    assert dock._deferred_strip is None


def test_a_hide_arriving_mid_preview_is_honoured_on_exit(previewing):
    dock, session, keys = previewing
    dock.show_gain_strip([[0.0, 1.0], [1.0, 2.0]], owner=("a", 0, 0))
    assert dock.gain_strip.isVisible()
    session.set_preview(keys[1], 5)

    dock.show_gain_strip(None)
    session.clear_preview()

    assert not dock.gain_strip.isVisible()


def test_a_preview_that_triggers_a_load_does_not_persist_an_empty_stack(opened):
    """Finding 4 (M7 final review): verified by experiment that
    `current_radargram`'s own `stack_for(preview_key)` call is, in every
    reachable path, a re-fetch of an entry `SiteSession.set_profiles`
    already created -- set_profiles is where a hover-triggered background
    load actually lands, synchronously before `line_loaded` (and so
    `_render()`) ever fires for that key. Adds a second, never-loaded
    line, previews it (no set_profiles yet: `_show_line` takes its
    axes-only branch since `profiles_for()` is still None, so nothing is
    inserted merely by hovering), then completes its load exactly as
    `LineLoader` would -- both call sites need the fix together for the
    empty stack to never land in `site.stacks` at all."""
    session, dock, key, line = opened
    p2 = synthetic_dzt(session.root / "raw", "FILE__002.DZT", n_traces=240)
    line2 = Line.open(p2, GridPlacement("A", "y", 0.5, 0.0, 1, "FILE__002"))
    session.add_lines([line2])
    key2 = next(k for k in session.keys() if k != key)  # noqa: SIM118 -- SiteSession.keys(), not a dict

    session.set_preview(key2, 3)
    assert key2 not in session.site.stacks  # sanity: hovering alone plants nothing

    session.set_profiles(key2, line2.load())  # the background load "finishing"

    assert dock.image is not None  # sanity: the preview really rendered
    assert key2 not in session.site.stacks


# ---- pick mode and pick refusal (M8, spec §4.1, §4.3) ----------------------


def test_set_pick_mode_reaches_the_view(opened):
    """`ProfileView.set_pick_mode` shipped in Plan 2 with no caller at
    all -- a manual tester found it, went looking for a pick mode, and
    concluded the build was broken rather than that the feature was
    unbuilt (spec §1). This is its first consumer."""
    session, dock, key, line = opened
    dock.set_pick_mode(True)
    assert dock.view.cursor().shape() == Qt.CursorShape.CrossCursor
    dock.set_pick_mode(False)
    assert dock.view.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_a_pick_while_previewing_is_refused_out_loud(previewing):
    """M7 guarded this and returned silently, because nothing consumed
    the signal yet. Now that a pick is real, silence is indistinguishable
    from a pick that landed -- the user shift-clicks a previewed line and
    nothing whatever happens. The guard stays; it just says why now.

    NOTE on the brief's test: as given, this test never entered a preview
    at all -- the `previewing` fixture only loads two lines and opens the
    first as the WORKING line (see `test_preview_renders_the_previewed_
    line_not_the_working_one`, which calls `session.set_preview` itself to
    get there). Without that call, `dock._preview_key` stays `None` and
    the emitted pick landed on the working line -- confirmed directly: run
    as the brief wrote it, `emitted` held one tuple and the test failed on
    `assert emitted == []`, not on the guard this test means to exercise.
    Added the same `session.set_preview(keys[1], 5)` call the sibling test
    uses to actually reach the previewing state before picking.
    """
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)
    emitted = []
    errors = []
    dock.pick_requested.connect(lambda k, t, ns: emitted.append((k, t, ns)))
    dock.error.connect(errors.append)

    dock.view.pick_requested.emit(20, 15.0)

    assert emitted == []
    assert len(errors) == 1
    assert "preview" in errors[0].lower()


# ---- picks on the profile (M8, spec §4.3) ----------------------------------


@pytest.fixture
def dock_with_picks(qgis_app, tmp_path):
    """A ProfileDock over a session that can actually store picks."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.layers import SiteLayers
    from plugin_testing import synthetic_dzt
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(lines)
    keys = session.keys()
    dock = ProfileDock(session)
    session.open_line(keys[0])
    yield dock, session, layers, keys
    dock.deleteLater()
    layers.detach()
    project.clear()


def test_a_new_pick_appears_on_the_profile_without_reopening_the_line(dock_with_picks):
    """`picks_changed` was declared in Plan 2, never emitted and never
    connected (spec §1). This is its first consumer, and the reason it
    exists: a pick the user just made has to show up where they made
    it."""
    dock, session, layers, keys = dock_with_picks
    assert dock.view._picks == []

    session.add_pick(keys[0], 12, 18.0)

    assert dock.view._picks == [(12, 18.0)]


def test_opening_a_line_shows_the_picks_already_on_it(dock_with_picks):
    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)
    session.open_line(keys[1])
    assert dock.view._picks == []

    session.open_line(keys[0])

    assert dock.view._picks == [(5, 10.0)]


def test_a_preview_shows_the_previewed_lines_own_picks(dock_with_picks):
    """Reading is not authoring. The view follows `display_key`, so a
    preview shows the hovered line's picks -- the point of a preview is
    to see what is on that line, interpretation included -- while
    `add_pick` still refuses to write there."""
    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)
    session.open_line(keys[1])
    session.add_pick(keys[1], 44, 33.0)
    session.open_line(keys[0])

    session.set_preview(keys[1], 20)
    assert dock.view._picks == [(44, 33.0)]

    session.clear_preview()
    assert dock.view._picks == [(5, 10.0)]


def test_closing_the_site_clears_the_picks_from_the_view(dock_with_picks):
    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)

    session.close_site()

    assert dock.view._picks == []


def test_a_failing_pick_read_is_logged_not_escaped(dock_with_picks, monkeypatch, message_log):
    """`picks_changed` is a Qt signal, so this slot's body runs under
    C++: an exception escaping it reaches qFatal() in the LTR container.
    The conftest's `_no_swallowed_slot_exceptions` fixture is what turns
    a regression here into a local red test."""
    dock, session, layers, keys = dock_with_picks

    def boom(key):
        raise RuntimeError("the picks table went away")

    monkeypatch.setattr(session, "picks_for", boom)
    session.picks_changed.emit()

    assert any("the picks table went away" in m for m in message_log)
