"""Shared numpy helpers. numpy only: scipy is never imported at module level."""

from __future__ import annotations

import numpy as np


def running_mean(a: np.ndarray, window: int, axis: int = 0) -> np.ndarray:
    """Centred running mean with a shrinking window at the edges.

    Implemented with cumsum so it is O(n) rather than O(n * window), which is
    what makes dewow and sliding background removal fast enough to feel
    interactive without scipy.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    a = np.asarray(a, dtype=float)
    if window == 1:
        return a.copy()

    n = a.shape[axis]
    w = min(window, n)
    pad_shape = list(a.shape)
    pad_shape[axis] = 1
    cs = np.concatenate([np.zeros(pad_shape), np.cumsum(a, axis=axis)], axis=axis)

    idx = np.arange(n)
    half = w // 2
    lo = np.clip(idx - half, 0, n)
    hi = np.clip(idx - half + w, 0, n)
    counts = (hi - lo).astype(float)

    shape = [1] * a.ndim
    shape[axis] = n
    totals = np.take(cs, hi, axis=axis) - np.take(cs, lo, axis=axis)
    return totals / counts.reshape(shape)
