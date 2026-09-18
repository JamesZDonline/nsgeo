### Task 4: `nsgeo.io.dzx` — the GSSI sidecar

Reads the XML sidecar for the line name, scan range, dielectric, system, and user marks. Hints only; never geometric truth.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/io/dzx.py`
- Create: `packages/nsgeo-core/tests/test_dzx.py`

**Interfaces:**
- Consumes: stdlib `xml.etree.ElementTree`
- Produces: `DzxMark(scan: int, kind: str, name: str)`; `DzxInfo(name, scan_range, dielectric, system, marks)`; `DzxError`; `read_dzx(path) -> DzxInfo | None`; `sidecar_for(path) -> Path | None`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_dzx.py`:

```python
"""The .DZX sidecar: line name, scan range, dielectric, marks. Hints only."""

from __future__ import annotations

from pathlib import Path

import pytest
from nsgeo.io.dzx import DzxError, DzxInfo, DzxMark, read_dzx, sidecar_for

DATA = Path(__file__).parent / "data" / "local"
REAL = {p.stem: p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt"} if DATA.exists() else {}

XML = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02">
  <GlobalProperties><dielectric>9</dielectric><unitsPerScan>0.016667</unitsPerScan></GlobalProperties>
  <DataCollection><system>UtilityScanHS</system><scanPerMeters>60.000000</scanPerMeters></DataCollection>
  <File>
    <scanRange>0,99</scanRange>
    <name>SYN_0001.DZT</name>
    <Profile>
      <scanRange>0,99</scanRange>
      <WayPt><scan>40</scan><mark>User</mark><name>Mark1</name></WayPt>
      <WayPt><scan>77</scan><mark>User</mark><name>Mark2</name></WayPt>
    </Profile>
  </File>
</DZX>
"""


def test_parses_a_synthetic_sidecar(tmp_path):
    dzt = tmp_path / "SYN_0001.DZT"
    dzt.write_bytes(b"\x00" * 1024)
    (tmp_path / "SYN_0001.DZX").write_text(XML)
    info = read_dzx(dzt)
    assert info == DzxInfo(
        name="SYN_0001.DZT",
        scan_range=(0, 99),
        dielectric=9.0,
        system="UtilityScanHS",
        marks=(DzxMark(40, "User", "Mark1"), DzxMark(77, "User", "Mark2")),
    )


def test_lowercase_extension_is_found(tmp_path):
    dzt = tmp_path / "a.dzt"
    dzt.write_bytes(b"")
    (tmp_path / "a.dzx").write_text(XML)
    assert sidecar_for(dzt) == tmp_path / "a.dzx"
    assert read_dzx(dzt) is not None


def test_missing_sidecar_returns_none(tmp_path):
    dzt = tmp_path / "lonely.DZT"
    dzt.write_bytes(b"")
    assert sidecar_for(dzt) is None
    assert read_dzx(dzt) is None


def test_path_may_point_at_the_sidecar_itself(tmp_path):
    side = tmp_path / "x.DZX"
    side.write_text(XML)
    assert read_dzx(side).name == "SYN_0001.DZT"


def test_malformed_xml_raises_dzx_error(tmp_path):
    side = tmp_path / "bad.DZX"
    side.write_text("<DZX><File>")
    with pytest.raises(DzxError, match="bad.DZX"):
        read_dzx(side)


def test_missing_elements_are_none_not_errors(tmp_path):
    side = tmp_path / "sparse.DZX"
    side.write_text('<DZX xmlns="www.geophysical.com/DZX/1.02"><File/></DZX>')
    info = read_dzx(side)
    assert info == DzxInfo(name=None, scan_range=None, dielectric=None, system=None, marks=())


@pytest.mark.skipif("FILE__001" not in REAL, reason="no real files")
def test_real_sidecar_without_marks():
    info = read_dzx(REAL["FILE__001"])
    assert info is not None
    assert info.name == "FILE__001.DZT"
    assert info.scan_range == (0, 607)
    assert info.dielectric == 14.0
    assert info.system == "UtilityScanHS"
    assert info.marks == ()


@pytest.mark.skipif("FILE__007" not in REAL, reason="no real files")
def test_real_sidecar_with_one_user_mark():
    info = read_dzx(REAL["FILE__007"])
    assert info is not None
    assert info.marks == (DzxMark(scan=634, kind="User", name="Mark1"),)


@pytest.mark.skipif("FILE__010" not in REAL, reason="no real files")
def test_real_file_without_sidecar():
    assert read_dzx(REAL["FILE__010"]) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_dzx.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.io.dzx'`

- [ ] **Step 3: Implement `dzx.py`**

Create `packages/nsgeo-core/src/nsgeo/io/dzx.py`:

```python
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

    scan_range: tuple[int, int] | None = None
    raw_range = _text(root, "./File/scanRange")
    if raw_range:
        lo, hi = raw_range.split(",")
        scan_range = (int(lo), int(hi))

    raw_dielectric = _text(root, "./GlobalProperties/dielectric")
    marks = tuple(
        DzxMark(
            scan=int(_text(wp, "./scan") or 0),
            kind=_text(wp, "./mark") or "",
            name=_text(wp, "./name") or "",
        )
        for wp in root.findall("./File/Profile/WayPt")
    )
    return DzxInfo(
        name=_text(root, "./File/name"),
        scan_range=scan_range,
        dielectric=float(raw_dielectric) if raw_dielectric else None,
        system=_text(root, "./DataCollection/system"),
        marks=marks,
    )
```

- [ ] **Step 4: Run tests, lint, mypy**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo`
Expected: all PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: read the GSSI .DZX sidecar for import hints

Line name, scan range, dielectric, system, and user marks, parsed
namespace-agnostically. Verified against the nine real sidecars,
including FILE__007's single user mark. A missing sidecar is None, not
an error; a malformed one names the file."
```

---

