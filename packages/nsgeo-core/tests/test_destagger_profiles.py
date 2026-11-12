"""The profile and lag-curve helpers behind the destagger measurement (#159).

`is_clear` is tested on hand-made curves: it judges a curve's shape, so the
curves need only be the shape of real ones. The match strength is tested on a
real line paired with itself.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.destagger.profiles import (
    CLEAR_RATIO,
    MIN_CORRELATION,
    SHOULDER_M,
    STEP_M,
    PairCurves,
    along_axis,
    bin_medians,
    is_clear,
    pair_curves,
    time_window,
)

from tests.destagger_data import GRID1_LENGTH, lines_for, needs_grid1
from tests.real_data import GPS_LINES


@needs_grid1
def test_the_match_strength_does_not_depend_on_line_length():
    """A real line compared with itself matches perfectly over the whole record and over
    either half along it: strength is normalised by the lines' own energy, not by the
    axis length, so a half is not read as half as strong."""
    (ln,) = lines_for(GPS_LINES[:1], GRID1_LENGTH)
    along = ln.placement.distance_along(ln.bins.data.shape[1], ln.header)
    gain = bin_medians([ln.bins])
    window = time_window(ln.bins.t_ns, gain)
    data = ln.bins.data
    pc = pair_curves(
        [data, data], [along, along], along_axis([along]), gain, window, [0, 1], [1, -1], 10
    )
    for half in (None, 0, 1):
        curve = pc.normalised(0, 1, half=half)
        assert curve.max() == pytest.approx(1.0, abs=1e-9)
        assert int(np.argmax(curve)) == 10  # at zero lag


# --- is_clear on hand-made curves (normalised correlation) -----------------------------


def _curve(*bumps: tuple[float, float], width_m: float = 0.05) -> np.ndarray:
    """A lag curve over +-1 m, with Gaussian bumps of (lag m, height)."""
    lags = np.arange(-round(1.0 / STEP_M), round(1.0 / STEP_M) + 1) * STEP_M
    out = np.zeros(lags.size)
    for at, height in bumps:
        out += height * np.exp(-0.5 * ((lags - at) / width_m) ** 2)
    return out


def test_a_single_strong_peak_is_clear():
    assert is_clear(_curve((0.1, 0.5)))


def test_a_peak_at_either_end_of_the_range_is_not_clear():
    assert not is_clear(_curve((-1.0, 0.5)))
    assert not is_clear(_curve((1.0, 0.5)))


def test_a_weak_peak_is_not_clear():
    assert not is_clear(_curve((0.1, MIN_CORRELATION * 0.9)))
    assert is_clear(_curve((0.1, MIN_CORRELATION * 1.1)))


def test_a_rival_maximum_makes_a_peak_unclear():
    rival = CLEAR_RATIO * 0.5 * 1.05
    assert not is_clear(_curve((0.0, 0.5), (0.4, rival)))
    assert is_clear(_curve((0.0, 0.5), (0.4, CLEAR_RATIO * 0.5 * 0.9)))


def test_a_shoulder_beside_the_peak_is_not_a_rival():
    near = _curve((0.0, 0.5), (SHOULDER_M * 0.75, 0.45), width_m=0.015)
    far = _curve((0.0, 0.5), (SHOULDER_M * 1.5, 0.45), width_m=0.015)
    inner = near[1:-1]
    assert np.count_nonzero((inner > near[:-2]) & (inner >= near[2:])) == 2  # two maxima
    assert is_clear(near)
    assert not is_clear(far)


def test_a_stricter_ratio_rejects_a_rival_the_default_allows():
    curve = _curve((0.0, 0.5), (0.5, 0.35))
    assert is_clear(curve)
    assert not is_clear(curve, ratio=0.6)


def test_bins_and_a_half_cannot_both_be_asked_for():
    """A half along the axis always uses every bin, so asking for both is a mistake that
    would otherwise be ignored silently."""
    curve = np.zeros((3, 5))
    pairs = PairCurves(
        lags=2,
        n_axis=10,
        by_bin={(0, 1): curve},
        halves={(0, 1): np.zeros((2, 5))},
        energy=np.ones((2, 3)),
        half_energy=np.ones((2, 2)),
    )
    pairs.normalised(0, 1, bins=slice(0, 2))
    pairs.normalised(0, 1, half=1)
    with pytest.raises(ValueError, match="not both"):
        pairs.normalised(0, 1, bins=slice(0, 2), half=1)
