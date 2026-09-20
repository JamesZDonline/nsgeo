"""The stored product: a volume of means, and how much data is under each cell.

Layout is z-major, `(nz, n_cells)`, and that is measured rather than
assumed. Cell-major builds 3-15% faster because each cell's column is
contiguous, but z-major extracts a slice 7x faster -- and a slice is
extracted on every thickness and depth change, where a rebuild happens only
when dz or the cell size moves. Paying 15% on the rare operation makes the
constant one free.
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
class SliceCube:
    """Binned amplitude over a frame and a z axis.

    `mean` is NaN wherever `count` is zero. `count` is per cell rather than
    per (level, cell), which is exact only because the binner rejects any
    line whose time range does not span the whole axis -- so a cell is
    either covered at every level or at none. That is what lets
    `slice_levels` use a plain mean instead of nanmean.
    """

    frame: CubeFrame
    z: ZAxis
    mean: np.ndarray
    count: np.ndarray
    provenance: Provenance

    def __post_init__(self) -> None:
        expected = (self.z.nz, self.frame.n_cells)
        if self.mean.shape != expected:
            raise ValueError(f"mean must be {expected}, got {self.mean.shape}")
        if self.count.shape != (self.frame.n_cells,):
            raise ValueError(f"count must be ({self.frame.n_cells},), got {self.count.shape}")

    def slice_levels(self, k0: int, k1: int) -> np.ndarray:
        """Mean over the half-open level window, shaped (ny, nx).

        A plain mean, not nanmean: coverage does not vary with level, so a
        NaN column is NaN at every level and propagates correctly -- and
        nanmean over a mostly-empty slice costs far more.
        """
        if not 0 <= k0 < k1 <= self.z.nz:
            raise ValueError(
                f"level window must satisfy 0 <= k0 < k1 <= {self.z.nz}, got {k0}..{k1}"
            )
        flat = self.mean[k0:k1].mean(axis=0)
        return flat.reshape(self.frame.ny, self.frame.nx)

    def coverage(self) -> np.ndarray:
        """Traces contributing to each cell, shaped (ny, nx)."""
        return self.count.reshape(self.frame.ny, self.frame.nx)
