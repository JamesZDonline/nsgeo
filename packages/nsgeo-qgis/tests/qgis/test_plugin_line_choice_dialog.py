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
