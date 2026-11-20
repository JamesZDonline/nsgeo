"""The Processing preset box both import dialogs share (#129)."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.preset_box import (
    DELETED_NOTE,
    NO_PRESETS_TOOLTIP,
    SLICES_NOTE,
    PresetBox,
    migration_note,
)
from plugin_testing import synthetic_dzt

GRID = Grid("Grid3", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    s.add_lines([Line.open(p, GridPlacement("Grid3", "y", 0.0, 0.0, 1, p.stem))])
    return s


def _save(session, name, *steps):
    """Save a preset made of `steps` (kind, params) from the grid's one line."""
    key = session.keys()[0]
    for kind, params in steps:
        session.append_step(key, build_step(kind, **params))
    session.save_preset(name, key)
    for _ in steps:
        session.remove_step(key, 0)


def test_the_list_is_none_then_the_presets_by_name(session):
    _save(session, "B preset", ("dewow", {}))
    _save(session, "A preset", ("dewow", {}))
    box = PresetBox(session)
    names = [box.combo.itemText(i) for i in range(box.combo.count())]
    assert names == ["None", "A preset", "B preset"]
    assert box.chosen() is None


def test_with_no_presets_the_box_is_greyed_on_none_with_its_tooltip(session):
    box = PresetBox(session)
    assert not box.combo.isEnabled()
    assert (
        box.combo.toolTip()
        == NO_PRESETS_TOOLTIP
        == "Save a preset from the Processing panel first."
    )
    assert box.chosen() is None
    assert not box.is_choice()


def test_the_note_shows_the_migration_line_only_for_a_migration_preset(session):
    _save(session, "Migrate", ("migrate_fk", {"velocity_m_ns": 0.1}))
    _save(session, "Plain", ("dewow", {}))
    box = PresetBox(session)
    box.combo.setCurrentIndex(box.combo.findData("Migrate"))
    assert migration_note(session.site.presets["Migrate"], saved=True) in box.note.text()
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    assert "Migration" not in box.note.text()
    box.combo.setCurrentIndex(0)
    assert box.note.text() == ""


def test_the_note_is_ordinary_text_not_dimmed(session):
    """Walkthrough A3: the dimmed grey note was easy to miss."""
    box = PresetBox(session)
    assert box.note.isEnabled()
    assert box.note.styleSheet() == ""


def test_the_note_shows_the_slices_line_only_when_the_rule_holds(session):
    _save(session, "Plain", ("dewow", {}))
    session.add_grid(Grid("Empty", (900.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5))
    box = PresetBox(session)
    box.set_grid("Empty")
    assert SLICES_NOTE.format(grid="Empty") not in box.note.text()  # None
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    assert box.note.text() == "Empty's first lines: this becomes its Slices preset too."
    box.set_grid(None)
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    assert "Slices" not in box.note.text()
    box.set_grid("Empty")
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    session.set_slice_preset("Empty", "Plain")
    assert "Slices" not in box.note.text()
    box.set_grid("Grid3")  # has lines
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    assert "Slices" not in box.note.text()


def test_a_deleted_choice_drops_to_none_and_says_so(session):
    _save(session, "Plain", ("dewow", {}))
    _save(session, "Other", ("dewow", {}))
    box = PresetBox(session)
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    session.delete_preset("Plain")
    assert box.chosen() is None
    assert box.note.text() == DELETED_NOTE.format(name="Plain")
    assert box.note.text() == "The preset Plain was deleted; these lines will import with none."
    box.combo.setCurrentIndex(box.combo.findData("Other"))
    assert "deleted" not in box.note.text()


def test_a_saved_preset_appears_and_the_choice_is_kept(session):
    _save(session, "Plain", ("dewow", {}))
    box = PresetBox(session)
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    _save(session, "Another", ("dewow", {}))
    assert box.combo.findData("Another") >= 0
    assert box.chosen() == "Plain"


def test_the_box_survives_the_site_closing_under_it(session):
    _save(session, "Plain", ("dewow", {}))
    box = PresetBox(session)
    box.set_grid("Grid3")
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    session.close_site()
    assert box.chosen() is None
    box.set_grid("Grid3")
    assert box.chosen() is None


def test_closing_the_site_greys_the_box_without_a_deleted_note(session):
    _save(session, "Plain", ("dewow", {}))
    box = PresetBox(session)
    box.combo.setCurrentIndex(box.combo.findData("Plain"))
    session.close_site()
    assert box.chosen() is None
    assert not box.is_choice()
    assert "deleted" not in box.note.text()


def test_opening_a_site_refills_the_box_and_moves_to_the_starting_value(session, tmp_path):
    _save(session, "Plain", ("dewow", {}))
    session.remember_import_preset("Grid3", "Plain")
    session.save()
    path = session.json_path
    box = PresetBox(session)
    box.set_grid("Grid3")
    session.close_site()
    assert not box.is_choice()
    session.open_site(path)
    assert box.is_choice()
    assert box.chosen() == "Plain"
    assert "deleted" not in box.note.text()
