"""The Processing preset box both import dialogs share (#129), and its helpers.

`PresetBox` is a combo and a grey note under it, told only which grid it is
for. Every slot guards its own body (an exception in a slot never reaches the
emitter) and logs through `_log`. The dialogs are modeless, so the site can
close or change under the box: it then shows None and no presets.
"""

from __future__ import annotations

import traceback
from collections.abc import Sequence
from typing import Any

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget

MIGRATION_STEP = "migrate_fk"
MIGRATION_TITLE = "Migration (Stolt f-k)"


def migration_note(dicts: Sequence[dict[str, Any]], *, saved: bool) -> str | None:
    """The sentence for a preset or stack with an enabled Migration step, or None.

    Reads the first enabled `migrate_fk` entry's velocity. `saved` says the
    velocity is one the step was saved with, not one a line will resolve to.
    """
    for entry in dicts:
        if entry.get("step") == MIGRATION_STEP and entry.get("enabled", True):
            v = float(entry["params"]["velocity_m_ns"])
            tail = ", the velocity it was saved with" if saved else ""
            return f"Its {MIGRATION_TITLE} step uses {v:.3f} m/ns{tail}."
    return None


NO_PRESETS_TOOLTIP = "Save a preset from the Processing panel first."
SLICES_NOTE = "{grid}'s first lines: this becomes its Slices preset too."
DELETED_NOTE = "The preset {name} was deleted; these lines will import with none."
NONE_LABEL = "None"
PRESET_GONE = "the preset {name} no longer exists; nothing was imported"


def _log() -> None:
    QgsMessageLog.logMessage(traceback.format_exc(), "nsgeo", Qgis.MessageLevel.Warning)


class PresetBox(QWidget):
    """The preset an import applies to its new lines: None, or a saved preset."""

    def __init__(self, session: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._grid_id: str | None = None
        self._refilling = 0
        self._deleted: str | None = None
        self.combo = QComboBox()
        self.note = QLabel("")
        self.note.setEnabled(False)  # the palette's dimmed text
        self.note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)
        layout.addWidget(self.note)
        self.combo.currentIndexChanged.connect(self._on_choice)
        session.presets_changed.connect(self._on_presets_changed)
        session.site_closed.connect(self._on_presets_changed)
        session.slice_sources_changed.connect(self._on_sources_changed)
        self.set_grid(None)

    # ---- public ----------------------------------------------------------
    def set_grid(self, grid_id: str | None) -> None:
        """Move to the grid's starting value (the site's last, else None)."""
        self._grid_id = grid_id
        self._deleted = None
        try:
            start = self.session.import_preset(grid_id)
        except Exception:  # noqa: BLE001 -- a closed site: start on None
            start = None
        self._fill(start)
        self._refresh_note()

    def chosen(self) -> str | None:
        return self.combo.currentData() if self.combo.isEnabled() else None

    def is_choice(self) -> bool:
        """False while the box is greyed out (no presets saved): not a choice."""
        return self.combo.isEnabled()

    # ---- internals -------------------------------------------------------
    def _names(self) -> list[str]:
        try:
            return list(self.session.preset_names())
        except Exception:  # noqa: BLE001 -- the site closed under the box
            return []

    def _fill(self, keep: str | None) -> None:
        names = self._names()
        self._refilling += 1
        try:
            self.combo.clear()
            self.combo.addItem(NONE_LABEL, None)
            for name in names:
                self.combo.addItem(name, name)
            index = self.combo.findData(keep) if keep is not None else 0
            self.combo.setCurrentIndex(max(index, 0))
            self.combo.setEnabled(bool(names))
            self.combo.setToolTip("" if names else NO_PRESETS_TOOLTIP)
        finally:
            self._refilling -= 1

    def _on_presets_changed(self, *_: Any) -> None:
        try:
            before = self.chosen()
            self._fill(before)
            if before is not None and self.chosen() is None:
                self._deleted = before
            self._refresh_note()
        except Exception:  # noqa: BLE001
            _log()

    def _on_choice(self, *_: Any) -> None:
        try:
            if self._refilling:
                return
            self._deleted = None
            self._refresh_note()
        except Exception:  # noqa: BLE001
            _log()

    def _on_sources_changed(self, *_: Any) -> None:
        try:
            self._refresh_note()
        except Exception:  # noqa: BLE001
            _log()

    def _refresh_note(self) -> None:
        lines: list[str] = []
        name = self.chosen()
        if self._deleted is not None:
            lines.append(DELETED_NOTE.format(name=self._deleted))
        if name is not None:
            try:
                dicts = self.session.site.presets.get(name, [])
            except Exception:  # noqa: BLE001
                dicts = []
            migration = migration_note(dicts, saved=True)
            if migration:
                lines.append(migration)
            if self._grid_id is not None and self._sets_slices(self._grid_id):
                lines.append(SLICES_NOTE.format(grid=self._grid_id))
        self.note.setText("\n".join(lines))

    def _sets_slices(self, grid_id: str) -> bool:
        try:
            return bool(self.session.import_sets_slice_preset(grid_id))
        except Exception:  # noqa: BLE001 -- a grid that is gone, a closed site
            return False
