"""The line velocity dialog: type a number, take one from a saved fit, or
average the fits ticked.

`velocity()` is the whole answer: a model to apply, or `None` for "remove the
override". `chosen_source()` is the record of where that number came from
(grid velocity spec §7.2): the record follows the last thing that filled the
box, and only while the box still holds that value. A typed number has no
source.

Deleting a fit is the one thing here that does not wait for Apply: Apply also
writes the spin box as the line's override, and opening the dialog only to
delete a bad fit must not set a velocity on the way.

Fits are listed by t0 (shallowest first). A pair whose velocities differ by
more than 2 * sqrt(s1^2 + s2^2) is flagged. That is a passive diagnostic, not a
refusal: it says the ground looks layered, which a later Dix conversion acts
on.
"""

from __future__ import annotations

import datetime as _dt
import math
import traceback
from collections.abc import Iterable, Mapping
from typing import TypeVar

from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit, applied_fit_note, fit_at_zero, unusable_fit_note
from nsgeo.velocity_source import METHOD_WEIGHTED_MEAN, SourceFit, VelocitySource, weighted_mean
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
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession

_HEADERS = ("", "t0 (ns)", "v ± σ (m/ns)", "rms (ns)", "points", "")
_TICK_COLUMN = 0
_FLAG_COLUMN = 5

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


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _AllBox(QCheckBox):
    """A tri-state box that a click only ever turns fully on or fully off."""

    def nextCheckState(self) -> None:  # noqa: N802 -- Qt's name
        if self.checkState() == Qt.CheckState.Checked:
            self.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.setCheckState(Qt.CheckState.Checked)


