"""The Qt-free arithmetic behind the Slices dock."""

from __future__ import annotations

import math
import tracemalloc

import numpy as np
import pytest
from nsgeo.slices import METHODS, plan_fill
from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    FRAME_BUDGET_MS,
    METHOD_LABELS,
    STREAM_MS_PER_LINE,
    STREAM_MS_PER_TRACE,
    WEIGHT_BYTES_PER_CELL,
    MemoryEstimate,
    Resolution,
    SliceFinish,
    SourceChoice,
    choose_residency,
    estimate_memory,
    format_bytes,
    format_status,
    name_list,
    preset_transform_conflict,
    preview_note,
    site_export_refusal,
    transform_names,
)
from plugin_testing import REAL_DZT, needs_real_data


def test_transform_names_come_from_the_registry_not_a_hardcoded_list():
    """Adding an amplitude transform to the core registry must offer it
    here with no edit. The mutant is a literal list, which passes a
    membership assertion and silently omits anything added later."""
    from nsgeo.processing import available_steps, get_step

    names = transform_names()
    expected = [n for n in available_steps() if getattr(get_step(n), "unipolar", False)]
    assert sorted(names) == expected
    assert set(names) == {"amp_abs", "amp_square", "amp_envelope"}
    assert "gain_agc" not in names and "dewow" not in names


def test_transform_names_follow_the_registrys_menu_order_not_the_ids(monkeypatch):
    """The Transform combo lists them as the core orders its Amplitude group
    (#82), so a transform added later lands where its `order` puts it. A
    double whose id sorts first but whose order is last tells the two apart."""
    from nsgeo.processing import base

    class _Late:
        name = "aaa_test_transform"
        title = "Late"
        group = "Amplitude"
        order = 99
        unipolar = True

    monkeypatch.setitem(base._REGISTRY, _Late.name, _Late)
    assert transform_names() == ["amp_abs", "amp_envelope", "amp_square", "aaa_test_transform"]


def test_a_preset_carrying_an_amplitude_transform_is_a_conflict():
    """Ruling 2: the transform is appended by the engine and is never part
    of a preset, so that the transform is always the LAST enabled step and
    StepStack.output_unipolar is exact. A preset that already holds one
    breaks that, and the failure it produces -- unipolar data on a bipolar
    table -- is the one spec 8 exists to prevent."""
    assert preset_transform_conflict([{"step": "dewow", "params": {}}]) is None
    assert preset_transform_conflict([]) is None
    assert (
        preset_transform_conflict(
            [{"step": "time_zero"}, {"step": "amp_abs"}, {"step": "gain_agc"}]
        )
        == "amp_abs"
    )
    # Found wherever it sits, not only last -- gain-after-transform is
    # precisely the ordering that makes output_unipolar report False.
    assert preset_transform_conflict([{"step": "amp_envelope"}]) == "amp_envelope"
    # A disabled transform still conflicts: enabling it later would break
    # the invariant with no further warning.
    assert preset_transform_conflict([{"step": "amp_square", "enabled": False}]) == "amp_square"
    # An unknown step name is not this function's business to reject.
    assert preset_transform_conflict([{"step": "not_a_step"}]) is None


def test_memory_estimate_counts_the_lines_and_the_cube_separately():
    """Spec 7.4's inversion: by 120 lines the cached LINES cost more than
    the cube. A policy that only attacks the cube does nothing for a large
    site, so the two are reported apart."""
    est = estimate_memory(prepared_samples=10_000_000, n_cells=90_000, nz=230, n_covered=18_000)
    assert est.lines_bytes == 10_000_000 * 4
    assert est.cube_bytes == 230 * 18_000 * 4 + 18_000 * 4 + 18_000 * 8
    assert est.weights_bytes == 90_000 * WEIGHT_BYTES_PER_CELL
    assert est.total_bytes == est.lines_bytes + est.cube_bytes + est.weights_bytes


#: The lines spec 7.4 was measured on: the ten real files, 606-666 traces.
REAL_TRACES_PER_LINE = 630


