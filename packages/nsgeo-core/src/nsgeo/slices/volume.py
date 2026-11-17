"""The prepared volume: a slice cube turned into one body per reflection (M16 spec §2.1, §5.1).

A cube of squared amplitude shows each reflection as two or three thin layers,
one per half-cycle of the wavelet. This module fills every level as the Slices
panel does, takes the RMS over one wave period down each column, blurs a little
sideways, resamples to a uniform depth axis and balances against a smooth
depth trend. The result reads as one hump per reflection.

`fill_levels` is the slow part and writes into a caller-owned array (a
memmap works). `prepare_volume` then makes one pass for the depth trend;
`PreparedVolume.slab` recomputes any depth range on demand, so no second full
copy of the cube is ever held.

numpy only.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from nsgeo.slices.cube import SliceCube
from nsgeo.slices.finish import FinishSettings, finish_slice
from nsgeo.slices.frame import ZAxis
from nsgeo.slices.interpolate import SliceFill
from nsgeo.slices.smooth import smooth
from nsgeo.velocity import VelocityModel

SQUARED_TRANSFORM = "amp_square"
_SNAP = 1e-6


class VolumeStopped(Exception):
    """The progress callback asked for the preparation to stop."""


def _positive(x: float) -> bool:
    return math.isfinite(x) and x > 0.0


def _non_negative(x: float) -> bool:
    return math.isfinite(x) and x >= 0.0


@dataclass(frozen=True)
class VolumeSettings:
    """How the volume is prepared: the RMS window, the sideways blur, the trend window."""

    period_ns: float = 2.5
    blur_m: float = 0.1
    trend_m: float = 0.15

    def __post_init__(self) -> None:
        if not _positive(self.period_ns):
            raise ValueError(f"period_ns must be finite and > 0, got {self.period_ns}")
        if not _non_negative(self.blur_m):
            raise ValueError(f"blur_m must be finite and >= 0, got {self.blur_m}")
        if not _positive(self.trend_m):
            raise ValueError(f"trend_m must be finite and > 0, got {self.trend_m}")

    def to_dict(self) -> dict[str, float]:
        return {"period_ns": self.period_ns, "blur_m": self.blur_m, "trend_m": self.trend_m}

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> VolumeSettings:
        """Valid fields of `doc` laid over the defaults; anything else is ignored."""
        checks = {"period_ns": _positive, "blur_m": _non_negative, "trend_m": _positive}
        fields: dict[str, float] = {}
        for name, valid in checks.items():
            try:
                value = float(doc[name])
            except (KeyError, TypeError, ValueError):
                continue
            if valid(value):
                fields[name] = value
        return cls(**fields)


def fill_levels(
    cube: SliceCube,
    weights: SliceFill,
    finish: FinishSettings,
    out: np.ndarray,
    *,
    progress: Callable[[int, int], bool] | None = None,
) -> None:
    """Fill every level as the Slices panel does and write squared amplitude into `out`.

    `out` is `(nz, ny, nx)`, float32 (an `open_memmap` will do). A cube whose
    transform is already `amp_square` goes in as it is; any other is squared
    after the fill. Cells nothing reaches stay NaN. `progress(k + 1, nz)`
    returning False raises `VolumeStopped`.
    """
    nz, ny, nx = cube.z.nz, cube.frame.ny, cube.frame.nx
    if out.shape != (nz, ny, nx):
        raise ValueError(f"out must be {(nz, ny, nx)}, got {out.shape}")
    squared = cube.provenance.transform == SQUARED_TRANSFORM
    for k in range(nz):
        level = finish_slice(cube.level(k), weights, cube.frame.cell, finish)
        if not squared:
            level = level * level
        out[k] = level
        if progress is not None and not progress(k + 1, nz):
            raise VolumeStopped(f"stopped after {k + 1} of {nz} levels")


def depth_axis(z: ZAxis, velocity: VelocityModel) -> tuple[np.ndarray, np.ndarray]:
    """`(depths_m, source_level)`: a uniform depth axis, shallow first, and where each depth sits.

    The axis keeps as many levels as the cube has from time zero on, and
    spreads them evenly from the first such level's depth to the last one's.
    A constant velocity gives whole source levels; any value within 1e-6 of a
    whole level is snapped to it, so nothing is blended there.
    """
    times = z.times_ns()
    first = int(np.argmax(times >= -1e-9)) if np.any(times >= -1e-9) else -1
    if first < 0:
        raise ValueError("the cube has no level at or after time zero")
    levels = np.arange(first, z.nz, dtype=float)
    source_depths = velocity.depth_at(times[first:])
    depths = np.linspace(source_depths[0], source_depths[-1], levels.size)
    source = np.interp(depths, source_depths, levels)
    nearest = np.round(source)
    source = np.where(np.abs(source - nearest) < _SNAP, nearest, source)
    return depths, source


def _rms_levels(
    filled: np.ndarray, covered: np.ndarray, w: int, a: int, b: int, nz: int
) -> np.ndarray:
    """RMS over `w` levels centred on each source level `a..b` (inclusive), float64.

    The window of level `i` is `i - w // 2 .. i + w - w // 2 - 1`, padded with
    the edge level past either end of the cube. The window is summed level by
    level, not from a running total, so a level's value never depends on
    which slab it was computed in.
    """
    before, after = w // 2, w - w // 2 - 1
    n = b - a + 1
    lo, hi = max(0, a - before), min(nz - 1, b + after)
    ext = np.asarray(filled[lo : hi + 1], dtype=np.float64)
    pad_front, pad_back = lo - (a - before), (b + after) - hi
    if pad_front or pad_back:
        ext = np.pad(ext, ((pad_front, pad_back), (0, 0), (0, 0)), mode="edge")
    ext[:, ~covered] = 0.0
    total = np.zeros((n,) + ext.shape[1:], dtype=np.float64)
    for offset in range(w):
        total += ext[offset : offset + n]
    rms = np.sqrt(np.maximum(total / w, 0.0))
    rms[:, ~covered] = np.nan
    return rms


@dataclass(frozen=True)
class PreparedVolume:
    """The depth trend and the geometry; `slab` builds amplitude and strength on demand."""

    depths_m: np.ndarray
    trend: np.ndarray
    covered: np.ndarray
    settings: VolumeSettings
    filled: np.ndarray = field(repr=False, compare=False)
    source_level: np.ndarray = field(repr=False, compare=False)
    cell: float = field(repr=False, compare=False)
    window: int = field(repr=False, compare=False)

    def _amplitude(self, j0: int, j1: int) -> np.ndarray:
        src = self.source_level[j0:j1]
        low = np.floor(src).astype(int)
        frac = src - low
        high = np.where(frac > 0.0, low + 1, low)
        nz = self.filled.shape[0]
        a, b = int(low.min()), int(high.max())
        rms = _rms_levels(self.filled, self.covered, self.window, a, b, nz)
        blur = self.settings.blur_m
        for i in range(rms.shape[0]):
            rms[i] = smooth(rms[i], self.cell, blur, blur)
        out = np.empty((j1 - j0,) + rms.shape[1:], dtype=np.float32)
        for j in range(j1 - j0):
            lo = rms[low[j] - a]
            out[j] = lo if frac[j] == 0.0 else (1.0 - frac[j]) * lo + frac[j] * rms[low[j] + 1 - a]
        return out

    def swing(self, j0: int, j1: int) -> np.ndarray:
        """The filled squared amplitude on the depth axis, levels `j0..j1`, float32.

        `(j1 - j0, ny, nx)`. It is read between source levels as `slab` reads
        them, but straight from `filled`: no RMS over a wave period and no
        blur, so each reflection keeps its separate half-cycles. NaN off
        `covered`.
        """
        nd = self.depths_m.size
        if not 0 <= j0 < j1 <= nd:
            raise ValueError(f"swing must satisfy 0 <= j0 < j1 <= {nd}, got {j0}, {j1}")
        src = self.source_level[j0:j1]
        low = np.floor(src).astype(int)
        frac = src - low
        out = np.empty((j1 - j0,) + self.covered.shape, dtype=np.float32)
        for j in range(j1 - j0):
            level = np.asarray(self.filled[low[j]], dtype=np.float64)
            if frac[j] != 0.0:
                level = (1.0 - frac[j]) * level + frac[j] * np.asarray(
                    self.filled[low[j] + 1], dtype=np.float64
                )
            out[j] = level
        out[:, ~self.covered] = np.nan
        return out

    def slab(self, j0: int, j1: int) -> tuple[np.ndarray, np.ndarray]:
        """`(amplitude, strength)` for depth levels `j0..j1`, each `(j1 - j0, ny, nx)` float32.

        Strength is amplitude over the depth trend, so it is about one at
        every depth. Both are NaN off `covered`.
        """
        nd = self.depths_m.size
        if not 0 <= j0 < j1 <= nd:
            raise ValueError(f"slab must satisfy 0 <= j0 < j1 <= {nd}, got {j0}, {j1}")
        amplitude = self._amplitude(j0, j1)
        trend = self.trend[j0:j1]
        usable = trend > 0.0
        scale = np.where(usable, 1.0 / np.where(usable, trend, 1.0), np.nan)
        strength = (amplitude * scale[:, None, None]).astype(np.float32)
        return amplitude, strength


def prepare_volume(
    filled: np.ndarray,
    z: ZAxis,
    velocity: VelocityModel,
    cell: float,
    settings: VolumeSettings,
    *,
    slab_levels: int = 64,
    progress: Callable[[int, int], bool] | None = None,
) -> PreparedVolume:
    """Make the one pass that finds the depth trend; the amplitude itself is not kept.

    `filled` is what `fill_levels` wrote: squared amplitude, `(nz, ny, nx)`.
    `progress(done, total)` is called once per slab of the pass; returning
    False raises `VolumeStopped`.
    """
    if filled.ndim != 3 or filled.shape[0] != z.nz:
        raise ValueError(f"filled must be ({z.nz}, ny, nx), got {filled.shape}")
    if slab_levels < 1:
        raise ValueError(f"slab_levels must be >= 1, got {slab_levels}")
    depths, source = depth_axis(z, velocity)
    nd = depths.size
    first = int(round(float(source[0])))
    covered = np.isfinite(filled[first])
    if not covered.any():
        raise ValueError("nothing is covered: the volume would be empty")
    window = max(1, int(round(settings.period_ns / z.dz_ns)))
    vol = PreparedVolume(
        depths_m=depths,
        trend=np.ones(nd),
        covered=covered,
        settings=settings,
        filled=filled,
        source_level=source,
        cell=cell,
        window=window,
    )
    median = np.empty(nd)
    starts = range(0, nd, slab_levels)
    for done, j0 in enumerate(starts, start=1):
        j1 = min(j0 + slab_levels, nd)
        amp = vol._amplitude(j0, j1)
        median[j0:j1] = np.median(amp[:, covered], axis=1)
        if progress is not None and not progress(done, len(starts)):
            raise VolumeStopped(f"stopped after {done} of {len(starts)} slabs")
    step = float(depths[1] - depths[0]) if nd > 1 else 1.0
    tw = max(1, int(round(settings.trend_m / step))) if step > 0.0 else 1
    padded = np.pad(median, tw // 2, mode="edge")
    trend = np.convolve(padded, np.ones(tw) / tw, mode="valid")[:nd]
    return replace(vol, trend=trend)
