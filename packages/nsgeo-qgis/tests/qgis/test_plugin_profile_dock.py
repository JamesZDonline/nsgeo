from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.velocity import VelocityModel
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.profile_dock import ProfileDock, velocity_source
from plugin_testing import synthetic_dzt

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


@pytest.fixture
def message_log(qgis_app):
    """Captured `QgsMessageLog` messages, for the life of this test only.

    Mirrors `test_plugin_profile_view.py`'s fixture of the same name (also
    duplicated in `test_plugin_layers.py`): `QgsApplication.messageLog()` is
    a session-scoped singleton, so a connection left dangling would keep
    accumulating every later test's messages into this one's list for the
    rest of the (also session-scoped) `qgis_app` fixture. Disconnected on
    teardown.
    """
    from qgis.core import QgsApplication

    log = QgsApplication.messageLog()
    messages: list[str] = []

    def _on_message(msg: str, tag: str, level: int) -> None:
        messages.append(msg)

    log.messageReceived.connect(_on_message)
    yield messages
    log.messageReceived.disconnect(_on_message)


def test_opening_shows_axes_and_loading_before_samples_arrive(opened):
    session, dock, key, line = opened
    assert "FILE__001" in dock.windowTitle()
    assert f"{line.n_traces} traces" in dock.windowTitle()
    assert dock.view.transform is not None and dock.view.transform.n_traces == 240
    assert dock.image is None
    session.set_profiles(key, line.load())
    assert dock.image is not None
    assert dock.view.transform.n_samples == 512


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
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.set_trace(key, 12)
    assert dock.view._cursor == 12
    dock.view.trace_hovered.emit(30)
    assert session.current_trace == 30
    dock.view.range_selected.emit(5, 9)
    assert session.selection == (5, 9)


def test_channel_combo_hidden_for_single_channel_files(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    assert dock.channel_combo.isHidden()


def test_closing_the_site_clears_the_view(opened):
    session, dock, key, line = opened
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