def test_streaming_stays_the_default_while_nobody_could_perceive_the_difference():
    """Spec 9.2: a resident cube redraws in 0.56 ms against streaming's
    3.6 ms and nobody can perceive that. Holding the cube below the frame
    budget buys nothing and costs memory, so it is not done even when
    there is room."""
    small = MemoryEstimate(lines_bytes=28_000_000, cube_bytes=83_000_000)
    n_traces = 24 * REAL_TRACES_PER_LINE  # spec 7.4's 24 lines
    assert choose_residency(small, n_traces, budget_bytes=DEFAULT_BUDGET_BYTES) == "streaming"
    assert n_traces * STREAM_MS_PER_TRACE < FRAME_BUDGET_MS  # why


def test_a_large_site_is_promoted_to_a_resident_cube_when_it_fits():
    est = MemoryEstimate(lines_bytes=140_000_000, cube_bytes=83_000_000)
    n_traces = 200 * REAL_TRACES_PER_LINE  # 200 lines: 28 ms per tick, past a 16 ms frame
    assert n_traces * STREAM_MS_PER_TRACE > FRAME_BUDGET_MS
    assert choose_residency(est, n_traces, budget_bytes=DEFAULT_BUDGET_BYTES) == "resident"


def test_a_large_site_that_does_not_fit_degrades_to_streaming_rather_than_failing():
    """Spec 7.4: an over-budget cube degrades to streaming instead of
    failing, and the source dialog warns rather than hard-caps."""
    est = MemoryEstimate(lines_bytes=140_000_000, cube_bytes=4_000_000_000)
    n_traces = 200 * REAL_TRACES_PER_LINE
    assert choose_residency(est, n_traces, budget_bytes=DEFAULT_BUDGET_BYTES) == "streaming"


def test_the_settings_override_wins_in_both_directions():
    small = MemoryEstimate(lines_bytes=1_000, cube_bytes=1_000)
    assert choose_residency(small, 2, DEFAULT_BUDGET_BYTES, always_resident=True) == "resident"
    huge = MemoryEstimate(lines_bytes=1, cube_bytes=10**12)
    # The user asked for it and spec 7.4 never hard-caps; the dock warns.
    assert choose_residency(huge, 2, DEFAULT_BUDGET_BYTES, always_resident=True) == "resident"


def test_streaming_is_costed_per_trace_so_long_lines_go_resident():
    """Ruling T3-c (M12). Streaming bins every trace of every line in the
    window, so its cost goes with traces, not lines: M12's site benchmark
    streamed 100 lines of 3000 traces in about 44 ms a tick, three frames,
    while a per-line estimate (100 x 0.14 = 14 ms) called that
    imperceptible. The same line count at the real files' length still
    streams, and the rule itself -- frame budget, memory budget -- is
    M11's."""
    fits = MemoryEstimate(lines_bytes=120_000_000, cube_bytes=15_000_000)
    assert pytest.approx(STREAM_MS_PER_LINE / REAL_TRACES_PER_LINE) == STREAM_MS_PER_TRACE
    assert choose_residency(fits, 100 * 3000) == "resident"
    assert choose_residency(fits, 100 * 670) == "streaming"
    assert choose_residency(MemoryEstimate(1, 2 * DEFAULT_BUDGET_BYTES), 100 * 3000) == "streaming"


@needs_real_data
def test_the_ten_real_lines_still_stream():
    """Real data: what M11's own ten lines choose under the per-trace
    estimate -- streaming, as before, at well under a frame."""
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line

    lines = [Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem)) for p in REAL_DZT[:10]]
    n_traces = sum(line.n_traces for line in lines)
    assert 6000 < n_traces < 6700
    # n_covered is a deliberate upper bound: the trace-count branch of
    # choose_residency answers before it reads the estimate.
    est = estimate_memory(
        sum(ln.n_traces * ln.header.n_samples for ln in lines), 120 * 120, 230, 120 * 120
    )
    assert choose_residency(est, n_traces) == "streaming"
    assert n_traces * STREAM_MS_PER_TRACE < 2.0


def test_format_bytes_reads_like_the_spec_status_line():
    assert format_bytes(28_000_000) == "28 MB"
    assert format_bytes(1_500_000_000) == "1.5 GB"
    assert format_bytes(900) == "1 MB"  # never "0 MB": a held line is not nothing


