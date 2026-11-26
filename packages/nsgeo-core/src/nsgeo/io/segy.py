"""SEG-Y reader, for the files RadExplorer exports (spec M21 §2, §15).

Verified against eighteen lines of one survey:

- Big-endian SEG-Y: a 3,200-byte EBCDIC text header, a 400-byte binary
  header, then per trace a 240-byte header and IEEE float32 samples (format
  5). Every trace has the binary header's sample count.
- Times are in **picoseconds**, as the text header says, not the standard's
  microseconds.
- The geographic flag (bytes 227-228) and the marks (237-240) are
  little-endian inside the big-endian file. The flag is counted here; the
  coordinates are not read (M21d), nor are the marks (C11).
- The files are **static-shifted**: each trace's samples are pushed down by
  its static (bytes 101-102, whole ns) and padded with exact zeros. Each trace
  is read from its first non-zero sample, which undoes it (§15); the static
  only cross-checks that shift.
- Time zero is the delay (bytes 109-110) *below* the first sample:
  `position_ns = -delay`.
- Trace spacing is the mean of the regular steps between the traces'
  coordinates. No coordinate is kept: in other files they may be real
  eastings and northings.

SEG-Y from other software is refused by name (C9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np

from nsgeo.io.dzg import QUALITY_UNKNOWN, DzgFix, DzgLog
from nsgeo.io.header import NoGpsLog, RadarFileError, RadarHeader

FILE_HEADER_BYTES = 3600
TEXT_HEADER_BYTES = 3200
TRACE_HEADER_BYTES = 240
#: Within this fraction of the median step, a step between traces is regular.
_STEP_TOLERANCE = 0.05
#: A trace's leading zeros may differ from its static by this many samples,
#: plus `_STATIC_DRIFT` of the shift (§15; the real traces reach 0.87 of 3 + 1 %).
_STATIC_SLACK = 4.0
_STATIC_DRIFT = 0.01
_ARC_SECONDS = 2

ARC_SECONDS_NOTE = (
    "its trace coordinates are in arc seconds, not metres along the line: place it by hand"
)


class SegyError(RadarFileError):
    """Raised when a SEG-Y file is malformed, or of a kind nsgeo does not read yet."""


@dataclass(frozen=True)
class SegyHeader(RadarHeader):
    """A SEG-Y line's header: the shared fields plus what this reader needs."""

    format_name: ClassVar[str] = "SEG-Y"

    #: The software that wrote it, as recognised from the text header.
    variant: str
    #: From the file size.
    n_traces: int
    #: Samples per trace as stored, before the static shift is undone.
    stored_samples: int
    delay_ns: float
    #: The largest trace static, 0 when the traces are not shifted.
    max_static_ns: float
    #: The even step the line is placed at, 0 when there is none.
    step_m: float
    #: Steps between traces more than 5 % from the median.
    jumps: int
    #: Traces whose (little-endian) geographic flag is set.
    geographic_traces: int


@dataclass(frozen=True)
class _Traces:
    """What one read of the file gives: the trace-header columns and the samples."""

    scalar: np.ndarray
    x: np.ndarray
    y: np.ndarray
    units: np.ndarray
    static: np.ndarray
    delay: np.ndarray
    n_samples: np.ndarray
    interval: np.ndarray
    geographic: np.ndarray
    #: Degrees x 10^6, little-endian (bytes 229-232 and 233-236). Read only by
    #: `read_gps`: never kept in a header.
    lon_e6: np.ndarray
    lat_e6: np.ndarray
    samples: np.ndarray  # (n_traces, stored_samples) float32


def _short(value: bytes, fmt: str) -> int:
    return int(np.frombuffer(value, dtype=fmt)[0])


def _text_header(raw: bytes) -> str:
    codec = "latin-1" if raw[:1] == b"C" else "cp500"
    return raw[:TEXT_HEADER_BYTES].decode(codec, errors="replace")


def _first_words(text: str) -> str:
    return "".join(ch for ch in text[:60] if ch.isprintable()).strip()


def _binary_header(head: bytes) -> tuple[int, int]:
    """The sample interval (ps) and samples per trace, after checking the rest."""
    code = _short(head[3224:3226], ">i2")
    if code != 5:
        if 1 <= _short(head[3224:3226], "<i2") <= 16:
            raise SegyError("little-endian SEG-Y is not read yet")
        raise SegyError(f"its samples are in format {code}: only IEEE float (format 5) is read yet")
    interval = _short(head[3216:3218], ">i2")
    n_samples = _short(head[3220:3222], ">i2")
    for what, n in (("the sample interval", interval), ("the samples per trace", n_samples)):
        if n <= 0:
            raise SegyError(
                f"its binary header gives {what} as {n}, which is not a whole number above 0"
            )
    if _short(head[3504:3506], ">i2") != 0:
        raise SegyError("extended text headers are not read yet")
    return interval, n_samples


