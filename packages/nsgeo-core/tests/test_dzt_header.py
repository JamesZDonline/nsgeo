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
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), rh_data=1024, n_channels=2)
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


def test_rejects_unknown_bit_depth(tmp_path):
    raw = bytearray(1024)
    import struct

    struct.pack_into("<H", raw, 0, 2047)
    struct.pack_into("<H", raw, 2, 128)
    struct.pack_into("<H", raw, 4, 512)
    struct.pack_into("<H", raw, 6, 24)  # unsupported
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
