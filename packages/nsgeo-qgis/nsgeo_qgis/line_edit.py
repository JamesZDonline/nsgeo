"""Qt-free placement rules for editing lines (line editing spec §3 call 1).

One rule runs through all of it: a line's Start is measured from the edge it
starts at. A forward line starts at the near edge, so its inset from that
edge is `start_along`; a reversed line starts at the far edge, so its inset
is `length - start_along`. Flipping a line, moving it to a grid of another
length, and a grid changing length all keep that inset and recompute
`start_along` from it. They are one rule, not three, so they cannot drift
apart. An inset can be negative: a line that starts past its edge (Grid 5's
reversed lines, written when the grid was 1 m longer) keeps its overhang.

No Qt and no `qgis` imports, so all of it runs on the normal CI matrix and
the Edit lines table, the Survey panel and `SiteSession` share one copy.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass

from nsgeo.geometry import Grid, GridPlacement

# The Note's "a few centimetres": a Start closer to its edge than this is at it.
START_TOLERANCE_M = 0.05
# Two placements whose floats differ by no more than this are the same one,
# so a double flip (15 - (15 - 0.3) != 0.3 exactly) reads as no change.
SAME_M = 1e-9

REMOVED = "was removed from the site while the table was open"
CHANGED_ELSEWHERE = "changed elsewhere while the table was open"


def length_along(grid: Grid, axis: str) -> float:
    """How far a line on `axis` can run: `size_y` for y lines, else `size_x`."""
    return grid.size_y if axis == "y" else grid.size_x


def width_across(grid: Grid, axis: str) -> float:
    """The other size: what the offsets of lines on `axis` range over."""
    return grid.size_x if axis == "y" else grid.size_y


def edge_inset(placement: GridPlacement, length: float) -> float:
    """How far the line starts inside the edge it starts at."""
    return placement.start_along if placement.direction == 1 else length - placement.start_along


def start_at_inset(direction: int, inset: float, length: float) -> float:
    """The inverse of `edge_inset`."""
    return inset if direction == 1 else length - inset


def followed_length(
    placement: GridPlacement, old_length: float, new_length: float
) -> GridPlacement:
    """The placement after its grid's length changed: a reversed line keeps
    its inset from the far edge and moves with it; a forward line stays."""
    if placement.direction == 1:
        return placement
    inset = edge_inset(placement, old_length)
    return dataclasses.replace(placement, start_along=start_at_inset(-1, inset, new_length))


def same_placement(a: GridPlacement, b: GridPlacement) -> bool:
    return (
        a.grid_id == b.grid_id
        and a.axis == b.axis
        and a.direction == b.direction
        and a.label == b.label
        and abs(a.offset - b.offset) <= SAME_M
        and abs(a.start_along - b.start_along) <= SAME_M
    )


def placement_note(placement: GridPlacement, grid: Grid) -> str:
    """What looks off about a placement on `grid`, or "". Judges only the
    Start and the offset (line editing spec §4.3)."""
    length = length_along(grid, placement.axis)
    width = width_across(grid, placement.axis)
    d = edge_inset(placement, length)
    edge = "near" if placement.direction == 1 else "far"
    parts: list[str] = []
    if d < -START_TOLERANCE_M:
        parts.append(f"starts {-d:.2f} m past the {edge} edge")
    elif d > START_TOLERANCE_M:
        parts.append(f"starts {d:.2f} m inside the {edge} edge")
    if placement.offset < -START_TOLERANCE_M or placement.offset > width + START_TOLERANCE_M:
        parts.append(f"offset {placement.offset:.2f} m is outside the grid's {width:.2f} m width")
    return "; ".join(parts)


@dataclass(frozen=True)
class Inset:
    """A Start worked out when the edit is applied, against the length of the
    grid as it is then, not as the table saw it."""

    inset: float


@dataclass(frozen=True)
class LineEdit:
    """One line's requested change, against the placement the table `seen`.
    `None` means unchanged."""

    key: str
    seen: GridPlacement
    label: str | None = None
    offset: float | None = None
    direction: int | None = None
    start_along: float | Inset | None = None
    grid_id: str | None = None

    def placed(self, frames: Mapping[str, Grid]) -> GridPlacement:
        """`seen` with the set fields applied. `KeyError` for a grid that is
        not in `frames`."""
        p = self.seen
        g = self.grid_id or p.grid_id
        dirn = self.direction or p.direction
        length = length_along(frames[g], p.axis)
        if isinstance(self.start_along, Inset):
            start = start_at_inset(dirn, self.start_along.inset, length)
        elif self.start_along is not None:
            start = self.start_along
        elif g != p.grid_id or dirn != p.direction:
            inset = edge_inset(p, length_along(frames[p.grid_id], p.axis))
            start = start_at_inset(dirn, inset, length)
        else:
            start = p.start_along
        return GridPlacement(
            grid_id=g,
            axis=p.axis,
            offset=p.offset if self.offset is None else self.offset,
            start_along=start,
            direction=dirn,
            label=p.label if self.label is None else self.label,
        )

    def _inset_now(self, frames: Mapping[str, Grid]) -> tuple[GridPlacement, Inset]:
        p = self.placed(frames)
        return p, Inset(edge_inset(p, length_along(frames[p.grid_id], p.axis)))

    def flipped(self, frames: Mapping[str, Grid]) -> LineEdit:
        p, inset = self._inset_now(frames)
        return dataclasses.replace(self, direction=-p.direction, start_along=inset)

    def snapped(self) -> LineEdit:
        return dataclasses.replace(self, start_along=Inset(0.0))

    def moved_to(self, grid_id: str, frames: Mapping[str, Grid]) -> LineEdit:
        _, inset = self._inset_now(frames)
        return dataclasses.replace(self, grid_id=grid_id, start_along=inset)

    def shifted(self, delta: float, frames: Mapping[str, Grid]) -> LineEdit:
        return dataclasses.replace(self, offset=self.placed(frames).offset + delta)

    def changes(self, frames: Mapping[str, Grid]) -> bool:
        return not same_placement(self.placed(frames), self.seen)


@dataclass(frozen=True)
class Skipped:
    key: str
    label: str
    reason: str


@dataclass(frozen=True)
class EditOutcome:
    changed: tuple[str, ...] = ()
    reordered: bool = False
    skipped: tuple[Skipped, ...] = ()

    def message(self) -> str:
        n = len(self.changed)
        if n and self.reordered:
            text = f"changed {n} line(s) and reordered the lines"
        elif n:
            text = f"changed {n} line(s)"
        elif self.reordered:
            text = "reordered the lines"
        else:
            text = "nothing changed"
        for s in self.skipped:
            text += f"; {s.label} {s.reason}, so it was left as it is"
        return text


@dataclass(frozen=True)
class GridEditReport:
    """What a grid edit did to its lines. `moved` holds (axis, new length,
    reversed lines moved); `outside` the labels of lines whose offset now
    lies outside the width."""

    grid_id: str
    moved: tuple[tuple[str, float, int], ...] = ()
    outside: tuple[str, ...] = ()

    def message(self) -> str:
        parts = [
            f"{self.grid_id} is now {length:.2f} m along {axis}; "
            f"its {n} reversed line(s) moved with the far edge."
            for axis, length, n in self.moved
        ]
        if self.outside:
            parts.append(
                f"{len(self.outside)} line(s) on {self.grid_id} now lie outside its width: "
                f"{', '.join(self.outside)}."
            )
        return " ".join(parts)


__all__ = [
    "CHANGED_ELSEWHERE",
    "REMOVED",
    "SAME_M",
    "START_TOLERANCE_M",
    "EditOutcome",
    "GridEditReport",
    "Inset",
    "LineEdit",
    "Skipped",
    "edge_inset",
    "followed_length",
    "length_along",
    "placement_note",
    "same_placement",
    "start_at_inset",
    "width_across",
]
