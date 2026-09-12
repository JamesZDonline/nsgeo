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
    dock._key = key  # force the otherwise-unreachable state directly
    dock._refresh_velocity()
    assert not message_log
