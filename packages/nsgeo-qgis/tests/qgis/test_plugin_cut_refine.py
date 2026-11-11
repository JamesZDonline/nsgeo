"""Minimum curvature behind a kriging preview, solved near the cut (cut spec §4.7, §5)."""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from nsgeo.slices import (
    SliceWindow,
    finish_section,
    plan_section_curvature,
    section_crops,
    solve_section_level,
    window_times_ns,
)
from nsgeo.slices.section import curvature_margin_cells
from nsgeo_qgis import cut_sections as cut_sections_module
from nsgeo_qgis.cut_sections import (
    CUT_REDRAW_MS,
    CUT_SOLVE_REST_MS,
    CUT_THREAD_NAME_PREFIX,
    CutLevelJob,
)
from nsgeo_qgis.refine import Refiner
from plugin_testing import spin_until
from qgis.PyQt.QtCore import QCoreApplication
from test_plugin_cut_sections import H, shown, site  # noqa: F401 -- fixtures
from test_plugin_profile_cut import profile  # noqa: F401 -- fixture

KRIGING_TITLE = "nsgeo Profile · cut: Cut 1 · A · 4.0 m · Kriging preview · minimum curvature"


def _to_min_curvature(dock):
    dock.grid_finish.set_value(
        dataclasses.replace(dock.grid_finish.value(), method="min_curvature")
    )
    dock.refresh_slice()


@pytest.fixture
def ran(monkeypatch):
    """Every job the cut worker runs, on a short rest and with a pause per job."""
    monkeypatch.setattr(cut_sections_module, "CUT_SOLVE_REST_MS", 20)
    log = SimpleNamespace(levels=[], threads=[], running=0, pause=0.0)
    real = CutLevelJob.run

    def run(self, should_stop):
        log.running += 1
        try:
            log.levels.append(self.level)
            log.threads.append(threading.current_thread().name)
            time.sleep(log.pause)
            return real(self, should_stop)
        finally:
            log.running -= 1

    monkeypatch.setattr(CutLevelJob, "run", run)
    return log


@pytest.fixture
def working(profile, ran):  # noqa: F811
    """A profile on grid A in minimum curvature, with the cut opened."""
    pd, dock, session, sections = profile
    _to_min_curvature(dock)
    key = session.add_cut("A", H)
    session.open_line(key)
    return pd, dock, session, sections, key, ran


def _reference(section, rows=None):
    """Each level solved the long way, with the section's own source."""
    source = section.source
    engine = source.engine
    cube = engine.cube()
    frame = cube.frame
    cut_spacing = engine.session.grid(source.grid_id).default_spacing
    crops = section_crops(
        section.columns, frame, curvature_margin_cells(source.settings, frame.cell, cut_spacing)
    )
    plans = plan_section_curvature(
        cube.coverage() > 0, crops, frame.cell, source.settings.max_distance_m
    )
    return {
        k: solve_section_level(
            cube.level(k), section.columns, crops, plans, source.settings, frame.cell
        )
        for k in (range(cube.z.nz) if rows is None else rows)
    }


def _held(sections, key):
    """The cached section, read without asking for it (asking arms a solve)."""
    entry = sections._cache.get(key)
    return None if entry is None else entry.section


def _done(sections, key):
    got = _held(sections, key)
    return got is not None and not got.standing_in


def test_the_exact_values():
    assert (CUT_SOLVE_REST_MS, CUT_REDRAW_MS, CUT_THREAD_NAME_PREFIX) == (300, 250, "nsgeo-cut")


