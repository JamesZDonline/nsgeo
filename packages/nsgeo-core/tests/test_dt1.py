"""The Sensors & Software DT1 reader, on synthetic files (M21a, spec §2 and §13)."""

from __future__ import annotations

import nsgeo.processing.dewow  # noqa: F401  (registers the step)
import numpy as np
import pytest
from nsgeo.geometry import GridPlacement
from nsgeo.io import read_header, read_samples, trace_count
from nsgeo.io.dt1 import Dt1Error, Dt1Header
from nsgeo.model import Line
from nsgeo.processing import Radargram, build_step

from tests.dt1_data import write_dt1


def _zeros(n_samples: int = 50, n_traces: int = 8) -> np.ndarray:
    return np.zeros((n_samples, n_traces), dtype=np.int16)


def test_a_dt1_round_trips_its_samples_and_header(tmp_path):
    data = np.arange(-300, 300, dtype=np.int16).reshape(60, 10)
    p = write_dt1(tmp_path / "LINE01.DT1", data, timezero_point=12.0)
    h = read_header(p)
    assert isinstance(h, Dt1Header) and h.format_name == "Sensors & Software DT1"
    assert (h.n_samples, h.n_traces, h.bytes_per_sample, h.n_channels) == (60, 10, 2, 1)
    assert h.dt_ns == pytest.approx(400.0 / 60)
    assert h.position_ns == pytest.approx(-12.0 * 400.0 / 60)
    assert h.traces_per_metre == pytest.approx(4.0) and h.antenna == "100 MHz"
    assert h.notes == () and h.not_a_profile == "" and h.epsr == 0.0
    assert h.hd_path == tmp_path / "LINE01.HD"
    assert trace_count(p, h) == 10
    s = read_samples(p, h)
    assert s.dtype == np.int32 and s.shape == (1, 60, 10)
    np.testing.assert_array_equal(s[0], data)
    np.testing.assert_array_equal(read_samples(p), s)


def test_four_byte_samples_are_read_too(tmp_path):
    data = (np.arange(40 * 5, dtype=np.int32).reshape(40, 5) - 100) * 70_000
    p = write_dt1(tmp_path / "L.DT1", data, bytes_per_sample=4)
    h = read_header(p)
    assert h.bytes_per_sample == 4
    np.testing.assert_array_equal(read_samples(p, h)[0], data)


def test_the_hd_is_read_by_key_whatever_its_order_and_extra_lines(tmp_path):
    p = write_dt1(
        tmp_path / "L.DT1",
        _zeros(),
        hd_extra=(
            "ODOMETER CAL (t/m) = 979.599976 ",
            "Start Rx Battery   = 12.71V",
            "THIS FILE IS A MERGING OF X:\\a\\LINE07.hd AND X:\\a\\LINE08.hd",
            "",
        ),
    )
    hd = p.with_suffix(".HD")
    lines = hd.read_text(encoding="latin-1").splitlines()
    hd.write_text("\r\n".join(lines[:3] + list(reversed(lines[3:]))), encoding="latin-1")
    h = read_header(p)
    assert (h.n_samples, h.n_traces) == (50, 8) and h.traces_per_metre == pytest.approx(4.0)


def test_a_lower_case_hd_is_found_and_its_spelling_kept(tmp_path):
    p = write_dt1(tmp_path / "line00.dt1", _zeros(), hd_suffix=".hd")
    assert read_header(p).hd_path == tmp_path / "line00.hd"


@pytest.mark.parametrize("units", ["ft", "feet", "FT"])
def test_feet_are_converted(tmp_path, units):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), step=0.5, units=units)
    h = read_header(p)
    assert h.traces_per_metre == pytest.approx(1 / (0.5 * 0.3048)) and h.notes == ()


@pytest.mark.parametrize("units", ["m", "metres", "meters", "M"])
def test_metres_are_read_in_any_spelling(tmp_path, units):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), step=0.5, units=units)
    assert read_header(p).traces_per_metre == pytest.approx(2.0)


@pytest.mark.parametrize("units", ["s", None])
def test_other_units_are_not_placed_and_are_noted(tmp_path, units):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), units=units)
    h = read_header(p)
    shown = repr(units or "")
    assert h.traces_per_metre == 0.0
    assert h.notes == (f"position units {shown} are not metres or feet: place it by hand",)


def test_a_zero_step_is_time_triggered_with_no_note(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), step=0.0, positions=[0.0] * 8)
    h = read_header(p)
    assert h.traces_per_metre == 0.0 and h.notes == ()


def test_no_time_zero_reads_from_zero_with_a_note(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), timezero_point=None)
    h = read_header(p)
    assert h.position_ns == 0.0 and h.timezero_point is None
    assert h.notes == ("no time zero in its .HD: set one with a Time zero step",)


def test_trace_positions_that_disagree_with_the_step_add_a_note(tmp_path):
    positions = [i * 0.5 for i in range(8)]
    p = write_dt1(tmp_path / "L.DT1", _zeros(), step=0.25, positions=positions)
    h = read_header(p)
    assert h.traces_per_metre == pytest.approx(4.0)
    assert h.notes == ("trace positions step 0.5 m, not the .HD's 0.25: placed at the .HD's step",)


