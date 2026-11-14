from __future__ import annotations

import math
import re

import numpy as np
import pytest
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing._util import refuse_non_finite, running_mean
from nsgeo.processing.base import (
    ParamSpec,
    Radargram,
    available_steps,
    build_step,
    get_step,
    nyquist_mhz,
    register,
    retime_ns,
)

from tests.real_data import DATA, real_radargram
from tests.synthetic import write_dzt


def rg(n_samples=8, n_traces=4, dt_ns=0.2, t0_ns=0.0):
    data = np.arange(n_samples * n_traces, dtype=float).reshape(n_samples, n_traces)
    return Radargram(data=data, dt_ns=dt_ns, t0_ns=t0_ns)


@pytest.fixture
def clean_registry():
    """Registering a step is a global side effect. Restore the registry so a
    test double cannot leak into available_steps() for every later test."""
    from nsgeo.processing import base

    saved = dict(base._REGISTRY)
    yield
    base._REGISTRY.clear()
    base._REGISTRY.update(saved)


def test_times_ns_starts_at_t0_and_steps_by_dt():
    r = rg(n_samples=5, dt_ns=0.25, t0_ns=1.0)
    np.testing.assert_allclose(r.times_ns(), [1.0, 1.25, 1.5, 1.75, 2.0])


def test_replace_keeps_unspecified_fields():
    r = rg(t0_ns=3.0)
    out = r.replace(data=r.data * 2)
    assert out.t0_ns == 3.0
    assert out.dt_ns == r.dt_ns


def test_shapes():
    r = rg(n_samples=9, n_traces=7)
    assert (r.n_samples, r.n_traces) == (9, 7)


def test_rejects_non_2d_data():
    with pytest.raises(ValueError, match="2-D"):
        Radargram(data=np.zeros(5), dt_ns=0.2, t0_ns=0.0)


def test_rejects_non_positive_dt():
    with pytest.raises(ValueError, match="dt_ns"):
        Radargram(data=np.zeros((4, 4)), dt_ns=0.0, t0_ns=0.0)


def test_registry_round_trip(clean_registry):
    @register
    class _Doubler:
        name = "test_doubler"
        title = "Doubler"
        group = "Gain"
        order = 9

        def __init__(self, factor: float = 2.0):
            self.factor = factor

        @property
        def params(self):
            return {"factor": self.factor}

        @classmethod
        def schema(cls):
            # Declared, like every real step: `Step` lists `schema()` in the
            # protocol, a front end enumerating the registry calls it to
            # build a form, and `build_step` validates against it. A
            # registered class without one is not a usable step.
            return (ParamSpec(name="factor", kind="float", label="Factor", default=2.0),)

        def apply(self, r: Radargram) -> Radargram:
            return r.replace(data=r.data * self.factor)

    assert "test_doubler" in available_steps()
    assert get_step("test_doubler") is _Doubler
    step = build_step("test_doubler", factor=3.0)
    out = step.apply(rg())
    assert out.data[1, 1] == pytest.approx(rg().data[1, 1] * 3.0)
    assert step.params == {"factor": 3.0}


def test_register_refuses_a_name_another_step_already_owns(clean_registry):
    """Import order must not decide what a saved stack runs.

    Verified before the guard: a class declaring `name = "dewow"` replaced
    the real one, and `build_step("dewow")` returned the impostor with no
    warning anywhere. A stack saved against one implementation then loads
    and runs against the other, changing the processing applied to
    irreplaceable survey data.
    """
    real = get_step("dewow")

    with pytest.raises(ValueError, match="dewow"):

        @register
        class _Impostor:
            name = "dewow"
            title = "Dewow"
            group = "Filters"
            order = 1

            def __init__(self, window_ns: float = 4.0):
                self.window_ns = window_ns

            @property
            def params(self):
                return {"window_ns": self.window_ns}

            @classmethod
            def schema(cls):
                return (ParamSpec(name="window_ns", kind="float", label="W", default=4.0),)

            def apply(self, r: Radargram) -> Radargram:
                return r

    assert get_step("dewow") is real
    assert type(build_step("dewow", window_ns=4.0)) is real


