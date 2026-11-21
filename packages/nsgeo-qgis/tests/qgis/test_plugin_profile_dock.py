from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.render import PercentileClip, colormap_names, to_index8
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.line_edit import LineEdit
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from nsgeo_qgis.ui import profile_dock
from nsgeo_qgis.ui.processing_dock import ProcessingDock
from nsgeo_qgis.ui.profile_dock import (
    LEFT_AXIS_KEY,
    PREVIEW_STEPS_REFUSED_TEXT,
    SLICE_BAND_KEY,
    STEPS_REFUSED_TEXT,
    ProfileDock,
    relabel_onto,
    velocity_source,
)
from nsgeo_qgis.ui.ruler import trace_units_at
from plugin_testing import REAL_DZT, needs_real_data, send_move_while_pressed, synthetic_dzt
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QLabel, QMessageBox, QStyle
from tests.real_data import CAMPUS_LINES, GPS_LINES

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


def test_colormap_combo_offers_only_bipolar_tables(bare):
    """M10 gave `colormap_names()` a `unipolar` filter for slice display.
    A radargram is bipolar, so this combo must ask for the bipolar tables
    only -- calling it with no argument would silently add amp_heat (a
    configuration error on bipolar data, per render.py's own
    UNIPOLAR_COLORMAPS docstring) plus amp_black_high/amp_white_high,
    which are pixel-identical to grey_black_high/grey_white_high already
    in the list.
    """
    _, dock, _ = bare
    items = [dock.colormap_combo.itemText(i) for i in range(dock.colormap_combo.count())]
    assert items == colormap_names(unipolar=False)
    assert "amp_heat" not in items


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
    blo, bhi = zoomed.trace_bounds
    assert zoomed.trace_hi - zoomed.trace_lo < bhi - blo  # sanity: this really is zoomed in
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
    """Both lines are ruled (on grid A), so this no longer pins the old
    n_traces gate. It pins that the second line's transform is built for its
    own trace count (300), not the first line's stale 240.
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
    assert dock.difference_label.text() == "Difference: Dewow"
    np.testing.assert_array_equal(dock.image.rg.data, expected_diff)

    dock.set_difference_index(-1)
    assert dock.difference_label.text() == ""
    np.testing.assert_array_equal(dock.image.rg.data, after_data)


def test_a_declined_difference_falls_back_to_the_ordinary_result(opened):
    """Ruling R7. With the difference view on background_mean, aiming it at
    time_zero (which changes the sample count) is declined, once, and the
    view shows the ordinary result. It used to keep background_mean's
    difference on screen with the button already off."""
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("time_zero", mode="sample", sample=40))
    session.append_step(key, build_step("background_mean"))
    stack = session.stack_for(key)
    dock.set_difference_index(1)
    np.testing.assert_array_equal(dock.image.rg.data, stack.difference(1).data)
    errors, cleared = [], []
    dock.error.connect(errors.append)
    dock.difference_cleared.connect(lambda: cleared.append(1))
    dock.set_difference_index(0)
    assert dock.image.rg.n_samples == 472
    np.testing.assert_array_equal(dock.image.rg.data, stack.result().data)
    assert dock.difference_label.text() == ""
    assert len(errors) == 1 and "sample count" in errors[0]
    assert cleared == [1]


def test_clear_resets_the_difference_view(opened):
    """#20 item 4. No real path reaches `_clear` with a Difference view
    showing today (`close_site` goes through `_open("")` first, which resets
    it), so this calls it directly: a guard for the day one does. It fails
    without the `_difference_index = -1` / label reset in `_clear`."""
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("background_mean"))
    dock.set_difference_index(1)
    cleared = []
    dock.difference_cleared.connect(lambda: cleared.append(1))
    dock._clear()
    assert dock._difference_index == -1
    assert dock.difference_label.text() == ""
    assert cleared == [1]


def test_a_step_failing_under_the_difference_view_is_reported_once(opened):
    """A difference reads the stack's intermediates, so a step that fails
    upstream of it fails the difference and the ordinary result alike, with
    the same message. Declining the one and then reporting the other must
    not put that message on the bar twice."""
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow", window_ns=4.0))
    session.append_step(key, build_step("background_mean"))
    dock.set_difference_index(1)
    errors = []
    dock.error.connect(errors.append)
    session.replace_step(key, 0, build_step("bandpass", low_mhz=100.0, high_mhz=90_000.0))
    assert len(errors) == 1 and "Nyquist" in errors[0]
    assert dock.difference_label.text() == ""


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
    """I2: a click on `fit_button` runs its default action (Fit, until another
    is picked), which is wired to `ProfileView.fit`; nothing in the suite ever
    clicked it -- deleting the `connect()` call survived. Zooms in first so
    `fit_button.click()` has something to visibly undo.
    """
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    t = dock.view.transform
    blo, bhi = t.trace_bounds
    assert t.trace_hi - t.trace_lo < bhi - blo  # really zoomed in
    dock.fit_button.click()
    # Fit shows the whole ruler (the grid's length, widened to this line), not
    # trace 0 to the line's own end.
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx(t.trace_bounds)


def test_the_one_to_one_button_shows_true_scale(opened):
    """The button gives a metre down the same length as a metre along. `GRID`'s
    0.08 m/ns makes `ns_per_metre` 25."""
    session, dock, key, line = opened
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    dock.one_to_one_button.click()
    t = dock.view.transform
    lo, hi = t.trace_lo, t.trace_hi
    m = dock.view.metres_at_trace_units
    across = t.width / (abs(m(hi) - m(lo)) / (hi - lo) * (hi - lo))
    assert t.time_hi - t.time_lo == pytest.approx(t.height / across * 25.0, rel=0.01)


def test_true_scale_is_greyed_without_a_velocity(opened, monkeypatch):
    session, dock, key, line = opened
    assert dock.one_to_one_button.isEnabled()
    monkeypatch.setattr(
        session, "resolved_velocity", lambda k: (_ for _ in ()).throw(KeyError("none"))
    )
    dock._refresh_velocity()
    assert not dock.one_to_one_button.isEnabled()


def test_true_scale_is_greyed_with_no_line_and_after_the_view_is_cleared(bare, opened):
    _, dock, _ = bare
    assert not dock.one_to_one_button.isEnabled()
    assert dock.one_to_one_button.toolTip() == profile_dock.TRUE_SCALE_GREYED_TIP
    session, odock, key, line = opened
    assert odock.one_to_one_button.isEnabled()
    session.close_site()
    assert not odock.one_to_one_button.isEnabled()
    assert odock.one_to_one_button.toolTip() == profile_dock.TRUE_SCALE_GREYED_TIP


def test_true_scale_greys_when_the_window_moves_onto_a_flat_run(opened, monkeypatch):
    session, dock, key, line = opened
    v = dock.view
    assert dock.one_to_one_button.isEnabled()
    n = line.n_traces
    flat = np.r_[np.arange(n // 2, dtype=float), np.full(n - n // 2, n // 2 - 1.0)] / 60.0
    v._distance = flat
    v.transform = v.transform.with_window(
        n * 0.6, n * 0.9, v.transform.time_lo, v.transform.time_hi
    )
    v.view_changed.emit()
    assert not dock.one_to_one_button.isEnabled()
    assert dock.one_to_one_button.toolTip() == profile_dock.TRUE_SCALE_FLAT_TIP
    assert profile_dock.TRUE_SCALE_FLAT_TIP != profile_dock.TRUE_SCALE_GREYED_TIP


def test_true_scale_is_greyed_on_a_line_with_no_metres(opened):
    session, dock, key, line = opened
    k2, _ = _add_line(
        session, "U1", GridPlacement("A", "y", 0.0, 0.0, 1, "U1"), traces_per_metre=0.0
    )
    session.open_line(k2)
    assert not dock.one_to_one_button.isEnabled()
    assert dock.view.metres_at_trace_units(10.0) is None


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

    Re-pinned for spec section 4.1: the velocity label may now elide at
    900px (the Slice band button takes room), so it is the label's full
    text that is asserted, not its width.
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
    velocity_text = dock.velocity_label.text()
    assert velocity_text  # sanity: really populated, like production
    assert "PREVIEW" not in dock.windowTitle()

    session.set_preview(keys[1], 5)
    QTest.qWait(50)

    assert dock.fit_button.x() == before_fit
    assert dock.one_to_one_button.x() == before_one_to_one
    assert dock.velocity_label.text() == velocity_text  # the full text is kept
    # The cue spec §3.3 requires is visible -- not merely "a method was
    # called" -- and it is the actual, un-elided line name: the whole
    # point of moving it out of the toolbar row.
    assert "PREVIEW" in dock.windowTitle()
    assert "a genuinely very long survey line name indeed" in dock.windowTitle()
    dock.hide()
    dock.deleteLater()


def test_the_toolbar_minimum_width_holds_in_any_font(qgis_app):
    """The row's minimum width, checked in ways that hold in any font (pixel
    bounds measured on one machine failed on CI's QGIS 3.44, 723 against 684).
    The velocity label is an `ElidedLabel` (`Ignored`) and asks for no width,
    and `difference_label` is a plain `QLabel`: long texts in both raise the
    minimum by no more than the Difference label's own growth. And the row
    stays within 900px, the docked width the M7 walkthrough used."""
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    QTest.qWait(50)
    base = dock.minimumSizeHint().width()
    label_before = dock.difference_label.sizeHint().width()
    dock.difference_label.setText("Difference: " + "w" * 60)
    dock.velocity_label.setText("Velocity " + "w" * 200)
    QTest.qWait(50)
    grown = dock.difference_label.sizeHint().width() - label_before
    after = dock.minimumSizeHint().width()
    assert after >= base + grown  # live: a stale cached reading fails here
    assert after <= base + grown
    assert base <= 900
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
    assert "Dewow" in dock.difference_label.text()

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
    assert "Dewow" in dock.difference_label.text()


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


# ---- live picks editing (M8 acceptance walkthrough, Finding A) ------------
#
# The author's own words: "if I selected a point and deleted it and hit
# save, the pick stayed visible in the profile until I made another pick
# in the profile, at which time the deleted ones would disappear." The
# cause was that nothing watched the `picks` layer's OWN editing signals --
# `picks_changed` was emitted from exactly one place (`SiteSession.
# add_pick`). These are the end-to-end (dock + real SiteLayers) versions:
# real edit-buffer operations (`startEditing`/`deleteFeature`/
# `commitChanges`), asserting on `dock.view._picks` itself, not on the
# signal being emitted by hand.


def test_a_buffered_delete_then_commit_refreshes_the_profile(dock_with_picks):
    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)
    assert dock.view._picks == [(5, 10.0)]

    picks = layers.layers["picks"]
    fid = next(picks.getFeatures()).id()
    assert picks.startEditing()
    assert picks.deleteFeature(fid)
    assert dock.view._picks == []  # visible before commitChanges() -- live

    assert picks.commitChanges()
    assert dock.view._picks == []  # and it STAYS gone -- the reported defect


def test_a_buffered_add_then_commit_refreshes_the_profile(dock_with_picks):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

    dock, session, layers, keys = dock_with_picks
    picks = layers.layers["picks"]
    assert picks.startEditing()
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 706.0)))
    f.setAttribute("line_key", keys[0])
    f.setAttribute("trace", 7)
    f.setAttribute("time_ns", 22.0)
    assert picks.addFeature(f)
    assert dock.view._picks == [(7, 22.0)]  # live, before any commit

    assert picks.commitChanges()
    assert dock.view._picks == [(7, 22.0)]


def test_a_geometry_move_through_the_edit_buffer_refreshes_the_profile(dock_with_picks):
    """A geometry-only move doesn't change what the view shows -- trace
    and time, not position -- so this counts `picks_changed` emissions
    instead of view content, proving the wiring actually fires for
    `geometryChanged` and not merely that unrelated content still
    matches."""
    from qgis.core import QgsGeometry, QgsPointXY

    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)
    picks = layers.layers["picks"]
    fid = next(picks.getFeatures()).id()
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))

    assert picks.startEditing()
    assert picks.changeGeometry(fid, QgsGeometry.fromPointXY(QgsPointXY(501.0, 707.0)))

    assert seen
    picks.commitChanges()


def test_a_rollback_restores_the_profile_to_what_is_on_disk(dock_with_picks):
    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)
    picks = layers.layers["picks"]
    fid = next(picks.getFeatures()).id()
    assert picks.startEditing()
    assert picks.deleteFeature(fid)
    assert dock.view._picks == []

    assert picks.rollBack()

    assert dock.view._picks == [(5, 10.0)]


def test_the_picks_binding_survives_a_site_close_and_reopen(dock_with_picks, tmp_path):
    """A site reopen replaces the `picks` layer OBJECT outright
    (`SiteLayers.detach()` empties its registry, `ensure_tables()` opens
    a fresh one) -- a connection made once and never renewed would point
    at a dead wrapper and silently stop updating the profile after this,
    the exact defect `MapLink._rebind_layer` exists to prevent for its
    own three layers."""
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

    dock, session, layers, keys = dock_with_picks
    session.save()
    key0 = keys[0]

    session.close_site()
    session.open_site(tmp_path / SURVEY_FILE)
    session.open_line(key0)

    picks = layers.layers["picks"]
    assert picks.startEditing()
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f.setAttribute("line_key", key0)
    f.setAttribute("trace", 9)
    f.setAttribute("time_ns", 15.0)
    assert picks.addFeature(f)

    assert dock.view._picks == [(9, 15.0)]


# ---- time cutoff (draggable late-time clip) ----------------------------------------


def _cutoff_setup(session, key, line, *extra_steps):
    """Load `line`, then give its stack `[time_cutoff(end), *extra_steps]`
    with `end` 200 samples in. Returns (stack, rg, end)."""
    session.set_profiles(key, line.load())
    stack = session.stack_for(key)
    rg = stack.source
    end = rg.t0_ns + 200 * rg.dt_ns
    session.append_step(key, build_step("time_cutoff", end_ns=end))
    for step in extra_steps:
        session.append_step(key, step)
    return stack, rg, end


def test_selecting_a_cutoff_step_shows_the_whole_record_with_the_line(opened):
    session, dock, key, line = opened
    _, _, end = _cutoff_setup(session, key, line)
    dock.set_selected_step(0)
    assert dock.image.rg.n_samples == 512
    assert dock.view.cutoff_ns == pytest.approx(end)
    dock.set_selected_step(-1)
    assert dock.image.rg.n_samples == 200
    assert dock.view.cutoff_ns is None


def test_steps_after_the_cutoff_still_apply_while_it_is_selected(opened):
    session, dock, key, line = opened
    stack, _, _ = _cutoff_setup(session, key, line, build_step("gain_agc", window_ns=10.0))
    dock.set_selected_step(0)
    assert np.array_equal(dock.image.rg.data, stack.result_bypassing(0).data)


def test_dragging_the_line_writes_the_step(opened):
    session, dock, key, line = opened
    stack, rg, end = _cutoff_setup(session, key, line)
    dock.set_selected_step(0)
    dock.view.cutoff_dragged.emit(end - 10 * rg.dt_ns)
    assert stack.entries[0][0].params["end_ns"] == pytest.approx(end - 10 * rg.dt_ns)
    assert session.dirty
    assert dock.view.cutoff_ns == pytest.approx(end - 10 * rg.dt_ns)


def test_a_drag_to_the_same_time_writes_nothing(opened, message_log):
    session, dock, key, line = opened
    _, _, end = _cutoff_setup(session, key, line)
    dock.set_selected_step(0)
    changed = []
    session.stack_changed.connect(changed.append)
    dock.view.cutoff_dragged.emit(end)
    assert changed == []
    # A slot that crashed and logged would write nothing too.
    assert not [m for m in message_log if "could not move the time cutoff" in m]


def test_a_grab_released_where_it_began_leaves_the_session_clean(opened, message_log):
    """Review Focus 5 through the real view. The test above emits the
    identical value at the dock; a real hand presses a few pixels off the
    line, wobbles, and lets go. Here that is 4 px off (about 8 samples on
    this 512-sample, 266-px image) and a 1-px wiggle. Saved first, so a
    write would show as the session turning dirty."""
    session, dock, key, line = opened
    stack, rg, end = _cutoff_setup(session, key, line)
    dock.set_selected_step(0)
    session.save()
    assert not session.dirty
    changed = []
    session.stack_changed.connect(changed.append)
    v = dock.view
    r = v.image_rect()
    x, y = r.left() + 100, r.top() + round(v._cutoff_y(v.transform)) + 4
    QTest.mousePress(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
    send_move_while_pressed(v, QPoint(x, y + 1))
    send_move_while_pressed(v, QPoint(x, y))
    QTest.mouseRelease(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
    assert changed == []
    assert not session.dirty
    assert stack.entries[0][0].params["end_ns"] == end
    assert not [m for m in message_log if "could not move the time cutoff" in m]


def test_a_drag_with_nothing_selected_writes_nothing(opened, message_log):
    session, dock, key, line = opened
    stack, rg, end = _cutoff_setup(session, key, line)
    dock.set_selected_step(-1)
    dock.view.cutoff_dragged.emit(end - 10 * rg.dt_ns)
    assert stack.entries[0][0].params["end_ns"] == pytest.approx(end)
    assert not [m for m in message_log if "could not move the time cutoff" in m]


def test_selecting_between_two_ordinary_steps_does_not_rerender(opened, monkeypatch):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow", window_ns=10.0))
    session.append_step(key, build_step("background_mean"))
    renders = []
    monkeypatch.setattr(dock, "_render", lambda: renders.append(1))
    dock.set_selected_step(0)
    dock.set_selected_step(1)
    assert renders == []


def test_a_preview_hides_the_line_and_refuses_a_drag(previewing, message_log):
    dock, session, keys = previewing
    stack = session.stack_for(keys[0])
    rg = stack.source
    end = rg.t0_ns + 200 * rg.dt_ns
    session.append_step(keys[0], build_step("time_cutoff", end_ns=end))
    dock.set_selected_step(0)
    assert dock.view.cutoff_ns == pytest.approx(end)
    session.set_preview(keys[1], 5)
    assert dock.view.cutoff_ns is None
    dock.view.cutoff_dragged.emit(end - 10 * rg.dt_ns)
    assert stack.entries[0][0].params["end_ns"] == pytest.approx(end)
    assert not [m for m in message_log if "could not move the time cutoff" in m]
    session.set_preview(None)
    assert dock.view.cutoff_ns == pytest.approx(end)


@pytest.fixture
def one_loaded(qgis_app, tmp_path):
    """Two lines, only the first (open) one loaded. `previewing` loads
    both, which dodges the case the first hover over any line is: the
    loader starts on `preview_changed`, so the preview shows before its
    samples exist, and a load that fails leaves it that way."""
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
    session.set_profiles(keys[0], lines[0].load())
    rg = session.stack_for(keys[0]).source
    end = rg.t0_ns + 200 * rg.dt_ns
    session.append_step(keys[0], build_step("time_cutoff", end_ns=end))
    dock.set_selected_step(0)
    assert dock.view.cutoff_ns == pytest.approx(end)
    yield dock, session, keys, lines, rg, end
    # Parentless top-level widget: torn down explicitly. See `opened`.
    dock.hide()
    dock.deleteLater()


def test_a_preview_of_an_unloaded_line_hides_the_cutoff(one_loaded, message_log):
    dock, session, keys, _, rg, end = one_loaded
    session.set_preview(keys[1], 5)
    assert dock.view.cutoff_ns is None
    dock.view.cutoff_dragged.emit(end - 50 * rg.dt_ns)
    assert session.stack_for(keys[0]).entries[0][0].params["end_ns"] == end
    assert not [m for m in message_log if "could not move the time cutoff" in m]
    session.set_preview(None)
    assert dock.view.cutoff_ns == pytest.approx(end)


def test_opening_an_unloaded_line_hides_the_cutoff_until_it_loads(one_loaded, message_log):
    """The second line has its own cutoff at the selected row, as a saved
    project's would, so the line comes back at that line's own time once
    its samples arrive. Until then nothing is drawn to drag, and a drag
    signal writes onto neither line."""
    dock, session, keys, lines, rg, end = one_loaded
    end_b = end - 50 * rg.dt_ns
    session.append_step(keys[1], build_step("time_cutoff", end_ns=end_b))
    session.open_line(keys[1])
    assert dock.view.cutoff_ns is None
    dock.view.cutoff_dragged.emit(end - 80 * rg.dt_ns)
    assert session.stack_for(keys[0]).entries[0][0].params["end_ns"] == end
    assert session.stack_for(keys[1]).entries[0][0].params["end_ns"] == end_b
    assert not [m for m in message_log if "could not move the time cutoff" in m]
    session.set_profiles(keys[1], lines[1].load())
    assert dock.view.cutoff_ns == pytest.approx(end_b)


@pytest.fixture
def processing_first(qgis_app, tmp_path):
    """A Processing panel built BEFORE the profile dock, so its slots on the
    session's signals run first. plugin.py builds them the other way round.
    Torn down the same way `opened` is."""
    session = SiteSession()
    processing = ProcessingDock(session)
    dock = ProfileDock(session)
    processing.step_selected.connect(dock.set_selected_step)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=240)
    line = Line.open(p, GridPlacement("A", "y", 0.0, 0.0, -1, "FILE__001"))
    session.add_lines([line])
    key = session.keys()[0]
    session.open_line(key)
    yield session, processing, dock, key, line
    dock.hide()
    dock.deleteLater()
    processing.deleteLater()


def test_closing_the_site_with_the_cutoff_selected_is_quiet_in_either_order(
    processing_first, message_log
):
    """`close_site` drops the site, then emits `line_opened("")`. The
    Processing panel answers that with `step_selected(-1)`, and when that
    reaches `set_selected_step` before this dock's own `_open` has dropped
    the working line, `_handle_row` reads that line's stack from a site
    that is gone. Only plugin.py's construction order kept it quiet."""
    session, processing, dock, key, line = processing_first
    _cutoff_setup(session, key, line)
    processing.list.setCurrentRow(0)
    assert dock.view.cutoff_ns is not None
    session.close_site()
    assert not [m for m in message_log if "could not follow the selected step" in m]
    assert dock.view.cutoff_ns is None


