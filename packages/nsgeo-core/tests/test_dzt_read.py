from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io.dzt import DztError, read_header, read_samples, trace_count

from tests.synthetic import write_dzt


def test_round_trips_single_channel(tmp_path):
    rng = np.random.default_rng(0)
    data = rng.integers(-10_000, 10_000, size=(512, 37)).astype(np.int32)
    p = tmp_path / "a.DZT"
    write_dzt(p, data)
    out = read_samples(p)
    assert out.shape == (1, 512, 37)
    np.testing.assert_array_equal(out[0], data)


def test_round_trips_multi_channel(tmp_path):
    rng = np.random.default_rng(1)
    data = rng.integers(-10_000, 10_000, size=(2, 512, 21)).astype(np.int32)
    p = tmp_path / "b.DZT"
    write_dzt(p, data, n_channels=2)
    out = read_samples(p)
    assert out.shape == (2, 512, 21)
    np.testing.assert_array_equal(out, data)


def test_trace_count_matches(tmp_path):
    p = tmp_path / "c.DZT"
    write_dzt(p, np.zeros((512, 44), dtype=np.int32))
    assert trace_count(p, read_header(p)) == 44


def test_non_integer_trace_count_is_a_hard_error(tmp_path):
    """The diagnostic that caught a wrong header-size assumption against real
    files. Truncating instead would turn a wrong header size into
    plausible-looking but misaligned data."""
    p = tmp_path / "d.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32))
    with open(p, "ab") as fh:
        fh.write(b"\x00" * 7)  # a partial trace
    with pytest.raises(DztError, match="non-integer trace count"):
        read_samples(p)


def test_leading_zero_traces_are_preserved(tmp_path):
    """Recording starts before the cart moves. These are data, not corruption."""
    data = np.ones((512, 20), dtype=np.int32)
    data[:, :4] = 0
    p = tmp_path / "e.DZT"
    write_dzt(p, data)
    out = read_samples(p)
    assert out.shape == (1, 512, 20)
    assert not out[0, :, :4].any()
    assert out[0, :, 4:].all()


def test_empty_payload_raises(tmp_path):
    p = tmp_path / "f.DZT"
    write_dzt(p, np.zeros((512, 0), dtype=np.int32))
    with pytest.raises(DztError, match="no traces"):
        read_samples(p)


def test_rh_zero_is_not_applied_as_an_offset(tmp_path):
    """rh_zero is 105 in real files, which is not a valid sentinel. Applying it
    would shift every sample by a garbage offset."""
    data = np.full((512, 5), 1234, dtype=np.int32)
    p = tmp_path / "g.DZT"
    write_dzt(p, data)
    out = read_samples(p)
    assert out[0, 0, 0] == 1234
