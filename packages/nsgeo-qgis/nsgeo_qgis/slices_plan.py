"""Qt-free arithmetic behind the Slices dock.

Everything here is a pure function of plain values, so it runs on the
normal CI matrix (no QGIS) and under mypy, the same bargain `lookup.py`
makes. The dock reads it; the engine reads it; neither of them computes
any of it.

Two rules live here rather than in a widget, because both are decisions
with reasons rather than layout:

* **A preset never carries an amplitude transform.** The engine appends
  the chosen transform after the preset's steps, so the transform is
  always the last enabled step and `StepStack.output_unipolar` is exact.
  Were a preset to carry one with a gain after it, `output_unipolar`
  would report False -- it is deliberately conservative, reporting only
  the last enabled step -- and a unipolar slice would be drawn on a
  bipolar table, which is the configuration error spec 8 exists to name.
* **Residency is chosen, not asked about.** Spec 9.2: a resident cube
  redraws a slice in 0.56 ms against streaming's 3.6 ms, and nobody can
  perceive that. It only begins to matter on a large site during a
  continuous drag. Asking a user to understand the word "residency" to
  make that call is asking them to do the plugin's job.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nsgeo.processing import get_step, grouped_steps
from nsgeo.slices import SliceWindow, ZAxis, plan_windows

#: The Transform combo's "no transform" entry. Spec 6.2 and GPRSLICE's own
#: `xfrm_method=NONE` both allow it: the slice is then a signed mean, drawn
#: on a bipolar table, and the two stay consistent because the transform
#: being absent is exactly what `output_unipolar` reports.
NO_TRANSFORM = ""

#: Issue #81: the transform a grid's slices start on. Square is what the
#: slices spec's convention names (Conyers, GPR-SLICE: "spatially averaged
#: squared amplitude or Hilbert envelope"). A default only fills a gap: a
#: transform the site remembers, "none" included, is kept.
DEFAULT_TRANSFORM = "amp_square"

#: Measured, spec 7.4: streaming costs ~0.14 ms per line per tick.
STREAM_MS_PER_LINE = 0.14

#: The lines that figure was measured on: spec 7 took every timing on "the
#: ten real files cycled to the stated line count", which hold 606-666
#: traces each, 630 on average.
MEASURED_TRACES_PER_LINE = 630

#: Streaming's cost per trace per tick (ruling T3-c, M12). Streaming
#: resamples and bins every trace of every line in the window, so its cost
#: goes with traces, not lines: M12's site benchmark streamed 100 lines of
#: 3000 traces in ~44 ms a tick (0.44 ms a line), where a per-line rate
#: called it 14 ms and imperceptible. Measured against that, this rate
#: predicts 0.67 ms a line -- on the cautious side.
STREAM_MS_PER_TRACE = STREAM_MS_PER_LINE / MEASURED_TRACES_PER_LINE

#: One 60 Hz frame. Below this, streaming is imperceptible.
FRAME_BUDGET_MS = 16.0

#: What the plugin will hold before it stops promoting to a resident cube.
#: A default, never a cap -- spec 7.4 warns and degrades, it does not block.
DEFAULT_BUDGET_BYTES = 1_500_000_000


@dataclass(frozen=True)
class SourceChoice:
    """What goes into a cube: spec 9.1's four decisions, as one value.

    `transform` is `NO_TRANSFORM` or a name from `transform_names()`.
    `line_keys` is the included subset, in survey order -- the thing the
    `Choose...` dialog edits.
    """

    grid_id: str
    preset: str
    transform: str
    line_keys: tuple[str, ...]


@dataclass(frozen=True)
class SiteSource:
    """What goes into a site slice: one transform, and each grid's own source.

    One transform for the whole site (spec 4.2): the grids are composed
    into one layer with one renderer, so they must agree on polarity, and
    the transform decides polarity. Each grid keeps its own preset and its
    own included lines. Order is the order grids are prepared in.
    """

    transform: str
    grids: tuple[SourceChoice, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for choice in self.grids:
            if choice.transform != self.transform:
                raise ValueError(
                    f"grid {choice.grid_id!r} is set to the transform {choice.transform!r}, "
                    f"but the site uses {self.transform!r}; a site has one transform"
                )
            if choice.grid_id in seen:
                raise ValueError(f"grid {choice.grid_id!r} is listed twice in the site source")
            seen.add(choice.grid_id)


@dataclass(frozen=True)
class Resolution:
    """The Resolution group's geometry: what a cube is binned at.

    Every field here invalidates every `LinePlan`. That is why they are
    one value rather than four setters -- there is no such thing as
    changing the cell size and keeping the plans, and M10 measured what
    happens when someone tries: a 1.0 m-cell plan used against a 0.5 m-cell
    frame bins every trace into the wrong cell, with no exception and
    plausible-looking coverage.

    The fill radius is NOT here: it is a display parameter applied after
    binning (spec 6.4), so it changes no plan.
    """

    cell: float
    dz_ns: float
    t0_ns: float
    t1_ns: float

    def __post_init__(self) -> None:
        if not self.cell > 0.0:
            raise ValueError(f"cell must be positive, got {self.cell}")
        if not self.dz_ns > 0.0:
            raise ValueError(f"dz_ns must be positive, got {self.dz_ns}")
        if not self.t1_ns > self.t0_ns:
            raise ValueError(f"t1_ns must exceed t0_ns, got {self.t0_ns}..{self.t1_ns}")


@dataclass(frozen=True)
class MemoryEstimate:
    """Held bytes, split the way spec 7.4 splits them.

    Separately, because they grow in opposite directions: cube memory
    grows with resolution and not with line count, cache memory the
    reverse. By 120 lines the cached lines cost more than the cube, so a
    single total would hide which one to act on.
    """

    lines_bytes: int
    cube_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.lines_bytes + self.cube_bytes


def transform_names() -> list[str]:
    """Registered steps whose output is unipolar, in the core's menu order
    (`grouped_steps()`, #82).

    From the registry, never a literal: the plugin's rule everywhere is
    that steps come from the registry, and a hardcoded list would
    silently omit any transform added to the core later.
    """
    return [
        name
        for _, names in grouped_steps()
        for name in names
        if getattr(get_step(name), "unipolar", False)
    ]


def preset_transform_conflict(steps: Sequence[Mapping[str, Any]]) -> str | None:
    """The name of the first amplitude transform in a preset, or None.

    Anywhere in the stack, and regardless of `enabled`: a disabled
    transform is one click from breaking the same invariant, with nothing
    to warn about it a second time.
    """
    for entry in steps:
        name = str(entry.get("step", ""))
        try:
            cls = get_step(name)
        except (KeyError, ValueError):
            continue  # not a step we know; not this function's business
        if getattr(cls, "unipolar", False):
            return name
    return None


#: The most cells a frame may have before the Slices dock refuses the
#: geometry. Not a memory *budget* -- spec 7.4 is explicit that those
#: warn rather than hard-cap -- but a floor under what can be drawn at
#: all. Cell count goes as 1/cell**2, so the arithmetic runs away fast:
#: measured on this repo, a 40 m grid at 0.01 m is 4000 x 4000, about a
#: gigabyte for ONE filled slice (the fill's FFT working set, ~64 B/cell,
#: dominates the 4 B/cell array), and 100 m is 6.4 GB. Streaming is no
#: escape: the per-slice array is the problem, not the cube. 4 million
#: cells keeps a filled slice near a quarter of a gigabyte, which still
#: covers a 100 m grid at 0.05 m -- far finer than any trace spacing
#: spec 4's own "no smaller than the trace spacing" would allow.
MAX_FRAME_CELLS = 4_000_000


def frame_cells(size_x: float, size_y: float, cell: float) -> int:
    """How many cells `CubeFrame.for_grid` would build for this geometry.

    Mirrors that method's own rounding exactly -- ceil, with a floor of
    one cell per axis -- because a bound computed from different
    arithmetic than the thing it bounds is not a bound.
    """
    if not cell > 0.0:
        raise ValueError(f"cell must be positive, got {cell}")
    nx = max(1, int(math.ceil(size_x / cell)))
    ny = max(1, int(math.ceil(size_y / cell)))
    return nx * ny


def smallest_safe_cell(size_x: float, size_y: float, max_cells: int = MAX_FRAME_CELLS) -> float:
    """The finest cell size, to a millimetre, whose frame still fits.

    Solved from `cells ~ size_x * size_y / cell**2` and then walked up
    against `frame_cells` itself, because `ceil` on each axis means the
    continuous solution can be one millimetre optimistic; the loop is
    what makes the result true rather than approximately true.

    Returns a value that may be below any control's own minimum -- a
    small grid is affordable at any cell size, and this must not invent a
    coarser floor than the UI already has. Callers take the max.
    """
    if not (size_x > 0.0 and size_y > 0.0):
        raise ValueError(f"grid size must be positive, got {size_x} x {size_y}")
    if max_cells < 1:
        raise ValueError(f"max_cells must be at least 1, got {max_cells}")
    cell = math.sqrt(size_x * size_y / max_cells)
    cell = math.ceil(cell * 1000.0) / 1000.0
    while cell > 0.0 and frame_cells(size_x, size_y, cell) > max_cells:
        cell = round(cell + 0.001, 3)
    return cell


#: Issue #81: the cell a grid starts from, in metres -- fixed, not a
#: fraction of the line spacing, because along a line the detail is set by
#: the trace spacing. `default_cell` caps it at half the line spacing.
DEFAULT_CELL_M = 0.2

#: Issue #81: the fill radius a grid starts from, in line spacings. Half a
#: spacing is the smallest radius that still closes the gap between lines
#: at their nominal offsets, so it smears far less than spec 6.4's 1.5x but
#: has no margin: a line that wanders off its offset can leave a stripe.
DEFAULT_RADIUS_SPACINGS = 0.5


def default_cell(spacing_m: float, floor: float) -> float:
    """The cell a grid is seeded with: `DEFAULT_CELL_M`, no larger than half
    the line spacing (spec 4), and never under `floor`, the finest cell the
    frame can afford (`smallest_safe_cell`)."""
    return max(floor, min(DEFAULT_CELL_M, spacing_m / 2.0))


def estimate_memory(prepared_samples: int, n_cells: int, nz: int) -> MemoryEstimate:
    """Bytes held by the prepared lines, and by a cube of this shape.

    `prepared_samples` is the total float32 sample count across every
    prepared line (`sum(n_samples * n_traces)`). The cube is float32
    `mean` plus int32 `count`, which is what `SliceCube` stores.
    """
    return MemoryEstimate(
        lines_bytes=int(prepared_samples) * 4,
        cube_bytes=int(nz) * int(n_cells) * 4 + int(n_cells) * 4,
    )


def choose_residency(
    estimate: MemoryEstimate,
    n_traces: int,
    budget_bytes: int = DEFAULT_BUDGET_BYTES,
    always_resident: bool = False,
) -> str:
    """`"resident"` or `"streaming"`, from the prepared trace count and the budget.

    M11's rule, costed per trace (ruling T3-c): stream while a tick costs
    no more than a frame, otherwise hold the cube if it fits the budget.
    `n_traces` is the total over every prepared line -- a line count alone
    misjudged 3000-trace lines about threefold.

    Three tiers are described in spec 7.4; two exist. The third -- one
    line at a time, memory-mapped off disk -- is unmeasured there, was
    never built, and M11 deliberately ships no control for it (plan
    Ruling 1). This function therefore returns one of two values, and
    nothing downstream should branch on a third.
    """
    if always_resident:
        return "resident"
    if n_traces * STREAM_MS_PER_TRACE <= FRAME_BUDGET_MS:
        # Imperceptible. Holding a cube here would spend memory to buy
        # nothing a person can see.
        return "streaming"
    if estimate.total_bytes <= budget_bytes:
        return "resident"
    return "streaming"


def format_bytes(n: int) -> str:
    """Megabytes, or gigabytes past a thousand of them. Never `0 MB`."""
    mb = n / 1_000_000.0
    if mb >= 1000.0:
        return f"{mb / 1000.0:.1f} GB"
    return f"{max(1, round(mb))} MB"


def format_status(
    mode: str,
    n_lines: int,
    estimate: MemoryEstimate,
    redraw_ms: float | None,
) -> str:
    """Spec 9.2's status line: what is held, and how fast slices redraw.

    Memory first, because spec 7.2 found memory and not time to be the
    binding constraint -- halving the cell doubles the time and
    quadruples the cube.
    """
    held = estimate.lines_bytes
    noun = "line" if n_lines == 1 else "lines"
    if mode == "resident":
        held += estimate.cube_bytes
        what = f"{n_lines} {noun} and the whole volume held in memory"
    else:
        what = f"{n_lines} {noun} held in memory"
    speed = "—" if redraw_ms is None else f"{max(1, round(redraw_ms))} ms"
    return f"{what}, {format_bytes(held)} · slices redraw in {speed}"


def depth_scroll_delta(angle_delta_y: int, shift_held: bool) -> int:
    """-1, 0 or +1 slice steps for one wheel event.

    Kept here, away from Qt, for two reasons: the plugin's boundary rule
    keeps arithmetic out of widgets, and `QWheelEvent`'s constructor
    differs between Qt 5 and Qt 6, so a rule pinned only through a
    synthesised event would be pinned only on one of them.

    Without shift this returns 0 and the event is not consumed: plain
    scrolling stays the map's zoom, because spec 9.3 is explicit that the
    slice introduces no new tool and takes no gesture away.
    """
    if not shift_held or angle_delta_y == 0:
        return 0
    return 1 if angle_delta_y < 0 else -1


# ---- the site view (M12) --------------------------------------------------

#: Ruling 4 (M12): the most windows the site's shared stretch is measured
#: over. Every one is binned, filled, normalised and adjusted for every
#: grid, so a ten-grid site measured at every window would cost seconds
#: per change -- and a display percentile does not need every window.
SITE_LIMIT_WINDOWS = 12


def radius_cells_for(spacing_m: float, radius_spacings: float, cell: float) -> int:
    """A grid's fill radius in cells, from a multiple of its own line spacing.

    Spec 4.4: in site scope the radius is a multiple of each grid's
    spacing, because one radius in metres would over-smooth a finely
    spaced grid and leave stripes in a coarse one. Rounded exactly as the
    dock's `radius_cells` rounds metres, so at equal spacings the site and
    This grid fill identically.
    """
    if not cell > 0.0:
        raise ValueError(f"cell must be positive, got {cell}")
    return max(0, int(round(radius_spacings * spacing_m / cell)))


def limit_windows(
    z: ZAxis, thickness_levels: int, max_windows: int = SITE_LIMIT_WINDOWS
) -> tuple[SliceWindow, ...]:
    """The windows the site's shared stretch is measured over (Ruling 4).

    `plan_windows(z, thickness, thickness)` -- abutting windows at the
    displayed thickness, never raw levels (trap 4) -- plus the thinner
    tail window `display.shared_limit` adds when the thickness does not
    divide the axis. Past `max_windows`, an evenly spread subset that
    always keeps the first window and the last.
    """
    if max_windows < 2:
        raise ValueError(f"max_windows must be at least 2, got {max_windows}")
    windows = list(plan_windows(z, thickness_levels, thickness_levels))
    if windows[-1].k1 < z.nz:
        windows.append(SliceWindow(windows[-1].k1, z.nz))
    n = len(windows)
    if n <= max_windows:
        return tuple(windows)
    # The step is more than one window, so the rounded positions are distinct.
    picks = [int(round(i * (n - 1) / (max_windows - 1))) for i in range(max_windows)]
    return tuple(windows[i] for i in picks)
