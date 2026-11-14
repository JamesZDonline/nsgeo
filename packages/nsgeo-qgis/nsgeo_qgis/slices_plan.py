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

import dataclasses
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nsgeo.processing import get_step, grouped_steps
from nsgeo.slices import (
    METHODS,
    NEIGHBOURS_PER_QUADRANT,
    FinishSettings,
    SliceWindow,
    ZAxis,
    plan_windows,
)

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

#: How often the GUI thread looks for a finished background solve (plan
#: call 6). Short enough that a result appears within a frame or two of
#: landing, long enough that an idle poll costs nothing.
REFINE_POLL_MS = 20

#: The longest a minimum-curvature solve may take and still follow the depth
#: live (plan call 5, interpolation spec §7). A slice whose last solve took
#: longer is drawn as its kriging preview and refined once the depth rests.
LIVE_SOLVE_BUDGET_MS = 50.0

#: How long the depth must rest before the background refine starts (plan
#: call 5). Every preview draw restarts it, so dragging, the wheel, the arrow
#: keys and edits all wait the same way.
REFINE_REST_MS = 300

#: The most solved, unsmoothed slices an engine keeps (plan call 8): the
#: twelve stretch windows (`SITE_LIMIT_WINDOWS`) and a few recently viewed.
SOLVED_SLICES_KEPT = 16

#: The method a slow minimum-curvature slice is previewed with (plan call 5),
#: at the same max distance, search radius and smoothing, so its blanks are
#: the full result's.
PREVIEW_METHOD = "kriging"

#: The refine indicator, on the depth readout's row (walkthrough rounds 1-2,
#: W1-W3, K2): while a preview stands, while the slice on screen is solved (with a
#: grid count in Whole site), and while only stretch windows are. Short, so it
#: never wraps, and never in the bottom status line, whose height it would move.
PREVIEW_INDICATOR = "Kriging preview"
REFINING_SLICE_INDICATOR = "Refining…"
REFINING_GRIDS_INDICATOR = "Refining ({done} of {total})…"
MEASURING_STRETCH_INDICATOR = "Colour stretch ({done} of {total})…"

#: What the plugin will hold before it stops promoting to a resident cube.
#: A default, never a cap -- spec 7.4 warns and degrades, it does not block.
DEFAULT_BUDGET_BYTES = 1_500_000_000

#: What one export may hold in memory: every grid's fill weights, its taps and
#: one band's accumulators, plus any cube it keeps (`export_pipeline`, where
#: the measurement behind it is recorded). Unlike the live budget it IS a cap:
#: an export that would hold more is refused before it starts. The live
#: engines hold up to `DEFAULT_BUDGET_BYTES` in the same process, so it is no more.
EXPORT_BUDGET_BYTES = DEFAULT_BUDGET_BYTES


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

    def same_source(self, other: SourceChoice | None) -> bool:
        """Whether `other` builds the same cube: equal but for the ORDER of
        `line_keys`. A cube is a sum of per-line contributions
        (`accumulate`, `build_cube`, `stream_slice`), so the survey order a
        reorder changes moves nothing but float rounding; it is not a change
        of lines and must neither read stale nor cost a re-preparation
        (line editing spec §4.5)."""
        return (
            other is not None
            and self.grid_id == other.grid_id
            and self.preset == other.preset
            and self.transform == other.transform
            and set(self.line_keys) == set(other.line_keys)
        )


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

    The interpolation settings are NOT here (`SliceFinish`): they are display
    parameters applied after binning (interpolation spec §4), so they change
    no plan.
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


#: #177: a cube may hold this many levels per sample of its deepest line. The
#: wheel once took dz to 0.001 ns, a cube 200 times deeper than any record.
LEVELS_PER_SAMPLE = 2


class TooManyLevels(ValueError):
    """A resolution whose z axis is past `LEVELS_PER_SAMPLE` times the samples."""


