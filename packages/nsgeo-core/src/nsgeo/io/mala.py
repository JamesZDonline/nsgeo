"""MALÅ `.rd3` / `.rd7` reader (spec M21 §2, §14).

A line is a data file and a `.rad` text header with the same stem. Verified
against eight lines of a GX450 HDR survey, each with both data files:

- The `.rad` holds one `KEY:value` per line (CRLF-ended, sometimes a space
  after the colon, values that themselves hold `:` or `=`). It is read by key.
- The data files have no header at all: `SAMPLES` samples per trace, trace
  after trace, little-endian `int16` in an `.rd3` and `int32` in an `.rd7`.
  `LAST TRACE` is the number of traces, not a last index.
- Every `.rd3` sample is its `.rd7` sample shifted right 16 bits. An `.rd3`
  is read shifted back left, so both files of a line, and lines read from
  either, share one amplitude scale (§14).
- `FREQUENCY` is the sampling frequency in MHz, so the sample interval is
  `1000 / FREQUENCY` ns. `SIGNAL POSITION` does not match the measured direct
  wave in any unit, so time zero is not read: a Time zero step sets it.
- Multichannel files (`DAT_0001_A1.rd3`, `_A2`, ...) are refused: none has
  been in hand to verify against.
- The `.cor` beside a line is its GPS log (M21d, §16): one tab-separated row
  per fix, trace numbers counted from 1, decimal degrees, GGA quality.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np

from nsgeo.io.dzg import DzgFix, DzgLog
from nsgeo.io.header import NoGpsLog, RadarFileError, RadarHeader, companion

_DTYPES = {".rd3": "<i2", ".rd7": "<i4"}
#: More than this fraction between two readings of one quantity is a
#: disagreement (the time window refuses, the spacing notes).
_TOLERANCE = 0.01
_CHANNEL = re.compile(r"^(.*)_A(\d+)$", re.IGNORECASE)
_ANTENNA_CODE = re.compile(r"\s*=\s*\d+\s*$")

TIME_ZERO_NOTE = "time zero is not read from a MALÅ .rad: set one with a Time zero step"
NO_INTERVAL_NOTE = "distance-triggered with no DISTANCE INTERVAL: place it by hand"
MULTICHANNEL = "multichannel MALÅ files are not read yet"


class MalaError(RadarFileError):
    """Raised when a MALÅ line or its .rad is missing, malformed or unsupported."""


@dataclass(frozen=True)
class MalaHeader(RadarHeader):
    """A MALÅ line's header: the shared fields plus what this reader needs."""

    format_name: ClassVar[str] = "MALÅ"

    rad_path: Path
    #: `LAST TRACE`; the file size is checked against it.
    n_traces: int
    #: 2 for an .rd3, 4 for an .rd7: from the extension, never from the size.
    bytes_per_sample: int
    #: `DISTANCE INTERVAL` in metres, 0 when absent.
    distance_interval: float
    #: "distance", "time" or "other", from the .rad's flags.
    trigger: str
    #: As the .rad gives it. Not time zero (§2), kept for reference.
    signal_position: float | None


def _read_rad(rad: Path) -> dict[str, str]:
    try:
        text = rad.read_bytes().decode("latin-1")
    except OSError as exc:
        raise MalaError(f"cannot read {rad.name}: {exc}") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            values[key.strip().upper()] = value.strip()
    return values


def _number(values: dict[str, str], key: str) -> float | None:
    """The key's value as a float, None when the key is absent."""
    if key not in values:
        return None
    try:
        return float(values[key])
    except ValueError:
        raise MalaError(f"its .rad gives {key} as {values[key]!r}, which is not a number") from None


def _required(values: dict[str, str], key: str, *, whole: bool) -> float:
    number = _number(values, key)
    if number is None:
        raise MalaError(f"its .rad has no {key}")
    if not (math.isfinite(number) and number > 0 and (not whole or number.is_integer())):
        what = "a whole number above 0" if whole else "a number above 0"
        raise MalaError(f"its .rad gives {key} as {values[key]!r}, which is not {what}")
    return number


