import numpy as np
import pytest
from nsgeo.velocity_fit import (
    StoredFit,
    applied_fit_note,
    fit_at_zero,
    fit_hyperbola,
    radar_clock_note,
    refit,
)


def test_points_on_an_analytic_hyperbola_recover_its_parameters():
    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
    fit = fit_hyperbola(x, t, apex_guess_m=x0, search_m=0.0)
    assert fit.v_m_ns == pytest.approx(v, rel=1e-9)
    assert fit.t0_ns == pytest.approx(t0, rel=1e-9)
    assert fit.rms_ns == pytest.approx(0.0, abs=1e-9)
    assert fit.n_points == 5


def test_hyperbola_time_evaluates_the_fitted_curve():
    from nsgeo.velocity_fit import hyperbola_time

    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    fit = fit_hyperbola(x, np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2), x0, search_m=0.0)
    probe = np.array([0.0, 4.0, 5.0, 9.5])
    expected = np.sqrt(t0**2 + (4.0 / v**2) * (probe - x0) ** 2)
    assert hyperbola_time(fit, probe) == pytest.approx(expected, rel=1e-9)
    assert hyperbola_time(fit, probe)[2] == pytest.approx(t0)  # the apex time is t0


def test_a_wrong_apex_guess_is_recovered_by_the_search():
    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
    fit = fit_hyperbola(x, t, apex_guess_m=5.4, search_m=0.5)
    assert fit.apex_x_m == pytest.approx(5.0, abs=0.011)  # grid step is 0.01 m
    assert fit.v_m_ns == pytest.approx(v, rel=1e-3)


def test_the_reported_sigma_brackets_the_error_under_noise():
    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.linspace(2.0, 8.0, 9)
    t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
    t = t + np.random.default_rng(0).normal(0.0, 0.2, size=t.size)
    fit = fit_hyperbola(x, t, apex_guess_m=x0, search_m=0.0)
    assert abs(fit.v_m_ns - v) <= 3.0 * fit.v_stderr_m_ns


def test_rms_is_in_nanoseconds_of_time_not_of_time_squared():
    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.linspace(2.0, 8.0, 9)
    t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
    t = t + np.random.default_rng(0).normal(0.0, 0.2, size=t.size)
    fit = fit_hyperbola(x, t, apex_guess_m=x0, search_m=0.0)
    # Independent of the implementation: the root-mean-square gap, in ns,
    # between each clicked time and the curve built from the fitted v and t0.
    curve = np.sqrt(fit.t0_ns**2 + (4.0 / fit.v_m_ns**2) * (x - x0) ** 2)
    expected = np.sqrt(np.sum((t - curve) ** 2) / t.size)
    assert 0.05 < expected < 0.5  # noise of 0.2 ns: ns, not ns squared
    assert fit.rms_ns == pytest.approx(expected, rel=1e-6)


def test_points_clustered_near_the_apex_report_a_large_sigma_while_the_residual_stays_quiet():
    v, t0, x0 = 0.1, 20.0, 5.0

    def noisy(x):
        t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
        return t + np.random.default_rng(1).normal(0.0, 0.2, size=t.size)

    spread_x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    tight_x = np.array([4.7, 4.85, 5.0, 5.15, 5.3])
    spread = fit_hyperbola(spread_x, noisy(spread_x), apex_guess_m=x0, search_m=0.0)
    tight = fit_hyperbola(tight_x, noisy(tight_x), apex_guess_m=x0, search_m=0.0)
    assert tight.v_stderr_m_ns > 5.0 * spread.v_stderr_m_ns  # sigma warns
    assert tight.rms_ns < 2.0 * spread.rms_ns  # the residual does not


def _good():
    x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    return x, np.sqrt(20.0**2 + 400.0 * (x - 5.0) ** 2)


def test_two_points_are_refused():
    with pytest.raises(ValueError, match="at least 3 points"):
        fit_hyperbola(np.array([4.0, 5.0]), np.array([21.0, 20.0]), apex_guess_m=5.0)


def test_a_non_positive_time_is_refused():
    x, t = _good()
    t[1] = 0.0
    with pytest.raises(ValueError, match="positive"):
        fit_hyperbola(x, t, apex_guess_m=5.0)


def test_a_non_finite_time_is_refused():
    x, t = _good()
    t[1] = np.nan
    with pytest.raises(ValueError, match="finite"):
        fit_hyperbola(x, t, apex_guess_m=5.0)


def test_an_upward_opening_set_is_refused():
    x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    t = np.sqrt(400.0 - 10.0 * (x - 5.0) ** 2)
    with pytest.raises(ValueError, match="open upward"):
        fit_hyperbola(x, t, apex_guess_m=5.0, search_m=0.0)


def test_a_superluminal_fit_is_refused():
    x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    t = np.sqrt(20.0**2 + (4.0 / 0.5**2) * (x - 5.0) ** 2)
    with pytest.raises(ValueError, match="C_M_PER_NS"):
        fit_hyperbola(x, t, apex_guess_m=5.0, search_m=0.0)


def test_all_points_at_one_offset_are_refused():
    x = np.full(4, 5.0)
    t = np.array([20.0, 20.1, 19.9, 20.0])
    with pytest.raises(ValueError, match="same position"):
        fit_hyperbola(x, t, apex_guess_m=5.0)


def test_points_symmetric_about_the_apex_are_refused_as_having_no_lever_arm():
    # Different x, identical offset from the apex: the design matrix is singular.
    x = np.array([3.0, 7.0, 3.0, 7.0])
    t = np.array([30.0, 30.1, 29.9, 30.0])
    with pytest.raises(ValueError, match="same distance"):
        fit_hyperbola(x, t, apex_guess_m=5.0, search_m=0.0)