def test_the_working_cut_is_solved_after_a_rest_and_replaces_kriging(working):
    pd, dock, session, sections, key, ran = working
    first = sections.section(key, build_cube=True)
    nz = first.z.nz
    assert first.standing_in and first.solved == (0, nz)
    assert pd.windowTitle() == f"{KRIGING_TITLE} 0 of {nz} depths"
    assert spin_until(lambda: _done(sections, key))
    final = sections.section(key, build_cube=True)
    assert final.method == "min_curvature" and final.standing_in is False
    assert final.solved == (nz, nz)
    assert pd.windowTitle() == "nsgeo Profile · cut: Cut 1 · A · 4.0 m · Minimum curvature"
    want = _reference(final)
    for k in range(nz):
        np.testing.assert_array_equal(final.values[k], want[k])
    doc = json.loads(final.provenance_json)
    assert "standing_in_for" not in doc and doc["finish"]["method"] == "min_curvature"
    assert sorted(ran.levels) == list(range(nz))  # each depth once


def _first_level_for(working, window):
    pd, dock, session, sections, key, ran = working
    z = sections.section(key, build_cube=True).z
    dock.window_changed.emit(*window_times_ns(z, window(z)))
    assert spin_until(lambda: len(ran.levels) >= 6)
    return ran.levels


def test_depths_near_the_slice_band_are_solved_first(working):
    levels = _first_level_for(working, lambda z: SliceWindow(18, 23))
    assert levels[0] == 20  # the centre of a five-level band, not one shallow
    assert set(levels[:3]) == {20, 19, 21}


@pytest.mark.parametrize("k", [91, 182, 329])
def test_a_one_level_band_starts_on_its_own_level_where_floor_would_slip(working, monkeypatch, k):
    pd, dock, session, sections, key, ran = working
    z = sections.section(key, build_cube=True).z
    # A fine axis, where `floor((t - t0) / dz)` of a float time lands a level low.
    fine = dataclasses.replace(z, t0_ns=1.0, dz_ns=0.1, nz=400)
    lo, hi = window_times_ns(fine, SliceWindow(k, k + 1))
    sections._band = (lo, hi)
    assert sections._centre_level(fine) == k


def test_a_hover_preview_starts_no_solve(profile, ran):  # noqa: F811
    pd, dock, session, sections = profile
    _to_min_curvature(dock)
    key = session.add_cut("A", H)
    dock.engine.cube()
    session.set_preview(key, 3)
    assert pd.windowTitle() == (
        "nsgeo Profile · PREVIEW: cut: Cut 1 · A · 4.0 m · "
        "Kriging preview (minimum curvature when opened)"
    )
    QCoreApplication.processEvents()
    time.sleep(0.15)
    QCoreApplication.processEvents()
    assert ran.levels == [] and not sections._refiner.busy


def test_a_settings_change_discards_the_solve(working):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.02
    nz = sections.section(key, build_cube=True).z.nz
    assert spin_until(lambda: len(ran.levels) >= 4)
    old = sections.section(key, build_cube=True)
    base = dock.grid_finish.value()
    dock.grid_finish.set_value(dataclasses.replace(base, max_distance_spacings=2.0))
    dock.refresh_slice()
    ran.pause = 0.0
    assert spin_until(lambda: ran.running == 0)
    new = sections.section(key, build_cube=True)
    assert new is not old and new.standing_in and new.solved[0] <= 1
    started = len(ran.levels)
    # The new solve starts after the rest, and every row it lands is the new settings'.
    assert spin_until(lambda: _done(sections, key))
    assert len(ran.levels) > started
    final = sections.section(key, build_cube=True)
    assert final.source.settings.max_distance_m == pytest.approx(2.0 * 0.5)
    want = _reference(final)
    for k in range(nz):
        np.testing.assert_array_equal(final.values[k], want[k])


def test_a_pick_while_kriging_stands_in_records_kriging(site, monkeypatch):  # noqa: F811
    monkeypatch.setattr(cut_sections_module, "CUT_SOLVE_REST_MS", 60_000)  # never within the test
    plugin = site
    _to_min_curvature(plugin.slices_dock)
    key = plugin.session.add_cut("A", H)
    plugin.session.open_line(key)
    assert plugin.cut_sections.section(key, build_cube=True).standing_in
    plugin._on_pick_requested(key, 5, 12.5)
    row = list(plugin.layers.layers["picks"].getFeatures())[-1]
    doc = json.loads(row["stack_json"])
    assert doc["finish"]["method"] == "kriging" and doc["standing_in_for"] == "min_curvature"


