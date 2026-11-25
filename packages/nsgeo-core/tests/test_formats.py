"""The shared radar header and the format registry (M21a, spec C1-C3, C12).

DZT reads through the registry exactly as it reads through `nsgeo.io.dzt`;
these tests pin the dispatch, the refusals and the companion lookup. The DZT
reader's own tests stay where they are, unedited.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry import GridPlacement
from nsgeo.io import dzt, formats
from nsgeo.io.dzt import DztError, DztHeader
from nsgeo.io.formats import UnsupportedFormat
from nsgeo.io.header import RadarFileError, RadarHeader
from nsgeo.model import Line

from tests.synthetic import write_dzt


def test_a_dzt_header_is_a_radar_header_with_empty_notes(tmp_path):
    p = tmp_path / "a.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32))
    h = formats.read_header(p)
    assert isinstance(h, DztHeader) and isinstance(h, RadarHeader)
    assert h.notes == () and h.not_a_profile == "" and h.format_name == "GSSI DZT"
    assert h == dzt.read_header(p)


@pytest.mark.parametrize("name", ["a.DZT", "a.dzt", "a.Dzt"])
def test_dispatch_ignores_the_case_of_the_extension(tmp_path, name):
    p = tmp_path / name
    write_dzt(p, np.arange(512 * 4, dtype=np.int32).reshape(512, 4))
    h = formats.read_header(p)
    np.testing.assert_array_equal(
        formats.read_samples(p, h), dzt.read_samples(p, dzt.read_header(p))
    )
    np.testing.assert_array_equal(formats.read_samples(p), formats.read_samples(p, h))
    assert formats.trace_count(p, h) == 4
    assert formats.format_for(p).name == "GSSI DZT"


@pytest.mark.parametrize(
    "name, shown", [("a.xyz", r"\.xyz files"), ("noext", "files with no extension")]
)
def test_an_unknown_extension_is_refused_naming_what_is_read(tmp_path, name, shown):
    (tmp_path / name).write_bytes(b"\0" * 2048)
    with pytest.raises(UnsupportedFormat, match=f"^nsgeo does not read {shown}; it reads \\.dzt"):
        formats.read_header(tmp_path / name)


def test_every_reader_error_is_a_radar_file_error():
    assert issubclass(UnsupportedFormat, RadarFileError)
    assert issubclass(DztError, RadarFileError)


def test_the_extension_is_named_as_the_file_spells_it(tmp_path):
    (tmp_path / "a.XyZ").write_bytes(b"")
    with pytest.raises(UnsupportedFormat, match=r"\.XyZ files"):
        formats.format_for(tmp_path / "a.XyZ")


@dataclass(frozen=True)
class _OtherHeader(RadarHeader):
    format_name = "Other"


def test_the_wrong_header_type_is_refused_not_read(tmp_path):
    p = tmp_path / "a.DZT"
    write_dzt(p, np.zeros((512, 4), dtype=np.int32))
    other = _OtherHeader(
        n_samples=512,
        n_channels=1,
        range_ns=100.0,
        position_ns=0.0,
        traces_per_metre=10.0,
        epsr=9.0,
        antenna="",
        notes=(),
        not_a_profile="",
    )
    with pytest.raises(RadarFileError, match="a Other header was given to the GSSI DZT reader"):
        formats.trace_count(p, other)
    with pytest.raises(RadarFileError, match="a Other header was given to the GSSI DZT reader"):
        formats.read_samples(p, other)


def test_the_registry_lists_dzt_and_its_extensions():
    assert ".dzt" in formats.supported_extensions()
    assert formats.FORMATS[0].name == "GSSI DZT" and formats.FORMATS[0].extensions == (".dzt",)
    assert all(e == e.lower() and e.startswith(".") for e in formats.supported_extensions())


def test_companion_returns_the_spelling_on_disk_and_prefers_upper_case(tmp_path):
    (tmp_path / "L.DT1").write_bytes(b"")
    (tmp_path / "L.hd").write_text("")
    assert formats.companion(tmp_path / "L.DT1", ".HD") == tmp_path / "L.hd"
    assert formats.companion(tmp_path / "L.DT1", ".hd") == tmp_path / "L.hd"
    names = {p.name for p in tmp_path.iterdir()}
    (tmp_path / "L.HD").write_text("")
    if len({p.name for p in tmp_path.iterdir()}) > len(names):
        # A case-sensitive filesystem holds both: upper case wins.
        assert formats.companion(tmp_path / "L.DT1", ".HD") == tmp_path / "L.HD"
    assert formats.companion(tmp_path / "missing" / "L.DT1", ".HD") is None
    assert formats.companion(tmp_path / "M.DT1", ".HD") is None


def test_a_line_opens_and_loads_through_the_dispatcher(tmp_path):
    p = tmp_path / "FILE__001.DZT"
    data = np.arange(512 * 6, dtype=np.int32).reshape(512, 6)
    write_dzt(p, data)
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    assert isinstance(line.header, DztHeader) and line.n_traces == 6
    (profile,) = line.load()
    np.testing.assert_array_equal(profile.data, dzt.read_samples(Path(p))[0])


def test_a_note_may_not_hold_the_imports_own_separator():
    fields = dict(
        n_samples=1,
        n_channels=1,
        range_ns=1.0,
        position_ns=0.0,
        traces_per_metre=1.0,
        epsr=9.0,
        antenna="",
    )
    with pytest.raises(ValueError, match="may not contain '; '"):
        _OtherHeader(**fields, notes=("one; two",), not_a_profile="")
    with pytest.raises(ValueError, match="may not contain '; '"):
        _OtherHeader(**fields, notes=(), not_a_profile="one; two")
