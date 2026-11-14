"""GSSI .DZG GPS log reader.

A DZG is the NMEA text the radar logs beside a .DZT: a `$GSSIS,{trace},…`
line naming the DZT trace, then the GGA sentence received at that trace.
`read_dzg` pairs them, one `DzgFix` per GGA, and keeps every fix whatever its
quality: a non-RTK fix between two RTK fixes is what marks a dropout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

RTK_FIXED = 4
"""GGA fix quality for an RTK fixed solution."""


class DzgError(ValueError):
    """Raised when a DZG's trace numbers cannot be trusted."""


@dataclass(frozen=True)
class DzgFix:
    trace: int
    utc_s: float | None
    lat: float
    lon: float
    quality: int
    n_sats: int | None
    hdop: float | None
    alt_m: float | None
    geoid_m: float | None


@dataclass(frozen=True)
class DzgLog:
    fixes: tuple[DzgFix, ...]
    bad_checksum: int
    unpaired: int

    @property
    def n_fixed(self) -> int:
        return sum(1 for f in self.fixes if f.quality == RTK_FIXED)


def dzg_for(path: str | Path) -> Path | None:
    """The .DZG beside a .DZT (either case), or the path itself if it is one.

    Matched against the real directory entries, not probed with
    `Path.exists()`, for the reason `sidecar_for` gives: on a
    case-insensitive filesystem an exists() probe returns a spelling the
    directory does not hold. `.DZG` is tried before `.dzg`.
    """
    path = Path(path)
    parent = path.parent
    try:
        names = {entry.name for entry in parent.iterdir()}
    except OSError:
        # An unreadable or absent directory holds no log; a missing DZG is normal.
        return None
    candidates: tuple[str, ...] = (path.with_suffix(".DZG").name, path.with_suffix(".dzg").name)
    if path.suffix.lower() == ".dzg":
        candidates = (path.name, *candidates)
    for name in candidates:
        if name in names:
            return parent / name
    return None


def _body(line: str) -> str | None:
    """The text between `$` and `*`, or None for a bad checksum or no `$`."""
    line = line.strip()
    if not line.startswith("$"):
        return None
    text = line[1:]
    if "*" not in text:
        return text
    body, _, given = text.rpartition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        ok = int(given.strip(), 16) == calc
    except ValueError:
        ok = False
    return body if ok else None


def _float(s: str) -> float | None:
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _int(s: str) -> int | None:
    try:
        return int(s)
    except ValueError:
        return None


def _degrees(value: str, hemisphere: str, deg_digits: int) -> float:
    if not value or hemisphere not in ("N", "S", "E", "W"):
        return math.nan
    try:
        deg = int(value[:deg_digits])
        minutes = float(value[deg_digits:])
    except ValueError:
        return math.nan
    out = deg + minutes / 60.0
    return -out if hemisphere in ("S", "W") else out


def _utc_s(s: str) -> float | None:
    if len(s) < 6:
        return None
    try:
        return int(s[0:2]) * 3600 + int(s[2:4]) * 60 + float(s[4:])
    except ValueError:
        return None


def _fix(trace: int, f: list[str]) -> DzgFix:
    def at(i: int) -> str:
        return f[i].strip() if i < len(f) else ""

    quality = _int(at(6))
    return DzgFix(
        trace=trace,
        utc_s=_utc_s(at(1)),
        lat=_degrees(at(2), at(3), 2),
        lon=_degrees(at(4), at(5), 3),
        quality=0 if quality is None else quality,
        n_sats=_int(at(7)),
        hdop=_float(at(8)),
        alt_m=_float(at(9)),
        geoid_m=_float(at(11)),
    )


def read_dzg(path: str | Path, n_traces: int | None = None) -> DzgLog:
    """Parse a DZG into its fixes.

    Trace numbers must rise strictly, and, when `n_traces` is given, name
    traces inside the DZT: a wrong pairing misplaces every trace after it.
    """
    path = Path(path)
    text = path.read_bytes().decode("latin-1")
    fixes: list[DzgFix] = []
    bad = 0
    unpaired = 0
    pending: int | None = None
    for line in text.splitlines():
        body = _body(line)
        if body is None:
            if line.strip().startswith("$"):
                bad += 1
                # A dropped GGA orphans the GSSIS before it; count it there. A dropped
                # GSSIS leaves the one before it with no GGA to meet, so a later GGA
                # must not pair with that older trace.
                sentence = line.strip()
                if (sentence[3:6] == "GGA" or sentence[1:6] == "GSSIS") and pending is not None:
                    unpaired += 1
                    pending = None
            continue
        fields = body.split(",")
        tag = fields[0]
        if tag == "GSSIS":
            if pending is not None:
                unpaired += 1
            pending = _int(fields[1].strip()) if len(fields) > 1 else None
            if pending is None:
                unpaired += 1
        elif tag[2:] == "GGA" and len(tag) == 5:
            if pending is None:
                unpaired += 1
            else:
                fixes.append(_fix(pending, fields))
                pending = None
    if pending is not None:
        unpaired += 1
    for a, b in zip(fixes, fixes[1:]):
        if b.trace <= a.trace:
            raise DzgError(
                f"{path.name}: trace numbers must rise, but {a.trace} is followed by {b.trace}"
            )
    if n_traces is not None:
        for fix in fixes:
            if not 0 <= fix.trace < n_traces:
                raise DzgError(
                    f"{path.name}: the GPS log names trace {fix.trace}, "
                    f"but the DZT has {n_traces} traces"
                )
    return DzgLog(fixes=tuple(fixes), bad_checksum=bad, unpaired=unpaired)
