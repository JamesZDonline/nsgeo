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


def test_empty_file_raises_dzx_error(tmp_path):
    side = tmp_path / "empty.DZX"
    side.write_text("")
    with pytest.raises(DzxError, match="empty.DZX"):
        read_dzx(side)


def test_non_numeric_dielectric_raises_dzx_error(tmp_path):
    side = tmp_path / "baddielectric.DZX"
    side.write_text(
        '<DZX xmlns="www.geophysical.com/DZX/1.02">'
        "<GlobalProperties><dielectric>abc</dielectric></GlobalProperties>"
        "</DZX>"
    )
    with pytest.raises(DzxError, match="baddielectric.DZX"):
        read_dzx(side)


def test_waypt_without_scan_raises_dzx_error(tmp_path):
    """A WayPt missing its scan is a malformed record, not an absent one:
    fabricating scan=0 would draw a mark at a position the file never gave.
    """
    side = tmp_path / "noscan.DZX"
    side.write_text(
        '<DZX xmlns="www.geophysical.com/DZX/1.02">'
        "<File><Profile><WayPt><mark>User</mark><name>M1</name></WayPt></Profile></File>"
        "</DZX>"
    )
    with pytest.raises(DzxError, match="noscan.DZX"):
        read_dzx(side)


TWO_FILE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02">
  <File>
    <scanRange>0,5</scanRange>
    <name>A.DZT</name>
    <Profile><WayPt><scan>1</scan><mark>User</mark><name>a</name></WayPt></Profile>
  </File>
  <File>
    <scanRange>10,15</scanRange>
    <name>B.DZT</name>
    <Profile><WayPt><scan>2</scan><mark>User</mark><name>b</name></WayPt></Profile>
  </File>
</DZX>
"""


def test_multiple_file_elements_do_not_mix_marks_across_lines(tmp_path):
    """Only the real files' single-File shape is documented; a stray second
    File must not contribute its marks to the first File's line.
    """
    side = tmp_path / "twofile.DZX"
    side.write_text(TWO_FILE_XML)
    info = read_dzx(side)
    assert info == DzxInfo(
        name="A.DZT",
        scan_range=(0, 5),
        dielectric=None,
        system=None,
        marks=(DzxMark(1, "User", "a"),),
    )


def test_whitespace_only_text_is_none_not_empty_string(tmp_path):
    side = tmp_path / "blank.DZX"
    side.write_text(
        '<DZX xmlns="www.geophysical.com/DZX/1.02">'
        "<DataCollection><system>   </system></DataCollection>"
        "<File><name>   </name></File>"
        "</DZX>"
    )
    info = read_dzx(side)
    assert info == DzxInfo(name=None, scan_range=None, dielectric=None, system=None, marks=())


def test_sidecar_that_is_a_directory_raises_dzx_error(tmp_path):
    dzt = tmp_path / "weird.DZT"
    dzt.write_bytes(b"")
    (tmp_path / "weird.DZX").mkdir()
    with pytest.raises(DzxError, match="weird.DZX"):
        read_dzx(dzt)


NO_NAMESPACE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DZX>
  <GlobalProperties><dielectric>9</dielectric></GlobalProperties>
  <DataCollection><system>UtilityScanHS</system></DataCollection>
  <File><scanRange>0,99</scanRange><name>SYN_0001.DZT</name></File>
</DZX>
"""

OTHER_NAMESPACE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="urn:example:some-other-dzx-namespace">
  <GlobalProperties><dielectric>9</dielectric></GlobalProperties>
  <DataCollection><system>UtilityScanHS</system></DataCollection>
  <File><scanRange>0,99</scanRange><name>SYN_0001.DZT</name></File>
</DZX>
"""


def test_reader_is_not_pinned_to_a_namespace(tmp_path):
    """`_strip_namespaces` is what makes this version-independent rather than
    pinned to 1.02; every other fixture happens to use exactly that
    namespace, so this is the only test that would notice if it broke.
    """
    side = tmp_path / "otherns.DZX"
    side.write_text(OTHER_NAMESPACE_XML)
    info = read_dzx(side)
    assert info is not None
    assert info.name == "SYN_0001.DZT"
    assert info.dielectric == 9.0
    assert info.system == "UtilityScanHS"


def test_reader_tolerates_no_namespace_at_all(tmp_path):
    side = tmp_path / "nons.DZX"
    side.write_text(NO_NAMESPACE_XML)
    info = read_dzx(side)
    assert info is not None
    assert info.name == "SYN_0001.DZT"
    assert info.dielectric == 9.0
    assert info.system == "UtilityScanHS"


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
