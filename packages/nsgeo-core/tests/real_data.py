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

DATA = Path(__file__).parent / "data" / "local"


def dzt_files(folder: Path) -> list[Path]:
    """The DZT files directly inside `folder`, sorted; [] when it is missing."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() == ".dzt")


CAMPUS_LINES = dzt_files(DATA)
"""The ten campus lines FILE__001-010.DZT (10.1-11.1 m each), at the top level."""

GPS_LINES = dzt_files(DATA / "with-dzg")
"""The sixty GPS-recorded lines for M17 (about 30 m each), a DZG beside each."""

GRID2_LINES = dzt_files(DATA / "grid2")
"""The sixty lines of Nashville City Cemetery 2023 Grid 2 (29.96 m), links to the raw files.

Grid 1 is `GPS_LINES`. Added for #159, whose per-line tests need a second survey."""


HAND_FIT_SITES = (
    sorted((DATA / "hand-fits").glob("*.nsgeo.json")) if (DATA / "hand-fits").is_dir() else []
)
"""Copied site files holding the author's saved hand fits (#140), built by
`make_hand_fit_data.py`. Their lines' DZTs live where the site files say."""
