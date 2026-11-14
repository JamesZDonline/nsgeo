"""Shared numpy helpers. numpy only: scipy is never imported at module level."""

from __future__ import annotations

import numpy as np


def running_mean(a: np.ndarray, window: int, axis: int = 0) -> np.ndarray:
    """Centred running mean of the finite samples, with a shrinking window at the edges.

    Output `i` averages the finite samples in `[i - w // 2, i - w // 2 + w)`,
    clipped to the axis, where `w` is `window` capped at the axis length. NaN
    and inf are left out of every window, so in dewow, AGC and sliding
    background a bad sample damages only itself (#43); a window with no finite
    sample is NaN. `window == 1` returns a copy, bad samples included.

    O(n) from cumulative sums, which is what keeps dewow and sliding background
    interactive without scipy. See `_window_sums` for how they stay accurate.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    a = np.asarray(a, dtype=float)
    if window == 1:
        return a.copy()
    if axis < 0:
        axis += a.ndim
    n = a.shape[axis]
    if n == 0:
        return a.copy()
    w = min(window, n)
    half = w // 2

    # Zero padding on both sides makes every window `w` long, so window `i` is
    # `padded[i : i + w]` and the shrinking edges need no special case: the
    # part of a window past either end sums zeros, and is not counted.
    padded_shape = list(a.shape)
    padded_shape[axis] = n + w - 1
    padded = np.zeros(padded_shape)
    inner = _along(axis, a.ndim, slice(half, half + n))

    # A finite total means every sample is finite: one NaN or inf anywhere
    # makes it NaN or inf. (Finite data that overflows the total takes the
    # slow path below, which is still right.)
    with np.errstate(invalid="ignore", over="ignore"):
        clean = bool(np.isfinite(np.sum(a)))
    if clean:
        padded[inner] = a
        i = np.arange(n)
        count = np.minimum(i - half + w, n) - np.maximum(i - half, 0)
        shape = [1] * a.ndim
        shape[axis] = n
        counts = count.reshape(shape).astype(float)
    else:
        finite = np.isfinite(a)
        np.copyto(padded[inner], a, where=finite)
        good = np.zeros(padded_shape, dtype=np.int64)
        good[inner] = finite
        cumulative = np.zeros(_grown(padded_shape, axis), dtype=np.int64)
        np.cumsum(good, axis=axis, out=cumulative[_along(axis, a.ndim, slice(1, None))])
        counts = _differences(cumulative, w, n, axis).astype(float)

    sums = _window_sums(padded, w, n, axis)
    with np.errstate(invalid="ignore", divide="ignore"):
        # 0 / 0 where a window holds no finite sample: NaN, as documented.
        np.divide(sums, counts, out=sums)
    return sums


def _window_sums(padded: np.ndarray, w: int, n: int, axis: int) -> np.ndarray:
    """`out[i] = padded[i : i + w].sum()` along `axis`, for `i` in `range(n)`.

    A plain cumulative sum loses every digit a window shares with the running
    total: after a 1e12 sample, later windows of ordinary values came out of a
    difference of two numbers near 1e12 and kept about four significant
    figures, which is what let AGC exceed its own cap. So the rounding error of
    each addition is recovered exactly (Knuth's two-sum: the cumulative sum
    computes each total as `fl(previous + x)`, and what that rounding dropped is
    itself a float) and accumulated alongside. Differencing both gives each
    window's sum to rounding relative to that window, not to everything before
    it on the axis. It costs a few extra passes over the data, no more.
    """
    ndim = padded.ndim
    after = _along(axis, ndim, slice(1, None))
    total = np.zeros(_grown(padded.shape, axis))
    np.cumsum(padded, axis=axis, out=total[after])
    new = total[after]
    old = total[_along(axis, ndim, slice(None, -1))]

    # Two-sum, in two buffers: `virtual` is new - old, then reused for the
    # cumulative sum of what was lost, which needs a leading zero of its own.
    spare = np.empty_like(total)
    spare[_along(axis, ndim, slice(0, 1))] = 0.0
    virtual = spare[after]
    np.subtract(new, old, out=virtual)
    lost = padded - virtual
    np.subtract(new, virtual, out=virtual)
    np.subtract(old, virtual, out=virtual)
    lost += virtual
    lost_total = spare
    np.cumsum(lost, axis=axis, out=lost_total[after])

    sums = _differences(total, w, n, axis)
    window = _along(axis, ndim, slice(0, n))
    np.subtract(
        lost_total[_along(axis, ndim, slice(w, w + n))], lost_total[window], out=lost[window]
    )
    sums += lost[window]
    return sums


def _differences(cumulative: np.ndarray, w: int, n: int, axis: int) -> np.ndarray:
    """`cumulative[i + w] - cumulative[i]` along `axis`, for `i` in `range(n)`."""
    ndim = cumulative.ndim
    ends = cumulative[_along(axis, ndim, slice(w, w + n))]
    starts = cumulative[_along(axis, ndim, slice(0, n))]
    return ends - starts


def _along(axis: int, ndim: int, s: slice) -> tuple[slice, ...]:
    index = [slice(None)] * ndim
    index[axis] = s
    return tuple(index)


def _grown(shape: list[int] | tuple[int, ...], axis: int) -> list[int]:
    """`shape` one longer along `axis`: room for a cumulative sum's leading zero."""
    grown = list(shape)
    grown[axis] += 1
    return grown


def refuse_non_finite(data: np.ndarray, consequence: str) -> None:
    """Raise `ValueError` when any sample of `data` (samples x traces) is NaN or inf.

    For the steps that cannot keep a bad sample to itself: a transform spreads
    it along the trace or across the image, and a decomposition cannot run on
    it. They refuse, naming how many traces (columns) hold one, rather than
    return a line of NaN. `consequence` says which of those this step does.
    """
    finite = np.isfinite(data)
    if finite.all():
        return
    bad = int(np.count_nonzero(~finite.all(axis=0)))
    raise ValueError(
        f"{bad} of {data.shape[1]} traces hold samples that are not finite; {consequence}"
    )
