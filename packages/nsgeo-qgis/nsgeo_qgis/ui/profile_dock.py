"""The profile dock: the profile viewer plus display-gain controls, bound
to the session. Opens the current line with header-derived axes before
samples arrive, renders once they do, and re-renders whenever the stack
changes -- with the axes following whatever the stack currently produces
(a time-zero crop shortens the sample axis, for instance).

Display gain (percentile clip, colormap) lives here, not in a processing
dock, because it changes only the colour mapping and is never recorded in
a stack.

Owns the `ProfileView` it displays (`self.view = ProfileView(body)`, and
`body` is this dock's own central widget): Qt's parent/child ownership is
what controls destruction order in production, the same way SurveyDock
owns its tree. A test that builds a `ProfileDock` directly still owns a
top-level widget with no parent of its own, so it must tear it down itself
(`hide()` then `deleteLater()`) rather than let Python's GC race Qt's own
teardown -- see `test_plugin_profile_view.py`'s `make_view` fixture for
the same hazard and pattern this file's own tests copy.

Signal/slot hazard: an exception raised inside a slot connected via
`connect()` never reaches whatever emitted the signal -- PyQt prints the
traceback to stderr and `emit()` returns as if the slot had succeeded (see
`nsgeo_qgis.plugin`'s module docstring, and `nsgeo_qgis.ui.survey_dock`/
`nsgeo_qgis.ui.profile_view` for the same `_log`-and-guard pattern this
file copies -- `nsgeo_qgis.log` is the one shared `log()` all three use,
not a fourth copy of the same two lines). Every slot below that does real
work guards its own body and reports through `_log` rather than let a
real failure -- a stale key, a placement whose `distance_along()` raises
for a time-triggered line (SurveyDock marks such a line "unplaced" in the
tree for the same reason; here it just means "no distance axis, fall back
to trace index" -- see `_safe_distance`) -- vanish silently.

`current_radargram()` is the one place a *processing* failure (a bad step,
e.g. a bandpass whose high cut exceeds Nyquist, or a difference view whose
step index no longer exists, or changes the sample count) is turned into
the `error` signal instead of an exception, so a bad step leaves the
previous render on screen with a message rather than blanking the view.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import Radargram, StepStack
from nsgeo.render import DEFAULT_COLORMAP, colormap_names
from nsgeo.velocity import VelocityModel, resolve_velocity
from qgis.core import Qgis
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.render.qimage import RadargramImage
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gain_strip import GainStrip
from nsgeo_qgis.ui.profile_view import MARGIN_TOP, ProfileView


def velocity_source(session: SiteSession, key: str) -> str:
    """Name whichever tier `nsgeo.velocity.resolve_velocity` actually used:
    "line override", "Grid <id>", a header-dielectric fallback, or
    "unknown source" when none of those three account for the result.

    This mirrors `resolve_velocity`'s own precedence (line override, then
    the grid's model, then the header's dielectric) -- but does not
    *re-decide* it. Instead it checks the actual object `resolve_velocity`
    returned against each of the three candidates it is documented to
    return, by *value* (`==`, not `is`): a `VelocityModel` is a frozen
    dataclass with value equality, so this is correct whether or not
    `resolve_velocity` happens to return the original object or an
    equal copy of it -- unlike an identity (`is`) comparison, which a
    review confirmed is strictly weaker (a `resolve_velocity` that
    returns `VelocityModel(layers=grid.velocity.layers)` instead of
    `grid.velocity` itself would fool an identity check into falling
    through to the wrong tier, but cannot fool `==`).

    Reordering the three known tiers is still always named correctly,
    because every candidate is still checked. What this can *not* do is
    invent a name for a tier that does not exist yet: if GitHub issue #4
    adds a fourth tier (e.g. a site-level default) and a line resolves to
    it, none of the three `==` checks below matches, and this returns
    "unknown source" rather than guessing "header ε ..." -- a label that
    confidently names the wrong tier is worse than no label at all, so the
    fallback is an explicit check against the header candidate, not a
    blind `else`.
    """
    line = session.line_for_key(key)
    grid = session.grid_for_line(line)
    resolved = resolve_velocity(line, grid)
    if resolved == line.velocity:
        return "line override"
    if grid is not None and resolved == grid.velocity:
        return f"Grid {grid.id}"
    if resolved == VelocityModel.from_dielectric(line.header.epsr):
        return f"header ε {line.header.epsr:g}"
    return "unknown source"


class ProfileDock(QgsDockWidget):
    error = pyqtSignal(str)
    pick_requested = pyqtSignal(str, int, float)
    gain_points_changed = pyqtSignal(list)
    difference_cleared = pyqtSignal()

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Profile", parent)
        self.setObjectName("nsgeoProfileDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.session = session
        self.image: RadargramImage | None = None
        self._difference_index = -1
        self._key: str | None = None

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 2, 4, 4)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Display gain"))
        self.percentile_slider = QSlider(Qt.Orientation.Horizontal)
        self.percentile_slider.setRange(500, 1000)
        # M5 follow-up (Finding 1): a lower percentile clips more of the
        # signal, which saturates more samples to black/white -- "more
        # gained" in the user's words. The intuitive drag direction is
        # therefore backwards from the slider's own min/max: dragging
        # right should LOWER the percentile. `setInvertedAppearance` only
        # flips which physical end of the widget the minimum/maximum are
        # drawn at (and which way a mouse drag or arrow key moves the
        # value) -- it leaves `value()`/`setValue()` semantics completely
        # alone, so `percentile` below still reads the slider's own value
        # directly and still returns the true percentile, exactly as
        # `RadargramImage` requires. An explicit inverse mapping (e.g.
        # `percentile = (minimum + maximum - value) / 10.0`) was the other
        # option the brief allowed, but it would make `value()` mean
        # something other than "percentile x 10" everywhere else this
        # slider is touched (tests included) for no benefit here.
        self.percentile_slider.setInvertedAppearance(True)
        self.percentile_slider.setValue(990)
        self.percentile_slider.setFixedWidth(120)
        self.percentile_label = QLabel("99.0 %")
        bar.addWidget(self.percentile_slider)
        bar.addWidget(self.percentile_label)
        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(colormap_names())
        self.colormap_combo.setCurrentText(DEFAULT_COLORMAP)
        bar.addWidget(self.colormap_combo)
        self.difference_label = QLabel("")
        bar.addWidget(self.difference_label)
        self.fit_button = QPushButton("Fit")
        self.one_to_one_button = QPushButton("1:1")
        bar.addWidget(self.fit_button)
        bar.addWidget(self.one_to_one_button)
        self.channel_combo = QComboBox()
        self.channel_combo.hide()
        bar.addWidget(self.channel_combo)
        bar.addStretch(1)
        self.velocity_label = QLabel("")
        bar.addWidget(self.velocity_label)
        layout.addLayout(bar)
        # Parented to `body`, which this dock owns via setWidget() below --
        # not a top-level, parentless widget the way a naive test fixture
        # might build one (see the module docstring). The strip sits beside
        # the viewer in its own row so both share the same vertical space
        # and the strip can borrow the viewer's own ViewTransform for its
        # time axis (see _sync_strip_mapping).
        viewer_row = QHBoxLayout()
        viewer_row.setSpacing(0)
        self.view = ProfileView(body)
        viewer_row.addWidget(self.view, 1)
        self.gain_strip = GainStrip(body)
        self.gain_strip.hide()
        viewer_row.addWidget(self.gain_strip)
        layout.addLayout(viewer_row, 1)
        self.setWidget(body)

        self.percentile_slider.valueChanged.connect(self._display_changed)
        self.colormap_combo.currentTextChanged.connect(self._display_changed)
        self.fit_button.clicked.connect(self.view.fit)
        self.one_to_one_button.clicked.connect(self.view.one_to_one)
        self.channel_combo.currentIndexChanged.connect(self._channel_changed)
        self.view.trace_hovered.connect(self._hovered)
        self.view.range_selected.connect(self._range_selected)
        self.view.pick_requested.connect(self._pick)
        self.view.view_changed.connect(self._sync_strip_mapping)
        self.gain_strip.points_changed.connect(self.gain_points_changed.emit)

        session.line_opened.connect(self._on_line_opened)
        session.line_loaded.connect(self._on_line_loaded)
        session.stack_changed.connect(self._on_stack_changed)
        session.trace_changed.connect(self._on_trace_changed)
        session.selection_changed.connect(self._on_selection_changed)
        session.lines_changed.connect(self._refresh_velocity)
        session.grids_changed.connect(self._refresh_velocity)
        session.site_closed.connect(self._clear)

    # ---- display settings ---------------------------------------------
    @property
    def percentile(self) -> float:
        return self.percentile_slider.value() / 10.0

    @property
    def colormap_name(self) -> str:
        return self.colormap_combo.currentText()

    def _display_changed(self, *_: Any) -> None:
        self.percentile_label.setText(f"{self.percentile:.1f} %")
        if self.image is None:
            return
        try:
            self.image = self.image.with_display(self.percentile, self.colormap_name)
            self.view.set_image(self.image.image)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not apply the display change: {exc}", Qgis.MessageLevel.Critical)

    # ---- placement safety ----------------------------------------------
    def _safe_distance(self, line: Any) -> Any:
        """`Line.distance_along()` raises `ValueError` for a time-triggered
        acquisition (`traces_per_metre <= 0`): there is no geometry to
        offer. `SurveyDock` marks a line like this "unplaced" in the tree
        for the same reason (see its `_line_item`); here it just means the
        bottom axis falls back to a trace-index label instead of metres --
        not an error a signal-connected slot should ever see escape.
        """
        try:
            return line.distance_along()
        except ValueError:
            return None

    # ---- session events -------------------------------------------------
    def _on_line_opened(self, key: str) -> None:
        try:
            self._open(key)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(
                f"could not open line {key!r} in the profile view: {exc}",
                Qgis.MessageLevel.Critical,
            )

    def _open(self, key: str) -> None:
        # Opening ANY line -- including re-opening the same one, or none at
        # all -- always leaves the difference view off: the previous line's
        # step index means nothing on a different stack. Emitted only when
        # a difference view was actually showing (matches the symmetric
        # guard in current_radargram()'s except branch below), and before
        # `self._key` changes, so `diff_button`'s own uncheck -- routed
        # through `difference_toggled` back into `set_difference_index` --
        # still resolves against the line that was just showing a
        # difference, not whatever `key` is about to become. Left
        # unemitted (as before this fix), `diff_button` stayed checked
        # across a line switch while the view underneath had already gone
        # back to `result()`: the button claimed a mode that was off, and
        # the very next stack_changed re-armed it against a step index
        # that could belong to an entirely different stack.
        was_diff = self._difference_index >= 0
        self._difference_index = -1
        self.difference_label.setText("")
        if was_diff:
            self.difference_cleared.emit()
        self._key = key or None
        if not key:
            self._clear_view_only()
            return
        line = self.session.line_for_key(key)
        label = getattr(line.placement, "label", None) or line.path.stem
        self.setWindowTitle(f"nsgeo Profile · {label} · {line.n_traces} traces")
        self.view.set_direction(int(getattr(line.placement, "direction", 1)))
        self.image = None
        # C1: `SiteSession.open_line` resets `_current_trace`/`_selection`
        # to their cleared sentinels but emits neither `trace_changed` nor
        # `selection_changed` for that reset (only `line_opened`), and
        # `ProfileView.set_axes` -- called below either way -- touches
        # neither `_cursor` nor `_selection` either. Left alone, the
        # previous line's cursor and selection band carry across to this
        # one: the widget would go on showing state the session has
        # already discarded, which is exactly what routing all state
        # through `SiteSession` (see its own module docstring) exists to
        # prevent. Cleared explicitly, every time a line opens, regardless
        # of whether its profiles are loaded yet.
        self.view.set_cursor(-1)
        self.view.clear_selection()
        profiles = self.session.profiles_for(key)
        if profiles:
            self._configure_channels(len(profiles))
            self._render()
        else:
            self.channel_combo.hide()
            self.view.set_axes(
                line.n_traces,
                line.header.n_samples,
                line.header.position_ns,
                line.header.dt_ns,
                self._safe_distance(line),
            )
            self.view.set_image(None)
        self._refresh_velocity()

    def _on_line_loaded(self, key: str) -> None:
        if key != self._key:
            return
        try:
            profiles = self.session.profiles_for(key) or []
            self._configure_channels(len(profiles))
            self._render()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not render line {key!r} once it loaded: {exc}", Qgis.MessageLevel.Critical)

    def _on_stack_changed(self, key: str) -> None:
        if key != self._key:
            return
        try:
            self._render()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not re-render after a stack change: {exc}", Qgis.MessageLevel.Critical)

    def _on_trace_changed(self, key: str, index: int) -> None:
        if key != self._key:
            return
        try:
            self.view.set_cursor(index)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not move the profile cursor: {exc}", Qgis.MessageLevel.Critical)

    def _on_selection_changed(self, key: str, a: int, b: int) -> None:
        if key != self._key:
            return
        try:
            self.view.set_selection(a, b)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not update the profile selection: {exc}", Qgis.MessageLevel.Critical)

    def _clear(self) -> None:
        # `_open` (the other place this dock forgets a line) resets the
        # same three pieces of difference-view bookkeeping; this path
        # must agree with it rather than leave `_difference_index` and
        # `diff_button` stuck on whatever they last were. `self._key` is
        # cleared first, so a `difference_cleared` emitted from here (and
        # any re-entrant `set_difference_index` it triggers) finds
        # `current_radargram()`'s own `self._key is None` check and
        # returns cleanly -- no re-entrant render to guard against here,
        # unlike `_open`'s ordering.
        self._key = None
        was_diff = self._difference_index >= 0
        self._difference_index = -1
        self.difference_label.setText("")
        try:
            self._clear_view_only()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not clear the profile view: {exc}", Qgis.MessageLevel.Critical)
        if was_diff:
            self.difference_cleared.emit()

    def _clear_view_only(self) -> None:
        self.image = None
        self.view.clear()
        self.setWindowTitle("nsgeo Profile")
        self.velocity_label.setText("")
        self.channel_combo.hide()

    # ---- rendering -------------------------------------------------------
    def set_difference_index(self, index: int) -> None:
        # `_open` and `current_radargram`'s except branch both already
        # set `_difference_index = -1` themselves before emitting
        # `difference_cleared`, which routes back here (via `diff_button`
        # unchecking itself and re-emitting `difference_toggled(-1)`) --
        # so that re-entrant call always arrives with the index unchanged.
        # Without this early-out, it re-rendered anyway: on an ordinary
        # line switch that alone re-rendered the OLD line one extra time
        # (a fresh RadargramImage, set_axes, set_image) before `_open`
        # went on to replace it, pure wasted work: and once the session
        # closes mid-switch, that re-entrant render runs against a stack
        # whose site is already gone, so it always raised and always got
        # logged Critical for an ordinary File > Close -- noise, not a
        # real failure, which is exactly what Critical is not for.
        if index == self._difference_index:
            return
        self._difference_index = index
        try:
            self._render()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not render the difference view: {exc}", Qgis.MessageLevel.Critical)

    def current_radargram(self) -> Radargram | None:
        if self._key is None:
            return None
        stack: StepStack = self.session.stack_for(self._key)
        if stack.source is None:
            return None
        try:
            if self._difference_index >= 0:
                return stack.difference(self._difference_index)
            return stack.result()
        except ValueError as exc:
            # The differenced step changes the sample count
            # (StepStack.difference's own guard) -- already a
            # human-facing message, unlike the IndexError sibling below.
            return self._decline_difference(str(exc))
        except IndexError:
            # The differenced index no longer exists at all --
            # StepStack.difference/intermediate both raise a developer-
            # facing IndexError for an out-of-range index (stack.py: "step
            # index 1 out of range (0..0)"), which is exactly what
            # applying a shorter preset, or removing the differenced
            # step, produces. Left uncaught here, it escaped into the
            # render slots' broad `except Exception`: logged Critical,
            # the image frozen on the stale render, `diff_button` still
            # checked, and `difference_label` still naming a step that no
            # longer exists -- no visible crash, just silently wrong. Its
            # own text is not shown to the user (unlike the ValueError
            # above): 0-based indices and a raw range are implementation
            # detail, not something a message bar should say.
            return self._decline_difference("the differenced step no longer exists in this stack")

    def _decline_difference(self, message: str) -> None:
        """Report `message` and revert an active difference view: shared
        by both branches of `current_radargram`'s except clause above, so
        the reset-clear-emit sequence -- and the `difference_cleared`
        guard that keeps it a no-op when no difference was showing --
        cannot drift between them."""
        self.error.emit(message)
        if self._difference_index >= 0:
            self._difference_index = -1
            self.difference_label.setText("")
            self.difference_cleared.emit()
        return None

    def _render(self) -> None:
        rg = self.current_radargram()
        if rg is None:
            return
        distance = None
        if self._key is not None:
            line = self.session.line_for_key(self._key)
            if rg.n_traces == line.n_traces:
                distance = self._safe_distance(line)
        keep_window = (
            self.view.transform is not None and self.view.transform.n_traces == rg.n_traces
        )
        old = self.view.transform
        self.view.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns, distance)
        if keep_window and old is not None and old.n_samples == rg.n_samples:
            self.view.transform = old
        self.image = (
            self.image.with_radargram(rg)
            if self.image is not None
            else RadargramImage(rg, self.percentile, self.colormap_name)
        )
        self.view.set_image(self.image.image)
        step_text = ""
        if self._difference_index >= 0 and self._key is not None:
            entries = self.session.stack_for(self._key).entries
            step_text = f"Difference: {entries[self._difference_index][0].name}"
        self.difference_label.setText(step_text)
        self._sync_strip_mapping()

    def _sync_strip_mapping(self) -> None:
        if self.view.transform is not None:
            self.gain_strip.set_time_mapping(self.view.transform, MARGIN_TOP)

    def show_gain_strip(self, points: list[list[float]] | None) -> None:
        """Show the strip editing `points`, or hide it (`points is None`, the
        selected step is not a curve, or nothing has rendered yet so there
        is no axis to share)."""
        if points is None or self.view.transform is None:
            self.gain_strip.hide()
            return
        self._sync_strip_mapping()
        self.gain_strip.set_points(points)
        self.gain_strip.show()

    def _refresh_velocity(self, *_: Any) -> None:
        # I4: both halves of this guard matter, even though only the first
        # is reachable today. `self._key is None` alone would not be
        # enough: `resolved_velocity` -> `line_for_key` -> `_require_site()`
        # raises `ProjectError` (not a `KeyError`) once the site is closed,
        # which the broad `except Exception` below would then catch and
        # log as a Critical failure instead of this returning quietly --
        # a silent no-op and a logged error are not the same outcome, so
        # this is not redundant with the exception handler even though
        # nothing in today's call graph reaches it (`close_site` always
        # emits `line_opened("")` -- which clears `self._key` via `_open`
        # -- before `site_closed`). Keep both halves.
        if self._key is None or not self.session.is_open:
            return
        try:
            model: VelocityModel = self.session.resolved_velocity(self._key)
            label = velocity_source(self.session, self._key)
            self.view.set_velocity(model)
            self.velocity_label.setText(f"v = {model.surface_velocity:.3f} m/ns ({label})")
        except KeyError:
            return
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not resolve the line's velocity: {exc}", Qgis.MessageLevel.Critical)

    def _configure_channels(self, n: int) -> None:
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        for i in range(n):
            self.channel_combo.addItem(f"channel {i}", i)
        if self._key is not None:
            self.channel_combo.setCurrentIndex(self.session.channel(self._key))
        self.channel_combo.blockSignals(False)
        self.channel_combo.setVisible(n > 1)

    def _channel_changed(self, index: int) -> None:
        if self._key is None or index < 0:
            return
        try:
            self.session.set_channel(self._key, index)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not switch channel: {exc}", Qgis.MessageLevel.Critical)

    # ---- viewer events -----------------------------------------------------
    def _hovered(self, trace: int) -> None:
        if self._key is None:
            return
        try:
            self.session.set_trace(self._key, trace)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not update the hovered trace: {exc}", Qgis.MessageLevel.Critical)

    def _range_selected(self, a: int, b: int) -> None:
        if self._key is None:
            return
        try:
            self.session.set_selection(self._key, a, b)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not update the selection: {exc}", Qgis.MessageLevel.Critical)

    def _pick(self, trace: int, time_ns: float) -> None:
        # I6: guarded like every other slot here, even though nothing
        # connects to `pick_requested` yet (Task 18/19 will). Verified
        # directly: an exception raised by a *downstream* subscriber of
        # `pick_requested` is swallowed by PyQt at the point that
        # subscriber is invoked, and never propagates back into this
        # `try` at all -- so this cannot catch a future picking dock's own
        # bug. What it does guard is this method's own body, which is
        # exactly the "every slot guards its body" rule this file's
        # docstring states, and the one place that will matter if this
        # method ever grows logic ahead of the `emit()` call. A pick is
        # authored data with no other source of truth; failing loudly
        # here is cheap insurance for what this line can control.
        if self._key is None:
            return
        try:
            self.pick_requested.emit(self._key, trace, time_ns)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not relay the pick: {exc}", Qgis.MessageLevel.Critical)
