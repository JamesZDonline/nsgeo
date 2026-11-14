from __future__ import annotations

import nsgeo.processing  # noqa: F401
import numpy as np
from nsgeo.processing.base import Radargram, build_step
from nsgeo.processing.stack import StepStack

from tests.real_data import DATA, real_radargram

FILE7 = DATA / "FILE__007.DZT"
GRID2 = DATA / "grid2" / "FILE__033.DZT"


def prepared(path):
    rg = real_radargram(path)
    rg = build_step("time_zero").apply(rg)
    return build_step("dewow").apply(rg)


def test_window_one_leaves_the_line_unchanged():
    rg = real_radargram(FILE7)
    out = build_step("trace_stack", window_traces=1).apply(rg)
    np.testing.assert_array_equal(out.data, rg.data)


def test_a_constant_section_is_unchanged():
    rg = Radargram(data=np.full((40, 30), 7.5), dt_ns=0.2, t0_ns=0.0)
    out = build_step("trace_stack", window_traces=5).apply(rg)
    np.testing.assert_allclose(out.data, 7.5)


def test_trace_count_and_time_axis_are_unchanged():
    rg = build_step("time_zero").apply(real_radargram(FILE7))
    out = build_step("trace_stack", window_traces=5).apply(rg)
    assert out.data.shape == rg.data.shape
    assert out.dt_ns == rg.dt_ns
    assert out.t0_ns == rg.t0_ns
    assert out.zero_ns == rg.zero_ns
    assert out.zero_set == rg.zero_set
    assert out.dx_m == rg.dx_m


def test_the_line_ends_average_what_is_there():
    rg = real_radargram(FILE7)
    out = build_step("trace_stack", window_traces=3).apply(rg)
    np.testing.assert_allclose(out.data[:, 0], rg.data[:, :2].mean(axis=1))
    np.testing.assert_allclose(out.data[:, -1], rg.data[:, -2:].mean(axis=1))


def _strongest_rows(rg):
    t = rg.times_ns()
    rows = np.flatnonzero((t >= 8.0) & (t <= 40.0))
    return rows[np.argmax(np.abs(rg.data[rows]), axis=0)]


def test_stacking_lowers_trace_to_trace_noise_on_real_lines():
    for path in (FILE7, GRID2):
        rg = prepared(path)
        out = build_step("trace_stack", window_traces=3).apply(rg)
        ratio = np.var(np.diff(out.data, axis=1)) / np.var(np.diff(rg.data, axis=1))
        assert ratio < 0.75, (path.name, ratio)
        shift = np.abs(_strongest_rows(out) - _strongest_rows(rg))
        assert np.median(shift) == 0, (path.name, np.median(shift))


def test_a_bad_sample_takes_its_neighbours_mean():
    rg = real_radargram(FILE7)
    data = rg.data.copy()
    data[100, 300] = np.nan
    out = build_step("trace_stack", window_traces=3).apply(rg.replace(data=data))
    assert out.data[100, 300] == (data[100, 299] + data[100, 301]) / 2
    assert not np.isnan(out.data).any()


def test_the_difference_view_works_across_it():
    st = StepStack()
    st.source = real_radargram(FILE7)
    st.append(build_step("trace_stack", window_traces=5))
    diff = st.difference(0)
    assert diff.data.shape == st.source.data.shape
    np.testing.assert_allclose(diff.data, st.source.data - st.intermediate(0).data)


def test_a_window_longer_than_the_line_is_capped_at_its_length():
    rg = real_radargram(FILE7)
    assert rg.n_traces == 635
    long = build_step("trace_stack", window_traces=10000).apply(rg)
    exact = build_step("trace_stack", window_traces=635).apply(rg)
    np.testing.assert_array_equal(long.data, exact.data)
