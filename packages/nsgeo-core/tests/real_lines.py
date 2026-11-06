"""The ten real DZT lines, prepared the way the slice tests bin them.

Shared by the site-view and interpolation tests. Lines run along X at
y = 0.25 + 0.5 * i, so the data rows sit 0.5 m apart.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing import build_step
from nsgeo.processing.base import Radargram
from nsgeo.slices import PreparedLine, ZAxis, plan_line, stream_slice

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []
needs_real_files = pytest.mark.skipif(
    len(FILES) < 10, reason="needs the ten real DZT files in tests/data/local"
)

CELL = 0.2
SPACING = 0.5
AXIS = ZAxis.from_range(1.0, 40.0, 0.2165)
WINDOWS = [(10 + 20 * k, 28 + 20 * k) for k in range(5)]
_RADARGRAMS: list = []


def radargrams():
    if not _RADARGRAMS:
        for path in FILES[:10]:
            header = read_header(path)
            rg = Radargram(
                data=np.asarray(read_samples(path, header)[0], dtype=float),
                dt_ns=header.dt_ns,
                t0_ns=header.position_ns,
            )
            for name in ("time_zero", "dewow", "background_mean", "gain_agc", "amp_envelope"):
                rg = build_step(name).apply(rg)
            _RADARGRAMS.append((path.name, rg))
    return _RADARGRAMS


def prepared_lines(indices, to_world):
    out = []
    for i in indices:
        name, rg = radargrams()[i]
        n = rg.data.shape[1]
        local = np.column_stack([np.linspace(0.0, 19.99, n), np.full(n, 0.25 + i * SPACING)])
        out.append(
            PreparedLine(
                key=name,
                data=rg.data.astype(np.float32),
                dt_ns=rg.dt_ns,
                t0_ns=rg.t0_ns,
                coords=to_world(local),
            )
        )
    return out


def binned(lines, frame, k0, k1):
    plans = [plan_line(p, frame, AXIS) for p in lines]
    return stream_slice(lines, plans, frame, AXIS, k0, k1)
