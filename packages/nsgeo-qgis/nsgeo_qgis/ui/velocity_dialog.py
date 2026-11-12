"""The velocity dialog, for one line or one grid: type a number, take one
from a saved fit, or average the fits ticked.

A line's dialog lists that line's fits. A grid's lists every fit on every line
currently on the grid, with a Line column (grid velocity spec §4). One class
serves both, so they share one table, one average and one Apply rule. Rows are
keyed by (line key, fit id) in both, because every line has a `fit-1`.

`velocity()` is the whole answer: a model to apply, or `None` for "remove the
velocity". `chosen_source()` is the record of where that number came from
(spec §7.2): the record follows the last thing that filled the box, and only
while the box still holds that value. A typed number has no source.

Deleting a fit is the one thing here that does not wait for Apply: Apply also
writes the spin box as the velocity, and opening the dialog only to delete a
bad fit must not set a velocity on the way.

Fits are listed by line in survey order, then by t0 (shallowest first); a
column header click sorts by that column. A pair whose velocities differ by
more than 2 * sqrt(s1^2 + s2^2) is flagged. That is a passive diagnostic, not a
refusal: it says the ground looks layered, which a later Dix conversion acts
on.
"""

from __future__ import annotations

import math
import traceback
from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit, applied_fit_note, fit_at_zero, unusable_fit_note
from nsgeo.velocity_source import (
    METHOD_FIT,
    METHOD_WEIGHTED_MEAN,
    VelocitySource,
    weighted_mean,
)
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.finish_panel import busy_cursor
from nsgeo_qgis.velocity_records import applied_now, fit_record, line_label

# What each column holds, by scope. The tick is always first and the flag last.
_LINE_COLUMNS = ("tick", "t0", "v", "rms", "points", "flag")
_GRID_COLUMNS = ("tick", "line", "t0", "v", "rms", "points", "flag")
_HEADER_TEXT = {
    "tick": "",
    "line": "Line",
    "t0": "t0 (ns)",
    "v": "v ± σ (m/ns)",
    "rms": "rms (ns)",
    "points": "points",
    "flag": "",
}
_TICK_COLUMN = 0

_GRID_HINT = "Slices and cuts on this grid use this velocity."
_LINE_INTRO = (
    "Saved hyperbola fits on this line. Tick fits to average them; pick one to use its velocity."
)
_GRID_INTRO = (
    "Saved hyperbola fits on this grid's lines. Tick fits to average them; "
    "pick one to use its velocity."
)
_DISAGREE_WARNING = (
    "Some ticked fits disagree with each other. The ground may be layered, "
    "and one number may not suit every depth."
)
_WEIGHT_NOTE = "Weighted by each fit's ±: tighter fits count for more."

Ref = tuple[str, str]  # (line key, fit id): every line has a fit-1
_K = TypeVar("_K")

# Two fits disagree when their velocities differ by more than this many
# combined standard errors. 1 would cry wolf on about a third (31.7%) of pairs
# that are genuinely identical; 2 flags about 4.6%, the conventional line.
_DISAGREEMENT_SIGMAS = 2.0


def disagreeing_fit_ids(fits: Mapping[_K, StoredFit]) -> frozenset[_K]:
    """Keys of every fit that disagrees with at least one other: velocities
    further apart than `_DISAGREEMENT_SIGMAS` times the two standard errors
    combined in quadrature."""
    items = list(fits.items())
    flagged: set[_K] = set()
    for i, (id_a, a) in enumerate(items):
        for id_b, b in items[i + 1 :]:
            combined = math.hypot(a.v_stderr_m_ns, b.v_stderr_m_ns)
            if abs(a.v_m_ns - b.v_m_ns) > _DISAGREEMENT_SIGMAS * combined:
                flagged.update((id_a, id_b))
    return frozenset(flagged)


