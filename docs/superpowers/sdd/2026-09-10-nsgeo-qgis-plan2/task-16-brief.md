### Task 16: Processing dock — the stack list

The ordered, toggleable stack for the current line, bound to the session. Add (from the registry, never hardcoded), remove, reorder, enable, and apply to the grid. Steps with `REQUIRED` parameters are requested through a signal that Task 17 answers with a form.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`

**Interfaces:**
- Consumes: `SiteSession` stack methods, `available_steps`, `build_step`, `default_params`, `required_params`
- Produces: `ProcessingDock(session, parent=None)` with `list: QListWidget`, `add_button`, `add_menu`, `remove_button`, `up_button`, `down_button`, `apply_button`, `status: QLabel`, `form_area: QVBoxLayout` (Task 17 fills it), `key() -> str | None`, `current_row() -> int`, `rebuild()`, `add_step(name)`, `remove_selected()`, `move_selected(delta)`, `apply_to_grid(confirm=True) -> list[str]`, signals `step_selected(int)`, `add_step_requested(str)`; module function `dest_index(start, row) -> int`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import available_steps
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import Qt

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.processing_dock import ProcessingDock, dest_index

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5)))
    session.add_lines(lines)
    key = session.keys()[0]
    session.set_profiles(key, lines[0].load())
    session.open_line(key)
    return session, dock, key


def test_add_menu_lists_the_registry_and_marks_required_steps(opened):
    _, dock, _ = opened
    texts = [a.text() for a in dock.add_menu.actions()]
    assert [t.split(" ")[0] for t in texts] == available_steps()
    assert any(t.startswith("bandpass") and "needs values" in t for t in texts)
    assert not any(t.startswith("dewow") and "needs values" in t for t in texts)


def test_add_remove_toggle_and_reorder(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    dock.add_step("background_mean")
    dock.add_step("gain_agc")
    assert [dock.list.item(i).text() for i in range(3)] == ["dewow", "background_mean", "gain_agc"]
    dock.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert session.stack_for(key).entries[1][1] is False
    dock.list.setCurrentRow(2)
    dock.move_selected(-1)
    assert [s.name for s, _ in session.stack_for(key).entries] == ["dewow", "gain_agc", "background_mean"]
    assert dock.list.currentRow() == 1
    dock.remove_selected()
    assert [s.name for s, _ in session.stack_for(key).entries] == ["dewow", "background_mean"]


def test_required_steps_are_requested_not_built(opened):
    session, dock, key = opened
    asked = []
    dock.add_step_requested.connect(asked.append)
    dock.add_step("bandpass")
    assert asked == ["bandpass"] and len(session.stack_for(key)) == 0


def test_selection_emits_and_rebuild_keeps_it(opened):
    session, dock, key = opened
    got = []
    dock.step_selected.connect(got.append)
    dock.add_step("dewow")
    dock.add_step("gain_agc")
    dock.list.setCurrentRow(1)
    assert got[-1] == 1
    session.set_step_enabled(key, 0, False)  # triggers rebuild
    assert dock.list.currentRow() == 1


def test_dest_index_matches_qt_rows_moved_semantics():
    assert dest_index(start=0, row=3) == 2  # moved down past two rows
    assert dest_index(start=3, row=0) == 0  # moved up to the top
    assert dest_index(start=1, row=1) == 1


def test_apply_to_grid_copies_to_the_other_lines(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    changed = dock.apply_to_grid(confirm=False)
    assert len(changed) == 2
    for other in changed:
        assert session.stack_for(other).to_dicts() == session.stack_for(key).to_dicts()
    assert "2 line" in dock.status.text()


def test_switching_lines_shows_that_lines_stack(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    other = session.keys()[1]
    session.open_line(other)
    assert dock.list.count() == 0
    session.open_line(key)
    assert dock.list.count() == 1


def test_no_line_disables_the_controls(qgis_app):
    dock = ProcessingDock(SiteSession())
    assert not dock.add_button.isEnabled() and not dock.apply_button.isEnabled()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.processing_dock'`

