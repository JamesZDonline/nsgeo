"""Format readers.

`read_header`, `trace_count` and `read_samples` here read any registered
radar format, picked by the file's extension (`nsgeo.io.formats`). Each
format's own module keeps its own functions under the same names.
"""

from __future__ import annotations

from nsgeo.io.dt1 import Dt1Error, Dt1Header
from nsgeo.io.dzg import RTK_FIXED, DzgError, DzgFix, DzgLog, dzg_for, read_dzg
from nsgeo.io.dzt import DztError, DztHeader
from nsgeo.io.dzx import DzxError, DzxInfo, DzxMark, read_dzx, sidecar_for
from nsgeo.io.formats import (
    FORMATS,
    RadarFormat,
    UnsupportedFormat,
    format_for,
    read_header,
    read_samples,
    supported_extensions,
    trace_count,
)
from nsgeo.io.header import RadarFileError, RadarHeader, companion

__all__ = [
    "Dt1Error",
    "Dt1Header",
    "DzgError",
    "DzgFix",
    "DzgLog",
    "DztError",
    "DztHeader",
    "DzxError",
    "DzxInfo",
    "DzxMark",
    "FORMATS",
    "RTK_FIXED",
    "RadarFileError",
    "RadarFormat",
    "RadarHeader",
    "UnsupportedFormat",
    "companion",
    "dzg_for",
    "format_for",
    "read_dzg",
    "read_dzx",
    "read_header",
    "read_samples",
    "sidecar_for",
    "supported_extensions",
    "trace_count",
]
