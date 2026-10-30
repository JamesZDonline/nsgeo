"""The Transform combo shows titles and hands out ids (#82).

The Slices dock (This grid) and the site panel (Whole site) both offer one.
What they store -- a cube recipe, the site view's remembered transform --
is the id, or "none", exactly as before titles existed.
"""

from __future__ import annotations

from nsgeo.processing import step_title
from nsgeo_qgis.slices_plan import transform_names
from nsgeo_qgis.ui.transform_combo import TransformCombo


def test_it_shows_titles_and_holds_the_ids(qgis_app):
    combo = TransformCombo()
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "None",
        "Absolute value",
        "Envelope",
        "Square of the amplitude",
    ]
    assert combo.values() == ["none", *transform_names()]
    assert combo.itemText(1) == step_title(combo.values()[1])


def test_it_starts_on_none(qgis_app):
    assert TransformCombo().value() == "none"


def test_set_value_selects_by_id_and_refuses_an_unknown_one(qgis_app):
    combo = TransformCombo()
    assert combo.set_value("amp_envelope") is True
    assert combo.value() == "amp_envelope"
    assert combo.currentText() == "Envelope"
    assert combo.set_value("does-not-exist") is False
    assert combo.value() == "amp_envelope"


def test_a_change_reports_the_id(qgis_app):
    combo = TransformCombo()
    seen: list[str] = []
    combo.value_changed.connect(seen.append)
    combo.setCurrentIndex(2)  # what a click does
    combo.set_value("none")
    assert seen == ["amp_envelope", "none"]