def test_reversed_positions_at_the_step_add_no_note(tmp_path):
    positions = [10.0 - i * 0.25 for i in range(8)]
    p = write_dt1(tmp_path / "L.DT1", _zeros(), step=0.25, positions=positions)
    assert read_header(p).notes == ()


def test_one_trace_is_not_cross_checked(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", _zeros(n_traces=1))
    h = read_header(p)
    assert h.n_traces == 1 and h.notes == ()


@pytest.mark.parametrize("mode", ["CMP/WARR", "CMP", "WARR", "cmp"])
def test_a_cmp_sounding_is_not_a_profile(tmp_path, mode):
    p = write_dt1(tmp_path / "CMP.DT1", _zeros(), survey_mode=mode)
    assert read_header(p).not_a_profile == "a CMP/WARR velocity sounding, not a profile"


@pytest.mark.parametrize("mode", ["Reflection", None])
def test_a_reflection_line_is_a_profile(tmp_path, mode):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), survey_mode=mode)
    h = read_header(p)
    assert h.not_a_profile == "" and h.survey_mode == (mode or "")


def test_the_antenna_is_blank_without_a_frequency(tmp_path):
    assert read_header(write_dt1(tmp_path / "L.DT1", _zeros(), frequency=None)).antenna == ""


def test_a_missing_hd_is_refused_by_name(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", _zeros())
    p.with_suffix(".HD").unlink()
    with pytest.raises(Dt1Error, match=r"^no L\.HD beside it$"):
        read_header(p)


@pytest.mark.parametrize("key", ["NUMBER OF TRACES", "NUMBER OF PTS/TRC", "TOTAL TIME WINDOW"])
def test_a_missing_key_is_refused_by_name(tmp_path, key):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), drop_keys=(key,))
    with pytest.raises(Dt1Error, match=f"^its .HD has no {key}$"):
        read_header(p)


@pytest.mark.parametrize(
    "key, value, says",
    [
        ("NUMBER OF TRACES", "eight", "is not a number"),
        ("TIMEZERO AT POINT", "n/a", "is not a number"),
        ("STEP SIZE USED", "", "is not a number"),
        ("NUMBER OF TRACES", "0", "is not a whole number above 0"),
        ("NUMBER OF PTS/TRC", "50.5", "is not a whole number above 0"),
        ("TOTAL TIME WINDOW", "-400", "is not a number above 0"),
        ("TOTAL TIME WINDOW", "nan", "is not a number above 0"),
    ],
)
def test_a_bad_value_is_refused_by_name(tmp_path, key, value, says):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), hd_values={key: value})
    with pytest.raises(Dt1Error, match=f"^its .HD gives {key} as {value.strip()!r}, which {says}$"):
        read_header(p)


@pytest.mark.parametrize("cut", [1, 128, 128 + 30])
def test_a_short_file_is_refused_not_truncated(tmp_path, cut):
    p = write_dt1(tmp_path / "L.DT1", _zeros())
    full = p.read_bytes()
    p.write_bytes(full[: len(full) - cut])
    with pytest.raises(Dt1Error, match=r"do not divide into the 8 traces its \.HD gives"):
        read_header(p)


def test_a_file_shrunk_after_its_header_was_read_is_refused(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", _zeros())
    h = read_header(p)
    p.write_bytes(p.read_bytes()[: -(128 + 100)])
    with pytest.raises(Dt1Error, match="refusing to guess which is right"):
        trace_count(p, h)
    with pytest.raises(Dt1Error, match="refusing to guess which is right"):
        read_samples(p, h)


def test_a_width_other_than_2_or_4_is_refused(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", _zeros(n_samples=50, n_traces=8))
    p.write_bytes(p.read_bytes() + b"\0" * (8 * 50))  # 3 bytes a sample by size
    with pytest.raises(Dt1Error, match="^3-byte samples are not read; DT1 samples are 2 or 4"):
        read_header(p)


def test_trace_headers_that_disagree_with_the_size_are_refused(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), header_bytes_per_sample=4)
    with pytest.raises(
        Dt1Error, match="^its trace headers say 4-byte samples but the file size says 2$"
    ):
        read_header(p)


def test_a_zero_width_in_the_trace_header_is_not_checked(tmp_path):
    p = write_dt1(tmp_path / "L.DT1", _zeros(), header_bytes_per_sample=0)
    assert read_header(p).bytes_per_sample == 2


def test_a_dt1_line_opens_loads_and_takes_a_processing_step(tmp_path):
    rng = np.random.default_rng(1)
    data = rng.integers(-2000, 2000, size=(80, 12)).astype(np.int16)
    p = write_dt1(tmp_path / "LINE02.DT1", data, timezero_point=8.0, window_ns=40.0)
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    assert line.n_traces == 12 and isinstance(line.header, Dt1Header)
    np.testing.assert_allclose(line.distance_along(), np.arange(12) * 0.25)
    rg = Radargram.from_profile(line.load()[0])
    assert rg.dx_m == pytest.approx(0.25)
    assert rg.t0_ns == pytest.approx(-8.0 * 40.0 / 80)
    out = build_step("dewow", window_ns=4.0).apply(rg)
    assert out.data.shape == (80, 12) and np.isfinite(out.data).all()
