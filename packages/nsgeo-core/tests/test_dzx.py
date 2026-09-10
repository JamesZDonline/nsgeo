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


def test_malformed_field_raises_dzx_error_not_bare_valueerror(tmp_path):
    side = tmp_path / "badfield.DZX"
    side.write_text(
        '<DZX xmlns="www.geophysical.com/DZX/1.02"><File><scanRange>oops</scanRange></File></DZX>'
    )
    with pytest.raises(DzxError, match="badfield.DZX"):
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