def test_the_status_line_says_what_is_held_and_how_fast_it_redraws():
    """Spec 9.2's wording, near-verbatim: memory, not time, is the binding
    constraint, and a constraint the user cannot see is one they cannot
    act on."""
    est = MemoryEstimate(lines_bytes=28_000_000, cube_bytes=83_000_000)
    streaming = format_status("streaming", n_lines=24, estimate=est, redraw_ms=3.6)
    assert streaming == "24 lines held in memory, 28 MB · slices redraw in 4 ms"
    resident = format_status("resident", n_lines=24, estimate=est, redraw_ms=0.56)
    assert "whole volume" in resident
    assert "111 MB" in resident  # lines AND cube, because both are held
    assert format_status("streaming", 1, est, 3.6).startswith("1 line held")  # not "1 lines"
    assert "redraw in —" in format_status("streaming", 24, est, redraw_ms=None)


def test_the_status_line_counts_the_interpolation_weights_as_held():
    """`total_bytes` counts the weights, so the readout does too: in both modes."""
    est = MemoryEstimate(lines_bytes=28_000_000, cube_bytes=83_000_000, weights_bytes=40_000_000)
    assert format_status("streaming", 24, est, 3.6) == (
        "24 lines held in memory, 68 MB · slices redraw in 4 ms"
    )
    assert "151 MB" in format_status("resident", 24, est, 0.56)


def test_the_value_objects_validate_themselves():
    with pytest.raises(ValueError):
        Resolution(cell=0.0, dz_ns=0.5, t0_ns=0.0, t1_ns=50.0)
    with pytest.raises(ValueError):
        Resolution(cell=0.1, dz_ns=-1.0, t0_ns=0.0, t1_ns=50.0)
    with pytest.raises(ValueError):
        Resolution(cell=0.1, dz_ns=0.5, t0_ns=50.0, t1_ns=0.0)
    ok = Resolution(cell=0.1, dz_ns=0.5, t0_ns=0.0, t1_ns=50.0)
    assert ok.cell == 0.1
    choice = SourceChoice(grid_id="A", preset="p", transform="amp_abs", line_keys=("a", "b"))
    assert choice.line_keys == ("a", "b")


def test_shift_scroll_steps_deeper_downward_one_step_per_notch():
    """Spec 9.2: shift + scroll on the canvas cycles depth, which is the
    convention users of other packages already have. The direction is the
    one the world uses -- scrolling down goes deeper -- and the rule is a
    plain function so it is pinned without synthesising a Qt event, whose
    constructor signature differs between Qt 5 and Qt 6."""
    from nsgeo_qgis.slices_plan import depth_scroll_steps

    assert depth_scroll_steps(0, -120) == (1, 0)  # down: deeper
    assert depth_scroll_steps(0, 120) == (-1, 0)  # up: shallower
    assert depth_scroll_steps(0, -240) == (2, 0)  # two notches Qt delivered as one event
    assert depth_scroll_steps(-60, 0) == (0, -60)  # a horizontal-only wheel changes nothing


def test_a_high_resolution_wheel_steps_once_per_notch_not_once_per_event():
    """#109: a high-resolution wheel (the user's Logitech M720 under libinput)
    reports one notch as several smaller events. Stepping once per event
    moved the depth two Steps per notch. Qt's `angleDelta` documentation
    says to add the deltas up until they reach 120, one notch."""
    from nsgeo_qgis.slices_plan import depth_scroll_steps

    assert depth_scroll_steps(0, -60) == (0, -60)  # half a notch: wait for the rest
    assert depth_scroll_steps(-60, -60) == (1, 0)

    pending, moved = 0, 0
    for _ in range(8):  # one notch in eighths
        steps, pending = depth_scroll_steps(pending, -15)
        moved += steps
    assert (moved, pending) == (1, 0)


def test_turning_the_wheel_back_drops_the_part_notch():
    """A part-notch left over from scrolling down must not swallow the first
    notch back up: the reversal takes effect on that notch."""
    from nsgeo_qgis.slices_plan import depth_scroll_steps

    assert depth_scroll_steps(-60, 120) == (-1, 0)
    assert depth_scroll_steps(60, -120) == (1, 0)


# ---- the cell-size floor (walkthrough round 2, W7: a crash) ---------------


