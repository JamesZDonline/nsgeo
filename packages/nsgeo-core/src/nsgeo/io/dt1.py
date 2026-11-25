"""Sensors & Software pulseEKKO DT1 reader (spec M21 §2, §13).

A line is two files with one stem: the `.DT1` (data) and the `.HD` (a text
header). Verified against seven pulseEKKO PRO lines and a CMP sounding from
two surveys (100 MHz, 2012 and 2014):

- The `.HD` holds a few free lines (`1234`, the instrument, a date), then one
  `KEY = value` per line. Files differ in which keys they add and in their
  order, so it is read by key, never by line number.
- The `.DT1` is fixed-size records: per trace a 128-byte header (25
  little-endian float32 values, then 28 bytes of comment) followed by
  `NUMBER OF PTS/TRC` little-endian samples. Trace-header value 1 is the
  position, value 5 the bytes per sample.
- `TIMEZERO AT POINT` is a sample index and matches the measured first break
  to within a sample on both surveys, so time zero is taken from it.
- Spacing is `STEP SIZE USED` in `POSITION UNITS`; every per-trace position
  step equals it on every real line.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, ClassVar

import numpy as np

from nsgeo.io.header import RadarFileError, RadarHeader, companion

TRACE_HEADER_BYTES = 128
_FEET_M = 0.3048
_METRES = {"m", "metre", "metres", "meter", "meters"}
_FEET = {"ft", "foot", "feet"}
_DTYPES = {2: "<i2", 4: "<i4"}
#: More than this fraction between the trace positions' step and the .HD's
#: step adds a note (spec §13).
_STEP_TOLERANCE = 0.01

CMP_NOTE = "a CMP/WARR velocity sounding, not a profile"


class Dt1Error(RadarFileError):
    """Raised when a DT1 line or its .HD is missing, malformed or unsupported."""


@dataclass(frozen=True)
class Dt1Header(RadarHeader):
    """A DT1 line's header: the shared fields plus what this reader needs."""

    format_name: ClassVar[str] = "Sensors & Software DT1"

    hd_path: Path
    #: As the .HD gives it; the file size is checked against it.
    n_traces: int
    #: 2 or 4, from the file size.
    bytes_per_sample: int
    #: `STEP SIZE USED` and `POSITION UNITS` as written (0 and "" when absent).
    step: float
    units: str
    survey_mode: str
    timezero_point: float | None


def _read_hd(hd: Path) -> dict[str, str]:
    try:
        text = hd.read_bytes().decode("latin-1")
    except OSError as exc:
        raise Dt1Error(f"cannot read {hd.name}: {exc}") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            values[key.strip().upper()] = value.strip()
    return values


def _number(values: dict[str, str], key: str) -> float | None:
    """The key's value as a float, None when the key is absent."""
    if key not in values:
        return None
    try:
        return float(values[key])
    except ValueError:
        raise Dt1Error(f"its .HD gives {key} as {values[key]!r}, which is not a number") from None


def _required(values: dict[str, str], key: str, *, whole: bool) -> float:
    number = _number(values, key)
    if number is None:
        raise Dt1Error(f"its .HD has no {key}")
    if not (math.isfinite(number) and number > 0 and (not whole or number.is_integer())):
        what = "a whole number above 0" if whole else "a number above 0"
        raise Dt1Error(f"its .HD gives {key} as {values[key]!r}, which is not {what}")
    return number


def _size_error(size: int, n_traces: int) -> Dt1Error:
    return Dt1Error(
        f"{size} bytes do not divide into the {n_traces} traces its .HD gives: "
        f"refusing to guess which is right"
    )


def _sample_width(size: int, n_traces: int, n_samples: int) -> int:
    """Bytes per sample implied by the file size (spec §13), refusing anything else."""
    if size % n_traces:
        raise _size_error(size, n_traces)
    payload = size // n_traces - TRACE_HEADER_BYTES
    if payload <= 0 or payload % n_samples:
        raise _size_error(size, n_traces)
    width = payload // n_samples
    if width not in _DTYPES:
        raise Dt1Error(f"{width}-byte samples are not read; DT1 samples are 2 or 4 bytes")
    return width


def _trace_header(fh: BinaryIO, offset: int) -> np.ndarray:
    fh.seek(offset)
    raw = fh.read(TRACE_HEADER_BYTES)
    return np.frombuffer(raw[:100], dtype="<f4", count=25)