def fits_at_line_zero(
    session: SiteSession, key: str
) -> tuple[dict[str, StoredFit], dict[str, str]]:
    """Each stored fit of line `key` measured from the line's current time
    zero, and the reasons any could not be. Without a known zero or a
    distance calibration, the stored fits as they are."""
    stored = dict(session.line_for_key(key).velocity_fits)
    if not stored:
        return {}, {}
    zero = session.line_zero(key, load=True)
    if zero is None:
        return stored, {}
    try:
        distance = session.line_for_key(key).distance_along()
    except ValueError:
        return stored, {}
    fits: dict[str, StoredFit] = {}
    failed: dict[str, str] = {}
    for fit_id, fit in stored.items():
        try:
            fits[fit_id] = fit_at_zero(fit, distance, zero)
        except ValueError as exc:
            fits[fit_id] = fit
            failed[fit_id] = str(exc)
    return fits, failed


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


class _AllBox(QCheckBox):
    """A tri-state box that a click only ever turns fully on or fully off."""

    def nextCheckState(self) -> None:  # noqa: N802 -- Qt's name
        if self.checkState() == Qt.CheckState.Checked:
            self.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.setCheckState(Qt.CheckState.Checked)


class VelocityDialog(QDialog):
    # The (line key, fit id) selected in the table, or None: lets the profile
    # light its curve when that line is the one open.
    fit_highlighted = pyqtSignal(object)

    def __init__(
        self,
        session: SiteSession,
        key: str | None = None,
        *,
        grid_id: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if (key is None) == (grid_id is None):
            raise ValueError("a velocity dialog is for one line or one grid")
        super().__init__(parent)
        self.session = session
        self.key = key
        self.grid_id = grid_id
        # A stale key or grid id raises KeyError here, for the caller.
        if grid_id is not None:
            session.grid(grid_id)
            self._keys = session.keys_on_grid(grid_id)
        else:
            session.line_for_key(key)  # type: ignore[arg-type]
            self._keys = [key]  # type: ignore[list-item]
        self._order = {k: i for i, k in enumerate(self._keys)}
        self._labels = {k: line_label(session.line_for_key(k)) for k in self._keys}
        self._kinds = _GRID_COLUMNS if grid_id is not None else _LINE_COLUMNS
        self._column = {kind: i for i, kind in enumerate(self._kinds)}
        self.setWindowTitle(f"Velocity · {grid_id if grid_id is not None else key}")
        self._by_ref: dict[Ref, StoredFit] = {}
        self._rank: dict[Ref, int] = {}
        self._refs: list[Ref] = []
        self._flagged: frozenset[Ref] = frozenset()
        # Each fit at its line's zero as the dialog opened, and why any could
        # not be. Read once per line that has fits (plan call P9): a line not
        # open in the Profile panel is read from its file to find its zero.
        self._at_zero: dict[Ref, StoredFit] = {}
        self._unusable: dict[Ref, str] = {}
        fitted = [k for k in self._keys if session.line_for_key(k).velocity_fits]
        if fitted:
            with busy_cursor():
                for k in fitted:
                    fits, failed = fits_at_line_zero(session, k)
                    self._at_zero.update({(k, i): f for i, f in fits.items()})
                    self._unusable.update({(k, i): why for i, why in failed.items()})
        self._cleared = False
        self._selected: Ref | None = None
        self._quiet_select = False
        # The column the rows are sorted by, and which way (a header click).
        self._sort_kind = "line" if grid_id is not None else "t0"
        self._sort_descending = False
        # What last filled the box (spec §7.2): "none", "average" (with the
        # refs ticked at the press and the value it put there) or "pick".
        self._fill_kind = "none"
        self._fill_refs: tuple[Ref, ...] = ()
        self._fill_value = 0.0
        self._average: tuple[float, float] | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.0, 0.3)
        self.spin.setDecimals(4)
        self.spin.setSingleStep(0.001)
        self.spin.setSpecialValueText("required")
        self.spin.setValue(self._velocity_in_force())
        self.velocity_hint = QLabel(_GRID_HINT if grid_id is not None else "")
        self.velocity_hint.setVisible(grid_id is not None)
        box_row = QHBoxLayout()
        box_row.addWidget(self.spin)
        box_row.addWidget(self.velocity_hint)
        box_row.addStretch()
        form.addRow("Velocity (m/ns)", box_row)
        layout.addLayout(form)

        self._intro_label = QLabel(_GRID_INTRO if grid_id is not None else _LINE_INTRO)
        self._intro_label.setWordWrap(True)
        layout.addWidget(self._intro_label)
        self.all_check = _AllBox("All")
        self.all_check.setTristate(True)
        all_row = QHBoxLayout()
        all_row.addWidget(self.all_check)
        all_row.addStretch()
        layout.addLayout(all_row)
        self.table = QTableWidget(0, len(self._kinds))
        self.table.setHorizontalHeaderLabels([_HEADER_TEXT[k] for k in self._kinds])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        # Just wide enough for the box: most of a row is for picking.
        header.setSectionResizeMode(_TICK_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)
        self._starred_label = QLabel()
        self._starred_label.setWordWrap(True)
        layout.addWidget(self._starred_label)
        delete_row = QHBoxLayout()
        self.delete_button = QPushButton("Delete fit")
        self.delete_button.setToolTip(
            "Remove the selected fit from its line's record."
            if grid_id is not None
            else "Remove the selected fit from this line's record."
        )
        self.delete_button.setEnabled(False)
        delete_row.addWidget(self.delete_button)
        delete_row.addStretch()
        layout.addLayout(delete_row)

        group = QGroupBox("Average of the ticked fits")
        group_layout = QVBoxLayout(group)
        self._average_label = QLabel()
        self._meta_label = QLabel()
        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self.use_average_button = QPushButton("Use average")
        self.use_average_button.setToolTip("Put the average in the velocity box.")
        group_layout.addWidget(self._average_label)
        group_layout.addWidget(self._meta_label)
        group_layout.addWidget(self._warning_label)
        group_layout.addWidget(QLabel(_WEIGHT_NOTE))
        use_row = QHBoxLayout()
        use_row.addWidget(self.use_average_button)
        use_row.addStretch()
        group_layout.addLayout(use_row)
        layout.addWidget(group)
        self._note_label = QLabel()
        self._note_label.setWordWrap(True)
        layout.addWidget(self._note_label)

        buttons = QDialogButtonBox()
        self.apply_button = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.clear_button = QPushButton(
            "Clear grid velocity" if grid_id is not None else "Clear override"
        )
        buttons.addButton(self.clear_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        self._load_rows()
        self._fill_table(self._initial_ticks())
        self._show_sort_indicator()
        self._refresh_average()
        self._refresh_note()
        self._refresh_starred()

        self.spin.valueChanged.connect(self._validate)
        self._validate()
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        header.sectionClicked.connect(self._on_header_clicked)
        self.all_check.stateChanged.connect(self._on_all_changed)
        self.use_average_button.clicked.connect(self._on_use_average)
        self.clear_button.clicked.connect(self._on_clear)
        self.delete_button.clicked.connect(self._on_delete)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self._select_applied_fit()

    # ---- the scope -----------------------------------------------------------
    def _scope_velocity(self) -> tuple[VelocityModel | None, VelocitySource | None]:
        """The velocity this dialog sets, and its record, as they are now."""
        if self.grid_id is not None:
            grid = self.session.grid(self.grid_id)
            return grid.velocity, grid.velocity_source
        line = self.session.line_for_key(self.key)  # type: ignore[arg-type]
        return line.velocity, line.velocity_source

    def _velocity_in_force(self) -> float:
        """What the box shows with nothing filled: a line's resolved velocity,
        or the grid's own (0, "required", when it has none)."""
        if self.grid_id is not None:
            velocity = self.session.grid(self.grid_id).velocity
            return 0.0 if velocity is None else velocity.surface_velocity
        return self.session.resolved_velocity(self.key).surface_velocity  # type: ignore[arg-type]

    def _applied_ref(self) -> Ref | None:
        """The one fit behind the velocity, when the record is a single fit
        still present here."""
        model, record = self._scope_velocity()
        if model is None or record is None or record.method != METHOD_FIT:
            return None
        if len(record.members) != 1:
            return None
        member = record.members[0]
        ref = (member.line_key, member.fit_id)
        if ref not in self._by_ref or self.session.member_state(member, self.grid_id) != "present":
            return None
        return ref

    # ---- the table ---------------------------------------------------------
    def _load_rows(self) -> None:
        """Every stored fit on the scope's lines, at its line's zero as read
        when the dialog opened."""
        by_ref: dict[Ref, StoredFit] = {}
        for k in self._keys:
            for fit_id, fit in self.session.line_for_key(k).velocity_fits.items():
                ref = (k, fit_id)
                by_ref[ref] = self._at_zero.get(ref, fit)
        self._by_ref = by_ref
        # Store order breaks ties in t0: survey order, then each line's fits as saved.
        self._rank = {ref: i for i, ref in enumerate(by_ref)}
        self._flagged = disagreeing_fit_ids(by_ref)

    def _initial_ticks(self) -> set[Ref]:
        """The record's members that are still present and usable; with no
        record, every usable fit."""
        usable = {r for r in self._by_ref if r not in self._unusable}
        record = self._scope_velocity()[1]
        if record is None:
            return usable
        members = {
            (m.line_key, m.fit_id)
            for m in record.members
            if self.session.member_state(m, self.grid_id) == "present"
        }
        return usable & members

    def _canonical(self, ref: Ref) -> tuple[int, float, int]:
        """By line in survey order, then t0: the order the dialog opens in."""
        return (self._order[ref[0]], self._by_ref[ref].t0_ns, self._rank[ref])

    def _flags(self, ref: Ref, applied: Ref | None, model: VelocityModel | None) -> str:
        flags = []
        if ref in self._flagged:
            flags.append("disagrees with another fit")
        if ref in self._unusable:
            flags.append(unusable_fit_note(self._unusable[ref]))
        elif ref == applied and model is not None:
            note = applied_fit_note(model.surface_velocity, self._by_ref[ref].v_m_ns)
            if note:
                flags.append(note)
        return "; ".join(flags)

    def _sorted_refs(self, flags: Mapping[Ref, str]) -> list[Ref]:
        refs = sorted(self._by_ref, key=self._canonical)
        keys: dict[str, Callable[[Ref], Any]] = {
            "line": self._canonical,
            "t0": lambda r: self._by_ref[r].t0_ns,
            "v": lambda r: self._by_ref[r].v_m_ns,
            "rms": lambda r: self._by_ref[r].rms_ns,
            "points": lambda r: len(self._by_ref[r].points),
            "flag": lambda r: flags[r],
        }
        return sorted(refs, key=keys[self._sort_kind], reverse=self._sort_descending)

    def _fill_table(self, ticked: set[Ref]) -> None:
        """(Re)build the rows from `_by_ref`, in the current sort order."""
        applied, model = self._applied_ref(), self._scope_velocity()[0]
        flags = {ref: self._flags(ref, applied, model) for ref in self._by_ref}
        self._refs = self._sorted_refs(flags)
        # The current index too, not just the selection: removing the current
        # row otherwise selects its neighbour, arming Delete on a fit nobody
        # chose.
        self.table.selectionModel().clear()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._refs))
            for row, ref in enumerate(self._refs):
                fit = self._by_ref[ref]
                tick = QTableWidgetItem()
                if ref in self._unusable:
                    # An unusable fit's numbers belong to another time zero.
                    tick.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                else:
                    tick.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    tick.setCheckState(
                        Qt.CheckState.Checked if ref in ticked else Qt.CheckState.Unchecked
                    )
                self.table.setItem(row, _TICK_COLUMN, tick)
                cells = {
                    "t0": f"{fit.t0_ns:.1f}",
                    "v": f"{fit.v_m_ns:.4f} ± {fit.v_stderr_m_ns:.4f}",
                    "rms": f"{fit.rms_ns:.2f}",
                    "points": str(len(fit.points)),
                    "flag": flags[ref],
                }
                if "line" in self._column:
                    cells["line"] = self._line_text(ref[0])
                for kind, text in cells.items():
                    self.table.setItem(row, self._column[kind], QTableWidgetItem(text))
        finally:
            self.table.blockSignals(False)

    def _line_text(self, key: str) -> str:
        """The line's label, starred when it has its own velocity (§4)."""
        star = "*" if self.session.line_for_key(key).velocity is not None else ""
        return f"{self._labels[key]}{star}"

    def _show_sort_indicator(self) -> None:
        order = Qt.SortOrder.AscendingOrder
        if self._sort_descending:
            order = Qt.SortOrder.DescendingOrder
        self.table.horizontalHeader().setSortIndicator(self._column[self._sort_kind], order)

    def _usable_rows(self) -> list[int]:
        return [r for r, ref in enumerate(self._refs) if ref not in self._unusable]

    def _set_checks(self, wanted: Iterable[Ref] | None) -> None:
        """Tick exactly `wanted` among the usable rows (all of them for None)."""
        keep = None if wanted is None else set(wanted)
        self.table.blockSignals(True)
        try:
            for row in self._usable_rows():
                on = keep is None or self._refs[row] in keep
                self.table.item(row, _TICK_COLUMN).setCheckState(
                    Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
                )
        finally:
            self.table.blockSignals(False)

    # ---- the average -------------------------------------------------------
    def _refresh_average(self) -> None:
        """Recompute the average of the ticked fits and everything shown from it."""
        refs = sorted(self.ticked_refs(), key=self._canonical)
        usable = self._usable_rows()
        self._average = None
        meta = warning = ""
        if not self._refs:
            text = (
                "No fits on this grid's lines yet"
                if self.grid_id is not None
                else "No fits on this line yet"
            )
        elif not refs:
            text = "No fits ticked"
        else:
            fits = [self._by_ref[r] for r in refs]
            try:
                v, sigma = weighted_mean([(f.v_m_ns, f.v_stderr_m_ns) for f in fits])
            except ValueError as exc:
                text = self._cannot_weight(refs, exc)
            else:
                self._average = (v, sigma)
                text = f"{v:.4f} ± {sigma:.4f} m/ns"
                count = _plural(len(fits), "fit")
                if self.grid_id is not None:
                    count += f" on {_plural(len({r[0] for r in refs}), 'line')}"
                t0s = [f.t0_ns for f in fits]
                if len(fits) == 1:
                    meta = f"{count} · t0 {t0s[0]:.1f} ns"
                else:
                    meta = f"{count} · t0 from {min(t0s):.1f} to {max(t0s):.1f} ns"
            if disagreeing_fit_ids({r: self._by_ref[r] for r in refs}):
                warning = _DISAGREE_WARNING
        self._average_label.setText(text)
        self._meta_label.setText(meta)
        self._warning_label.setText(warning)
        self._warning_label.setVisible(bool(warning))
        self.use_average_button.setEnabled(self._average is not None)
        state = Qt.CheckState.Unchecked
        if usable and len(refs) == len(usable):
            state = Qt.CheckState.Checked
        elif refs:
            state = Qt.CheckState.PartiallyChecked
        self.all_check.setEnabled(bool(usable))
        self.all_check.blockSignals(True)
        self.all_check.setCheckState(state)
        self.all_check.blockSignals(False)

    def _who(self, ref: Ref, *, start: bool = False) -> str:
        """How a fit is named in a sentence (`start`: at its start): by its
        line too in a grid's dialog."""
        t0 = f"fit at {self._by_ref[ref].t0_ns:.1f} ns"
        if self.grid_id is not None:
            return f"{self._labels[ref[0]]}'s {t0}"
        return f"The {t0}" if start else f"the {t0}"

    def _cannot_weight(self, refs: list[Ref], exc: ValueError) -> str:
        for ref in refs:
            s = self._by_ref[ref].v_stderr_m_ns
            if not math.isfinite(s) or s <= 0:
                return f"{self._who(ref, start=True)} has σ {s}; it cannot be weighted."
        return f"These fits cannot be averaged: {exc}"

    def ticked_refs(self) -> list[Ref]:
        """The ticked rows' (line key, fit id), in table order."""
        refs = []
        for row, ref in enumerate(self._refs):
            item = self.table.item(row, _TICK_COLUMN)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                refs.append(ref)
        return refs

    def set_ticked(self, refs: Iterable[Ref]) -> None:
        """Tick exactly `refs`; an unusable fit is never ticked."""
        self._set_checks(refs)
        self._refresh_average()

    def intro_text(self) -> str:
        return self._intro_label.text()

    def average_text(self) -> str:
        return self._average_label.text()

    def average_meta_text(self) -> str:
        return self._meta_label.text()

    def average_warning_text(self) -> str:
        return self._warning_label.text()

    def source_note_text(self) -> str:
        return self._note_label.text()

    def starred_note_text(self) -> str:
        return self._starred_label.text()

    def _refresh_note(self) -> None:
        self._note_label.setText(self._note())
        self._note_label.setVisible(bool(self._note_label.text()))

    def _note(self) -> str:
        """Where the velocity came from, and what has changed since (§7.3)."""
        record = self._scope_velocity()[1]
        if record is None:
            return ""
        when = f" (applied {record.applied_at[:10]})" if record.applied_at else ""
        if record.method == METHOD_WEIGHTED_MEAN:
            lines = [f"This velocity is the average of {len(record.members)} fits{when}."]
        else:
            m = record.members[0]
            lines = [f"This velocity is {m.line_label}'s fit at {m.t0_ns:.1f} ns{when}."]
        for m in record.members:
            who = f"{m.line_label}'s fit at {m.t0_ns:.1f} ns"
            state = self.session.member_state(m, self.grid_id)
            if state != "present":
                lines.append(f"{who}: {state}")
                continue
            ref = (m.line_key, m.fit_id)
            if ref in self._unusable:
                lines.append(f"{who}: cannot be measured at the current time zero")
                continue
            fit = self._by_ref.get(ref)
            if fit is not None and round(fit.v_m_ns, 4) != round(m.v_m_ns, 4):
                lines.append(f"{who} now gives {fit.v_m_ns:.4f} (time zero changed)")
        return "\n".join(lines)

    def _refresh_starred(self) -> None:
        self._starred_label.setText(self._starred())
        self._starred_label.setVisible(bool(self._starred_label.text()))

    def _starred(self) -> str:
        """In a grid's dialog, the grid's lines with a velocity of their own:
        the grid's Apply never reaches them (spec §4, my call: every such line
        on the grid, with fits or not)."""
        if self.grid_id is None:
            return ""
        own = []
        for k in self._keys:
            velocity = self.session.line_for_key(k).velocity
            if velocity is not None:
                own.append((self._labels[k], velocity.surface_velocity))
        if not own:
            return ""
        if len(own) == 1:
            label, v = own[0]
            return f"* {label} has its own velocity ({v:.4f}). Apply doesn't change it."
        named = [f"{label} ({v:.4f})" for label, v in own]
        return (
            f"* {', '.join(named[:-1])} and {named[-1]} have their own velocities. "
            "Apply doesn't change them."
        )

    # ---- reading the dialog ------------------------------------------------
    def row_ref(self, row: int) -> Ref:
        return self._refs[row]

    def fit_id_at_row(self, row: int) -> str:
        return self._refs[row][1]

    def flagged_refs(self) -> frozenset[Ref]:
        return self._flagged

    def flagged_fit_ids(self) -> frozenset[str]:
        return frozenset(ref[1] for ref in self._flagged)

    def flag_text(self, row: int) -> str:
        item = self.table.item(row, self._column["flag"])
        return item.text() if item is not None else ""

    def highlighted_ref(self) -> Ref | None:
        """The row selected in the table, whatever the spin box now says."""
        return self._selected

    def highlighted_fit_id(self) -> str | None:
        return None if self._selected is None else self._selected[1]

    def selected_fit_id(self) -> str | None:
        """The selected fit, unless the spin box has since been moved off its
        velocity -- then the number is the user's own."""
        ref = self._selected
        if ref is None or self._cleared or ref in self._unusable:
            # An unusable fit's numbers belong to another time zero: never applied.
            return None
        if round(self.spin.value(), 4) != round(self._by_ref[ref].v_m_ns, 4):
            return None
        return ref[1]

    def _record(self, refs: Iterable[Ref]) -> VelocitySource:
        """The record of `refs`, with each fit's numbers as this dialog shows them."""
        fits = [(key, fit_id, self._by_ref[(key, fit_id)]) for key, fit_id in refs]
        return fit_record(self.session, fits, applied_at=applied_now())

    def _outcome(self) -> tuple[VelocityModel | None, VelocitySource | None]:
        """The model to apply and its record, by §7.2: the record follows the
        last thing that filled the box, and only while the box holds that value."""
        if self._cleared:
            return None, None
        box = round(self.spin.value(), 4)
        if (
            self._fill_kind == "average"
            and box == round(self._fill_value, 4)
            and set(self.ticked_refs()) == set(self._fill_refs)
            and all(r in self._by_ref for r in self._fill_refs)
        ):
            source = self._record(self._fill_refs)
            # Unrounded: the box shows 4 dp of it.
            return VelocityModel.constant(source.v_m_ns), source
        if self._fill_kind == "pick":
            # The pick is remembered with its ref, so selecting another row
            # (an unusable one, say) does not forget what the box holds.
            ref = self._fill_refs[0]
            fit = self._by_ref.get(ref)
            if fit is not None and ref not in self._unusable and box == round(fit.v_m_ns, 4):
                source = self._record([ref])
                # The fit's own velocity, not the spin box's 4-dp rounding of it.
                return VelocityModel.constant(source.v_m_ns), source
        current, record = self._scope_velocity()
        if current is not None and box == round(current.surface_velocity, 4):
            # The velocity in force, untouched: kept to the last digit, with
            # its record as it was.
            return current, record
        return VelocityModel.constant(self.spin.value()), None

    def velocity(self) -> VelocityModel | None:
        return self._outcome()[0]

    def chosen_source(self) -> VelocitySource | None:
        """The record to store with `velocity()`, or None for a typed number."""
        return self._outcome()[1]

    # ---- driving the dialog --------------------------------------------------
    def select_fit(self, fit_id: str) -> None:
        """Select a fit of the line, in a line's dialog, as a click on its
        row's numbers would."""
        self.select_row(self._refs.index((self.key, fit_id)))  # type: ignore[arg-type]

    def select_row(self, row: int) -> None:
        """Select a row as a click on its numbers would: from a column that
        is not the tick (`selectRow` makes the first column current)."""
        self.table.setCurrentCell(row, _TICK_COLUMN + 1)

    def _select_quietly(self, ref: Ref) -> None:
        """Select a row for the highlight and the curve only: the box is not
        filled, and what last filled it is kept."""
        self._quiet_select = True
        try:
            self.table.selectRow(self._refs.index(ref))
        finally:
            self._quiet_select = False

    def _select_applied_fit(self) -> bool:
        """Select the fit behind the velocity, if there is one, for the
        highlight and the curve. The box is not filled: it stays on the
        velocity in force, so an untouched Apply changes nothing (§7.2 rule 1,
        §7.3). Adopting a re-measured number takes a click on the row."""
        ref = self._applied_ref()
        if ref is None:
            return False
        self._select_quietly(ref)
        return True

    def _on_selection_changed(self) -> None:
        try:
            rows = self.table.selectionModel().selectedRows()
            self.delete_button.setEnabled(bool(rows))
            self._selected = self._refs[rows[0].row()] if rows else None
            self.fit_highlighted.emit(self._selected)
            # A row selected from its tick cell (a click beside the box) is
            # being ticked, not picked: Qt makes the clicked cell current
            # before it selects the row.
            if not self._quiet_select and self.table.currentColumn() != _TICK_COLUMN:
                self._pick(self._selected)
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _pick(self, ref: Ref | None) -> None:
        """Put a usable fit's velocity in the box and remember it as the fill.
        Anything else leaves the box, and what filled it, alone."""
        if ref is None or ref in self._unusable:
            return
        self.spin.setValue(self._by_ref[ref].v_m_ns)
        self._fill_kind = "pick"
        self._fill_refs = (ref,)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """A click on a row always picks it, even when it is already selected
        (which fires no selection change): the way to adopt a re-measured
        number. The tick column is for ticking, not picking."""
        try:
            if column != _TICK_COLUMN:
                self._pick(self._refs[row])
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _on_header_clicked(self, section: int) -> None:
        """Sort by the clicked column; a second click reverses it. Ticks and
        the selection stay with their fits, and the box is left alone."""
        try:
            kind = self._kinds[section]
            if kind == "tick":
                # Qt has already moved the indicator to the clicked section.
                self._show_sort_indicator()
                return
            if kind == self._sort_kind:
                self._sort_descending = not self._sort_descending
            else:
                self._sort_kind, self._sort_descending = kind, False
            ticked = set(self.ticked_refs())
            selected = self._selected
            self._fill_table(ticked)
            self._show_sort_indicator()
            if selected is not None:
                self._select_quietly(selected)
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        try:
            if item.column() == _TICK_COLUMN:
                self._refresh_average()
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _on_all_changed(self, *_: object) -> None:
        try:
            state = self.all_check.checkState()
            if state == Qt.CheckState.PartiallyChecked:
                return  # only ever set from the table, never asked for
            self._set_checks(None if state == Qt.CheckState.Checked else ())
            self._refresh_average()
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _on_use_average(self) -> None:
        try:
            if self._average is None:
                return
            self._fill_kind = "average"
            # In survey order, whatever the table is sorted by: the record's
            # members read the same however the rows were shown.
            self._fill_refs = tuple(sorted(self.ticked_refs(), key=self._canonical))
            self._fill_value = self._average[0]
            self.spin.setValue(self._average[0])
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _validate(self, *_: object) -> None:
        try:
            # Zero is the "required" placeholder, and not a velocity.
            self.apply_button.setEnabled(self.spin.value() > 0)
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _on_clear(self) -> None:
        try:
            self._cleared = True
            self.accept()
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _memberships(self, ref: Ref) -> list[str]:
        """A sentence for each remembered velocity this fit is a member of:
        its line's own, and any grid's (spec §4.4)."""
        key, fit_id = ref
        line = self.session.line_for_key(key)
        stored = line.velocity_fits[fit_id]
        line_whose = "the line's" if self.grid_id is None else f"{self._labels[key]}'s"
        records = [(line_whose, line.velocity_source)]
        site = self.session.site
        for grid in site.grids if site is not None else []:
            whose = "this grid's" if grid.id == self.grid_id else f"grid {grid.id}'s"
            records.append((whose, grid.velocity_source))
        sentences = []
        for whose, record in records:
            if record is None:
                continue
            if not any(m.line_key == key and m.names(fit_id, stored) for m in record.members):
                continue
            if record.method == METHOD_WEIGHTED_MEAN:
                sentences.append(
                    f"This fit is part of {whose} velocity, the average of "
                    f"{len(record.members)} fits."
                )
            else:
                sentences.append(f"This fit set {whose} velocity.")
        return sentences

    def _on_delete(self) -> None:
        try:
            ref = self._selected
            if ref is None:
                return
            key, fit_id = ref
            fit = self._by_ref[ref]
            text = f"Delete {self._who(ref)} ({fit.v_m_ns:.4f} ± {fit.v_stderr_m_ns:.4f} m/ns)?"
            sentences = self._memberships(ref)
            if sentences:
                stays = (
                    "The velocity stays as it is until you apply another."
                    if len(sentences) == 1
                    else "These velocities stay as they are until you apply others."
                )
                text += "\n\n" + " ".join([*sentences, stays])
            answer = QMessageBox.question(self, "Delete fit", text)
            if answer != QMessageBox.StandardButton.Yes:
                return
            ticked = {r for r in self.ticked_refs() if r != ref}
            self.session.remove_velocity_fit(key, fit_id)
            self._at_zero.pop(ref, None)
            self._unusable.pop(ref, None)
            self._fill_kind = "none"
            self._load_rows()
            self._fill_table(ticked)
            self._refresh_average()
            self._refresh_note()
            # Back to how the dialog opened: the fit behind the velocity
            # selected, and the velocity in force in the box. Selecting the
            # deleted fit copied its number there, and it is gone.
            self._select_applied_fit()
            self.spin.setValue(self._velocity_in_force())
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)