class VelocityDialog(QDialog):
    # The fit selected in the table, or None: lets the profile light its curve.
    fit_highlighted = pyqtSignal(object)

    def __init__(self, session: SiteSession, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.key = key
        self.setWindowTitle(f"Velocity · {key}")
        line = session.line_for_key(key)  # a stale key raises KeyError here, for the caller
        self._label = line.placement.label or line.path.stem
        self._by_ref: dict[Ref, StoredFit] = {}
        self._refs: list[Ref] = []
        self._flagged: frozenset[Ref] = frozenset()
        # Each fit at the line's zero as the dialog opened, and why any could
        # not be: read once, so a delete does not read the line again.
        self._at_zero, self._unusable = fits_at_line_zero(session, key)
        self._cleared = False
        self._selected: str | None = None
        self._quiet_select = False
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
        self.spin.setValue(session.resolved_velocity(key).surface_velocity)
        form.addRow("Velocity (m/ns)", self.spin)
        layout.addLayout(form)

        layout.addWidget(
            QLabel(
                "Saved hyperbola fits on this line. Tick fits to average them; "
                "pick one to use its velocity."
            )
        )
        self.all_check = _AllBox("All")
        self.all_check.setTristate(True)
        all_row = QHBoxLayout()
        all_row.addWidget(self.all_check)
        all_row.addStretch()
        layout.addLayout(all_row)
        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(list(_HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        delete_row = QHBoxLayout()
        self.delete_button = QPushButton("Delete fit")
        self.delete_button.setToolTip("Remove the selected fit from this line's record.")
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
        self.clear_button = QPushButton("Clear override")
        buttons.addButton(self.clear_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        self._fill_table(self._initial_ticks())
        self._refresh_average()
        self._refresh_note()

        self.spin.valueChanged.connect(self._validate)
        self._validate()
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.all_check.stateChanged.connect(self._on_all_changed)
        self.use_average_button.clicked.connect(self._on_use_average)
        self.clear_button.clicked.connect(self._on_clear)
        self.delete_button.clicked.connect(self._on_delete)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self._select_applied_fit()

    # ---- the table ---------------------------------------------------------
    def _initial_ticks(self) -> set[Ref]:
        """The record's members that are still present and usable; with no
        record, every usable fit."""
        line = self.session.line_for_key(self.key)
        usable = {(self.key, i) for i in line.velocity_fits if i not in self._unusable}
        record = line.velocity_source
        if record is None:
            return usable
        members = {
            (m.line_key, m.fit_id)
            for m in record.members
            if self.session.member_state(m) == "present"
        }
        return usable & members

    def _fill_table(self, ticked: set[Ref]) -> None:
        """(Re)build the rows from the line's stored fits, shallowest first."""
        line = self.session.line_for_key(self.key)
        stored = dict(line.velocity_fits)
        failed = self._unusable
        self._by_ref = {(self.key, i): self._at_zero.get(i, f) for i, f in stored.items()}
        self._refs = sorted(self._by_ref, key=lambda r: self._by_ref[r].t0_ns)
        self._flagged = disagreeing_fit_ids(self._by_ref)
        applied = line.velocity_from_fit
        # The current index too, not just the selection: removing the current
        # row otherwise selects its neighbour, arming Delete on a fit nobody
        # chose.
        self.table.selectionModel().clear()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._refs))
            for row, ref in enumerate(self._refs):
                fit_id = ref[1]
                fit = self._by_ref[ref]
                flags = []
                if ref in self._flagged:
                    flags.append("disagrees with another fit")
                if fit_id in failed:
                    flags.append(unusable_fit_note(failed[fit_id]))
                elif fit_id == applied and line.velocity is not None:
                    note = applied_fit_note(line.velocity.surface_velocity, fit.v_m_ns)
                    if note:
                        flags.append(note)
                tick = QTableWidgetItem()
                if fit_id in failed:
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
                cells = (
                    f"{fit.t0_ns:.1f}",
                    f"{fit.v_m_ns:.4f} ± {fit.v_stderr_m_ns:.4f}",
                    f"{fit.rms_ns:.2f}",
                    str(len(fit.points)),
                    "; ".join(flags),
                )
                for col, text in enumerate(cells, start=1):
                    self.table.setItem(row, col, QTableWidgetItem(text))
        finally:
            self.table.blockSignals(False)

    def _usable_rows(self) -> list[int]:
        return [r for r, ref in enumerate(self._refs) if ref[1] not in self._unusable]

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
        refs = self.ticked_refs()
        usable = self._usable_rows()
        self._average = None
        meta = warning = ""
        if not self._refs:
            text = "No fits on this line yet"
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
                noun = "fit" if len(fits) == 1 else "fits"
                t0s = [f.t0_ns for f in fits]
                if len(fits) == 1:
                    meta = f"1 fit · t0 {t0s[0]:.1f} ns"
                else:
                    meta = f"{len(fits)} {noun} · t0 from {min(t0s):.1f} to {max(t0s):.1f} ns"
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

    def _cannot_weight(self, refs: list[Ref], exc: ValueError) -> str:
        for ref in refs:
            fit = self._by_ref[ref]
            s = fit.v_stderr_m_ns
            if not math.isfinite(s) or s <= 0:
                return f"The fit at {fit.t0_ns:.1f} ns has σ {s}; it cannot be weighted."
        return f"These fits cannot be averaged: {exc}"

    def ticked_refs(self) -> list[Ref]:
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

    def average_text(self) -> str:
        return self._average_label.text()

    def average_meta_text(self) -> str:
        return self._meta_label.text()

    def average_warning_text(self) -> str:
        return self._warning_label.text()

    def source_note_text(self) -> str:
        return self._note_label.text()

    def _refresh_note(self) -> None:
        self._note_label.setText(self._note())
        self._note_label.setVisible(bool(self._note_label.text()))

    def _note(self) -> str:
        """Where the line's velocity came from, and what has changed since (§7.3)."""
        record = self.session.line_for_key(self.key).velocity_source
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
            state = self.session.member_state(m)
            if state != "present":
                lines.append(f"{who}: {state}")
                continue
            ref = (m.line_key, m.fit_id)
            if ref[1] in self._unusable:
                lines.append(f"{who}: cannot be measured at the current time zero")
                continue
            fit = self._by_ref.get(ref)
            if fit is not None and round(fit.v_m_ns, 4) != round(m.v_m_ns, 4):
                lines.append(f"{who} now gives {fit.v_m_ns:.4f} (time zero changed)")
        return "\n".join(lines)

    # ---- reading the dialog ------------------------------------------------
    def fit_id_at_row(self, row: int) -> str:
        return self._refs[row][1]

    def flagged_fit_ids(self) -> frozenset[str]:
        return frozenset(ref[1] for ref in self._flagged)

    def flag_text(self, row: int) -> str:
        item = self.table.item(row, _FLAG_COLUMN)
        return item.text() if item is not None else ""

    def highlighted_fit_id(self) -> str | None:
        """The fit selected in the table, whatever the spin box now says."""
        return self._selected

    def selected_fit_id(self) -> str | None:
        """The selected fit, unless the spin box has since been moved off its
        velocity -- then the number is the user's own."""
        fit_id = self._selected
        if fit_id is None or self._cleared or fit_id in self._unusable:
            # An unusable fit's numbers belong to another time zero: never applied.
            return None
        if round(self.spin.value(), 4) != round(self._by_ref[(self.key, fit_id)].v_m_ns, 4):
            return None
        return fit_id

    def _member(self, ref: Ref) -> SourceFit:
        return SourceFit.of(ref[0], ref[1], self._label, self._by_ref[ref])

    def _outcome(self) -> tuple[VelocityModel | None, VelocitySource | None]:
        """The model to apply and its record, by §7.2: the record follows the
        last thing that filled the box, and only while the box holds that value."""
        if self._cleared:
            return None, None
        box = round(self.spin.value(), 4)
        if (
            self._fill_kind == "average"
            and box == round(self._fill_value, 4)
            and tuple(self.ticked_refs()) == self._fill_refs
            and all(r in self._by_ref for r in self._fill_refs)
        ):
            source = VelocitySource.from_fits([self._member(r) for r in self._fill_refs], _now())
            # Unrounded: the box shows 4 dp of it.
            return VelocityModel.constant(source.v_m_ns), source
        if self._fill_kind == "pick":
            # The pick is remembered with its ref, so selecting another row
            # (an unusable one, say) does not forget what the box holds.
            ref = self._fill_refs[0]
            fit = self._by_ref.get(ref)
            if fit is not None and ref[1] not in self._unusable and box == round(fit.v_m_ns, 4):
                source = VelocitySource.from_fits([self._member(ref)], _now())
                # The fit's own velocity, not the spin box's 4-dp rounding of it.
                return VelocityModel.constant(source.v_m_ns), source
        line = self.session.line_for_key(self.key)
        current = line.velocity
        if current is not None and box == round(current.surface_velocity, 4):
            # The line's own override, untouched: kept to the last digit, with
            # its record as it was.
            return current, line.velocity_source
        return VelocityModel.constant(self.spin.value()), None

    def velocity(self) -> VelocityModel | None:
        return self._outcome()[0]

    def chosen_source(self) -> VelocitySource | None:
        """The record to store with `velocity()`, or None for a typed number."""
        return self._outcome()[1]

    # ---- driving the dialog --------------------------------------------------
    def select_fit(self, fit_id: str) -> None:
        self.table.selectRow(self._refs.index((self.key, fit_id)))

    def _select_applied_fit(self) -> bool:
        """Select the fit behind the line's velocity, if there is one, for the
        highlight and the curve. The box is not filled: it stays on the
        velocity in force, so an untouched Apply changes nothing (§7.2 rule 1,
        §7.3). Adopting a re-measured number takes a click on the row."""
        line = self.session.line_for_key(self.key)
        pointer = line.velocity_from_fit
        if pointer is None or (self.key, pointer) not in self._by_ref or line.velocity is None:
            return False
        self._quiet_select = True
        try:
            self.select_fit(pointer)
        finally:
            self._quiet_select = False
        return True

    def _on_selection_changed(self) -> None:
        try:
            rows = self.table.selectionModel().selectedRows()
            self.delete_button.setEnabled(bool(rows))
            self._selected = self._refs[rows[0].row()][1] if rows else None
            self.fit_highlighted.emit(self._selected)
            if not self._quiet_select:
                self._pick(self._selected)
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)

    def _pick(self, fit_id: str | None) -> None:
        """Put a usable fit's velocity in the box and remember it as the fill.
        Anything else leaves the box, and what filled it, alone."""
        if fit_id is None or fit_id in self._unusable:
            return
        ref = (self.key, fit_id)
        self.spin.setValue(self._by_ref[ref].v_m_ns)
        self._fill_kind = "pick"
        self._fill_refs = (ref,)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """A click on a row always picks it, even when it is already selected
        (which fires no selection change): the way to adopt a re-measured
        number. The tick column is for ticking, not picking."""
        try:
            if column != _TICK_COLUMN:
                self._pick(self._refs[row][1])
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
            self._fill_refs = tuple(self.ticked_refs())
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

    def _on_delete(self) -> None:
        try:
            fit_id = self._selected
            if fit_id is None:
                return
            ref = (self.key, fit_id)
            fit = self._by_ref[ref]
            text = (
                f"Delete the fit at {fit.t0_ns:.1f} ns "
                f"({fit.v_m_ns:.4f} ± {fit.v_stderr_m_ns:.4f} m/ns)?"
            )
            line = self.session.line_for_key(self.key)
            record = line.velocity_source
            stored = line.velocity_fits[fit_id]
            if record is not None and any(
                m.line_key == self.key and m.names(fit_id, stored) for m in record.members
            ):
                if record.method == METHOD_WEIGHTED_MEAN:
                    text += (
                        f"\n\nThis fit is part of the line's velocity, the average of "
                        f"{len(record.members)} fits. The velocity stays as it is "
                        "until you apply another."
                    )
                else:
                    text += (
                        "\n\nThis fit set the line's velocity. The velocity stays as it is "
                        "until you apply another."
                    )
            answer = QMessageBox.question(self, "Delete fit", text)
            if answer != QMessageBox.StandardButton.Yes:
                return
            ticked = {r for r in self.ticked_refs() if r != ref}
            self.session.remove_velocity_fit(self.key, fit_id)
            self._fill_kind = "none"
            self._fill_table(ticked)
            self._refresh_average()
            self._refresh_note()
            # Back to how the dialog opened: the fit behind the velocity
            # selected, and the velocity in force in the box. Selecting the
            # deleted fit copied its number there, and it is gone.
            self._select_applied_fit()
            self.spin.setValue(self.session.resolved_velocity(self.key).surface_velocity)
        except Exception:  # noqa: BLE001 -- a slot must not raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Critical)
