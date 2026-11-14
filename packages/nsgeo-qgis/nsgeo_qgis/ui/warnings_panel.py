"""The Slices dock's Warnings section: what stands in the way, in full.

A refusal, a warning or a note stays here for as long as it is true, in
words that wrap rather than elide, so it never widens the dock. A toast is
for what just happened; this is for what is still so.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from qgis.PyQt.QtWidgets import QGroupBox, QLabel, QSizePolicy, QVBoxLayout

REFUSAL = "refusal"
WARNING = "warning"
NOTE = "note"

ICONS = {REFUSAL: "⛔", WARNING: "⚠", NOTE: "ⓘ"}
_ORDER = (REFUSAL, WARNING, NOTE)


@dataclass(frozen=True)
class Entry:
    kind: str
    text: str


class WarningsPanel(QGroupBox):
    """One word-wrapped label per entry; hidden when there are none."""

    def __init__(self, parent=None) -> None:
        super().__init__("Warnings", parent)
        self._layout = QVBoxLayout(self)
        self._entries: tuple[Entry, ...] = ()
        self._labels: list[QLabel] = []
        self.setVisible(False)

    def set_entries(self, entries: Iterable[Entry]) -> None:
        shown = [e for e in entries if e.text]
        ordered = tuple(e for kind in _ORDER for e in shown if e.kind == kind)
        if ordered == self._entries:
            return
        self._entries = ordered
        while len(self._labels) > len(ordered):
            label = self._labels.pop()
            self._layout.removeWidget(label)
            label.setParent(None)
            label.deleteLater()
        for i, entry in enumerate(ordered):
            if i == len(self._labels):
                label = QLabel()
                label.setWordWrap(True)
                # Ignored width: a long text wraps, it never raises the
                # dock's minimum width.
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
                self._layout.addWidget(label)
                self._labels.append(label)
            self._labels[i].setText(f"{ICONS[entry.kind]} {entry.text}")
        self.setVisible(bool(ordered))

    def entries(self) -> tuple[Entry, ...]:
        return self._entries
