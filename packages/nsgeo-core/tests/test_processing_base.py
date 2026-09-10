from __future__ import annotations

import numpy as np
import pytest
from nsgeo.processing._util import running_mean
from nsgeo.processing.base import (
    Radargram,
    available_steps,
    build_step,
    get_step,
    register,
)


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

        def apply(self, r: Radargram) -> Radargram:
            return r.replace(data=r.data * self.factor)

    assert "test_doubler" in available_steps()
    assert get_step("test_doubler") is _Doubler
    step = build_step("test_doubler", factor=3.0)
    out = step.apply(rg())
    assert out.data[1, 1] == pytest.approx(rg().data[1, 1] * 3.0)
    assert step.params == {"factor": 3.0}


def test_unknown_step_name_lists_alternatives():
    with pytest.raises(KeyError, match="available"):
        get_step("no_such_step")


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
