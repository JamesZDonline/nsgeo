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
from typing import TypeVar

import numpy as np
from nsgeo.geometry import GridPlacement
from nsgeo.io import DztError, DzxError, DzxInfo, read_dzx, read_header, trace_count
from nsgeo.model import Line

_TRAILING = re.compile(r"(\d+)\s*$")
_T = TypeVar("_T")


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
    label_edited: bool = False
    direction_edited: bool = False
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
    duplicates them on a second call.

    `"; "` is this function's own delimiter between components, so neither
    `marker` nor `text` may contain it: a `text` with an embedded `"; "` is
    stored as two components, only the first of which starts with
    `marker`, so the second is never recognised (and never cleared) again.
    """
    assert "; " not in marker and (text is None or "; " not in text), (
        f"a note component may not contain '; ', which is _merge_note's own delimiter: {text!r}"
    )
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
        if not row.direction_edited:
            if options.direction_mode == "alternate":
                row.direction = 1 if slot % 2 == 0 else -1
            elif options.direction_mode == "reverse":
                row.direction = -1
            else:
                row.direction = 1
        if not row.label_edited:
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
                # A comma, not "; " -- that is _merge_note's own delimiter
                # (see its docstring), and this text must stay one
                # component across repeated recompute_offsets calls.
                reversed_note = (
                    "reversed direction cannot be positioned without a known "
                    "grid length along this axis, so start_along is used as given"
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


def identity_curve(t0_ns: float, dt_ns: float, n_samples: int) -> list[list[float]]:
    """Two control points at 0 dB spanning the time axis: the identity, so
    seeding gain_curve with it is not a guess."""
    t_end = t0_ns + dt_ns * (n_samples - 1)
    return [[float(t0_ns), 0.0], [float(t_end), 0.0]]


# --- grid corners ---------------------------------------------------------

CORNER_ROLES: tuple[str, str, str, str] = ("origin", "+X", "+X+Y", "+Y")

_COINCIDENT = 1e-6  # metres: shorter than this, two corners are one point
_DEGENERATE_AREA = 1e-9  # relative to the largest edge squared
_BEARING_TIE = 1e-9  # degrees: bearings closer than this are a tie
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def utm_epsg(lon: float, lat: float) -> int | None:
    """The WGS 84 UTM EPSG code for a lon/lat, so a grid picked on a
    geographic map still gets metre coordinates. UTM is undefined beyond
    84 degrees (UPS territory) and for non-finite input, so those give None.
    """
    if not (math.isfinite(lon) and math.isfinite(lat)) or abs(lat) > 84:
        return None
    zone = math.floor((lon + 180) / 6) % 60 + 1
    return (32600 if lat >= 0 else 32700) + zone


@dataclass(frozen=True)
class CornerFrame:
    rows: tuple[int, ...]  # filled row indices, ascending
    local: np.ndarray  # (n, 2) metres in the grid's own frame
    world: np.ndarray  # (n, 2) the points as given
    size_x: float | None  # measured; None when no filled edge spans the axis
    size_y: float | None


def _signed_area(pts: np.ndarray) -> float:
    # Centred first: at UTM magnitudes (northings ~4e6) the raw shoelace sum
    # is a difference of ~1e13-sized products, and its rounding noise would
    # swamp the area of a narrow or exactly collinear set.
    centred = pts - pts.mean(axis=0)
    x, y = centred[:, 0], centred[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _cross(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Signed area (times two) of the turn a -> b -> c; positive is anticlockwise."""
    return float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def corner_frame(points: Sequence[tuple[float, float] | None]) -> CornerFrame:
    """Turn up to four picked corners (CORNER_ROLES order, None for an empty
    row) into the local frame a fit needs: origin (0, 0), +X (sx, 0),
    +X+Y (sx, sy), +Y (0, sy), each size the mean of its filled edges.

    Mirrored corners are refused, not fitted. The fit forbids reflections, so
    it would return a plausible-looking frame with only a large RMS to show
    for the mistake; naming the cause is the useful answer. Four corners
    whose consecutive turns disagree in sign are crossed (two rows swapped,
    say Z order): a wrong correspondence like a mirrored set, and refused for
    the same reason, rather than fitted into a bad frame or misreported as
    "in a line".
    """
    if len(points) != 4:
        raise ValueError(f"expected four corner slots, got {len(points)}")
    rows = tuple(i for i, p in enumerate(points) if p is not None)
    if len(rows) < 2:
        raise ValueError("fit needs at least two corners")
    world = np.array([points[i] for i in rows], dtype=float)
    at = {r: world[k] for k, r in enumerate(rows)}

    def edges(pairs: tuple[tuple[int, int], ...]) -> list[float]:
        return [float(np.linalg.norm(at[a] - at[b])) for a, b in pairs if a in at and b in at]

    x_edges = edges(((0, 1), (3, 2)))
    y_edges = edges(((0, 3), (1, 2)))
    if any(e < _COINCIDENT for e in x_edges + y_edges):
        raise ValueError("two corners coincide")
    size_x = float(np.mean(x_edges)) if x_edges else None
    size_y = float(np.mean(y_edges)) if y_edges else None
    for name, size, needing in (("X", size_x, (1, 2)), ("Y", size_y, (2, 3))):
        if size is None and any(r in at for r in needing):
            raise ValueError(
                f"these corners don't fix the size along {name}: "
                f"pick two corners joined by an {name} edge"
            )
    sx, sy = size_x or 0.0, size_y or 0.0
    template = ((0.0, 0.0), (sx, 0.0), (sx, sy), (0.0, sy))
    local = np.array([template[r] for r in rows], dtype=float)
    if len(rows) == 4:
        turns = [
            _cross(world[a], world[b], world[c])
            for a, b, c in ((0, 1, 2), (1, 2, 3), (2, 3, 0), (3, 0, 1))
        ]
        if any(t > 0 for t in turns) and any(t < 0 for t in turns):
            raise ValueError("these corners are out of order: check which row each corner is in")
    if len(rows) >= 3:
        spread = max(float(np.linalg.norm(a - b)) for a in world for b in world)
        area = _signed_area(world)
        if abs(area) < _DEGENERATE_AREA * spread**2:
            raise ValueError("these corners lie in a line")
        if area < 0:
            raise ValueError("these corners are mirrored: check which corner is +X and which is +Y")
    return CornerFrame(rows, local, world, size_x, size_y)


