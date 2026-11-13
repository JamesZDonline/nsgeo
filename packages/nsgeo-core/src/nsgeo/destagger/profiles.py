"""Along-line profiles of the binned envelope, and their lagged comparison with neighbours.

The method is the 2026-11-11 spike's. Every trace is placed on a common along
axis at `STEP_M`; each time bin is divided by its median over the lines (a time
gain, so deep bins count as much as shallow ones), low-passed to drop trace
noise and high-passed to drop slow trends, and zeroed near each line's own
ends, where the radar is bright in every window. Each pair of neighbouring
lines walked in opposite directions is then compared by FFT over a range of
lags; a line's comparison with the mean of its two neighbours is the mean of
its two pair curves (correlation is linear).

Pair curves are kept per time bin and for each half along the axis, so the
per-line step can measure a line from independent halves, and re-measure it
after its neighbours are corrected by shifting the curves instead of
recomputing the profiles. Lines are visited in offset order and only two
lines' transforms are held at once. What is kept grows with the grid, but
slowly: n_bins x (6 x search range + 1) values per pair of lines (about 5 MB
for Nashville Grid 1's 60 lines, about 30 MB for 200 lines of 50 m), against
every line's whole transform before.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
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
) -> tuple[np.ndarray, np.ndarray]:
    """One line's profiles (len(window), len(axis)) and its valid mask over `axis`.

    `data` is the line's (n_bins, n_traces) envelope, `along` its trace positions, `gain`
    the per-bin median, `window` the bin indices used. The valid part leaves out the
    line's own ends. Each bin is resampled, low-passed and high-passed; the valid part is
    then normalised jointly over all bins, and zero outside it.
    """
    order = np.argsort(along, kind="stable")
    a = along[order]
    valid = (axis >= a[0] + END_TRIM_M) & (axis <= a[-1] - END_TRIM_M)
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


#: How far a pair's curve is kept, in multiples of the search range: the per-line step
#: shifts a pair by the grid value and by both lines' own values, each within the range.
PAIR_LAG_FACTOR = 3


@dataclass(frozen=True, eq=False)
class PairCurves:
    """Lag curves of each pair of neighbouring opposite-direction lines.

    `by_bin[(a, b)]` is (n_bins, 2 * lags + 1): line a's match with line b in each time bin
    when a is shifted by -lags..+lags steps along the axis (grid coordinates, not a line's
    own travel), divided by the axis length `n_axis` as the grid value always was.
    `halves[(a, b)]` is (2, 2 * lags + 1), summed over bins, for the first and the second
    half of the axis. `a` comes before `b` in offset order. `energy` (n_lines, n_bins) and
    `half_energy` (n_lines, 2) are each line's energy on the same scale, so a curve over
    sqrt(energy_a * energy_b) is a correlation coefficient: 1 for a perfect match whatever
    the lines' lengths or the part of them compared. Equality is identity: it holds arrays.
    """

    lags: int
    n_axis: int
    by_bin: dict[tuple[int, int], np.ndarray]
    halves: dict[tuple[int, int], np.ndarray]
    energy: np.ndarray
    half_energy: np.ndarray

    def raw(self, a: int, b: int, bins: slice = slice(None)) -> np.ndarray:
        """a's curve against b, summed over `bins`, as a's shift along the axis."""
        if (a, b) in self.by_bin:
            return self.by_bin[(a, b)][bins].sum(axis=0)
        return self.by_bin[(b, a)][bins].sum(axis=0)[::-1]

    def normalised(
        self, a: int, b: int, bins: slice | None = None, half: int | None = None
    ) -> np.ndarray:
        """a's curve against b as a correlation coefficient, over `bins` (all by default) or
        one `half` along the axis (0 first, 1 second; halves always use every bin)."""
        if bins is not None and half is not None:
            raise ValueError("give bins or a half along the axis, not both")
        if half is None:
            bins = slice(None) if bins is None else bins
            curve = self.raw(a, b, bins)
            scale = float(self.energy[a, bins].sum() * self.energy[b, bins].sum())
        else:
            forward = (a, b) in self.halves
            curve = self.halves[(a, b) if forward else (b, a)][half]
            curve = curve if forward else curve[::-1]
            scale = float(self.half_energy[a, half] * self.half_energy[b, half])
        return curve / np.sqrt(scale) if scale > 0 else np.zeros_like(curve)


def pair_curves(
    datas: Sequence[np.ndarray],
    alongs: Sequence[np.ndarray],
    axis: np.ndarray,
    gain: np.ndarray,
    window: np.ndarray,
    order: Sequence[int],
    directions: Sequence[int],
    lags: int,
    check: Callable[[], None] = lambda: None,
) -> PairCurves:
    """Profile every line and compare each with the next in `order` when it runs the other way.

    `datas[k]` is line k's (n_bins, n_traces) envelope and `alongs[k]` its trace positions;
    `gain` and `window` are as for `line_profiles`. Lines are visited in `order` (by offset),
    so only the previous line's transforms are held. `check` is called once per line.
    """
    n = axis.size
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    mid = 0.5 * (axis[0] + axis[-1])
    masks = (axis <= mid, axis > mid)
    by_bin: dict[tuple[int, int], np.ndarray] = {}
    halves: dict[tuple[int, int], np.ndarray] = {}
    energy = np.zeros((len(datas), window.size))
    half_energy = np.zeros((len(datas), 2))

    def crop(x: np.ndarray) -> np.ndarray:
        return np.concatenate([x[..., -lags:], x[..., : lags + 1]], axis=-1) / n

    previous: tuple[int, list[np.ndarray]] | None = None
    for k in order:
        check()
        f, _ = line_profiles(datas[k], alongs[k], axis, gain, window)
        energy[k] = (f * f).sum(axis=1) / n
        half_energy[k] = [(f[:, mask] ** 2).sum() / n for mask in masks]
        ffts = [np.fft.rfft(f, nfft, axis=-1)]
        ffts += [np.fft.rfft(f * mask, nfft, axis=-1) for mask in masks]
        if previous is not None and directions[previous[0]] != directions[k]:
            a, mine = previous
            by_bin[(a, k)] = crop(np.fft.irfft(mine[0] * np.conj(ffts[0]), nfft, axis=-1))
            halves[(a, k)] = np.array(
                [crop(np.fft.irfft((mine[i] * np.conj(ffts[i])).sum(axis=0), nfft)) for i in (1, 2)]
            )
        previous = (k, ffts)
    return PairCurves(lags, n, by_bin, halves, energy, half_energy)


def line_curves(
    pairs: PairCurves,
    neighbours: dict[int, list[int]],
    directions: Sequence[int],
    max_lag: int,
    check: Callable[[], None] = lambda: None,
) -> tuple[np.ndarray, np.ndarray]:
    """Each line's curve against the mean of its neighbours, over -max_lag..+max_lag steps.

    Returned twice, (n_lines, n_lags) each: unnormalised, as the grid value is measured,
    and as correlation coefficients. One row per line in `neighbours`, in index order. The
    curve reads as a shift of the line in its own direction of travel: the lag axis is
    reversed for direction -1, so both directions add up instead of cancelling. `check`
    is called once per line.
    """
    centre = slice(pairs.lags - max_lag, pairs.lags + max_lag + 1)
    raw: list[np.ndarray] = []
    normalised: list[np.ndarray] = []
    for k in sorted(neighbours):
        check()
        for rows, curve in ((raw, pairs.raw), (normalised, pairs.normalised)):
            c = np.mean([curve(k, j) for j in neighbours[k]], axis=0)[centre]
            rows.append(c[::-1] if directions[k] < 0 else c)
    return np.array(raw), np.array(normalised)


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
#: The peak must be at least this correlation coefficient. On Nashville, unrelated lines
#: (Grid 1 and Grid 2 alternating) give a grid curve peaking at 0.04 to 0.05, and the real
#: grids 0.27 to 0.43; one line against its neighbours peaks at 0.1 to 0.8 when it matches.
MIN_CORRELATION = 0.10


def is_clear(
    curve: np.ndarray, min_correlation: float = MIN_CORRELATION, ratio: float = CLEAR_RATIO
) -> bool:
    """The peak is clear: not at either end, strong enough, and well above every other maximum.

    `curve` is a correlation coefficient (`PairCurves.normalised`). Other maxima within
    `SHOULDER_M` of the peak are its own shoulder and are ignored; the highest of the rest
    must be at most `ratio` of the peak. This guards against locking onto repeating
    features such as rows of graves (C10). The height test catches lines that share no
    features: their curve is a low hump with no rival maximum, so shape alone cannot
    reject it.
    """
    i = int(np.argmax(curve))
    if i == 0 or i == curve.size - 1 or curve[i] < min_correlation:
        return False
    inner = curve[1:-1]
    maxima = np.flatnonzero((inner > curve[:-2]) & (inner >= curve[2:])) + 1
    far = maxima[np.abs(maxima - i) * STEP_M > SHOULDER_M]
    return not (far.size and curve[far].max() > ratio * curve[i])


@dataclass(frozen=True)
class AxisPeak:
    """A grid value's lag peak with its bootstrap spread, in metres of destagger."""

    destagger: float
    spread_m: float
    clear: bool


def grid_peak(curves: np.ndarray, normalised: np.ndarray, boot: int, seed: int = 0) -> AxisPeak:
    """The grid value from per-line curves (n_lines, n_lags): the peak of their mean.

    destagger = -lag / 2, since opposite lines each move half their disagreement.
    `spread_m` is half the width of the 95% interval over `boot` resamplings of the lines.
    Whether the peak is clear is judged on the mean of `normalised`, the same curves as
    correlation coefficients.
    """
    lag, _ = peak(curves.mean(axis=0))
    rng = np.random.default_rng(seed)
    n = curves.shape[0]
    shifts = [peak(curves[rng.integers(0, n, n)].mean(axis=0))[0] for _ in range(boot)]
    lo, hi = np.percentile(shifts, [2.5, 97.5])
    return AxisPeak(-lag * STEP_M / 2, (hi - lo) * STEP_M / 4, is_clear(normalised.mean(axis=0)))
