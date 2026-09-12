"""The processing dock: the current line's step stack.

Steps come from the registry, never from a hardcoded list. Every edit goes
through the session so the core's no-mutation rule holds and every other
view updates. Nothing here computes anything.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import available_steps, build_step, default_params, get_step, required_params
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
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

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.lookup import identity_curve
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.add_step_dialog import AddStepDialog
from nsgeo_qgis.ui.param_form import ParamForm


def dest_index(start: int, row: int) -> int:
    """Translate QAbstractItemModel.rowsMoved's destination row (the row the
    item is inserted *before*, in pre-move numbering) into the index the
    item ends up at.

    A row moving down (`row > start`) is removed from `start` first, which
    shifts every later index down by one before the insertion, so it lands
    at `row - 1`. A row moving up (`row < start`) is unaffected by its own
    later removal, so it lands exactly at `row`.

    The tie (`row == start`) is not something a real `rowsMoved` ever
    reports: Qt's `beginMoveRows` rejects a same-parent destination inside
    `[start, start + 1]` (verified directly against a live
    `QListWidget.model()`: `moveRow(src=1, dest=1)` and
    `moveRow(src=1, dest=2)` both return `False` and emit nothing). Using
    `row <= start` here rather than `row < start` is defensive only, for
    that unreachable case -- it costs nothing, and lands it back at `start`
    instead of one short of it. What actually stops a same-position drop
    from spuriously calling `session.move_step` is `_on_rows_moved`'s own
    `dst != start` guard below, not this function.
    """
    return row if row <= start else row - 1


class ProcessingDock(QgsDockWidget):
    step_selected = pyqtSignal(int)  # -1 when nothing is selected
    add_step_requested = pyqtSignal(str)  # steps with REQUIRED params

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Processing", parent)
        self.setObjectName("nsgeoProcessingDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.session = session
        # A depth counter, not a bool: Task 17 connects `step_selected`
        # (emitted at the end of `rebuild()`) to a parameter form that can
        # write back to the session, which can trigger a nested
        # `rebuild()` while the outer one is still on the stack. A plain
        # set/clear flag would let the inner call's `finally` clear the
        # guard while the outer frame is still mid-rebuild; a counter
        # only reaches zero when the outermost call finishes.
        self._updating = 0
        # `_show_form` last actually displayed: the (key, row) it was shown
        # at, AND the step object identity found there. `rebuild()` emits
        # `step_selected` unconditionally every time it runs, including the
        # echo that comes back from this very form's own commits
        # (`_on_form_committed` -> `session.replace_step` -> `stack_changed`
        # -> `rebuild()`) and the second of `add_step()`'s two emissions
        # (once from `rebuild()`, once from its own `setCurrentRow`).
        # Rebuilding on that echo would call `self.form.clear()` and tear
        # down every editor, including the very one whose `editingFinished`
        # just fired, discarding whatever the user has typed into any other
        # field that has not been committed yet -- so a genuine echo (the
        # row and the step at it both unchanged) must be a no-op.
        #
        # (key, row) alone is NOT enough: it cannot distinguish "same row,
        # same step" (an echo) from "same row, a *different* step now sits
        # there" (a real change this form must show) -- e.g. removing the
        # row above the selection, or an insert at/above it, both leave
        # `row` unchanged while swapping in a different step underneath.
        # Comparing the step's object identity as well as its position
        # fixes that: this project never mutates a step in place (every
        # edit is `build_step(...)` producing a new instance), so identity
        # is exactly "is this the step whose editors are already on
        # screen", not merely "is this the same list position". -2 is a
        # sentinel no real row index is, so the very first `step_selected`
        # (row -1, nothing open yet) is never mistaken for an echo.
        self._shown: tuple[str | None, int] = (None, -2)
        self._shown_step: Any = None

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
            # `checked=False` absorbs whatever `addAction`'s convenience
            # overload passes the slot -- binding the zero-argument
            # `triggered()` overload is an implementation detail of that
            # overload, not documented API, and this repo has no PyQt6 to
            # confirm it holds there too. `n=name` keeps the step name
            # correct under either binding (see `test_add_menu_...` below,
            # which triggers these for real rather than only reading text).
            self.add_menu.addAction(text, lambda checked=False, n=name: self.add_step(n))
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
        self.form = ParamForm(body)
        self.form_area.addWidget(self.form)
        self.form.committed.connect(self._on_form_committed)
        self.step_selected.connect(self._show_form)
        self.add_step_requested.connect(self.add_step_with_dialog)

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
        # Not `.connect(self.apply_to_grid)`: `clicked` carries a `bool
        # checked` argument, and Qt's own argument-trimming would hand
        # that straight to `apply_to_grid`'s `confirm` parameter -- every
        # real click would then silently pass `confirm=False` and skip
        # the "replace every other line" prompt entirely. The lambda
        # drops the `checked` argument so a real click always confirms.
        self.apply_button.clicked.connect(lambda: self.apply_to_grid())
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.currentRowChanged.connect(self._on_current_row)
        self.list.model().rowsMoved.connect(self._on_rows_moved)

        session.line_opened.connect(self.rebuild)
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
        # A stack change (or a line switch) makes any earlier "applied to
        # N line(s)" or "cancelled" caption stale; this is the one piece
        # of state in this dock that isn't just re-read from the session,
        # so it's cleared on every rebuild rather than left to say
        # something about a stack that no longer applies.
        self.status.setText("")
        keep = self.list.currentRow()
        self._updating += 1
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
                    item.setCheckState(
                        Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
                    )
                    self.list.addItem(item)
            if 0 <= keep < self.list.count():
                self.list.setCurrentRow(keep)
        finally:
            self._updating -= 1
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

    # ---- form ---------------------------------------------------------
    def _show_form(self, row: int) -> None:
        key = self.key()
        shown = (key, row)
        if key is None or row < 0:
            if shown == self._shown:
                return  # already showing "nothing"
            self._shown, self._shown_step = shown, None
            self.form.clear()
            return
        step, _ = self.session.stack_for(key).entries[row]
        if shown == self._shown and step is self._shown_step:
            return  # an echo of our own commit, or add_step()'s second emit
        self._shown, self._shown_step = shown, step
        self.form.set_step(step.name, step.params)

    def _on_form_committed(self, params: dict[str, Any]) -> None:
        key = self.key()
        row = self.list.currentRow()
        if key is None or row < 0 or self.form.step_name is None:
            return
        current = self.session.stack_for(key).entries[row][0]
        # Second line of defence: if the row this form is bound to no
        # longer holds the exact step object the form was built from (it
        # shouldn't, given `_show_form`'s identity check above, but this is
        # cheap and turns any residual desync into a no-op instead of
        # corrupting the wrong step), bail rather than write the new params
        # onto it. Identity, not just `.name`: two steps of the same kind
        # (e.g. `[dewow_a, dewow_b]`, remove row 0) would share a name but
        # are still the wrong step to overwrite -- `_show_form` keeps
        # `self._shown_step` in lockstep with what this form displays, so
        # comparing against that is strictly stronger than comparing names.
        if current is not self._shown_step:
            return
        if current.params == params:
            return
        new = build_step(self.form.step_name, **params)
        # Set before replace_step: the stack_changed -> rebuild() ->
        # step_selected echo this triggers reports this exact object back
        # to _show_form, which then correctly recognises it as the step
        # already on screen and skips rebuilding the editors.
        self._shown_step = new
        self.session.replace_step(key, row, new)

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

    def time_axis(self) -> tuple[float, float, int]:
        """(t0_ns, dt_ns, n_samples) of the input a step appended right now
        would actually receive: the stack's own `result()` when it
        evaluates cleanly, so a step already in the stack that changes the
        axis (`time_zero` crops both `t0_ns` and `n_samples` -- see
        `nsgeo.processing.timezero`) is accounted for, exactly as the new
        step's own `apply()` will see it. Only used today to seed a new
        curve step's identity default (see `add_step_with_dialog`), so the
        distinction only bites once something ahead of it in the stack
        changes the sample axis.

        `result()` can raise `ValueError` when some OTHER step already in
        the stack is misconfigured (a bandpass whose high cut exceeds
        Nyquist, say) -- that is a problem with that step, not a reason
        this method should raise too: it falls back to the stack's raw
        source instead, same as before this method looked at `result()` at
        all, and to the line's header when nothing has loaded yet. Logged
        when it fires: the seed then lands on the raw axis while the
        viewer keeps its last good (possibly quite different) transform,
        so a curve step seeded right now can end up with control points
        off the drawn axis with nothing said otherwise."""
        key = self.key()
        assert key is not None
        stack = self.session.stack_for(key)
        if stack.source is not None:
            try:
                rg = stack.result()
            except ValueError as exc:
                _log(
                    f"time_axis: stack does not evaluate cleanly ({exc}); "
                    "seeding a new step against the raw source axis instead"
                )
                rg = stack.source
            return rg.t0_ns, rg.dt_ns, rg.n_samples
        h = self.session.line_for_key(key).header
        return h.position_ns, h.dt_ns, h.n_samples

    def build_add_dialog(self, name: str) -> AddStepDialog:
        key = self.key()
        assert key is not None
        line = self.session.line_for_key(key)
        return AddStepDialog(
            name, header=line.header, radargram=self.session.stack_for(key).source, parent=self
        )

    def append_from_dialog(self, dialog: AddStepDialog) -> None:
        key = self.key()
        step = dialog.result_step()
        if key is None or step is None:
            return
        self.session.append_step(key, step)
        self.list.setCurrentRow(self.list.count() - 1)

    def add_step_with_dialog(self, name: str) -> None:
        key = self.key()
        if key is None:
            return
        specs = get_step(name).schema()
        required = [s for s in specs if s.required]
        if required and all(s.kind == "curve" for s in required):
            # The identity curve is not a guess: seed it and let the strip edit it.
            t0, dt, n = self.time_axis()
            params = {s.name: identity_curve(t0, dt, n) for s in required}
            params.update(default_params(name))
            self.session.append_step(key, build_step(name, **params))
            self.list.setCurrentRow(self.list.count() - 1)
            return
        dialog = self.build_add_dialog(name)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.append_from_dialog(dialog)
        finally:
            # Parenting (`parent=self` in build_add_dialog) keeps Qt from
            # segfaulting on a parentless-widget GC, but it also means the
            # dialog otherwise lives on, hidden, for the dock's whole
            # lifetime -- every add-step interaction would leak one.
            dialog.deleteLater()

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
                f"Replace the processing stack of every other line in grid {grid.id} "
                "with this one?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.status.setText("cancelled; nothing was applied")
                return []
        changed = self.session.apply_stack_to_grid(key, grid.id)
        self.status.setText(f"applied to {len(changed)} line(s) in grid {grid.id}")
        return changed
