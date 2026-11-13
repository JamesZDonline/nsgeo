"""The hyperbola tracer, against hyperbolas planted with the real lines' wavelet."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo import hyperbola_trace as ht
from nsgeo.hyperbola_trace import TraceBox, edge_time, trace_hyperbola
from nsgeo.processing.base import Radargram
from nsgeo.processing.timezero import first_break_row
from nsgeo.velocity_fit import fit_hyperbola

from tests.planted import (
    REAL_DT_NS,
    REAL_DX_M,
    REAL_NOISE_RATIO,
    REAL_PERIOD_NS,
    Planted,
    plant,
    ricker,
    wavelet_onset_ns,
)

N_TRACES = 200
N_SAMPLES = 200


def _scene(hyperbolas, *, distance_m=None, seed=1):
    return plant(
        N_TRACES,
        N_SAMPLES,
        hyperbolas,
        noise_ratio=REAL_NOISE_RATIO,
        seed=seed,
        distance_m=distance_m,
    )


def _fit(dots, distance_m):
    traces = np.array([d[0] for d in dots])
    times = np.array([d[1] for d in dots])
    return fit_hyperbola(distance_m[traces], times, float(distance_m[traces[0]]))


def _within_2_sigma(fit, truth):
    return abs(fit.v_m_ns - truth) <= 2 * fit.v_stderr_m_ns


def test_a_planted_hyperbola_is_traced_to_its_velocity():
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))
    assert _within_2_sigma(_fit(dots, x), 0.07)


@pytest.mark.parametrize("fraction", [0.1, 0.2, 0.5])
def test_the_edge_rule_matches_time_zeros_first_break(fraction):
    t = np.arange(200) * REAL_DT_NS
    trace = ricker(t - 20.0, REAL_PERIOD_NS)
    rg = Radargram(data=trace[:, None], dt_ns=REAL_DT_NS, t0_ns=0.0)
    row_time = first_break_row(rg, fraction) * REAL_DT_NS
    edge = edge_time(trace, t, 0.0, float(t[-1]), fraction)
    assert edge is not None
    assert abs(edge - row_time) <= REAL_DT_NS


def test_the_wavelet_onset_is_where_the_planted_edge_lands():
    t = np.arange(400) * 0.01
    w = np.abs(ricker(t - 5.0, 3.0))
    first = t[np.flatnonzero(w >= 0.2)[0]]
    assert first == pytest.approx(5.0 - 6.0 + wavelet_onset_ns(3.0), abs=0.02)


def test_at_most_ten_dots_and_the_apex_nearest_first():
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))
    assert 4 <= len(dots) <= 10
    traces = [d[0] for d in dots]
    assert abs(traces[0] - 100) == min(abs(k - 100) for k in traces)
    assert traces[1:] == sorted(traces[1:])


def test_the_stronger_of_two_hyperbolas_is_traced():
    data, t, x = _scene([Planted(80, 15.0, 0.07), Planted(120, 15.0, 0.07, amplitude=0.4)])
    dots = trace_hyperbola(data, t, x, TraceBox(50, 150, 10.0, 30.0))
    fit = _fit(dots, x)
    assert abs(fit.apex_x_m / REAL_DX_M - 80) <= 3


def test_a_fading_leg_drops_the_faded_traces():
    data, t, x = _scene([Planted(100, 15.0, 0.07, fade_from_trace=25)])
    dots = trace_hyperbola(data, t, x, TraceBox(40, 160, 10.0, 35.0))
    assert all(abs(d[0] - 100) <= 35 for d in dots)
    assert _within_2_sigma(_fit(dots, x), 0.07)


@pytest.mark.parametrize(
    "box",
    [TraceBox(98, 160, 10.0, 35.0), TraceBox(40, 160, 10.0, 25.0)],
    ids=["apex-and-one-leg", "bottom-cuts-both-legs"],
)
def test_a_leg_cut_off_by_the_box_is_traced_from_the_part_inside(box):
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    dots = trace_hyperbola(data, t, x, box)
    assert _within_2_sigma(_fit(dots, x), 0.07)
    assert all(box.top_ns <= d[1] <= box.bottom_ns for d in dots)


def test_a_planted_hyperbola_at_five_times_the_noise_is_still_traced():
    data, t, x = plant(
        N_TRACES,
        N_SAMPLES,
        [Planted(100, 15.0, 0.07)],
        noise_ratio=5 * REAL_NOISE_RATIO,
        seed=1,
    )
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))
    assert _within_2_sigma(_fit(dots, x), 0.07)


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.1, 1.5])
def test_a_fraction_outside_zero_to_one_is_refused(fraction):
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    with pytest.raises(ValueError, match="edge fraction must be between 0 and 1"):
        trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0), fraction=fraction)
    with pytest.raises(ValueError, match="edge fraction must be between 0 and 1"):
        edge_time(data[:, 100], t, 0.0, float(t[-1]), fraction)


def test_too_few_surviving_edges_gives_the_cleaning_message_not_the_fits(monkeypatch):
    # Only the traces near the apex stand above the faded legs, a handful.
    data, t, x = _scene([Planted(100, 15.0, 0.07, fade_from_trace=0)])
    monkeypatch.setattr(ht, "MIN_DOTS", 40)
    with pytest.raises(
        ValueError,
        match=r"Too few points were left after cleaning \(\d+\); a fit needs at least 40\.",
    ):
        trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))


def test_thinning_never_repeats_a_trace():
    data, t, x = _scene([Planted(100, 15.0, 0.07, fade_from_trace=0)])
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0), max_dots=4)
    assert len({d[0] for d in dots}) == len(dots) >= 4


def test_a_box_top_cutting_into_the_band_does_not_shift_the_fit():
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    box = TraceBox(60, 140, 15.3, 30.0)
    try:
        dots = trace_hyperbola(data, t, x, box)
    except ValueError:
        return  # a refusal is acceptable; a silently shifted fit is not
    assert _within_2_sigma(_fit(dots, x), 0.07)


def test_noise_alone_is_no_hyperbola():
    data, t, x = _scene([])
    with pytest.raises(
        ValueError,
        match="No hyperbola was found in the box.|The hyperbola in the box is too faint to trace.",
    ):
        trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))


def test_a_tiny_box_is_refused():
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    with pytest.raises(ValueError, match="The box is too small to hold a hyperbola"):
        trace_hyperbola(data, t, x, TraceBox(100, 102, 10.0, 30.0))


def test_a_box_over_the_cell_limit_is_refused(monkeypatch):
    monkeypatch.setattr(ht, "MAX_BOX_CELLS", 100)
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    with pytest.raises(ValueError, match=r"too big to trace quickly \(81 traces by 20 ns\)"):
        trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))


def test_uneven_trace_spacing_is_respected():
    rng = np.random.default_rng(5)
    steps = REAL_DX_M * (1.0 + rng.uniform(-0.3, 0.3, N_TRACES))
    x = np.concatenate([[0.0], np.cumsum(steps[1:])])
    data, t, x = _scene([Planted(100, 15.0, 0.07)], distance_m=x)
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))
    assert _within_2_sigma(_fit(dots, x), 0.07)


def test_a_backwards_box_is_normalised():
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    forward = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))
    backward = trace_hyperbola(data, t, x, TraceBox(140, 60, 30.0, 10.0))
    assert forward == backward


def test_a_few_survivors_are_all_returned_not_just_the_apex():
    # Fewer cleaned edges than max_dots must all come back (once returned only the apex).
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    dots = trace_hyperbola(data, t, x, TraceBox(96, 104, 10.0, 30.0))
    assert len(dots) >= ht.MIN_DOTS
