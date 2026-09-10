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
    el = root.find(xpath)
    return el.text.strip() if el is not None and el.text else None


def read_dzx(path: str | Path) -> DzxInfo | None:
    """Parse the sidecar for `path`, or return None when there is none."""
    side = sidecar_for(path)
    if side is None:
        return None
    try:
        root = ET.parse(side).getroot()
    except ET.ParseError as exc:
        raise DzxError(f"{side.name} is not well-formed XML: {exc}") from exc
    _strip_namespaces(root)

    try:
        scan_range: tuple[int, int] | None = None
        raw_range = _text(root, "./File/scanRange")
        if raw_range:
            lo, hi = raw_range.split(",")
            scan_range = (int(lo), int(hi))

        raw_dielectric = _text(root, "./GlobalProperties/dielectric")
        dielectric = float(raw_dielectric) if raw_dielectric else None

        marks = tuple(
            DzxMark(
                scan=int(_text(wp, "./scan") or 0),
                kind=_text(wp, "./mark") or "",
                name=_text(wp, "./name") or "",
            )
            for wp in root.findall("./File/Profile/WayPt")
        )
    except ValueError as exc:
        raise DzxError(f"{side.name} has a malformed field: {exc}") from exc

    return DzxInfo(
        name=_text(root, "./File/name"),
        scan_range=scan_range,
        dielectric=dielectric,
        system=_text(root, "./DataCollection/system"),
        marks=marks,
    )
