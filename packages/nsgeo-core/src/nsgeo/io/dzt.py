"""GSSI DZT reader.

Written from the format description and verified against real SIR-4000 files
(32-bit) and pulseEKKO lines exported to DZT by EKKO_Project (16-bit). See
spec section 6a: several widely cited facts about this format do not hold in
real data, and each is called out at the point it matters.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MINHEADSIZE = 1024

#: On-disk sample dtype by rh_bits. 8- and 16-bit samples are unsigned offset
#: binary, centred on `_CENTRES`; 32-bit samples are signed and centred near
#: zero. Verified for 16-bit (pulseEKKO export: values 17351..42461, midpoint
#: 32768) and 32-bit (SIR-4000). Reading 16-bit as signed wraps every sample
#: just below the centre to about +32767 and just above to about -32767, which
#: loads without error but draws a banded, scrambled profile. 8-bit follows
#: the same convention by the format description and has no real file yet.
_DTYPES = {8: "<u1", 16: "<u2", 32: "<i4"}

#: The value an unsigned sample takes at zero amplitude, by rh_bits.
_CENTRES = {8: 1 << 7, 16: 1 << 15, 32: 0}

#: The leading samples of every trace that are a per-trace header, not radar
#: data. Verified in both real variants, with different contents: SIR-4000
#: writes a trace counter (0, 1, 2, ...) then a mark word (0, or 0x9201 on a
#: marked trace); the pulseEKKO export writes 0xFFFF then 0xE800 on every
#: trace. They are set to zero amplitude on read rather than trimmed, so the
#: sample count and the time of every sample stay exactly as the header says.
TRACE_HEADER_SAMPLES = 2


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
        """The on-disk sample dtype (not the dtype `read_samples` returns)."""
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
    if not math.isfinite(range_ns) or range_ns <= 0:
        raise DztError(f"header declares a non-finite or non-positive range: {range_ns} ns")
    if not math.isfinite(position):
        raise DztError(f"header declares a non-finite position (t0): {position} ns")
    if bits not in _DTYPES:
        raise DztError(f"unsupported bit depth {bits}; expected one of {sorted(_DTYPES)}")

    # Verified against real files: rh_data is 128, giving a 131072-byte
    # header. Assuming MINHEADSIZE here produces a non-integer trace count.
    data_offset = MINHEADSIZE * rh_data if rh_data < MINHEADSIZE else MINHEADSIZE * n_channels
    if data_offset < MINHEADSIZE:
        # Only reachable with rh_data == 0, and then the samples would be
        # read starting inside the header itself. `trace_count`'s
        # divisibility guard does not catch it -- a header length is itself
        # a whole multiple of the trace size often enough that the count
        # divides evenly (measured on a real file with rh_data zeroed: 672
        # traces against a true 608), so 64 traces of raw header bytes are
        # prepended and every position along the line shifts by about a
        # metre, silently. Cannot reject a real file: the observed value
        # across all ten is 131072, and the `else` branch floors at
        # 1024 * n_channels.
        raise DztError(
            f"header declares rh_data={rh_data}, putting the start of the "
            f"samples at byte {data_offset}, inside the {MINHEADSIZE}-byte "
            f"header; refusing to read header bytes as traces because that "
            f"would shift every position along the line"
        )

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
    """Read all samples as signed int32, shape (n_channels, n_samples, n_traces).

    Channels are interleaved per trace on disk. Amplitudes are otherwise raw,
    with two exceptions, both decoding rather than processing:

    - 8- and 16-bit samples have their offset-binary centre subtracted, so
      every bit depth comes back signed and centred on zero. The centre comes
      from the bit depth, never from rh_zero: rh_zero is 105 in real SIR-4000
      files (neither documented sentinel), though the 16-bit pulseEKKO export
      does write 0x8000 there.
    - The first `TRACE_HEADER_SAMPLES` samples of each trace (in each channel)
      are set to 0, because they are a per-trace header, not radar data.
      Multi-channel files are unverified against real data on this point.
    """
    path = Path(path)
    if header is None:
        header = read_header(path)
    n_traces = trace_count(path, header)
    flat = np.fromfile(path, dtype=np.dtype(header.dtype), offset=header.data_offset)
    expected = n_traces * header.n_channels * header.n_samples
    if flat.size != expected:
        raise DztError(f"expected {expected} samples, read {flat.size}")
    samples = flat.astype(np.int32, copy=False)
    centre = _CENTRES[header.bits]
    if centre:
        samples -= centre
    traces = samples.reshape(n_traces, header.n_channels, header.n_samples)
    traces[:, :, :TRACE_HEADER_SAMPLES] = 0
    return traces.transpose(1, 2, 0)
