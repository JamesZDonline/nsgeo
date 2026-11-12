"""Real-data helpers for the destagger tests: Nashville Grid 1 and Grid 2 as measure lines.

Lines are placed the way the survey was walked: zigzag at 0.5 m, line 1
forward, on grid "G". Reading and binning a file takes about 0.15 s, so the
binned envelope is cached per path for the whole test session.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from nsgeo.destagger import EnvelopeBins, MeasureLine, envelope_bins
from nsgeo.geometry import GridPlacement
from nsgeo.io.dzt import read_header, read_samples

from tests.real_data import GPS_LINES, GRID2_LINES

needs_grid1 = pytest.mark.skipif(
    len(GPS_LINES) != 60, reason="needs Grid 1 in tests/data/local/with-dzg"
)
needs_grid2 = pytest.mark.skipif(
    len(GRID2_LINES) != 60, reason="needs Grid 2 in tests/data/local/grid2"
)

GRID1_LENGTH = 29.98
GRID2_LENGTH = 29.96

_BINS: dict[Path, EnvelopeBins] = {}


def bins_for(path: Path) -> EnvelopeBins:
    if path not in _BINS:
        header = read_header(path)
        samples = read_samples(path, header)[0]
        _BINS[path] = envelope_bins(samples, header.dt_ns, header.position_ns)
    return _BINS[path]


def key_for(path: Path) -> str:
    """Grid folder and file name: the surveys reuse file names."""
    return f"{path.parent.name}/{path.name}"


def lines_for(
    paths,
    length: float,
    *,
    axis: str = "y",
    fitted: bool = False,
    mirrored: bool = False,
    travel_shift: float | list[float] = 0.0,
    moved: dict[int, float] | None = None,
    skew: float = 0.0,
) -> list[MeasureLine]:
    """Zigzag lines at 0.5 m, line 1 forward, on grid "G".

    `fitted`: scale = length / recorded span, both ends on the edges.
    `moved`: 0-based index -> metres added along that line's travel.
    `skew`: adds skew x rank to every start. `mirrored`: start -> length - start,
    direction flipped. `travel_shift`: one value, or one per line.
    """
    out = []
    for k, path in enumerate(paths):
        header = read_header(path)
        bins = bins_for(path)
        n = bins.data.shape[1]
        forward = k % 2 == 0
        direction = 1 if forward else -1
        scale = 1.0
        if fitted:
            scale = length / ((n - 1) / header.traces_per_metre)
        start = (0.0 if forward else length) + skew * k
        start += direction * (moved or {}).get(k, 0.0)
        if mirrored:
            start, direction = length - start, -direction
        shift = (
            travel_shift[k] if isinstance(travel_shift, (list, tuple, np.ndarray)) else travel_shift
        )
        placement = GridPlacement(
            "G", axis, 0.25 + 0.5 * k, start, direction, f"line {k + 1}", scale, float(shift)
        )
        out.append(MeasureLine(key_for(path), bins, placement, header))
    return out


def with_header(line: MeasureLine, **changes) -> MeasureLine:
    return replace(line, header=replace(line.header, **changes))
