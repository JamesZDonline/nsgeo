"""The SEG-Y reader, on synthetic RadExplorer-style files (M21c, spec §2 and §15)."""

from __future__ import annotations

import struct

import nsgeo.processing.dewow  # noqa: F401  (registers the step)
import numpy as np
import pytest
from nsgeo.geometry import GridPlacement
from nsgeo.io import (
    SegyError,
    SegyHeader,
    UnsupportedFormat,
    format_for,
    read_header,
    read_samples,
    trace_count,
)
from nsgeo.model import Line
from nsgeo.processing import Radargram, build_step
from nsgeo.slices import CubeFrame, PreparedLine, ZAxis, plan_line, stream_slice

from tests.segy_data import OTHER_TEXT, write_segy
from tests.synthetic import write_dzt


def _live(n_samples: int = 50, n_traces: int = 6, seed: int = 3) -> np.ndarray:
    """Samples with no exact zero in them, as recorded float data has none."""
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_samples, n_traces))
    return (signs * rng.uniform(0.5, 2.0, size=(n_samples, n_traces))).astype(np.float32)


def test_a_segy_round_trips_its_samples_and_header(tmp_path):
    data = np.linspace(-5, 5, 300 * 40, dtype=np.float32).reshape(300, 40)
    p = write_segy(tmp_path / "LINE01.sgy", data)
    h = read_header(p)
    assert isinstance(h, SegyHeader) and h.format_name == "SEG-Y" and h.variant == "RadExplorer"
    assert (h.n_samples, h.stored_samples, h.n_traces, h.n_channels) == (300, 300, 40, 1)
    assert h.dt_ns == pytest.approx(0.406) and h.position_ns == pytest.approx(-11.766)
    assert h.delay_ns == pytest.approx(11.766) and h.max_static_ns == 0.0
    assert h.traces_per_metre == pytest.approx(1 / 0.068) and h.step_m == pytest.approx(0.068)
    assert h.jumps == 0 and h.notes == () and h.antenna == "" and h.epsr == 0.0
    assert h.geographic_traces == 40 and h.not_a_profile == ""
    assert trace_count(p, h) == 40
    s = read_samples(p, h)
    assert s.dtype == np.float32 and s.shape == (1, 300, 40)
    np.testing.assert_array_equal(s[0], data)
    np.testing.assert_array_equal(read_samples(p), s)


def test_the_geographic_flag_is_read_little_endian(tmp_path):
    assert (
        read_header(write_segy(tmp_path / "A.sgy", _live(), geographic=False)).geographic_traces
        == 0
    )
    p = write_segy(tmp_path / "B.sgy", _live())
    raw = p.read_bytes()
    # Trace 2's flag bytes, as written: 01 00, which big-endian would be 256.
    at = 3600 + 2 * (240 + 4 * 50) + 226
    assert raw[at : at + 2] == b"\x01\x00"
    assert read_header(p).geographic_traces == 6


def test_times_are_picoseconds(tmp_path):
    h = read_header(write_segy(tmp_path / "A.sgy", _live(), dt_ps=1000, delay_ps=2500))
    assert h.dt_ns == pytest.approx(1.0) and h.range_ns == pytest.approx(50.0)
    assert h.position_ns == pytest.approx(-2.5)


def test_a_static_shift_is_undone(tmp_path):
    data = _live()
    statics = [800, 0, 10, 20, 30, 41]
    p = write_segy(tmp_path / "S.sgy", data, statics_ns=statics)
    h = read_header(p)
    assert h.stored_samples > 1900 and h.n_samples == 50
    assert h.range_ns == pytest.approx(50 * 0.406) and h.max_static_ns == 800
    assert h.notes == (
        "its traces carry a static shift of up to 800 ns: read as recorded, without it",
    )
    np.testing.assert_array_equal(read_samples(p, h)[0], data)


def test_a_line_without_a_bogus_first_static_keeps_its_trailing_zeros_out(tmp_path):
    data = _live()
    p = write_segy(tmp_path / "S.sgy", data, statics_ns=[5, 10, 20, 0, 3, 7], stored_samples=200)
    h = read_header(p)
    assert (h.stored_samples, h.n_samples) == (200, 50)
    np.testing.assert_array_equal(read_samples(p, h)[0], data)


