from __future__ import annotations

import math
import re

import nsgeo.processing.dewow  # noqa: F401  (registers the step)
import nsgeo.processing.timezero  # noqa: F401
import numpy as np
import pytest
from nsgeo.processing.base import Radargram, build_step
from nsgeo.processing.timezero import first_break_ns, first_break_row, sets_time_zero, time_base_of

from tests.real_data import DATA, real_radargram


def make(n_samples=100, n_traces=20, dt_ns=0.2, t0_ns=0.0, fill=0.0):
    return Radargram(
        data=np.full((n_samples, n_traces), fill, dtype=float), dt_ns=dt_ns, t0_ns=t0_ns
    )


def test_time_zero_by_sample_crops_rows():
    rg = make(n_samples=100)
    out = build_step("time_zero", mode="sample", sample=17).apply(rg)
    assert out.n_samples == 83


def test_time_zero_makes_its_row_read_zero_and_records_its_radar_time():
    rg = make(n_samples=100, dt_ns=0.25, t0_ns=1.0)
    out = build_step("time_zero", mode="sample", sample=8).apply(rg)
    assert out.n_samples == 92
    assert out.t0_ns == 0.0
    assert out.times_ns()[0] == 0.0
    assert out.zero_ns == pytest.approx(1.0 + 8 * 0.25)
    assert out.zero_set is True


def test_time_zero_first_break_finds_the_onset():
    rg = make(n_samples=200)
    data = rg.data.copy()
    data[40:, :] = 100.0  # signal starts at row 40
    out = build_step("time_zero", mode="first_break", threshold=0.5).apply(rg.replace(data=data))
    assert out.n_samples == 160


def test_time_zero_first_break_ignores_leading_zero_traces():
    """Leading all-zero traces are normal and must not confuse the pick."""
    rg = make(n_samples=200, n_traces=20)
    data = rg.data.copy()
    data[40:, 4:] = 100.0
    data[:, :4] = 0.0
    out = build_step("time_zero", mode="first_break", threshold=0.5).apply(rg.replace(data=data))
    assert out.n_samples == 160


def test_time_zero_at_sample_zero_still_sets_the_clock():
    rg = make(n_samples=50, t0_ns=2.0)
    out = build_step("time_zero", mode="sample", sample=0).apply(rg)
    assert out.n_samples == 50
    assert out.t0_ns == 0.0
    assert out.zero_ns == pytest.approx(2.0)
    assert out.zero_set is True


def test_every_kept_row_keeps_its_radar_time():
    rg = make(n_samples=100, dt_ns=0.25, t0_ns=-2.0).replace(zero_ns=1.5)
    out = build_step("time_zero", mode="sample", sample=12).apply(rg)
    np.testing.assert_allclose(out.to_radar_ns(out.times_ns()), rg.to_radar_ns(rg.times_ns())[12:])


def test_a_second_time_zero_changes_nothing():
    data = np.zeros((200, 20))
    data[40:, :] = 100.0
    rg = make(n_samples=200).replace(data=data)
    once = build_step("time_zero", threshold=0.5).apply(rg)
    twice = build_step("time_zero", threshold=0.5).apply(once)
    assert twice.n_samples == once.n_samples
    assert twice.zero_ns == pytest.approx(once.zero_ns)
    assert twice.t0_ns == 0.0


def test_first_break_row_is_the_steps_own_pick():
    data = np.zeros((200, 20))
    data[40:, :] = 100.0
    rg = make(n_samples=200).replace(data=data)
    assert first_break_row(rg, 0.5) == 40
    assert build_step("time_zero", threshold=0.5).apply(rg).n_samples == 200 - first_break_row(
        rg, 0.5
    )


def test_sets_time_zero_reads_enabled_entries_only():
    assert sets_time_zero([{"step": "time_zero", "params": {}, "enabled": True}])
    assert sets_time_zero([{"step": "time_zero", "params": {}}])
    assert not sets_time_zero([{"step": "time_zero", "params": {}, "enabled": False}])
    assert not sets_time_zero([{"step": "dewow", "params": {}, "enabled": True}])
    assert time_base_of([]) == "radar"
    assert time_base_of([{"step": "time_zero", "params": {}, "enabled": True}]) == "time_zero"


def test_time_zero_rejects_cropping_everything():
    with pytest.raises(ValueError, match="would leave no samples"):
        build_step("time_zero", mode="sample", sample=100).apply(make(n_samples=100))


def test_time_zero_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        build_step("time_zero", mode="vibes").apply(make())