- [ ] **Step 3: Implement the dock**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`:

```python
"""The processing dock: the current line's step stack.

Steps come from the registry, never from a hardcoded list. Every edit goes
through the session so the core's no-mutation rule holds and every other
view updates. Nothing here computes anything.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import available_steps, build_step, default_params, required_params
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession


def dest_index(start: int, row: int) -> int:
    """Translate QAbstractItemModel.rowsMoved's destination row (the row the
    item is inserted *before*, in pre-move numbering) into the index the
    item ends up at."""
    return row if row < start else row - 1


class ProcessingDock(QgsDockWidget):
    step_selected = pyqtSignal(int)  # -1 when nothing is selected
    add_step_requested = pyqtSignal(str)  # steps with REQUIRED params

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Processing", parent)
        self.setObjectName("nsgeoProcessingDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.session = session
        self._updating = False

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.add_button = QToolButton()
        self.add_button.setText("Add step")
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_menu = QMenu(self.add_button)
        for name in available_steps():
            text = f"{name}  (needs values)" if required_params(name) else name
            self.add_menu.addAction(text, lambda n=name: self.add_step(n))
        self.add_button.setMenu(self.add_menu)
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("↑")
        self.down_button = QPushButton("↓")
        for w in (self.add_button, self.remove_button, self.up_button, self.down_button):
            row.addWidget(w)
        row.addStretch(1)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.list)

        self.form_area = QVBoxLayout()
        layout.addLayout(self.form_area)

        bottom = QHBoxLayout()
        self.apply_button = QPushButton("Apply to grid…")
        bottom.addWidget(self.apply_button)
        bottom.addStretch(1)
        layout.addLayout(bottom)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setWidget(body)

        self.remove_button.clicked.connect(self.remove_selected)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.apply_button.clicked.connect(self.apply_to_grid)
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.currentRowChanged.connect(self._on_current_row)
        self.list.model().rowsMoved.connect(self._on_rows_moved)

        session.line_opened.connect(lambda _key: self.rebuild())
        session.stack_changed.connect(self._on_stack_changed)
        session.site_closed.connect(self.rebuild)
        self.rebuild()

    # ---- state ------------------------------------------------------------
    def key(self) -> str | None:
        return self.session.current_key if self.session.is_open else None

    def current_row(self) -> int:
        return self.list.currentRow()

    def rebuild(self) -> None:
        key = self.key()
        keep = self.list.currentRow()
        self._updating = True
        try:
            self.list.clear()
            if key is not None:
                for step, enabled in self.session.stack_for(key).entries:
                    item = QListWidgetItem(step.name)
                    item.setFlags(
                        Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsDragEnabled
                    )
                    item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                    self.list.addItem(item)
            if 0 <= keep < self.list.count():
                self.list.setCurrentRow(keep)
        finally:
            self._updating = False
        has_line = key is not None
        for w in (self.add_button, self.apply_button):
            w.setEnabled(has_line)
        self._update_row_buttons()
        self.step_selected.emit(self.list.currentRow())

    def _update_row_buttons(self) -> None:
        row = self.list.currentRow()
        n = self.list.count()
        self.remove_button.setEnabled(row >= 0)
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(0 <= row < n - 1)

    def _on_stack_changed(self, key: str) -> None:
        if key == self.key():
            self.rebuild()

    # ---- list events ------------------------------------------------------
    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._updating:
            return
        key = self.key()
        if key is None:
            return
        row = self.list.row(item)
        flag = item.checkState() == Qt.CheckState.Checked
        if self.session.stack_for(key).entries[row][1] != flag:
            self.session.set_step_enabled(key, row, flag)

    def _on_current_row(self, row: int) -> None:
        if not self._updating:
            self._update_row_buttons()
            self.step_selected.emit(row)

    def _on_rows_moved(self, _parent: Any, start: int, _end: int, _dest: Any, row: int) -> None:
        if self._updating:
            return
        key = self.key()
        if key is None:
            return
        dst = dest_index(start, row)
        if dst != start:
            self.session.move_step(key, start, dst)

    # ---- actions ----------------------------------------------------------
    def add_step(self, name: str) -> None:
        key = self.key()
        if key is None:
            return
        if required_params(name):
            self.add_step_requested.emit(name)
            return
        self.session.append_step(key, build_step(name, **default_params(name)))
        self.list.setCurrentRow(self.list.count() - 1)

    def remove_selected(self) -> None:
        key = self.key()
        row = self.list.currentRow()
        if key is None or row < 0:
            return
        self.session.remove_step(key, row)

    def move_selected(self, delta: int) -> None:
        key = self.key()
        row = self.list.currentRow()
        dst = row + delta
        if key is None or row < 0 or not 0 <= dst < self.list.count():
            return
        self.session.move_step(key, row, dst)
        self.list.setCurrentRow(dst)

    def apply_to_grid(self, confirm: bool = True) -> list[str]:
        key = self.key()
        if key is None:
            return []
        line = self.session.line_for_key(key)
        grid = self.session.grid_for_line(line)
        if grid is None:
            self.status.setText("this line is not in a grid")
            return []
        if confirm:
            answer = QMessageBox.question(
                self,
                "Apply to grid",
                f"Replace the processing stack of every other line in grid {grid.id} with this one?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return []
        changed = self.session.apply_stack_to_grid(key, grid.id)
        self.status.setText(f"applied to {len(changed)} line(s) in grid {grid.id}")
        return changed
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py` `initGui`, after the profile dock:

```python
        self.processing_dock = ProcessingDock(self.session, main)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.processing_dock)
        self.docks.append(self.processing_dock)
```

with the import, the `__init__` attribute, and `self.processing_dock = None` in `unload`.

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: processing dock with the current line's step stack

Add from the registry (required-parameter steps are requested, not
built), remove, reorder by drag or buttons, enable/disable, apply to
the grid after confirmation. Every edit is a session call; the list is
rebuilt from the stack on each change."
```

---

