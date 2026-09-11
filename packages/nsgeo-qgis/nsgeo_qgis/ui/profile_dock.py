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
e.g. a bandpass whose high cut exceeds Nyquist) is turned into the `error`
signal instead of an exception, so a bad step leaves the previous render
on screen with a message rather than blanking the view.
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
from nsgeo_qgis.ui.profile_view import ProfileView


def velocity_source(session: SiteSession, key: str) -> str:
    """Name whichever tier `nsgeo.velocity.resolve_velocity` actually used:
    "line override", "Grid <id>", or a header-dielectric fallback.

    This mirrors `resolve_velocity`'s own precedence (line override, then
    the grid's model, then the header's dielectric) -- but does not
    *re-decide* it. `resolve_velocity` returns `line.velocity`/`grid.velocity`
    by identity (no copy) when one of those tiers applies, and only builds a
    fresh `VelocityModel` for the header-fallback tier; comparing the
    object `resolve_velocity` actually returned against those two candidates
    (`is`, not `==`) names the tier it used, without this function
    independently re-checking "is `line.velocity` not None" itself.

    That matters because GitHub issue #4 is going to change this precedence
    (grid velocity becomes optional in a different way): two copies of the
    same "line, then grid, then header" cascade -- one here, one in
    `resolve_velocity` -- would drift the moment either side is edited and
    the other is not, and a label that confidently names the wrong tier is
    worse than no label at all. Deriving it from `resolve_velocity`'s own
    return value instead means this can never name the wrong tier, whatever
    the precedence becomes -- there is nothing left here to forget to
    update.
    """
    line = session.line_for_key(key)
    grid = session.grid_for_line(line)
    resolved = resolve_velocity(line, grid)
    if resolved is line.velocity:
        return "line override"
    if grid is not None and resolved is grid.velocity:
        return f"Grid {grid.id}"
    return f"header ε {line.header.epsr:g}"


class ProfileDock(QgsDockWidget):
    error = pyqtSignal(str)
    pick_requested = pyqtSignal(str, int, float)

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
        self.percentile_slider.setRange(900, 1000)
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
        # might build one (see the module docstring).
        self.view = ProfileView(body)
        layout.addWidget(self.view, 1)
        self.setWidget(body)

        self.percentile_slider.valueChanged.connect(self._display_changed)
        self.colormap_combo.currentTextChanged.connect(self._display_changed)
        self.fit_button.clicked.connect(self.view.fit)
        self.one_to_one_button.clicked.connect(self.view.one_to_one)
        self.channel_combo.currentIndexChanged.connect(self._channel_changed)
        self.view.trace_hovered.connect(self._hovered)
        self.view.range_selected.connect(self._range_selected)
        self.view.pick_requested.connect(self._pick)

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
        self._key = key or None
        self._difference_index = -1
        self.difference_label.setText("")
        if not key:
            self._clear_view_only()
            return
        line = self.session.line_for_key(key)
        label = getattr(line.placement, "label", None) or line.path.stem
        self.setWindowTitle(f"nsgeo Profile · {label} · {line.n_traces} traces")
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
        self._key = None
        try:
            self._clear_view_only()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not clear the profile view: {exc}", Qgis.MessageLevel.Critical)

    def _clear_view_only(self) -> None:
        self.image = None
        self.view.clear()
        self.setWindowTitle("nsgeo Profile")
        self.velocity_label.setText("")
        self.channel_combo.hide()

    # ---- rendering -------------------------------------------------------
    def set_difference_index(self, index: int) -> None:
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
            self.error.emit(str(exc))
            if self._difference_index >= 0:
                self._difference_index = -1
                self.difference_label.setText("")
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

    def _refresh_velocity(self, *_: Any) -> None:
        if self._key is None or not self.session.is_open:
            return
        try:
            model: VelocityModel = self.session.resolved_velocity(self._key)
            label = velocity_source(self.session, self._key)
        except KeyError:
            return
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not resolve the line's velocity: {exc}", Qgis.MessageLevel.Critical)
            return
        self.view.set_velocity(model)
        self.velocity_label.setText(f"v = {model.surface_velocity:.3f} m/ns ({label})")

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
        if self._key is not None:
            self.pick_requested.emit(self._key, trace, time_ns)