def test_time_zero_does_not_mutate_input():
    rg = make(n_samples=50, fill=3.0)
    before = rg.data.copy()
    build_step("time_zero", mode="sample", sample=5).apply(rg)
    np.testing.assert_array_equal(rg.data, before)


def test_dewow_removes_a_constant_offset():
    rg = make(n_samples=200, fill=7.0)
    out = build_step("dewow", window_ns=4.0).apply(rg)
    np.testing.assert_allclose(out.data, 0.0, atol=1e-9)


def test_dewow_preserves_high_frequency_content():
    n = 400
    t = np.arange(n)
    fast = np.sin(2 * np.pi * t / 4.0)[:, None] * np.ones((1, 5))
    slow = 10.0 * np.sin(2 * np.pi * t / 400.0)[:, None] * np.ones((1, 5))
    rg = Radargram(data=fast + slow, dt_ns=0.2, t0_ns=0.0)
    out = build_step("dewow", window_ns=8.0).apply(rg)
    mid = slice(50, 350)
    assert np.std(out.data[mid]) > 0.5 * np.std(fast[mid])
    assert np.abs(out.data[mid].mean()) < 0.5


def test_dewow_leaves_time_axis_untouched():
    rg = make(n_samples=100, dt_ns=0.2, t0_ns=1.5)
    out = build_step("dewow", window_ns=4.0).apply(rg)
    assert out.t0_ns == pytest.approx(1.5)
    assert out.n_samples == 100


def test_dewow_rejects_window_shorter_than_one_sample():
    with pytest.raises(ValueError, match="window_ns"):
        build_step("dewow", window_ns=0.0).apply(make(dt_ns=0.2))


def test_step_params_are_declared_for_the_ui():
    step = build_step("dewow", window_ns=6.0)
    assert step.params == {"window_ns": 6.0}


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_dewow_on_a_real_line_a_bad_sample_damages_only_itself(bad):
    """#43: one NaN used to turn the rest of its trace into NaN."""
    rg = real_radargram(DATA / "FILE__007.DZT")
    data = rg.data.copy()
    data[100, 300] = bad
    out = build_step("dewow").apply(rg.replace(data=data)).data
    assert np.argwhere(~np.isfinite(out)).tolist() == [[100, 300]]
    assert np.isnan(out[100, 300]) == np.isnan(bad)
    # A neighbour is its sample less the mean of the good samples in its window.
    window = int(round(4.0 / rg.dt_ns))
    lo, hi = 101 - window // 2, 101 - window // 2 + window
    good = [v for v in data[lo:hi, 300] if math.isfinite(v)]
    assert out[101, 300] == pytest.approx(data[101, 300] - math.fsum(good) / len(good), rel=1e-12)


@pytest.mark.parametrize(
    ("row", "bad"),
    [(None, None), (300, np.nan), (300, np.inf), (49, np.nan), (49, np.inf)],
)
def test_time_zero_on_a_real_line_crops_49_rows_whatever_one_bad_sample(row, bad):
    """#42: one NaN used to cancel the crop, and one inf moved it to row 300.
    Row 49 is the pick itself: its mean over its other 634 samples still
    reaches the threshold, where leaving the whole row out would pick row 50."""
    rg = real_radargram(DATA / "FILE__007.DZT")
    if row is not None:
        data = rg.data.copy()
        data[row, 5] = bad
        rg = rg.replace(data=data)
    assert first_break_row(rg) == 49
    assert build_step("time_zero").apply(rg).n_samples == rg.n_samples - 49


def test_time_zero_refuses_an_all_zero_line():
    """It used to crop nothing and say nothing. first_break_row itself still
    answers 0 for no signal: other code calls it directly."""
    rg = make(n_samples=100, n_traces=20)
    with pytest.raises(
        ValueError,
        match=re.escape("Time zero found no first arrival: every sample on this line is zero"),
    ):
        build_step("time_zero").apply(rg)
    assert first_break_row(rg) == 0
    assert build_step("time_zero", mode="sample", sample=3).apply(rg).n_samples == 97


def test_time_zero_refuses_a_line_with_no_finite_sample():
    rg = make(n_samples=100, n_traces=20, fill=np.nan)
    with pytest.raises(ValueError, match="Time zero found no first arrival"):
        build_step("time_zero").apply(rg)
    assert first_break_row(rg) == 0


def test_first_break_ns_is_the_picked_rows_time_on_the_axis():
    data = np.zeros((200, 20))
    data[40:, :] = 100.0
    rg = make(n_samples=200).replace(data=data)
    assert first_break_ns(rg, 0.5) == pytest.approx(rg.t0_ns + 40 * rg.dt_ns)
    assert first_break_ns(rg, 0.5) == pytest.approx(rg.times_ns()[40])
