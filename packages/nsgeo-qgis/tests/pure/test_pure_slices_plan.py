"""The Qt-free arithmetic behind the Slices dock."""

from __future__ import annotations

import pytest
from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    FRAME_BUDGET_MS,
    STREAM_MS_PER_LINE,
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


def test_streaming_stays_the_default_while_nobody_could_perceive_the_difference():
    """Spec 9.2: a resident cube redraws in 0.56 ms against streaming's
    3.6 ms and nobody can perceive that. Holding the cube below the frame
    budget buys nothing and costs memory, so it is not done even when
    there is room."""
    small = MemoryEstimate(lines_bytes=28_000_000, cube_bytes=83_000_000)
    assert choose_residency(small, n_lines=24, budget_bytes=DEFAULT_BUDGET_BYTES) == "streaming"
    assert 24 * STREAM_MS_PER_LINE < FRAME_BUDGET_MS  # why


def test_a_large_site_is_promoted_to_a_resident_cube_when_it_fits():
    est = MemoryEstimate(lines_bytes=140_000_000, cube_bytes=83_000_000)
    n_lines = 200  # 200 * 0.14 ms = 28 ms per tick, past a 16 ms frame
    assert n_lines * STREAM_MS_PER_LINE > FRAME_BUDGET_MS
    assert choose_residency(est, n_lines, budget_bytes=DEFAULT_BUDGET_BYTES) == "resident"


def test_a_large_site_that_does_not_fit_degrades_to_streaming_rather_than_failing():
    """Spec 7.4: an over-budget cube degrades to streaming instead of
    failing, and the source dialog warns rather than hard-caps."""
    est = MemoryEstimate(lines_bytes=140_000_000, cube_bytes=4_000_000_000)
    assert choose_residency(est, n_lines=200, budget_bytes=DEFAULT_BUDGET_BYTES) == "streaming"


def test_the_settings_override_wins_in_both_directions():
    small = MemoryEstimate(lines_bytes=1_000, cube_bytes=1_000)
    assert choose_residency(small, 2, DEFAULT_BUDGET_BYTES, always_resident=True) == "resident"
    huge = MemoryEstimate(lines_bytes=1, cube_bytes=10**12)
    # The user asked for it and spec 7.4 never hard-caps; the dock warns.
    assert choose_residency(huge, 2, DEFAULT_BUDGET_BYTES, always_resident=True) == "resident"


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
