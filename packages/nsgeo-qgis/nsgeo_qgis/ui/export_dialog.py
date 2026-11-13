"""The GeoTIFF export dialog: where to save, the export cell and pixel, and what
will be written.

It never builds an export itself. `preview(cell, pixel)` is injected and says
what that choice would write and hold; the dialog shows it and refuses Export,
with the reason in the group, when the memory estimate is over budget or the
disk is too small. Both checks run before anything starts.

A target (or its style file or coverage companion) that is already a layer in
the project is asked about in an in-dialog strip, not a nested modal: Replace
accepts and `layers_to_replace()` names what the caller must remove first.
"""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from qgis.core import QgsMapLayer, QgsProject
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.slice_export import coverage_path
from nsgeo_qgis.slices_plan import (
    EXPORT_BUDGET_BYTES,
    ExportPreview,
    export_refusal,
    finest_fits,
    format_bytes,
    name_list,
    summary_lines,
)

#: Free space must cover the estimate with this margin (the temporary files and
#: the overviews take more than the raw bands).
DISK_MARGIN = 1.2
#: Rapid spin changes compute the estimate once, this long after the last.
DEBOUNCE_MS = 150
#: The largest export cell offered, metres.
MAX_CELL_M = 100.0
MIN_PIXEL_M = 0.001
#: The summary group's last row, kept for the reason an export is refused.
_REASON_ROW = 99


@dataclass(frozen=True)
class ExportChoice:
    path: Path
    cell: float
    pixel: float


def target_paths(path: Path, coverage: bool = True) -> list[Path]:
    """The files an export to `path` writes: the raster and its style file, and, when
    `coverage` is asked for, the coverage companion with its own."""
    paths = [path, path.with_suffix(".qml")]
    if coverage:
        companion = coverage_path(path)
        paths += [companion, companion.with_suffix(".qml")]
    return paths


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def targets_in_use(project: QgsProject, paths: Iterable[Path]) -> list[QgsMapLayer]:
    """The project's layers whose source is any of `paths`."""
    wanted = {_norm(p) for p in paths}
    return [
        layer
        for layer in project.mapLayers().values()
        if layer.source() and _norm(layer.source().split("|")[0]) in wanted
    ]


def _free_bytes(path: Path) -> int | None:
    """Free space where `path` would be written, or None when it can't be read."""
    folder = path.parent
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    try:
        return int(shutil.disk_usage(folder).free)
    except OSError:
        return None


def _ceil_mm(value: float) -> float:
    return math.ceil(value * 1000 - 1e-6) / 1000