def test_switching_lines_reads_the_new_lines_step_at_the_selected_row(previewing):
    dock, session, keys = previewing
    a, b = keys
    rg_a = session.stack_for(a).source
    end_a = rg_a.t0_ns + 200 * rg_a.dt_ns
    end_b = rg_a.t0_ns + 100 * rg_a.dt_ns
    session.append_step(a, build_step("dewow", window_ns=10.0))
    session.append_step(a, build_step("time_cutoff", end_ns=end_a))
    session.append_step(b, build_step("time_cutoff", end_ns=end_b))
    session.append_step(b, build_step("dewow", window_ns=10.0))
    dock.set_selected_step(1)
    assert dock.view.cutoff_ns == pytest.approx(end_a)
    session.open_line(b)
    assert dock.view.cutoff_ns is None
    assert dock.image.rg.n_samples == 100
    dock.set_selected_step(0)
    assert dock.view.cutoff_ns == pytest.approx(end_b)


# ---- the display limit is measured with the gain curves switched off (#6) ----

FLAT = [[-11.0, 0.0], [99.0, 0.0]]
DEEP = [[-11.0, 0.0], [40.0, 0.0], [99.0, 30.0]]


def _clip(dock):
    return PercentileClip(dock.percentile).limit


def test_without_a_gain_curve_the_limit_is_taken_from_what_is_shown(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow"))
    result = session.stack_for(key).result()
    assert dock.image.reference is result
    assert dock.image.limit == _clip(dock)(result.data)


def test_a_gain_curve_edit_never_moves_the_limit(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("gain_curve", points=FLAT))
    limit0 = dock.image.limit
    session.replace_step(key, 1, build_step("gain_curve", points=DEEP))
    assert dock.image.limit == limit0
    # today's rule (the percentile of what is shown) would have moved it
    assert _clip(dock)(session.stack_for(key).result().data) > limit0


def test_a_curve_edit_reuses_the_cached_reference(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("gain_curve", points=FLAT))
    before = dock.image.reference
    session.replace_step(key, 1, build_step("gain_curve", points=DEEP))
    assert dock.image.reference is before


def test_agc_after_a_gain_curve_does_not_blank_the_profile(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("gain_curve", points=[[-11.0, 12.0], [99.0, 12.0]]))
    session.append_step(key, build_step("gain_agc"))
    stack = session.stack_for(key)
    clip = _clip(dock)
    assert dock.image.limit == clip(stack.result_bypassing(0).data)
    # the hazard is real: the unprocessed record's scale would blank the AGC output
    assert clip(stack.source.data) > 1e3 * dock.image.limit
    assert np.std(to_index8(stack.result().data, dock.image.limit)) > 20


def test_two_gain_curves_are_both_left_out_of_the_scale(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    # Row 0 has a real gain (FLAT is 0 dB, a numerical no-op that would let
    # an implementation bypassing only the last curve pass).
    session.append_step(key, build_step("gain_curve", points=[[-11.0, 12.0], [99.0, 12.0]]))
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("gain_curve", points=DEEP))
    stack = session.stack_for(key)
    clip = _clip(dock)
    assert clip(stack.result_bypassing(0, 2).data) != clip(stack.result_bypassing(2).data)
    assert dock.image.limit == clip(stack.result_bypassing(0, 2).data)


def test_a_disabled_gain_curve_leaves_todays_scale(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("gain_curve", points=DEEP))
    session.set_step_enabled(key, 1, False)
    assert dock.image.reference is session.stack_for(key).result()


def test_the_difference_view_keeps_the_scale_of_what_is_shown(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("gain_curve", points=DEEP))
    dock.set_difference_index(1)
    stack = session.stack_for(key)
    assert dock.image.limit == _clip(dock)(stack.difference(1).data)


@pytest.mark.parametrize("with_curve", [True, False], ids=["curve", "no curve"])
def test_selecting_the_cutoff_row_never_changes_the_brightness(opened, with_curve):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow"))
    if with_curve:
        session.append_step(key, build_step("gain_curve", points=DEEP))
    session.append_step(key, build_step("time_cutoff", end_ns=50.0))
    cutoff_row = 2 if with_curve else 1
    stack = session.stack_for(key)
    limit0 = dock.image.limit
    dock.set_selected_step(cutoff_row)
    assert dock.image.rg.n_samples > stack.result().n_samples  # the bypass is shown
    assert dock.image.limit == limit0
    dock.set_selected_step(-1)
    assert dock.image.limit == limit0


def test_a_preview_takes_its_scale_from_its_own_gain_curve(opened, tmp_path):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    p2 = synthetic_dzt(tmp_path / "raw", "FILE__002.DZT", n_traces=240)
    line2 = Line.open(p2, GridPlacement("A", "y", 1.0, 0.0, -1, "FILE__002"))
    session.add_lines([line2])
    (key2,) = set(session.keys()) - {key}
    session.set_profiles(key2, line2.load())
    session.append_step(key2, build_step("gain_curve", points=DEEP))
    session.set_preview(key2, 5)
    expected = _clip(dock)(session.stack_for(key2).result_bypassing(0).data)
    assert dock.image.limit == expected


def test_the_percentile_slider_says_what_it_measures(opened):
    _, dock, _, _ = opened
    assert "gain curve" in dock.percentile_slider.toolTip()


@needs_real_data
def test_a_real_line_balanced_by_a_gain_curve_keeps_its_limit(bare):
    session, dock, tmp_path = bare
    session.new_site(tmp_path)
    session.add_grid(GRID)
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0, 0.0, -1, "REAL"))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    session.append_step(key, build_step("time_zero", mode="first_break", threshold=0.25))
    session.append_step(key, build_step("dewow", window_ns=4.0))
    session.append_step(key, build_step("background_sliding", window_traces=200))
    stack = session.stack_for(key)
    t0 = stack.intermediate(2).t0_ns
    points = [[t0, 0.0], [50.0, 40.0], [stack.intermediate(2).t0_ns + 1e4, 40.0]]
    session.append_step(key, build_step("gain_curve", points=points))
    limit0 = dock.image.limit
    expected = _clip(dock)(stack.intermediate(2).data)
    assert limit0 == expected
    raised = [[t, db + 6.0] for t, db in points]
    session.replace_step(key, 3, build_step("gain_curve", points=raised))
    assert dock.image.limit == limit0