def level_limit_problem(resolution: Resolution, samples: Sequence[int]) -> str | None:
    """Why `resolution` makes too many levels for lines of `samples` samples, or None.

    No lines, no limit."""
    if not samples:
        return None
    nz = ZAxis.from_range(resolution.t0_ns, resolution.t1_ns, resolution.dz_ns).nz
    deepest = max(samples)
    limit = LEVELS_PER_SAMPLE * deepest
    if nz <= limit:
        return None
    if len(set(samples)) == 1:
        why = f"twice the {deepest:,} samples in each line"
    else:
        why = f"twice the {deepest:,} samples in its deepest line"
    return (
        f"Too many levels: dz {resolution.dz_ns:.4g} ns from {resolution.t0_ns:,g} to "
        f"{resolution.t1_ns:,g} ns makes {nz:,} levels; this cube allows {limit:,} ({why}). "
        "Narrow z0\u2013z1 or raise dz."
    )


#: What a grid is finished with unless the user says otherwise (interpolation
#: spec §8): kriging, out to three quarters of a line spacing (the user's
#: decision of 2026-11-03, interpolation spec §5.2). Half a spacing was the
#: first default and striped nominal gaps: binning moves each line up to half
#: a cell, so a gap's middle cell can be ceil(spacing / cell) * cell / 2 from
#: data, at most (spacing + cell) / 2, which 0.75 covers for any cell up to
#: half the spacing. A skipped line still shows: at 0.5 m lines and a 0.2 m
#: cell its middle rows are 0.4 m from data.
DEFAULT_METHOD = "kriging"
DEFAULT_MAX_DISTANCE_SPACINGS = 0.75
#: The neighbour search reaches at least this many line spacings (plan call 1).
SEARCH_RADIUS_SPACINGS = 2.0

#: Method keys in `METHODS` order, with the labels the Method combo shows.
METHOD_LABELS: dict[str, str] = {
    "none": "None (binned only)",
    "idw": "Inverse distance (IDW)",
    "kriging": "Kriging",
    "min_curvature": "Minimum curvature",
}

#: Per cell, the fill weights' int32 source index and float32 weight for each
#: of the four quadrants' nearest neighbours. Deliberately the weights proper,
#: not `FillWeights.nbytes` (populated mask, targets): the estimate only has to
#: be the right order of magnitude to warn before anything is built. Building
#: them peaks a little above it: 105-107 B a cell, measured on wandering 0.5 m
#: lines over 50 m at 0.05 m, once `plan_fill` chunked its working set (466-561
#: B before), within the half again this estimate is allowed
#: (`test_the_weights_estimate_covers_building_them`).
WEIGHT_BYTES_PER_CELL = 4 * NEIGHBOURS_PER_QUADRANT * 8

#: Minimum curvature holds two sets of weights for a frame (#148): its plan
#: (the operator and, since #111, its multigrid levels: 95-98 B a cell,
#: measured on the same lines) and, built with it, the kriging preview drawn
#: while the depth moves (`PREVIEW_METHOD`, `WEIGHT_BYTES_PER_CELL`). This is
#: the plan's part; `estimate_memory` counts it on top of the preview's.
CURVATURE_PLAN_BYTES_PER_CELL = 96

#: The remembered fields a `SliceFinish` is made of.
FINISH_FIELDS = ("method", "max_distance_spacings", "smooth_x_m", "smooth_y_m")


