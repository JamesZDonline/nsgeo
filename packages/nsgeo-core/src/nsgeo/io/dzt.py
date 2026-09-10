"""GSSI DZT reader.

Written from the format description and verified against ten real SIR-4000
files. See spec section 6a: several widely cited facts about this format do
not hold in real data, and each is called out at the point it matters.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

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