def read_header(path: str | Path) -> Dt1Header:
    """Read the .HD, stat the .DT1 and read its first and last trace headers. Cheap."""
    path = Path(path)
    hd = companion(path, ".HD")
    if hd is None:
        raise Dt1Error(f"no {path.stem}.HD beside it")
    values = _read_hd(hd)
    n_traces = int(_required(values, "NUMBER OF TRACES", whole=True))
    n_samples = int(_required(values, "NUMBER OF PTS/TRC", whole=True))
    window_ns = _required(values, "TOTAL TIME WINDOW", whole=False)
    timezero = _number(values, "TIMEZERO AT POINT")
    step = _number(values, "STEP SIZE USED") or 0.0
    frequency = _number(values, "NOMINAL FREQUENCY")
    units = values.get("POSITION UNITS", "")
    mode = values.get("SURVEY MODE", "")

    try:
        size = path.stat().st_size
        width = _sample_width(size, n_traces, n_samples)
        record = TRACE_HEADER_BYTES + n_samples * width
        with open(path, "rb") as fh:
            first = _trace_header(fh, 0)
            last = _trace_header(fh, (n_traces - 1) * record)
    except OSError as exc:
        raise Dt1Error(f"cannot read it: {exc}") from exc
    said = int(first[5])
    if said and said != width:
        raise Dt1Error(f"its trace headers say {said}-byte samples but the file size says {width}")

    notes: list[str] = []
    dt_ns = window_ns / n_samples
    if timezero is None:
        position_ns = 0.0
        notes.append("no time zero in its .HD; set one with a Time zero step")
    else:
        position_ns = -timezero * dt_ns

    unit = units.lower()
    if unit in _METRES or unit in _FEET:
        metres_per_unit = 1.0 if unit in _METRES else _FEET_M
        traces_per_metre = 1.0 / (step * metres_per_unit) if step > 0 else 0.0
        if step > 0 and n_traces > 1:
            actual = abs(float(last[1]) - float(first[1])) / (n_traces - 1)
            if abs(actual - step) > _STEP_TOLERANCE * step:
                notes.append(
                    f"trace positions step {actual:.4g} {units}, not the .HD's {step:g}; "
                    f"placed at the .HD's step"
                )
    else:
        traces_per_metre = 0.0
        notes.append(f"position units {units!r} are not metres or feet; place it by hand")

    upper = mode.upper()
    return Dt1Header(
        n_samples=n_samples,
        n_channels=1,
        range_ns=window_ns,
        position_ns=position_ns,
        traces_per_metre=traces_per_metre,
        epsr=0.0,
        antenna=f"{frequency:g} MHz" if frequency is not None else "",
        notes=tuple(notes),
        not_a_profile=CMP_NOTE if "CMP" in upper or "WARR" in upper else "",
        hd_path=hd,
        n_traces=n_traces,
        bytes_per_sample=width,
        step=step,
        units=units,
        survey_mode=mode,
        timezero_point=timezero,
    )


def _record_bytes(header: Dt1Header) -> int:
    return TRACE_HEADER_BYTES + header.n_samples * header.bytes_per_sample


def trace_count(path: str | Path, header: Dt1Header) -> int:
    """The .HD's trace count, after checking the file still holds exactly that many."""
    try:
        size = Path(path).stat().st_size
    except OSError as exc:
        raise Dt1Error(f"cannot read it: {exc}") from exc
    if size != header.n_traces * _record_bytes(header):
        raise _size_error(size, header.n_traces)
    return header.n_traces


def read_samples(path: str | Path, header: Dt1Header | None = None) -> np.ndarray:
    """All samples as signed int32, shape (1, n_samples, n_traces), raw.

    No centre is removed and no sample is zeroed: a DT1's trace headers are
    separate records, not samples, and its samples are signed.
    """
    path = Path(path)
    if header is None:
        header = read_header(path)
    n_traces = trace_count(path, header)
    raw = np.fromfile(path, dtype=np.uint8)
    records = raw.reshape(n_traces, _record_bytes(header))[:, TRACE_HEADER_BYTES:]
    samples = records.copy().view(_DTYPES[header.bytes_per_sample]).astype(np.int32)
    return np.ascontiguousarray(samples.T)[np.newaxis]