@needs_real_data
def test_raising_only_the_deep_point_leaves_the_shallow_pixels_alone(bare):
    session, dock, tmp_path = bare
    session.new_site(tmp_path)
    session.add_grid(GRID)
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0, 0.0, -1, "REAL"))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    session.append_step(key, build_step("time_zero", mode="first_break", threshold=0.25))
    session.append_step(key, build_step("dewow", window_ns=4.0))
    session.append_step(key, build_step("background_sliding", window_traces=200))
    stack = session.stack_for(key)
    t0 = stack.intermediate(2).t0_ns
    dt = stack.intermediate(2).dt_ns
    t_end = t0 + 1e4
    points = [[t0, 0.0], [50.0, 0.0], [t_end, 40.0]]
    session.append_step(key, build_step("gain_curve", points=points))
    k = int((50.0 - t0) / dt)  # rows before the curve leaves 0 dB
    assert k > 0
    limit0 = dock.image.limit
    shallow0 = to_index8(stack.result().data[:k], limit0)
    session.replace_step(key, 3, build_step("gain_curve", points=[*points[:2], [t_end, 52.0]]))
    assert dock.image.limit == limit0
    np.testing.assert_array_equal(to_index8(stack.result().data[:k], dock.image.limit), shallow0)


# ---- one ruler per grid, and the window held in metres (#67) -------------------


def _add_line(session, name, placement, **kw):
    p = synthetic_dzt(session.root / "raw", f"{name}.DZT", **{"n_traces": 300, **kw})
    line = Line.open(p, placement)
    session.add_lines([line])
    key = next(k for k in session.keys() if session.line_for_key(k) is line)  # noqa: SIM118 -- SiteSession.keys(), not a dict
    return key, line


def _forward(session, name="FILE__FWD", **kw):
    return _add_line(session, name, GridPlacement("A", "y", 0.5, 0.0, 1, name), **kw)


def _x_of_metre(dock, line, metres):
    return dock.view.transform.x_of_trace(trace_units_at(line.distance_along(), metres))


def _zoom(dock):
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    t = dock.view.transform
    return dock.view.window_m(), (t.time_lo, t.time_hi)


def test_a_reversed_line_is_mirrored_against_its_grid_ruler(opened):
    session, dock, key, line = opened
    v = dock.view
    assert (v.ruler.grid_id, v.ruler.axis, v.ruler.hi_m) == ("A", "y", 11.0)
    assert v.ruler.lo_m == pytest.approx(
        -239 / 60 - 1 / 120
    )  # the line runs past the grid's 0 edge
    assert v.transform.mirrored


