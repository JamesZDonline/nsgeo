"""Along-line profiles of the binned envelope, and their lagged comparison with neighbours.

The method is the 2026-11-11 spike's. Every trace is placed on a common along
axis at `STEP_M`; each time bin is divided by its median over the lines (a time
gain, so deep bins count as much as shallow ones), low-passed to drop trace
noise and high-passed to drop slow trends, and zeroed near each line's own
ends, where the radar is bright in every window. Each line is then compared
with the mean of its opposite-direction neighbours, by FFT, over a range of
lags.

The functions work on any subset of time bins and any range along the axis, so
the per-line step can measure the same line from independent halves.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from nsgeo.destagger.prepare import EnvelopeBins

STEP_M = 0.02
LOWPASS_M = 0.15
HIGHPASS_M = 3.0
END_TRIM_M = 2.0
MIN_SEARCH_M = 1.0
SEARCH_FRACTION = 0.03
T_START_NS = 4.0
#: The window ends at the last bin whose median envelope stands this far above the noise floor.
NOISE_FLOOR_RATIO = 1.25
#: A window needs at least this many bins to be measured at all.
MIN_WINDOW_BINS = 8
#: The noise floor is the median of this many bins at the end of the record.
FLOOR_BINS = 8


def search_range_m(longest_m: float) -> float:
    """Neighbour-lag search half-width: max(MIN_SEARCH_M, SEARCH_FRACTION * longest_m) (C12)."""
    return max(MIN_SEARCH_M, SEARCH_FRACTION * longest_m)


def time_window(t_ns: np.ndarray, medians: np.ndarray) -> np.ndarray:
    """Indices of the bins to measure: after `T_START_NS`, up to the noise floor.

    The direct wave is skipped by time. The end is where the median envelope over
    the lines falls to `NOISE_FLOOR_RATIO` times the floor, the median of the last
    `FLOOR_BINS` bins: deeper bins carry only noise, which would dilute the match.
    A record too short or too quiet to leave `MIN_WINDOW_BINS` uses everything
    after `T_START_NS`.
    """
    after = np.flatnonzero(t_ns > T_START_NS)
    floor = float(np.median(medians[-FLOOR_BINS:]))
    above = np.flatnonzero(medians > NOISE_FLOOR_RATIO * floor)
    end = int(above.max()) if above.size else -1
    window = after[after <= end]
    return window if window.size >= MIN_WINDOW_BINS else after


def bin_medians(bins: Sequence[EnvelopeBins]) -> np.ndarray:
    """Per bin, the median envelope over every trace of every line."""
    n = min(b.data.shape[0] for b in bins)
    return np.array([np.median(np.concatenate([b.data[j] for b in bins])) for j in range(n)])


def along_axis(alongs: Sequence[np.ndarray]) -> np.ndarray:
    """The common along axis: every `STEP_M` from the smallest to the largest position."""
    lo = min(float(a.min()) for a in alongs)
    hi = max(float(a.max()) for a in alongs)
    return lo + STEP_M * np.arange(int(np.floor((hi - lo) / STEP_M + 1e-9)) + 1)


def _moving_mean(x: np.ndarray, width: int) -> np.ndarray:
    """Mean of `width` samples along the last axis, edges repeated, same length as `x`."""
    pad = width // 2
    padded = np.pad(x, [(0, 0)] * (x.ndim - 1) + [(pad, pad)], mode="edge")
    c = np.concatenate([np.zeros(x.shape[:-1] + (1,)), np.cumsum(padded, axis=-1)], axis=-1)
    return ((c[..., width : width + x.shape[-1]] - c[..., : x.shape[-1]]) / width)[
        ..., : x.shape[-1]
    ]


def line_profiles(
    data: np.ndarray,
    along: np.ndarray,
    axis: np.ndarray,
    gain: np.ndarray,
    window: np.ndarray,
    along_range: tuple[float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """One line's profiles (len(window), len(axis)) and its valid mask over `axis`.

    `data` is the line's (n_bins, n_traces) envelope, `along` its trace positions, `gain`
    the per-bin median, `window` the bin indices used. `along_range` limits the valid
    part to part of the axis (a half of the line); the line's own ends are trimmed
    first. Each bin is resampled, low-passed and high-passed; the valid part is then
    normalised jointly over all bins, and zero outside it.
    """
    order = np.argsort(along, kind="stable")
    a = along[order]
    valid = (axis >= a[0] + END_TRIM_M) & (axis <= a[-1] - END_TRIM_M)
    if along_range is not None:
        valid &= (axis >= along_range[0]) & (axis <= along_range[1])
    sel = data[window][:, order].astype(float) / gain[window][:, None]
    f = np.array([np.interp(axis, a, row) for row in sel])
    lp = int(round(LOWPASS_M / STEP_M)) | 1
    hp = int(round(HIGHPASS_M / STEP_M))
    f = _moving_mean(f, lp)
    f = f - _moving_mean(f, hp)
    out = np.zeros_like(f)
    if valid.any():
        v = f[:, valid]
        sd = v.std()
        if sd > 0:
            out[:, valid] = (v - v.mean(axis=1, keepdims=True)) / sd
    return out, valid


def neighbour_indices(order: Sequence[int], directions: Sequence[int]) -> dict[int, list[int]]:
    """For each line (by position in `order`, sorted by offset) its opposite-direction neighbours.

    Lines with none are absent. `order` holds indices into `directions`.
    """
    out: dict[int, list[int]] = {}
    for pos, k in enumerate(order):
        nb = [
            order[q]
            for q in (pos - 1, pos + 1)
            if 0 <= q < len(order) and directions[order[q]] != directions[k]
        ]
        if nb:
            out[k] = nb
    return out


def lag_curves(
    profiles: np.ndarray,
    neighbours: dict[int, list[int]],
    directions: Sequence[int],
    max_lag: int,
) -> dict[int, np.ndarray]:
    """Per line, its lag curve against the mean of its neighbours, summed over bins.

    `profiles` is (n_lines, n_bins, n_along). The curve runs over lags -max_lag..+max_lag
    steps and reads as a shift of the line in its own direction of travel: the lag axis is
    reversed for direction -1, so both directions add up instead of cancelling. The sum
    over bins is taken before the inverse FFT (it is linear), so one transform per line.
    """
    n = profiles.shape[-1]
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    ffts: dict[int, np.ndarray] = {}

    def fft_of(j: int) -> np.ndarray:
        if j not in ffts:
            ffts[j] = np.fft.rfft(profiles[j], nfft, axis=-1)
        return ffts[j]

    out = {}
    for k, nb in neighbours.items():
        g = np.mean([fft_of(j) for j in nb], axis=0)
        x = np.fft.irfft((fft_of(k) * np.conj(g)).sum(axis=0), nfft)
        c = np.concatenate([x[-max_lag:], x[: max_lag + 1]]) / n
        out[k] = c[::-1] if directions[k] < 0 else c
    return out


def peak(curve: np.ndarray) -> tuple[float, float]:
    """The lag (steps, parabola-refined) and height of a curve's highest point."""
    max_lag = (curve.size - 1) // 2
    i = int(np.argmax(curve))
    if 0 < i < curve.size - 1:
        y0, y1, y2 = curve[i - 1], curve[i], curve[i + 1]
        den = y0 - 2 * y1 + y2
        return (i - max_lag) + (0.5 * (y0 - y2) / den if den else 0.0), float(y1)
    return float(i - max_lag), float(curve[i])


