"""Import DZT files into a grid, with a correction table.

The guess (Task 7's plan_import) is vendor-neutral and the table is the
real mechanism: Include, Label, Offset, and Dir are editable; Start
(along) is shown but not -- see the note above EDITABLE below for why.
Traces, Length, Sidecar come from the file. Excluding a redone line pulls
later files into its slot unless their offsets, labels, or direction were
hand-edited.

Modeless, like GridDialog (plugin.py's open_grid_dialog is the pattern):
show() plus the finished signal, never exec(). Nothing this dialog itself
does needs the rest of QGIS to stay interactive, but the toolbar and the
survey dock do stay clickable while it is open -- which means the site can
be closed or replaced, or the very grid this dialog is importing into can
be removed (the dock's "Remove grid" has no guard against an import still
in flight), before Import is clicked. _grid() absorbs both (KeyError for a
removed grid, ProjectError for a closed site -- SiteSession.grid() raises
the latter via _require_site()) so that every slot reading the target
grid stays safe, not only accept(): fix round 1 found set_include(),
remove_selected(), and every spin-box/radio-button-triggered replan
raising ProjectError uncaught (silently, in every case reachable via a
signal) when only KeyError was handled. accept() additionally re-checks
session identity and re-derives the target grid right before it writes
anything -- see its own docstring below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nsgeo.geometry.grid import Grid
from nsgeo.project import ProjectError
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.lookup import (
    ImportOptions,
    ImportRow,
    plan_import,
    recompute_offsets,
    rows_to_lines,
)
from nsgeo_qgis.session import SiteSession

(
    COL_INCLUDE,
    COL_FILE,
    COL_LABEL,
    COL_OFFSET,
    COL_DIR,
    COL_START,
    COL_TRACES,
    COL_LENGTH,
    COL_SIDECAR,
    COL_NOTE,
) = range(10)
HEADERS = [
    "",
    "File",
    "Label",
    "Offset (m)",
    "Dir",
    "Start (m)",
    "Traces",
    "Length (m)",
    "Sidecar",
    "Note",
]
# Start (along) is NOT here, on purpose: it is mechanically derived from
# row.direction (options.start_along + grid_size_along when reversed,
# options.start_along otherwise -- lookup.py's own start_along contract),
# not independently editable, and ImportRow has no start_along_edited to
# protect a hand-typed value across the next replan (every edit in this
# dialog triggers one). A reversed row's start_along left stale after a
# replan would place it mirrored outside the grid instead of into it, so
# this must stay derived rather than editable.
#
# Dir IS here (unlike Task 11's first round): a line re-walked in the same
# direction as its neighbour is an ordinary field exception under the
# zigzag default, not an edge case, and excluding+re-importing a redone
# line to work around a read-only Dir cell re-derives every later line's
# offset/direction too (recompute_offsets' documented, correct behaviour
# for a *redone* line -- wrong for fixing one direction in isolation).
# ImportRow.direction_edited (mirroring offset_edited/label_edited) is
# what makes this actually stick: recompute_offsets skips re-deriving
# row.direction once it is set, and the start_along mirroring above keys
# off row.direction, not options.direction_mode, so it follows a
# hand-flipped row for free.
EDITABLE = {COL_LABEL, COL_OFFSET, COL_DIR}


class ImportDialog(QDialog):
    def __init__(
        self, session: SiteSession, grid_id: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        # Modeless means the toolbar and dock stay clickable while this
        # dialog is open (see the module docstring); this is what identifies
        # which site accept() is actually allowed to write into.
        self._opened_against = session.json_path
        self.rows: list[ImportRow] = []
        self.imported_keys: list[str] = []
        self._updating = False
        self.setWindowTitle("Import DZT files")
        self.resize(900, 520)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.grid_combo = QComboBox()
        site = session.site
        for g in site.grids if site else []:
            self.grid_combo.addItem(g.id, g.id)
        if grid_id:
            self.grid_combo.setCurrentIndex(max(0, self.grid_combo.findData(grid_id)))
        self.axis_combo = QComboBox()
        self.axis_combo.addItem("y (lines run along Y, offsets across X)", "y")
        self.axis_combo.addItem("x (lines run along X, offsets across Y)", "x")
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0.01, 100.0)
        self.spacing.setDecimals(3)
        self.first_offset = QDoubleSpinBox()
        self.first_offset.setRange(-1e4, 1e4)
        self.first_offset.setDecimals(3)
        self.start_along = QDoubleSpinBox()
        self.start_along.setRange(-1e4, 1e4)
        self.start_along.setDecimals(3)
        form.addRow("Target grid", self.grid_combo)
        form.addRow("Lines run along", self.axis_combo)
        form.addRow("Spacing across", self.spacing)
        form.addRow("First line at", self.first_offset)
        form.addRow("Start along", self.start_along)

        direction_row = QHBoxLayout()
        self.direction_alternate = QRadioButton("alternate (zigzag)")
        self.direction_forward = QRadioButton("all +1")
        self.direction_reverse = QRadioButton("all -1")
        self.direction_alternate.setChecked(True)
        self._direction_group = QButtonGroup(self)
        for b in (self.direction_alternate, self.direction_forward, self.direction_reverse):
            self._direction_group.addButton(b)
            direction_row.addWidget(b)
        direction_row.addStretch(1)
        form.addRow("Direction", direction_row)
        label_row = QHBoxLayout()
        self.label_stem = QRadioButton("file name")
        self.label_number = QRadioButton("line number")
        self.label_stem.setChecked(True)
        self._label_group = QButtonGroup(self)
        for b in (self.label_stem, self.label_number):
            self._label_group.addButton(b)
            label_row.addWidget(b)
        label_row.addStretch(1)
        form.addRow("Label from", label_row)
        layout.addLayout(form)

        buttons_row = QHBoxLayout()
        self.add_button = QPushButton("Add files…")
        self.add_button.clicked.connect(self._choose_files)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self.remove_selected)
        self.up_button = QPushButton("↑")
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button = QPushButton("↓")
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        for b in (self.add_button, self.remove_button, self.up_button, self.down_button):
            buttons_row.addWidget(b)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        # Fix round 1, Finding 4: with Dir now editable, Start (m) is the
        # only inert cell left in the table -- without this, a user who
        # clicks it and gets nothing has no way to learn why, or what
        # would actually move it (Direction, or row order).
        start_header = self.table.horizontalHeaderItem(COL_START)
        assert start_header is not None
        start_header.setToolTip(
            "Derived from Direction (mode, or a per-row edit) and row order; not directly editable."
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Import")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.grid_combo.currentIndexChanged.connect(self._grid_changed)
        self.axis_combo.currentIndexChanged.connect(self._replan)
        for s in (self.spacing, self.first_offset, self.start_along):
            s.valueChanged.connect(self._replan)
        for b in (
            self.direction_alternate,
            self.direction_forward,
            self.direction_reverse,
            self.label_stem,
            self.label_number,
        ):
            b.toggled.connect(self._replan)
        self._grid_changed()

    # ---- options ------------------------------------------------------------
    def _grid(self) -> Grid | None:
        gid = self.grid_combo.currentData()
        if not gid:
            return None
        try:
            return self.session.grid(gid)
        except (KeyError, ProjectError):
            # The target grid can be removed from under a still-open,
            # modeless dialog (KeyError), or the site itself can close
            # entirely (session.grid() -> _require_site() raises
            # ProjectError -- see the module docstring). Fix round 1,
            # Finding 1: catching only KeyError here left ProjectError
            # escaping every caller below uncaught -- set_include(),
            # remove_selected() (desyncing self.rows from the table:
            # it deletes before replanning), and every spin-box/radio
            # slot's replan, all silently via the signal/slot hazard.
            # Every caller of _grid()/options() must see "no grid
            # selected" for both causes, not just one of them.
            return None

    def _grid_changed(self, *_: Any) -> None:
        grid = self._grid()
        if grid is not None:
            self.spacing.setValue(grid.default_spacing)
        self._replan()

    def options(self) -> ImportOptions:
        grid = self._grid()
        axis = self.axis_combo.currentData() or "y"
        along = None
        if grid is not None:
            along = grid.size_y if axis == "y" else grid.size_x
        mode = (
            "alternate"
            if self.direction_alternate.isChecked()
            else "forward"
            if self.direction_forward.isChecked()
            else "reverse"
        )
        return ImportOptions(
            grid_id=grid.id if grid else "",
            axis=axis,
            spacing=self.spacing.value(),
            first_offset=self.first_offset.value(),
            start_along=self.start_along.value(),
            direction_mode=mode,
            label_source="number" if self.label_number.isChecked() else "stem",
            grid_size_along=along,
        )

    # ---- rows -----------------------------------------------------------------
    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select DZT files", "", "GSSI DZT (*.DZT *.dzt);;All files (*)"
        )
        if paths:
            self.add_files([Path(p) for p in paths])

    def add_files(self, paths: list[Path]) -> None:
        known = {r.path.resolve() for r in self.rows}
        fresh: list[Path] = []
        for p in paths:
            resolved = Path(p).resolve()
            if resolved in known:
                continue
            known.add(resolved)  # a duplicate *within* this same call must not slip through either
            fresh.append(Path(p))
        if not fresh:
            return
        try:
            new_rows = plan_import(fresh, self.options())
        except Exception as exc:  # noqa: BLE001 -- see plugin.py's module docstring:
            # this is a QPushButton.clicked-reachable slot (via
            # _choose_files), so a bad file must be reported through
            # `status`, not disappear into stderr while the dialog looks
            # like nothing happened.
            self.status.setText(f"could not read a file: {exc}")
            return
        self.rows.extend(new_rows)
        self._replan()

    def _replan(self, *_: Any) -> None:
        recompute_offsets(self.rows, self.options())
        self._refresh_table()

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def remove_selected(self) -> None:
        for r in reversed(self._selected_rows()):
            del self.rows[r]
        self._replan()

    def move_selected(self, delta: int) -> None:
        sel = self._selected_rows()
        if len(sel) != 1:
            return
        i, j = sel[0], sel[0] + delta
        if not 0 <= j < len(self.rows):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self._replan()
        self.table.selectRow(j)

    def set_include(self, row: int, flag: bool) -> None:
        self.rows[row].include = flag
        self._replan()

    def set_offset(self, row: int, value: float) -> None:
        self.rows[row].offset = float(value)
        self.rows[row].offset_edited = True
        self._replan()

    def set_direction(self, row: int, value: int) -> None:
        # value need not already be exactly +-1 (a hand-typed cell only
        # promises "negative means reversed" -- see _on_item_changed).
        # direction_edited is what makes this stick: without it,
        # recompute_offsets re-derives row.direction from direction_mode
        # on the very next replan, which every other edit in this dialog
        # triggers (fix round 1, Finding 2).
        self.rows[row].direction = 1 if value >= 0 else -1
        self.rows[row].direction_edited = True
        self._replan()

    # ---- table ------------------------------------------------------------
    def _refresh_table(self) -> None:
        self._updating = True
        try:
            self.table.setRowCount(len(self.rows))
            for r, row in enumerate(self.rows):
                inc = QTableWidgetItem("")
                inc.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                inc.setCheckState(Qt.CheckState.Checked if row.include else Qt.CheckState.Unchecked)
                if not row.placeable:
                    inc.setFlags(Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, COL_INCLUDE, inc)
                sidecar = ""
                if row.sidecar is not None:
                    parts = ["✓"]
                    if row.sidecar.dielectric is not None:
                        parts.append(f"ε {row.sidecar.dielectric:g}")
                    if row.sidecar.marks:
                        parts.append(f"{len(row.sidecar.marks)} mark(s)")
                    sidecar = " ".join(parts)
                values = {
                    COL_FILE: row.path.name,
                    COL_LABEL: row.label,
                    COL_OFFSET: f"{row.offset:.2f}",
                    COL_DIR: "+1" if row.direction == 1 else "−1",
                    COL_START: f"{row.start_along:.2f}",
                    COL_TRACES: "" if row.n_traces is None else str(row.n_traces),
                    COL_LENGTH: "" if row.length_m is None else f"{row.length_m:.2f}",
                    COL_SIDECAR: sidecar,
                    COL_NOTE: row.note,
                }
                for col, text in values.items():
                    item = QTableWidgetItem(text)
                    if col not in EDITABLE:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, col, item)
            self.table.resizeColumnsToContents()
            n = sum(1 for r in self.rows if r.include and r.placeable)
            self.import_button.setText(f"Import {n} line(s)")
            self.import_button.setEnabled(n > 0)
        finally:
            self._updating = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        r, c = item.row(), item.column()
        row = self.rows[r]
        if c == COL_INCLUDE:
            self.set_include(r, item.checkState() == Qt.CheckState.Checked)
        elif c == COL_LABEL:
            # Fix round 1, Finding 5: this edit cannot itself fail, so it
            # must not clear a standing `status` message about something
            # else (e.g. add_files' "could not read a file: ..."). No
            # placement field changed either: a full replan is unnecessary
            # (and would just redraw the same table).
            row.label = item.text().strip() or row.path.stem
            row.label_edited = True
        elif c == COL_OFFSET:
            try:
                value = float(item.text().replace(",", "."))
            except ValueError:
                # A hand-typed cell that is not a number must not raise out
                # of a signal-connected slot (see the module docstring);
                # report it and revert the cell to the row's real value
                # instead of leaving unparsed garbage on screen.
                self.status.setText(f"{item.text()!r} is not a number; offset unchanged")
                self._refresh_table()
                return
            self.status.setText("")
            self.set_offset(r, value)
        elif c == COL_DIR:
            # Fix round 2, Finding 2: a leading minus (either glyph) means
            # reversed regardless of what follows -- "-1.0", "-2", and a
            # bare "-" all count. The previous exact-string match
            # ("-1"/"−1" only) silently read every one of those as
            # *forward* instead, and -- worse -- still set
            # direction_edited, pinning the row against direction_mode
            # with no status message at all; "-1.0" in particular is a
            # natural thing to type into a numeric-looking cell. Anything
            # without a leading minus must parse as a positive number to
            # count as forward; genuinely unrecognised text (including
            # "0", which is not a valid direction, and "" or "reverse",
            # neither of which parses at all) is reported and reverted
            # instead of silently pinned, the same as COL_OFFSET does for
            # unparseable text. A successful parse clears nothing (see
            # COL_LABEL above): only the failure case has anything of its
            # own to report.
            text = item.text().strip()
            if text.startswith(("-", "−")):
                self.set_direction(r, -1)
                return
            try:
                value = float(text.lstrip("+"))
            except ValueError:
                value = None
            if value is None or value <= 0:
                self.status.setText(f"{item.text()!r} is not recognised as a direction; unchanged")
                self._refresh_table()
                return
            self.set_direction(r, 1)

    # ---- accept -----------------------------------------------------------
    def accept(self) -> None:
        # accept() is reached via buttons.accepted (a signal-connected
        # slot) as well as by calling it directly; every failure below
        # must report through `status` and return rather than raise, both
        # for the signal path (an uncaught exception would be swallowed --
        # see the module docstring) and so a duplicate import or a stale
        # site/grid never *looks* like it succeeded.
        if not self.session.is_open:
            self.status.setText("no site is open; nothing was imported")
            return
        if self.session.json_path != self._opened_against:
            # Modeless means the site this dialog was opened against can
            # be closed or replaced by a different one while it is still
            # open (see the module docstring) -- without this check, an
            # accept() here would write into whatever site happens to be
            # open now, silently, which could define its own same-named
            # grid.
            self.status.setText(
                "a different site was opened while the import dialog was open; nothing was imported"
            )
            return
        gid = self.grid_combo.currentData()
        if gid and self._grid() is None:
            # The grid itself vanished (e.g. "Remove grid" in the dock,
            # which has no guard against an import still in flight) while
            # this dialog stayed open on it.
            self.status.setText(f"grid {gid!r} no longer exists; nothing was imported")
            return
        if not gid:
            self.status.setText("choose a target grid")
            return
        opts = self.options()
        # Re-derive against the *current* options right before writing --
        # a concurrent edit to this same grid (a GridDialog open at the
        # same time) can change grid_size_along since the table was last
        # refreshed, and a stale start_along/note must not be what gets
        # imported (see lookup.py's start_along contract).
        recompute_offsets(self.rows, opts)
        self._refresh_table()
        try:
            lines = rows_to_lines(self.rows, opts)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring:
            # a file can become unreadable (deleted, permissions, a bad
            # header) between planning and clicking Import.
            self.status.setText(f"could not read a file: {exc}")
            return
        if not lines:
            self.status.setText("nothing to import: no included, placeable rows")
            return
        try:
            self.session.add_lines(lines)
        except ValueError as exc:  # a key already in the site -- add_lines' one failure mode
            self.status.setText(str(exc))
            return
        self.imported_keys = [self.session.line_key(ln) for ln in lines]
        super().accept()
