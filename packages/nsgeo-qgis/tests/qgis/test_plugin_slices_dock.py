"""The Slices dock's Source group."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_plan import transform_names
from nsgeo_qgis.ui.slices_dock import SlicesDock
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [{"step": "dewow", "params": {}, "enabled": True}]


@pytest.fixture
def docked(qgis_app, tmp_path):
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
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    dock = SlicesDock(session)
    yield dock, session
    dock.engine.dispose()
    dock.deleteLater()


def test_the_source_combos_are_filled_from_the_site_not_from_literals(docked):
    dock, session = docked
    assert [dock.grid_combo.itemText(i) for i in range(dock.grid_combo.count())] == ["A"]
    assert "p" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]
    offered = [dock.transform_combo.itemText(i) for i in range(dock.transform_combo.count())]
    assert offered[0] == "none"  # spec 6.2 and GPRSLICE's xfrm_method=NONE
    assert offered[1:] == transform_names()


def test_adding_a_preset_updates_the_combo_without_a_reopen(docked):
    dock, session = docked
    session.site.presets["second"] = list(PRESET)
    session.presets_changed.emit()
    assert "second" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]


def test_the_included_summary_reads_as_a_fraction_of_the_grid(docked):
    dock, session = docked
    assert dock.included_label.text().startswith("3 of 3 included")
    dock.set_included(tuple(session.keys())[:2])
    assert dock.included_label.text().startswith("2 of 3 included")


def test_the_dock_reports_the_memory_before_committing_to_preparing_it(docked):
    """Spec 9.1: before committing the ~0.9 s the dock reports what the
    resulting memory will be, because it is decided by the line count and
    the chosen resolution -- and spec 7.4 warns rather than hard-caps."""
    dock, _ = docked
    text = dock.included_label.text()
    assert "MB" in text or "GB" in text


def test_choosing_a_preset_that_carries_a_transform_is_refused_visibly(docked):
    """Ruling 2, surfaced. The engine raises; the dock must turn that into
    something the user can read and act on, not let it escape a slot."""
    dock, session = docked
    session.site.presets["bad"] = [{"step": "amp_abs", "params": {}, "enabled": True}]
    session.presets_changed.emit()
    seen: list[str] = []
    dock.error.connect(seen.append)
    dock.preset_combo.setCurrentText("bad")  # re-preparing is what refuses it
    assert any("amp_abs" in msg for msg in seen), seen
    assert "amp_abs" in dock.source_status.text()
    assert not dock.engine.is_prepared


def test_refilling_the_combos_does_not_re_prepare(docked):
    """Refilling a QComboBox emits currentTextChanged. Without the
    _updating guard the dock re-prepares on construction and on every
    grids_changed / lines_changed / presets_changed — ~0.9 s of work per
    unrelated session signal, which IS the "nothing runs automatically"
    the design forbids."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    prepared: list[int] = []
    dock.engine.on_prepared = lambda: prepared.append(1)
    session.site.presets["another"] = list(PRESET)
    session.presets_changed.emit()
    session.lines_changed.emit()
    assert dock.engine.wait_for_preparation(2_000)
    assert prepared == [], "refilling the combos must not have re-prepared"


def test_preparing_reports_progress_and_then_reports_prepared(docked):
    dock, session = docked
    dock.prepare()  # the dock prepares on construction too; this is the retry path
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.is_prepared
    assert dock.engine.line_count == 3
    assert "prepared" in dock.source_status.text().lower()


def test_changing_the_source_re_prepares_it_rather_than_waiting_to_be_asked(docked):
    """Spec 9.1, explicitly: changing the grid, preset or transform
    re-runs the preparation as a QgsTask. That is not a violation of
    "nothing runs automatically" -- the user chose a preset, and
    preparation is the execution of that choice, not an inference about
    it. A prepared source left standing after one of its three inputs
    changed would tell the user the screen matches a choice it does not."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 3

    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    dock.grid_combo.setCurrentText("B")  # no explicit prepare() call
    assert dock.engine.wait_for_preparation(20_000)
    # Grid B holds no lines, so the re-preparation really ran and really
    # used the new grid rather than leaving the old result in place.
    assert dock.engine.line_count == 0


def test_closing_the_site_empties_the_dock(docked):
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    session.close_site()
    assert dock.grid_combo.count() == 0
    assert not dock.engine.is_prepared