def test_zeros_that_disagree_with_the_static_are_refused(tmp_path):
    data = _live()
    # Trace 2's recorded data truly begins with six exact zeros: cutting them
    # would misalign it, so the static (1 ns, 2.5 samples) refuses it.
    starts_with_zeros = data.copy()
    starts_with_zeros[:6, 1] = 0.0
    p = write_segy(tmp_path / "T.sgy", starts_with_zeros, statics_ns=[4, 1, 0, 0, 0, 0])
    with pytest.raises(
        SegyError,
        match=r"^trace 2's samples start 8 samples down, but its static of 1 ns is 2 samples: "
        r"refusing to guess which is right$",
    ):
        read_header(p)
    q = write_segy(
        tmp_path / "U.sgy", data, statics_ns=[4, 0, 0, 0, 0, 0], shifts=[10, 0, 12, 0, 0, 0]
    )
    with pytest.raises(
        SegyError, match=r"^trace 3's samples start 12 samples down, but its static of 0 ns"
    ):
        read_header(q)
    # Within 4 samples plus 1 % of the shift is the same shift, rounded.
    r = write_segy(
        tmp_path / "V.sgy", data, statics_ns=[800, 0, 0, 0, 0, 0], shifts=[1990, 4, 0, 0, 0, 0]
    )
    np.testing.assert_array_equal(read_samples(r)[0], data)


def test_an_all_zero_trace_reads_as_zeros(tmp_path):
    data = _live()
    data[:, 3] = 0.0
    p = write_segy(tmp_path / "S.sgy", data, statics_ns=[100, 2, 3, 900, 5, 6])
    h = read_header(p)
    assert h.n_samples == 50
    np.testing.assert_array_equal(read_samples(p, h)[0], data)


def test_without_statics_zeros_are_kept(tmp_path):
    data = _live()
    data[:7, :] = 0.0
    data[-3:, 2] = 0.0
    p = write_segy(tmp_path / "S.sgy", data)
    h = read_header(p)
    assert h.n_samples == 50 and h.notes == ()
    np.testing.assert_array_equal(read_samples(p, h)[0], data)


def test_spacing_from_trace_coordinates(tmp_path):
    def header(name, data=None, **kw):
        return read_header(
            write_segy(tmp_path / f"{name}.sgy", _live(n_traces=11) if data is None else data, **kw)
        )

    # Integer millimetres alternating 68 and 69: the mean, not the median.
    x = np.cumsum([0] + [68, 69] * 5)
    h = header("mean", x_mm=x)
    assert h.step_m == pytest.approx(0.0685) and h.traces_per_metre == pytest.approx(1 / 0.0685)
    assert header("scalar0", x_mm=np.arange(11) * 2, scalar=0).step_m == pytest.approx(2.0)
    assert header("scalar10", x_mm=np.arange(11) * 3, scalar=10).step_m == pytest.approx(30.0)
    h = header("diagonal", x_mm=np.arange(11) * 30, y_mm=np.arange(11) * 40)
    assert h.step_m == pytest.approx(0.05)

    jumped = np.cumsum([0] + [68] * 4 + [274] + [68] * 2 + [3149] + [68] * 2)
    h = header("jumps", x_mm=jumped)
    assert h.jumps == 2 and h.step_m == pytest.approx(0.068)
    assert h.notes == (
        "its trace coordinates jump at 2 traces, the largest 3.15 m at trace 9: "
        "placed at an even 0.068 m",
    )
    assert h.traces_per_metre == pytest.approx(1 / 0.068)

    h = header("arcsec", units=2)
    assert h.traces_per_metre == 0.0 and h.step_m == 0.0
    assert h.notes == (
        "its trace coordinates are in arc seconds, not metres along the line: place it by hand",
    )
    h = header("still", x_mm=[0] * 11)
    assert (h.traces_per_metre, h.step_m, h.jumps, h.notes) == (0.0, 0.0, 0, ())
    h = header("one", data=_live(n_traces=1), x_mm=[500])
    assert (h.traces_per_metre, h.notes) == (0.0, ())


def test_no_coordinate_reaches_the_header(tmp_path):
    easting = 712_345_000
    northing = 1_812_345_000
    x = easting + np.arange(11) * 68
    y = northing + np.arange(11) * 0
    h = read_header(write_segy(tmp_path / "S.sgy", _live(n_traces=11), x_mm=x, y_mm=y))
    assert h.step_m == pytest.approx(0.068)
    text = repr(h)
    for value in (easting, northing, easting / 1000, northing / 1000):
        assert f"{value:g}" not in text and str(value) not in text


def _refused(tmp_path, message, data=None, **kw):
    p = write_segy(tmp_path / "R.sgy", _live() if data is None else data, **kw)
    with pytest.raises(SegyError, match=message):
        read_header(p)


def test_other_software_is_refused_quoting_its_text_header(tmp_path):
    _refused(
        tmp_path,
        r"^not a RadExplorer SEG-Y, the only kind nsgeo reads yet: its text header begins "
        r"'C 1 CLIENT                        COMPANY'$",
        text=OTHER_TEXT,
    )
    _refused(tmp_path, r"its text header begins 'C 1 CLIENT", text=OTHER_TEXT, ascii_text=True)