def _refuse_sibling_channels(path: Path) -> None:
    """A multichannel set is refused before its .rad is looked for: the set may
    have one .rad for all its channels, and "no X_A1.rad" would mislead."""
    match = _CHANNEL.match(path.stem)
    if match is None:
        return
    base = match.group(1)
    sibling = re.compile(rf"^{re.escape(base)}_A\d+$", re.IGNORECASE)
    suffix = path.suffix.lower()
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name != path.name and entry.suffix.lower() == suffix and sibling.match(entry.stem):
            raise MalaError(f"{MULTICHANNEL}: {path.name} is one channel of {base}")


def _size_error(size: int, n_traces: int, record: int) -> MalaError:
    return MalaError(
        f"{size} bytes are not the {n_traces} traces of {record} bytes its .rad gives: "
        f"refusing to guess which is right"
    )


def _check_size(path: Path, n_traces: int, record: int) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MalaError(f"cannot read it: {exc}") from exc
    if size != n_traces * record:
        raise _size_error(size, n_traces, record)


def read_header(path: str | Path) -> MalaHeader:
    """Read the .rad and stat the data file. Cheap."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in _DTYPES:
        raise MalaError(f"{path.name} is not an .rd3 or .rd7 file")
    _refuse_sibling_channels(path)
    rad = companion(path, ".rad")
    if rad is None:
        raise MalaError(f"no {path.stem}.rad beside it")
    values = _read_rad(rad)

    for key in ("CHANNELS", "NUMBER OF CH"):
        channels = _number(values, key)
        if channels is not None and channels > 1:
            raise MalaError(f"{MULTICHANNEL}: its .rad gives {channels:g} channels")

    n_samples = int(_required(values, "SAMPLES", whole=True))
    frequency = _required(values, "FREQUENCY", whole=False)
    n_traces = int(_required(values, "LAST TRACE", whole=True))
    dt_ns = 1000.0 / frequency
    range_ns = n_samples * dt_ns
    window = _number(values, "TIMEWINDOW")
    if window is not None and abs(window - range_ns) > _TOLERANCE * range_ns:
        raise MalaError(
            f"its .rad gives a {window:g} ns TIMEWINDOW but {n_samples} samples at "
            f"{frequency:g} MHz span {range_ns:g} ns: refusing to guess which is right"
        )

    width = 2 if suffix == ".rd3" else 4
    _check_size(path, n_traces, n_samples * width)

    notes = [TIME_ZERO_NOTE]
    interval = _number(values, "DISTANCE INTERVAL") or 0.0
    if _number(values, "DISTANCE FLAG") == 1:
        trigger = "distance"
        if interval > 0:
            traces_per_metre = 1.0 / interval
            stop = _number(values, "STOP POSITION")
            start = _number(values, "START POSITION") or 0.0
            if stop is not None and n_traces > 1:
                actual = abs(stop - start) / (n_traces - 1)
                if abs(actual - interval) > _TOLERANCE * interval:
                    notes.append(
                        f"its start and stop positions step {actual:.4g} m, not its "
                        f"DISTANCE INTERVAL {interval:g}: placed at the DISTANCE INTERVAL"
                    )
        else:
            traces_per_metre = 0.0
            notes.append(NO_INTERVAL_NOTE)
    else:
        trigger = "time" if _number(values, "TIME FLAG") == 1 else "other"
        traces_per_metre = 0.0

    return MalaHeader(
        n_samples=n_samples,
        n_channels=1,
        range_ns=range_ns,
        position_ns=0.0,
        traces_per_metre=traces_per_metre,
        epsr=0.0,
        antenna=_ANTENNA_CODE.sub("", values.get("ANTENNAS", "")).strip(),
        notes=tuple(notes),
        not_a_profile="",
        rad_path=rad,
        n_traces=n_traces,
        bytes_per_sample=width,
        distance_interval=interval,
        trigger=trigger,
        signal_position=_number(values, "SIGNAL POSITION"),
    )


def trace_count(path: str | Path, header: MalaHeader) -> int:
    """The .rad's trace count, after checking the file still holds exactly that many."""
    _check_size(Path(path), header.n_traces, header.n_samples * header.bytes_per_sample)
    return header.n_traces