def test_the_same_metre_is_at_the_same_pixel_on_neighbouring_lines(opened):
    session, dock, key, line = opened
    fkey, fwd = _forward(session)
    before = _x_of_metre(dock, line, 2.0)
    session.open_line(fkey)
    # the ruler widened when the reversed line was added, so both see the same one
    assert abs(_x_of_metre(dock, fwd, 2.0) - before) < 0.5


def test_zoom_is_held_in_metres_when_the_next_line_opens(opened):
    session, dock, key, line = opened
    fkey, _ = _forward(session)
    m, t = _zoom(dock)
    session.open_line(fkey)
    assert dock.view.window_m() == pytest.approx(m)
    tr = dock.view.transform
    assert (tr.time_lo, tr.time_hi) == pytest.approx(t)
    assert not tr.mirrored


def test_the_hold_survives_a_preview_and_its_end(opened):
    session, dock, key, line = opened
    fkey, _ = _forward(session)
    m, _t = _zoom(dock)
    session.set_preview(fkey, 5)
    assert dock.view.window_m() == pytest.approx(m)
    session.clear_preview()
    assert dock.view.window_m() == pytest.approx(m)
    assert dock.view.transform.mirrored


def test_a_header_only_preview_is_ruled_and_held_through_its_load(opened):
    session, dock, key, line = opened
    fkey, fwd = _forward(session)
    m, _t = _zoom(dock)
    session.set_preview(fkey, 5)
    assert dock.view.ruler is not None
    assert dock.view.window_m() == pytest.approx(m)
    session.set_profiles(fkey, fwd.load())
    assert dock.view.window_m() == pytest.approx(m)


def test_a_cross_line_or_another_grid_starts_at_fit(opened):
    session, dock, key, line = opened
    _zoom(dock)
    xkey, _ = _add_line(session, "FILE__X", GridPlacement("A", "x", 0.5, 0.0, 1, "FILE__X"))
    session.open_line(xkey)
    assert dock.view.ruler.key == ("A", "x")
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == t.trace_bounds
    session.open_line(key)
    _zoom(dock)
    session.add_grid(dataclasses.replace(GRID, id="B"))
    bkey, _ = _add_line(session, "FILE__B", GridPlacement("B", "y", 0.5, 0.0, 1, "FILE__B"))
    session.open_line(bkey)
    assert dock.view.ruler.key == ("B", "y")
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == t.trace_bounds


def test_the_hold_is_in_metres_across_different_trace_spacings(opened):
    session, dock, key, line = opened
    fkey, _ = _forward(session, traces_per_metre=50.0)
    m, _t = _zoom(dock)
    t0 = dock.view.transform
    session.open_line(fkey)
    t1 = dock.view.transform
    assert dock.view.window_m() == pytest.approx(m, abs=0.05)
    assert t1.trace_hi - t1.trace_lo != pytest.approx(t0.trace_hi - t0.trace_lo)


def test_a_line_without_distance_neither_mirrors_nor_holds(opened, message_log):
    session, dock, key, line = opened
    m, _t = _zoom(dock)
    tkey, tline = _add_line(
        session,
        "FILE__TIME",
        GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__TIME"),
        traces_per_metre=0.0,
    )
    session.open_line(tkey)
    t = dock.view.transform
    assert dock.view.ruler is None and not t.mirrored
    assert (t.trace_lo, t.trace_hi) == (0.0, float(tline.n_traces))
    session.open_line(key)
    # the window held on the ruler comes back; nothing was carried onto the
    # unruled line and nothing is logged
    assert dock.view.window_m() == pytest.approx(m)
    assert message_log == []


def test_the_difference_view_keeps_the_mirror_and_the_window(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("dewow", window_ns=4.0))
    m, _t = _zoom(dock)
    dock.set_difference_index(0)
    assert dock.view.transform.mirrored
    assert dock.view.window_m() == pytest.approx(m)
    dock.set_difference_index(-1)
    assert dock.view.transform.mirrored
    assert dock.view.window_m() == pytest.approx(m)


def test_a_grid_resize_moves_fit_without_reopening_the_line(opened):
    session, dock, key, line = opened
    session.replace_grid(dataclasses.replace(GRID, size_y=20.0))
    assert dock.view.ruler.hi_m == pytest.approx(20.0)
    dock.fit_button.click()
    assert dock.view.window_m()[1] == pytest.approx(20.0)


