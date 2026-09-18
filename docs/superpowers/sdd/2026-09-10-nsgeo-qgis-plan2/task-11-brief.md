### Task 11: Import dialog

Select files, choose the grid and axis, correct the guessed placements in a table, import. Include checkbox, remove, reorder, and the vendor-neutral guess from Task 7. Validated on the ten real files.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_import_dialog`)
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`

**Interfaces:**
- Consumes: `plan_import`, `recompute_offsets`, `rows_to_lines`, `ImportOptions`, `SiteSession.add_lines`
- Produces: `ImportDialog(session, grid_id=None, parent=None)` with `add_files(paths)`, `rows: list[ImportRow]`, `options() -> ImportOptions`, `table: QTableWidget`, column constants `COL_INCLUDE .. COL_NOTE`, `remove_selected()`, `move_selected(delta)`, `set_include(row, flag)`, `set_offset(row, value)`, `import_button`, `status`, `imported_keys: list[str]` after `accept()`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.PyQt.QtCore import Qt

from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.import_dialog import COL_DIR, COL_INCLUDE, COL_LABEL, COL_NOTE, COL_OFFSET, ImportDialog

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(GRID)
    return s


def test_table_shows_planned_rows_and_edits_flow_back(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT", n_traces=60) for i in (2, 1, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    assert d.table.rowCount() == 3
    assert [d.table.item(r, COL_LABEL).text() for r in range(3)] == ["FILE__001", "FILE__002", "FILE__003"]
    assert [d.table.item(r, COL_OFFSET).text() for r in range(3)] == ["0.00", "0.50", "1.00"]
    assert d.table.item(1, COL_DIR).text() == "−1"
    d.set_include(1, False)
    assert [d.table.item(r, COL_OFFSET).text() for r in range(3) if d.rows[r].include] == ["0.00", "0.50"]
    d.set_offset(2, 3.25)
    d.set_include(1, True)
    assert d.rows[2].offset == 3.25 and d.rows[2].offset_edited
    assert d.table.item(1, COL_OFFSET).text() == "0.50"


def test_remove_and_reorder(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.table.selectRow(2)
    d.move_selected(-1)
    assert [r.path.stem for r in d.rows] == ["FILE__001", "FILE__003", "FILE__002"]
    assert [r.offset for r in d.rows] == [0.0, 0.5, 1.0]
    d.table.selectRow(0)
    d.remove_selected()
    assert [r.path.stem for r in d.rows] == ["FILE__003", "FILE__002"]
    assert d.rows[0].offset == 0.0


def test_accept_adds_lines_and_fills_the_layer(session, tmp_path):
    layers = SiteLayers(session)
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.set_include(1, False)
    d.accept()
    assert d.imported_keys == ["raw/FILE__001.DZT", "raw/FILE__003.DZT"]
    assert session.keys() == d.imported_keys
    assert layers.feature_count("lines") == 2
    layers.detach()


def test_duplicate_import_is_reported_not_raised(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.accept()
    d2 = ImportDialog(session, grid_id="A")
    d2.add_files(files)
    d2.accept()
    assert "already" in d2.status.text()
    assert d2.result() != d2.DialogCode.Accepted


def test_axis_and_spacing_options_come_from_the_widgets(session, tmp_path):
    d = ImportDialog(session, grid_id="A")
    d.axis_combo.setCurrentIndex(d.axis_combo.findData("x"))
    d.spacing.setValue(0.25)
    d.first_offset.setValue(1.0)
    d.direction_forward.setChecked(True)
    d.label_number.setChecked(True)
    o = d.options()
    assert (o.axis, o.spacing, o.first_offset, o.direction_mode, o.label_source) == ("x", 0.25, 1.0, "forward", "number")
    assert o.grid_size_along == 5.0  # size_x when lines run along x


@needs_real_data
def test_real_files_import_into_the_grid(session):
    d = ImportDialog(session, grid_id="A")
    d.add_files(REAL_DZT)
    assert d.table.rowCount() == 10
    assert "exceeds" in d.table.item(7, COL_NOTE).text()  # FILE__008, 11.10 m
    assert d.table.item(0, COL_INCLUDE).checkState() == Qt.CheckState.Checked
    d.accept()
    assert len(session.keys()) == 10
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.import_dialog'`

- [ ] **Step 3: Implement the dialog**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py`:

```python
"""Import DZT files into a grid, with a correction table.

The guess (Task 7's plan_import) is vendor-neutral and the table is the
real mechanism: Include, Label, Offset, Dir, Start are editable; Traces,
Length, Sidecar come from the file. Excluding a redone line pulls later
files into its slot unless their offsets were hand-edited.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

from nsgeo_qgis.lookup import ImportOptions, ImportRow, plan_import, recompute_offsets, rows_to_lines
from nsgeo_qgis.session import SiteSession

COL_INCLUDE, COL_FILE, COL_LABEL, COL_OFFSET, COL_DIR, COL_START, COL_TRACES, COL_LENGTH, COL_SIDECAR, COL_NOTE = range(10)
HEADERS = ["", "File", "Label", "Offset (m)", "Dir", "Start (m)", "Traces", "Length (m)", "Sidecar", "Note"]
EDITABLE = {COL_LABEL, COL_OFFSET, COL_DIR, COL_START}


class ImportDialog(QDialog):
    def __init__(self, session: SiteSession, grid_id: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
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
        self.direction_reverse = QRadioButton("all −1")
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
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Import")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.grid_combo.currentIndexChanged.connect(self._grid_changed)
        for w in (self.axis_combo,):
            w.currentIndexChanged.connect(self._replan)
        for s in (self.spacing, self.first_offset, self.start_along):
            s.valueChanged.connect(self._replan)
        for b in (self.direction_alternate, self.direction_forward, self.direction_reverse, self.label_stem, self.label_number):
            b.toggled.connect(self._replan)
        self._grid_changed()

    # ---- options ----------------------------------------------------------
    def _grid(self) -> Any:
        gid = self.grid_combo.currentData()
        return self.session.grid(gid) if gid else None

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
        mode = "alternate" if self.direction_alternate.isChecked() else "forward" if self.direction_forward.isChecked() else "reverse"
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

    # ---- rows -------------------------------------------------------------
    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select DZT files", "", "GSSI DZT (*.DZT *.dzt);;All files (*)")
        if paths:
            self.add_files([Path(p) for p in paths])

    def add_files(self, paths: list[Path]) -> None:
        known = {r.path.resolve() for r in self.rows}
        fresh = [Path(p) for p in paths if Path(p).resolve() not in known]
        if not fresh:
            return
        try:
            new_rows = plan_import(fresh, self.options())
        except Exception as exc:  # DztError, OSError: name the file, keep the dialog alive
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

    # ---- table ------------------------------------------------------------
    def _refresh_table(self) -> None:
        self._updating = True
        try:
            self.table.setRowCount(len(self.rows))
            for r, row in enumerate(self.rows):
                inc = QTableWidgetItem("")
                inc.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
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
        try:
            if c == COL_INCLUDE:
                row.include = item.checkState() == Qt.CheckState.Checked
            elif c == COL_LABEL:
                row.label = item.text().strip() or row.path.stem
                return  # label edits need no replan
            elif c == COL_OFFSET:
                row.offset = float(item.text().replace(",", "."))
                row.offset_edited = True
            elif c == COL_DIR:
                row.direction = -1 if item.text().strip().lstrip("+") in ("-1", "−1") else 1
            elif c == COL_START:
                row.start_along = float(item.text().replace(",", "."))
        except ValueError:
            pass
        self._replan()

    # ---- accept -----------------------------------------------------------
    def accept(self) -> None:
        opts = self.options()
        if not opts.grid_id:
            self.status.setText("choose a target grid")
            return
        # A label edited in the table must survive recompute_offsets; it does,
        # because recompute only rewrites labels when label_source == "number".
        try:
            lines = rows_to_lines(self.rows, opts)
            self.session.add_lines(lines)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.imported_keys = [self.session.line_key(ln) for ln in lines]
        super().accept()
```

**Known wrinkle to handle while implementing:** `recompute_offsets` rewrites `row.label` to the file stem when `label_source == "stem"`, which would discard a hand-edited label on the next replan. Fix it in `lookup.py` the same way offsets are protected: add `label_edited: bool = False` to `ImportRow`, set it in `_on_item_changed` for `COL_LABEL`, and make `recompute_offsets` skip rows with `label_edited`. Add a pure test for it in `test_pure_lookup.py`:

```python
def test_hand_edited_labels_survive_recompute(three):
    rows = plan_import(three, OPTS)
    rows[1].label = "line 6a"
    rows[1].label_edited = True
    recompute_offsets(rows, OPTS)
    assert rows[1].label == "line 6a"
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py`, replace the `open_import_dialog` stub:

```python
    def open_import_dialog(self, grid_id: str | None) -> None:
        assert self.session is not None
        if not self.session.is_open:
            return
        if not (self.session.site and self.session.site.grids):
            self.message("Add a grid before importing lines.", Qgis.MessageLevel.Warning)
            return
        dialog = ImportDialog(self.session, grid_id=grid_id, parent=self.iface.mainWindow())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.message(f"imported {len(dialog.imported_keys)} line(s)")
```

with `from nsgeo_qgis.ui.import_dialog import ImportDialog`.

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: import dialog with a correction table

Files, grid, axis, spacing, direction mode, and label source feed the
vendor-neutral planner; the table is the real mechanism. Include
checkboxes and Remove pull later files into a redone line's slot;
hand-edited offsets and labels survive replanning. Validated on the ten
real files, including the 11.10 m line that overruns an 11 m grid."
```

---

