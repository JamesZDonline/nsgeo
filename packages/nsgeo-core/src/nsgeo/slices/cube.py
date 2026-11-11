"""The stored product: a volume of means, and how much data is under each cell.

Layout is z-major, `(nz, n)`, and that is measured rather than assumed.
Cell-major builds 3-15% faster because each cell's column is contiguous,
but z-major extracts a slice 7x faster -- and a slice is extracted on every
thickness and depth change, where a rebuild happens only when dz or the
cell size moves. Paying 15% on the rare operation makes the constant one
free.

`n` is the number of COVERED cells, not `frame.n_cells` (#113). A survey
leaves 60-90% of a frame's cells empty, and a dense cube spent 4 bytes per
level on every one of them (484 MB at 0.05 m, 63 MB packed). A block keeps
the ids of its covered cells beside its columns, and every read goes
through `SliceCube`, so no caller needs to know the layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from nsgeo.slices.frame import CubeFrame, ZAxis


@dataclass(frozen=True)
class Provenance:
    """What a reader needs in order to trust a cube.

    Kept as plain data so it survives a round trip through JSON without
    reaching back into the model: a cube outlives the session that built it
    and may be read by a front end that never loaded the site.
    """

    line_keys: tuple[str, ...]
    preset_name: str
    steps: tuple[dict[str, Any], ...]
    transform: str
    velocity: dict[str, Any] | None
    built_utc: str
    core_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_keys": list(self.line_keys),
            "preset_name": self.preset_name,
            "steps": [dict(s) for s in self.steps],
            "transform": self.transform,
            "velocity": self.velocity,
            "built_utc": self.built_utc,
            "core_version": self.core_version,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Provenance:
        return cls(
            line_keys=tuple(doc["line_keys"]),
            preset_name=doc["preset_name"],
            steps=tuple(dict(s) for s in doc.get("steps", ())),
            transform=doc["transform"],
            velocity=doc.get("velocity"),
            built_utc=doc["built_utc"],
            core_version=doc["core_version"],
        )


@dataclass(frozen=True)
class CubeBlock:
    """The covered cells of one travel direction, packed.

    `cells` are flat frame ids (`iy * nx + ix`), strictly increasing, so a
    read finds a cell with `searchsorted`. `mean` is `(nz, n)` and `count`
    is `(n,)`, every count at least 1: a cell with no traces is not stored
    at all, which is what makes the block small. `heading_deg` is `None`
    for a block holding every direction; #47 sets it once it groups lines
    by travel direction.

    Dtypes are float32, int32 and int64 as built and as saved, but only
    their kinds are enforced here: `save_cube` narrows whatever it is given, so a wide
    block is a caller's convenience and not a corrupt one.
    """

    cells: np.ndarray
    mean: np.ndarray
    count: np.ndarray
    heading_deg: float | None = None

    def __post_init__(self) -> None:
        if self.cells.ndim != 1:
            raise ValueError(f"cells must be 1-D, got shape {self.cells.shape}")
        if self.cells.dtype.kind not in "iu":
            raise ValueError(f"cells must be integer ids, got dtype {self.cells.dtype}")
        if self.mean.dtype.kind != "f":
            raise ValueError(f"mean must be floating point, got dtype {self.mean.dtype}")
        if self.count.dtype.kind not in "iu":
            raise ValueError(f"count must be integer, got dtype {self.count.dtype}")
        n = self.cells.size
        if self.mean.ndim != 2 or self.mean.shape[1] != n:
            raise ValueError(f"mean must be (nz, {n}), got {self.mean.shape}")
        if self.count.shape != (n,):
            raise ValueError(f"count must be ({n},), got {self.count.shape}")
        if n and not (np.diff(self.cells) > 0).all():
            raise ValueError("cells must be strictly increasing (sorted, no duplicates)")
        if n and int(self.count.min()) < 1:
            raise ValueError("every stored cell must have a count of at least 1")


@dataclass(frozen=True)
class SliceCube:
    """Binned amplitude over a frame and a z axis, in packed blocks.

    Read it with `slice_levels`, `level`, `values_at` and `coverage`; the
    block arrays are the storage, not the interface (#113).

    A cell's count is per cell rather than per (level, cell), which is
    exact only because the binner rejects any line whose time range does
    not span the whole axis -- so a cell is either covered at every level
    or at none. That is what lets `slice_levels` use a plain mean instead
    of nanmean.

    Several blocks may cover the same cell. A read then returns the
    count-weighted mean of the blocks, which is the mean of every trace in
    the cell.
    """

    frame: CubeFrame
    z: ZAxis
    blocks: tuple[CubeBlock, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.blocks:
            raise ValueError("a cube needs at least one block")
        for i, block in enumerate(self.blocks):
            if block.mean.shape[0] != self.z.nz:
                raise ValueError(
                    f"block {i}: mean has {block.mean.shape[0]} levels, but z has {self.z.nz}"
                )
            if block.cells.size and (
                int(block.cells[0]) < 0 or int(block.cells[-1]) >= self.frame.n_cells
            ):
                raise ValueError(
                    f"block {i}: cell ids must lie in [0, {self.frame.n_cells}), "
                    f"got {int(block.cells[0])}..{int(block.cells[-1])}"
                )

    @classmethod
    def from_dense(
        cls,
        frame: CubeFrame,
        z: ZAxis,
        mean: np.ndarray,
        count: np.ndarray,
        provenance: Provenance,
    ) -> SliceCube:
        """Pack a dense `(nz, n_cells)` mean and `(n_cells,)` count as one block.

        Keeps the columns where `count > 0`. Version 1 files (which stored
        the dense arrays) load through this, and tests use it to build
        small cubes from a literal array.
        """
        expected = (z.nz, frame.n_cells)
        if mean.shape != expected:
            raise ValueError(f"mean must be {expected}, got {mean.shape}")
        if count.shape != (frame.n_cells,):
            raise ValueError(f"count must be ({frame.n_cells},), got {count.shape}")
        cells = np.flatnonzero(count > 0)
        block = CubeBlock(
            cells=cells.astype(np.int64, copy=False),
            mean=np.ascontiguousarray(mean[:, cells], dtype=np.float32),
            count=count[cells].astype(np.int32, copy=False),
        )
        return cls(frame=frame, z=z, blocks=(block,), provenance=provenance)

    @property
    def nbytes(self) -> int:
        """Bytes held by every block array (ids, means and counts)."""
        return sum(b.cells.nbytes + b.mean.nbytes + b.count.nbytes for b in self.blocks)

    def _window(self, k0: int, k1: int) -> None:
        if not 0 <= k0 < k1 <= self.z.nz:
            raise ValueError(
                f"level window must satisfy 0 <= k0 < k1 <= {self.z.nz}, got {k0}..{k1}"
            )

    def slice_levels(self, k0: int, k1: int) -> np.ndarray:
        """Mean over the half-open level window, shaped (ny, nx).

        A plain mean, not nanmean: coverage does not vary with level, so
        every stored column is finite, and an uncovered cell is NaN at
        every level. One block takes the window mean of its columns in
        float32 and scatters it, the same arithmetic the dense layout did,
        so the slice is bit-identical to it (#113), except that a single-column
        block sums its column pairwise and can differ by one ulp. Several blocks combine
        as the count-weighted mean, in float64.
        """
        self._window(k0, k1)
        out = np.full(self.frame.n_cells, np.nan, dtype=np.float32)
        if len(self.blocks) == 1:
            (block,) = self.blocks
            out[block.cells] = block.mean[k0:k1].mean(axis=0)
        else:
            total = np.zeros(self.frame.n_cells, dtype=np.float64)
            weight = np.zeros(self.frame.n_cells, dtype=np.float64)
            for block in self.blocks:
                window = block.mean[k0:k1].mean(axis=0, dtype=np.float64)
                total[block.cells] += block.count * window
                weight[block.cells] += block.count
            seen = weight > 0
            out[seen] = total[seen] / weight[seen]
        return out.reshape(self.frame.ny, self.frame.nx)

    def level(self, k: int) -> np.ndarray:
        """One level, shaped (ny, nx): a window of width one."""
        return self.slice_levels(k, k + 1)

    def values_at(self, cells: np.ndarray, k0: int = 0, k1: int | None = None) -> np.ndarray:
        """Levels `k0..k1` at the given flat cell ids, shaped (k1 - k0, len(cells)).

        `-1` is the id `CubeFrame.cell_index` gives a point outside the
        frame, and a cell nothing landed in has no data; both read as NaN.
        Any other id outside the frame is a caller's bug and raises.
        """
        k1 = self.z.nz if k1 is None else k1
        self._window(k0, k1)
        ids = np.asarray(cells)
        if ids.ndim != 1 or ids.dtype.kind not in "iu":
            raise ValueError("cells must be a 1-D array of integer cell ids")
        ids = ids.astype(np.int64, copy=False)
        if ids.size and (int(ids.min()) < -1 or int(ids.max()) >= self.frame.n_cells):
            raise ValueError(
                f"cell ids must be -1 or lie in [0, {self.frame.n_cells}), "
                f"got {int(ids.min())}..{int(ids.max())}"
            )
        shape = (k1 - k0, ids.size)
        out = np.full(shape, np.nan, dtype=np.float32)
        total = None if len(self.blocks) == 1 else np.zeros(shape, dtype=np.float64)
        weight = np.zeros(ids.size, dtype=np.float64)
        for block in self.blocks:
            if block.cells.size == 0:
                continue
            at = np.minimum(np.searchsorted(block.cells, ids), block.cells.size - 1)
            hit = block.cells[at] == ids
            if total is None:
                out[:, hit] = block.mean[k0:k1][:, at[hit]]
            else:
                count = block.count[at[hit]]
                total[:, hit] += block.mean[k0:k1][:, at[hit]].astype(np.float64) * count
                weight[hit] += count
        if total is not None:
            seen = weight > 0
            out[:, seen] = total[:, seen] / weight[seen]
        return out

    def coverage(self) -> np.ndarray:
        """Traces contributing to each cell, shaped (ny, nx).

        Built on each call rather than cached: a cache would hold 4 bytes
        per frame cell that the memory estimate would then have to count
        (#113), and the scatter costs about a millisecond at a million cells.
        """
        out = np.zeros(self.frame.n_cells, dtype=np.int32)
        for block in self.blocks:
            out[block.cells] += block.count
        return out.reshape(self.frame.ny, self.frame.nx)
