"""Amplitude-to-colour mapping for front ends. numpy only.

Display gain is not a processing step. Clip percentile, colour range, and
colormap alter how amplitude maps to colour, not the data, so dragging them
remaps a lookup table and repaints with no recomputation, and none of it is
recorded in a stack. Front ends wrap the byte arrays produced here in their
own image type (QImage, PIL, ...) and do nothing else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

DEFAULT_COLORMAP = "grey_black_high"


class Normalizer(Protocol):
    """Chooses the symmetric amplitude limit that maps to the ends of the
    colour table. Bipolar data is always mapped symmetrically about zero."""

    def limit(self, data: np.ndarray) -> float: ...


@dataclass(frozen=True)
class PercentileClip:
    """Limit = the given percentile of |data|.

    Above `max_samples` values, a strided subsample is used. On a 512 x 6301
    radargram the full percentile costs about 120 ms; the subsample keeps a
    display-gain drag interactive and is deterministic for a given array.
    """

    percentile: float = 99.0
    max_samples: int = 200_000

    def __post_init__(self) -> None:
        if not 0.0 < self.percentile <= 100.0:
            raise ValueError(f"percentile must be in (0, 100], got {self.percentile}")
        if self.max_samples < 1:
            raise ValueError(f"max_samples must be >= 1, got {self.max_samples}")

    def limit(self, data: np.ndarray) -> float:
        flat = np.asarray(data, dtype=float).ravel()
        if flat.size > self.max_samples:
            flat = flat[:: int(math.ceil(flat.size / self.max_samples))]
        if flat.size == 0:
            return 1.0
        lim = float(np.percentile(np.abs(flat), self.percentile))
        return lim if lim > 0.0 else 1.0


@dataclass(frozen=True)
class FixedRange:
    """A user-chosen limit. Drop-in for PercentileClip."""

    limit_value: float

    def __post_init__(self) -> None:
        if not self.limit_value > 0.0:
            raise ValueError(f"limit_value must be positive, got {self.limit_value}")

    def limit(self, data: np.ndarray) -> float:
        return float(self.limit_value)


def _grey(black_high: bool) -> np.ndarray:
    ramp = np.linspace(255.0, 0.0, 256) if black_high else np.linspace(0.0, 255.0, 256)
    g = np.round(ramp).astype(np.uint8)
    return np.stack([g, g, g], axis=1)


def _seismic() -> np.ndarray:
    """Blue for negative, white at zero, red for positive.

    Built from two linear segments meeting at index 128 rather than one
    `linspace(-1, 1, 256)`: with an even-sized table the single-ramp
    midpoint falls at index 127.5, not on an integer index, so no entry is
    exactly zero and the "white at zero" entry rounds to off-white. Index
    128 is where `to_index8` places a zero amplitude, so the table's zero
    must sit there exactly.
    """
    neg = np.linspace(-1.0, 0.0, 129)  # indices 0..128
    pos = np.linspace(0.0, 1.0, 128)[1:]  # indices 129..255
    t = np.concatenate([neg, pos])
    r = np.where(t < 0, 1.0 + t, 1.0)
    g = 1.0 - np.abs(t)
    b = np.where(t > 0, 1.0 - t, 1.0)
    return np.round(np.stack([r, g, b], axis=1) * 255.0).astype(np.uint8)


_COLORMAPS: dict[str, np.ndarray] = {
    "grey_black_high": _grey(black_high=True),
    "grey_white_high": _grey(black_high=False),
    "seismic": _seismic(),
}


def colormap_names() -> list[str]:
    return list(_COLORMAPS)


def colormap(name: str) -> np.ndarray:
    """A (256, 3) uint8 lookup table. Returns a copy."""
    try:
        return _COLORMAPS[name].copy()
    except KeyError:
        raise KeyError(f"unknown colormap {name!r}; available: {colormap_names()}") from None


def to_index8(data: np.ndarray, limit: float) -> np.ndarray:
    """Map amplitudes to 0..255 with -limit -> 0, 0 -> 128, +limit -> 255."""
    if not limit > 0.0:
        raise ValueError(f"limit must be positive, got {limit}")
    scaled = (np.asarray(data, dtype=float) / limit + 1.0) * 127.5
    return np.round(np.clip(scaled, 0.0, 255.0)).astype(np.uint8)


def to_rgb8(data: np.ndarray, limit: float, lut: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8, C-contiguous, ready to wrap as an RGB888 image."""
    lut = np.asarray(lut)
    if lut.shape != (256, 3) or lut.dtype != np.uint8:
        raise ValueError(f"lut must be a (256, 3) uint8 table, got {lut.shape} {lut.dtype}")
    return np.ascontiguousarray(lut[to_index8(data, limit)])


def decimate_columns(data: np.ndarray, max_width: int) -> np.ndarray:
    """Block-mean along the trace axis until there are at most `max_width`
    columns. Happens after processing, never before, so the view is a
    downsampled real result. Returns `data` itself when already narrow."""
    if max_width < 1:
        raise ValueError(f"max_width must be >= 1, got {max_width}")
    n = data.shape[1]
    if n <= max_width:
        return data
    block = int(math.ceil(n / max_width))
    n_blocks = int(math.ceil(n / block))
    padded = np.full((data.shape[0], n_blocks * block), np.nan)
    padded[:, :n] = data
    return np.nanmean(padded.reshape(data.shape[0], n_blocks, block), axis=2)
