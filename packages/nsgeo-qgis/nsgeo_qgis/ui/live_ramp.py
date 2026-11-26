"""Move a slice's colour-ramp stops and watch it recolour as you drag (#183).

QGIS's own Select Color Ramp dialog (`QgsGradientColorRampDialog`) emits
`changed` each time a stop moves, but QGIS opens it modally and reads it only
on OK. Here it is shown modeless instead (`show()`, not `exec()`), and each
`changed` puts the ramp on the slice layer at once (`own_colours.set_ramp`).
The range and min/max settings stay as they are.

The layer's own style signal then reports the edit like any other
(`SliceLayer.own_style_changed`), so the ramp is remembered with the survey as
it moves. OK keeps it. Cancel puts back the ramp the dialog opened with, over
whatever range the slice has by then.

Under the stop editor nsgeo adds **Fewer stops**: the ramp redrawn with as
many stops as the box beside it says, as close to the ramp as that many
allow (`own_colours.fewer_stops`). A ramp of hundreds of stops, such as
QGIS's Turbo, becomes a handful to drag.

GUI thread only. Every slot guards its own body (see `plugin.py`'s docstring).
"""

from __future__ import annotations

from collections.abc import Callable

from qgis.core import QgsGradientColorRamp, QgsRasterLayer
from qgis.gui import QgsGradientColorRampDialog
from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import QHBoxLayout, QPushButton, QSpinBox, QWidget

from nsgeo_qgis import own_colours
from nsgeo_qgis.log import log as _log


class LiveRamp(QObject):
    """At most one live ramp dialog over the slice layer.

    `layer` returns the slice layer while it wears the user's own colours,
    else None. It is asked again at each change, so the edits land on
    whichever layer shows the slice now.
    """

    def __init__(
        self,
        layer: Callable[[], QgsRasterLayer | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._layer = layer
        self._parent = parent
        self._original: QgsGradientColorRamp | None = None
        self.dialog: QgsGradientColorRampDialog | None = None
        #: The Fewer stops row, while the dialog is open.
        self.stops_spin: QSpinBox | None = None
        self.fewer_button: QPushButton | None = None

    def open(self) -> bool:
        """Show the dialog on the slice's ramp, or bring the open one to the
        front. False when the slice's style has no gradient ramp to edit."""
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return True
        layer = self._layer()
        ramp = own_colours.source_ramp(layer)
        if ramp is None:
            return False
        self._original = ramp.clone()
        dialog = QgsGradientColorRampDialog(ramp, self._parent)
        dialog.setWindowTitle(own_colours.ramp_title(layer))
        dialog.changed.connect(self._on_changed)
        dialog.rejected.connect(self._on_rejected)
        dialog.finished.connect(self._on_finished)
        self.dialog = dialog
        self._add_fewer_stops(dialog)
        dialog.show()
        return True

    def follow(self) -> None:
        """Retitle the dialog for the slice on screen: its range moves with a
        computed min/max. A no-op with no dialog open."""
        if self.dialog is not None:
            self.dialog.setWindowTitle(own_colours.ramp_title(self._layer()))

    def keep_and_close(self) -> None:
        """Close the dialog as OK would: the slice keeps the ramp as it is."""
        if self.dialog is not None:
            self.dialog.accept()

    def cancel(self) -> None:
        """Close the dialog as Cancel would: the ramp it opened with goes back."""
        if self.dialog is not None:
            self.dialog.reject()

    def _add_fewer_stops(self, dialog: QgsGradientColorRampDialog) -> None:
        """The Fewer stops row, put just under QGIS's stop editor."""
        row = QWidget(dialog)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        spin = QSpinBox(row)
        spin.setRange(2, 20)
        spin.setValue(7)
        spin.setSuffix(" stops")
        button = QPushButton("Fewer stops", row)
        button.setToolTip(
            "Redraw the ramp with this many stops, ends included,\n"
            "as close to it as that many allow."
        )
        button.clicked.connect(self._on_fewer_stops)
        layout.addWidget(button)
        layout.addWidget(spin)
        layout.addStretch(1)
        outer = dialog.layout()
        editor = dialog.findChild(QWidget, "mStopEditor")
        at = outer.indexOf(editor) + 1 if editor is not None else outer.count() - 1
        outer.insertWidget(max(at, 0), row)
        self.stops_spin, self.fewer_button = spin, button

    def _on_fewer_stops(self) -> None:
        try:
            if self.dialog is None or self.stops_spin is None:
                return
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                fewer = own_colours.fewer_stops(self.dialog.ramp(), self.stops_spin.value())
            finally:
                QGuiApplication.restoreOverrideCursor()
            self.dialog.setRamp(fewer)  # emits `changed`: the slice follows
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise
            _log(f"could not refit the colour ramp: {exc}")

    def _put(self, ramp: QgsGradientColorRamp) -> None:
        layer = self._layer()
        if layer is not None and own_colours.set_ramp(layer, ramp):
            layer.triggerRepaint()

    def _on_changed(self) -> None:
        try:
            if self.dialog is not None:
                self._put(self.dialog.ramp())
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise
            _log(f"could not recolour the slice: {exc}")

    def _on_rejected(self) -> None:
        try:
            if self._original is not None:
                self._put(self._original)
        except Exception as exc:  # noqa: BLE001 -- a slot must never raise
            _log(f"could not put the slice's colour ramp back: {exc}")

    def _on_finished(self, _result: int) -> None:
        dialog, self.dialog, self._original = self.dialog, None, None
        self.stops_spin = self.fewer_button = None
        if dialog is not None:
            dialog.deleteLater()
