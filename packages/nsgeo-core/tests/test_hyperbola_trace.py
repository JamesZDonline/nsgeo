"""The hyperbola tracer, against hyperbolas planted with the real lines' wavelet."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo import hyperbola_trace as ht
from nsgeo.hyperbola_trace import TraceBox, trace_hyperbola
from nsgeo.velocity_fit import fit_hyperbola, hyperbola_time

from tests.planted import (
    REAL_DT_NS,
    REAL_DX_M,
    REAL_NOISE_RATIO,
    REAL_PERIOD_NS,
    REAL_WAVELET,
    Planted,
    leg_fade_width,
    plant,
    real_layers,
    ricker,
    wavelet_at,
    wavelet_edge_ns,
    wavelet_precursor_ns,
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


def test_the_planted_edge_is_the_zero_crossing_into_the_first_strong_lobe():
    # A Ricker's side lobes are 0.45 of its peak, so its first strong lobe is
    # the main one, which starts P / (pi sqrt 2) before the centre.
    lags = np.arange(-20, 21) * REAL_DT_NS
    edge = wavelet_edge_ns(ricker(lags, 3.0))
    assert edge == pytest.approx(20 * REAL_DT_NS - 3.0 / (np.pi * np.sqrt(2.0)), abs=1e-4)
    # REAL_WAVELET's first strong lobe is the -0.69 one after the 0.21 precursor.
    edge, ahead = wavelet_edge_ns(REAL_WAVELET), wavelet_precursor_ns(REAL_WAVELET)
    precursor = wavelet_at(np.linspace(ahead + 0.01, edge - 0.01, 50))
    strong = wavelet_at(np.linspace(edge + 0.01, edge + 1.3, 50))
    assert 0.15 < np.abs(precursor).max() < 0.5 <= np.abs(strong).max()
    assert precursor.min() >= 0.0 >= strong.max()
    # plant puts that crossing on t(x): here the apex's, at t0.
    data, t, _ = plant(3, 200, [Planted(1, 15.0, 0.07)], noise_ratio=0.0, seed=0)
    trace = data[:, 1]
    j = int(np.flatnonzero((trace[:-1] > 0.0) & (trace[1:] <= 0.0) & (t[1:] > 14.0))[0]) + 1
    crossing = t[j - 1] + trace[j - 1] / (trace[j - 1] - trace[j]) * REAL_DT_NS
    assert crossing == pytest.approx(15.0, abs=0.02)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_edge_is_the_zero_crossing_into_the_first_strong_lobe(seed):
    # REAL_WAVELET has a faint precursor (0.21 of its peak) ahead of its first
    # strong lobe (0.69). The edge is the zero crossing into that lobe, which
    # plant puts on t(x), and never the precursor's (#140, spec §4.2).
    data, t, x = _scene([Planted(100, 15.0, 0.07)], seed=seed)
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))
    traces = np.array([d[0] for d in dots])
    times = np.array([d[1] for d in dots])
    truth = np.sqrt(15.0**2 + 4.0 * (x[traces] - x[100]) ** 2 / 0.07**2)
    precursor = truth - (wavelet_edge_ns() - wavelet_precursor_ns())
    assert np.abs(times - truth).max() <= REAL_DT_NS
    assert (np.abs(times - truth) < np.abs(times - precursor)).all()


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
    # Not 2 sigma: at the planted noise sigma is about 0.1%, and the end dots,
    # read where the leg has faded to the floor, carry about five times the
    # apex's crossing noise. Over 100 seeds 2 sigma misses on 34, each time by
    # under 0.35% (this seed: 0.31% against a sigma of 0.15%).
    assert _fit(dots, x).v_m_ns == pytest.approx(0.07, rel=0.01)


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


def test_a_line_recorded_backwards_is_traced():
    # A line laid out against its grid's direction has distance falling with
    # trace (#140: every saved fit on such a line was refused).
    x = (N_TRACES - 1 - np.arange(N_TRACES)) * REAL_DX_M
    data, t, x = _scene([Planted(100, 15.0, 0.07)], distance_m=x)
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))
    assert _within_2_sigma(_fit(dots, x), 0.07)


def _layered_scene(t0_ns, v_m_ns, half_traces, layer_phase, seed):
    # As on the real lines (#140): layers a period apart at REAL_LAYER_RATIO
    # of the apex, legs fading to REAL_LEG_FADE at the last dot a person would
    # click, half_traces either side of the apex.
    fade = leg_fade_width(half_traces * REAL_DX_M)
    return plant(
        N_TRACES,
        N_SAMPLES,
        [Planted(100, t0_ns, v_m_ns, leg_fade_m=fade)],
        noise_ratio=REAL_NOISE_RATIO,
        seed=seed,
        layers=real_layers(N_SAMPLES, layer_phase * REAL_PERIOD_NS),
    )


@pytest.mark.parametrize(
    ("t0_ns", "v_m_ns", "half_traces", "layer_phase", "box"),
    [
        (15.0, 0.07, 25, 0.75, TraceBox(65, 135, 13.0, 21.2)),
        (25.0, 0.078, 27, 0.375, TraceBox(62, 137, 23.0, 29.5)),
    ],
    ids=["15ns", "25ns"],
)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_hyperbola_among_layers_is_traced_to_its_velocity(
    t0_ns, v_m_ns, half_traces, layer_phase, box, seed
):
    # The box is drawn close around the dots a person would click (their
    # extent + 20%, at least 5 traces and 2 ns), as the hand-fit tests do.
    # A scan score blind to phase took a steep curve through the bright apex,
    # and the edge windows around it read the layers (#140).
    data, t, x = _layered_scene(t0_ns, v_m_ns, half_traces, layer_phase, seed)
    dots = trace_hyperbola(data, t, x, box)
    assert _within_2_sigma(_fit(dots, x), v_m_ns)
    assert max(d[0] for d in dots) - min(d[0] for d in dots) >= half_traces


@pytest.mark.parametrize("seed", range(20))
def test_no_dot_jumps_a_lobe(seed):
    # The legs fade into layers as strong as the real ones, which cross them.
    # On a real line, dots on one leg jumped down a level: a window reaching
    # further below the expected crossing than above it took the next lobe
    # down (#140, the author: "a little noisy"). The next crossing into a lobe
    # of the same sign is a whole period away, so a dot within a quarter period
    # of the fit through the dots is on the same lobe as the rest.
    data, t, x = _layered_scene(15.0, 0.07, 25, 0.625, seed)
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 13.0, 24.0))
    traces = np.array([d[0] for d in dots])
    times = np.array([d[1] for d in dots])
    fit = _fit(dots, x)
    assert np.abs(times - hyperbola_time(fit, x[traces])).max() <= REAL_PERIOD_NS / 4


@pytest.mark.parametrize("seed", range(20))
def test_a_precursor_growing_down_the_legs_does_not_lift_the_dots(seed):
    # The legs fade into layers as strong as the real ones, so the lobe ahead
    # of the band grows against the band's main lobe down the legs: from about
    # 0.2 at the apex to past 0.5 near the box's ends, as on the real lines
    # (0.25 at the apex, 0.51 at the last clicked dot, 0.75 beyond). Taking the
    # crossing anywhere within a quarter period of where the lobe is expected
    # followed the layers there, and the dots floated off the band (#140,
    # ruling R13). Locked to a narrow window, they stay on the planted edge.
    data, t, x = _layered_scene(15.0, 0.07, 25, 0.25, seed)
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 13.0, 24.0))
    traces = np.array([d[0] for d in dots])
    times = np.array([d[1] for d in dots])
    truth = np.sqrt(15.0**2 + 4.0 * (x[traces] - x[100]) ** 2 / 0.07**2)
    assert np.abs(times - truth).max() <= REAL_PERIOD_NS / 8
    assert _within_2_sigma(_fit(dots, x), 0.07)


@pytest.mark.xfail(
    strict=True,
    reason="a flat layer through the apex's own edge shifts the edges there; a known limit",
)
def test_a_layer_through_the_apex_edge_still_gives_the_velocity():
    # The layer's onset falls 0.35 ns after the apex's: across the flat top
    # the two wavelets add, the edges there come out late, and the cleaning
    # keeps them over the true legs.
    data, t, x = _layered_scene(20.0, 0.08, 30, 0.5, seed=1)
    dots = trace_hyperbola(data, t, x, TraceBox(58, 142, 18.0, 25.6))
    assert _within_2_sigma(_fit(dots, x), 0.08)


def test_a_backwards_box_is_normalised():
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    forward = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0))
    backward = trace_hyperbola(data, t, x, TraceBox(140, 60, 30.0, 10.0))
    assert forward == backward


def test_a_few_survivors_are_all_returned_not_just_the_apex():
    # Fewer cleaned edges than max_dots must all come back (once returned only
    # the apex). A box only as wide as the flat top no longer serves: the scan
    # cannot place a curve in nine traces, and the window takes no crossing
    # far from it.
    data, t, x = _scene([Planted(100, 15.0, 0.07)])
    dots = trace_hyperbola(data, t, x, TraceBox(60, 140, 10.0, 30.0), max_dots=1000)
    assert len(dots) > ht.MAX_DOTS
    assert len({d[0] for d in dots}) == len(dots)
