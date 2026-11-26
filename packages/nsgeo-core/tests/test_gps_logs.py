"""Each format's GPS log, through the registry (M21d, radar formats spec §16).

Every coordinate here is made up, about the origin the GPS tests already use.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pytest
from nsgeo.geometry.track import gps_length_note, track_from_log
from nsgeo.io import (
    NO_GPS_FORMAT,
    QUALITY_UNKNOWN,
    DzgLog,
    MalaError,
    NoGpsLog,
    RadarFileError,
    UnsupportedFormat,
    gps_formats,
    read_gps,
    read_header,
    trace_count,
)

from tests.dt1_data import write_dt1
from tests.dzg_data import write_dzg
from tests.mala_data import write_cor, write_mala
from tests.segy_data import write_segy
from tests.synthetic import write_dzt

LAT0, LON0 = 45.2, 10.5
M_PER_DEG = 111_320.0


def to_xy(lon, lat):
    """A flat local projection about the made-up origin."""
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    return (lon - LON0) * M_PER_DEG * math.cos(math.radians(LAT0)), (lat - LAT0) * M_PER_DEG


def north(metres: float) -> float:
    return LAT0 + metres / M_PER_DEG


def _log(path):
    h = read_header(path)
    return read_gps(path, h, trace_count(path, h))


# ---- the registry --------------------------------------------------------------


def test_gps_formats_are_dzt_mala_and_segy():
    assert [f.name for f in gps_formats()] == ["GSSI DZT", "MALÅ", "SEG-Y"]


def test_a_dzt_reads_its_dzg_and_says_when_there_is_none(tmp_path):
    p = tmp_path / "FILE__001.DZT"
    write_dzt(p, np.zeros((64, 60), dtype=np.int32))
    with pytest.raises(NoGpsLog, match="^no DZG beside it$"):
        _log(p)
    write_dzg(p.with_suffix(".DZG"), [(0, LAT0, LON0, 4), (59, north(5), LON0, 4)])
    log = _log(p)
    assert [f.trace for f in log.fixes] == [0, 59] and log.n_fixed == 2


def test_a_dt1_has_no_gps_source(tmp_path):
    p = write_dt1(tmp_path / "LINE01.DT1", np.zeros((100, 10), dtype=np.int16))
    with pytest.raises(UnsupportedFormat, match=f"^{NO_GPS_FORMAT}$"):
        _log(p)
    assert issubclass(NoGpsLog, RadarFileError)


def test_a_header_of_another_format_is_refused(tmp_path):
    dzt = tmp_path / "FILE__001.DZT"
    write_dzt(dzt, np.zeros((64, 60), dtype=np.int32))
    mala = write_mala(tmp_path / "DAT_0001.rd7", np.zeros((50, 8), dtype=np.int32))
    with pytest.raises(RadarFileError, match="header was given to the MALÅ reader"):
        read_gps(mala, read_header(dzt), 8)


# ---- MALÅ .cor -----------------------------------------------------------------


def _mala(tmp_path, rows, n_traces=40, name="DAT_0001.rd7"):
    p = write_mala(tmp_path / name, np.zeros((50, n_traces), dtype=np.int32))
    write_cor(p.with_suffix(".cor"), rows)
    return p


def test_a_cor_reads_with_its_traces_counted_from_one(tmp_path):
    rows = [(1, LAT0, LON0, 2), (20, north(10), LON0, 1), (40, north(20), LON0, 2)]
    log = _log(_mala(tmp_path, rows))
    assert isinstance(log, DzgLog) and (log.bad_checksum, log.unpaired) == (0, 0)
    assert [f.trace for f in log.fixes] == [0, 19, 39]
    assert [f.quality for f in log.fixes] == [2, 1, 2]
    assert log.fixes[1].lat == pytest.approx(north(10)) and log.fixes[1].lon == pytest.approx(LON0)
    assert log.fixes[0].alt_m == 12.5 and log.fixes[0].geoid_m is None
    assert log.fixes[1].utc_s == 12 * 3600 + 1 and log.n_fixed == 0


def test_a_cor_south_and_west_are_negative(tmp_path):
    log = _log(_mala(tmp_path, [(1, -LAT0, -LON0, 2), (2, -LAT0, -LON0 - 0.001, 2)]))
    assert log.fixes[0].lat == pytest.approx(-LAT0) and log.fixes[1].lon == pytest.approx(
        -LON0 - 0.001
    )


def test_a_cor_naming_the_last_trace_reads_and_one_past_it_is_refused(tmp_path):
    assert (
        _log(_mala(tmp_path, [(1, LAT0, LON0, 2), (40, north(5), LON0, 2)])).fixes[-1].trace == 39
    )
    with pytest.raises(MalaError, match="^its .cor names trace 41, but the line has 40 traces$"):
        _log(_mala(tmp_path, [(1, LAT0, LON0, 2), (41, north(5), LON0, 2)], name="DAT_0002.rd7"))
    with pytest.raises(MalaError, match="^its .cor names trace 0, but the line has 40 traces$"):
        _log(_mala(tmp_path, [(0, LAT0, LON0, 2), (4, north(5), LON0, 2)], name="DAT_0003.rd7"))


def test_cor_errors_name_the_row(tmp_path):
    p = _mala(tmp_path, [(1, LAT0, LON0, 2), (5, north(5), LON0, 2)])
    cor = p.with_suffix(".cor")
    good = cor.read_text(encoding="latin-1").splitlines()

    def refused(second, message):
        cor.write_text("\r\n".join([good[0], second]) + "\r\n", encoding="latin-1")
        with pytest.raises(MalaError, match=message):
            _log(p)

    cols = good[1].split("\t")
    refused("\t".join(cols[:9]), r"^its \.cor row 2 has 9 columns, not 10$")
    refused(
        "\t".join(["x", *cols[1:]]),
        r"^its \.cor row 2 gives the trace as 'x', which is not a number$",
    )
    bad_lat = [*cols[:3], "north", *cols[4:]]
    refused("\t".join(bad_lat), r"^its \.cor row 2 gives the latitude as 'north'")
    refused(
        "\t".join(["1", *cols[1:]]),
        r"^its \.cor row 2 names trace 1 after trace 1: trace numbers must rise$",
    )


def test_a_missing_cor_is_no_gps_log(tmp_path):
    p = write_mala(tmp_path / "DAT_0009.rd7", np.zeros((50, 8), dtype=np.int32))
    with pytest.raises(NoGpsLog, match=r"^no DAT_0009\.cor beside it$"):
        _log(p)


# ---- SEG-Y trace positions -----------------------------------------------------


def _positions(n, every=1):
    """Made-up positions walking north, changing every `every` traces."""
    return np.array([(LON0, north(0.2 * (i // every))) for i in range(n)])


def test_segy_repeats_collapse_to_the_first_trace_of_each_run(tmp_path):
    data = np.ones((40, 30), dtype=np.float32)
    log = _log(write_segy(tmp_path / "LINE01.sgy", data, positions=_positions(30, every=3)))
    assert [f.trace for f in log.fixes] == list(range(0, 30, 3))
    assert {f.quality for f in log.fixes} == {QUALITY_UNKNOWN}
    assert log.fixes[1].lat == pytest.approx(north(0.2), abs=2e-6)
    assert log.fixes[0].utc_s is None and log.fixes[0].alt_m is None


def test_segy_traces_without_the_flag_are_skipped(tmp_path):
    data = np.ones((40, 10), dtype=np.float32)
    p = write_segy(tmp_path / "LINE01.sgy", data, positions=_positions(10))
    raw = bytearray(p.read_bytes())
    for i in (0, 1, 2):
        at = 3600 + i * (240 + 4 * 40) + 226
        raw[at : at + 2] = b"\x00\x00"
    p.write_bytes(bytes(raw))
    assert [f.trace for f in _log(p).fixes] == list(range(3, 10))


def test_segy_without_positions_is_no_gps_log(tmp_path):
    p = write_segy(tmp_path / "LINE01.sgy", np.ones((40, 10), dtype=np.float32), geographic=False)
    with pytest.raises(NoGpsLog, match="^its traces carry no GPS positions$"):
        _log(p)


# ---- placement and the length check --------------------------------------------


def test_logs_without_rtk_place_on_all_their_fixes(tmp_path):
    rows = [(1 + 4 * i, north(2.0 * i), LON0, 2) for i in range(10)]
    log = _log(_mala(tmp_path, rows))
    t = track_from_log(log, to_xy, "LOCAL", smooth_m=4.0)
    assert t.anchor_on == "all" and t.smooth_m == 4.0 and len(t.anchors()) == 10


def _jitter_log(length_m: float, n: int = 101, jitter: float = 1.0, quality: int = 2) -> DzgLog:
    from nsgeo.io import DzgFix

    fixes = []
    for i in range(n):
        east = (jitter if i % 2 else -jitter) / (M_PER_DEG * math.cos(math.radians(LAT0)))
        lat = north(length_m * i / (n - 1))
        fixes.append(DzgFix(10 * i, None, lat, LON0 + east, quality, None, None, None, None))
    return DzgLog(tuple(fixes), 0, 0)


@pytest.mark.parametrize("ratio, noted", [(1.0, False), (1.1, False), (1.3, True), (2.0, True)])
def test_the_length_note_compares_the_thinned_track_with_the_wheel(tmp_path, ratio, noted):
    p = write_mala(tmp_path / "DAT_0001.rd7", np.zeros((50, 1001), dtype=np.int32), interval=0.1)
    header = read_header(p)  # 10 traces a metre: the wheel says 100 m over 1000 traces
    note = gps_length_note(_jitter_log(100.0 * ratio), to_xy, header)
    # 2 m of peak-to-peak jitter still adds a few per cent after thinning.
    if noted:
        assert note is not None
        match = re.fullmatch(
            r"its GPS track is (\d+) m but its wheel says 100 m: check which is right", note
        )
        assert match and 100 * ratio <= int(match.group(1)) <= 110 * ratio
    else:
        assert note is None


def test_no_length_note_without_a_wheel_or_with_a_short_track(tmp_path):
    timed = write_mala(
        tmp_path / "DAT_0001.rd7", np.zeros((50, 1001), dtype=np.int32), distance_flag=0
    )
    assert gps_length_note(_jitter_log(200.0), to_xy, read_header(timed)) is None
    wheel = write_mala(
        tmp_path / "DAT_0002.rd7", np.zeros((50, 1001), dtype=np.int32), interval=0.1
    )
    assert gps_length_note(_jitter_log(3.0, jitter=0.0), to_xy, read_header(wheel)) is None


def test_messages_hold_no_coordinate(tmp_path):
    rows = [(1, LAT0, LON0, 2), (41, north(5), LON0, 2)]
    with pytest.raises(MalaError) as err:
        _log(_mala(tmp_path, rows))
    for value in (LAT0, LON0, f"{LAT0:.6f}", f"{LON0:.6f}"):
        assert str(value) not in str(err.value)
