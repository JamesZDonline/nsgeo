"""A test-only MALÅ writer, copying the real layout (spec M21 §2, §14).

The `.rad` is text, one `KEY:value` per line, CRLF-ended, in the real files'
key order and with the keys the reader ignores. The data file has no header:
`.rd3` is little-endian int16 samples, `.rd7` int32, trace after trace.

Synthetic files prove self-consistency only; the real files in
`tests/data/local/mala` catch real quirks.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

_DTYPES = {".rd3": "<i2", ".rd7": "<i4"}


def write_mala(
    path: Path,
    data: np.ndarray,
    *,
    frequency: float = 5120.0,
    interval: float | None = 0.5,
    distance_flag: int = 1,
    time_flag: int = 0,
    timewindow: float | str | None = "auto",
    antenna: str | None = "GX450 HDR (v.1)=3",
    signal_position: float | None = 102.734375,
    rad_suffix: str = ".rad",
    rad_extra: Sequence[str] = (),
    drop_keys: Sequence[str] = (),
    rad_values: dict[str, str] | None = None,
    last_trace: int | None = None,
    start: float = 0.0,
    stop: float | str | None = "auto",
    write_rad: bool = True,
) -> Path:
    """Write `data` (n_samples, n_traces) as `path` (.rd3 or .rd7) and its `.rad`.

    `None` for an optional value leaves its key out, as does naming the key
    in `drop_keys`. `rad_values` replaces a key's value as written.
    `timewindow` and `stop` are computed from the other arguments when "auto".
    `last_trace` overrides the trace count the `.rad` gives.
    """
    path = Path(path)
    data = np.asarray(data)
    n_samples, n_traces = data.shape
    dtype = np.dtype(_DTYPES[path.suffix.lower()])
    info = np.iinfo(dtype)
    if data.size and (data.min() < info.min or data.max() > info.max):
        raise ValueError(f"data does not fit {dtype}")
    if timewindow == "auto":
        timewindow = n_samples * 1000.0 / frequency
    if stop == "auto":
        stop = start + (n_traces - 1) * (interval or 0.0)
    keys: list[tuple[str, object]] = [
        ("SAMPLES", n_samples),
        ("FREQUENCY", f"{frequency:.6f}"),
        ("FREQUENCY STEPS", 1),
        ("SIGNAL POSITION", signal_position),
        ("RAW SIGNAL POSITION", 65009),
        ("DISTANCE FLAG", distance_flag),
        ("TIME FLAG", time_flag),
        ("PROGRAM FLAG", 0),
        ("EXTERNAL FLAG", 0),
        ("TIME INTERVAL", " 0.000000"),
        ("DISTANCE INTERVAL", None if interval is None else f" {interval:.6f}"),
        ("OPERATOR", "_"),
        ("CUSTOMER", "_"),
        ("SITE", "_"),
        ("ANTENNAS", antenna),
        ("ANTENNA ORIENTATION", "NOT VALID FIELD"),
        ("ANTENNA SEPARATION", " 0.180000"),
        ("COMMENT", "Wheel (30cm)=2"),
        ("TIMEWINDOW", None if timewindow is None else f"{float(timewindow):.6f}"),
        ("STACKS", 1),
        ("STACK EXPONENT", 0),
        ("STACKING TIME", "0.000000"),
        ("LAST TRACE", n_traces if last_trace is None else last_trace),
        ("STOP POSITION", None if stop is None else f"{float(stop):.6f}"),
        ("SYSTEM CALIBRATION", "0.0001953125"),
        ("START POSITION", f"{start:.6f}"),
        ("SHORT FLAG", 1),
        ("WHEEL CALIBRATION", "261.942000"),
        ("POSITIVE DIRECTION", 1),
    ]
    if write_rad:
        lines = []
        for key, value in keys:
            if value is None or key in drop_keys:
                continue
            lines.append(f"{key}:{(rad_values or {}).get(key, value)}")
        lines.extend(rad_extra)
        text = "\r\n".join(lines) + "\r\n"
        path.with_suffix(rad_suffix).write_bytes(text.encode("latin-1"))
    path.write_bytes(np.ascontiguousarray(data.T).astype(dtype).tobytes())
    return path


def write_mala_pair(stem_path: Path, data32: np.ndarray, **kw: Any) -> tuple[Path, Path]:
    """Write `<stem>.rd7` as `data32` and `<stem>.rd3` as its top 16 bits, with one `.rad`."""
    stem_path = Path(stem_path)
    data32 = np.asarray(data32, dtype=np.int32)
    rd7 = write_mala(stem_path.with_suffix(".rd7"), data32, **kw)
    rd3 = write_mala(
        stem_path.with_suffix(".rd3"),
        (data32 >> 16).astype(np.int16),
        write_rad=False,
        **kw,
    )
    return rd7, rd3


def write_cor(path: Path, rows: Sequence[tuple[int, float, float, int]]) -> Path:
    """Write a MALÅ `.cor` GPS log in the real layout: tab-separated, CRLF-ended,
    one row per fix of (trace counted from 1, latitude, longitude, quality), with
    a fixed date, times a second apart and a 12.5 m altitude. Negative latitude
    or longitude is written as S or W. Coordinates are made up: never a real one.
    """
    lines = []
    for i, (trace, lat, lon, quality) in enumerate(rows):
        s = 12 * 3600 + i
        clock = f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"
        lines.append(
            "\t".join(
                [
                    str(trace),
                    "2000-01-01",
                    clock,
                    f"{abs(lat):.9f}",
                    "S" if lat < 0 else "N",
                    f"{abs(lon):.9f}",
                    "W" if lon < 0 else "E",
                    "12.5",
                    "M",
                    str(quality),
                ]
            )
        )
    path = Path(path)
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    return path