class ExportDialog(QDialog):
    def __init__(
        self,
        preview: Callable[[float, float], ExportPreview],
        cell_floor: float,
        live_cell: float,
        default_path: str = "",
        project: QgsProject | None = None,
        parent: QWidget | None = None,
        writes_coverage: bool = True,
    ) -> None:
        super().__init__(parent)
        self._writes_coverage = writes_coverage
        self.setWindowTitle("Export GeoTIFF")
        self._preview_fn = preview
        self._project = project if project is not None else QgsProject.instance()
        self._rows: list[tuple[str, str]] = []
        self._replace: list[QgsMapLayer] = []
        self._tracking = True  # the pixel follows the cell until it is set finer

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)

        self.path_edit = QLineEdit(default_path)
        browse = QPushButton("…")
        browse.setToolTip("Choose where to save the file.")
        browse.setFixedWidth(32)
        grid.addWidget(QLabel("Save to"), 0, 0)
        grid.addWidget(self.path_edit, 0, 1)
        grid.addWidget(browse, 0, 2)

        floor = _ceil_mm(cell_floor)
        self.cell_spin = QDoubleSpinBox()
        self.cell_spin.setDecimals(3)
        self.cell_spin.setSingleStep(0.005)
        self.cell_spin.setSuffix(" m")
        self.cell_spin.setRange(floor, max(MAX_CELL_M, floor))
        self.cell_spin.setValue(live_cell)
        self.pixel_spin = QDoubleSpinBox()
        self.pixel_spin.setDecimals(4)  # 0.0125 m is a natural half of 0.025 m
        self.pixel_spin.setSingleStep(0.005)
        self.pixel_spin.setSuffix(" m")
        self.pixel_spin.setMinimum(MIN_PIXEL_M)
        self.pixel_spin.setMaximum(self.cell_spin.value())
        self.pixel_spin.setValue(self.cell_spin.value())
        self.cell_spin.setToolTip("How finely each grid's slice is rebuilt.")
        self.pixel_spin.setToolTip("The size of one pixel in the file; never larger than the cell.")
        grid.addWidget(QLabel("Export cell"), 1, 0)
        grid.addWidget(self.cell_spin, 1, 1)
        grid.addWidget(self._hint(f"live {live_cell:g} m · finest {floor:g} m"), 1, 2, 1, 1)
        grid.addWidget(QLabel("Export pixel"), 2, 0)
        grid.addWidget(self.pixel_spin, 2, 1)
        grid.addWidget(self._hint("the cell, or finer"), 2, 2, 1, 1)
        grid.setColumnStretch(1, 1)

        self.summary_group = QGroupBox("What will be written")
        self._summary_layout = QGridLayout(self.summary_group)
        self._summary_layout.setColumnStretch(1, 1)
        self.reason_label = QLabel("")
        self.reason_label.setWordWrap(True)
        self.reason_label.setStyleSheet("font-weight: bold;")
        self._summary_layout.addWidget(self.reason_label, _REASON_ROW, 0, 1, 2)
        layout.addWidget(self.summary_group)

        self.confirm_strip = QFrame()
        self.confirm_strip.setFrameShape(QFrame.Shape.StyledPanel)
        strip = QVBoxLayout(self.confirm_strip)
        self.confirm_label = QLabel("")
        self.confirm_label.setWordWrap(True)
        strip.addWidget(self.confirm_label)
        strip_buttons = QHBoxLayout()
        strip_buttons.addStretch()
        self.replace_button = QPushButton("Replace")
        self.keep_button = QPushButton("Cancel")
        strip_buttons.addWidget(self.replace_button)
        strip_buttons.addWidget(self.keep_button)
        strip.addLayout(strip_buttons)
        self.confirm_strip.hide()
        layout.addWidget(self.confirm_strip)

        self.buttons = QDialogButtonBox()
        self.export_button = self.buttons.addButton(
            "Export", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(self.buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh_now)
        self.cell_spin.valueChanged.connect(self._on_cell_changed)
        self.pixel_spin.valueChanged.connect(self._on_pixel_changed)
        self.path_edit.textChanged.connect(self._schedule)
        browse.clicked.connect(self._browse)
        self.export_button.clicked.connect(self._on_export)
        self.replace_button.clicked.connect(self._on_replace)
        self.keep_button.clicked.connect(self._on_keep)
        self.buttons.rejected.connect(self.reject)

        self.refresh_now()

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setEnabled(False)
        return label

    # -- fields ---------------------------------------------------------------

    def _on_cell_changed(self, value: float) -> None:
        was_cell = self._tracking
        self.pixel_spin.setMaximum(value)  # clamps a pixel that is now too coarse
        if was_cell:
            self.pixel_spin.setValue(value)
        self._schedule()

    def _on_pixel_changed(self, value: float) -> None:
        self._tracking = value >= self.cell_spin.value() - 1e-9
        self._schedule()

    def _schedule(self, *_: object) -> None:
        self.confirm_strip.hide()
        self.export_button.setEnabled(False)  # stale until the estimate is redone
        self._timer.start()

    def _browse(self) -> None:
        start = self.path_edit.text() or str(Path.home())
        name, _ = QFileDialog.getSaveFileName(
            self, "Export GeoTIFF", start, "GeoTIFF (*.tif *.tiff)"
        )
        if name:
            self.path_edit.setText(name)

    def result_settings(self) -> ExportChoice:
        path = Path(self.path_edit.text().strip()).expanduser()
        if not path.suffix:
            path = path.with_suffix(".tif")
        return ExportChoice(path, self.cell_spin.value(), self.pixel_spin.value())

    def layers_to_replace(self) -> list[QgsMapLayer]:
        """The layers the caller must remove before writing, after Replace."""
        return list(self._replace)

    def summary_rows(self) -> list[tuple[str, str]]:
        return list(self._rows)

    # -- the summary and its two checks ---------------------------------------

    def refresh_now(self) -> None:
        """Recompute the summary and the checks for the current fields."""
        self._timer.stop()
        cell, pixel = self.cell_spin.value(), self.pixel_spin.value()
        preview = self._preview_fn(cell, pixel)
        rows = summary_lines(preview)
        text = self.path_edit.text().strip()
        path = self.result_settings().path if text else Path.home() / "x.tif"
        free = _free_bytes(path)
        rows.append(("Disk", "unknown" if free is None else f"{format_bytes(free)} free"))
        self._set_rows(rows)

        reasons = []
        if preview.held_bytes > EXPORT_BUDGET_BYTES:
            finest_cell, finest_pixel = finest_fits(
                lambda c, p: self._preview_fn(c, p).held_bytes, cell, pixel, EXPORT_BUDGET_BYTES
            )
            reasons.append(
                export_refusal(preview.held_bytes, EXPORT_BUDGET_BYTES, finest_cell, finest_pixel)
            )
        if free is not None and free < DISK_MARGIN * preview.file_bytes:
            need = format_bytes(round(DISK_MARGIN * preview.file_bytes))
            reasons.append(
                f"Not enough free disk space: about {need} needed, {format_bytes(free)} free."
            )
        self.reason_label.setText("\n".join(reasons))
        self.reason_label.setVisible(bool(reasons))
        self.export_button.setEnabled(not reasons and bool(text))

    def _set_rows(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows
        lay = self._summary_layout
        for item in [lay.itemAt(i) for i in range(lay.count())]:
            widget = item.widget()
            if widget is not None and widget is not self.reason_label:
                lay.removeWidget(widget)
                widget.deleteLater()
        for i, (key, value) in enumerate(rows):
            name = QLabel(key)
            name.setAlignment(Qt.AlignmentFlag.AlignTop)
            name.setEnabled(False)
            body = QLabel(value)
            body.setWordWrap(True)
            lay.addWidget(name, i, 0)
            lay.addWidget(body, i, 1)

    # -- accepting ------------------------------------------------------------

    def _on_export(self) -> None:
        if self._timer.isActive():
            self.refresh_now()
            if not self.export_button.isEnabled():
                return  # the latest numbers do not fit
        in_use = targets_in_use(
            self._project, target_paths(self.result_settings().path, self._writes_coverage)
        )
        if not in_use:
            self._replace = []
            self.accept()
            return
        self._replace = in_use
        names = name_list([layer.name() for layer in in_use])
        if len(in_use) == 1:
            text = (
                f"{names} is open in this project. Replace it? "
                "The layer is removed and added again when the export finishes."
            )
        else:
            text = (
                f"{names} are open in this project. Replace them? "
                "The layers are removed and added again when the export finishes."
            )
        self.confirm_label.setText(text)
        self.confirm_strip.show()

    def _on_keep(self) -> None:
        self._replace = []
        self.confirm_strip.hide()

    def _on_replace(self) -> None:
        self.accept()