def _count(size: int, n_samples: int) -> int:
    record = TRACE_HEADER_BYTES + 4 * n_samples
    body = size - FILE_HEADER_BYTES
    if body <= 0 or body % record:
        raise SegyError(
            f"its {body} bytes of traces are not whole traces of {record} bytes: "
            f"refusing to guess where they start"
        )
    return body // record


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as exc:
        raise SegyError(f"cannot read it: {exc}") from exc


def _read(path: Path) -> tuple[bytes, np.ndarray]:
    try:
        raw = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise SegyError(f"cannot read it: {exc}") from exc
    if raw.size < FILE_HEADER_BYTES:
        raise SegyError(f"{raw.size} bytes: too short to be a SEG-Y file")
    return raw[:FILE_HEADER_BYTES].tobytes(), raw


def _column(body: np.ndarray, position: int, dtype: str) -> np.ndarray:
    """One trace-header field for every trace, from its 1-based SEG-Y byte position."""
    width = np.dtype(dtype).itemsize
    chunk = np.ascontiguousarray(body[:, position - 1 : position - 1 + width])
    return chunk.view(dtype).reshape(-1).astype(np.int64)


def _traces(raw: np.ndarray, n_traces: int, n_samples: int) -> _Traces:
    record = TRACE_HEADER_BYTES + 4 * n_samples
    body = raw[FILE_HEADER_BYTES : FILE_HEADER_BYTES + n_traces * record].reshape(n_traces, record)
    samples = np.ascontiguousarray(body[:, TRACE_HEADER_BYTES:]).view(">f4").astype(np.float32)
    return _Traces(
        scalar=_column(body, 71, ">i2"),
        x=_column(body, 73, ">i4"),
        y=_column(body, 77, ">i4"),
        units=_column(body, 89, ">i2"),
        static=_column(body, 101, ">i2"),
        delay=_column(body, 109, ">i2"),
        n_samples=_column(body, 115, ">i2"),
        interval=_column(body, 117, ">i2"),
        geographic=_column(body, 227, "<i2"),
        lon_e6=_column(body, 229, "<i4"),
        lat_e6=_column(body, 233, "<i4"),
        samples=samples,
    )


def _check_traces(t: _Traces, interval: int, n_samples: int) -> None:
    bad = np.flatnonzero(t.n_samples != n_samples)
    if bad.size:
        i = int(bad[0])
        raise SegyError(
            f"trace {i + 1} has {t.n_samples[i]} samples, not the {n_samples} its binary header "
            f"gives: SEG-Y with traces of different lengths is not read yet"
        )
    bad = np.flatnonzero(t.interval != interval)
    if bad.size:
        i = int(bad[0])
        raise SegyError(
            f"trace {i + 1} gives a {t.interval[i]} ps sample interval, not the {interval} ps its "
            f"binary header gives: refusing to guess which is right"
        )
    if t.delay.min() != t.delay.max():
        raise SegyError(
            f"its traces start at different delays, {t.delay.min() / 1000:g} to "
            f"{t.delay.max() / 1000:g} ns: not read yet"
        )


def _leads(t: _Traces, dt_ns: float) -> tuple[np.ndarray, int]:
    """Each trace's first non-zero sample and the line's sample count (§15).

    Without statics nothing moves and the line keeps every stored sample.
    """
    n_traces, stored = t.samples.shape
    if not t.static.any():
        return np.zeros(n_traces, dtype=np.int64), stored
    live = t.samples != 0
    has = live.any(axis=1)
    lead = np.where(has, live.argmax(axis=1), 0)
    last = stored - 1 - live[:, ::-1].argmax(axis=1)
    run = np.where(has, last - lead + 1, 0)
    expected = t.static / dt_ns
    bad = np.flatnonzero(
        has & (np.abs(lead - expected) > _STATIC_SLACK + _STATIC_DRIFT * np.abs(expected))
    )
    if bad.size:
        i = int(bad[0])
        raise SegyError(
            f"trace {i + 1}'s samples start {lead[i]} samples down, but its static of "
            f"{t.static[i]:g} ns is {expected[i]:.0f} samples: refusing to guess which is right"
        )
    return lead, int(run.max()) if has.any() else stored


def _spacing(t: _Traces) -> tuple[float, int, list[str]]:
    """(step_m, jumps, notes) from the traces' coordinates (§15)."""
    if t.units.size and int(t.units[0]) == _ARC_SECONDS:
        return 0.0, 0, [ARC_SECONDS_NOTE]
    if t.x.size < 2:
        return 0.0, 0, []
    scalar = np.where(t.scalar == 0, 1, t.scalar).astype(float)
    scale = np.where(scalar < 0, 1.0 / np.abs(scalar), scalar)
    steps = np.hypot(np.diff(t.x * scale), np.diff(t.y * scale))
    median = float(np.median(steps))
    if not median > 0:
        return 0.0, 0, []
    regular = np.abs(steps - median) <= _STEP_TOLERANCE * median
    step = float(steps[regular].mean())
    jumps = int((~regular).sum())
    notes = []
    if jumps:
        off = np.where(regular, -np.inf, np.abs(steps - median))
        k = int(off.argmax())
        traces = "trace" if jumps == 1 else "traces"
        notes.append(
            f"its trace coordinates jump at {jumps} {traces}, the largest {steps[k]:.3g} m at "
            f"trace {k + 2}: placed at an even {step:.4g} m"
        )
    return step, jumps, notes