def read_samples(path: str | Path, header: MalaHeader | None = None) -> np.ndarray:
    """All samples as signed int32, shape (1, n_samples, n_traces).

    An .rd7 is raw. An .rd3 is widened and shifted left 16 bits, which puts it
    on its .rd7's scale (§14); widening first keeps int16 from wrapping.
    """
    path = Path(path)
    if header is None:
        header = read_header(path)
    n_traces = trace_count(path, header)
    dtype = "<i2" if header.bytes_per_sample == 2 else "<i4"
    try:
        flat = np.fromfile(path, dtype=dtype, count=n_traces * header.n_samples)
    except OSError as exc:
        raise MalaError(f"cannot read it: {exc}") from exc
    samples = flat.reshape(n_traces, header.n_samples).astype(np.int32)
    if header.bytes_per_sample == 2:
        samples = np.left_shift(samples, 16)
    return np.ascontiguousarray(samples.T)[np.newaxis]


_COR_COLUMNS = 10


def _cor_number(row: int, what: str, value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise MalaError(f"its .cor row {row} gives {what} as {value!r}, which is not a number")
    return number


def _utc_s(value: str) -> float | None:
    try:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return None


def read_gps(path: str | Path, header: MalaHeader) -> DzgLog:
    """The line's `.cor` as a GPS log: one fix per row, at trace number minus 1
    (a `.cor` counts from 1, a DZG from 0), quality as given (§16)."""
    path = Path(path)
    cor = companion(path, ".cor")
    if cor is None:
        raise NoGpsLog(f"no {path.stem}.cor beside it")
    try:
        text = cor.read_bytes().decode("latin-1")
    except OSError as exc:
        raise MalaError(f"cannot read {cor.name}: {exc}") from exc
    fixes: list[DzgFix] = []
    previous: int | None = None
    for i, line in enumerate((ln for ln in text.splitlines() if ln.strip()), start=1):
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) != _COR_COLUMNS:
            raise MalaError(f"its .cor row {i} has {len(cols)} columns, not {_COR_COLUMNS}")
        trace_value = _cor_number(i, "the trace", cols[0])
        if not trace_value.is_integer():
            raise MalaError(
                f"its .cor row {i} gives the trace as {cols[0]!r}, which is not a number"
            )
        trace = int(trace_value)
        if previous is not None and trace <= previous:
            raise MalaError(
                f"its .cor row {i} names trace {trace} after trace {previous}: "
                f"trace numbers must rise"
            )
        if not 1 <= trace <= header.n_traces:
            raise MalaError(
                f"its .cor names trace {trace}, but the line has {header.n_traces} traces"
            )
        previous = trace
        lat = _cor_number(i, "the latitude", cols[3]) * (-1.0 if cols[4].upper() == "S" else 1.0)
        lon = _cor_number(i, "the longitude", cols[5]) * (-1.0 if cols[6].upper() == "W" else 1.0)
        quality = _cor_number(i, "the quality", cols[9])
        altitude: float | None = None
        if cols[8].upper() == "M":
            try:
                altitude = float(cols[7])
            except ValueError:
                altitude = None
        fixes.append(
            DzgFix(
                trace=trace - 1,
                utc_s=_utc_s(cols[2]),
                lat=lat,
                lon=lon,
                quality=int(quality),
                n_sats=None,
                hdop=None,
                alt_m=altitude,
                geoid_m=None,
            )
        )
    return DzgLog(fixes=tuple(fixes), bad_checksum=0, unpaired=0)
