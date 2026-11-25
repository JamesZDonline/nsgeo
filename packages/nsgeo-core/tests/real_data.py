"""The real survey data under tests/data/local: one named list per survey.

The data is gitignored (DZT headers can carry GPS; see data/local/README.md),
so on CI every list is empty and the tests that use one skip.

Each survey is read from its own folder with a flat listing, never a recursive
search of local/. The surveys reuse file names (FILE__001.DZT is in both) and
differ in line length, so a recursive search mixes them, and a lookup by name
can land in the wrong survey (#141). Key real files by path, never by stem.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing.base import Radargram

DATA = Path(__file__).parent / "data" / "local"


def radar_files(folder: Path, suffix: str) -> list[Path]:
    """Files directly in `folder` with `suffix` in any case, sorted; [] when it is missing."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() == suffix.lower())


def dzt_files(folder: Path) -> list[Path]:
    """The DZT files directly inside `folder`, sorted; [] when it is missing."""
    return radar_files(folder, ".dzt")


CAMPUS_LINES = dzt_files(DATA)
"""The ten campus lines FILE__001-010.DZT (10.1-11.1 m each), at the top level."""

GPS_LINES = dzt_files(DATA / "with-dzg")
"""The sixty GPS-recorded lines for M17 (about 30 m each), a DZG beside each."""

GRID2_LINES = dzt_files(DATA / "grid2")
"""The sixty lines of the second GPS survey, Grid 2 (29.96 m), links to the raw files.

Grid 1 is `GPS_LINES`. Added for #159, whose per-line tests need a second survey."""

DT1_A = radar_files(DATA / "dt1-a", ".dt1")
"""A Sensors & Software survey for M21: LINE00-LINE04 (pulseEKKO PRO, 100 MHz,
1000 samples) and a CMP sounding, each .DT1 with its .HD."""

DT1_B = radar_files(DATA / "dt1-b", ".dt1")
"""A second Sensors & Software survey for M21: yyline3 (a merge of two lines,
500 samples) with its .HD, and a CMP.DT1 kept without its .HD on purpose."""

MALA = radar_files(DATA / "mala", ".rd7")
"""A MALÅ survey for M21b: eight lines DAT_0320-DAT_0330 (GX450 HDR, 1511 samples),
each as .rd7 and .rd3 with one .rad (and .cor, .mrk, .srd, which nothing reads yet)."""

MALA_RD3 = radar_files(DATA / "mala", ".rd3")
"""The same eight MALÅ lines' .rd3 files."""

MALA_EDGE = DATA / "mala-edge"
"""Copies of two MALÅ lines for edge cases: DAT_0328.rd7 without its .rad, and
DAT_0327 (.rd3 and .rd7) with its .rad spelled .RAD."""


HAND_FIT_SITES = (
    sorted((DATA / "hand-fits").glob("*.nsgeo.json")) if (DATA / "hand-fits").is_dir() else []
)
"""Copied site files holding the author's saved hand fits (#140), built by
`make_hand_fit_data.py`. Their lines' DZTs live where the site files say."""


def real_radargram(path: Path) -> Radargram:
    """Channel 0 of the DZT at `path` as a Radargram; skips when the file is missing (CI)."""
    if not path.exists():
        try:
            shown = path.relative_to(DATA).as_posix()
        except ValueError:
            shown = str(path)
        pytest.skip(f"{shown} is not in tests/data/local")
    header = read_header(path)
    tpm = header.traces_per_metre
    return Radargram(
        data=np.asarray(read_samples(path, header)[0], dtype=float),
        dt_ns=header.dt_ns,
        t0_ns=header.position_ns,
        dx_m=1.0 / tpm if tpm > 0 else None,
    )