def _open(path: Path) -> tuple[int, int, int, _Traces]:
    """(interval_ps, stored_samples, n_traces, traces), every file-level check passed."""
    head, raw = _read(path)
    text = _text_header(head)
    if "RadExplorer" not in text:
        raise SegyError(
            f"not a RadExplorer SEG-Y, the only kind nsgeo reads yet: its text header begins "
            f"{_first_words(text)!r}"
        )
    interval, stored = _binary_header(head)
    n_traces = _count(raw.size, stored)
    traces = _traces(raw, n_traces, stored)
    _check_traces(traces, interval, stored)
    return interval, stored, n_traces, traces


def read_header(path: str | Path) -> SegyHeader:
    """Read and check the whole file: the line's sample count depends on every trace (§15)."""
    path = Path(path)
    if path.suffix.lower() not in (".sgy", ".segy"):
        raise SegyError(f"{path.name} is not an .sgy or .segy file")
    interval, stored, n_traces, t = _open(path)
    dt_ns = interval / 1000.0
    _, n_samples = _leads(t, dt_ns)
    notes: list[str] = []
    max_static = float(t.static.max()) if t.static.any() else 0.0
    if max_static:
        notes.append(
            f"its traces carry a static shift of up to {max_static:g} ns: "
            f"read as recorded, without it"
        )
    step, jumps, spacing_notes = _spacing(t)
    notes += spacing_notes
    delay_ns = float(t.delay[0]) / 1000.0
    return SegyHeader(
        n_samples=n_samples,
        n_channels=1,
        range_ns=n_samples * dt_ns,
        position_ns=-delay_ns,
        traces_per_metre=1.0 / step if step > 0 and math.isfinite(step) else 0.0,
        epsr=0.0,
        antenna="",
        notes=tuple(notes),
        not_a_profile="",
        variant="RadExplorer",
        n_traces=n_traces,
        stored_samples=stored,
        delay_ns=delay_ns,
        max_static_ns=max_static,
        step_m=step,
        jumps=jumps,
        geographic_traces=int((t.geographic == 1).sum()),
    )


def trace_count(path: str | Path, header: SegyHeader) -> int:
    """The trace count from the file size, checked against the header's."""
    n = _count(_size(Path(path)), header.stored_samples)
    if n != header.n_traces:
        raise SegyError("its samples changed after its header was read")
    return n


def read_samples(path: str | Path, header: SegyHeader | None = None) -> np.ndarray:
    """All samples as float32, shape (1, n_samples, n_traces), each trace moved
    up by its static shift (§15)."""
    path = Path(path)
    if header is None:
        header = read_header(path)
    trace_count(path, header)
    _, stored, n_traces, t = _open(path)
    if stored != header.stored_samples or n_traces != header.n_traces:
        raise SegyError("its samples changed after its header was read")
    lead, n_samples = _leads(t, header.dt_ns)
    if n_samples != header.n_samples:
        raise SegyError("its samples changed after its header was read")
    index = lead[:, np.newaxis] + np.arange(n_samples)
    inside = index < stored
    out = np.take_along_axis(t.samples, np.minimum(index, stored - 1), axis=1)
    out = np.where(inside, out, np.float32(0)).astype(np.float32)
    return np.ascontiguousarray(out.T)[np.newaxis]


NO_POSITIONS = "its traces carry no GPS positions"


def read_gps(path: str | Path, header: SegyHeader) -> DzgLog:
    """The positions in the trace headers as a GPS log (§16): one fix at the
    first trace of each run of equal positions, among traces whose geographic
    flag is set, with quality `QUALITY_UNKNOWN` and no time or altitude."""
    path = Path(path)
    _, stored, n_traces, t = _open(path)
    if stored != header.stored_samples or n_traces != header.n_traces:
        raise SegyError("its samples changed after its header was read")
    flagged = np.flatnonzero(t.geographic == 1)
    if flagged.size == 0:
        raise NoGpsLog(NO_POSITIONS)
    lon = t.lon_e6[flagged]
    lat = t.lat_e6[flagged]
    change = np.concatenate([[True], (np.diff(lon) != 0) | (np.diff(lat) != 0)])
    fixes = tuple(
        DzgFix(
            trace=int(trace),
            utc_s=None,
            lat=float(la) / 1e6,
            lon=float(lo) / 1e6,
            quality=QUALITY_UNKNOWN,
            n_sats=None,
            hdop=None,
            alt_m=None,
            geoid_m=None,
        )
        for trace, lo, la in zip(flagged[change], lon[change], lat[change])
    )
    return DzgLog(fixes=fixes, bad_checksum=0, unpaired=0)