@needs_real_data
def test_real_zigzag_lines_keep_a_metre_in_place_across_the_sweep(bare):
    session, dock, tmp_path = bare
    session.new_site(tmp_path)
    session.add_grid(Grid("R", (0.0, 0.0), 0.0, 20.0, 11.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(10):
        placement = (
            GridPlacement("R", "y", 0.5 * i, 0.0, 1, f"R{i}")
            if i % 2 == 0
            else GridPlacement("R", "y", 0.5 * i, 11.0, -1, f"R{i}")
        )
        lines.append(Line.open(REAL_DZT[i % len(REAL_DZT)], placement))
    session.add_lines(lines)
    keys = session.keys()
    session.set_profiles(keys[0], lines[0].load())
    session.open_line(keys[0])
    x0 = _x_of_metre(dock, lines[0], 5.0)
    for k, ln in zip(keys[1:], lines[1:], strict=True):
        session.set_profiles(k, ln.load())
        session.set_preview(k, 3)
        assert _x_of_metre(dock, ln, 5.0) == pytest.approx(x0, abs=0.5)
    session.clear_preview()
    dock.view.set_window_m(4.5, 5.5, dock.view.transform.time_lo, dock.view.transform.time_hi)
    m = dock.view.window_m()
    x0 = _x_of_metre(dock, lines[0], 5.0)
    for k, ln in zip(keys[1:], lines[1:], strict=True):
        session.set_preview(k, 3)
        assert _x_of_metre(dock, ln, 5.0) == pytest.approx(x0, abs=0.5)
        assert dock.view.window_m() == pytest.approx(m)


@pytest.mark.parametrize("zoomed", [False, True])
def test_a_same_shape_unruled_line_after_a_ruled_one_starts_clean(opened, zoomed):
    session, dock, key, line = opened
    if zoomed:
        _zoom(dock)
    tkey, tline = _add_line(
        session,
        "FILE__T240",
        GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__T240"),
        n_traces=240,
        traces_per_metre=0.0,
    )
    session.open_line(tkey)
    t = dock.view.transform
    assert dock.view.ruler is None and not t.mirrored and t.bounds is None
    assert (t.trace_lo, t.trace_hi) == (0.0, 240.0)


def test_two_same_shape_unruled_lines_keep_the_window_between_them(opened):
    session, dock, key, line = opened
    ka, _ = _add_line(
        session,
        "T1",
        GridPlacement("A", "y", 0.0, 0.0, 1, "T1"),
        n_traces=240,
        traces_per_metre=0.0,
    )
    kb, _ = _add_line(
        session,
        "T2",
        GridPlacement("A", "y", 0.0, 0.0, 1, "T2"),
        n_traces=240,
        traces_per_metre=0.0,
    )
    session.open_line(ka)
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    zoomed = dock.view.transform
    session.open_line(kb)
    assert (dock.view.transform.trace_lo, dock.view.transform.trace_hi) == (
        zoomed.trace_lo,
        zoomed.trace_hi,
    )
    assert dock.view.transform.trace_hi - dock.view.transform.trace_lo < 240


def test_the_hold_comes_back_after_a_glance_at_a_cross_line(opened):
    session, dock, key, line = opened
    fkey, _ = _forward(session)
    xkey, _ = _add_line(session, "FILE__X", GridPlacement("A", "x", 0.5, 0.0, 1, "FILE__X"))
    m, t = _zoom(dock)
    session.set_preview(xkey, 5)
    tr = dock.view.transform
    assert (tr.trace_lo, tr.trace_hi) == tr.trace_bounds  # a cross-line starts at Fit
    session.clear_preview()
    assert dock.view.window_m() == pytest.approx(m)
    session.set_preview(xkey, 5)
    session.set_preview(fkey, 5)
    assert dock.view.window_m() == pytest.approx(m)
    tr = dock.view.transform
    assert (tr.time_lo, tr.time_hi) == pytest.approx(t)


def test_an_import_past_the_ruler_edge_widens_it_without_reopening(opened):
    session, dock, key, line = opened
    assert dock.view.ruler.hi_m == pytest.approx(11.0)
    # lines_changed alone (no grid edit): 900 traces from 10 m run to 25 m
    _add_line(
        session, "FILE__LONG", GridPlacement("A", "y", 0.5, 10.0, 1, "FILE__LONG"), n_traces=900
    )
    assert dock.view.ruler.hi_m == pytest.approx(10.0 + 899 / 60 + 1 / 120)


# ---- a whole-record or whole-ruler view is held as whole (#67) -------------------


def _whole_time(dock, rg_end=None):
    t = dock.view.transform
    return t.time_lo <= t.t0_ns + t.dt_ns / 2 and t.time_hi >= t.t_end - t.dt_ns / 2


def _cutoff_at_200(session, dock, key, line):
    session.set_profiles(key, line.load())
    rg = session.stack_for(key).source
    end = rg.t0_ns + 200 * rg.dt_ns
    session.append_step(key, build_step("time_cutoff", end_ns=end))
    return end


def test_reselecting_the_cutoff_row_shows_the_whole_bypassed_record(opened):
    session, dock, key, line = opened
    end = _cutoff_at_200(session, dock, key, line)
    assert dock.view.transform.t_end == pytest.approx(end, abs=1.0)
    dock.set_selected_step(0)
    t = dock.view.transform
    assert t.n_samples == 512 and _whole_time(dock)


def test_removing_the_cutoff_step_shows_the_whole_record(opened):
    session, dock, key, line = opened
    _cutoff_at_200(session, dock, key, line)
    session.remove_step(key, 0)
    assert dock.view.transform.n_samples == 512 and _whole_time(dock)


def test_a_horizontal_zoom_is_held_while_the_time_axis_stays_whole(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("time_zero", mode="sample", sample=40))
    assert dock.view.transform.n_samples == 472
    t = dock.view.transform
    dock.view.transform = t.with_window(t.trace_lo + 100, t.trace_lo + 300, t.time_lo, t.time_hi)
    m = dock.view.window_m()
    session.set_step_enabled(key, 0, False)
    assert dock.view.transform.n_samples == 512
    assert _whole_time(dock)
    assert dock.view.window_m() == pytest.approx(m)


def test_a_longer_record_after_a_shorter_one_shows_its_full_record(opened):
    session, dock, key, line = opened
    short = _add_line(session, "SHORT", GridPlacement("A", "y", 0.5, 0.0, 1, "SHORT"), n_traces=300)
    session.set_profiles(short[0], short[1].load())
    session.append_step(short[0], build_step("time_zero", mode="sample", sample=40))
    session.open_line(short[0])
    assert dock.view.transform.n_samples == 472
    session.set_profiles(key, line.load())
    session.open_line(key)
    assert dock.view.transform.n_samples == 512 and _whole_time(dock)


def test_a_view_at_fit_stays_at_fit_when_the_ruler_grows(opened):
    session, dock, key, line = opened
    session.replace_grid(dataclasses.replace(GRID, size_y=20.0))
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx(t.trace_bounds)
    assert dock.view.window_m() == pytest.approx((dock.view.ruler.lo_m, 20.0))


def test_a_time_zoom_is_still_held_across_lines(opened):
    session, dock, key, line = opened
    fkey, _ = _forward(session)
    t = dock.view.transform
    mid = (t.time_lo + t.time_hi) / 2
    dock.view.transform = t.with_window(t.trace_lo, t.trace_hi, t.time_lo, mid)
    held = (dock.view.transform.time_lo, dock.view.transform.time_hi)
    session.open_line(fkey)
    n = dock.view.transform
    assert (n.time_lo, n.time_hi) == pytest.approx(held)


def test_a_same_shape_unruled_pair_needs_the_same_trace_count(opened):
    session, dock, key, line = opened
    ka, _ = _add_line(
        session,
        "U1",
        GridPlacement("A", "y", 0.0, 0.0, 1, "U1"),
        n_traces=240,
        traces_per_metre=0.0,
    )
    kb, _ = _add_line(
        session,
        "U2",
        GridPlacement("A", "y", 0.0, 0.0, 1, "U2"),
        n_traces=300,
        traces_per_metre=0.0,
    )
    session.open_line(ka)
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    session.open_line(kb)
    t = dock.view.transform
    assert t.n_traces == 300
    assert (t.trace_lo, t.trace_hi) == (0.0, 300.0)


def test_a_removed_line_files_its_window_for_the_next_one(opened):
    session, dock, key, line = opened
    bkey, _ = _forward(session, "FILE__B")
    ckey, _ = _forward(session, "FILE__C")
    _zoom(dock)  # W1 on A
    session.open_line(bkey)
    r = dock.view.image_rect()
    dock.view.zoom_at(2.0, r.width() / 4, r.height() / 2)  # W2 on B
    w2 = dock.view.window_m()
    session.remove_line(bkey)
    session.open_line(ckey)
    assert dock.view.window_m() == pytest.approx(w2)


def test_the_held_windows_are_forgotten_when_the_site_closes(opened, tmp_path):
    session, dock, key, line = opened
    _zoom(dock)
    session.close_site()
    other = tmp_path / "second"
    other.mkdir()
    session.new_site(other)
    session.add_grid(GRID)
    nkey, _ = _add_line(session, "FILE__N", GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__N"))
    session.open_line(nkey)
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx(t.trace_bounds)


def test_a_line_edit_reaches_the_open_profile_even_when_its_ruler_is_unchanged(opened):
    session, dock, key, line = opened
    assert "wall line" not in dock.windowTitle()
    session.edit_lines([LineEdit(key, line.placement, label="wall line")])
    assert "wall line" in dock.windowTitle()


def test_a_time_zero_that_crops_nothing_still_moves_the_axis(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    assert dock.view.transform.t0_ns == pytest.approx(-11.086, abs=1e-3)
    session.append_step(key, build_step("time_zero", mode="sample", sample=0))
    assert dock.view.transform.t0_ns == 0.0


def test_picks_stay_on_their_sample_when_time_zero_is_added(dock_with_picks):
    dock, session, layers, keys = dock_with_picks
    key = keys[0]
    session.set_profiles(key, session.line_for_key(key).load())
    session.add_pick(key, 30, 20.0)  # radar clock: no step yet
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))
    zero = dock.shown_zero_ns()
    assert zero != 0.0
    assert dock.view._picks == [(30, pytest.approx(20.0 - zero))]


def test_a_relabelled_axis_with_no_ruler_is_not_put_back(opened):
    session, dock, key, line = opened
    dock._set_axes_holding("", 100, 200, -11.0, 0.2, None)
    before = dock.view.transform
    dock._set_axes_holding("", 100, 200, 0.0, 0.2, None)
    assert dock.view.transform is not before
    assert dock.view.transform.t0_ns == 0.0


# ---- a line whose steps can't run says so (#197) -------------------------


def _bandpass_past_nyquist():
    return build_step("bandpass", low_mhz=100.0, high_mhz=90_000.0)


@pytest.fixture
def two_lines(bare):
    """Lines A (open, rendering) and B, both with their samples loaded."""
    session, dock, tmp_path = bare
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i, label in enumerate(("FILE__001", "FILE__002")):
        p = synthetic_dzt(tmp_path / "raw", f"{label}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, -1, label)))
    session.add_lines(lines)
    key_a, key_b = session.keys()
    for key, line in zip((key_a, key_b), lines, strict=True):
        session.set_profiles(key, line.load())
    session.open_line(key_a)
    return session, dock, key_a, key_b


def test_opening_a_line_whose_steps_refuse_shows_why_not_the_last_picture(two_lines):
    session, dock, key_a, key_b = two_lines
    assert dock.view._image is not None
    session.append_step(key_b, _bandpass_past_nyquist())
    session.open_line(key_b)
    assert dock.view._image is None
    assert dock.view._message == STEPS_REFUSED_TEXT


def test_a_preview_of_a_line_whose_steps_refuse_says_so(two_lines):
    session, dock, key_a, key_b = two_lines
    session.append_step(key_b, _bandpass_past_nyquist())
    session.set_preview(key_b, 3)
    assert dock.view._image is None
    assert dock.view._message == PREVIEW_STEPS_REFUSED_TEXT.format(name="FILE__002")


def test_back_from_a_preview_to_a_refusing_line_shows_why(two_lines):
    session, dock, key_a, key_b = two_lines
    session.set_preview(key_b, 3)
    session.append_step(key_a, _bandpass_past_nyquist())
    session.set_preview(None)
    assert dock.view._image is None
    assert dock.view._message == STEPS_REFUSED_TEXT


def test_a_bad_edit_on_the_open_line_keeps_its_last_picture(two_lines):
    """Guard: a refusing edit to the line being worked on leaves its last
    picture up (the toast says why). Fails if `_show_steps_refused` also runs
    on `stack_changed`, which would blank the picture on every bad keystroke."""
    session, dock, key_a, _ = two_lines
    before = dock.view._image
    assert before is not None
    session.append_step(key_a, _bandpass_past_nyquist())
    assert dock.view._image is before


# ---- M17a P14: a GPS line in the profile ----------------------------------------------


def _open_gps(bare, track=None, shift=0.3, n_traces=200):
    from plugin_testing import CRS, LAT0, LON0, M_PER_DEG, gps_line, open_gps, synthetic_gps_dzt

    session, dock, tmp_path = bare
    session.new_site(tmp_path)
    session.set_site_crs(CRS)
    if track is None:
        line = gps_line(tmp_path / "raw", "FILE__001.DZT", {25: 4, 175: 4}, n_traces, shift)
    else:
        path = synthetic_gps_dzt(
            tmp_path / "raw",
            "FILE__001.DZT",
            [(t, LAT0 + m / M_PER_DEG, LON0, 4) for t, m in track],
            n_traces=n_traces,
            traces_per_metre=10.0,
        )
        line = open_gps(path, travel_shift=shift)
    session.add_lines([line])
    key = session.keys()[0]
    session.open_line(key)
    return session, dock, key, line


def test_a_gps_line_opens_with_walked_distance_and_no_ruler(bare):
    session, dock, key, line = _open_gps(bare, shift=0.3)
    distance = dock.view._distance
    assert distance is not None
    # the bottom axis is the walked distance: 199 traces at 0.1 m, moved on by the destagger
    assert distance[0] == pytest.approx(0.3)
    # (to 0.05 m: the projection scales the made-up 0.1 m fix spacing a little)
    assert distance[-1] == pytest.approx(19.9 + 0.3, abs=0.05)
    assert np.allclose(distance, line.distance_along())
    # a line with no grid has no shared ruler to rule against
    assert dock._ruler_for(line, distance) is None
    assert dock.view.ruler is None


def test_the_velocity_fit_on_a_gps_line_measures_along_the_walked_distance(bare):
    # The fixes put the middle of the line at 0.12 m a trace; the start run, where the
    # wheel alone places the traces, is 0.1 m a trace. The fit's x is the walked distance
    # at each clicked trace (decision 11's interim, until M17b), not trace x wheel spacing.
    session, dock, key, line = _open_gps(
        bare, track=[(50, 5.0), (150, 5.0 + 12.0)], shift=0.0, n_traces=200
    )
    clicked = [(60, 20.0), (100, 12.0), (140, 20.0)]
    dock._velocity_points = list(clicked)
    x_m, _ = dock.velocity_points_in_metres(0.0)
    walked = line.distance_along()
    assert list(x_m) == pytest.approx([walked[t] for t, _ in clicked])
    wheel = walked[1] - walked[0]
    assert wheel == pytest.approx(0.1)
    # the middle really is 0.12 m a trace, so trace x wheel spacing would put the points elsewhere
    assert x_m[2] - x_m[0] != pytest.approx((140 - 60) * wheel)
    assert x_m[2] - x_m[0] == pytest.approx(80 * 0.12, abs=0.05)


def test_the_slice_band_button_hides_and_shows_the_band_keeping_its_window(opened):
    session, dock, key, line = opened
    dock.set_slice_band(18.0, 22.0)
    shown = dock.view._slice_band
    assert shown is not None
    dock.slice_band_button.setChecked(False)
    assert dock.view._slice_band is None
    assert dock._slice_band == (18.0, 22.0)  # the window is kept
    dock.slice_band_button.setChecked(True)
    assert dock.view._slice_band == pytest.approx(shown)


def test_a_window_change_while_hidden_is_drawn_when_shown_again(opened):
    session, dock, key, line = opened
    dock.set_slice_band(18.0, 22.0)
    shown = dock.view._slice_band
    dock.slice_band_button.setChecked(False)
    dock.set_slice_band(30.0, 34.0)
    assert dock.view._slice_band is None
    dock.slice_band_button.setChecked(True)
    lo, hi = dock.view._slice_band
    assert hi - lo == pytest.approx(4.0)
    assert lo - shown[0] == pytest.approx(12.0)  # the new window, on the shown clock


def test_the_slice_band_choice_survives_a_new_dock(opened):
    session, dock, key, line = opened
    dock.slice_band_button.setChecked(False)
    other = ProfileDock(session)
    try:
        assert not other.slice_band_button.isChecked()
    finally:
        other.deleteLater()


def test_the_slice_band_is_a_show_slice_band_checkbox_left_of_the_fit_group(opened):
    from qgis.PyQt.QtWidgets import QCheckBox

    session, dock, key, line = opened
    dock.resize(1361, 448)
    QTest.qWait(50)
    box = dock.slice_band_button
    assert isinstance(box, QCheckBox)
    assert box.text() == "Show slice band"
    assert box.x() < dock.fit_button.x()
    assert box.x() < dock.one_to_one_button.x()


def test_the_slice_band_button_is_greyed_until_there_is_a_window(opened):
    session, dock, key, line = opened
    assert not dock.slice_band_button.isEnabled()
    dock.set_slice_band(18.0, 22.0)
    assert dock.slice_band_button.isEnabled()
    dock.slice_band_button.setChecked(False)
    dock.clear_slice_band()
    assert not dock.slice_band_button.isEnabled()
    assert not dock.slice_band_button.isChecked()  # greying keeps the choice


def test_a_remembered_false_comes_back_unchecked(opened):
    session, dock, key, line = opened
    profile_dock.profile_settings().setValue(SLICE_BAND_KEY, "false")  # an INI file after a restart
    other = ProfileDock(session)
    try:
        assert not other.slice_band_button.isChecked()
    finally:
        other.deleteLater()


def test_a_bad_remembered_band_choice_is_overwritten_by_the_next_choice(opened):
    session, dock, key, line = opened
    profile_dock.profile_settings().setValue(SLICE_BAND_KEY, "maybe")
    other = ProfileDock(session)
    try:
        other.slice_band_button.setChecked(False)
        assert profile_dock.profile_settings().value(SLICE_BAND_KEY) in (False, "false")
    finally:
        other.deleteLater()


def test_a_bad_remembered_band_choice_falls_back_to_shown(opened):
    session, dock, key, line = opened
    profile_dock.profile_settings().setValue(SLICE_BAND_KEY, "maybe")
    other = ProfileDock(session)
    try:
        assert other.slice_band_button.isChecked()
    finally:
        other.deleteLater()


@pytest.fixture
def plugin(fake_iface, answer_modal, tmp_path):
    import nsgeo_qgis
    from qgis.core import QgsProject, QgsSettings

    QgsProject.instance().clear()
    QgsSettings().setValue("nsgeo/slicesDockTabified", False)
    QgsSettings().setValue("nsgeo/surfacesDockTabified", False)
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    session = plugin.session
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, -1, "FILE__001"))])
    session.open_line(session.keys()[0])
    yield plugin
    answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)
    plugin.unload()
    QgsProject.instance().clear()
    QgsSettings().setValue("nsgeo/slicesDockTabified", False)
    QgsSettings().setValue("nsgeo/surfacesDockTabified", False)


