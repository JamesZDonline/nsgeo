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
        self._working_key: str | None = None
        self._preview_key: str | None = None
        self._strip_was_visible = False
        self._deferred_strip: tuple[list[list[float]], Any] | None = None

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
        # Radargram amplitude is bipolar; the unipolar tables (M10, for
        # horizontal slices) don't belong here -- amp_heat on bipolar data
        # is a configuration error, and amp_black_high/amp_white_high are
        # pixel-identical to grey_black_high/grey_white_high already in
        # this list.
        self.colormap_combo.addItems(colormap_names(unipolar=False))
        self.colormap_combo.setCurrentText(DEFAULT_COLORMAP)
        bar.addWidget(self.colormap_combo)
        # Finding 7 (M7 walkthrough re-review, third round): the preview
        # marker moved out of this row entirely -- see `_show_line`'s
        # `is_preview` parameter, which marks it in the window title
        # instead (`nsgeo Profile · PREVIEW: <name> · N traces`). Findings
        # 2 and 5 chased a label that could not both fit here AND stay
        # visible: reordered past a stretch, it still shifted the buttons
        # at a realistic dock width; given a fixed width instead, it
        # raised the dock's own minimum width and clipped its neighbours
        # permanently; made to elide gracefully, it elided to an empty
        # string at 900px -- there was simply no room in this row to hold
        # it, visibly, ever. The title bar already names the line and
        # costs no layout at all. `difference_label` was never part of
        # the complaint -- it goes back to exactly where it sat before
        # any of this: a plain `QLabel`, immediately before `fit_button`.
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
        self.view.selection_cleared.connect(self._selection_cleared)
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
        session.preview_changed.connect(self._on_preview_changed)

    # ---- display settings ---------------------------------------------
    @property
    def percentile(self) -> float:
        return self.percentile_slider.value() / 10.0

    @property
    def colormap_name(self) -> str:
        return self.colormap_combo.currentText()

    @property
    def _key(self) -> str | None:
        """The line being DISPLAYED -- the preview when there is one.

        Every read site in this file wants this: a stack_changed on the
        line currently on screen should re-render it whether that line is
        the working one or a preview, and `_on_trace_changed`'s key filter
        should reject the working line's cursor while a preview is up.
        The two assignment sites became `_working_key` instead.
        """
        return self._preview_key or self._working_key

    @property
    def _effective_difference_index(self) -> int:
        """`-1` while previewing: the difference view is a property of a
        step in the WORKING line's stack, and `_difference_index` indexes
        that stack. Computing it against a previewed line's stack would be
        an index into the wrong list -- at best an IndexError, at worst a
        plausible-looking image of the wrong subtraction. Kept separate
        from `_difference_index` itself so the mode is remembered and
        returns intact when the view snaps back (spec §3.3)."""
        return -1 if self._preview_key is not None else self._difference_index

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
        self._working_key = key or None
        # Finding 2 (M7 final review): remove_line() resets ONLY the
        # dropped key's own current/preview fields (see its own docstring)
        # -- if the CURRENT line is removed while a DIFFERENT line is
        # being previewed, session.preview_key survives untouched, and
        # remove_line still emits line_opened("") (its ordering: current
        # first, THEN preview). Dropping `_preview_key` unconditionally
        # here used to blank the view and clear the banner while
        # session.display_key -- and the map marker -- kept naming the
        # previewed line: this dock desyncing from the very session it
        # mirrors. Every OTHER caller of line_opened has already reset
        # session.preview_key to None before emitting (open_line always
        # does, and remove_line does too whenever the removed line IS the
        # preview), so `key` is only ever falsy here WITH a live session
        # preview in exactly that one case -- checking the session instead
        # of assuming "opened means no preview" fixes it without touching
        # any other path.
        still_previewing = not key and self.session.is_open and self.session.preview_key is not None
        if not still_previewing:
            self._preview_key = None
            # A preview may have disabled the channel combo (see
            # `_enter_preview`); opening ANY line -- including via
            # promotion, which is how a preview ends without
            # `_exit_preview` ever running -- means no preview is up any
            # more, so re-enable it unconditionally rather than leave it
            # stuck disabled.
            self.channel_combo.setEnabled(True)
        # A deferred strip payload belongs to the line that was working
        # when it arrived. Promotion and a site close both change which
        # line that is, so the payload is not merely stale, it is wrong:
        # replaying it later would put another line's curve on the strip,
        # and a drag there writes through session.current_key. Dropped,
        # never replayed. (_exit_preview is the ONLY path that may replay
        # one, because there the working line has not changed.)
        self._deferred_strip = None
        if not key:
            if still_previewing:
                # The view, title/tooltip and disabled channel combo are
                # already showing exactly the surviving preview --
                # untouched above -- so there is nothing left to do beyond
                # the working line's own bookkeeping (difference index,
                # deferred strip), already cleared.
                return
            self._clear_view_only()
            return
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
        self._show_line(key)

    def _show_line(self, key: str, *, is_preview: bool = False) -> None:
        """Configure the view for `key`: title, direction, axes, image,
        channels, velocity. Shared by `_open` (the working line) and
        `_enter_preview`. Deliberately does NOT touch the difference view
        or the cursor/selection: those differ between the two callers,
        which is the whole reason this is a separate method.

        Finding 7 (M7 walkthrough re-review, third round): `is_preview`
        marks the window title -- `nsgeo Profile · PREVIEW: <name> · N
        traces`, the marker at the FRONT of the name so it cannot be lost
        to truncation on a narrow or tabbed dock -- and, alongside it,
        sets the dock's tooltip to the "select it on the map to work on
        it" hint (cleared otherwise). This is an explicit parameter, not
        a re-derivation from `self._preview_key`: at the moment
        `_enter_preview` calls this, `_preview_key` is already set to
        `key`, so re-deriving "is this a preview" from it here would
        still give the right answer today, but only by coupling this
        method to an assignment ordering that has already changed twice
        in this milestone. The caller already knows which case it is;
        saying so directly is the honest version.
        """
        line = self.session.line_for_key(key)
        label = getattr(line.placement, "label", None) or line.path.stem
        shown = f"PREVIEW: {label}" if is_preview else label
        self.setWindowTitle(f"nsgeo Profile · {shown} · {line.n_traces} traces")
        self.setToolTip(
            f"Preview: {label} — select it on the map to work on it" if is_preview else ""
        )
        self.view.set_direction(int(getattr(line.placement, "direction", 1)))
        self.image = None
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
        self._working_key = None
        self._preview_key = None
        # A deferred strip payload belongs to the line that was working
        # when it arrived. Promotion and a site close both change which
        # line that is, so the payload is not merely stale, it is wrong:
        # replaying it later would put another line's curve on the strip,
        # and a drag there writes through session.current_key. Dropped,
        # never replayed. (_exit_preview is the ONLY path that may replay
        # one, because there the working line has not changed.)
        self._deferred_strip = None
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
        self.setToolTip("")
        self.velocity_label.setText("")
        self.channel_combo.hide()

    # ---- preview (M7, spec §3.3) ----------------------------------------
    def _on_preview_changed(self, key: str, trace: int) -> None:
        try:
            if key and key != self._working_key:
                if key == self._preview_key:
                    # Only the trace moved. MapLink (Tweak 1) now emits
                    # session.set_preview on every mouse move so the
                    # cursor tracks a previewed line smoothly without
                    # waiting for the dwell -- re-entering _enter_preview
                    # here on every one of those would rebuild the whole
                    # radargram per move (_show_line's `self.image = None`
                    # then `_render()`), even though the key has not
                    # changed. Measured end to end: 50 moves along a
                    # previewed 1300-trace line, 16.8 ms/move (4.9 ms at
                    # 240 traces) -- the exact renderer thrash the dwell
                    # exists to prevent, moved from the dwell's side to
                    # ours. _enter_preview's other effects (window title/
                    # tooltip, gain strip hidden, channel combo disabled,
                    # _strip_was_visible capture) were all already set
                    # when the preview first entered, and nothing about a
                    # trace move should disturb any of them.
                    self.view.set_cursor(trace)
                    return
                self._enter_preview(key, trace)
            else:
                # Either the preview was cleared, or the pointer is over
                # the line already being worked on -- which is not a
                # preview at all: marking the title as a preview and
                # hiding the gain strip for the line the user is editing
                # would be pure noise, and a re-render of what is already
                # on screen.
                self._exit_preview()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not show the preview of {key!r}: {exc}", Qgis.MessageLevel.Critical)

    def _enter_preview(self, key: str, trace: int) -> None:
        if self._preview_key is None:
            self._strip_was_visible = self.gain_strip.isVisible()
        self._preview_key = key
        self.gain_strip.hide()
        # Spec §3.3: a preview is never a write target. Unlike
        # set_trace/set_selection, session.set_channel has no current_key
        # guard of its own, so this is the only thing standing between a
        # hovered line's channel combo and a permanent change to which
        # channel it renders. Re-enabled in `_open` (promotion, or any
        # later line-open) and in `_exit_preview`.
        self.channel_combo.setEnabled(False)
        self.difference_label.setText("")
        # Finding 7 (M7 walkthrough re-review, third round): the preview
        # marker is the window title/tooltip now (see `_show_line`'s
        # `is_preview` parameter) -- there is no toolbar label left here
        # to set.
        self._show_line(key, is_preview=True)
        self.view.clear_selection()
        self.view.set_cursor(trace)

    def _exit_preview(self) -> None:
        if self._preview_key is None:
            return
        self._preview_key = None
        self.channel_combo.setEnabled(True)
        if self._working_key is None:
            self._clear_view_only()
            return
        self._show_line(self._working_key)
        self.view.set_cursor(self.session.current_trace)
        start, end = self.session.selection
        if start < 0 or end < 0:
            self.view.clear_selection()
        else:
            self.view.set_selection(start, end)
        deferred, self._deferred_strip = self._deferred_strip, None
        if deferred is not None:
            self.show_gain_strip(*deferred)  # not previewing now: takes the normal path
        elif self._strip_was_visible:
            self.gain_strip.show()
        self._strip_was_visible = False

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
        # Finding 4 (M7 final review): while previewing, `self._key` is the
        # previewed line, not the working one -- and a preview must not
        # persist an empty StepStack for a line the user only hovered
        # (spec §3.3). insert=False builds and returns the same usable
        # stack (source attached) without keeping it; see stack_for's own
        # docstring and SiteSession.set_profiles, which needs the same
        # treatment for the same reason.
        stack: StepStack = self.session.stack_for(self._key, insert=self._preview_key is None)
        if stack.source is None:
            return None
        try:
            if self._effective_difference_index >= 0:
                return stack.difference(self._effective_difference_index)
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
        if self._effective_difference_index >= 0 and self._key is not None:
            entries = self.session.stack_for(self._key).entries
            step_text = f"Difference: {entries[self._effective_difference_index][0].name}"
        self.difference_label.setText(step_text)
        self._sync_strip_mapping()

    def _sync_strip_mapping(self) -> None:
        if self.view.transform is not None:
            self.gain_strip.set_time_mapping(self.view.transform, MARGIN_TOP)

    def show_gain_strip(self, points: list[list[float]] | None, owner: Any = None) -> None:
        """Show the strip editing `points`, or hide it (`points is None`, the
        selected step is not a curve, or nothing has rendered yet so there
        is no axis to share).

        `owner` says whose curve `points` is and goes straight through to
        `GainStrip.set_points`, which needs it to tell an echo of the
        strip's own edit (refused mid-drag) from a payload belonging to a
        different curve (the gesture ends and the payload is accepted) --
        see the gain strip module docstring's fourth invariant. It is
        defaulted here, unlike on `set_points` itself, only so the three
        hide calls need not invent a token for a payload that is never
        delivered -- the `points is None` branch returns without reaching
        `set_points` at all. A `None` owner alongside real points would
        still be honoured, and ends any gesture in progress -- the safe
        direction: the corrupting one is keeping a gesture alive across a
        change of curve.

        While a preview is up this is deferred rather than acted on: the
        strip edits a step in the WORKING line's stack and writes on
        drag, so a strip whose curve belongs to a line that is not on
        screen is precisely the C2 configuration (spec §3.3). Deferred
        rather than dropped, because the request can carry a NEW curve
        (the working line finishing a load mid-preview) that
        `_exit_preview` must still honour once the preview ends, rather
        than re-showing whatever was on screen before it started.
        """
        if self._preview_key is not None:
            self._deferred_strip = None if points is None else (points, owner)
            if points is None:
                # An explicit "hide" that arrives mid-preview is still an
                # instruction: without this, _exit_preview's
                # _strip_was_visible branch re-shows the previous curve for
                # a step that is no longer selected.
                self._strip_was_visible = False
            self.gain_strip.hide()
            return
        if points is None or self.view.transform is None:
            self.gain_strip.hide()
            return
        self._sync_strip_mapping()
        self.gain_strip.set_points(points, owner)
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
        if self._preview_key is not None:
            # Spec §3.3: a preview is never a write target. Unlike
            # set_trace/set_selection, session.set_channel has no
            # current_key guard of its own, so this is the only thing
            # standing between a hovered line and a permanent change to
            # which channel it renders. The combo is also disabled while
            # previewing (see `_enter_preview`) so this is a second line
            # of defence, not the only one -- the same shape as every
            # other guard in this file.
            return
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

    def _selection_cleared(self) -> None:
        # Spec §3.3: a preview is never a write target. `_hovered` and
        # `_range_selected` above reach the session with `self._key` --
        # the DISPLAYED key, preview or working -- and let the session's
        # own `current_key` check structurally no-op a write that arrives
        # while a preview is up. `SiteSession.clear_selection()` cannot be
        # routed the same way: it takes no key argument at all, and
        # unconditionally clears whichever line IS `current_key` -- so
        # calling it while previewing would not be rejected, it would
        # reach past the previewed line and clear the WORKING line's real
        # selection from a click the user only meant for the line they
        # were glancing at. Guarded explicitly instead, the same way
        # `_channel_changed` already guards `session.set_channel` (which
        # has the identical gap for the identical reason).
        if self._preview_key is not None or self._working_key is None:
            return
        try:
            self.session.clear_selection()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not clear the selection: {exc}", Qgis.MessageLevel.Critical)

    def _pick(self, trace: int, time_ns: float) -> None:
        if self._preview_key is not None:
            # A preview never authors data (spec §3.3, §4.3). `self._key`
            # is the DISPLAYED line, so without this a shift-click on a
            # previewed radargram would emit a pick for a line the user
            # only hovered. Nothing consumes pick_requested until M8 --
            # this is guarded here, in the change that makes `_key` mean
            # "displayed", rather than left for M8 to discover.
            return
        # I6: guarded like every other slot here, even though nothing
        # connects to `pick_requested` yet. Nothing in Plan 2 does: the
        # pick tool is M8, in Plan 3 ("Pick tool, picks layer, marks
        # layer"), and this signal plus `ProfileView.set_pick_mode()` are
        # the half of it that already exists. Until then a shift-click on
        # the profile emits into nothing, and `set_pick_mode()` has no
        # control wired to it -- picks are authored by editing the
        # `picks` layer on the map canvas with QGIS's own tools. An
        # earlier draft of this comment said "Task 18/19 will"; those
        # tasks were re-scoped to the gain strip and the difference
        # view/presets and never touched picking, and the stale note sent
        # a reader looking for a pick mode that was never built. Verified
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
