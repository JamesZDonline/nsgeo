from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io.dzt import DztError, parse_header, read_header

from tests.synthetic import write_dzt


def test_header_size_uses_rh_data_rule(tmp_path):
    """Verified against real files: rh_data=128 means a 131072-byte header,
    not the 1024-byte minimum. Getting this wrong yields a non-integer
    trace count and silently misaligned data."""
    p = tmp_path / "a.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), rh_data=128)
    h = read_header(p)
    assert h.data_offset == 131072


def test_header_size_falls_back_to_channel_rule(tmp_path):
    p = tmp_path / "b.DZT"
    write_dzt(p, np.zeros((2, 512, 10), dtype=np.int32), rh_data=1024, n_channels=2)
    h = read_header(p)
    assert h.data_offset == 2048


def test_parses_verified_real_world_field_values(tmp_path):
    p = tmp_path / "c.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32))
    h = read_header(p)
    assert h.tag == 2047  # real files use 0x07FF, not the cited 255
    assert h.n_samples == 512
    assert h.bits == 32
    assert h.n_channels == 1
    assert h.traces_per_metre == pytest.approx(60.0)
    assert h.range_ns == pytest.approx(110.864, abs=1e-3)
    assert h.antenna == "HS350US"


def test_dt_ns_is_range_over_samples(tmp_path):
    p = tmp_path / "d.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), range_ns=102.4)
    h = read_header(p)
    assert h.dt_ns == pytest.approx(0.2)


def test_rejects_short_file():
    with pytest.raises(DztError, match="too short"):
        parse_header(b"\x00" * 100)


def test_rejects_unknown_bit_depth():
    raw = bytearray(1024)
    import struct

    struct.pack_into("<H", raw, 0, 2047)
    struct.pack_into("<H", raw, 2, 128)
    struct.pack_into("<H", raw, 4, 512)
    struct.pack_into("<H", raw, 6, 24)  # unsupported
    struct.pack_into("<f", raw, 26, 110.864)  # a valid range, not what's under test here
    struct.pack_into("<H", raw, 52, 1)
    with pytest.raises(DztError, match="bit depth"):
        parse_header(bytes(raw))


def test_rejects_zero_samples():
    import struct

    raw = bytearray(1024)
    struct.pack_into("<H", raw, 0, 2047)
    struct.pack_into("<H", raw, 2, 128)
    struct.pack_into("<H", raw, 4, 0)
    struct.pack_into("<H", raw, 6, 32)
    struct.pack_into("<H", raw, 52, 1)
    with pytest.raises(DztError, match="samples"):
        parse_header(bytes(raw))


def test_rejects_non_positive_range():
    """`dt_ns` is `range_ns / n_samples`; a zero (or negative) `range_ns`
    yields `dt_ns == 0` without `n_samples` itself being zero, which the
    existing zero-samples guard does not catch. Downstream, Task 15 feeds a
    header's `dt_ns` straight into `ViewTransform.fit()` before samples ever
    load, well before `Radargram.__post_init__`'s `dt_ns > 0` check would see
    it -- so this must be rejected here, at the header boundary."""
    import struct

    raw = bytearray(1024)
    struct.pack_into("<H", raw, 0, 2047)
    struct.pack_into("<H", raw, 2, 128)
    struct.pack_into("<H", raw, 4, 512)
    struct.pack_into("<H", raw, 6, 32)
    struct.pack_into("<f", raw, 26, 0.0)  # rh_rng: zero range
    struct.pack_into("<H", raw, 52, 1)
    with pytest.raises(DztError, match="range"):
        parse_header(bytes(raw))


def test_multi_channel_samples_are_interleaved_per_trace(tmp_path):
    """On disk: trace0ch0, trace0ch1, trace1ch0, trace1ch1, ... Task 3's reader
    inverts exactly this order, so it is pinned here with distinct values."""
    data = np.zeros((2, 3, 2), dtype=np.int32)  # (channels, samples, traces)
    data[0] = [[10, 11], [12, 13], [14, 15]]  # channel 0
    data[1] = [[20, 21], [22, 23], [24, 25]]  # channel 1
    p = tmp_path / "i.DZT"
    write_dzt(p, data, n_channels=2, rh_data=1)  # 1024-byte header
    h = read_header(p)
    raw = np.fromfile(p, dtype="<i4", offset=h.data_offset)
    # trace 0: ch0 samples then ch1 samples; then trace 1 likewise
    assert raw.tolist() == [10, 12, 14, 20, 22, 24, 11, 13, 15, 21, 23, 25]