def test_closing_the_slices_panel_leaves_the_band(plugin):
    plugin.slices_dock.window_changed.emit(18.0, 22.0)
    first = plugin.profile_dock.view._slice_band
    plugin.slices_dock.close()
    assert plugin.profile_dock.view._slice_band == pytest.approx(first)
    plugin.slices_dock.window_changed.emit(19.0, 23.0)
    band = plugin.profile_dock.view._slice_band
    assert band is not None
    assert band[1] - band[0] == pytest.approx(4.0)
    assert band[0] - first[0] == pytest.approx(1.0)


def _break_velocity(session, monkeypatch, exc):
    def boom(k):
        raise exc

    monkeypatch.setattr(session, "resolved_velocity", boom)


def test_a_failed_velocity_refresh_clears_the_depth_axis(opened, monkeypatch):
    session, dock, key, line = opened
    assert dock.view.depth_tick_labels()  # GRID's velocity is shown
    _break_velocity(session, monkeypatch, RuntimeError("boom"))
    dock._refresh_velocity()
    assert dock.view.depth_tick_labels() == []
    assert dock.velocity_label.text() == ""


def test_a_missing_velocity_on_a_line_clears_the_depth_axis(opened, monkeypatch):
    session, dock, key, line = opened
    assert dock.view.depth_tick_labels()
    _break_velocity(session, monkeypatch, KeyError("no velocity"))
    dock._refresh_velocity()
    assert dock.view.depth_tick_labels() == []
    assert dock.velocity_label.text() == ""


def test_the_fit_menu_shows_its_tooltips(opened):
    session, dock, key, line = opened
    assert dock.fit_menu.toolTipsVisible()


def test_fit_width_and_fit_height_from_the_menu(opened):
    session, dock, key, line = opened
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    z = dock.view.transform
    dock.fit_width_action.trigger()
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx(t.trace_bounds)
    assert (t.time_lo, t.time_hi) == pytest.approx((z.time_lo, z.time_hi))
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    z = dock.view.transform
    dock.fit_height_action.trigger()
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx((z.trace_lo, z.trace_hi))
    assert (t.time_lo, t.time_hi) == pytest.approx((t.t0_ns, t.t_end))


def test_the_fit_button_repeats_the_last_pick(opened):
    session, dock, key, line = opened
    dock.fit_width_action.trigger()
    # QAction.trigger() on a menu action emits the menu's triggered signal.
    assert dock.fit_button.text() == "Fit width"
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    z = dock.view.transform
    dock.fit_button.click()
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx(t.trace_bounds)
    assert (t.time_lo, t.time_hi) == pytest.approx((z.time_lo, z.time_hi))


def test_a_new_dock_starts_with_fit(opened):
    session, dock, key, line = opened
    dock.fit_height_action.trigger()
    other = ProfileDock(session)
    try:
        assert other.fit_button.text() == "Fit"
    finally:
        other.deleteLater()


def test_the_toolbar_fits_the_users_panel_in_the_worst_case(opened):
    # 1361 px wide, a long Difference label and a velocity label naming its fits.
    session, dock, key, line = opened
    # The widest Fit button text ("Fit height") is picked first.
    dock.fit_height_action.trigger()
    dock.resize(1361, 448)
    full = "v = 0.100 m/ns (Grid A, average of 6 fits)"
    dock.difference_label.setText("Difference: Background removal (sliding)")
    dock.velocity_label.setText(full)
    QTest.qWait(50)
    assert dock.widget().minimumSizeHint().width() <= 1361
    for b in (dock.fit_button, dock.one_to_one_button, dock.slice_band_button):
        assert b.geometry().right() < dock.widget().width()
    # `ElidedLabel.text()` is always the full text, so ask the plain QLabel for
    # what it paints: the whole text when there is room, else the tooltip.
    painted = QLabel.text(dock.velocity_label)
    assert painted == full or dock.velocity_label.toolTip() == full


def test_picking_a_fit_does_not_move_the_buttons_after_it(opened):
    session, dock, key, line = opened
    dock.resize(1361, 448)
    QTest.qWait(50)
    # The band checkbox sits left of Fit now; the velocity label is what follows 1:1.
    before = (dock.fit_button.width(), dock.one_to_one_button.x(), dock.velocity_label.x())
    for action in (dock.fit_width_action, dock.fit_height_action, dock.fit_all_action):
        action.trigger()
        QTest.qWait(50)
        assert (
            dock.fit_button.width(),
            dock.one_to_one_button.x(),
            dock.velocity_label.x(),
        ) == before


def test_the_axis_menu_sets_a_unit_and_remembers_it(opened):
    session, dock, key, line = opened
    dock._on_axis_menu_requested("left", QPoint(0, 0))
    act = next(a for a in dock.axis_menu.actions() if a.data() == "sample")
    act.trigger()
    assert dock.view.axis_units == ("sample", "m")
    other = ProfileDock(session)
    try:
        assert other.view.axis_units == ("sample", "m")
    finally:
        other.deleteLater()
    dock.axis_menu.hide()


def test_the_axis_menu_names_its_three_units(opened):
    session, dock, key, line = opened
    dock._on_axis_menu_requested("right", QPoint(0, 0))
    try:
        assert [(a.text(), a.data()) for a in dock.axis_menu.actions()] == [
            ("Time (ns)", "ns"),
            ("Samples", "sample"),
            ("Depth (m)", "m"),
        ]
        dock.axis_menu.actions()[0].trigger()
        assert dock.view.axis_units == ("ns", "ns")
    finally:
        dock.axis_menu.hide()


def test_depth_is_greyed_in_the_menu_without_a_velocity(opened, monkeypatch):
    session, dock, key, line = opened
    _break_velocity(session, monkeypatch, KeyError("no velocity"))
    dock._refresh_velocity()
    dock._on_axis_menu_requested("left", QPoint(0, 0))
    try:
        depth = next(a for a in dock.axis_menu.actions() if a.data() == "m")
        assert dock.axis_menu.toolTipsVisible()
        assert not depth.isEnabled()
        assert depth.toolTip() == "Depth needs a velocity for this line"
    finally:
        dock.axis_menu.hide()


def test_a_bad_remembered_unit_falls_back_and_is_overwritten(opened):
    session, dock, key, line = opened
    profile_dock.profile_settings().setValue(LEFT_AXIS_KEY, "feet")
    other = ProfileDock(session)
    try:
        assert other.view.axis_units == ("ns", "m")
        other._set_axis_unit("left", "sample")
        assert profile_dock.profile_settings().value(LEFT_AXIS_KEY) == "sample"
    finally:
        other.deleteLater()


# ---- a time zoom survives a clock change on the same line (#163 item 2, spec §4.8) ----


def _radar_window(dock):
    t = dock.view.transform
    return (dock.shown_zero_ns() + t.time_lo, dock.shown_zero_ns() + t.time_hi)


def _zoom_middle(dock):
    t = dock.view.transform
    mid = (t.time_lo + t.time_hi) / 2
    dock.view.transform = t.with_window(t.trace_lo + 20, t.trace_hi - 20, mid - 5.0, mid + 5.0)