def _non_negative(value: object) -> float | None:
    """`value` as a finite non-negative float, or None. A bool is no number,
    matching the core loader's `_finite`."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number >= 0.0 else None


@dataclass(frozen=True)
class SliceFinish:
    """How a slice is finished: the fill method, how far from data it may
    reach (in line spacings, so it follows a grid's spacing), and the X/Y
    smoothing in metres (interpolation spec §8)."""

    method: str = DEFAULT_METHOD
    max_distance_spacings: float = DEFAULT_MAX_DISTANCE_SPACINGS
    smooth_x_m: float = 0.0
    smooth_y_m: float = 0.0

    def in_metres(self, spacing_m: float) -> FinishSettings:
        if not spacing_m > 0.0:
            raise ValueError(f"line spacing must be positive, got {spacing_m}")
        max_distance_m = self.max_distance_spacings * spacing_m
        return FinishSettings(
            method=self.method,
            max_distance_m=max_distance_m,
            search_radius_m=max(SEARCH_RADIUS_SPACINGS * spacing_m, 2.0 * max_distance_m),
            smooth_x_m=self.smooth_x_m,
            smooth_y_m=self.smooth_y_m,
        )

    def updated(self, fields: Mapping[str, object]) -> SliceFinish:
        """`self` with the finish fields in `fields` laid over it. A method
        this build does not know, a negative or non-finite number, and every
        other key are ignored, so a damaged record falls back field by field."""
        method = fields.get("method")
        kept: dict[str, Any] = {}
        if isinstance(method, str) and method in METHODS:
            kept["method"] = method
        for key in FINISH_FIELDS[1:]:
            number = _non_negative(fields.get(key))
            if number is not None:
                kept[key] = number
        return dataclasses.replace(self, **kept)


@dataclass(frozen=True)
class MemoryEstimate:
    """Held bytes, split the way spec 7.4 splits them.

    Separately, because they grow differently: a packed cube grows with the
    cells the lines cover (so with line count and with resolution), cache
    memory with line count alone. By 120 lines the cached lines can cost
    more than the cube, so a single total would hide which one to act on.
    """

    lines_bytes: int
    cube_bytes: int
    #: The interpolation weights, built once per grid and kept (interpolation
    #: spec §7). Counted so a fine cell on a large grid warns before building.
    weights_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self.lines_bytes + self.cube_bytes + self.weights_bytes


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
#: all. Cell count goes as 1/cell**2, so the arithmetic runs away fast: a
#: 40 m grid at 0.01 m is 4000 x 4000, 16 million cells, and 100 m is 100
#: million. Streaming is no escape: what grows is per cell, not the cube.
#: The interpolation dominates (interpolation spec §7), measured on 0.5 m
#: lines at 0.05 m: the weights hold about 95 B a cell and peak near 107 B
#: while they are built (`WEIGHT_BYTES_PER_CELL`), and each finished slice
#: needs about 55 B a cell more to apply them and 41 B to smooth, against
#: the 4 B a cell of the slice itself. 4 million cells is then about 0.4 GB
#: of weights and 0.2 GB a slice (0.4 GB smoothed). Minimum curvature holds
#: twice the weights, its plan beside a kriging preview (about 190 B a cell,
#: `CURVATURE_PLAN_BYTES_PER_CELL`, #148), so nearer 0.8 GB, and each solve
#: needs about 35 B a cell of working space, with up to two running at once
#: (the refine worker and the GUI thread): about 1.2 GB smoothed. Both stay
#: inside the 1.5 GB default budget, and the cap still covers a 100 m grid at
#: 0.05 m -- far finer than spec 4's own "no smaller than the trace spacing"
#: would allow.
MAX_FRAME_CELLS = 4_000_000

#: Two limits decide whether the whole-site picture is drawn at the cell or as
#: a coarser preview (which also refuses to export). The site lattice is not
#: a frame: its cost is the compose, not the interpolation `MAX_FRAME_CELLS`
#: guards. Measured with `scripts/bench_site.py` (idle workstation, 15.9 GB),
#: against compose <= 250 ms and transient <= 400 MB:
#:
#: `SITE_MAX_PIXELS` bounds the lattice itself, the 10 B a pixel the compose
#: accumulates. `--lattice-scale`: ten 20 m grids spaced apart, kriging, no
#: smoothing, 0.25 m cell, so only ~0.64 M pixels are covered by grids:
#:
#:     lattice   compose (median)   transient
#:      4 M          12 ms            40 MB
#:      8 M          19 ms            80 MB
#:     12 M          23 ms           120 MB
#:     16 M          29 ms           160 MB
#:     24 M          39 ms           240 MB
#:
#: All meet the criterion, so the limit is the 16 M cap.
SITE_MAX_PIXELS = 16_000_000

#: `SITE_MAX_COVERED_PIXELS` bounds the grids' windows summed at the drawn
#: pitch: the compose samples each covered pixel (about 46 ns rotated) and the
#: gathers hold about 52 B of taps for it, so a dense site at a fine cell
#: costs far more than the same lattice mostly empty. `--dense`: two grids at
#: 30 degrees, 0.05 m cell, filling the lattice:
#:
#:     covered   compose (median)   transient   gathers held
#:      2 M          81 ms            69 MB        104 MB
#:      4 M         167 ms           138 MB        208 MB
#:      5 M        ~240 ms           173 MB        260 MB
#:      6 M       241-283 ms         207 MB        312 MB
#:      8 M         353 ms           277 MB        416 MB
#:
#: 6 M passed once and failed twice on the 250 ms bar (timing noise at the
#: edge), so the limit is 5 M. The gathers are counted in
#: `SiteEngine.held_bytes`. Both limits at once (a 16 M lattice with 5 M
#: covered) composed in 244-245 ms with 225 MB transient: inside both bars,
#: with about 5 ms of headroom. The 250 ms bar is for value ticks; coverage
#: ticks (`counts=True`) run about 1.8x slower (~420 ms at the 5 M covered
#: limit) and are accepted, since coverage is a check view, not the one
#: scrubbed.
SITE_MAX_COVERED_PIXELS = 5_000_000


def old_cube_note(shift_ns: float) -> str:
    """The one line said when a radar-clock cube is rebuilt on the time-zero clock."""
    return (
        "This cube was saved before times were measured from each line's first break. "
        f"It was rebuilt that way, with its range moved by {shift_ns:+.2f} ns."
    )


#: A site whose grids are not all on one clock (a site-level notion; the two
#: clocks themselves are the core's `TIME_BASE_TIME_ZERO` and `TIME_BASE_RADAR`).
TIME_BASE_MIXED = "mixed"


def combined_time_base(bases: Iterable[str]) -> str:
    """The one clock a set of grids is on, or `TIME_BASE_MIXED` when they differ.

    The single rule behind both the site note and `NSGEO_SITE_TIME_BASE`. An
    empty set has no clock: refused, never called mixed."""
    distinct = set(bases)
    if not distinct:
        raise ValueError("no grids, so no time base")
    return distinct.pop() if len(distinct) == 1 else TIME_BASE_MIXED


def mixed_clock_note(radar_grids: Sequence[str]) -> str:
    """The warning for a site whose grids are on different clocks, naming the
    grids with no Time zero step; empty when there are none."""
    grids = list(radar_grids)
    if not grids:
        return ""
    if len(grids) == 1:
        return (
            f"Grid {grids[0]} has no Time zero step, so its times are from the radar's own "
            "zero and will not line up with the other grids."
        )
    return (
        f"Grids {name_list(grids)} have no Time zero step, so their times are from the "
        "radar's own zero and will not line up with the other grids."
    )


def name_list(names: Sequence[str]) -> str:
    """`A`, `A and B`, `A, B and C`."""
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def preview_note(
    pitch: float,
    cell: float,
    width_m: float,
    height_m: float,
    finest: float,
    stretching: Sequence[str],
) -> str:
    """Why the site is drawn coarser than its grids, and what would draw it in full."""
    note = (
        f"Preview at {pitch:g} m pixels: the site ({width_m:.0f} \u00d7 {height_m:.0f} m) "
        f"is too big to draw at {cell:g} m. "
        f"It draws in full at a {finest:g} m cell or coarser."
    )
    if stretching:
        grids = "grid" if len(stretching) == 1 else "grids"
        note = f"{note[:-1]}, or without {grids} {name_list(stretching)}."
    return note


def export_refusal(
    held_bytes: int, budget: int, finest_cell: float | None, finest_pixel: float | None
) -> str:
    """Why an export cannot start, and the finest cell or pixel that would fit."""
    text = (
        f"This export would hold about {format_bytes(held_bytes)} in memory, "
        f"more than the {format_bytes(budget)} it is allowed."
    )
    if finest_cell is not None:
        text += f" A {finest_cell:g} m export cell would fit."
    if finest_pixel is not None:
        text += f" A {finest_pixel:g} m export pixel would fit."
    return text


_METHOD_WORDS = {
    "none": "no interpolation",
    "idw": "inverse distance",
    "kriging": "kriging",
    "min_curvature": "minimum curvature",
}


def slices_text(finish: SliceFinish) -> str:
    """How the slices are made, for the export summary: `kriging, max distance
    0.75 × spacing, no smoothing`."""
    parts = [_METHOD_WORDS.get(finish.method, finish.method)]
    if finish.method != "none":
        parts.append(f"max distance {finish.max_distance_spacings:g} \u00d7 spacing")
    if finish.smooth_x_m or finish.smooth_y_m:
        parts.append(f"smoothing {finish.smooth_x_m:g} \u00d7 {finish.smooth_y_m:g} m")
    else:
        parts.append("no smoothing")
    return ", ".join(parts)


def _ns(value: float) -> str:
    return f"{round(value, 2):g}".replace("-", "\u2212")


def bands_detail(windows: Sequence[tuple[float, float]]) -> str:
    """The bands, for the export summary: `every 2.5 ns from −1.8 to 45 ns, 5 ns thick`.

    `windows` are each band's `(top_ns, thickness_ns)`. One band has no step.
    """
    if not windows:
        return ""
    first_top, thickness = windows[0]
    last_top, last_thickness = windows[-1]
    span = f"from {_ns(first_top)} to {_ns(last_top + last_thickness)} ns"
    if len(windows) == 1:
        return f"{span}, {_ns(thickness)} ns thick"
    step = windows[1][0] - first_top
    return f"every {_ns(step)} ns {span}, {_ns(thickness)} ns thick"


@dataclass(frozen=True)
class ExportPreview:
    """What the export dialog's summary shows for one cell and pixel.

    `grids` and `normalisation` are `None` for a single grid's export, which
    drops those two rows. `held_bytes` is what the export would hold in
    memory; `file_bytes` is what it would write (the coverage companion
    included).
    """

    cell: float
    pixel: float
    width_px: int
    height_px: int
    bands: int
    bands_detail: str
    slices: str
    grids: tuple[str, ...] | None
    normalisation: str | None
    file_bytes: int
    held_bytes: int


def summary_lines(preview: ExportPreview) -> list[tuple[str, str]]:
    """The rows of the export dialog's "What will be written" group."""
    bands = str(preview.bands)
    if preview.bands_detail:
        bands += f", {preview.bands_detail}"
    rows = [
        ("Bands", bands),
        (
            "Picture",
            f"{preview.width_px} \u00d7 {preview.height_px} pixels at {preview.pixel:g} m",
        ),
    ]
    if preview.grids is not None:
        named = f" ({name_list(preview.grids)})" if 1 < len(preview.grids) <= 4 else ""
        rows.append(
            ("Grids", f"{len(preview.grids)} included{named}, rebuilt at {preview.cell:g} m")
        )
    rows.append(("Slices", preview.slices))
    if preview.normalisation is not None:
        # With no normalisation nothing is measured, so there is nothing to measure again.
        again = (
            ""
            if preview.normalisation.lower() == "none"
            else f", measured again at {preview.cell:g} m"
        )
        rows.append(("Normalisation", f"{preview.normalisation}{again}"))
    rows.append(
        (
            "Memory",
            f"about {format_bytes(preview.held_bytes)} of the "
            f"{format_bytes(EXPORT_BUDGET_BYTES)} allowed",
        )
    )
    rows.append(
        ("File", f"about {format_bytes(preview.file_bytes)} before compression, plus a style file")
    )
    return rows


#: How far past the current cell `finest_fits` looks for a cell that fits.
FINEST_CELL_REACH = 8


def finest_fits(
    held_at: Callable[[float, float], int], cell: float, pixel: float, budget: int
) -> tuple[float | None, float | None]:
    """The finest `(cell, pixel)` that would fit `budget`, each on a 1 mm grid.

    The pixel is searched in `[pixel, cell]` at this cell; it is `None` when
    the pixel already equals the cell, or nothing fits. The cell is searched
    from this one up with the pixel set to it (`None` when this cell already fits),
    by doubling and then bisection, and is `None` past `FINEST_CELL_REACH` times this
    cell. Both assume the
    held bytes fall as the cell or the pixel grows, and use O(log) calls of
    `held_at`, each of which can be slow.
    """
    cell_mm = round(cell * 1000)
    pixel_mm = max(1, math.ceil(pixel * 1000 - 1e-6))

    def fits_pixel(mm: int) -> bool:
        return held_at(cell, mm / 1000.0) <= budget

    def fits_cell(mm: int) -> bool:
        return held_at(mm / 1000.0, mm / 1000.0) <= budget

    def smallest(lo: int, hi: int, fits: Callable[[int], bool]) -> int:
        # `hi` fits; the answer is in (lo, hi] when `lo` does not, else lo.
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if fits(mid):
                hi = mid
            else:
                lo = mid
        return hi

    finest_pixel: float | None = None
    if pixel_mm < cell_mm and fits_pixel(cell_mm):
        finest_pixel = smallest(pixel_mm - 1, cell_mm, fits_pixel) / 1000.0

    finest_cell: float | None = None
    # When the current cell already fits at pixel = cell, only the pixel needs to
    # change, so no finer cell is offered; otherwise search above it.
    lo, hi = cell_mm, cell_mm * 2
    while not fits_cell(cell_mm) and hi <= cell_mm * FINEST_CELL_REACH:
        if fits_cell(hi):
            finest_cell = smallest(lo, hi, fits_cell) / 1000.0
            break
        lo, hi = hi, hi * 2
    return finest_cell, finest_pixel


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


def default_cell(spacing_m: float, floor: float) -> float:
    """The cell a grid is seeded with: `DEFAULT_CELL_M`, no larger than half
    the line spacing (spec 4), and never under `floor`, the finest cell the
    frame can afford (`smallest_safe_cell`)."""
    return max(floor, min(DEFAULT_CELL_M, spacing_m / 2.0))


def estimate_memory(
    prepared_samples: int, n_cells: int, nz: int, n_covered: int, *, method: str
) -> MemoryEstimate:
    """Bytes held by the prepared lines, by a cube of this shape, and by the
    interpolation weights for `method`.

    `prepared_samples` is the total float32 sample count across every
    prepared line (`sum(n_samples * n_traces)`). A resident cube is packed
    (#113): it stores float32 `mean` (nz rows), int32 `count` and int64 cell
    ids for the `n_covered` covered cells only, which is exactly
    `SliceCube.nbytes`. `n_covered` is required so no caller can keep the
    dense figure by omission. The fill weights are written for every cell of
    the frame, so they still scale with `n_cells`. Minimum curvature holds its
    plan beside the kriging preview built with it, so it counts both (#148);
    `method` is required for the same reason as `n_covered`.
    """
    covered = int(n_covered)
    per_cell = WEIGHT_BYTES_PER_CELL
    if method == "min_curvature":
        per_cell += CURVATURE_PLAN_BYTES_PER_CELL
    return MemoryEstimate(
        lines_bytes=int(prepared_samples) * 4,
        cube_bytes=int(nz) * covered * 4 + covered * 4 + covered * 8,
        weights_bytes=int(n_cells) * per_cell,
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
    binding constraint -- halving the cell doubles the time, roughly
    doubles a packed cube of line data (the covered cells follow the line
    length) and still quadruples the fill weights.
    """
    # The interpolation weights are held in either mode (interpolation spec §7).
    held = estimate.lines_bytes + estimate.weights_bytes
    noun = "line" if n_lines == 1 else "lines"
    if mode == "resident":
        held += estimate.cube_bytes
        what = f"{n_lines} {noun} and the whole volume held in memory"
    else:
        what = f"{n_lines} {noun} held in memory"
    speed = "—" if redraw_ms is None else f"{max(1, round(redraw_ms))} ms"
    return f"{what}, {format_bytes(held)} · slices redraw in {speed}"


#: One notch of an ordinary mouse wheel, in `QWheelEvent.angleDelta()` units
#: (eighths of a degree, so 15 degrees).
WHEEL_NOTCH = 120


def depth_scroll_steps(pending: int, angle_delta_y: int) -> tuple[int, int]:
    """`(steps, pending)` for one shift+wheel event: the slice steps to move
    (+1 deeper per notch turned down) and the part-notch left over, which
    the caller hands back in with the next event.

    #109: a high-resolution wheel reports one notch as several smaller
    events, so stepping once per event moved the depth two Steps per notch
    on the user's mouse. Qt's `angleDelta` documentation says to add the
    deltas up until they reach a notch. Turning the wheel the other way
    drops the leftover, so the first notch back still takes effect.

    Kept here, away from Qt, for two reasons: the plugin's boundary rule
    keeps arithmetic out of widgets, and `QWheelEvent`'s constructor
    differs between Qt 5 and Qt 6, so a rule pinned only through a
    synthesised event would be pinned only on one of them.
    """
    if angle_delta_y == 0:
        return 0, pending
    if pending and (pending > 0) != (angle_delta_y > 0):
        pending = 0
    total = pending + angle_delta_y
    notches = abs(total) // WHEEL_NOTCH * (1 if total > 0 else -1)
    return -notches, total - notches * WHEEL_NOTCH


# ---- the site view (M12) --------------------------------------------------

#: Ruling 4 (M12): the most windows the site's shared stretch is measured
#: over. Every one is binned, filled, normalised and adjusted for every
#: grid, so a ten-grid site measured at every window would cost seconds
#: per change -- and a display percentile does not need every window.
SITE_LIMIT_WINDOWS = 12


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
