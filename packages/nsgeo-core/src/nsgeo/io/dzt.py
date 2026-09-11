"""GSSI DZT reader.

Written from the format description and verified against ten real SIR-4000
files. See spec section 6a: several widely cited facts about this format do
not hold in real data, and each is called out at the point it matters.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MINHEADSIZE = 1024

#: Sample dtype by rh_bits. Only 32-bit has been validated against real files;
#: the 8- and 16-bit paths come from the format description and are untested.
_DTYPES = {8: "<u1", 16: "<i2", 32: "<i4"}


class DztError(Exception):
    """Raised when a DZT file is malformed or uses an unsupported variant."""


@dataclass(frozen=True)
class DztHeader:
    tag: int
    n_samples: int
    bits: int
    n_channels: int
    data_offset: int
    samples_per_second: float
    traces_per_metre: float
    range_ns: float
    position_ns: float
    epsr: float
    antenna: str
    zero: int

    @property
    def dt_ns(self) -> float:
        """Sample interval in nanoseconds."""
        return self.range_ns / self.n_samples

    @property
    def bytes_per_sample(self) -> int:
        return self.bits // 8

    @property
    def dtype(self) -> str:
        return _DTYPES[self.bits]


def parse_header(raw: bytes) -> DztHeader:
    """Parse a DZT header from at least the first 1024 bytes.

    All header *fields* live within the first 1024 bytes, which is why opening
    a survey is cheap. This is distinct from the header *size*, which is
    1024 * rh_data and is commonly far larger.
    """
    if len(raw) < MINHEADSIZE:
        raise DztError(f"file too short for a DZT header: {len(raw)} bytes")

    tag = struct.unpack_from("<H", raw, 0)[0]
    rh_data = struct.unpack_from("<H", raw, 2)[0]
    n_samples = struct.unpack_from("<H", raw, 4)[0]
    bits = struct.unpack_from("<H", raw, 6)[0]
    zero = struct.unpack_from("<h", raw, 8)[0]
    sps = struct.unpack_from("<f", raw, 10)[0]
    spm = struct.unpack_from("<f", raw, 14)[0]
    position = struct.unpack_from("<f", raw, 22)[0]
    range_ns = struct.unpack_from("<f", raw, 26)[0]
    n_channels = struct.unpack_from("<H", raw, 52)[0] or 1
    epsr = struct.unpack_from("<f", raw, 54)[0]
    antenna = raw[98:112].split(b"\x00")[0].decode("latin-1").strip()

    if n_samples == 0:
        raise DztError("header declares zero samples per trace")
    if range_ns <= 0:
        raise DztError(f"header declares a non-positive range: {range_ns} ns")
    if bits not in _DTYPES:
        raise DztError(f"unsupported bit depth {bits}; expected one of {sorted(_DTYPES)}")

    # Verified against real files: rh_data is 128, giving a 131072-byte
    # header. Assuming MINHEADSIZE here produces a non-integer trace count.
    data_offset = MINHEADSIZE * rh_data if rh_data < MINHEADSIZE else MINHEADSIZE * n_channels

    return DztHeader(
        tag=tag,
        n_samples=n_samples,
        bits=bits,
        n_channels=n_channels,
        data_offset=data_offset,
        samples_per_second=sps,
        traces_per_metre=spm,
        range_ns=range_ns,
        position_ns=position,
        epsr=epsr,
        antenna=antenna,
        zero=zero,
    )


def read_header(path: str | Path) -> DztHeader:
    """Read only the header. Cheap: reads 1024 bytes regardless of file size."""
    with open(path, "rb") as fh:
        return parse_header(fh.read(MINHEADSIZE))


def _bytes_per_trace(header: DztHeader) -> int:
    return header.n_samples * header.bytes_per_sample * header.n_channels


def trace_count(path: str | Path, header: DztHeader) -> int:
    """Number of traces, derived from file size. Raises if not a whole number."""
    payload = Path(path).stat().st_size - header.data_offset
    if payload <= 0:
        raise DztError(f"file has no traces after a {header.data_offset}-byte header")
    per = _bytes_per_trace(header)
    if payload % per:
        raise DztError(
            f"non-integer trace count: {payload} payload bytes is not divisible by "
            f"{per} bytes/trace. The header size ({header.data_offset}) is probably "
            f"wrong; refusing to truncate because that would silently misalign data."
        )
    return payload // per


def read_samples(path: str | Path, header: DztHeader | None = None) -> np.ndarray:
    """Read all samples as (n_channels, n_samples, n_traces).

    Channels are interleaved per trace on disk. Raw values are returned
    unmodified: no zero-offset is applied, because rh_zero is not trustworthy
    (it is 105 in real files, neither documented sentinel).
    """
    path = Path(path)
    if header is None:
        header = read_header(path)
    n_traces = trace_count(path, header)
    flat = np.fromfile(path, dtype=np.dtype(header.dtype), offset=header.data_offset)
    expected = n_traces * header.n_channels * header.n_samples
    if flat.size != expected:
        raise DztError(f"expected {expected} samples, read {flat.size}")
    return flat.reshape(n_traces, header.n_channels, header.n_samples).transpose(1, 2, 0)