def test_registering_the_same_class_twice_is_not_a_conflict(clean_registry):
    """A module imported twice re-runs its decorators; that is not two steps
    fighting over a name, and must not raise."""

    @register
    class _Once:
        name = "test_once"
        title = "Once"
        group = "Gain"
        order = 9

        @property
        def params(self):
            return {}

        @classmethod
        def schema(cls):
            return ()

        def apply(self, r: Radargram) -> Radargram:
            return r

    assert register(_Once) is _Once
    assert get_step("test_once") is _Once


def test_unknown_step_name_lists_alternatives():
    with pytest.raises(KeyError, match="available"):
        get_step("no_such_step")


def test_nyquist_mhz_pins_the_constant():
    """Every existing call site (the real DZT test fixtures' dt_ns, and
    Bandpass's own guard against them) happens to still hold for roughly
    any constant in (130, 1083) substituted for 500.0 -- so those alone
    pin neither the factor nor the units. A value picked specifically to
    fail under a wrong constant: 500.0 / 0.2 is 2500.0, not (say) 500 / 0.2
    rounded, or a units slip of 1/(2*dt_ns) without the 1e-9/1e6 rescale.
    """
    assert nyquist_mhz(0.2) == 2500.0


def test_running_mean_of_constant_is_constant():
    a = np.full((10, 3), 5.0)
    np.testing.assert_allclose(running_mean(a, 5, axis=0), 5.0)


def test_running_mean_window_one_is_identity():
    a = np.arange(12.0).reshape(4, 3)
    np.testing.assert_allclose(running_mean(a, 1, axis=0), a)


def test_running_mean_shrinks_window_at_edges():
    a = np.array([[0.0], [1.0], [2.0], [3.0]])
    out = running_mean(a, 3, axis=0)
    assert out[0, 0] == pytest.approx(0.5)  # mean of [0, 1]
    assert out[1, 0] == pytest.approx(1.0)  # mean of [0, 1, 2]
    assert out[3, 0] == pytest.approx(2.5)  # mean of [2, 3]


def test_running_mean_along_trace_axis():
    a = np.tile(np.arange(6.0), (2, 1))
    out = running_mean(a, 3, axis=1)
    assert out.shape == a.shape
    assert out[0, 2] == pytest.approx(2.0)


def test_running_mean_rejects_zero_window():
    with pytest.raises(ValueError, match="window"):
        running_mean(np.zeros((4, 4)), 0, axis=0)


