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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nsgeo.processing import available_steps, get_step

#: The Transform combo's "no transform" entry. Spec 6.2 and GPRSLICE's own
#: `xfrm_method=NONE` both allow it: the slice is then a signed mean, drawn
#: on a bipolar table, and the two stay consistent because the transform
#: being absent is exactly what `output_unipolar` reports.
NO_TRANSFORM = ""

#: Measured, spec 7.4: streaming costs ~0.14 ms per line per tick.
STREAM_MS_PER_LINE = 0.14

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
    """Registered steps whose output is unipolar, in registry order.

    From the registry, never a literal: the plugin's rule everywhere is
    that steps come from `available_steps()`, and a hardcoded list would
    silently omit any transform added to the core later.
    """
    return [name for name in available_steps() if getattr(get_step(name), "unipolar", False)]


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
    n_lines: int,
    budget_bytes: int = DEFAULT_BUDGET_BYTES,
    always_resident: bool = False,
) -> str:
    """`"resident"` or `"streaming"`, from the line count and the budget.

    Three tiers are described in spec 7.4; two exist. The third -- one
    line at a time, memory-mapped off disk -- is unmeasured there, was
    never built, and M11 deliberately ships no control for it (plan
    Ruling 1). This function therefore returns one of two values, and
    nothing downstream should branch on a third.
    """
    if always_resident:
        return "resident"
    if n_lines * STREAM_MS_PER_LINE <= FRAME_BUDGET_MS:
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