def test_the_slices_own_refine_lands_while_a_cut_is_solving(working):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.05
    assert spin_until(lambda: len(ran.levels) >= 1)

    class Quick:
        def run(self, should_stop):
            pass

    landed: list = []
    dock.refiner.start([Quick()], landed.append, lambda m: None)
    assert spin_until(lambda: bool(landed), 5_000)
    assert sections._refiner.busy  # the cut's list is still going
    assert not _done(sections, key)


def test_the_cut_worker_thread_is_named_nsgeo_cut(working):
    pd, dock, session, sections, key, ran = working
    assert spin_until(lambda: len(ran.threads) >= 2)
    assert all(name.startswith("nsgeo-cut") for name in ran.threads)
    assert isinstance(sections._refiner, Refiner)


def test_deleting_the_working_cut_mid_solve_stops_the_worker(working, message_log, monkeypatch):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.03
    assert spin_until(lambda: len(ran.levels) >= 3)
    session.remove_cut(key)
    # The next cut must not arm a solve of its own while this is checked.
    monkeypatch.setattr(cut_sections_module, "CUT_SOLVE_REST_MS", 600_000)
    assert spin_until(lambda: ran.running == 0)
    count = len(ran.levels)
    other = session.add_cut("A", [(1.0, 2.0), (5.0, 2.0)])
    session.open_line(other)
    got = sections.section(other, build_cube=True)
    engine = got.source.engine
    kriging = finish_section(
        engine.cube(), engine.section_fills(got.source.finish)[1], got.columns, got.source.settings
    )
    np.testing.assert_array_equal(got.values, kriging)  # nothing of the deleted cut landed on it
    QCoreApplication.processEvents()
    time.sleep(0.1)
    QCoreApplication.processEvents()
    assert len(ran.levels) == count and not sections._refiner.busy
    np.testing.assert_array_equal(_held(sections, other).values, kriging)
    assert key not in sections._cache
    assert not [m for m in message_log if "failed" in m or "could not" in m]


def test_closing_the_site_mid_solve_stops_the_worker(working, message_log):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.03
    assert spin_until(lambda: len(ran.levels) >= 3)
    session.close_site()
    assert spin_until(lambda: ran.running == 0)
    count = len(ran.levels)
    QCoreApplication.processEvents()
    time.sleep(0.1)
    QCoreApplication.processEvents()
    assert len(ran.levels) == count and not sections._refiner.busy
    assert sections._cache == {}
    assert not [m for m in message_log if "failed" in m or "could not" in m]


def test_opening_another_item_cancels_the_solve(working):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.03
    assert spin_until(lambda: len(ran.levels) >= 3)
    line = session.keys()[0]
    session.set_profiles(line, session.line_for_key(line).load())
    session.open_line(line)
    assert spin_until(lambda: ran.running == 0)
    count = len(ran.levels)
    QCoreApplication.processEvents()
    time.sleep(0.1)
    QCoreApplication.processEvents()
    assert len(ran.levels) == count and not sections._refiner.busy
    left = _held(sections, key)
    assert left.standing_in and left.solved[0] < left.solved[1]
    # Opened again, it solves the depths still owed and finishes.
    ran.pause = 0.0
    session.open_line(key)
    assert spin_until(lambda: _done(sections, key))


def test_the_panel_dropping_the_cuts_engine_stops_the_solve(working):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.03
    assert spin_until(lambda: len(ran.levels) >= 3)
    dock.grid_combo.setCurrentText("B")  # the cut's grid is no longer shown
    dock.engine.wait_for_preparation(20_000)
    dock.flush_debounce()
    assert spin_until(lambda: ran.running == 0)
    count = len(ran.levels)
    QCoreApplication.processEvents()
    time.sleep(0.1)
    QCoreApplication.processEvents()
    assert len(ran.levels) == count and not sections._refiner.busy
    assert sections._working is None


