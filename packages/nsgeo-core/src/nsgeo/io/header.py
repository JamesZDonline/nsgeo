"""The header every radar format shares (spec M21, C1).

`RadarHeader` holds the facts about a radar file that code outside the
readers uses: the sample axis, where time zero falls, the trace spacing, a
dielectric and an antenna name. Each format subclasses it with what its own
reader needs, so `line.header.epsr` and the like read the same whatever the
file, and a `DztHeader` is still a `DztHeader`.

Python 3.9 is supported, so dataclasses cannot be `kw_only`: no field here
has a default, which lets every subclass add required fields of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


class RadarFileError(Exception):
    """Raised when a radar file is malformed, unsupported, or missing a companion file."""


class NoGpsLog(RadarFileError):
    """Raised for a line whose format has a GPS source, but which has no log:
    no DZG or .cor beside it, or no position in its traces (spec M21 §16)."""


@dataclass(frozen=True)
class RadarHeader:
    #: The format's name as the user reads it, e.g. "GSSI DZT".
    format_name: ClassVar[str] = "radar"

    n_samples: int
    n_channels: int
    range_ns: float
    #: The time of the first sample, in ns after time zero (negative when the
    #: record starts before it).
    position_ns: float
    #: 0 when the line was not recorded against distance (time-triggered).
    traces_per_metre: float
    epsr: float
    antenna: str
    #: Facts the reader wants the user told at import, one sentence each,
    #: none containing "; " (the import joins a row's notes with it).
    notes: tuple[str, ...]
    #: "" for a profile; otherwise why the file is not one (e.g. a CMP sounding).
    not_a_profile: str

    def __post_init__(self) -> None:
        for text in (*self.notes, self.not_a_profile):
            if "; " in text:
                raise ValueError(f"a header note may not contain '; ': {text!r}")

    @property
    def dt_ns(self) -> float:
        """Sample interval in nanoseconds."""
        return self.range_ns / self.n_samples


def companion(path: str | Path, suffix: str) -> Path | None:
    """The file beside `path` with the same stem and `suffix`, in the spelling on disk.

    Tries `suffix` in upper case, then lower case, matched against the real
    directory entries rather than probed with `Path.exists()`, for the reason
    `nsgeo.io.dzx.sidecar_for` gives: on a case-insensitive filesystem an
    exists() probe returns a spelling the directory does not hold, and that
    spelling then reaches the user in messages. None when there is no such
    file or the directory cannot be read.
    """
    path = Path(path)
    parent = path.parent
    try:
        names = {entry.name for entry in parent.iterdir()}
    except OSError:
        return None
    for candidate in (path.stem + suffix.upper(), path.stem + suffix.lower()):
        if candidate in names:
            return parent / candidate
    return None
