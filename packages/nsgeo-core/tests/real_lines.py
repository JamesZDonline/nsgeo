"""The ten real DZT lines, prepared the way the slice tests bin them.

Shared by the site-view and interpolation tests. Lines run along X at
y = 0.25 + 0.5 * i, so the data rows sit 0.5 m apart.
"""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing import build_step
from nsgeo.processing.base import Radargram
from nsgeo.slices import (
    CubeFrame,
    FinishSettings,
    PreparedLine,
    Provenance,
    VolumeSettings,
    ZAxis,
    build_cube,
    fill_levels,
    plan_fill,
    plan_line,
    prepare_volume,
    stream_slice,
)
from nsgeo.velocity import VelocityModel

from tests.real_data import CAMPUS_LINES

needs_real_files = pytest.mark.skipif(
    len(CAMPUS_LINES) < 10, reason="needs the ten real DZT files in tests/data/local"
)

CELL = 0.2
SPACING = 0.5
AXIS = ZAxis.from_range(1.0, 40.0, 0.2165)
WINDOWS = [(10 + 20 * k, 28 + 20 * k) for k in range(5)]
_RADARGRAMS: list = []


def radargrams():
    if not _RADARGRAMS:
        for path in CAMPUS_LINES[:10]:
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


def _provenance(transform: str) -> Provenance:
    return Provenance(
        line_keys=("a",),
        preset_name="p",
        steps=(),
        transform=transform,
        velocity=None,
        built_utc="2026-11-12T00:00:00Z",
        core_version="0.1.0.dev0",
    )


_SQUARED: list = []


def squared_volume():
    """Ten real lines, left bipolar and squared (`amp_square`), binned on a frame with spare rows
    and columns so some cells stay uncovered. Built once."""
    if not _SQUARED:
        lines = []
        for i, path in enumerate(CAMPUS_LINES[:10]):
            header = read_header(path)
            rg = Radargram(
                data=np.asarray(read_samples(path, header)[0], dtype=float),
                dt_ns=header.dt_ns,
                t0_ns=header.position_ns,
            )
            for name in ("time_zero", "dewow", "background_mean", "gain_agc"):
                rg = build_step(name).apply(rg)
            n = rg.data.shape[1]
            local = np.column_stack([np.linspace(0.0, 19.99, n), np.full(n, 0.25 + i * SPACING)])
            lines.append(
                PreparedLine(
                    key=path.name,
                    data=(rg.data**2).astype(np.float32),
                    dt_ns=rg.dt_ns,
                    t0_ns=rg.t0_ns,
                    coords=local,
                )
            )
        frame = CubeFrame((0.0, 0.0), 0.0, CELL, 110, 30, "EPSG:32633")
        plans = [plan_line(p, frame, AXIS) for p in lines]
        cube = build_cube(lines, plans, frame, AXIS, _provenance("amp_square"))
        finish = FinishSettings("idw", 0.25, 1.0)
        weights = plan_fill(cube.coverage() > 0, CELL, "idw", 0.25, 1.0)
        out = np.empty((AXIS.nz, frame.ny, frame.nx), dtype=np.float32)
        fill_levels(cube, weights, finish, out)
        vol = prepare_volume(out, AXIS, VelocityModel.constant(0.071), CELL, VolumeSettings())
        _SQUARED.append((out, vol))
    return _SQUARED[0]
