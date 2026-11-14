"""The Warnings section: one wrapped line per entry, refusals first."""

from __future__ import annotations

from nsgeo_qgis.ui.warnings_panel import NOTE, REFUSAL, WARNING, Entry, WarningsPanel
from qgis.PyQt.QtWidgets import QLabel


def test_entries_show_in_full_in_kind_order_and_the_panel_hides_when_empty(qgis_app):
    panel = WarningsPanel()
    panel.set_entries([Entry(NOTE, "n"), Entry(REFUSAL, "r"), Entry(WARNING, "w"), Entry(NOTE, "")])
    assert [e.kind for e in panel.entries()] == [REFUSAL, WARNING, NOTE]
    assert [lbl.text() for lbl in panel.findChildren(QLabel)] == [
        "\u26d4 r",
        "\u26a0 w",
        "\u24d8 n",
    ]
    assert all(lbl.wordWrap() for lbl in panel.findChildren(QLabel))
    assert not panel.isHidden()
    panel.set_entries([])
    assert panel.isHidden() and panel.entries() == ()


def test_each_entry_repeats_its_text_in_a_tooltip(qgis_app):
    panel = WarningsPanel()
    long_token = "x" * 90
    panel.set_entries([Entry(WARNING, long_token), Entry(NOTE, "n")])
    assert [lbl.toolTip() for lbl in panel.findChildren(QLabel)] == [long_token, "n"]
    panel.set_entries([Entry(WARNING, "changed")])
    assert [lbl.toolTip() for lbl in panel.findChildren(QLabel)] == ["changed"]