def test_frame_cells_matches_cube_frame_for_grids_own_rounding():
    """`smallest_safe_cell` is only a safe bound if `frame_cells` counts
    what `CubeFrame.for_grid` actually builds -- which rounds UP, and
    floors at one cell, so a grid that is not a whole number of cells is
    covered rather than clipped. Pinned against sizes chosen to land both
    on and off an exact multiple."""
    from nsgeo.slices.frame import CubeFrame
    from nsgeo_qgis.slices_plan import frame_cells

    class _Grid:
        def __init__(self, sx, sy):
            self.origin, self.azimuth, self.crs = (0.0, 0.0), 0.0, "EPSG:32616"
            self.size_x, self.size_y = sx, sy

    for sx, sy in ((6.0, 12.0), (40.0, 40.0), (7.3, 11.9), (0.4, 0.4)):
        for cell in (0.5, 0.25, 0.1, 0.03):
            frame = CubeFrame.for_grid(_Grid(sx, sy), cell)
            assert frame_cells(sx, sy, cell) == frame.nx * frame.ny, (sx, sy, cell)


def test_smallest_safe_cell_is_the_finest_cell_that_still_fits():
    """Walkthrough round 2, W7: "cell size going to .001 ... crashes qgis
    because it is too fine a grid."

    `cell_spin` spans 0.01-5.0 m but kept Qt's default `singleStep` of
    1.0, so ONE press of the down-arrow from 0.5 m clamps straight to the
    0.01 m minimum. Cell count goes as 1/cell**2: on a 40 m grid that is a
    4000 x 4000 frame -- about a gigabyte for a single filled slice, and
    streaming does not help, because the per-slice array alone is the
    problem.

    Both halves pinned, because a bound that is merely safe is useless:
    the returned cell must FIT, and one spin step finer must NOT.
    """
    from nsgeo_qgis.slices_plan import MAX_FRAME_CELLS, frame_cells, smallest_safe_cell

    # 298.6 x 297.4 and 0.5 x 72.0 are not decoration: for both, the
    # closed-form estimate alone -- sqrt(sx * sy / max), rounded up to a
    # millimetre -- still lands OVER the cap (4,001,980 cells and
    # 4,008,000), because `ceil` is applied per AXIS and not to the
    # product. They are what makes the walk-up loop load-bearing rather
    # than decorative; without them a one-line implementation passes.
    for sx, sy in (
        (6.0, 12.0),
        (40.0, 40.0),
        (100.0, 100.0),
        (250.0, 80.0),
        (3.0, 3.0),
        (298.6, 297.4),
        (0.5, 72.0),
    ):
        cell = smallest_safe_cell(sx, sy)
        assert frame_cells(sx, sy, cell) <= MAX_FRAME_CELLS, (sx, sy, cell)
        # Tight: not a needlessly coarse bound that would take real
        # resolution away from a small grid.
        finer = round(cell - 0.001, 3)
        if finer > 0:
            assert frame_cells(sx, sy, finer) > MAX_FRAME_CELLS or cell <= 0.011, (sx, sy, cell)


def test_smallest_safe_cell_never_goes_below_the_spin_floor_on_a_small_grid():
    """A 6 x 12 m grid is affordable at any cell the spin can express, so
    the bound must not invent a coarser floor than the control already
    has -- it exists to stop a crash, not to take resolution away."""
    from nsgeo_qgis.slices_plan import smallest_safe_cell

    assert smallest_safe_cell(6.0, 12.0) <= 0.01


# ---- the site view (M12) --------------------------------------------------


def test_a_site_source_shares_one_transform_and_names_each_grid_once():
    """Spec 4.2: one transform combo for the site. A site slice is one
    layer with one renderer, so every grid must agree on polarity; and a
    grid listed twice would be prepared twice and drawn on top of itself."""
    from nsgeo_qgis.slices_plan import SiteSource

    a = SourceChoice(grid_id="A", preset="p", transform="amp_envelope", line_keys=("a1",))
    b = SourceChoice(grid_id="B", preset="q", transform="amp_envelope", line_keys=("b1",))
    source = SiteSource(transform="amp_envelope", grids=(a, b))
    assert source.grids == (a, b)
    assert SiteSource(transform="", grids=()).grids == ()  # an empty site is a site

    signed_b = SourceChoice(grid_id="B", preset="q", transform="", line_keys=("b1",))
    with pytest.raises(ValueError, match="'B'"):
        SiteSource(transform="amp_envelope", grids=(a, signed_b))
    again_a = SourceChoice(grid_id="A", preset="q", transform="amp_envelope", line_keys=("a2",))
    with pytest.raises(ValueError, match="'A'"):
        SiteSource(transform="amp_envelope", grids=(a, b, again_a))


