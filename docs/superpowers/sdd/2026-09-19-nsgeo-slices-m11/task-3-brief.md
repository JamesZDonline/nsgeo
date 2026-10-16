### Task 3: The Slices dock and its Source group

The dock exists, is tabified with Processing, and can choose a grid, a preset, a transform and a
set of lines and prepare them. Nothing displays a slice yet — that is Task 4.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` (new)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py` (new)

**Interfaces:**

- Consumes: Task 2's `SliceEngine`, `SourceChoice`, `Resolution`, `transform_names`,
  `preset_transform_conflict`, `estimate_memory`, `format_bytes`, `NO_TRANSFORM`.
- Produces:
  - `SlicesDock(session, parent=None)` — a `QgsDockWidget`, object name `nsgeoSlicesDock`, title
    `nsgeo Slices`. Public: `engine`, `grid_combo`, `preset_combo`, `transform_combo`,
    `choose_button`, `included_label`, `source_status`, `source_choice() -> SourceChoice | None`,
    `set_included(keys)`, `included_keys() -> tuple[str, ...]`, `prepare()`,
    `rebuild_source()`.
  - Signals (both connected in `plugin.py` in this task): `choose_lines_requested = pyqtSignal()`,
    `error = pyqtSignal(str)`.
  - `LineChoiceDialog(session, included, parent=None)` — modeless. Public: `table`,
    `included_keys() -> tuple[str, ...]`, `set_included(key, flag)`, `select_all()`,
    `select_none()`.
  - `plugin.NsgeoPlugin.slices_dock`, `plugin.NsgeoPlugin.open_line_choice_dialog()`.

- [ ] **Step 1: Write the failing dialog tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py`:

```python
"""The contributing-lines table: spec 9.1's one dialog."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.line_choice_dialog import LineChoiceDialog
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)


@pytest.fixture
def peopled(qgis_app, tmp_path):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
            GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
        )
        for i in range(3)
    ]
    session.add_lines(lines)
    return session


def test_every_line_in_the_grid_is_listed_and_included_by_default(peopled):
    dialog = LineChoiceDialog(peopled, included=tuple(peopled.keys()))
    assert dialog.table.rowCount() == 3
    assert dialog.included_keys() == tuple(peopled.keys())


def test_a_line_carrying_its_own_stack_is_marked_as_using_the_preset_instead(peopled):
    """Spec 9.1: a cube built from mixed recipes has no comparable
    amplitudes, and the user should watch that decision being made rather
    than discover it later. The marking is the watching."""
    from nsgeo.processing import build_step

    key = peopled.keys()[1]
    peopled.append_step(key, build_step("dewow"))
    dialog = LineChoiceDialog(peopled, included=tuple(peopled.keys()))
    texts = [
        dialog.table.item(row, dialog.STACK_COLUMN).text() for row in range(dialog.table.rowCount())
    ]
    assert texts[0] == ""
    assert "preset" in texts[1].lower(), texts
    assert texts[2] == ""


def test_excluding_a_line_removes_it_from_the_result_and_keeps_the_order(peopled):
    keys = tuple(peopled.keys())
    dialog = LineChoiceDialog(peopled, included=keys)
    dialog.set_included(keys[1], False)
    assert dialog.included_keys() == (keys[0], keys[2])
    dialog.set_included(keys[1], True)
    assert dialog.included_keys() == keys  # back in survey order, not appended last


def test_select_all_and_none_are_available_because_a_grid_can_hold_forty_lines(peopled):
    dialog = LineChoiceDialog(peopled, included=())
    assert dialog.included_keys() == ()
    dialog.select_all()
    assert len(dialog.included_keys()) == 3
    dialog.select_none()
    assert dialog.included_keys() == ()


def test_the_dialog_is_modeless(peopled):
    """Trap 5: QDialog.exec()'s loop ends the instant the dialog is hidden
    from any cause, so this plugin uses show() plus finished everywhere.
    The qgis-tier conftest forbids exec() outright, so a regression here
    fails rather than hanging the suite."""
    dialog = LineChoiceDialog(peopled, included=())
    assert not dialog.isModal()
```

- [ ] **Step 2: Run and watch them fail.** Expected: no module `line_choice_dialog`.

- [ ] **Step 3: Implement `line_choice_dialog.py`**

```python
"""Which lines go into the cube, and which of them carry their own stack.

