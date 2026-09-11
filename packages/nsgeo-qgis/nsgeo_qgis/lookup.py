"""Qt-free helpers behind the dialogs and map tools.

Import planning, the nearest-trace search the map link uses, polygon
corners for the grid dialog, and the identity gain curve. No Qt anywhere,
so all of it runs on the normal CI matrix.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzt import DztError, read_header, trace_count
from nsgeo.io.dzx import DzxError, DzxInfo, read_dzx
from nsgeo.model.survey import Line

_TRAILING = re.compile(r"(\d+)\s*$")


def trailing_number(stem: str) -> int | None:
    """GSSI FILE__001, MALA DAT_0001, Sensors & Software LINE01 all end in
    a sequence number. Vendor-neutral by construction."""
    m = _TRAILING.search(stem)
    return int(m.group(1)) if m else None


def sort_files(paths: Sequence[str | Path]) -> list[Path]:
    def key(p: Path) -> tuple[bool, int, str]:
        n = trailing_number(p.stem)
        return (n is None, n or 0, p.name)

    return sorted((Path(p) for p in paths), key=key)


@dataclass(frozen=True)
class ImportOptions:
    grid_id: str
    axis: str  # the axis the lines run ALONG
    spacing: float  # across the other axis
    first_offset: float = 0.0
    start_along: float = 0.0
    direction_mode: str = "alternate"  # alternate | forward | reverse
    label_source: str = "stem"  # stem | number
    grid_size_along: float | None = None  # for the over-length warning


@dataclass
class ImportRow:
    path: Path
    label: str
    offset: float
    direction: int
    start_along: float
    n_traces: int | None
    length_m: float | None
    traces_per_metre: float
    sidecar: DzxInfo | None
    include: bool = True
    offset_edited: bool = False
    note: str = ""

    @property
    def placeable(self) -> bool:
        return self.traces_per_metre > 0 and self.n_traces is not None


def _read_sidecar(path: Path) -> tuple[DzxInfo | None, str]:
    """Best-effort .DZX read: a malformed sidecar becomes a row-level note,
    never a crash. A missing sidecar (the common case, e.g. FILE__010 in the
    real data) is silent -- read_dzx already returns None for that."""
    try:
        return read_dzx(path), ""
    except DzxError as exc:
        return None, f"sidecar unreadable: {exc}"


def plan_import(paths: Sequence[str | Path], options: ImportOptions) -> list[ImportRow]:
    rows: list[ImportRow] = []
    for path in sort_files(paths):
        sidecar, note = _read_sidecar(path)
        n: int | None
        try:
            header = read_header(path)
            n = trace_count(path, header)
            spm = float(header.traces_per_metre)
        except (DztError, OSError) as exc:
            # A single unreadable/non-DZT file must not take the whole batch
            # down with it -- same principle as the traces_per_metre=0 case
            # below, just triggered by a bad header instead of a bad rate.
            n = None
            spm = 0.0
            note = "; ".join(filter(None, [note, f"cannot read header: {exc}"]))
        rows.append(
            ImportRow(
                path=path,
                label=path.stem,
                offset=options.first_offset,
                direction=1,
                start_along=options.start_along,
                n_traces=n,
                length_m=n / spm if n is not None and spm > 0 else None,
                traces_per_metre=spm,
                sidecar=sidecar,
                include=spm > 0,
                note=note,
            )
        )
    recompute_offsets(rows, options)
    return rows


def _merge_note(note: str, marker: str, text: str | None) -> str:
    """Set (or, if `text` is None, clear) the note component identified by
    `marker`, leaving any other component untouched -- e.g. a sidecar-parse
    warning set once when the row was built. This is what keeps
    recompute_offsets safe to call repeatedly as the import table is
    edited: it only ever touches the notes it itself derives, and never
    duplicates them on a second call."""
    parts = [p for p in note.split("; ") if p and not p.startswith(marker)]
    if text is not None:
        parts.append(text)
    return "; ".join(parts)


def recompute_offsets(rows: list[ImportRow], options: ImportOptions) -> None:
    """Offsets, directions, labels, and start_along over the included rows,
    in table order. A hand-edited offset is kept; everything else follows
    the slot index, so excluding a redone line pulls the next file into its
    place.

    Also (re)derives three placement-dependent note components -- the
    unplaceable-row exclusion, the reversed-direction start point, and the
    over-length warning -- without touching any other note already on the
    row.
    """
    slot = 0
    for row in rows:
        if not row.placeable:
            row.include = False
            if row.n_traces is not None:
                # A real header, but a non-positive acquisition rate: this
                # really is a time-triggered survey. When the header itself
                # never read (n_traces is None), nothing is known about the
                # acquisition mode -- plan_import's own "cannot read header"
                # note already says why, and asserting time-triggering here
                # would be a fabricated diagnosis.
                row.note = _merge_note(
                    row.note,
                    "time-triggered",
                    "time-triggered (traces/m = 0): cannot be grid-placed",
                )
        if not row.include:
            continue
        if not row.offset_edited:
            row.offset = options.first_offset + slot * options.spacing
        if options.direction_mode == "alternate":
            row.direction = 1 if slot % 2 == 0 else -1
        elif options.direction_mode == "reverse":
            row.direction = -1
        else:
            row.direction = 1
        row.label = f"line {slot}" if options.label_source == "number" else row.path.stem

        # GridPlacement.distance_along is start_along + direction * (i/spm):
        # a reversed row starting at the same start_along as a forward row
        # runs the wrong way, off the far side of the origin edge, instead
        # of down into the grid. A reversed row must start at the far end
        # of the axis instead.
        reversed_note: str | None = None
        if row.direction == -1:
            if options.grid_size_along is not None:
                row.start_along = options.start_along + options.grid_size_along
            else:
                row.start_along = options.start_along
                reversed_note = (
                    "reversed direction cannot be positioned without a known "
                    "grid length along this axis; using start_along as given"
                )
        else:
            row.start_along = options.start_along
        row.note = _merge_note(row.note, "reversed direction", reversed_note)

        exceeds: str | None = None
        if (
            options.grid_size_along is not None
            and row.length_m is not None
            and row.length_m > options.grid_size_along + 1e-9
        ):
            exceeds = (
                f"exceeds grid size along {options.axis} ({options.grid_size_along} m) "
                f"by {row.length_m - options.grid_size_along:.2f} m"
            )
        row.note = _merge_note(row.note, "exceeds grid size along", exceeds)
        slot += 1


def rows_to_lines(rows: Sequence[ImportRow], options: ImportOptions) -> list[Line]:
    return [
        Line.open(
            row.path,
            GridPlacement(
                grid_id=options.grid_id,
                axis=options.axis,
                offset=float(row.offset),
                start_along=float(row.start_along),
                direction=int(row.direction),
                label=row.label,
            ),
        )
        for row in rows
        if row.include and row.placeable
    ]


def nearest_trace(
    coords_by_key: Mapping[str, np.ndarray], xy: tuple[float, float], tolerance: float
) -> tuple[str, int, float] | None:
    """The (line key, trace index, distance) closest to `xy`, or None when
    nothing lies within `tolerance`. Plain numpy: ten lines are a few
    thousand points, no spatial index needed."""
    best: tuple[str, int, float] | None = None
    point = np.asarray(xy, dtype=float)
    for key, coords in coords_by_key.items():
        if len(coords) == 0:
            continue
        d = np.hypot(coords[:, 0] - point[0], coords[:, 1] - point[1])
        i = int(np.argmin(d))
        if d[i] <= tolerance and (best is None or d[i] < best[2]):
            best = (key, i, float(d[i]))
    return best


@dataclass(frozen=True)
class PolygonCorners:
    local: np.ndarray  # (4, 2) grid-local metres
    world: np.ndarray  # (4, 2) world coordinates
    size_x: float
    size_y: float


def corners_from_polygon(
    vertices: Sequence[tuple[float, float]], origin_index: int, plus_y_index: int
) -> PolygonCorners:
    """Turn a four-vertex ring into the control points a rigid fit wants.
    `plus_y_index` must neighbour `origin_index`; the other neighbour is +X
    and the remaining vertex is +X+Y.

    Of the two corners adjacent to the origin, only one yields a
    right-handed (non-mirrored) frame; the other is rejected. Silently
    accepting it would be worse than accepting a non-square quadrilateral:
    fit_grid_from_corners forbids reflection by construction, so a mirrored
    pick still returns a plausible-looking origin, size, and azimuth --
    identical to the correct pick's -- with nothing but a large
    residual_rms to distinguish it, which callers may reasonably read as
    "not square" rather than "wrong corner".
    """
    pts = [tuple(map(float, v)) for v in vertices]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) != 4:
        raise ValueError(f"expected four corners, got {len(pts)}")
    o = origin_index % 4
    if plus_y_index % 4 not in ((o + 1) % 4, (o - 1) % 4):
        raise ValueError("the +Y corner must be adjacent to the origin corner")
    y = plus_y_index % 4
    x = (o - 1) % 4 if y == (o + 1) % 4 else (o + 1) % 4
    # cross(x - o, y - o) is positive iff (+X, +Y) is a right-handed pair --
    # which a real grid's axes always are (Grid.axes() has
    # cross(x_hat, y_hat) == +1 at every azimuth). A rotation (to_world's
    # only transform) preserves that sign; a reflection would flip it. So a
    # non-positive cross here means this (origin, +Y) pick mirrors the two
    # neighbours onto each other's roles, regardless of the ring's own
    # winding direction.
    cross = (pts[x][0] - pts[o][0]) * (pts[y][1] - pts[o][1]) - (pts[x][1] - pts[o][1]) * (
        pts[y][0] - pts[o][0]
    )
    if cross <= 0:
        raise ValueError(
            "these corners are mirrored: pick the other corner adjacent to the origin for +Y"
        )
    far = ({0, 1, 2, 3} - {o, x, y}).pop()
    world = np.array([pts[o], pts[x], pts[far], pts[y]], dtype=float)
    size_x = float(math.dist(pts[o], pts[x]))
    size_y = float(math.dist(pts[o], pts[y]))
    local = np.array([[0.0, 0.0], [size_x, 0.0], [size_x, size_y], [0.0, size_y]])
    return PolygonCorners(local=local, world=world, size_x=size_x, size_y=size_y)


def identity_curve(t0_ns: float, dt_ns: float, n_samples: int) -> list[list[float]]:
    """Two control points at 0 dB spanning the time axis: the identity, so
    seeding gain_curve with it is not a guess."""
    t_end = t0_ns + dt_ns * (n_samples - 1)
    return [[float(t0_ns), 0.0], [float(t_end), 0.0]]