def test_the_default_cell_is_0_2_m_no_larger_than_half_the_spacing():
    """#81: a fixed 0.2 m, not a fraction of the line spacing -- along a
    line the detail is set by the trace spacing, so a widely spaced grid
    keeps fine cells. Spec 4's "no larger than half the line spacing"
    still caps it, and the frame's affordable floor (`smallest_safe_cell`,
    walkthrough W7) still wins over both."""
    from nsgeo_qgis.slices_plan import default_cell

    assert default_cell(0.5, 0.01) == pytest.approx(0.2)
    assert default_cell(1.0, 0.01) == pytest.approx(0.2)  # not 0.4: fixed, not relative
    assert default_cell(0.25, 0.01) == pytest.approx(0.125)  # half the spacing
    assert default_cell(0.5, 0.3) == pytest.approx(0.3)  # the floor wins


def test_limit_windows_are_the_abutting_windows_and_the_thinner_tail():
    """Below the cap, `limit_windows` is exactly what
    `SliceEngine.shared_limit` measures over: `plan_windows(z, t, t)` plus
    a thinner final window when the thickness does not divide the axis --
    the levels a viewer reaches at the end of the slider (trap 4)."""
    from nsgeo.slices import SliceWindow, ZAxis
    from nsgeo_qgis.slices_plan import limit_windows

    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=23)
    assert limit_windows(z, 5) == (
        SliceWindow(0, 5),
        SliceWindow(5, 10),
        SliceWindow(10, 15),
        SliceWindow(15, 20),
        SliceWindow(20, 23),
    )
    whole = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=20)
    assert limit_windows(whole, 5)[-1] == SliceWindow(15, 20)  # no tail to add
    assert len(limit_windows(whole, 5)) == 4
    assert limit_windows(whole, 40) == (SliceWindow(0, 20),)  # thicker than the axis


def test_limit_windows_keep_at_most_twelve_evenly_spread_with_both_ends():
    """Ruling 4: a ten-grid site cannot afford a full stretch pass over
    every window on every change, and a display percentile does not need
    one. The subset is evenly spread and always holds the first window
    and the last -- the last being the thinner tail, whose levels on a
    real cube were the brightest (display.shared_limit's docstring)."""
    from nsgeo.slices import SliceWindow, ZAxis, plan_windows
    from nsgeo_qgis.slices_plan import SITE_LIMIT_WINDOWS, limit_windows

    assert SITE_LIMIT_WINDOWS == 12
    z = ZAxis(t0_ns=0.0, dz_ns=0.25, nz=181)
    every = list(plan_windows(z, 5, 5)) + [SliceWindow(180, 181)]
    assert len(every) == 37
    chosen = limit_windows(z, 5)
    assert len(chosen) == 12
    assert chosen[0] == every[0]
    assert chosen[-1] == SliceWindow(180, 181)
    index = [every.index(w) for w in chosen]
    assert index == sorted(set(index)), "repeated or out of order"
    gaps = {b - a for a, b in zip(index, index[1:])}
    assert gaps <= {3, 4}, f"not evenly spread: gaps {sorted(gaps)}"

    assert len(limit_windows(z, 5, max_windows=5)) == 5
    assert len(limit_windows(z, 60)) == 4  # three whole windows and the tail: under the cap
    with pytest.raises(ValueError):
        limit_windows(z, 5, max_windows=1)


def test_slice_finish_defaults():
    # Max distance 0.75 x spacing: the user's decision of 2026-11-03.
    assert SliceFinish() == SliceFinish("kriging", 0.75, 0.0, 0.0)


@pytest.mark.parametrize("spacing", [0.5, 0.7, 1.5])
def test_the_default_max_distance_is_three_quarters_of_a_spacing(spacing):
    assert SliceFinish().in_metres(spacing).max_distance_m == 0.75 * spacing