def _direct_running_mean(a, window, axis=0):
    """running_mean written out: each output i is the mean of the finite samples
    in [lo, hi), the shrinking-edge rule, or NaN when none is. Summed with
    math.fsum so the reference carries no rounding of its own."""
    a = np.moveaxis(np.asarray(a, dtype=float), axis, 0)
    n = a.shape[0]
    out = np.empty_like(a)
    for i in range(n):
        lo = max(i - window // 2, 0)
        hi = min(i - window // 2 + window, n)
        for j in np.ndindex(a.shape[1:]):
            vals = [v for v in a[(slice(lo, hi), *j)] if math.isfinite(v)]
            out[(i, *j)] = math.fsum(vals) / len(vals) if vals else np.nan
    return np.moveaxis(out, 0, axis)


def test_running_mean_skips_nan_and_inf():
    """#43: one NaN or inf used to poison the rest of the axis through the
    cumulative sum (420 rows of dewow output from one NaN)."""
    a = np.random.default_rng(0).normal(size=(64, 5))
    a[10, 1] = np.nan
    a[30, 2] = np.inf
    a[31, 2] = -np.inf
    for window, axis in ((7, 0), (3, 1)):
        np.testing.assert_allclose(
            running_mean(a, window, axis=axis), _direct_running_mean(a, window, axis), rtol=1e-12
        )


def test_running_mean_of_a_window_with_no_finite_sample_is_nan():
    a = np.array([[np.nan], [np.nan], [np.nan], [1.0]])
    out = running_mean(a, 3, axis=0)
    assert np.isnan(out[0, 0]) and np.isnan(out[1, 0])
    assert out[2, 0] == 1.0 and out[3, 0] == 1.0


def test_running_mean_keeps_precision_beside_a_huge_value():
    """A 1e12 sample used to stay in the cumulative total, so every later
    window came out of a difference of two numbers near 1e12 and kept only
    about four significant figures. That is what let AGC exceed its cap."""
    a = np.random.default_rng(0).normal(size=200)
    a[0] = 1e12
    out = running_mean(a, 5)
    # Rows 3 on: windows [i - 2, i + 3) clear of row 0.
    np.testing.assert_allclose(out[3:], _direct_running_mean(a, 5)[3:], rtol=1e-12)


def test_refuse_non_finite_counts_traces_not_samples_or_rows():
    """Four bad samples, on three rows, in two of six traces."""
    data = np.zeros((10, 6))
    data[2, 1] = data[5, 1] = data[7, 1] = np.nan
    data[2, 4] = -np.inf
    with pytest.raises(
        ValueError,
        match=re.escape("2 of 6 traces hold samples that are not finite; it would spread"),
    ):
        refuse_non_finite(data, "it would spread")
    refuse_non_finite(np.ones((10, 6)), "it would spread")


def test_radargram_is_hashable_with_identity_equality():
    r = rg()
    assert r == r and hash(r) == hash(r)
    assert r != Radargram(data=r.data, dt_ns=r.dt_ns, t0_ns=r.t0_ns)
    assert len({r, r}) == 1


def test_from_profile_casts_to_float_and_copies_the_header_axis(tmp_path):
    """The seam between the data model (int32 Profile) and processing
    (float Radargram): real files feed this exact path."""
    path = tmp_path / "L0.DZT"
    write_dzt(path, np.zeros((512, 4), dtype=np.int32), range_ns=102.4)
    line = Line.open(path, GridPlacement(grid_id="G1", axis="y", offset=0.0))
    profile = line.load()[0]

    rg_out = Radargram.from_profile(profile)

    assert np.issubdtype(rg_out.data.dtype, np.floating)
    assert rg_out.dt_ns == pytest.approx(profile.header.dt_ns)
    assert rg_out.t0_ns == pytest.approx(profile.header.position_ns)
    assert rg_out.n_traces == profile.n_traces
    assert rg_out.data is not profile.data


def test_from_profile_derives_dx_from_traces_per_metre(tmp_path):
    """Trace spacing is the one piece of acquisition context a step needs,
    and it comes from the header -- the same quantity
    `GridPlacement.distance_along` already uses. No new source of truth."""
    path = tmp_path / "L0.DZT"
    write_dzt(path, np.zeros((512, 4), dtype=np.int32), traces_per_metre=60.0)
    profile = Line.open(path, GridPlacement(grid_id="G1", axis="y", offset=0.0)).load()[0]

    assert Radargram.from_profile(profile).dx_m == pytest.approx(1 / 60.0)


def test_from_profile_leaves_dx_none_for_a_time_triggered_file(tmp_path):
    """Collected on a timer, not a survey wheel: there is no spatial axis,
    which is the same condition `GridPlacement` already refuses on. None,
    not a guess, so migration can refuse rather than run on trace index."""
    path = tmp_path / "L0.DZT"
    write_dzt(path, np.zeros((512, 4), dtype=np.int32), traces_per_metre=0.0)
    profile = Line.open(path, GridPlacement(grid_id="G1", axis="y", offset=0.0)).load()[0]

    assert Radargram.from_profile(profile).dx_m is None


def test_dx_m_defaults_to_none_so_existing_constructions_are_untouched():
    assert Radargram(data=np.zeros((4, 4)), dt_ns=0.2, t0_ns=0.0).dx_m is None


def test_retime_ns_converts_between_clocks():
    assert retime_ns(10.0, -0.5, 0.0) == pytest.approx(9.5)
    assert retime_ns(10.0, 0.0, -0.5) == pytest.approx(10.5)
    np.testing.assert_allclose(retime_ns(np.array([1.0, 2.0]), 2.0, 0.5), [2.5, 3.5])


_PASS_THROUGH = [
    ("dewow", {}),
    ("gain_agc", {}),
    ("gain_parametric", {}),
    ("gain_curve", {"points": [[0.0, 0.0], [10.0, 6.0]]}),
    ("bandpass", {"low_mhz": 100.0, "high_mhz": 800.0}),
    ("background_mean", {}),
    ("background_sliding", {"window_traces": 5}),
    ("background_svd", {}),
    ("amp_abs", {}),
    ("amp_square", {}),
    ("amp_envelope", {}),
    ("time_cutoff", {"end_ns": 10.0}),
    ("migrate_fk", {"velocity_m_ns": 0.1}),
    ("trace_stack", {"window_traces": 3}),
]


def test_the_pass_through_list_covers_every_step_but_time_zero():
    import nsgeo.processing  # noqa: F401  (registers every step)

    names = {n for n, _ in _PASS_THROUGH}
    assert names | {"time_zero"} == set(available_steps())


@pytest.mark.parametrize("name, params", _PASS_THROUGH)
def test_every_other_step_passes_the_clock_through(name, params):
    import nsgeo.processing  # noqa: F401

    rg = Radargram(
        data=np.random.default_rng(0).normal(size=(128, 40)),
        dt_ns=0.2,
        t0_ns=0.0,
        dx_m=0.02,
        zero_ns=-1.25,
        zero_set=True,
    )
    out = build_step(name, **params).apply(rg)
    assert out.zero_ns == -1.25
    assert out.zero_set is True


def test_radar_clock_conversions_are_asymmetric_and_round_trip():
    rg = Radargram(data=np.zeros((4, 2)), dt_ns=0.2, t0_ns=0.0, zero_ns=-1.25)
    assert rg.to_radar_ns(1.0) == pytest.approx(-0.25)
    assert rg.from_radar_ns(-0.25) == pytest.approx(1.0)
    t = np.array([0.0, 1.0, 2.5])
    np.testing.assert_allclose(rg.from_radar_ns(rg.to_radar_ns(t)), t)
    np.testing.assert_allclose(rg.to_radar_ns(t), t - 1.25)


def test_retime_with_equal_nonzero_zeros_is_exact():
    # Grouped as t + (from - to): equal zeros cancel exactly.
    assert retime_ns(52.0, 12.345678, 12.345678) == 52.0


def test_one_nan_through_the_users_stack_stays_one_sample():
    """The stack every saved project uses, on a real line: one NaN inside the
    45 ns cutoff comes out as one NaN, at the same sample, and nothing else."""
    import nsgeo.processing  # noqa: F401

    rg = real_radargram(DATA / "FILE__007.DZT")
    data = rg.data.copy()
    data[150, 300] = np.nan
    out = rg.replace(data=data)
    for name, params in [
        ("time_zero", {}),
        ("time_cutoff", {"end_ns": 45.0}),
        ("dewow", {}),
        ("background_mean", {}),
        ("gain_agc", {}),
        ("gain_curve", {"points": [[0.0, 0.0], [20.0, 6.0], [45.0, 0.0]]}),
    ]:
        out = build_step(name, **params).apply(out)
    # Time zero crops 49 rows on this line, so the sample is row 101 (21.9 ns).
    assert np.argwhere(~np.isfinite(out.data)).tolist() == [[150 - 49, 300]]
    assert np.isnan(out.data[150 - 49, 300])
