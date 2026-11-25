"""The MALÅ reader, on synthetic files (M21b, spec §2 and §14)."""

from __future__ import annotations

import nsgeo.processing.dewow  # noqa: F401  (registers the step)
import numpy as np
import pytest
from nsgeo.geometry import GridPlacement
from nsgeo.io import MalaError, MalaHeader, read_header, read_samples, trace_count
from nsgeo.model import Line
from nsgeo.processing import Radargram, build_step

from tests.mala_data import write_mala, write_mala_pair

TIME_ZERO_NOTE = "time zero is not read from a MALÅ .rad: set one with a Time zero step"


def _zeros(n_samples: int = 50, n_traces: int = 8, dtype: type = np.int32) -> np.ndarray:
    return np.zeros((n_samples, n_traces), dtype=dtype)


def test_an_rd7_round_trips_its_samples_and_header(tmp_path):
    data = np.arange(-3000, 3000, dtype=np.int32).reshape(100, 60) * 1000
    p = write_mala(tmp_path / "DAT_0001.rd7", data, interval=0.5)
    h = read_header(p)
    assert isinstance(h, MalaHeader) and h.format_name == "MALÅ"
    assert (h.n_samples, h.n_traces, h.bytes_per_sample, h.n_channels) == (100, 60, 4, 1)
    assert h.dt_ns == pytest.approx(1000 / 5120) and h.position_ns == 0.0
    assert h.range_ns == pytest.approx(100 * 1000 / 5120)
    assert h.traces_per_metre == pytest.approx(2.0) and h.antenna == "GX450 HDR (v.1)"
    assert h.notes == (TIME_ZERO_NOTE,) and h.not_a_profile == "" and h.epsr == 0.0
    assert h.rad_path == tmp_path / "DAT_0001.rad" and h.trigger == "distance"
    assert h.signal_position == pytest.approx(102.734375)
    assert trace_count(p, h) == 60
    s = read_samples(p, h)
    assert s.dtype == np.int32 and s.shape == (1, 100, 60)
    np.testing.assert_array_equal(s[0], data)
    np.testing.assert_array_equal(read_samples(p), s)


def test_an_rd3_reads_on_its_rd7s_scale(tmp_path):
    column = [-(2**31), 2**31 - 1, -1, 0, 65535, 65536]
    data32 = np.array([column] * 4, dtype=np.int64).T.astype(np.int32)
    rd7, rd3 = write_mala_pair(tmp_path / "DAT_0002", data32)
    h = read_header(rd3)
    assert h.bytes_per_sample == 2 and h.n_traces == 4
    a, b = read_samples(rd3), read_samples(rd7)
    assert a.dtype == np.int32
    np.testing.assert_array_equal(a, b & ~np.int32(0xFFFF))
    assert a.min() == -(2**31) and a.max() == 32767 << 16


def test_the_rad_is_read_by_key_with_crlf_and_colons_in_values(tmp_path):
    p = write_mala(
        tmp_path / "DAT_0003.rd7",
        _zeros(),
        rad_suffix=".RAD",
        rad_extra=("COMMENT2:Wheel (30cm)=2", "TIME:12:04:33", "free line with no colon"),
        rad_values={"SAMPLES": " 50", "ANTENNAS": "  500MHz shielded=7 "},
    )
    h = read_header(p)
    assert h.n_samples == 50 and h.antenna == "500MHz shielded"
    assert h.rad_path == tmp_path / "DAT_0003.RAD"


def test_no_antenna_key_reads_as_no_antenna(tmp_path):
    assert read_header(write_mala(tmp_path / "D.rd7", _zeros(), antenna=None)).antenna == ""


def test_a_missing_rad_is_refused_by_name(tmp_path):
    p = write_mala(tmp_path / "DAT_0004.rd7", _zeros(), write_rad=False)
    with pytest.raises(MalaError, match=r"^no DAT_0004\.rad beside it$"):
        read_header(p)


@pytest.mark.parametrize("key", ["SAMPLES", "FREQUENCY", "LAST TRACE"])
def test_a_missing_key_is_refused_by_name(tmp_path, key):
    p = write_mala(tmp_path / "D.rd7", _zeros(), drop_keys=(key,))
    with pytest.raises(MalaError, match=f"^its .rad has no {key}$"):
        read_header(p)


@pytest.mark.parametrize(
    "key, value, what",
    [
        ("SAMPLES", "abc", "not a number"),
        ("SAMPLES", "50.5", "not a whole number above 0"),
        ("LAST TRACE", "0", "not a whole number above 0"),
        ("FREQUENCY", "-5120", "not a number above 0"),
        ("FREQUENCY", "nan", "not a number above 0"),
    ],
)
def test_a_bad_value_is_refused_by_name(tmp_path, key, value, what):
    p = write_mala(tmp_path / "D.rd7", _zeros(), rad_values={key: value})
    with pytest.raises(MalaError, match=rf"^its \.rad gives {key} as '{value}', which is {what}$"):
        read_header(p)


def test_a_timewindow_that_disagrees_is_refused(tmp_path):
    p = write_mala(tmp_path / "D.rd7", _zeros(), timewindow=12.0)
    with pytest.raises(
        MalaError,
        match=r"^its \.rad gives a 12 ns TIMEWINDOW but 50 samples at 5120 MHz span 9\.76562 ns: "
        r"refusing to guess which is right$",
    ):
        read_header(p)
    # Within 1 % is the same window, rounded; absent is not checked.
    assert read_header(write_mala(tmp_path / "E.rd7", _zeros(), timewindow=9.8))
    assert read_header(write_mala(tmp_path / "F.rd7", _zeros(), timewindow=None))