@pytest.mark.parametrize("search", [-0.5, float("nan"), float("inf")])
def test_a_negative_or_non_finite_search_is_refused(search):
    x, t = _good()
    with pytest.raises(ValueError, match="search"):
        fit_hyperbola(x, t, apex_guess_m=5.0, search_m=search)


def test_a_non_finite_apex_guess_is_refused_by_name():
    x, t = _good()
    with pytest.raises(ValueError, match="apex guess"):
        fit_hyperbola(x, t, apex_guess_m=float("nan"))


def test_two_dimensional_input_is_not_called_a_length_mismatch():
    x = np.zeros((2, 3))
    with pytest.raises(ValueError, match="one-dimensional"):
        fit_hyperbola(x, x + 20.0, apex_guess_m=0.0)


def test_a_searched_apex_needs_a_fourth_point():
    x, t = _good()
    with pytest.raises(ValueError, match="at least 4 points"):
        fit_hyperbola(x[:3], t[:3], apex_guess_m=5.0, search_m=0.25)


def test_the_reported_sigma_is_calibrated_over_many_noise_draws():
    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.linspace(2.0, 8.0, 9)
    clean = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
    rng = np.random.default_rng(42)
    vs, sigmas = [], []
    for _ in range(2000):
        fit = fit_hyperbola(x, clean + rng.normal(0.0, 0.2, x.size), x0, search_m=0.0)
        vs.append(fit.v_m_ns)
        sigmas.append(fit.v_stderr_m_ns)
    ratio = np.mean(sigmas) / np.std(vs)
    assert 0.9 < ratio < 1.1


def _stored_on_the_radar_clock(zero_ns=-0.5):
    """A 9-point hyperbola (t0 20 ns, v 0.1) fitted on its own clock, stored with its
    times on the radar clock (each plus zero_ns). Traces are 1 cm apart."""
    traces = np.arange(0, 90, 10)
    distance = np.arange(100) * 0.01
    x = distance[traces]
    t = np.sqrt(20.0**2 + (4.0 / 0.1**2) * (x - x[4]) ** 2)
    fitted = fit_hyperbola(x, t, x[0])
    stored = StoredFit(
        fitted.t0_ns,
        fitted.v_m_ns,
        fitted.v_stderr_m_ns,
        fitted.rms_ns,
        4,
        tuple((int(tr), float(ti + zero_ns)) for tr, ti in zip(traces, t, strict=True)),
        "2026-11-10T00:00:00+00:00",
        zero_ns,
    )
    return stored, distance, x, t


def test_refit_at_the_fits_own_zero_reproduces_it():
    stored, distance, _, _ = _stored_on_the_radar_clock()
    again = refit(stored, distance, -0.5)
    assert again.v_m_ns == pytest.approx(stored.v_m_ns, rel=1e-12)
    assert again.t0_ns == pytest.approx(stored.t0_ns, rel=1e-12)


def test_refit_at_a_moved_zero_equals_a_fresh_fit_of_the_shifted_points():
    stored, distance, x, _ = _stored_on_the_radar_clock()
    moved = refit(stored, distance, -2.0)
    radar_t = np.array([t for _, t in stored.points])
    fresh = fit_hyperbola(x, radar_t - (-2.0), x[0])
    assert moved.v_m_ns == pytest.approx(fresh.v_m_ns, rel=1e-12)
    assert moved.t0_ns == pytest.approx(fresh.t0_ns, rel=1e-12)


def test_fit_at_zero_returns_the_stored_fit_when_the_zero_is_unchanged():
    stored, distance, _, _ = _stored_on_the_radar_clock()
    assert fit_at_zero(stored, distance, stored.zero_ns) is stored
    moved = fit_at_zero(stored, distance, -2.0)
    assert moved.zero_ns == -2.0
    assert moved.points == stored.points
    assert moved.apex_trace == int(
        np.argmin(np.abs(distance - refit(stored, distance, -2.0).apex_x_m))
    )


def test_an_old_fit_reads_as_the_radar_clock():
    doc = {
        "t0_ns": 18.4,
        "v_m_ns": 0.0984,
        "v_stderr_m_ns": 0.0041,
        "rms_ns": 0.31,
        "apex_trace": 412,
        "points": [[389, 21.2], [412, 18.6], [437, 21.9]],
        "fitted_at": "2026-10-22T14:02:11Z",
    }
    assert StoredFit.from_dict(doc).zero_ns == 0.0


@pytest.mark.parametrize(
    "fb, quiet", [(-0.10, True), (0.108, True), (-0.48, False), (-11.0, False)]
)
def test_radar_clock_note_is_quiet_within_half_a_sample(fb, quiet):
    assert (radar_clock_note(fb, 0.2165, None, None) == "") is quiet


def test_radar_clock_note_names_the_first_break_and_the_corrected_velocity():
    text = radar_clock_note(-0.48, 0.2165, 0.0703, 0.0712)
    assert "first break is at -0.5 ns" in text
    assert "0.0712 m/ns (+1.3%)" in text
    assert text.endswith("Add a Time zero step to measure from it.")


def test_radar_clock_note_without_velocities_has_no_middle_sentence():
    assert "Measured from" not in radar_clock_note(-0.48, 0.2165, None, 0.07)


def test_applied_fit_note_is_quiet_when_the_velocities_agree_at_4dp():
    assert applied_fit_note(0.07031, 0.07034) == ""
    assert applied_fit_note(0.0703, 0.0712) == (
        "applied 0.0703; measured from the current time zero 0.0712"
    )