@pytest.mark.parametrize(
    "kw, message",
    [
        ({"little_endian": True}, r"^little-endian SEG-Y is not read yet$"),
        (
            {"format_code": 1},
            r"^its samples are in format 1: only IEEE float \(format 5\) is read yet$",
        ),
        ({"dt_ps": 0}, r"^its binary header gives the sample interval as 0, which is not a whole"),
        ({"extended": 1}, r"^extended text headers are not read yet$"),
        (
            {"trace_samples": {3: 49}},
            r"^trace 4 has 49 samples, not the 50 its binary header gives: SEG-Y with traces of "
            r"different lengths is not read yet$",
        ),
        (
            {"trace_dt": {1: 400}},
            r"^trace 2 gives a 400 ps sample interval, not the 406 ps its binary header gives: "
            r"refusing to guess which is right$",
        ),
        (
            {"delays": {5: 9766}},
            r"^its traces start at different delays, 9\.766 to 11\.766 ns: not read yet$",
        ),
    ],
)
def test_what_is_refused(tmp_path, kw, message):
    _refused(tmp_path, message, **kw)


def test_a_truncated_or_short_file_is_refused(tmp_path):
    p = write_segy(tmp_path / "R.sgy", _live())
    raw = p.read_bytes()
    p.write_bytes(raw[:-3])
    with pytest.raises(
        SegyError,
        match=r"^its 2637 bytes of traces are not whole traces of 440 bytes: "
        r"refusing to guess where they start$",
    ):
        read_header(p)
    p.write_bytes(raw[:3000])
    with pytest.raises(SegyError, match=r"^3000 bytes: too short to be a SEG-Y file$"):
        read_header(p)


def test_a_dzt_renamed_sgy_is_refused_by_its_text_header(tmp_path):
    dzt = tmp_path / "FILE__001.DZT"
    write_dzt(dzt, np.zeros((512, 40), dtype=np.int32))
    renamed = dzt.rename(tmp_path / "NOT_SEGY.sgy")
    with pytest.raises(SegyError, match=r"^not a RadExplorer SEG-Y"):
        read_header(renamed)


def test_a_file_that_changed_after_its_header_was_read_is_refused(tmp_path):
    p = write_segy(tmp_path / "S.sgy", _live(), statics_ns=[0, 10, 0, 0, 0, 0])
    h = read_header(p)
    write_segy(tmp_path / "S.sgy", _live(n_traces=7), statics_ns=[0, 10, 0, 0, 0, 0, 0])
    with pytest.raises(SegyError, match=r"^its samples changed after its header was read$"):
        trace_count(p, h)
    write_segy(
        tmp_path / "S.sgy",
        _live(n_samples=40),
        statics_ns=[0, 10, 0, 0, 0, 0],
        stored_samples=h.stored_samples,
    )
    with pytest.raises(SegyError, match=r"^its samples changed after its header was read$"):
        read_samples(p, h)


def test_the_vm_beside_a_line_is_not_a_radar_file(tmp_path):
    with pytest.raises(UnsupportedFormat):
        format_for(tmp_path / "LINE01.sgy.vm")
    assert format_for(tmp_path / "LINE01.SEGY").name == "SEG-Y"


def test_a_segy_line_opens_loads_slices_and_takes_a_processing_step(tmp_path):
    data = _live(n_samples=80, n_traces=12)
    p = write_segy(
        tmp_path / "LINE07.sgy", data, statics_ns=[700] + [3] * 11, x_mm=np.arange(12) * 250
    )
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    assert line.n_traces == 12 and isinstance(line.header, SegyHeader)
    np.testing.assert_allclose(line.distance_along(), np.arange(12) * 0.25)
    rg = Radargram.from_profile(line.load()[0])
    assert rg.dx_m == pytest.approx(0.25) and rg.t0_ns == pytest.approx(-11.766)
    out = build_step("dewow", window_ns=4.0).apply(rg)
    assert out.data.shape == (80, 12) and np.isfinite(out.data).all()

    # Float samples through the slice binning (C5): three lines across a small frame.
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=0.5, nx=8, ny=4, crs="EPSG:32633")
    z = ZAxis.from_range(0.0, 15.0, 0.406)
    lines = []
    for k in range(3):
        q = write_segy(tmp_path / f"G{k}.sgy", _live(80, 12, seed=k), statics_ns=[650] + [k] * 11)
        h = read_header(q)
        samples = read_samples(q, h)[0]
        assert samples.dtype == np.float32
        coords = np.column_stack([np.linspace(0.1, 3.9, 12), np.full(12, 0.25 + k * 0.5)])
        lines.append(
            PreparedLine(
                key=q.name, data=samples, dt_ns=h.dt_ns, t0_ns=h.position_ns, coords=coords
            )
        )
    plans = [plan_line(ln, frame, z) for ln in lines]
    mean, count = stream_slice(lines, plans, frame, z, 0, 5)
    assert count.sum() > 0 and np.isfinite(mean[count > 0]).all()


def test_binary_header_words_are_where_the_standard_puts_them(tmp_path):
    p = write_segy(tmp_path / "S.sgy", _live())
    raw = p.read_bytes()
    assert struct.unpack(">hhh", raw[3216:3218] + raw[3220:3222] + raw[3224:3226]) == (406, 50, 5)
