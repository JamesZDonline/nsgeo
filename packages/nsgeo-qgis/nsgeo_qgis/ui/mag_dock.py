"""The Mag panel: a magnetometer grid, or every one, mapped and on the canvas.

One scope-and-settings panel in the mould of the Slices panel, without its
GPR machinery. This grid draws the chosen mag grid; Whole site draws every mag
grid that holds a file (plan call P11). The map is drawn on the GUI thread
under the busy cursor and only while the panel is showing (P14): closing the
panel leaves the layer as it was last drawn, and closing the site clears it.

Every choice the user makes is remembered in the survey (`set_mag_view`), the
whole set at once, but never on a site that has no magnetometer grid and no
file, so a GPR-only site saves exactly as before.

Qt slots here guard their own bodies (the plugin module docstring's rule):
what goes wrong is reported through `error` and the status line, never raised.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
from nsgeo.geometry import Grid
from nsgeo.mag import MagFile, MagSetup
from nsgeo.render import colormap_names
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.mag_engine import DEFAULT_MAG_FINISH, MagEngine, MagMosaic, MagSettings
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_layer import MAG_LAYER_NAME, SliceLayer
from nsgeo_qgis.ui.finish_panel import FinishPanel, busy_cursor

DEFAULT_PALETTE = "grey_black_high"
_IMPORT_FIRST = "Import a magnetometer file to see it here."


def draw_mag_layer(dock: MagDock, layer: SliceLayer) -> None:
    """Put the dock's map on `layer`, or clear the layer when there is none."""
    shown = dock.current_map()
    if shown is None:
        layer.clear()
        return
    layer.update_north_up(
        shown.array,
        shown.lattice.geotransform,
        shown.lattice.crs,
        limit=shown.limit,
        centre=shown.centre(),
        colormap_name=dock.palette(),
        unipolar=False,
        subtitle=dock.subtitle(),
        name=MAG_LAYER_NAME,
        own=dock.own_colours_on(),
        own_style=dock.own_style(),
    )