def _binned_rows(spacing, cell, size=10.0, skip=(), nx=40):
    """Lines along X from `spacing / 2`, each on the row of the cell its
    centre falls in, as binning places them; every column populated."""
    ny = int(math.ceil(size / cell))
    pop = np.zeros((ny, nx), bool)
    for i, y in enumerate(np.arange(spacing / 2, size - 1e-9, spacing)):
        if i not in skip:
            pop[int(y // cell)] = True
    return pop


@pytest.mark.parametrize("method", ["idw", "kriging", "min_curvature"])
@pytest.mark.parametrize(
    ("spacing", "cell"), [(0.5, 0.2), (0.75, 0.2), (0.7, 0.2), (0.5, 0.15), (1.5, 0.2)]
)
def test_the_default_finish_closes_every_gap_between_binned_lines(method, spacing, cell):
    """Binning moves a line up to half a cell, so its gaps are floor or
    ceil(spacing / cell) cells; 0.5 x spacing striped the even ones."""
    settings = SliceFinish(method=method).in_metres(spacing)
    pop = _binned_rows(spacing, cell)
    rows = np.flatnonzero(pop.any(axis=1))
    out = plan_fill(pop, cell, method, settings.max_distance_m, settings.search_radius_m).apply(
        np.where(pop, 1.0, np.nan)
    )
    assert np.isfinite(out[rows[0] : rows[-1] + 1]).all()


@pytest.mark.parametrize("method", ["idw", "kriging", "min_curvature"])
def test_the_default_finish_leaves_a_skipped_line_blank(method):
    settings = SliceFinish(method=method).in_metres(0.5)
    pop = _binned_rows(0.5, 0.2, skip=(10,))
    rows = np.flatnonzero(pop.any(axis=1))
    out = plan_fill(pop, 0.2, method, settings.max_distance_m, settings.search_radius_m).apply(
        np.where(pop, 1.0, np.nan)
    )
    assert np.isnan(out[rows[0] : rows[-1] + 1]).all(axis=1).any()


def test_in_metres_scales_by_the_spacing_and_sets_the_search_radius():
    got = SliceFinish().in_metres(0.5)
    assert got.max_distance_m == 0.375
    assert got.search_radius_m == 1.0
    wide = SliceFinish(max_distance_spacings=3.0).in_metres(0.5)
    assert wide.max_distance_m == 1.5
    assert wide.search_radius_m == 3.0


@pytest.mark.parametrize("spacing", [0.0, -0.5])
def test_in_metres_refuses_a_spacing_that_is_not_positive(spacing):
    with pytest.raises(ValueError):
        SliceFinish().in_metres(spacing)


@pytest.mark.parametrize("radius_spacings", [0.5, 1.5])
def test_updated_lays_known_fields_over_and_ignores_the_rest(radius_spacings):
    # 1.5 differs from the default max distance, so mapping the 0.2.0 radius onto it shows.
    got = SliceFinish().updated({"method": "idw", "radius_spacings": radius_spacings, "cell": 0.2})
    assert got == SliceFinish(method="idw")
    got = SliceFinish().updated(
        {"max_distance_spacings": 1.5, "smooth_x_m": 0.3, "smooth_y_m": 0.4}
    )
    assert got == SliceFinish("kriging", 1.5, 0.3, 0.4)


def test_updated_ignores_a_bad_method_or_number():
    base = SliceFinish("idw", 1.0, 0.1, 0.2)
    for bad in ("bogus", 3):
        assert base.updated({"method": bad}) == base
    for field in ("max_distance_spacings", "smooth_x_m", "smooth_y_m"):
        for bad in (-1.0, float("nan"), float("inf"), True):
            assert base.updated({field: bad}) == base, (field, bad)


def test_updated_accepts_an_int_as_a_number():
    assert SliceFinish().updated({"smooth_x_m": 1}).smooth_x_m == 1.0


@pytest.mark.parametrize("method", ["idw", "kriging", "min_curvature"])
def test_the_weights_estimate_covers_building_them(method, monkeypatch):
    """The over-budget warning counts `WEIGHT_BYTES_PER_CELL` before any weights
    exist (interpolation spec §7), so building them must not need much more:
    within half as much again. Measured on wandering 0.5 m lines over 50 m at
    0.05 m: 105-107 B a cell, against 466-561 B before `plan_fill` chunked its
    working set. Small chunks here, so their fixed few megabytes do not swamp a
    grid this size.

    Minimum curvature's plan is only about 95-100 B a cell (with its hierarchy), but its solve needs
    buffers of its own, so it is measured over the plan and one `apply`
    together (plan call 9): about 138 B a cell. IDW's and kriging's `apply` is
    a slice's transient, the 55 B a cell `MAX_FRAME_CELLS` already counts, so
    they are measured over building alone, as before."""
    from nsgeo.slices import interpolate

    monkeypatch.setattr(interpolate, "_PLAN_CHUNK", 1024, raising=False)
    monkeypatch.setattr(interpolate, "_SOLVE_CHUNK", 256)
    settings = SliceFinish(method=method).in_metres(0.5)
    pop = _binned_rows(0.5, 0.05, nx=200)
    # Varying data, so the solve really runs: constant data leave nothing to
    # solve (b = 0) and the CG buffers would never be allocated.
    yy, xx = np.indices(pop.shape)
    values = np.where(pop, np.sin(xx * 0.05) + np.cos(yy * 0.03), np.nan).astype(np.float32)
    out = None
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        before, _ = tracemalloc.get_traced_memory()
        fw = plan_fill(pop, 0.05, method, settings.max_distance_m, settings.search_radius_m)
        if method == "min_curvature":
            out = fw.apply(values)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if out is None:
        out = fw.apply(values)
    else:
        assert fw.solve(values)[1] > 0, "the measured solve must have iterated"
    assert (np.isfinite(out) & ~pop).sum() > 0.8 * pop.size
    assert (peak - before) / pop.size <= 1.5 * WEIGHT_BYTES_PER_CELL


def test_method_labels_follow_methods():
    """The Method combo lists every core method, in the core's order."""
    assert list(METHOD_LABELS) == list(METHODS)
    assert METHOD_LABELS["min_curvature"] == "Minimum curvature"


def test_the_estimate_counts_the_fill_weights():
    est = estimate_memory(0, 1000, 10, 100)
    assert est.weights_bytes == 1000 * WEIGHT_BYTES_PER_CELL
    assert est.total_bytes == est.lines_bytes + est.cube_bytes + est.weights_bytes


def test_name_list_reads_as_a_sentence():
    assert name_list(["A"]) == "A"
    assert name_list(["A", "B"]) == "A and B"
    assert name_list(["A", "B", "C"]) == "A, B and C"


def test_preview_note_is_exact_copy():
    base = (
        "Preview at 0.4 m pixels: the grids are at 0.05 m, but the site "
        "(1234 \u00d7 568 m) is too big to draw at full detail. "
        "It draws in full at a 0.12 m cell or coarser."
    )
    assert preview_note(0.4, 0.05, 1234.4, 567.6, 0.12, []) == base
    assert preview_note(0.4, 0.05, 1234.4, 567.6, 0.12, ["C", "D"]) == (
        base + " Leaving out C and D would also let it draw in full."
    )


def test_site_export_refusal_is_exact_copy():
    base = (
        "The site can't be exported at full detail yet: the site "
        "(1234 \u00d7 568 m) is too big at a 0.05 m cell. Choose a cell of 0.12 m or coarser"
    )
    assert site_export_refusal(0.05, 1234.4, 567.6, 0.12, []) == base + "."
    assert site_export_refusal(0.05, 1234.4, 567.6, 0.12, ["C"]) == base + ", or leave out C."


def test_the_estimate_matches_the_cube_it_describes():
    """The figure the checkbox shows is the cube's real size (#113)."""
    from nsgeo.slices import (
        CubeFrame,
        PreparedLine,
        Provenance,
        ZAxis,
        build_cube,
        covered_cells,
        plan_line,
    )

    rng = np.random.default_rng(0)
    lines = []
    for i in range(8):
        t = np.linspace(0.05, 9.9, 60)
        across = np.full(60, 0.25 + 0.5 * (i % 4))
        xy = [t, across] if i < 4 else [across, t]
        lines.append(
            PreparedLine(
                key=f"l{i}",
                data=(rng.random((30, 60)) + 0.5).astype(np.float32),
                dt_ns=1.0,
                t0_ns=0.0,
                coords=np.column_stack(xy),
            )
        )
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=0.5, nx=20, ny=20, crs="EPSG:32633")
    z = ZAxis(t0_ns=0.0, dz_ns=1.0, nz=24)
    prov = Provenance(
        line_keys=("a",),
        preset_name="p",
        steps=(),
        transform="amp_abs",
        velocity=None,
        built_utc="2026-11-10T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    cube = build_cube(lines, [plan_line(ln, frame, z) for ln in lines], frame, z, prov)
    n_covered = covered_cells(frame, (ln.coords for ln in lines))
    assert n_covered < frame.n_cells
    assert estimate_memory(0, frame.n_cells, z.nz, n_covered).cube_bytes == cube.nbytes


# ---- the export dialog's summary and the finest fit ------------------------


def _preview(**over):
    from nsgeo_qgis.slices_plan import ExportPreview

    base = dict(
        cell=0.025,
        pixel=0.0125,
        width_px=2582,
        height_px=3035,
        bands=18,
        bands_detail="every 2.5 ns from −1.8 to 45 ns, 5 ns thick",
        slices="kriging, max distance 0.75 × spacing, no smoothing",
        grids=("A", "B"),
        normalisation="edge match",
        file_bytes=600_000_000,
        held_bytes=1_000_000_000,
    )
    base.update(over)
    return ExportPreview(**base)


def test_the_summary_for_a_two_grid_site_is_exact():
    from nsgeo_qgis.slices_plan import summary_lines

    assert summary_lines(_preview()) == [
        ("Bands", "18, every 2.5 ns from −1.8 to 45 ns, 5 ns thick"),
        ("Picture", "2582 × 3035 pixels at 0.0125 m"),
        ("Grids", "2 included (A and B), rebuilt at 0.025 m"),
        ("Slices", "kriging, max distance 0.75 × spacing, no smoothing"),
        ("Normalisation", "edge match, measured again at 0.025 m"),
        ("File", "about 600 MB before compression, plus a style file"),
    ]


def test_the_summary_for_one_grid_drops_the_site_rows():
    from nsgeo_qgis.slices_plan import summary_lines

    rows = summary_lines(_preview(grids=None, normalisation=None))
    assert [k for k, _ in rows] == ["Bands", "Picture", "Slices", "File"]


def test_the_summary_for_a_big_site_counts_grids_without_naming_them():
    from nsgeo_qgis.slices_plan import summary_lines

    names = tuple(f"G{i}" for i in range(10))
    assert dict(summary_lines(_preview(grids=names)))["Grids"] == (
        "10 included, rebuilt at 0.025 m"
    )


def _counting(held):
    calls = []

    def held_at(cell, pixel):
        calls.append((cell, pixel))
        return held(cell, pixel)

    return held_at, calls


def test_finest_pixel_is_the_smallest_millimetre_that_fits():
    from nsgeo_qgis.slices_plan import finest_fits

    # Held falls as the pixel grows and fits from 15 mm up.
    held_at, calls = _counting(lambda c, p: 1_500_000_000 * 15 // round(p * 1000))
    _, pixel = finest_fits(held_at, 0.025, 0.0125, 1_500_000_000)
    assert pixel == 0.015
    assert len(calls) < 30


def test_finest_pixel_is_none_when_pixel_equals_cell_or_nothing_fits():
    from nsgeo_qgis.slices_plan import finest_fits

    assert finest_fits(lambda c, p: 10**12, 0.025, 0.025, 10**9)[1] is None
    assert finest_fits(lambda c, p: 10**12, 0.025, 0.0125, 10**9)[1] is None


def test_finest_cell_doubles_then_bisects_to_a_millimetre():
    from nsgeo_qgis.slices_plan import finest_fits

    # Held = k / cell^2 with pixel = cell; fits from a 0.037 m cell up.
    budget = 10**9
    k = budget * 0.037**2

    held_at, calls = _counting(lambda c, p: int(k / (c * c)) if p == c else 10**12)
    cell, _ = finest_fits(held_at, 0.025, 0.0125, budget)
    assert cell == pytest.approx(0.037)
    assert len(calls) < 30


def test_finest_cell_is_none_past_eight_times_the_current_cell():
    from nsgeo_qgis.slices_plan import finest_fits

    # Fits only from 0.25 m; 8 x 0.025 = 0.2.
    held_at, _ = _counting(lambda c, p: 0 if c >= 0.25 else 10**12)
    assert finest_fits(held_at, 0.025, 0.025, 10**9)[0] is None
    # ... and exactly at the reach it is found.
    held_at, _ = _counting(lambda c, p: 0 if c >= 0.2 - 1e-9 else 10**12)
    assert finest_fits(held_at, 0.025, 0.025, 10**9)[0] == pytest.approx(0.2)