def _two_time_zeros(session, dock, key, first, second):
    _zoom_middle(dock)
    before = _radar_window(dock)
    session.append_step(key, build_step("time_zero", **first))
    assert _radar_window(dock) == pytest.approx(before)
    session.replace_step(key, 0, build_step("time_zero", **second))
    assert _radar_window(dock) == pytest.approx(before)


def test_a_time_zoom_survives_adding_time_zero_on_an_unruled_line(opened):
    session, dock, key, line = opened
    k2, l2 = _add_line(
        session, "U1", GridPlacement("A", "y", 0.0, 0.0, 1, "U1"), traces_per_metre=0.0
    )
    session.open_line(k2)
    session.set_profiles(k2, l2.load())
    _two_time_zeros(
        session, dock, k2, dict(mode="sample", sample=20), dict(mode="sample", sample=26)
    )


def test_a_time_zoom_survives_adding_time_zero_on_a_ruled_line(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    _two_time_zeros(
        session, dock, key, dict(mode="sample", sample=20), dict(mode="sample", sample=26)
    )


def test_a_zoom_at_the_top_stays_at_the_top(opened):
    session, dock, key, line = opened
    k2, l2 = _add_line(
        session, "U2", GridPlacement("A", "y", 0.0, 0.0, 1, "U2"), traces_per_metre=0.0
    )
    session.open_line(k2)
    session.set_profiles(k2, l2.load())
    t = dock.view.transform
    dock.view.transform = t.with_window(t.trace_lo, t.trace_hi, t.t0_ns, t.t0_ns + 10.0)
    session.append_step(k2, build_step("time_zero", mode="sample", sample=20))
    n = dock.view.transform
    assert (n.time_lo, n.time_hi) == pytest.approx((n.t0_ns, n.t0_ns + 10.0))


@needs_real_data
def test_a_time_zoom_survives_time_zero_on_the_campus_line(bare):
    session, dock, tmp_path = bare
    session.new_site(tmp_path)
    session.add_grid(GRID)
    path = next(p for p in CAMPUS_LINES if p.name == "FILE__007.DZT")
    line = Line.open(path, GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__007"))
    session.add_lines([line])
    key = session.keys()[0]
    session.open_line(key)
    session.set_profiles(key, line.load())
    _two_time_zeros(session, dock, key, dict(mode="first_break"), dict(mode="sample", sample=52))


@pytest.mark.skipif(not GPS_LINES, reason="needs the with-dzg lines in tests/data/local")
def test_a_time_zoom_survives_time_zero_on_a_gps_line(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    try:
        session.new_site(tmp_path)
        session.add_grid(Grid("G", (500.0, 700.0), 0.0, 30.0, 29.98, "EPSG:32616", 0.5))
        line = Line.open(GPS_LINES[0], GridPlacement("G", "y", 0.25, 0.0, 1, "l0"))
        session.add_lines([line])
        key = session.keys()[0]
        session.open_line(key)
        session.set_profiles(key, line.load())
        _two_time_zeros(
            session, dock, key, dict(mode="sample", sample=20), dict(mode="sample", sample=47)
        )
    finally:
        dock.hide()
        dock.deleteLater()


def test_a_same_line_take_down_then_render_keeps_the_radar_window(opened):
    """`_take_down_picture` can follow a render of the SAME line (a refused
    steps path). The header axes keep the radar times through the clock rule;
    the render after must not read them as a processed clock and move the
    window by the line's zero."""
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("time_zero", mode="sample", sample=60))
    _zoom_middle(dock)
    before = _radar_window(dock)
    dock._show_steps_refused(key, is_preview=False)
    dock._render()
    assert _radar_window(dock) == pytest.approx(before)


def test_a_same_line_take_down_through_rule_1_does_not_set_the_header_flag(opened):
    """The re-review's probe: a line with no steps, a zoom mid-record, a refused
    steps path, then a Time zero appended. The take-down's axes went through
    rule 1 on the same line's picture, so they are not header-only and the
    render after must not move the radar window by the new zero."""
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    _zoom_middle(dock)
    before = _radar_window(dock)
    dock._show_steps_refused(key, is_preview=False)
    session.append_step(key, build_step("time_zero", mode="sample", sample=20))
    assert _radar_window(dock) == pytest.approx(before)


def test_the_fit_button_keeps_its_widest_width_after_a_font_change(opened):
    session, dock, key, line = opened
    f = dock.fit_button.font()
    f.setPointSizeF(f.pointSizeF() * 1.25)
    dock.fit_button.setFont(f)
    QTest.qWait(50)
    xs = set()
    for action in (dock.fit_all_action, dock.fit_width_action, dock.fit_height_action):
        action.trigger()
        QTest.qWait(50)
        xs.add(dock.one_to_one_button.x())
    assert len(xs) == 1


def test_a_held_zoom_does_not_move_when_an_unloaded_lines_samples_arrive(opened):
    """The header-only axes `_take_down_picture` sets are on the radar clock,
    not a clock the user zoomed on: the load that follows must not shift the
    held window by the line's zero (spec §4.8; the module's hold promise)."""
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    kb, lb = _add_line(session, "B1", GridPlacement("A", "y", 0.5, 0.0, 1, "B1"), n_traces=240)
    session.append_step(kb, build_step("time_zero", mode="sample", sample=60))
    _zoom_middle(dock)
    zoomed = (dock.view.transform.time_lo, dock.view.transform.time_hi)
    session.open_line(kb)
    assert dock._shown_radargram is None and dock.shown_zero_ns() == 0.0  # header-only
    session.set_profiles(kb, lb.load())
    assert dock.shown_zero_ns() != 0.0
    first_visit = (dock.view.transform.time_lo, dock.view.transform.time_hi)
    assert first_visit == pytest.approx(zoomed)
    session.open_line(key)
    session.open_line(kb)  # already loaded: no header step
    assert (dock.view.transform.time_lo, dock.view.transform.time_hi) == pytest.approx(first_visit)


# ---- Time zero's row: the bypass on the line's clock, else its input (#158, §4.14 Q3) ----


def _stack_of(session, key, *entries):
    session.set_profiles(key, session.line_for_key(key).load())
    for name, params in entries:
        session.append_step(key, build_step(name, **params))
    return session.stack_for(key)


def test_selecting_time_zero_in_sample_mode_draws_the_bypass_on_the_lines_clock(opened):
    session, dock, key, line = opened
    stack = _stack_of(session, key, ("time_zero", dict(mode="sample", sample=20)), ("dewow", {}))
    src = stack.source
    assert dock.image.rg.data.shape[0] == 492
    dock.set_selected_step(0)
    drawn = dock.image.rg
    # §4.14 Q3: every step but Time zero, on the uncropped record
    np.testing.assert_array_equal(drawn.data, stack.result_bypassing(0).data)
    assert dock.shown_zero_ns() == pytest.approx(stack.zero_ns())
    assert dock.view.transform.t0_ns == pytest.approx(src.t0_ns + (src.zero_ns - stack.zero_ns()))
    assert dock.view.transform.n_samples == src.data.shape[0]
    dock.set_selected_step(-1)
    assert dock.view.transform.n_samples == 492


def test_first_break_mode_selected_draws_the_ordinary_result(opened):
    """Review Focus 3: the guard for today's behaviour; it may pass first."""
    session, dock, key, line = opened
    stack = _stack_of(session, key, ("time_zero", dict(mode="first_break")))
    dock.set_selected_step(0)
    np.testing.assert_array_equal(dock.image.rg.data, stack.result().data)
    assert dock._handle_row() == -1


def test_a_time_zero_that_is_not_first_draws_the_bypass(opened):
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("dewow", {}),
        ("time_zero", dict(mode="sample", sample=20)),
        ("gain_agc", {}),
    )
    dock.set_selected_step(1)
    np.testing.assert_array_equal(dock.image.rg.data, stack.result_bypassing(1).data)
    assert dock.shown_zero_ns() == pytest.approx(stack.zero_ns())


def test_selecting_time_zero_at_the_top_brings_the_cropped_rows_in(opened):
    """A guard for Plan A's top-stays-top rule with the new view: it passes
    without this task's relabel, which only the mid-record test below needs."""
    session, dock, key, line = opened
    _stack_of(session, key, ("time_zero", dict(mode="sample", sample=20)))
    t = dock.view.transform
    dock.view.transform = t.with_window(t.trace_lo, t.trace_hi, t.time_lo, t.time_lo + 10.0)
    before = (dock.view.transform.time_lo, dock.view.transform.time_hi)
    dock.set_selected_step(0)
    t = dock.view.transform
    assert t.time_lo == pytest.approx(t.t0_ns)
    assert t.time_hi - t.time_lo == pytest.approx(10.0)
    dock.set_selected_step(-1)
    t = dock.view.transform
    assert (t.time_lo, t.time_hi) == pytest.approx(before)


def test_selecting_time_zero_mid_record_holds_the_picture_still(opened):
    session, dock, key, line = opened
    _stack_of(session, key, ("time_zero", dict(mode="sample", sample=20)))
    _zoom_middle(dock)
    before = _radar_window(dock)
    labels = (dock.view.transform.time_lo, dock.view.transform.time_hi)
    dock.set_selected_step(0)
    assert _radar_window(dock) == pytest.approx(before)
    # spec §4.11 "elsewhere, nothing moves": the relabel keeps the zero, so the
    # tick labels do not shift either
    t = dock.view.transform
    assert (t.time_lo, t.time_hi) == pytest.approx(labels)
    dock.set_selected_step(-1)
    assert _radar_window(dock) == pytest.approx(before)


def test_a_migrated_line_still_draws_time_zeros_input(opened):
    """§4.11 Q6: the bypass runs `migrate_fk` on a record that starts far
    from zero, which it refuses; the fallback then draws the input."""
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("time_zero", dict(mode="sample", sample=20)),
        ("migrate_fk", dict(velocity_m_ns=0.1)),
    )
    assert stack.source.t0_ns < -2.5  # the bypass would hand migration this record
    errors = []
    dock.error.connect(errors.append)
    dock.set_selected_step(0)
    assert errors == []
    np.testing.assert_array_equal(dock.image.rg.data, stack.source.data)


