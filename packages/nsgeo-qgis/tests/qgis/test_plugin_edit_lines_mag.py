"""Edit lines on a magnetometer grid: a row per traverse, Scale and Destagger only (M19a)."""

from __future__ import annotations

import pytest
from nsgeo.mag import MagFile, MagSetup
from nsgeo_qgis.line_edit import CHANGED_ELSEWHERE, REMOVED, traverse_key, traverse_row
from nsgeo_qgis.ui.edit_lines_dialog import (
    COL_DESTAGGER,
    COL_DIR,
    COL_GRID,
    COL_LABEL,
    COL_LENGTH,
    COL_OFFSET,
    COL_SCALE,
    COL_START,
    COL_TRACES,
    MAG_DESTAGGER_TIP,
    EditLinesDialog,
)
from plugin_testing import synthetic_grad601
from qgis.PyQt.QtCore import Qt


@pytest.fixture
def dialog(mag_site):
    session, root = mag_site
    dlg = EditLinesDialog(session, "M1")
    yield session, root, dlg
    dlg.deleteLater()


def _cell(dlg, row, col):
    return dlg.table.item(row, col)


def _type(dlg, row, col, text):
    _cell(dlg, row, col).setText(text)


def test_traverse_keys_round_trip():
    assert traverse_key("raw/mag/m1.dat", 0) == "raw/mag/m1.dat#1"
    assert traverse_row(traverse_key("a#b.dat", 7)) == 7
    for bad in ("m1.dat", "m1.dat#", "m1.dat#x", "m1.dat#0", "#3"):
        with pytest.raises(ValueError):
            traverse_row(bad)


def test_a_mag_grid_lists_its_traverses(dialog):
    session, root, dlg = dialog
    assert dlg.windowTitle() == "Edit lines · M1 · magnetometer"
    assert dlg.table.rowCount() == 8
    for r in range(8):
        assert _cell(dlg, r, COL_LABEL).text() == f"traverse {r + 1}"
        assert _cell(dlg, r, COL_TRACES).text() == "32"
        assert _cell(dlg, r, COL_LENGTH).text() == "4.00"
        assert _cell(dlg, r, COL_GRID).text() == "M1"
        assert not _cell(dlg, r, COL_GRID).flags() & Qt.ItemFlag.ItemIsEditable
    assert dlg.destagger_spin.toolTip() == MAG_DESTAGGER_TIP
    assert MAG_DESTAGGER_TIP.endswith(
        "On a magnetometer grid each traverse moves along the way it was walked, "
        "so outbound and return traverses move opposite ways."
    )


def test_only_scale_and_destagger_can_be_edited_on_mag(dialog):
    session, root, dlg = dialog
    for w in (
        dlg.start_spin,
        dlg.set_start_button,
        dlg.snap_button,
        dlg.offset_spin,
        dlg.shift_button,
        dlg.flip_button,
        dlg.grid_combo,
        dlg.move_button,
        dlg.up_button,
        dlg.down_button,
        dlg.fit_button,
        dlg.measure_button,
    ):
        assert w.isHidden(), w
    assert not dlg.scale_spin.isHidden() and not dlg.destagger_spin.isHidden()
    before = [dlg.edit_for(k) for k in dlg._order]
    for col, text in ((COL_OFFSET, "9"), (COL_START, "1"), (COL_DIR, "-1"), (COL_LABEL, "x")):
        assert not _cell(dlg, 0, col).flags() & Qt.ItemFlag.ItemIsEditable
        _type(dlg, 0, col, text)
    assert [dlg.edit_for(k) for k in dlg._order] == before
    session.save()
    dlg.accept()
    assert not session.dirty


def test_a_typed_destagger_and_scale_reach_the_file(dialog):
    session, root, dlg = dialog
    session.save()
    changes = []
    session.mag_changed.connect(lambda: changes.append(1))
    dlg.select_keys(dlg.keys()[:2])
    dlg.destagger_spin.setValue(0.25)
    dlg.set_destagger_button.click()
    _type(dlg, 2, COL_SCALE, "0.98")
    dlg.accept()
    mag = session.mag_file_on("M1")
    assert mag.shifts == (0.25, 0.25, 0, 0, 0, 0, 0, 0)
    assert mag.scales[2] == 0.98
    assert changes == [1] and session.dirty
    assert len(dlg.outcome.changed) == 3 and not dlg.outcome.skipped


def test_ok_with_nothing_changed_writes_nothing(dialog):
    session, root, dlg = dialog
    session.save()
    before = session.mag_file_on("M1")
    dlg.accept()
    assert session.mag_file_on("M1") is before
    assert not session.dirty


def test_a_file_replaced_while_editing_skips_its_traverses(dialog):
    session, root, dlg = dialog
    other = synthetic_grad601(root / "raw" / "mag", "m1b.dat")
    new = MagFile.open(other, "M1", MagSetup())
    _type(dlg, 0, COL_DESTAGGER, "0.3")
    session.set_mag_file(new)
    dlg.accept()
    assert [s.reason for s in dlg.outcome.skipped] == [REMOVED]
    assert session.mag_file_on("M1") is new
    assert new.shifts == (0.0,) * 8


def test_a_traverse_changed_elsewhere_is_skipped(dialog):
    import dataclasses

    session, root, dlg = dialog
    _type(dlg, 0, COL_DESTAGGER, "0.3")
    mag = session.mag_file_on("M1")
    session.set_mag_file(dataclasses.replace(mag, shifts=(0.1,) + mag.shifts[1:]))
    dlg.accept()
    assert [s.reason for s in dlg.outcome.skipped] == [CHANGED_ELSEWHERE]
    assert session.mag_file_on("M1").shifts[0] == 0.1


def test_edit_traverses_refuses_an_unknown_grid(mag_site):
    session, root = mag_site
    with pytest.raises(KeyError):
        session.edit_traverses("nope", [])


def test_gpr_edit_lines_is_unchanged(mag_site):
    session, root = mag_site
    dlg = EditLinesDialog(session, "G1")
    assert dlg.windowTitle() == "Edit lines · G1"
    dlg.show()
    for w in (dlg.measure_button, dlg.fit_button, dlg.grid_combo, dlg.flip_button, dlg.move_button):
        assert not w.isHidden()
    assert dlg.table.cellWidget(0, COL_GRID) is not None
    dlg.deleteLater()
