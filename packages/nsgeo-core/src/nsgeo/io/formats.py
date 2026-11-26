"""The radar format registry: one way in for every format (spec M21, C2).

Each format registers a `read_header`, a `trace_count` and a `read_samples`,
with the signatures `nsgeo.io.dzt` already has. The module-level functions
here pick the format from the file's extension (case-insensitively) and call
its reader, so `from nsgeo.io import read_header` reads any registered format.

Adding a format: a module with a `RadarHeader` subclass and those three
functions, and one entry in `FORMATS` (spec §7).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import numpy as np

from nsgeo.io import dt1, dzt, mala, segy
from nsgeo.io.dzg import DzgLog, dzg_for, read_dzg
from nsgeo.io.header import NoGpsLog, RadarFileError, RadarHeader, companion

__all__ = [
    "FORMATS",
    "NO_GPS_FORMAT",
    "RadarFormat",
    "UnsupportedFormat",
    "companion",
    "format_for",
    "gps_formats",
    "read_gps",
    "read_header",
    "read_samples",
    "supported_extensions",
    "trace_count",
]


class UnsupportedFormat(RadarFileError):
    """Raised for a file whose extension no registered format reads."""


@dataclass(frozen=True)
class RadarFormat:
    name: str
    #: Lower case, with the dot.
    extensions: tuple[str, ...]
    read_header: Callable[[Path], RadarHeader]
    trace_count: Callable[[Path, RadarHeader], int]
    read_samples: Callable[[Path, RadarHeader], np.ndarray]
    #: Extensions that hold the same traces, best first (spec §14). When one
    #: stem in one folder is chosen in more than one, the import ticks only
    #: the best. Empty for a format with one file per line.
    prefer: tuple[str, ...] = ()
    #: The line's GPS log, or None for a format with no GPS source (spec §16).
    #: Raises `NoGpsLog` for a line that has none.
    read_gps: Callable[[Path, RadarHeader, int], DzgLog] | None = None


#: A radar format nsgeo reads, but whose GPS log it does not (spec M21 C10).
NO_GPS_FORMAT = "no GPS log read for this format yet"


_H = TypeVar("_H", bound=RadarHeader)


def _checked(name: str, header_type: type[_H], header: RadarHeader, path: Path) -> _H:
    """`header` as the reader's own header type, or a RadarFileError naming both formats.

    Without it a DT1 header handed to the DZT reader would be read with the
    DZT's byte layout and return garbage without complaint."""
    if not isinstance(header, header_type):
        raise RadarFileError(
            f"{path.name}: a {header.format_name} header was given to the {name} reader"
        )
    return header


def _dzt_trace_count(path: Path, header: RadarHeader) -> int:
    return dzt.trace_count(path, _checked(DZT_NAME, dzt.DztHeader, header, path))


def _dzt_read_samples(path: Path, header: RadarHeader) -> np.ndarray:
    return dzt.read_samples(path, _checked(DZT_NAME, dzt.DztHeader, header, path))


def _dt1_trace_count(path: Path, header: RadarHeader) -> int:
    return dt1.trace_count(path, _checked(DT1_NAME, dt1.Dt1Header, header, path))


def _dt1_read_samples(path: Path, header: RadarHeader) -> np.ndarray:
    return dt1.read_samples(path, _checked(DT1_NAME, dt1.Dt1Header, header, path))


def _mala_trace_count(path: Path, header: RadarHeader) -> int:
    return mala.trace_count(path, _checked(MALA_NAME, mala.MalaHeader, header, path))


def _mala_read_samples(path: Path, header: RadarHeader) -> np.ndarray:
    return mala.read_samples(path, _checked(MALA_NAME, mala.MalaHeader, header, path))


def _segy_trace_count(path: Path, header: RadarHeader) -> int:
    return segy.trace_count(path, _checked(SEGY_NAME, segy.SegyHeader, header, path))


def _segy_read_samples(path: Path, header: RadarHeader) -> np.ndarray:
    return segy.read_samples(path, _checked(SEGY_NAME, segy.SegyHeader, header, path))