def roles_from_ring(
    ring: Sequence[tuple[float, float]],
) -> tuple[list[tuple[float, float]], list[int]]:
    """Assign CORNER_ROLES to a four-vertex ring, returning the points in
    role order and each one's index in the cleaned ring.

    Cleaning drops consecutive duplicates and the closing vertex. Roles run
    anticlockwise (a clockwise ring is reversed), so +X is the next vertex
    and +Y the previous one, which keeps the frame right-handed. The origin
    is the vertex whose origin-to-+Y bearing is closest to north, so the
    default grid reads the way a surveyor would lay it; ties go to the lower
    vertex index (of the cleaned ring, whatever the winding) so the result
    is stable.
    """
    pts = [(float(p[0]), float(p[1])) for p in ring]
    clean: list[tuple[float, float]] = []
    for p in pts:
        if not clean or p != clean[-1]:
            clean.append(p)
    if len(clean) > 1 and clean[0] == clean[-1]:
        clean.pop()
    if len(clean) != 4:
        raise ValueError(f"expected four corners, got {len(clean)}")
    order = [0, 1, 2, 3]
    if _signed_area(np.array(clean)) < 0:
        order.reverse()
    best_k, best_bearing = 0, math.inf
    for k in range(4):
        o = clean[order[k]]
        y = clean[order[k - 1]]
        bearing = abs(math.degrees(math.atan2(y[0] - o[0], y[1] - o[1])))
        tie = abs(bearing - best_bearing) <= _BEARING_TIE
        if bearing < best_bearing - _BEARING_TIE or (tie and order[k] < order[best_k]):
            best_k, best_bearing = k, bearing
    # origin, +X (next), +X+Y (opposite), +Y (previous; k + 3 wraps to k - 1)
    idx = [order[(best_k + d) % 4] for d in (0, 1, 2, 3)]
    return [clean[i] for i in idx], idx


def rotate_roles(rows: Sequence[_T]) -> list[_T]:
    """Move every row's content one role on: +X becomes the origin, and so on.
    A cyclic shift keeps the frame right-handed, unlike a swap, and empty rows
    move with the rest."""
    return [rows[1], rows[2], rows[3], rows[0]]


def compass_label(point: tuple[float, float], centre: tuple[float, float]) -> str:
    """The eight-point compass direction of a point from a centre, so a corner
    can be named by where it sits on the map rather than by its role."""
    bearing = math.degrees(math.atan2(point[0] - centre[0], point[1] - centre[1]))
    return _COMPASS[math.floor((bearing + 22.5) / 45) % 8]
