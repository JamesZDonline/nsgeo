"""GSSI .DZX sidecar reader.

The sidecar is XML metadata written next to a .DZT: the line's file name,
scan range, dielectric setting, acquisition system, and user marks. Import
uses it for hints (label, dielectric suggestion, marks layer). Nothing here
is geometric truth, and a missing sidecar is normal, not an error.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class DzxError(Exception):
    """Raised when a sidecar exists but cannot be parsed."""


@dataclass(frozen=True)
class DzxMark:
    scan: int
    kind: str
    name: str


@dataclass(frozen=True)
class DzxInfo:
    name: str | None
    scan_range: tuple[int, int] | None
    dielectric: float | None
    system: str | None
    marks: tuple[DzxMark, ...]


def sidecar_for(path: str | Path) -> Path | None:
    """The .DZX beside a .DZT (either case), or the path itself if it is one."""
    path = Path(path)
    if path.suffix.lower() == ".dzx":
        return path if path.exists() else None
    for suffix in (".DZX", ".dzx"):
        candidate = path.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def _strip_namespaces(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _text(root: ET.Element, xpath: str) -> str | None:
    """Stripped text of the first match, or None if absent or blank.

    A whitespace-only element (`<name>   </name>`) is text-wise present but
    carries nothing worth reporting, so it collapses to the same absent
    sentinel as a missing element rather than surfacing as `""`.
    """
    el = root.find(xpath)
    if el is None:
        return None
    text = (el.text or "").strip()
    return text or None


def _mark(waypt: ET.Element) -> DzxMark:
    """Build one mark. A WayPt without a scan is a malformed record, not an
    absent one — unlike a missing top-level field, this raises rather than
    inventing scan 0, which would be a fabricated placement.
    """
    raw_scan = _text(waypt, "./scan")
    if raw_scan is None:
        raise ValueError("WayPt has no scan")
    return DzxMark(
        scan=int(raw_scan),
        kind=_text(waypt, "./mark") or "",
        name=_text(waypt, "./name") or "",
    )


def read_dzx(path: str | Path) -> DzxInfo | None:
    """Parse the sidecar for `path`, or return None when there is none."""
    side = sidecar_for(path)
    if side is None:
        return None
    try:
        # ElementTree expands internal entities, so a hostile "billion
        # laughs" sidecar is a memory DoS; accepted, since defusedxml would
        # break the stdlib-only rule and this is a file the user chose to open.
        root = ET.parse(side).getroot()
    except ET.ParseError as exc:
        raise DzxError(f"{side.name} is not well-formed XML: {exc}") from exc
    except OSError as exc:
        raise DzxError(f"{side.name} could not be read: {exc}") from exc
    _strip_namespaces(root)

    # The documented shape has exactly one File. If more appear, name,
    # scanRange, and marks all come from that same one rather than mixing
    # two lines' worth of data (a stray extra File's marks are its own line's
    # scan axis, not this one's).
    file_el = root.find("./File")

    try:
        scan_range: tuple[int, int] | None = None
        name: str | None = None
        marks: tuple[DzxMark, ...] = ()
        if file_el is not None:
            raw_range = _text(file_el, "./scanRange")
            if raw_range:
                lo, hi = raw_range.split(",")
                scan_range = (int(lo), int(hi))
            name = _text(file_el, "./name")
            marks = tuple(_mark(wp) for wp in file_el.findall("./Profile/WayPt"))

        raw_dielectric = _text(root, "./GlobalProperties/dielectric")
        dielectric = float(raw_dielectric) if raw_dielectric else None
    except ValueError as exc:
        raise DzxError(f"{side.name} has a malformed field: {exc}") from exc

    return DzxInfo(
        name=name,
        scan_range=scan_range,
        dielectric=dielectric,
        system=_text(root, "./DataCollection/system"),
        marks=marks,
    )
