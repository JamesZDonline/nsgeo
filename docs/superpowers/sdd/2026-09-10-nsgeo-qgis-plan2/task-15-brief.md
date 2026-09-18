### Task 15: Profile dock and the M5 checkpoint

The viewer bound to the session: opens the current line, shows header-derived axes immediately and the image when samples arrive, re-renders on stack changes, and carries the display-gain controls. Ends M5: first sight of real data.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Consumes: `SiteSession`, `ProfileView`, `RadargramImage`, `colormap_names`, `resolve_velocity`
- Produces: `ProfileDock(session, parent=None)` with `view: ProfileView`, `percentile_slider: QSlider` (900–1000, tenths of a percent), `percentile_label`, `colormap_combo`, `fit_button`, `one_to_one_button`, `channel_combo`, `velocity_label`, `difference_label`, `current_radargram() -> Radargram | None`, `set_difference_index(int)` (−1 = result; used by Task 19), `percentile -> float`, `colormap_name -> str`, `image: RadargramImage | None`, signals `error(str)`, `pick_requested(str, int, float)`; `velocity_source(session, key) -> str`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.velocity import VelocityModel
from plugin_testing import synthetic_dzt

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.profile_dock import ProfileDock, velocity_source

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.08))


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
    return session, dock, key, line


def test_opening_shows_axes_and_loading_before_samples_arrive(opened):
    session, dock, key, line = opened
    assert "FILE__001" in dock.windowTitle()
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.profile_dock'`

- [ ] **Step 3: Implement the dock**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:

```python
"""The profile dock: viewer plus display-gain controls, bound to the session.

Display gain lives here, not in the processing dock, because it changes the
colour mapping and never the data.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import Radargram, StepStack
from nsgeo.render import DEFAULT_COLORMAP, colormap_names
from nsgeo.velocity import VelocityModel
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

from nsgeo_qgis.render.qimage import RadargramImage
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.profile_view import ProfileView


def velocity_source(session: SiteSession, key: str) -> str:
    line = session.line_for_key(key)
    if line.velocity is not None:
        return "line override"
    grid = session.grid_for_line(line)
    if grid is not None and grid.velocity is not None:
        return f"Grid {grid.id}"
    return f"header ε {line.header.epsr:g}"


class ProfileDock(QgsDockWidget):
    error = pyqtSignal(str)
    pick_requested = pyqtSignal(str, int, float)

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Profile", parent)
        self.setObjectName("nsgeoProfileDock")
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)
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

    # ---- display settings -------------------------------------------------
    @property
    def percentile(self) -> float:
        return self.percentile_slider.value() / 10.0

    @property
    def colormap_name(self) -> str:
        return self.colormap_combo.currentText()

    def _display_changed(self, *_: Any) -> None:
        self.percentile_label.setText(f"{self.percentile:.1f} %")
        if self.image is not None:
            self.image = self.image.with_display(self.percentile, self.colormap_name)
            self.view.set_image(self.image.image)

    # ---- session events ---------------------------------------------------
    def _on_line_opened(self, key: str) -> None:
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
                line.n_traces, line.header.n_samples, line.header.position_ns, line.header.dt_ns, line.distance_along()
            )
            self.view.set_image(None)
        self._refresh_velocity()

    def _on_line_loaded(self, key: str) -> None:
        if key == self._key:
            profiles = self.session.profiles_for(key) or []
            self._configure_channels(len(profiles))
            self._render()

    def _on_stack_changed(self, key: str) -> None:
        if key == self._key:
            self._render()

    def _on_trace_changed(self, key: str, index: int) -> None:
        if key == self._key:
            self.view.set_cursor(index)

    def _on_selection_changed(self, key: str, a: int, b: int) -> None:
        if key == self._key:
            self.view.set_selection(a, b)

    def _clear(self) -> None:
        self._key = None
        self._clear_view_only()

    def _clear_view_only(self) -> None:
        self.image = None
        self.view.clear()
        self.setWindowTitle("nsgeo Profile")
        self.velocity_label.setText("")
        self.channel_combo.hide()

    # ---- rendering --------------------------------------------------------
    def set_difference_index(self, index: int) -> None:
        self._difference_index = index
        self._render()

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
        if self._key is not None:
            line = self.session.line_for_key(self._key)
            distance = line.distance_along() if rg.n_traces == line.n_traces else None
        else:
            distance = None
        keep_window = self.view.transform is not None and self.view.transform.n_traces == rg.n_traces
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
        except KeyError:
            return
        self.view.set_velocity(model)
        self.velocity_label.setText(
            f"v = {model.surface_velocity:.3f} m/ns ({velocity_source(self.session, self._key)})"
        )

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
        if self._key is not None and index >= 0:
            self.session.set_channel(self._key, index)

    # ---- viewer events ----------------------------------------------------
    def _hovered(self, trace: int) -> None:
        if self._key is not None:
            self.session.set_trace(self._key, trace)

    def _range_selected(self, a: int, b: int) -> None:
        if self._key is not None:
            self.session.set_selection(self._key, a, b)

    def _pick(self, trace: int, time_ns: float) -> None:
        if self._key is not None:
            self.pick_requested.emit(self._key, trace, time_ns)
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py` `initGui`, after the survey dock:

```python
        self.profile_dock = ProfileDock(self.session, main)
        self.profile_dock.error.connect(lambda msg: self.message(msg, Qgis.MessageLevel.Warning))
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.profile_dock)
        self.docks.append(self.profile_dock)
```

with `from nsgeo_qgis.ui.profile_dock import ProfileDock`, `self.profile_dock: ProfileDock | None = None` in `__init__`, and `self.profile_dock = None` in `unload`.

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: profile dock bound to the session

Opens the current line with header-derived axes before samples arrive,
renders when they do, re-renders on stack changes with axes following
the result (time_zero crops), and carries the display-gain controls
that never touch the stack. Step errors reach the message bar."
```

**M5 checkpoint (manual, 5 minutes).** Reload the plugin, open the site from M4, click FILE__001 in the tree. The profile dock shows axes at once and the raw radargram within a second: a dominant direct-wave band at the top, mid-grey below, exactly like the raw render in the Lavish mock. Drag the display-gain slider: the image remaps instantly. Wheel over the image: zoom about the cursor; middle-drag: pan; Fit and 1:1 restore. Hover: the status readout is not present yet (Plan 3), but nothing errors. The depth axis on the right starts at about −0.44 m because time zero has not been applied. Click another line: the viewer switches and the previous line reopens instantly from cache.

---

