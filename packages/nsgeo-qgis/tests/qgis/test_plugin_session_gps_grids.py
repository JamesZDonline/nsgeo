"""M17b (#134): GPS lines belong to grids, and a grid change never moves their track."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from nsgeo.geometry import Grid, GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.line_edit import CHANGED_ELSEWHERE, TrackEdit
from nsgeo_qgis.paraview_export import ParaViewExport
from nsgeo_qgis.session import SiteSession
from plugin_testing import (
    CRS,
    LAT0,
    LON0,
    M_PER_DEG,
    STEPS_ZERO,
    Dock,
    open_gps,
    synthetic_dzt,
    synthetic_gps_dzt,
)

GA = Grid("A", (0.0, 0.0), 0.0, 10.0, 15.0, CRS, 0.5)
GB = Grid("B", (50.0, 0.0), 0.0, 8.0, 9.0, CRS, 0.5)


class Spy:
    def __init__(self, signal):
        self.calls: list = []
        signal.connect(lambda *a: self.calls.append(a))


def _gps(folder, name, grid_id=None, lon=LON0):
    path = synthetic_gps_dzt(
        folder,
        name,
        [(t, LAT0 + t * 0.1 / M_PER_DEG, lon, 4) for t in (25, 175)],
        n_traces=200,
        traces_per_metre=10.0,
    )
    return open_gps(path, grid_id=grid_id)


def _tape(folder, name, grid_id="A"):
    p = synthetic_dzt(folder, name)
    return Line.open(p, GridPlacement(grid_id, "y", 0.0, 0.0, 1, p.stem))


@pytest.fixture
def site(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.set_site_crs(CRS)
    s.add_grid(GA)
    s.add_grid(GB)
    raw = tmp_path / "raw"
    s.add_lines(
        [
            _gps(raw, "FILE__001.DZT", "A", lon=LON0),
            _gps(raw, "FILE__002.DZT", None, lon=LON0 + 0.5 / M_PER_DEG),
            _tape(raw, "FILE__003.DZT"),
        ]
    )
    s.site.slice_sources["A"] = {"lines": ["raw/FILE__001.DZT", "raw/FILE__003.DZT"]}
    return s


IN_A, LOOSE, TAPE = "raw/FILE__001.DZT", "raw/FILE__002.DZT", "raw/FILE__003.DZT"


def _coords(s, key):
    return s.line_for_key(key).trace_coords(s.site.frames)


def test_move_lines_moves_a_gps_line_between_grids_and_never_its_track(site):
    s = site
    before = {k: _coords(s, k).tobytes() for k in (IN_A, LOOSE)}
    changed = Spy(s.lines_changed)
    s.save()
    outcome = s.move_lines([IN_A, LOOSE], "B")
    assert set(outcome.changed) == {IN_A, LOOSE}
    assert [s.line_for_key(k).placement.grid_id for k in (IN_A, LOOSE)] == ["B", "B"]
    assert {k: _coords(s, k).tobytes() for k in (IN_A, LOOSE)} == before
    assert len(changed.calls) == 1
    assert s.dirty
    assert IN_A not in s.site.slice_sources["A"]["lines"]


def test_a_mixed_move_moves_the_tape_line_and_the_gps_line_in_one_change(site):
    s = site
    changed = Spy(s.lines_changed)
    outcome = s.move_lines([TAPE, IN_A], "B")
    assert set(outcome.changed) == {TAPE, IN_A}
    assert s.keys_on_grid("B") == [IN_A, TAPE]
    assert len(changed.calls) == 1


def test_a_gps_line_moved_joins_the_end_of_the_survey_order(site):
    s = site
    s.move_lines([IN_A], "B")
    assert s.keys()[-1] == IN_A


def test_a_gps_line_already_on_the_grid_is_left_alone(site):
    s = site
    changed = Spy(s.lines_changed)
    assert s.move_lines([IN_A], "A").changed == ()
    assert changed.calls == []


def test_a_track_edit_after_the_destagger_changed_elsewhere_is_skipped_the_tape_edit_applies(site):
    from nsgeo_qgis.line_edit import LineEdit

    s = site
    seen = s.line_for_key(IN_A).placement
    tape_seen = s.line_for_key(TAPE).placement
    s.set_travel_shift([IN_A], 0.3)
    outcome = s.edit_lines(
        [
            TrackEdit(IN_A, seen, grid_id="B"),
            LineEdit(TAPE, tape_seen, grid_id="B"),
        ]
    )
    assert outcome.changed == (TAPE,)
    assert [(x.key, x.reason) for x in outcome.skipped] == [(IN_A, CHANGED_ELSEWHERE)]
    assert s.line_for_key(IN_A).placement.grid_id == "A"


def test_a_track_edit_into_a_grid_that_is_gone_is_skipped_and_named(site):
    s = site
    seen = s.line_for_key(IN_A).placement
    outcome = s.edit_lines([TrackEdit(IN_A, seen, grid_id="Z")])
    assert outcome.changed == ()
    assert "no longer exists" in outcome.skipped[0].reason


def test_a_removed_gps_line_is_skipped_as_removed(site):
    s = site
    seen = s.line_for_key(IN_A).placement
    s.remove_line(IN_A)
    outcome = s.edit_lines([TrackEdit(IN_A, seen, grid_id="B")])
    assert [x.key for x in outcome.skipped] == [IN_A]


def test_replace_grid_leaves_a_gps_lines_track_where_it_was(site):
    s = site
    before = _coords(s, IN_A).tobytes()
    s.replace_grid(dataclasses.replace(GA, origin=(40.0, 30.0), size_x=20.0, size_y=22.0))
    assert _coords(s, IN_A).tobytes() == before
    assert np.isfinite(_coords(s, IN_A)).all()


def test_remove_grid_with_lines_takes_its_gps_lines(site):
    s = site
    s.remove_grid("A", with_lines=True)
    assert IN_A not in s.keys()  # noqa: SIM118 -- SiteSession.keys(), not a dict
    assert LOOSE in s.keys()  # noqa: SIM118


def test_a_gps_line_in_a_grid_is_in_its_keys_on_grid_and_its_slice_source(site):
    s = site
    assert IN_A in s.keys_on_grid("A")
    assert LOOSE not in s.keys_on_grid("A")
    s.site.slice_sources.pop("A")
    s.site.presets["p"] = list(STEPS_ZERO)
    export = ParaViewExport(s, Dock(s))
    line_keys = export.source_choice("A", export.defaults("A")).line_keys
    assert IN_A in line_keys and TAPE in line_keys


def test_profiles_stay_in_distance_walked_so_a_gps_line_has_no_ruler(site):
    from nsgeo_qgis.ui.profile_dock import ProfileDock

    s = site
    dock = ProfileDock(s)
    gps = s.line_for_key(IN_A)
    assert dock._ruler_for(gps, gps.distance_along()) is None
    tape = s.line_for_key(TAPE)
    ruler = dock._ruler_for(tape, tape.distance_along())
    assert ruler is not None
    # The ruler is built over the tape lines only: moving the GPS line off the
    # grid does not change it.
    s.move_lines([IN_A], "B")
    assert dock._ruler_for(tape, tape.distance_along()) == ruler
    dock.deleteLater()


def test_a_gps_line_is_not_moved_into_a_grid_in_another_crs_and_the_reason_is_named(site):
    s = site
    other = "EPSG:32633"
    assert other != CRS
    s.add_grid(dataclasses.replace(GB, id="C", crs=other))
    before = s.line_for_key(IN_A).placement
    outcome = s.move_lines([IN_A], "C")
    assert outcome.changed == ()
    assert [(x.key, x.reason) for x in outcome.skipped] == [
        (IN_A, f"its new grid 'C' is in {other}, the line in {CRS}")
    ]
    assert s.line_for_key(IN_A).placement == before


def test_a_gps_lines_source_carries_its_walked_distance_and_gap_over(site):
    s = site
    s.set_profiles(IN_A, s.line_for_key(IN_A).load())
    s.set_profiles(TAPE, s.line_for_key(TAPE).load())
    line = s.line_for_key(IN_A)
    source = s.stack_for(IN_A).source
    np.testing.assert_array_equal(source.trace_x_m, line.distance_along())
    assert source.gap_m == line.placement.gap_m
    assert s.stack_for(TAPE).source.trace_x_m is None


def test_a_destagger_edit_reattaches_a_gps_lines_source(site):
    s = site
    s.set_profiles(IN_A, s.line_for_key(IN_A).load())
    s.set_profiles(TAPE, s.line_for_key(TAPE).load())
    before = s.stack_for(IN_A).source.trace_x_m.copy()
    tape_source = s.stack_for(TAPE).source
    spy = Spy(s.stack_changed)
    dirty_at_emit = []
    s.stack_changed.connect(lambda _k: dirty_at_emit.append(s.dirty))
    s.edit_lines([TrackEdit(IN_A, s.line_for_key(IN_A).placement, travel_shift=0.2)])
    assert dirty_at_emit == [True]
    after = s.stack_for(IN_A).source.trace_x_m
    np.testing.assert_allclose(after - before, 0.2)
    np.testing.assert_array_equal(after, s.line_for_key(IN_A).distance_along())
    assert spy.calls == [(IN_A,)]
    assert s.stack_for(TAPE).source is tape_source


def test_the_bulk_destagger_reattaches_a_gps_lines_source(site):
    s = site
    s.set_profiles(IN_A, s.line_for_key(IN_A).load())
    before = s.stack_for(IN_A).source.trace_x_m.copy()
    spy = Spy(s.stack_changed)
    dirty_at_emit = []
    s.stack_changed.connect(lambda _k: dirty_at_emit.append(s.dirty))
    s.set_travel_shift([IN_A], 0.2)
    after = s.stack_for(IN_A).source.trace_x_m
    np.testing.assert_allclose(after - before, 0.2)
    assert spy.calls == [(IN_A,)]
    assert dirty_at_emit == [True]
