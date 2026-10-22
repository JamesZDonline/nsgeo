from __future__ import annotations

import nsgeo.processing  # noqa: F401  (registers the built-in steps)
import numpy as np
import pytest
from nsgeo.processing.base import Radargram, build_step, get_step


def make(n_samples=100, n_traces=20, dt_ns=0.2, t0_ns=0.0):
    rng = np.random.default_rng(0)
    return Radargram(data=rng.normal(size=(n_samples, n_traces)), dt_ns=dt_ns, t0_ns=t0_ns)


def test_keeps_the_rows_before_the_cutoff_and_the_start_time():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=-4.0)
    out = build_step("time_cutoff", end_ns=-4.0 + 37 * 0.5).apply(rg)
    assert out.n_samples == 37
    assert out.t0_ns == rg.t0_ns
    np.testing.assert_array_equal(out.data, rg.data[:37])


def test_a_snapped_boundary_on_a_real_world_axis_keeps_exactly_m_rows():
    # dt and t0 as this repo's real HS350 headers carry them; t0 + m*dt is inexact in binary
    rg = make(n_samples=512, dt_ns=0.21653111279010773, t0_ns=-11.086392402648926)
    for m in (1, 2, 255, 300, 511):
        end = rg.t0_ns + m * rg.dt_ns
        assert build_step("time_cutoff", end_ns=end).apply(rg).n_samples == m


def test_a_cutoff_between_samples_keeps_every_sample_before_it():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=0.0)
    out = build_step("time_cutoff", end_ns=10.2).apply(rg)
    assert out.n_samples == 21  # samples at 0.0 .. 10.0


def test_a_cutoff_past_the_record_is_a_no_op():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=0.0)
    assert build_step("time_cutoff", end_ns=50.0).apply(rg) is rg  # exactly the record end
    assert build_step("time_cutoff", end_ns=1e6).apply(rg) is rg


def test_a_cutoff_at_or_before_the_first_sample_is_refused():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=2.0)
    for end in (2.0, -5.0):
        with pytest.raises(ValueError, match="would leave no samples"):
            build_step("time_cutoff", end_ns=end).apply(rg)


def test_end_ns_is_required_and_must_be_a_finite_number():
    with pytest.raises(ValueError, match="end_ns"):
        build_step("time_cutoff")
    with pytest.raises(ValueError, match="must be a number"):
        build_step("time_cutoff", end_ns="late")
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            build_step("time_cutoff", end_ns=bad)


def test_the_schema_declares_a_time_parameter_in_ns():
    (spec,) = get_step("time_cutoff").schema()
    assert (spec.name, spec.kind, spec.unit, spec.required) == ("end_ns", "time", "ns", True)
