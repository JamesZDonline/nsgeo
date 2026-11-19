"""Synthetic GSSI DZG logs for tests, at a made-up place near lat 45.2, lon 10.5.

Never copy a sentence from a real file into a test.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np


def nmea(body: str) -> str:
    """`body` as a sentence: `$body*hh`, hh the XOR of every character."""
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return f"${body}*{calc:02X}"


def _ddmm(value: float, deg_digits: int) -> str:
    v = abs(value)
    deg = int(v)
    minutes = (v - deg) * 60.0
    return f"{deg:0{deg_digits}d}{minutes:010.7f}"


def gga_body(
    utc_s: float,
    lat: float,
    lon: float,
    quality: int,
    *,
    talker: str = "GN",
    alt_m: float = 120.0,
    geoid_m: float = 47.5,
) -> str:
    h, rem = divmod(utc_s, 3600.0)
    m, s = divmod(rem, 60.0)
    clock = f"{int(h):02d}{int(m):02d}{s:05.2f}"
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return (
        f"{talker}GGA,{clock},{_ddmm(lat, 2)},{ns},{_ddmm(lon, 3)},{ew},{quality},22,0.6,"
        f"{alt_m:.3f},M,{geoid_m:.3f},M,1.4,0000"
    )


def write_dzg(
    path: Path,
    fixes: Sequence[tuple[int, float, float, int]],
    *,
    talker: str = "GN",
    alt_m: float = 120.0,
    geoid_m: float = 47.5,
) -> Path:
    """Write `(trace, lat, lon, quality)` fixes as GSSIS + GGA pairs, CRLF ended.

    The time steps 1.0 s per fix from 16:39:15.40.
    """
    start = 16 * 3600 + 39 * 60 + 15.4
    lines: list[str] = []
    for k, (trace, lat, lon, quality) in enumerate(fixes):
        lines.append(f"$GSSIS,{trace},-1")
        body = gga_body(start + k, lat, lon, quality, talker=talker, alt_m=alt_m, geoid_m=geoid_m)
        lines.append(nmea(body))
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
    return path


def local_xy(
    lat0: float, lon0: float
) -> Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """A `(lon, lat) -> (x, y)` local equirectangular projection in metres about a point."""
    radius = 6_371_000.0
    cos0 = math.cos(math.radians(lat0))

    def to_xy(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = np.radians(np.asarray(lon, dtype=float) - lon0) * radius * cos0
        y = np.radians(np.asarray(lat, dtype=float) - lat0) * radius
        return x, y

    return to_xy
