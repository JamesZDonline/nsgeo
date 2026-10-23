import numpy as np
import pytest
from nsgeo.velocity_fit import fit_hyperbola


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