class MagDock(QgsDockWidget):
    #: `current_map()` / `subtitle()` / `palette()` are worth reading again.
    map_changed = pyqtSignal()
    #: Open the mag layer's Symbology page (the plugin has `iface`).
    symbology_requested = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Mag", parent)
        self.setObjectName("nsgeoMagDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.session = session
        self.engine = MagEngine()
        self._scope = "grid"
        self._map: MagMosaic | None = None
        self._status = _IMPORT_FIRST
        self._subtitle = ""
        #: True while the widgets are being set from the session or the grid
        #: list: nothing is remembered or redrawn then.
        self._seeding = False

        body = QWidget(self)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(4, 4, 4, 4)

        scope_row = QHBoxLayout()
        self.grid_scope_button = QPushButton("This grid")
        self.site_scope_button = QPushButton("Whole site")
        self._scope_buttons = QButtonGroup(self)
        self._scope_buttons.setExclusive(True)
        for button in (self.grid_scope_button, self.site_scope_button):
            button.setCheckable(True)
            self._scope_buttons.addButton(button)
            scope_row.addWidget(button)
        self.grid_scope_button.setChecked(True)
        outer.addLayout(scope_row)

        source = QGroupBox("Source")
        source_form = QFormLayout(source)
        self.grid_combo = QComboBox()
        self.grid_combo.setToolTip("Magnetometer grids only. Whole site ignores this choice.")
        self.file_label = QLabel("")
        self.missing_label = QLabel("")
        source_form.addRow("Grid", self.grid_combo)
        source_form.addRow("File", self.file_label)
        source_form.addRow("Missing", self.missing_label)
        outer.addWidget(source)

        resolution = QGroupBox("Resolution")
        resolution_form = QFormLayout(resolution)
        self.cell_spin = QDoubleSpinBox()
        self.cell_spin.setDecimals(3)
        self.cell_spin.setRange(0.025, 2.0)
        self.cell_spin.setSingleStep(0.025)
        self.cell_spin.setValue(MagSettings().cell)
        resolution_form.addRow("Cell (m)", self.cell_spin)
        outer.addWidget(resolution)

        self.finish_panel = FinishPanel(metres_label=True)
        self.finish_panel.set_value(DEFAULT_MAG_FINISH)
        self.finish_panel.set_spacing(MagSetup().spacing_m)
        outer.addWidget(self.finish_panel)

        display = QGroupBox("Display")
        display_form = QFormLayout(display)
        self.colours_combo = QComboBox()
        self.colours_combo.addItems(["nsgeo colours", "my own colours"])
        self.colours_combo.setToolTip(
            "nsgeo colours: the Palette below, centred on the median.\n"
            "My own colours: whatever you set in the mag layer's\n"
            "Layer Properties ▸ Symbology."
        )
        self.symbology_button = QPushButton("Symbology…")
        self.symbology_button.setToolTip("Open the mag layer's Symbology page")
        colours_row = QHBoxLayout()
        colours_row.addWidget(self.colours_combo, 1)
        colours_row.addWidget(self.symbology_button)
        display_form.addRow("Colours", colours_row)
        self.palette_combo = QComboBox()
        self.palette_combo.addItems(colormap_names(unipolar=False))
        self.palette_combo.setCurrentIndex(self.palette_combo.findText(DEFAULT_PALETTE))
        display_form.addRow("Palette", self.palette_combo)
        outer.addWidget(display)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        outer.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        self.setWidget(scroll)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._on_debounce)

        self.grid_scope_button.clicked.connect(lambda: self._on_scope_button("grid"))
        self.site_scope_button.clicked.connect(lambda: self._on_scope_button("site"))
        self.grid_combo.currentIndexChanged.connect(self._on_grid_changed)
        self.cell_spin.valueChanged.connect(self._on_resolution_edited)
        self.finish_panel.edited.connect(self._on_resolution_edited)
        self.palette_combo.currentIndexChanged.connect(self._on_palette_changed)
        self.colours_combo.currentIndexChanged.connect(self._on_colours_changed)
        self.symbology_button.clicked.connect(lambda: self.symbology_requested.emit())
        session.site_opened.connect(self._on_site_opened)
        session.site_closed.connect(self._on_site_closed)
        session.grids_changed.connect(self._on_sources_changed)
        session.mag_changed.connect(self._on_sources_changed)
        if session.is_open:
            self._on_site_opened()
        else:
            self._sync_colours()

    # ---- what the panel shows ---------------------------------------------
    def scope(self) -> str:
        return self._scope

    def settings(self) -> MagSettings:
        return MagSettings(cell=float(self.cell_spin.value()), finish=self.finish_panel.value())

    def palette(self) -> str:
        return self.palette_combo.currentText() or DEFAULT_PALETTE

    def current_map(self) -> MagMosaic | None:
        return self._map

    def status(self) -> str:
        return self._status

    def subtitle(self) -> str:
        return self._subtitle

    def set_scope(self, scope: str) -> None:
        if scope not in ("grid", "site"):
            raise ValueError(f"the Mag panel has no scope {scope!r}")
        self._scope = scope
        self._seeding = True
        try:
            button = self.grid_scope_button if scope == "grid" else self.site_scope_button
            button.setChecked(True)
        finally:
            self._seeding = False
        self._remember()
        self.refresh()

    def show_grid(self, grid_id: str) -> None:
        """Choose `grid_id` in the Grid combo, as navigation: the scope is
        unchanged and nothing is remembered (only the author's own change in
        this panel is). A slot: never raises."""
        try:
            index = self.grid_combo.findData(grid_id)
            if index < 0:
                return
            self._seeding = True
            try:
                self.grid_combo.setCurrentIndex(index)
            finally:
                self._seeding = False
            self._sync_source()
            self.refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self.error.emit(f"could not show the mag grid: {exc}")

    # ---- drawing ----------------------------------------------------------
    def refresh(self) -> None:
        """Make the map for what is chosen, then announce it. Only while the
        panel is showing; a closed site always clears."""
        try:
            if not self.session.is_open:
                self._set_map(None, "", "")
                return
            if not self.isVisible():
                return
            with busy_cursor():
                self._compute()
        except Exception as exc:  # noqa: BLE001 -- reached from signal slots
            message = f"Could not draw the mag map: {exc}"
            _log(message)
            self._set_map(None, message, "")
            self.error.emit(message)

    def _items(self) -> tuple[list[tuple[MagFile, Grid]], str]:
        """The `(file, grid)` pairs to draw, and the status when there are none."""
        session = self.session
        grids = {g.id: g for g in session.mag_grids()}
        if self._scope == "grid":
            grid_id = self.grid_combo.currentData()
            if grid_id is None or grid_id not in grids:
                return [], _IMPORT_FIRST
            mag = session.mag_file_on(grid_id)
            if mag is None:
                return [], f"Grid {grid_id} has no magnetometer file yet."
            return [(mag, grids[grid_id])], ""
        items = []
        for grid in session.mag_grids():
            mag = session.mag_file_on(grid.id)
            if mag is not None:
                items.append((mag, grid))
        return items, ("" if items else _IMPORT_FIRST)

    def _compute(self) -> None:
        items, status = self._items()
        shown = self.engine.mosaic(items, self.settings()) if items else None
        if shown is None:
            self._set_map(None, status, "")
            return
        if self._scope == "grid":
            subtitle = f"{items[0][1].id} · {items[0][0].path.name}"
        else:
            subtitle = f"{len(shown.grids)} mag grids"
        if shown.left_out:
            status = (
                "Left out of the whole site, being in another CRS: "
                + ", ".join(shown.left_out)
                + "."
            )
        self._set_map(shown, status, subtitle)

    def _set_map(self, shown: MagMosaic | None, status: str, subtitle: str) -> None:
        self._map = shown
        self._status = status
        self._subtitle = subtitle
        self.status_label.setText(status)
        self.map_changed.emit()

    # ---- remembering ------------------------------------------------------
    def _has_mag(self) -> bool:
        return bool(self.session.mag_grids() or self.session.mag_files())

    def _remember(self) -> None:
        """Write every choice to the survey, unless the site has never had mag."""
        if self._seeding or not self.session.is_open or not self._has_mag():
            return
        fields: dict[str, Any] = {
            "scope": self._scope,
            "cell": float(self.cell_spin.value()),
            "finish": dataclasses.asdict(self.finish_panel.value()),
            "palette": self.palette(),
        }
        grid_id = self.grid_combo.currentData()
        if grid_id is not None:
            fields["grid"] = grid_id
        self.session.set_mag_view(**fields)

    def _restore(self) -> None:
        """Set the widgets from what the survey remembers; announces nothing."""
        view = self.session.mag_view()
        self._seeding = True
        try:
            self._scope = (
                view.get("scope", "grid") if view.get("scope") in ("grid", "site") else "grid"
            )
            (
                self.grid_scope_button if self._scope == "grid" else self.site_scope_button
            ).setChecked(True)
            cell = view.get("cell")
            self.cell_spin.setValue(
                float(cell) if isinstance(cell, (int, float)) else MagSettings().cell
            )
            finish = view.get("finish")
            self.finish_panel.set_value(
                DEFAULT_MAG_FINISH.updated(finish if isinstance(finish, dict) else {})
            )
            index = self.palette_combo.findText(str(view.get("palette", DEFAULT_PALETTE)))
            self.palette_combo.setCurrentIndex(
                index if index >= 0 else self.palette_combo.findText(DEFAULT_PALETTE)
            )
            self._fill_grids(prefer=view.get("grid"))
        finally:
            self._seeding = False

    # ---- the session's changes --------------------------------------------
    def _fill_grids(self, prefer: object = None) -> None:
        """List the mag grids, keeping the chosen one when it is still there."""
        keep = prefer if prefer is not None else self.grid_combo.currentData()
        blocked = self.grid_combo.blockSignals(True)
        try:
            self.grid_combo.clear()
            if self.session.is_open:
                for grid in self.session.mag_grids():
                    self.grid_combo.addItem(grid.id, grid.id)
            index = self.grid_combo.findData(keep) if keep is not None else -1
            if index >= 0:
                self.grid_combo.setCurrentIndex(index)
        finally:
            self.grid_combo.blockSignals(blocked)
        self._sync_source()

    def _sync_source(self) -> None:
        """The File and Missing rows, and the Interpolation panel's spacing."""
        mag = None
        grid_id = self.grid_combo.currentData()
        if self.session.is_open and grid_id is not None:
            mag = self.session.mag_file_on(grid_id)
        if mag is None:
            self.file_label.setText("none")
            self.missing_label.setText("")
            spacing = (
                (self.session.mag_setup() or MagSetup()).spacing_m if self.session.is_open else None
            )
            self.finish_panel.set_spacing(spacing)
            return
        self.file_label.setText(mag.path.name)
        try:
            missing = int(np.isnan(mag.readings()).sum())
        except Exception as exc:  # noqa: BLE001 -- the count is a courtesy
            _log(f"could not count missing readings in {mag.path.name}: {exc}")
            missing = 0
        self.missing_label.setText(str(missing) if missing else "none")
        self.finish_panel.set_spacing(mag.setup.spacing_m)

    def _on_site_opened(self) -> None:
        try:
            self._restore()
            self._sync_source()
            self._sync_colours()
            self.refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self.error.emit(f"could not set up the Mag panel: {exc}")

    def _on_site_closed(self) -> None:
        try:
            self.engine.clear()
            self._fill_grids()
            self._sync_colours()
            self._set_map(None, _IMPORT_FIRST, "")
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self.error.emit(f"could not close the Mag panel: {exc}")

    def _on_sources_changed(self) -> None:
        """`grids_changed` / `mag_changed`: a grid, its placement or its file moved."""
        try:
            self._fill_grids()
            self._sync_colours()
            self.refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self.error.emit(f"could not update the Mag panel: {exc}")

    def showEvent(self, event: Any) -> None:  # noqa: N802 -- Qt override
        super().showEvent(event)
        try:
            self.refresh()
        except Exception as exc:  # noqa: BLE001 -- a Qt event handler
            _log(f"could not draw the mag map on showing: {exc}")

    # ---- the user's changes ------------------------------------------------
    def _on_scope_button(self, scope: str) -> None:
        try:
            if scope != self._scope:
                self.set_scope(scope)
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self.error.emit(f"could not change the mag scope: {exc}")

    def _on_grid_changed(self, _index: int) -> None:
        try:
            if self._seeding:
                return
            self._sync_source()
            self._remember()
            self.refresh()
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self.error.emit(f"could not change the mag grid: {exc}")

    def _on_resolution_edited(self, *_args: object) -> None:
        """Cell or interpolation: remembered now, redrawn when the edits pause."""
        try:
            if self._seeding:
                return
            self._remember()
            self._debounce.start()
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self.error.emit(f"could not change the mag resolution: {exc}")

    def _on_debounce(self) -> None:
        try:
            self.refresh()
        except Exception as exc:  # noqa: BLE001 -- a QTimer slot
            self.error.emit(f"could not draw the mag map: {exc}")

    def _on_palette_changed(self, _index: int) -> None:
        try:
            if self._seeding:
                return
            self._remember()
            if self.isVisible() and self._map is not None:
                self.map_changed.emit()
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self.error.emit(f"could not change the mag palette: {exc}")

    # ---- the user's own QGIS colours (#180) --------------------------------
    def own_colours_on(self) -> bool:
        """Whether the map wears the user's own QGIS colours. One choice for
        both scopes: it is the same field in nT either way (plan call P9)."""
        if not self.session.is_open:
            return False
        return bool(self.session.slice_colours("mag").get("own", False))

    def own_style(self) -> str | None:
        if not self.session.is_open:
            return None
        style = self.session.slice_colours("mag").get("style")
        return style if isinstance(style, str) else None

    def set_own_style(self, text: str) -> None:
        """`SliceLayer.own_style_changed`: remember the edited (or newly seeded)
        style. A slot: never raises."""
        try:
            if self.session.is_open and self.own_colours_on():
                self.session.set_slice_colours("mag", style=text)
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise
            _log(f"could not remember the mag colours: {exc}")

    def _on_colours_changed(self, index: int) -> None:
        try:
            if self.session.is_open and self._has_mag():
                self.session.set_slice_colours("mag", own=index == 1)
            self._sync_colours()
            if self.isVisible() and self._map is not None:
                self.map_changed.emit()
        except Exception as exc:  # noqa: BLE001 -- a slot on currentIndexChanged
            self.error.emit(f"could not change the mag colours: {exc}")

    def _sync_colours(self) -> None:
        own = self.own_colours_on()
        blocked = self.colours_combo.blockSignals(True)
        try:
            self.colours_combo.setCurrentIndex(1 if own else 0)
        finally:
            self.colours_combo.blockSignals(blocked)
        self.colours_combo.setEnabled(self.session.is_open and self._has_mag())
        self.symbology_button.setEnabled(own)