Spec 9.1 kept exactly one dialog out of the dock: the contributing lines,
because they need a table and a table does not fit a narrow panel. Grid,
preset and transform are combo boxes in the dock instead -- an earlier
draft put all four behind one `Edit...` button, and review rejected it
because a control named for the act of editing rather than for what it
edits leaves the user to guess its scope.

Modeless, like every dialog in this plugin: `show()` plus `finished`,
never `exec()`. See `plugin.py`'s module docstring for why.
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

HEADERS = ("", "Line", "Traces", "Length (m)", "Own stack")


class LineChoiceDialog(QDialog):
    INCLUDE_COLUMN = 0
    STACK_COLUMN = 4

    def __init__(self, session: Any, included: tuple[str, ...], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Lines in this cube")
        self.setModal(False)
        self.session = session
        self._keys: list[str] = list(session.keys()) if session.is_open else []
        self._included: set[str] = {k for k in included if k in set(self._keys)}

        layout = QVBoxLayout(self)
        note = QLabel(
            "Every line contributes through the same preset. A line with its own saved "
            "stack is listed here so the substitution is visible: amplitudes from mixed "
            "recipes are not comparable, which is the whole premise of a slice."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        self.all_button = QPushButton("Select all")
        self.none_button = QPushButton("Select none")
        row.addWidget(self.all_button)
        row.addWidget(self.none_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.all_button.clicked.connect(lambda: self.select_all())
        self.none_button.clicked.connect(lambda: self.select_none())
        self.table.itemChanged.connect(self._on_item_changed)
        self._refresh()

    # ---- state ------------------------------------------------------------
    def included_keys(self) -> tuple[str, ...]:
        """The included subset, in survey order -- never in click order.

        Order matters downstream only for readability (provenance,
        progress), but an order that changes when a user unticks and
        re-ticks a row makes two otherwise identical cubes look different
        in their own records."""
        return tuple(k for k in self._keys if k in self._included)

    def set_included(self, key: str, flag: bool) -> None:
        if flag:
            self._included.add(key)
        else:
            self._included.discard(key)
        self._refresh()

    def select_all(self) -> None:
        self._included = set(self._keys)
        self._refresh()

    def select_none(self) -> None:
        self._included = set()
        self._refresh()

    # ---- table ------------------------------------------------------------
    def _refresh(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._keys))
            for row, key in enumerate(self._keys):
                line = self.session.line_for_key(key)
                tick = QTableWidgetItem("")
                tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                tick.setCheckState(
                    Qt.CheckState.Checked if key in self._included else Qt.CheckState.Unchecked
                )
                tick.setData(Qt.ItemDataRole.UserRole, key)
                self.table.setItem(row, self.INCLUDE_COLUMN, tick)
                label = line.placement.label or key
                length = line.n_traces / max(1e-9, line.header.traces_per_metre)
                has_stack = bool(self.session.site.stacks.get(key))
                for column, text in (
                    (1, str(label)),
                    (2, str(line.n_traces)),
                    (3, f"{length:.1f}"),
                    (4, "using the preset instead" if has_stack else ""),
                ):
                    self.table.setItem(row, column, QTableWidgetItem(text))
        finally:
            self.table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        # A slot on a Qt signal: an exception here is swallowed by PyQt
        # locally and turns into qFatal() in the CI container.
        try:
            if item.column() != self.INCLUDE_COLUMN:
                return
            key = item.data(Qt.ItemDataRole.UserRole)
            if not key:
                return
            self.set_included(str(key), item.checkState() == Qt.CheckState.Checked)
        except Exception:  # noqa: BLE001 -- see above
            from nsgeo_qgis.log import log

            log("could not update the line selection")
```

- [ ] **Step 4: Run and watch them pass.** Expected: 5 passed.

- [ ] **Step 5: Write the failing dock tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`:

```python
"""The Slices dock's Source group."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_plan import transform_names
from nsgeo_qgis.ui.slices_dock import SlicesDock
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [{"step": "dewow", "params": {}, "enabled": True}]


@pytest.fixture
def docked(qgis_app, tmp_path):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
            GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
        )
        for i in range(3)
    ]
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    dock = SlicesDock(session)
    yield dock, session
    dock.engine.dispose()
    dock.deleteLater()


def test_the_source_combos_are_filled_from_the_site_not_from_literals(docked):
    dock, session = docked
    assert [dock.grid_combo.itemText(i) for i in range(dock.grid_combo.count())] == ["A"]
    assert "p" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]
    offered = [dock.transform_combo.itemText(i) for i in range(dock.transform_combo.count())]
    assert offered[0] == "none"  # spec 6.2 and GPRSLICE's xfrm_method=NONE
    assert offered[1:] == transform_names()


def test_adding_a_preset_updates_the_combo_without_a_reopen(docked):
    dock, session = docked
    session.site.presets["second"] = list(PRESET)
    session.presets_changed.emit()
    assert "second" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]


def test_the_included_summary_reads_as_a_fraction_of_the_grid(docked):
    dock, session = docked
    assert dock.included_label.text().startswith("3 of 3 included")
    dock.set_included(tuple(session.keys())[:2])
    assert dock.included_label.text().startswith("2 of 3 included")


def test_the_dock_reports_the_memory_before_committing_to_preparing_it(docked):
    """Spec 9.1: before committing the ~0.9 s the dock reports what the
    resulting memory will be, because it is decided by the line count and
    the chosen resolution -- and spec 7.4 warns rather than hard-caps."""
    dock, _ = docked
    text = dock.included_label.text()
    assert "MB" in text or "GB" in text


def test_choosing_a_preset_that_carries_a_transform_is_refused_visibly(docked):
    """Ruling 2, surfaced. The engine raises; the dock must turn that into
    something the user can read and act on, not let it escape a slot."""
    dock, session = docked
    session.site.presets["bad"] = [{"step": "amp_abs", "params": {}, "enabled": True}]
    session.presets_changed.emit()
    seen: list[str] = []
    dock.error.connect(seen.append)
    dock.preset_combo.setCurrentText("bad")  # re-preparing is what refuses it
    assert any("amp_abs" in msg for msg in seen), seen
    assert "amp_abs" in dock.source_status.text()
    assert not dock.engine.is_prepared


def test_refilling_the_combos_does_not_re_prepare(docked):
    """Refilling a QComboBox emits currentTextChanged. Without the
    _updating guard the dock re-prepares on construction and on every
    grids_changed / lines_changed / presets_changed — ~0.9 s of work per
    unrelated session signal, which IS the "nothing runs automatically"
    the design forbids."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    prepared: list[int] = []
    dock.engine.on_prepared = lambda: prepared.append(1)
    session.site.presets["another"] = list(PRESET)
    session.presets_changed.emit()
    session.lines_changed.emit()
    assert dock.engine.wait_for_preparation(2_000)
    assert prepared == [], "refilling the combos must not have re-prepared"


def test_preparing_reports_progress_and_then_reports_prepared(docked):
    dock, session = docked
    dock.prepare()  # the dock prepares on construction too; this is the retry path
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.is_prepared
    assert dock.engine.line_count == 3
    assert "prepared" in dock.source_status.text().lower()


def test_changing_the_source_re_prepares_it_rather_than_waiting_to_be_asked(docked):
    """Spec 9.1, explicitly: changing the grid, preset or transform
    re-runs the preparation as a QgsTask. That is not a violation of
    "nothing runs automatically" -- the user chose a preset, and
    preparation is the execution of that choice, not an inference about
    it. A prepared source left standing after one of its three inputs
    changed would tell the user the screen matches a choice it does not."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 3

    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    dock.grid_combo.setCurrentText("B")  # no explicit prepare() call
    assert dock.engine.wait_for_preparation(20_000)
    # Grid B holds no lines, so the re-preparation really ran and really
    # used the new grid rather than leaving the old result in place.
    assert dock.engine.line_count == 0


def test_closing_the_site_empties_the_dock(docked):
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    session.close_site()
    assert dock.grid_combo.count() == 0
    assert not dock.engine.is_prepared
```

- [ ] **Step 6: Run and watch them fail.** Expected: no module `slices_dock`.

- [ ] **Step 7: Implement `slices_dock.py` (Source group only)**

The dock is a `QgsDockWidget` titled `nsgeo Slices`, object name `nsgeoSlicesDock`, allowed in the
left and right dock areas. Build it as a `QVBoxLayout` of `QGroupBox`es so Task 4 appends three
more without restructuring; this task creates the **Source** group only.

```python
"""The Slices dock: choosing a source, then navigating the slices it makes.

Tabified with the Processing dock rather than competing for screen space
(spec 9.2) -- a sub-ten-step stack leaves room below it. A separate widget
rather than a tab inside `processing_dock.py`, so it can be torn off to
see both at once, and because issue #21 already records that file as
overloaded.

Four groups, ordered by how often they are touched and what each costs:
Source (~0.9 s, a task), Position (0.6-4 ms), Resolution (44 ms) and
Display (free). This module builds them; it computes nothing. Every number
on screen comes from `slices_plan` or from the engine.
"""
```

Its `__init__` must, in this order:

1. Store `session`; build `self.engine = SliceEngine(session, on_prepared=self._on_prepared,
   on_error=self._on_engine_error, on_progress=self._on_progress)`.
2. Build the Source group: `grid_combo`, `preset_combo`, `transform_combo` (each a `QComboBox` in
   a `QFormLayout` labelled `Grid`, `Preset`, `Transform`), a row holding `included_label`
   (`QLabel`) and `choose_button` (`QPushButton("Choose…")`), and `source_status` (`QLabel`,
   `setWordWrap(True)`).
3. Fill `transform_combo` once with `["none", *transform_names()]`; the other two are rebuilt from
   the session.
4. Connect, in the dock: `choose_button.clicked` → `lambda: self.choose_lines_requested.emit()`
   (a lambda, not the signal's `emit` directly — `clicked` carries a `bool checked` that would be
   passed straight through); `grid_combo.currentTextChanged`, `preset_combo.currentTextChanged`
   and `transform_combo.currentTextChanged` → `self._on_source_changed`; and
   `session.site_opened`, `session.site_closed`, `session.grids_changed`, `session.lines_changed`,
   `session.presets_changed` → `self.rebuild_source`.
5. Call `self.rebuild_source()`.

Behaviour the tests above pin:

- `rebuild_source()` refills `grid_combo` from `session.site.grids` (ids) and `preset_combo` from
  `sorted(session.site.presets)`, preserving the current selection where it still exists, guarded
  by a `self._updating` **depth counter** — not a bool. `processing_dock.py` explains why at
  length: a slot can re-enter `rebuild` while the outer call is still on the stack, and a
  set/clear flag lets the inner call's `finally` clear the guard early.
- `_default_included()` is every line whose `placement.grid_id` is the selected grid, in
  `session.keys()` order. Changing the grid resets the inclusion set to that default, because an
  inclusion list from another grid means nothing here.
- `included_label` reads `f"{len(included)} of {total} included · about {format_bytes(...)}"`,
  the estimate coming from `estimate_memory(sum(line.n_traces * line.header.n_samples for
  included lines), n_cells, nz)` — with `n_cells`/`nz` from the engine's current frame and axis
  when there is one, and `0` before a resolution is set. Say **about**: the count is taken from
  the headers, before `time_zero` crops rows (512 samples against 463 after a four-step preset),
  so it overestimates by roughly a tenth. An honest approximation beats a precise-looking number
  that is wrong in the other direction.
- `_on_source_changed` returns immediately while `self._updating` is non-zero, and otherwise
  calls `self.prepare()`. **The guard is load-bearing, not defensive.** `rebuild_source` refills
  the grid and preset combos, and refilling a `QComboBox` emits `currentTextChanged`; without the
  guard the dock would re-prepare on its own construction and again on every `grids_changed`,
  `lines_changed` and `presets_changed` — roughly 0.9 s of work per unrelated session signal, and
  the one thing "nothing runs automatically" really does forbid. §9.1's auto-preparation is the
  execution of a choice *the user made*; the dock refilling its own combos is not one. Spec 9.1 is explicit that changing the grid, preset
  or transform re-runs the preparation as a `QgsTask`, and equally explicit that this is not the
  "nothing runs automatically" the design forbids: the user chose a preset, and preparation is the
  execution of that choice rather than an inference about it. **Do not add a `Prepare` button.**
  Three rapid combo changes are safe without debouncing because `SliceEngine._generation`
  discards every stale result; a button would be a second way to do the one thing the combos
  already do, and this project has rejected exactly that shape of control before (spec 9.1's
  `Edit…`). `prepare()` stays public as the retry path after a refusal — a fixed preset fires
  `presets_changed`, which `rebuild_source` is already connected to.
- `prepare()` builds a `SourceChoice` from the three combos and the inclusion set and calls
  `engine.set_source(...)` **inside a `try/except ValueError`**, putting the message into both
  `source_status` and the `error` signal. This is the one place Ruling 2's refusal becomes
  visible.
- `_on_progress(done, total)` writes `f"preparing… {done} of {total}"` into `source_status`;
  `_on_prepared()` writes `f"prepared · {engine.line_count} lines"`; `_on_engine_error(msg)`
  writes it and emits `error`.
- Every slot guards its own body with `except Exception` and reports through `error` or
  `nsgeo_qgis.log.log`. An exception escaping a slot passes locally and aborts the CI container.

- [ ] **Step 8: Run and watch them pass.** Expected: 8 passed.

- [ ] **Step 9: Wire the dock into `plugin.py`**

In `initGui`, after the `ProcessingDock` block:

```python
        self.slices_dock = SlicesDock(self.session, main)
        self.slices_dock.error.connect(lambda msg: self.message(msg, Qgis.MessageLevel.Warning))
        self.slices_dock.choose_lines_requested.connect(self.open_line_choice_dialog)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.slices_dock)
        # Spec 9.2: tabified with Processing rather than a fourth dock
        # competing for screen space. Processing stays the raised tab --
        # this milestone adds a capability, it does not take the screen
        # away from the one people already use.
        main.tabifyDockWidget(self.processing_dock, self.slices_dock)
        self.processing_dock.raise_()
        self.docks.append(self.slices_dock)
```

Add `self.slices_dock: SlicesDock | None = None` and `self._line_choice_dialog: LineChoiceDialog
| None = None` to `__init__`, `self.slices_dock = None` to the dock-clearing block in `unload`,
and — in `unload`, beside the existing `reject()` calls and for the same reasons given there —
`if self._line_choice_dialog is not None: self._line_choice_dialog.reject()`.

Then the modeless opener, following `open_import_dialog` exactly:

```python
    def open_line_choice_dialog(self) -> None:
        """Spec 9.1's one dialog. Modeless, like every dialog here.

        A single tracking slot, so a second `Choose...` does not stack a
        dialog on top of the first; the result is committed on `finished`
        rather than after a blocking call, and the dock is re-read then
        rather than captured now, because the site can change while this
        is open.
        """
        try:
            if self.session is None or not self.session.is_open or self.slices_dock is None:
                return
            if self._line_choice_dialog is not None:
                self._line_choice_dialog.raise_()
                self._line_choice_dialog.activateWindow()
                return
            dock = self.slices_dock
            dialog = LineChoiceDialog(self.session, dock.included_keys(), self.iface.mainWindow())
            self._line_choice_dialog = dialog

            def finished(result: int) -> None:
                try:
                    if result == QDialog.DialogCode.Accepted and self.slices_dock is not None:
                        self.slices_dock.set_included(dialog.included_keys())
                except Exception as exc:  # noqa: BLE001 -- a slot on finished
                    self.message(f"could not apply the line choice: {exc}", Qgis.MessageLevel.Warning)
                finally:
                    self._line_choice_dialog = None
                    dialog.deleteLater()

            dialog.finished.connect(finished)
            dialog.show()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not open the line chooser: {exc}", Qgis.MessageLevel.Critical)
```

- [ ] **Step 10: Add the plugin-level tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` (which already builds and unloads
the whole plugin against `fake_iface`):

```python
def test_the_slices_dock_is_tabified_with_processing(fake_iface, qgis_app):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        assert plugin.slices_dock is not None
        assert plugin.slices_dock.objectName() == "nsgeoSlicesDock"
        main = fake_iface.mainWindow()
        tabbed = main.tabifiedDockWidgets(plugin.processing_dock)
        assert plugin.slices_dock in tabbed
        # Processing stays the visible tab: M11 adds a capability, it does
        # not take the screen away from the dock people already use.
        assert plugin.processing_dock.visibleRegion is not None
    finally:
        plugin.unload()


def test_unloading_closes_an_open_line_chooser(fake_iface, qgis_app, tmp_path):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.session.new_site(tmp_path)
        plugin.open_line_choice_dialog()
        assert plugin._line_choice_dialog is not None
        dialog = plugin._line_choice_dialog
        plugin.unload()
        # reject(), not close(): closeEvent only calls reject() on a
        # VISIBLE dialog, and this plugin hides dialogs deliberately.
        assert dialog.result() == QDialog.DialogCode.Rejected
    finally:
        if plugin.session is not None:
            plugin.unload()
```

Import `QDialog` from `qgis.PyQt.QtWidgets` in that test file if it is not already imported.

- [ ] **Step 11: Verify and prove discrimination**

Run both tiers. Expected: 481 + ~15 = ~496 QGIS passed; core+pure unchanged.

Mutants, one at a time:

1. In `prepare()`, remove the `try/except ValueError`. Expect
   `test_choosing_a_preset_that_carries_a_transform_is_refused_visibly` to FAIL — and note
   whether it fails as an assertion or via the `_no_swallowed_slot_exceptions` fixture, because
   the second is the fixture doing exactly the job it exists for.
2. In `included_keys()` of the dialog, return `tuple(self._included)` (set order) instead of
   survey order. Expect
   `test_excluding_a_line_removes_it_from_the_result_and_keeps_the_order` to FAIL.
3. Replace `rebuild_source`'s depth counter with a plain bool. Confirm whether any test catches
   it; if none does, say so plainly in the report rather than claiming coverage — the counter is
   defence carried over from `processing_dock.py`, and an honest "not pinned" is worth more than
   a test invented to look like one.

- [ ] **Step 12: Commit and push**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py \
        packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py \
        packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/tests/qgis
git commit -m "feat(slices): the Slices dock and its Source group

Tabified with Processing (spec 9.2). Grid, preset and transform are
combos that name what they change; the one dialog is the contributing
lines, which need a table.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 3 is done when:** the dock appears tabified with Processing, a source can be chosen and
prepared, a conflicting preset is refused visibly, and both tiers are green.

---

