"""The Qt-free arithmetic behind the Slices dock."""

from __future__ import annotations

import pytest
from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    FRAME_BUDGET_MS,
    STREAM_MS_PER_LINE,
    STREAM_MS_PER_TRACE,
    MemoryEstimate,
    Resolution,
    SourceChoice,
    choose_residency,
    estimate_memory,
    format_bytes,
    format_status,
    preset_transform_conflict,
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
    assert names == expected
    assert set(names) == {"amp_abs", "amp_square", "amp_envelope"}
    assert "gain_agc" not in names and "dewow" not in names


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
    est = estimate_memory(prepared_samples=10_000_000, n_cells=90_000, nz=230)
    assert est.lines_bytes == 10_000_000 * 4
    assert est.cube_bytes == 230 * 90_000 * 4 + 90_000 * 4
    assert est.total_bytes == est.lines_bytes + est.cube_bytes


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
    est = estimate_memory(sum(ln.n_traces * ln.header.n_samples for ln in lines), 120 * 120, 230)
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


def test_shift_scroll_steps_deeper_downward_and_is_inert_without_shift():
    """Spec 9.2: shift + scroll on the canvas cycles depth, which is the
    convention users of other packages already have. The direction is the
    one the world uses -- scrolling down goes deeper -- and the rule is a
    plain function so it is pinned without synthesising a Qt event, whose
    constructor signature differs between Qt 5 and Qt 6."""
    from nsgeo_qgis.slices_plan import depth_scroll_delta

    assert depth_scroll_delta(-120, shift_held=True) == 1  # down: deeper
    assert depth_scroll_delta(120, shift_held=True) == -1  # up: shallower
    assert depth_scroll_delta(-120, shift_held=False) == 0  # plain scroll is a map zoom
    assert depth_scroll_delta(0, shift_held=True) == 0  # a horizontal-only wheel


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


def test_the_fill_radius_follows_each_grids_own_line_spacing():
    """Spec 4.4: in site scope the radius is a multiple of each grid's own
    spacing, so a 0.5 m grid and a 1.0 m grid in one site each get
    M11's 1.5x. Rounded like the dock's `radius_cells` (round, not floor:
    3.6 cells is 4, which a floor would make 3), and never negative."""
    from nsgeo_qgis.slices_plan import radius_cells_for

    assert radius_cells_for(0.5, 1.5, 0.25) == 3
    assert radius_cells_for(1.0, 1.5, 0.25) == 6
    assert radius_cells_for(0.6, 1.5, 0.25) == 4  # 3.6 cells
    assert radius_cells_for(0.5, 0.0, 0.25) == 0
    assert radius_cells_for(0.5, -2.0, 0.25) == 0
    with pytest.raises(ValueError):
        radius_cells_for(0.5, 1.5, 0.0)


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