def test_a_palette_change_after_the_solve_keeps_it(working):
    pd, dock, session, sections, key, ran = working
    assert spin_until(lambda: _done(sections, key))
    jobs = len(ran.levels)
    before = _held(sections, key)
    changed = []
    sections.section_changed.connect(changed.append)
    dock.palette_combo.setCurrentIndex(1 - dock.palette_combo.currentIndex())
    dock.refresh_slice()
    QCoreApplication.processEvents()
    time.sleep(0.1)
    QCoreApplication.processEvents()
    after = _held(sections, key)
    assert after is not before and not after.standing_in and after.method == "min_curvature"
    assert after.values is before.values
    assert after.source.palette == dock.palette_combo.currentText()
    assert changed.count(key) >= 1  # redrawn in the new colours
    assert len(ran.levels) == jobs  # and nothing solved again
    assert pd.windowTitle().endswith("Minimum curvature")


def test_a_rename_mid_solve_keeps_solving_and_shows_the_new_name(working):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.02
    assert spin_until(lambda: len(ran.levels) >= 3)
    session.rename_cut(key, "Ridge")
    ran.pause = 0.0
    assert pd.windowTitle().startswith("nsgeo Profile · cut: Ridge · A")
    assert spin_until(lambda: _done(sections, key))
    assert sorted(ran.levels) == list(range(len(ran.levels)))  # no depth solved twice
    assert json.loads(_held(sections, key).provenance_json)["cut_name"] == "Ridge"
    assert pd.windowTitle() == "nsgeo Profile · cut: Ridge · A · 4.0 m · Minimum curvature"


def test_a_mid_solve_title_counts_the_depths_solved(working):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.01
    nz = sections.section(key, build_cube=True).z.nz
    marker = "Kriging preview · minimum curvature "

    def counted():
        if marker not in pd.windowTitle():
            return False
        return int(pd.windowTitle().split(marker)[1].split(" ")[0]) > 0

    assert spin_until(counted)
    done, total = _held(sections, key).solved
    assert 0 < done < total == nz
    assert f"{marker}" in pd.windowTitle() and f" of {nz} depths" in pd.windowTitle()


def test_a_redraw_during_the_solve_keeps_the_zoom_the_cursor_and_the_selection(working):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.01
    view = pd.view

    def window():
        t = view.transform
        return (t.trace_lo, t.trace_hi, t.time_lo, t.time_hi)

    whole = window()
    view.zoom_at(2.0, 20.0, 20.0)
    view.set_cursor(7)
    view.set_selection(3, 9)
    zoomed = window()
    assert zoomed != whole  # the zoom took
    before = _held(sections, key).solved[0]
    redraws = []
    sections.section_changed.connect(redraws.append)
    assert spin_until(lambda: len(redraws) >= 2 and _held(sections, key).solved[0] > before + 2)
    assert window() == zoomed
    assert view._cursor == 7 and view._selection == (3, 9)


def test_a_cancelled_solve_leaves_the_true_count_for_the_reopened_cut(working):
    pd, dock, session, sections, key, ran = working
    ran.pause = 0.01
    assert spin_until(lambda: len(_entry(sections, key).levels) >= 3)
    line = session.keys()[0]
    session.set_profiles(line, session.line_for_key(line).load())
    session.open_line(line)
    assert spin_until(lambda: ran.running == 0)
    got = _held(sections, key)
    assert got.solved[0] == len(_entry(sections, key).levels) >= 3
    session.open_line(key)
    assert pd.windowTitle().endswith(f"minimum curvature {got.solved[0]} of {got.solved[1]} depths")


def _entry(sections, key):
    return sections._cache[key]