@pytest.mark.parametrize("cut", [1, 4 * 50, 4 * 50 + 2])
def test_a_short_file_is_refused_not_truncated(tmp_path, cut):
    p = write_mala(tmp_path / "D.rd7", _zeros())
    size = p.stat().st_size
    p.write_bytes(p.read_bytes()[: size - cut])
    message = rf"^{size - cut} bytes are not the 8 traces of 200 bytes its \.rad gives: refusing"
    with pytest.raises(MalaError, match=message):
        read_header(p)


def test_a_file_that_shrank_after_its_header_was_read_is_refused(tmp_path):
    p = write_mala(tmp_path / "D.rd7", _zeros())
    h = read_header(p)
    p.write_bytes(p.read_bytes()[:-200])
    with pytest.raises(MalaError, match="are not the 8 traces"):
        trace_count(p, h)
    with pytest.raises(MalaError, match="are not the 8 traces"):
        read_samples(p, h)


def test_an_rd3_renamed_rd7_is_refused(tmp_path):
    rd3 = write_mala(tmp_path / "D.rd3", _zeros(50, 8, np.int16))
    renamed = rd3.rename(tmp_path / "D.rd7")
    with pytest.raises(MalaError, match=r"^800 bytes are not the 8 traces of 200 bytes"):
        read_header(renamed)


def test_spacing_by_trigger(tmp_path):
    def header(name, **kw):
        return read_header(write_mala(tmp_path / f"{name}.rd7", _zeros(), **kw))

    h = header("dist", interval=0.25)
    assert h.traces_per_metre == pytest.approx(4.0) and h.notes == (TIME_ZERO_NOTE,)

    h = header("no-interval", interval=None, stop=None)
    assert h.traces_per_metre == 0.0
    no_interval = "distance-triggered with no DISTANCE INTERVAL: place it by hand"
    assert h.notes == (TIME_ZERO_NOTE, no_interval)

    h = header("time", distance_flag=0, time_flag=1)
    assert h.traces_per_metre == 0.0 and h.trigger == "time" and h.notes == (TIME_ZERO_NOTE,)

    h = header("other", distance_flag=0, time_flag=0)
    assert h.traces_per_metre == 0.0 and h.trigger == "other"

    h = header("off", interval=0.5, stop=7 * 0.5 * 1.02)
    assert h.traces_per_metre == pytest.approx(2.0)
    assert h.notes[1] == (
        "its start and stop positions step 0.51 m, not its DISTANCE INTERVAL 0.5: "
        "placed at the DISTANCE INTERVAL"
    )
    assert header("near", interval=0.5, stop=7 * 0.5 * 1.005).notes == (TIME_ZERO_NOTE,)
    assert header("no-stop", stop=None).notes == (TIME_ZERO_NOTE,)
    one = read_header(write_mala(tmp_path / "one.rd7", _zeros(50, 1), stop=99.0))
    assert one.notes == (TIME_ZERO_NOTE,)


def test_multichannel_siblings_are_refused_before_the_rad_is_looked_for(tmp_path):
    a1 = write_mala(tmp_path / "DAT_0001_A1.rd3", _zeros(dtype=np.int16), write_rad=False)
    write_mala(tmp_path / "DAT_0001_A2.RD3", _zeros(dtype=np.int16), write_rad=False)
    with pytest.raises(
        MalaError,
        match=r"^multichannel MALÅ files are not read yet: "
        r"DAT_0001_A1\.rd3 is one channel of DAT_0001$",
    ):
        read_header(a1)


def test_a_lone_channel_file_reads_and_a_sibling_of_another_kind_does_not_count(tmp_path):
    p = write_mala(tmp_path / "DAT_0005_A1.rd3", _zeros(dtype=np.int16))
    write_mala(tmp_path / "DAT_0005_A2.rd7", _zeros(), write_rad=False)
    write_mala(tmp_path / "DAT_0006_A2.rd3", _zeros(dtype=np.int16), write_rad=False)
    assert read_header(p).n_traces == 8


@pytest.mark.parametrize("key", ["CHANNELS", "NUMBER OF CH"])
def test_a_rad_giving_more_than_one_channel_is_refused(tmp_path, key):
    p = write_mala(tmp_path / "D.rd3", _zeros(dtype=np.int16), rad_extra=(f"{key}:4",))
    with pytest.raises(
        MalaError, match=r"^multichannel MALÅ files are not read yet: its \.rad gives 4 channels$"
    ):
        read_header(p)
    q = write_mala(tmp_path / "E.rd3", _zeros(dtype=np.int16), rad_extra=(f"{key}:1",))
    assert read_header(q).n_channels == 1


@pytest.mark.parametrize("signal_position", [102.734375, 0.0, None])
def test_signal_position_is_never_time_zero(tmp_path, signal_position):
    p = write_mala(tmp_path / "D.rd7", _zeros(), signal_position=signal_position)
    h = read_header(p)
    assert h.position_ns == 0.0 and h.signal_position == signal_position
    assert TIME_ZERO_NOTE in h.notes


def test_a_mala_line_opens_loads_and_takes_a_processing_step(tmp_path):
    rng = np.random.default_rng(1)
    data = rng.integers(-2000, 2000, size=(80, 12)).astype(np.int16)
    p = write_mala(tmp_path / "DAT_0007.rd3", data, frequency=2000.0, interval=0.25)
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    assert line.n_traces == 12 and isinstance(line.header, MalaHeader)
    np.testing.assert_allclose(line.distance_along(), np.arange(12) * 0.25)
    rg = Radargram.from_profile(line.load()[0])
    assert rg.dx_m == pytest.approx(0.25) and rg.t0_ns == 0.0
    out = build_step("dewow", window_ns=4.0).apply(rg)
    assert out.data.shape == (80, 12) and np.isfinite(out.data).all()
