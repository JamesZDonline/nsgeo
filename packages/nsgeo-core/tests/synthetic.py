"""Test-only DZT writer. Produces files with known headers and known samples
so the reader can be round-trip tested without committing real survey data."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

MINHEADSIZE = 1024


def write_dzt(
    path: Path,
    data: np.ndarray,
    *,
    traces_per_metre: float = 60.0,
    range_ns: float = 110.864,
    bits: int = 32,
    n_channels: int = 1,
    rh_data: int = 128,
    tag: int = 2047,
) -> None:
    """Write `data` (n_samples, n_traces) as a DZT file.

    For n_channels > 1, `data` is (n_channels, n_samples, n_traces) and
    channels are interleaved per trace, which is how GSSI writes them.
    """
    if data.ndim == 2:
        if n_channels != 1:
            raise ValueError(f"2D data requires n_channels=1, got n_channels={n_channels}")
        n_samples, n_traces = data.shape
        stack = data[None, :, :]
    elif data.ndim == 3:
        n_ch, n_samples, n_traces = data.shape
        if n_ch != n_channels:
            raise ValueError(
                f"data has shape {data.shape} but n_channels={n_channels}; "
                f"mismatch on first dimension"
            )
        stack = data
    else:
        raise ValueError(f"data must be 2D or 3D, got shape {data.shape}")

    head = bytearray(MINHEADSIZE)
    struct.pack_into("<H", head, 0, tag)
    struct.pack_into("<H", head, 2, rh_data)
    struct.pack_into("<H", head, 4, n_samples)
    struct.pack_into("<H", head, 6, bits)
    struct.pack_into("<h", head, 8, 105)  # rh_zero: junk, as in real files
    struct.pack_into("<f", head, 10, 250.0)  # rhf_sps
    struct.pack_into("<f", head, 14, traces_per_metre)
    struct.pack_into("<f", head, 18, 5.0)  # rhf_mpm
    struct.pack_into("<f", head, 22, -11.086)  # rhf_position
    struct.pack_into("<f", head, 26, range_ns)
    struct.pack_into("<H", head, 52, n_channels)
    struct.pack_into("<f", head, 54, 14.0)  # rhf_epsr
    head[98 : 98 + 7] = b"HS350US"

    headsize = MINHEADSIZE * rh_data if rh_data < MINHEADSIZE else MINHEADSIZE * n_channels
    blob = bytearray(headsize)
    blob[:MINHEADSIZE] = head

    dtype = {8: "<u1", 16: "<i2", 32: "<i4"}[bits]
    # interleave channels per trace: trace0ch0, trace0ch1, trace1ch0, ...
    interleaved = np.transpose(stack, (2, 0, 1)).astype(dtype).reshape(-1)
    path.write_bytes(bytes(blob) + interleaved.tobytes())
