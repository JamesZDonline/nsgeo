from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing._util import running_mean
from nsgeo.processing.base import (
    ParamSpec,
    Radargram,
    available_steps,
    build_step,
    get_step,
    nyquist_mhz,
    register,
)

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
