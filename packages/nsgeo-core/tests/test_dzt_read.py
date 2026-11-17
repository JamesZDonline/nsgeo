from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io.dzt import TRACE_HEADER_SAMPLES, DztError, read_header, read_samples, trace_count

from tests.synthetic import write_dzt


def test_round_trips_single_channel(tmp_path):
    rng = np.random.default_rng(0)
    data = rng.integers(-10_000, 10_000, size=(512, 37)).astype(np.int32)
    p = tmp_path / "a.DZT"
    write_dzt(p, data)
    out = read_samples(p)
    assert out.shape == (1, 512, 37)
    np.testing.assert_array_equal(out[0, 2:], data[2:])


def test_round_trips_multi_channel(tmp_path):
    rng = np.random.default_rng(1)
    data = rng.integers(-10_000, 10_000, size=(2, 512, 21)).astype(np.int32)
    p = tmp_path / "b.DZT"
    write_dzt(p, data, n_channels=2)
    out = read_samples(p)
    assert out.shape == (2, 512, 21)
    np.testing.assert_array_equal(out[:, 2:], data[:, 2:])


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
    assert out[0, 2:, 4:].all()


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
    assert out[0, 2, 0] == 1234


@pytest.mark.parametrize("bits", [8, 16, 32])
def test_every_bit_depth_comes_back_signed_and_centred(tmp_path, bits):
    """8- and 16-bit samples are unsigned offset binary on disk. Read as
    signed, a 16-bit sample just below the 32768 centre wraps to about +32767:
    the pulseEKKO export loaded without error and drew a scrambled profile."""
    lim = {8: 100, 16: 15_000, 32: 10_000_000}[bits]
    rng = np.random.default_rng(bits)
    data = rng.integers(-lim, lim, size=(64, 9)).astype(np.int32)
    data[2:4] = [[-1], [1]]  # either side of the centre: where signed reading wraps
    p = tmp_path / "h.DZT"
    write_dzt(p, data, bits=bits)
    out = read_samples(p)
    assert out.dtype == np.int32
    np.testing.assert_array_equal(out[0, 2:], data[2:])


def test_sixteen_bit_centre_is_decoded_from_the_raw_bytes(tmp_path):
    """Pins the on-disk encoding independently of the test writer: raw 32768
    is zero amplitude, 32767 is -1, 32769 is +1."""
    p = tmp_path / "i.DZT"
    write_dzt(p, np.zeros((4, 3), dtype=np.int32), bits=16, rh_data=1)
    raw = np.array([[0xFFFF, 0xE800, 32767, 32769]] * 3, dtype="<u2")
    p.write_bytes(p.read_bytes()[:1024] + raw.tobytes())
    out = read_samples(p)
    np.testing.assert_array_equal(out[0, :, 0], [0, 0, -1, 1])


@pytest.mark.parametrize(
    ("bits", "words"),
    [
        (32, lambda i: (i, 0x9201 if i == 4 else 0)),  # SIR-4000: counter, mark word
        (16, lambda i: (0xFFFF - (1 << 15), 0xE800 - (1 << 15))),  # pulseEKKO export
    ],
)
def test_per_trace_header_samples_read_as_zero(tmp_path, bits, words):
    """The first two samples of every trace are a per-trace header in both real
    variants, with different contents. Zeroed, not trimmed: the sample count
    and every sample's time stay as the header says."""
    data = np.full((32, 8), 7, dtype=np.int32)
    for i in range(8):
        data[:TRACE_HEADER_SAMPLES, i] = words(i)
    p = tmp_path / "j.DZT"
    write_dzt(p, data, bits=bits)
    out = read_samples(p)
    assert out.shape == (1, 32, 8)
    assert not out[0, :TRACE_HEADER_SAMPLES].any()
    assert (out[0, TRACE_HEADER_SAMPLES:] == 7).all()


def test_per_trace_header_is_zeroed_in_every_channel(tmp_path):
    data = np.full((2, 16, 5), 3, dtype=np.int32)
    p = tmp_path / "k.DZT"
    write_dzt(p, data, n_channels=2)
    out = read_samples(p)
    assert not out[:, :TRACE_HEADER_SAMPLES].any()
    assert (out[:, TRACE_HEADER_SAMPLES:] == 3).all()
