"""Edit a grid's lines in one table, with a panel for changing many at once
(line editing spec §4.1).

Label, Offset, Dir, Start and Grid are editable; Traces, Length, Along, Picks
and Note come from the line. Start is editable here although it is not in
ImportDialog: an import derives every Start from the direction and the grid's
length, so a hand-typed one would be lost on the next replan, while this table
holds each row's edit as a `LineEdit` against the placement it saw, so a typed
Start sticks (and a flip or a move still keeps the line's inset from its edge,
by the same rule, because they all go through `line_edit.py`).

Modeless, like ImportDialog (plugin.py's open_edit_lines_dialog is the
pattern): show() plus the finished signal, never exec(). The toolbar and the
Survey dock stay clickable while it is open, so the site can close or be
replaced, the grid can be removed, and a line can be edited elsewhere. The
table does not re-read the site while it is open: it reads the grid's lines
once, and OK re-checks everything (spec call 14) -- the site's identity, the
grid, and each line's placement against the one the table saw, which
`SiteSession.edit_lines` does and reports as skipped lines. Every method that
reads the grid or the frames catches KeyError (a grid gone) and ProjectError
(no site open) and says so on the status line instead of raising, because most
of them are reached from a signal, where an uncaught exception is swallowed.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from nsgeo.geometry import Grid
from nsgeo.project import ProjectError
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.line_edit import (
    SAME_M,
    EditOutcome,
    LineEdit,
    length_along,
    placement_note,
    same_placement,
    width_across,
)
from nsgeo_qgis.session import SiteSession

(
    COL_LABEL,
    COL_OFFSET,
    COL_DIR,
    COL_START,
    COL_GRID,
    COL_ALONG,
    COL_TRACES,
    COL_LENGTH,
    COL_PICKS,
    COL_NOTE,
) = range(10)
HEADERS = [
    "Label",
    "Offset (m)",
    "Dir",
    "Start (m)",
    "Grid",
    "Along",
    "Traces",
    "Length (m)",
    "Picks",
    "Note",
]
# Grid is a combo box in its cell, not an editable item.
EDITABLE = {COL_LABEL, COL_OFFSET, COL_DIR, COL_START}
# The background of every cell whose field differs from the placement the
# table saw, so a change is visible before OK.
CHANGED = QColor(255, 236, 179)


class EditLinesDialog(QDialog):
    def __init__(
        self,
        session: SiteSession,
        grid_id: str,
        *,
        select: Sequence[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.grid_id = grid_id
        self.outcome: EditOutcome | None = None
        # Identifies the site accept() may write into (see the module docstring).
        self._opened_against = session.json_path
        self._updating = False
        self._order: list[str] = []
        self._edits: dict[str, LineEdit] = {}
        self._traces: dict[str, int] = {}
        self._per_metre: dict[str, float] = {}
        self._picks: dict[str, int] = {}
        self._grid_ids: list[str] = []
        try:
            self._grid_ids = [g.id for g in session.site.grids] if session.site else []
            for key in session.keys_on_grid(grid_id):
                line = session.line_for_key(key)
                self._order.append(key)
                self._edits[key] = LineEdit(key, seen=line.placement)  # type: ignore[arg-type]
                self._traces[key] = line.n_traces
                self._per_metre[key] = line.header.traces_per_metre
                self._picks[key] = len(session.picks_for(key))
        except (KeyError, ProjectError):
            pass  # an empty table; _refresh says why

        self.setWindowTitle(f"Edit lines · {grid_id}")
        self.resize(980, 560)
        layout = QVBoxLayout(self)
        self.header_label = QLabel("")
        layout.addWidget(self.header_label)

        row = QHBoxLayout()
        self.up_button = QPushButton("↑")
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button = QPushButton("↓")
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        row.addWidget(self.up_button)
        row.addWidget(self.down_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.table = QTableWidget(len(self._order), len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._combos: list[QComboBox] = []
        for r in range(len(self._order)):
            combo = QComboBox()
            combo.addItems(self._grid_ids)
            combo.currentTextChanged.connect(lambda text, r=r: self._on_grid_picked(r, text))
            self.table.setCellWidget(r, COL_GRID, combo)
            self._combos.append(combo)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)

        self.bulk = QGroupBox("")
        bulk = QVBoxLayout(self.bulk)
        start_row = QHBoxLayout()
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(-1e4, 1e4)
        self.start_spin.setDecimals(3)
        self.set_start_button = QPushButton("Set")
        self.set_start_button.clicked.connect(lambda: self.set_start(self.start_spin.value()))
        self.snap_button = QPushButton("Snap to grid edge")
        self.snap_button.clicked.connect(self.snap_to_edge)
        start_row.addWidget(QLabel("Start (m)"))
        start_row.addWidget(self.start_spin)
        start_row.addWidget(self.set_start_button)
        start_row.addWidget(self.snap_button)
        start_row.addStretch(1)
        bulk.addLayout(start_row)
        offset_row = QHBoxLayout()
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-1e4, 1e4)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setValue(0.5)
        self.shift_button = QPushButton("Shift")
        self.shift_button.clicked.connect(lambda: self.shift_offset(self.offset_spin.value()))
        offset_row.addWidget(QLabel("Shift offsets by (m)"))
        offset_row.addWidget(self.offset_spin)
        offset_row.addWidget(self.shift_button)
        offset_row.addStretch(1)
        bulk.addLayout(offset_row)
        other_row = QHBoxLayout()
        self.flip_button = QPushButton("Flip")
        self.flip_button.clicked.connect(self.flip)
        self.grid_combo = QComboBox()
        self.grid_combo.addItems(self._grid_ids)
        self.move_button = QPushButton("Move")
        self.move_button.clicked.connect(lambda: self.move_to(self.grid_combo.currentText()))
        other_row.addWidget(self.flip_button)
        other_row.addWidget(QLabel("Move to grid"))
        other_row.addWidget(self.grid_combo)
        other_row.addWidget(self.move_button)
        other_row.addStretch(1)
        bulk.addLayout(other_row)
        layout.addWidget(self.bulk)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._refresh()
        self.select_keys(select)

    # ---- reading --------------------------------------------------------------
    def keys(self) -> list[str]:
        return list(self._order)

    def edit_for(self, key: str) -> LineEdit:
        return self._edits[key]

    def _unavailable(self) -> str:
        if not self.session.is_open:
            return "no site is open"
        return f"grid {self.grid_id!r} no longer exists"

    def _frames(self) -> Mapping[str, Grid]:
        """The site's frames. `ProjectError` when no site is open."""
        site = self.session.site
        if site is None:
            raise ProjectError("no site is open")
        return site.frames

    def _grid(self) -> Grid:
        return self.session.grid(self.grid_id)

    # ---- selection ------------------------------------------------------------
    def selected_keys(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._order[r] for r in rows if r < len(self._order)]

    def select_keys(self, keys: Iterable[str]) -> None:
        wanted = set(keys)
        model = self.table.selectionModel()
        self.table.clearSelection()
        for r, key in enumerate(self._order):
            if key in wanted:
                model.select(
                    self.table.model().index(r, 0),
                    model.SelectionFlag.Select | model.SelectionFlag.Rows,
                )
        self._selection_changed()

    def _selection_changed(self) -> None:
        sel = self.selected_keys()
        rows = [self._order.index(k) for k in sel]
        self.bulk.setTitle(f"Change the {len(sel)} selected lines")
        self.bulk.setEnabled(bool(sel))
        self.up_button.setEnabled(bool(rows) and min(rows) > 0)
        self.down_button.setEnabled(bool(rows) and max(rows) < len(self._order) - 1)

    # ---- acting on the selection ------------------------------------------------
    def _apply(self, change: Callable[[LineEdit, Mapping[str, Grid]], LineEdit]) -> None:
        try:
            frames = self._frames()
            for key in self.selected_keys():
                self._edits[key] = change(self._edits[key], frames)
        except (KeyError, ProjectError):
            self.status.setText(self._unavailable())
            return
        self._refresh()

    def set_start(self, value: float) -> None:
        self._apply(lambda e, f: dataclasses.replace(e, start_along=float(value)))

    def snap_to_edge(self) -> None:
        self._apply(lambda e, f: e.snapped())

    def shift_offset(self, delta: float) -> None:
        self._apply(lambda e, f: e.shifted(delta, f))

    def flip(self) -> None:
        self._apply(lambda e, f: e.flipped(f))

    def move_to(self, grid_id: str) -> None:
        self._apply(lambda e, f: e.moved_to(grid_id, f))

    def move_selected(self, delta: int) -> None:
        """Move every selected row one place, keeping their order; nothing
        when one would leave the table (the survey order, spec §4.1)."""
        sel = self.selected_keys()
        rows = [self._order.index(k) for k in sel]
        if not rows or not min(rows) + delta >= 0 or max(rows) + delta >= len(self._order):
            return
        for r in rows if delta < 0 else reversed(rows):
            self._order[r], self._order[r + delta] = self._order[r + delta], self._order[r]
        self._refresh()
        self.select_keys(sel)

    # ---- table ------------------------------------------------------------------
    def _refresh(self, note: str | None = None) -> None:
        """Redraw every row and the status line from the edits. `note`, when
        given, replaces the status (a refused cell edit)."""
        sel = self.selected_keys()
        try:
            grid = self._grid()
            frames = self._frames()
            self._render(frames, grid)
            n, m = self._counts(frames)
        except (KeyError, ProjectError):
            self.status.setText(self._unavailable())
            return
        if note is not None:
            self.status.setText(note)
        elif n == 0:
            self.status.setText("")
        else:
            self.status.setText(
                f"{n} line{'s' if n != 1 else ''} changed · "
                f"{m} pick{'s' if m != 1 else ''} will move with {'them' if n != 1 else 'it'}"
            )
        if sel:
            self.select_keys(sel)
        else:
            self._selection_changed()

    def _counts(self, frames: Mapping[str, Grid]) -> tuple[int, int]:
        changed = [k for k in self._order if self._edits[k].changes(frames)]
        moving = 0
        for k in changed:
            e = self._edits[k]
            placed = dataclasses.replace(e.placed(frames), label=e.seen.label)
            if not same_placement(placed, e.seen):
                moving += self._picks[k]
        return len(changed), moving

    def _render(self, frames: Mapping[str, Grid], grid: Grid) -> None:
        axes = {self._edits[k].seen.axis for k in self._order}
        n = len(self._order)
        if len(axes) == 1:
            a = next(iter(axes))
            self.header_label.setText(
                f"{self.grid_id} · {length_along(grid, a):.2f} m along {a} × "
                f"{width_across(grid, a):.2f} m across · {n} lines"
            )
        else:
            self.header_label.setText(
                f"{self.grid_id} · {grid.size_x:.2f} m × {grid.size_y:.2f} m · {n} lines"
            )
        self._updating = True
        try:
            for r, key in enumerate(self._order):
                edit = self._edits[key]
                seen = edit.seen
                p = edit.placed(frames)
                per_metre = self._per_metre[key]
                length = self._traces[key] / per_metre if per_metre > 0 else 0.0
                differs = {
                    COL_LABEL: p.label != seen.label,
                    COL_OFFSET: abs(p.offset - seen.offset) > SAME_M,
                    COL_DIR: p.direction != seen.direction,
                    COL_START: abs(p.start_along - seen.start_along) > SAME_M,
                    COL_GRID: p.grid_id != seen.grid_id,
                }
                values = {
                    COL_LABEL: p.label or Path(key).stem,
                    COL_OFFSET: f"{p.offset:.2f}",
                    COL_DIR: "+1" if p.direction == 1 else "−1",
                    COL_START: f"{p.start_along:.2f}",
                    COL_GRID: p.grid_id,
                    COL_ALONG: p.axis,
                    COL_TRACES: str(self._traces[key]),
                    COL_LENGTH: f"{length:.2f}" if length > 0 else "",
                    COL_PICKS: str(self._picks[key]),
                    COL_NOTE: placement_note(p, frames[p.grid_id]),
                }
                for col, text in values.items():
                    item = QTableWidgetItem(text)
                    if col not in EDITABLE:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if differs.get(col):
                        item.setBackground(CHANGED)
                    self.table.setItem(r, col, item)
                combo = self._combos[r]
                combo.blockSignals(True)
                combo.setCurrentText(p.grid_id)
                combo.blockSignals(False)
                combo.setStyleSheet(
                    f"background-color: {CHANGED.name()};" if differs[COL_GRID] else ""
                )
            self.table.resizeColumnsToContents()
        finally:
            self._updating = False

    def _on_grid_picked(self, row: int, text: str) -> None:
        if self._updating or not 0 <= row < len(self._order):
            return
        key = self._order[row]
        try:
            edit = self._edits[key]
            if text == edit.placed(self._frames()).grid_id:
                return
            self._edits[key] = edit.moved_to(text, self._frames())
        except (KeyError, ProjectError):
            self.status.setText(self._unavailable())
            return
        self._refresh()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        r, c = item.row(), item.column()
        if not 0 <= r < len(self._order) or c not in EDITABLE:
            return
        key = self._order[r]
        text = item.text().strip()
        try:
            edit = self._edits[key]
            frames = self._frames()
            if c == COL_LABEL:
                edit = dataclasses.replace(edit, label=text or Path(key).stem)
            elif c in (COL_OFFSET, COL_START):
                try:
                    value = float(text.replace(",", "."))
                except ValueError:
                    self._refresh(f"{item.text()!r} is not a number; unchanged")
                    return
                edit = (
                    dataclasses.replace(edit, offset=value)
                    if c == COL_OFFSET
                    else dataclasses.replace(edit, start_along=value)
                )
            else:
                # Parsed like ImportDialog: a leading minus (either glyph)
                # means reversed; anything else must be a positive number.
                if text.startswith(("-", "−")):
                    wanted = -1
                else:
                    try:
                        value = float(text.lstrip("+"))
                    except ValueError:
                        value = 0.0
                    if value <= 0:
                        self._refresh(
                            f"{item.text()!r} is not recognised as a direction; unchanged"
                        )
                        return
                    wanted = 1
                if wanted != edit.placed(frames).direction:
                    edit = edit.flipped(frames)
            self._edits[key] = edit
        except (KeyError, ProjectError):
            self.status.setText(self._unavailable())
            return
        self._refresh()

    # ---- accept -----------------------------------------------------------------
    def accept(self) -> None:
        # Reached from buttons.accepted as well as called directly: every
        # failure reports through `status` and returns, never raises (see the
        # module docstring). Re-checks the site, then the grid, then lets
        # SiteSession.edit_lines re-check every line (spec call 14).
        if not self.session.is_open:
            self.status.setText("no site is open; nothing was changed")
            return
        if self.session.json_path != self._opened_against:
            self.status.setText(
                "a different site was opened while the table was open; nothing was changed"
            )
            return
        try:
            self._grid()
        except KeyError:
            self.status.setText(f"grid {self.grid_id!r} no longer exists; nothing was changed")
            return
        try:
            frames = self._frames()
            edits: list[Any] = [e for e in self._edits.values() if e.changes(frames)]
            self.outcome = self.session.edit_lines(edits, grid_id=self.grid_id, order=self.keys())
        except (KeyError, ValueError, ProjectError) as exc:
            self.status.setText(str(exc))
            return
        super().accept()