#: Peaks closer than this to the highest point are its own shoulder, not another match.
SHOULDER_M = 0.12
#: The highest other local maximum must be at most this fraction of the peak.
CLEAR_RATIO = 0.8


#: The peak must be at least this correlation per bin (profiles are normalised to unit variance
#: over their bins, so a perfect match sums to the bin count). Unrelated lines peak near 0.02
#: on Nashville; the real grids peak at 0.14 to 0.25.
MIN_CORRELATION = 0.08


def is_clear(curve: np.ndarray, n_bins: int, min_correlation: float = MIN_CORRELATION) -> bool:
    """The peak is clear: not at either end, strong enough, and well above every other maximum.

    `curve` is summed over `n_bins` bins. Other maxima within `SHOULDER_M` of the peak
    are its own shoulder and are ignored; the highest of the rest must be at most
    `CLEAR_RATIO` of the peak. This guards against locking onto repeating features such
    as rows of graves (C10). The height test catches lines that share no features: their
    curve is a low hump with no rival maximum, so shape alone cannot reject it.
    """
    i = int(np.argmax(curve))
    if i == 0 or i == curve.size - 1 or curve[i] < min_correlation * n_bins:
        return False
    inner = curve[1:-1]
    maxima = np.flatnonzero((inner > curve[:-2]) & (inner >= curve[2:])) + 1
    far = maxima[np.abs(maxima - i) * STEP_M > SHOULDER_M]
    return not (far.size and curve[far].max() > CLEAR_RATIO * curve[i])


@dataclass(frozen=True)
class AxisPeak:
    """A grid value's lag peak with its bootstrap spread, in metres of destagger."""

    destagger: float
    spread_m: float
    clear: bool


def grid_peak(curves: np.ndarray, n_bins: int, boot: int, seed: int = 0) -> AxisPeak:
    """The grid value from per-line curves (n_lines, n_lags), each summed over `n_bins` bins.

    It is the peak of their mean.

    destagger = -lag / 2, since opposite lines each move half their disagreement.
    `spread_m` is half the width of the 95% interval over `boot` resamplings of the lines.
    """
    mean = curves.mean(axis=0)
    lag, _ = peak(mean)
    rng = np.random.default_rng(seed)
    n = curves.shape[0]
    shifts = [peak(curves[rng.integers(0, n, n)].mean(axis=0))[0] for _ in range(boot)]
    lo, hi = np.percentile(shifts, [2.5, 97.5])
    return AxisPeak(-lag * STEP_M / 2, (hi - lo) * STEP_M / 4, is_clear(mean, n_bins))