def _dzt_read_gps(path: Path, header: RadarHeader, n_traces: int) -> DzgLog:
    _checked(DZT_NAME, dzt.DztHeader, header, path)
    dzg = dzg_for(path)
    if dzg is None:
        raise NoGpsLog("no DZG beside it")
    return read_dzg(dzg, n_traces)


def _mala_read_gps(path: Path, header: RadarHeader, n_traces: int) -> DzgLog:
    return mala.read_gps(path, _checked(MALA_NAME, mala.MalaHeader, header, path))


def _segy_read_gps(path: Path, header: RadarHeader, n_traces: int) -> DzgLog:
    return segy.read_gps(path, _checked(SEGY_NAME, segy.SegyHeader, header, path))


DZT_NAME = dzt.DztHeader.format_name
DT1_NAME = dt1.Dt1Header.format_name
MALA_NAME = mala.MalaHeader.format_name
SEGY_NAME = segy.SegyHeader.format_name

#: In the order the import's file picker lists them.
FORMATS: tuple[RadarFormat, ...] = (
    RadarFormat(
        DZT_NAME,
        (".dzt",),
        dzt.read_header,
        _dzt_trace_count,
        _dzt_read_samples,
        read_gps=_dzt_read_gps,
    ),
    RadarFormat(DT1_NAME, (".dt1",), dt1.read_header, _dt1_trace_count, _dt1_read_samples),
    RadarFormat(
        MALA_NAME,
        (".rd3", ".rd7"),
        mala.read_header,
        _mala_trace_count,
        _mala_read_samples,
        prefer=(".rd7", ".rd3"),
        read_gps=_mala_read_gps,
    ),
    RadarFormat(
        SEGY_NAME,
        (".sgy", ".segy"),
        segy.read_header,
        _segy_trace_count,
        _segy_read_samples,
        read_gps=_segy_read_gps,
    ),
)


def supported_extensions() -> tuple[str, ...]:
    """Every registered extension, lower case with the dot, in registry order."""
    return tuple(ext for fmt in FORMATS for ext in fmt.extensions)


def format_for(path: str | Path) -> RadarFormat:
    """The registered format that reads `path`, by its extension in any case."""
    path = Path(path)
    suffix = path.suffix.lower()
    for fmt in FORMATS:
        if suffix in fmt.extensions:
            return fmt
    what = f"{path.suffix} files" if path.suffix else "files with no extension"
    raise UnsupportedFormat(
        f"nsgeo does not read {what}; it reads {', '.join(supported_extensions())}"
    )


def read_header(path: str | Path) -> RadarHeader:
    """Read the header, by the format the extension names. Cheap for every format but
    a static-shifted SEG-Y, which is read whole (spec §15)."""
    path = Path(path)
    return format_for(path).read_header(path)


def trace_count(path: str | Path, header: RadarHeader) -> int:
    """Number of traces in `path`, checked against `header` by the format's own rule."""
    path = Path(path)
    return format_for(path).trace_count(path, header)


def read_samples(path: str | Path, header: RadarHeader | None = None) -> np.ndarray:
    """All samples, shape (n_channels, n_samples, n_traces), raw (spec C5)."""
    path = Path(path)
    fmt = format_for(path)
    return fmt.read_samples(path, fmt.read_header(path) if header is None else header)


def gps_formats() -> tuple[RadarFormat, ...]:
    """The registered formats with a GPS source, in registry order."""
    return tuple(fmt for fmt in FORMATS if fmt.read_gps is not None)


def read_gps(path: str | Path, header: RadarHeader, n_traces: int) -> DzgLog:
    """The line's GPS log, by its format (spec §16). `UnsupportedFormat` with
    `NO_GPS_FORMAT` for a format with no GPS source; `NoGpsLog` for a line with
    no log."""
    path = Path(path)
    fmt = format_for(path)
    if fmt.read_gps is None:
        raise UnsupportedFormat(NO_GPS_FORMAT)
    return fmt.read_gps(path, header, n_traces)