@needs_real_data
def test_the_campus_line_with_time_zero_selected_starts_49_rows_above_the_line(bare):
    """Spec §4.11's real numbers: FILE__007 seeded at 49 draws a record that
    starts 49 rows (10.6 ns) above the line, on the line's clock."""
    session, dock, tmp_path = bare
    session.new_site(tmp_path)
    session.add_grid(GRID)
    path = next(p for p in CAMPUS_LINES if p.name == "FILE__007.DZT")
    line = Line.open(path, GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__007"))
    session.add_lines([line])
    key = session.keys()[0]
    session.open_line(key)
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("time_zero", mode="sample", sample=49))
    n_kept = dock.view.transform.n_samples
    dock.set_selected_step(0)
    t = dock.view.transform
    assert t.n_samples == n_kept + 49
    assert t.t0_ns == pytest.approx(-11.086 - (-0.476), abs=0.01)
    assert dock.shown_zero_ns() == pytest.approx(session.stack_for(key).zero_ns())


def test_the_line_shows_only_in_sample_mode_while_selected(opened):
    """Review Focus 3, and the line's place: Time zero's first kept row on the
    record it receives, relabelled onto the line's clock."""
    session, dock, key, line = opened
    _stack_of(session, key, ("time_zero", dict(mode="sample", sample=20)))
    assert dock.view.cutoff_ns is None  # not selected
    dock.set_selected_step(0)
    rg = dock._shown_radargram
    assert dock.view.cutoff_ns == pytest.approx(rg.t0_ns + 20 * rg.dt_ns)
    assert dock.view.cutoff_ns == pytest.approx(0.0, abs=1e-9)  # the line's own zero
    assert dock.view._cutoff_kind == "start"
    assert dock.view._cutoff_text(dock.view.transform) == "Time zero \u00b7 sample 20"
    session.replace_step(key, 0, build_step("time_zero", mode="first_break"))
    assert dock.view.cutoff_ns is None  # first_break mode: no line
    session.replace_step(key, 0, build_step("time_zero", mode="sample", sample=30))
    assert dock.view.cutoff_ns == pytest.approx(0.0, abs=1e-9)
    assert dock.view._cutoff_text(dock.view.transform).endswith("sample 30")
    dock.set_selected_step(-1)
    assert dock.view.cutoff_ns is None


def test_a_time_zero_that_is_not_first_draws_its_line_on_its_input_rows(opened):
    """Review Focus 1: Dewow, Time zero, AGC. The rows are the step's rows."""
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("dewow", {}),
        ("time_zero", dict(mode="sample", sample=20)),
        ("gain_agc", {}),
    )
    dock.set_selected_step(1)
    rg = dock._shown_radargram
    np.testing.assert_array_equal(rg.data, stack.result_bypassing(1).data)
    assert dock.view.cutoff_ns == pytest.approx(rg.t0_ns + 20 * rg.dt_ns)
    assert dock.view._cutoff_text(dock.view.transform).endswith("sample 20")


def test_dragging_time_zeros_line_through_the_dock_writes_its_row(opened):
    session, dock, key, line = opened
    _stack_of(session, key, ("time_zero", dict(mode="sample", sample=20)))
    dock.set_selected_step(0)
    rg = dock._shown_radargram
    step = session.stack_for(key).entries[0][0]
    dock.view.cutoff_dragged.emit(rg.t0_ns + 20 * rg.dt_ns)
    assert session.stack_for(key).entries[0][0] is step  # unmoved: nothing written
    dock.view.cutoff_dragged.emit(rg.t0_ns + 26 * rg.dt_ns)
    assert session.stack_for(key).entries[0][0].params["sample"] == 26


def test_a_drag_to_either_end_clamps_and_is_accepted(opened):
    """Review Focus 5: row 0 and row n - 1 are both writable."""
    session, dock, key, line = opened
    _stack_of(session, key, ("time_zero", dict(mode="sample", sample=20)))
    dock.set_selected_step(0)
    n = dock._shown_radargram.n_samples
    t = dock.view.transform
    assert t.snap_row(-1e6) == pytest.approx(t.t0_ns)
    dock.view.cutoff_dragged.emit(t.snap_row(-1e6))
    assert session.stack_for(key).entries[0][0].params["sample"] == 0
    assert dock.view.cutoff_ns is not None
    t = dock.view.transform
    dock.view.cutoff_dragged.emit(t.snap_row(1e6))
    assert session.stack_for(key).entries[0][0].params["sample"] == n - 1
    assert session.stack_for(key).result().data.shape[0] == 1


def test_a_disabled_time_zero_draws_its_line_as_the_cutoff_does(opened):
    """Review Focus 2. `_handle_row` ignores `enabled`: a disabled time cutoff
    still shows its line, and so does a disabled Time zero. With the step
    disabled, `zero_ns()` skips it, so the relabel is a no-op and the record
    is on the source's own clock; the line sits at the step's row on it, and
    a drag writes that row. Nothing is cropped, nor does the line claim it is."""
    session, dock, key, line = opened
    stack = _stack_of(session, key, ("time_zero", dict(mode="sample", sample=20)))
    session.set_step_enabled(key, 0, False)
    dock.set_selected_step(0)
    src = stack.source
    rg = dock._shown_radargram
    assert rg.t0_ns == pytest.approx(src.t0_ns)  # no crop, no relabel
    assert dock.view.cutoff_ns == pytest.approx(src.t0_ns + 20 * src.dt_ns)
    dock.view.cutoff_dragged.emit(src.t0_ns + 26 * src.dt_ns)
    assert session.stack_for(key).entries[0][0].params["sample"] == 26
    assert session.stack_for(key).entries[0][1] is False


def test_a_row_handles_fallback_input_view_is_its_own_scale(opened):
    """The fallback view (a later step refuses the bypass) takes its display
    limit from the drawn input, not the processed stack, whose scale can
    differ by orders of magnitude."""
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("time_zero", dict(mode="sample", sample=20)),
        ("migrate_fk", dict(velocity_m_ns=0.1)),
    )
    dock.set_selected_step(0)
    np.testing.assert_array_equal(dock.image.rg.data, stack.source.data)
    assert dock.image.reference is dock.image.rg
    assert dock.image.limit == _clip(dock)(stack.source.data)


def test_a_time_zero_that_refuses_still_draws_its_input(opened):
    """A sample past the record's end (a preset on a shorter record): the
    input, unrelabelled, is what the user needs to fix the row. No error."""
    session, dock, key, line = opened
    stack = _stack_of(session, key, ("time_zero", dict(mode="sample", sample=600)))
    errors = []
    dock.error.connect(errors.append)
    dock.set_selected_step(0)
    assert errors == []
    np.testing.assert_array_equal(dock.image.rg.data, stack.source.data)


def test_selecting_time_zero_keeps_the_processed_look(opened):
    """§4.14 Q3: the bypass is drawn, on the ordinary view's display scale."""
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("time_zero", dict(mode="sample", sample=20)),
        ("dewow", {}),
        ("gain_agc", {}),
    )
    ordinary = dock.image.limit
    dock.set_selected_step(0)
    expect = relabel_onto(stack.result_bypassing(0), stack.zero_ns())
    np.testing.assert_array_equal(dock.image.rg.data, expect.data)
    assert dock.image.limit == pytest.approx(ordinary, rel=0.05)


def test_a_later_step_that_refuses_falls_back_to_the_input(opened):
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("time_zero", dict(mode="sample", sample=20)),
        ("migrate_fk", dict(velocity_m_ns=0.1)),
    )
    errors = []
    dock.error.connect(errors.append)
    dock.set_selected_step(0)
    assert errors == []
    np.testing.assert_array_equal(dock.image.rg.data, stack.source.data)
    assert dock.view.cutoff_ns is not None


def test_a_bypass_with_other_rows_falls_back(opened):
    """A second Time zero crops the bypass, so its rows are not the input's:
    the input is drawn and the line's row is the step's own `sample`."""
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("time_zero", dict(mode="sample", sample=20)),
        ("time_zero", dict(mode="sample", sample=10)),
    )
    assert stack.result_bypassing(0).data.shape[0] != stack.source.data.shape[0]
    dock.set_selected_step(0)
    rg = dock._shown_radargram
    np.testing.assert_array_equal(rg.data, relabel_onto(stack.source, stack.zero_ns()).data)
    assert dock.view.cutoff_ns == pytest.approx(rg.t0_ns + 20 * rg.dt_ns)


def test_a_cutoff_after_time_zero_still_draws_the_bypass(opened):
    """§4.14 Q3: a time cutoff after Time zero cuts the bypass's bottom, which
    is no reason to fall back: the shorter bypass is drawn, on the line's clock."""
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    src = session.stack_for(key).source
    end = src.t0_ns + 150 * src.dt_ns
    stack = _stack_of(
        session,
        key,
        ("time_zero", dict(mode="sample", sample=20)),
        ("dewow", {}),
        ("time_cutoff", dict(end_ns=end)),
    )
    bypass = stack.result_bypassing(0)
    assert bypass.n_samples < src.n_samples
    dock.set_selected_step(0)
    rg = dock._shown_radargram
    np.testing.assert_array_equal(rg.data, relabel_onto(bypass, stack.zero_ns()).data)
    assert rg.n_samples < src.n_samples
    assert rg.t0_ns + rg.zero_ns == pytest.approx(bypass.t0_ns + bypass.zero_ns)
    assert dock.view.cutoff_ns == pytest.approx(rg.t0_ns + 20 * rg.dt_ns)
    ref = stack.result_bypassing(0)  # no gain curve: the reference is the bypass itself
    assert dock.image.limit == _clip(dock)(ref.data)


def test_a_fallback_view_takes_its_scale_from_the_drawn_input(opened):
    """The mismatch fallback (a second Time zero crops the top) is its own
    scale: the limit is the input's, not the processed stack's."""
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("time_zero", dict(mode="sample", sample=20)),
        ("gain_agc", {}),
        ("time_zero", dict(mode="sample", sample=10)),
    )
    dock.set_selected_step(0)
    assert dock.image.reference is dock.image.rg
    assert dock.image.limit == _clip(dock)(stack.source.data)


def test_a_bypass_view_measures_its_scale_with_the_gain_curve_and_time_zero_off(opened):
    session, dock, key, line = opened
    stack = _stack_of(
        session,
        key,
        ("time_zero", dict(mode="sample", sample=20)),
        ("dewow", {}),
        ("gain_curve", dict(points=[[0, 0], [50, 40]])),
    )
    dock.set_selected_step(0)
    np.testing.assert_array_equal(dock.image.reference.data, stack.result_bypassing(0, 2).data)
