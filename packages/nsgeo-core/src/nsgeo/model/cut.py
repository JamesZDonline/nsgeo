"""A cut: a path drawn on a grid, whose vertical section the cube gives (cut spec §3).

A cut is not a `Line`. It has no DZT file, no placement and no processing, so
it lives in `Site.cuts` and is keyed `cut:<id>`. Line keys are DZT paths, so
the two key spaces cannot collide (plan call 2). Vertices are grid-local
metres in drawn order, so a cut follows its grid if the grid is edited.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

CUT_KEY_PREFIX = "cut:"


def cut_key(cut_id: str) -> str:
    return CUT_KEY_PREFIX + cut_id


def is_cut_key(key: str) -> bool:
    return key.startswith(CUT_KEY_PREFIX)


@dataclass(frozen=True)
class Cut:
    id: str
    name: str
    grid_id: str
    vertices: tuple[tuple[float, float], ...]  # grid-local metres, drawn order

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("a cut needs a non-empty id and name")
        if len(self.vertices) < 2:
            raise ValueError(f"a cut needs at least two vertices, got {len(self.vertices)}")
        for vertex in self.vertices:
            if len(vertex) != 2 or not all(math.isfinite(c) for c in vertex):
                raise ValueError(f"cut vertices must be finite (x, y) pairs, got {vertex!r}")

    @classmethod
    def new(cls, grid_id: str, vertices: Sequence[tuple[float, float]], name: str) -> Cut:
        """A cut with a fresh id. Consecutive duplicate vertices are dropped, so a
        double click does not leave a zero-length segment."""
        kept: list[tuple[float, float]] = []
        for x, y in vertices:
            point = (float(x), float(y))
            if not all(math.isfinite(c) for c in point):
                raise ValueError(f"cut vertices must be finite, got {point!r}")
            if not kept or point != kept[-1]:
                kept.append(point)
        if len(kept) < 2:
            raise ValueError("a cut needs two different points")
        return cls(id=uuid.uuid4().hex, name=name, grid_id=grid_id, vertices=tuple(kept))

    @property
    def key(self) -> str:
        return cut_key(self.id)

    def _segments(self) -> list[tuple[float, float, float]]:
        """(start distance, length, index of the segment's first vertex)."""
        out = []
        run = 0.0
        for i in range(len(self.vertices) - 1):
            (x0, y0), (x1, y1) = self.vertices[i], self.vertices[i + 1]
            length = math.hypot(x1 - x0, y1 - y0)
            out.append((run, length, float(i)))
            run += length
        return out

    @property
    def length_m(self) -> float:
        return sum(length for _, length, _ in self._segments())

    def point_at(self, distance_m: float) -> tuple[float, float]:
        """The point `distance_m` along the path, clamped to its ends."""
        segments = self._segments()
        d = min(max(distance_m, 0.0), self.length_m)
        for start, length, first in segments:
            if d <= start + length or first == len(segments) - 1:
                (x0, y0), (x1, y1) = self.vertices[int(first)], self.vertices[int(first) + 1]
                t = 0.0 if length == 0.0 else min(max((d - start) / length, 0.0), 1.0)
                return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
        raise AssertionError("unreachable: a cut has at least one segment")

    def locate(self, local: tuple[float, float]) -> tuple[float, float]:
        """(distance along the path, distance off it) of the nearest point on it."""
        px, py = local
        best = (math.inf, 0.0)
        for start, length, first in self._segments():
            (x0, y0), (x1, y1) = self.vertices[int(first)], self.vertices[int(first) + 1]
            dx, dy = x1 - x0, y1 - y0
            t = 0.0 if length == 0.0 else ((px - x0) * dx + (py - y0) * dy) / (length * length)
            t = min(max(t, 0.0), 1.0)
            offset = math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
            if offset < best[0]:
                best = (offset, start + t * length)
        return (best[1], best[0])
