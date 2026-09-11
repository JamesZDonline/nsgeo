from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import available_steps
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.processing_dock import ProcessingDock, dest_index
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import Qt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5)))
    session.add_lines(lines)
    key = session.keys()[0]
    session.set_profiles(key, lines[0].load())
    session.open_line(key)
    return session, dock, key


def test_add_menu_lists_the_registry_and_marks_required_steps(opened):
    _, dock, _ = opened
    texts = [a.text() for a in dock.add_menu.actions()]
    assert [t.split(" ")[0] for t in texts] == available_steps()
    assert any(t.startswith("bandpass") and "needs values" in t for t in texts)
    assert not any(t.startswith("dewow") and "needs values" in t for t in texts)


def test_add_remove_toggle_and_reorder(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    dock.add_step("background_mean")
    dock.add_step("gain_agc")
    assert [dock.list.item(i).text() for i in range(3)] == ["dewow", "background_mean", "gain_agc"]
    dock.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert session.stack_for(key).entries[1][1] is False
    dock.list.setCurrentRow(2)
    dock.move_selected(-1)
    assert [s.name for s, _ in session.stack_for(key).entries] == [
        "dewow",
        "gain_agc",
        "background_mean",
    ]
    assert dock.list.currentRow() == 1
    dock.remove_selected()
    assert [s.name for s, _ in session.stack_for(key).entries] == ["dewow", "background_mean"]


def test_required_steps_are_requested_not_built(opened):
    session, dock, key = opened
    asked = []
    dock.add_step_requested.connect(asked.append)
    dock.add_step("bandpass")
    assert asked == ["bandpass"] and len(session.stack_for(key)) == 0


def test_selection_emits_and_rebuild_keeps_it(opened):
    session, dock, key = opened
    got = []
    dock.step_selected.connect(got.append)
    dock.add_step("dewow")
    dock.add_step("gain_agc")
    dock.list.setCurrentRow(1)
    assert got[-1] == 1
    session.set_step_enabled(key, 0, False)  # triggers rebuild
    assert dock.list.currentRow() == 1


def test_dest_index_matches_qt_rows_moved_semantics():
    assert dest_index(start=0, row=3) == 2  # moved down past two rows
    assert dest_index(start=3, row=0) == 0  # moved up to the top
    assert dest_index(start=1, row=1) == 1


def test_apply_to_grid_copies_to_the_other_lines(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    changed = dock.apply_to_grid(confirm=False)
    assert len(changed) == 2
    for other in changed:
        assert session.stack_for(other).to_dicts() == session.stack_for(key).to_dicts()
    assert "2 line" in dock.status.text()


def test_switching_lines_shows_that_lines_stack(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    other = session.keys()[1]
    session.open_line(other)
    assert dock.list.count() == 0
    session.open_line(key)
    assert dock.list.count() == 1


def test_no_line_disables_the_controls(qgis_app):
    dock = ProcessingDock(SiteSession())
    assert not dock.add_button.isEnabled() and not dock.apply_button.isEnabled()


def test_apply_button_click_confirms_before_applying(opened, answer_modal):
    """`apply_button.clicked` carries a `bool checked` argument. Connecting
    it straight to `apply_to_grid` (whose only parameter is `confirm: bool
    = True`) would let Qt's own argument-trimming hand that `checked`
    value to `confirm` -- verified directly: a `clicked` signal wired to a
    one-bool-defaulted-parameter slot is invoked with `checked=False` --
    which would silently skip the confirmation prompt on every real click
    and overwrite every other line in the grid with no way to back out.
    Pins the wiring that avoids that: a real click must still ask, and
    declining must leave every other line's stack untouched.
    """
    from qgis.PyQt.QtWidgets import QMessageBox

    session, dock, key = opened
    dock.add_step("dewow")
    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.No)
    dock.apply_button.click()
    assert len(calls) == 1
    other = session.keys()[1]
    assert len(session.stack_for(other)) == 0
