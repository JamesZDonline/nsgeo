"""CRS, outline and gather helpers for the site view (#75).

Pure functions of a frame, a lattice and a transform context: the site engine
(`SiteEngine._gather`, `_grid_extents`) and the export (`site_export.world_to_frame`)
both use them. Each call builds its own `QgsCoordinateTransform` and holds no Qt
object beyond it, so a call is safe off the GUI thread as long as its
`QgsCoordinateTransformContext` argument is a copy taken on the GUI thread.
"""

from __future__ import annotations

import math
import struct

import numpy as np
from nsgeo.slices import (
    CubeFrame,
    Footprint,
    SiteLattice,
    bilinear_taps,
    footprint,
    slice_extent,
)
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsGeometry,
)

#: Points per edge when a frame's outline is transformed into another CRS.
#: A transverse Mercator edge is not quite straight in a neighbouring zone.
EDGE_POINTS = 8

#: WKB header of a little-endian 2-D LineString: byte order, type, point count.
_WKB_LINESTRING = 2
_WKB_HEADER = 9


def transform_points(
    points: np.ndarray, source: str, target: str, context: QgsCoordinateTransformContext
) -> np.ndarray:
    """(n, 2) points from `source` to `target` in one C++ call; a missing transform raises.

    The points travel as one WKB LineString, transformed together and read back
    (200 k points: 0.10 s, against 0.92 s a point at a time, identical results).
    An invalid `QgsCoordinateTransform` returns its input unchanged while
    reporting success (`layers._require_transform`), which would draw a grid in
    the wrong place without a word, so it raises.
    """
    transform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem(source), QgsCoordinateReferenceSystem(target), context
    )
    if not transform.isValid():
        raise RuntimeError(f"no coordinate transform from {source} to {target}")
    pts = np.ascontiguousarray(points, dtype="<f8").reshape(-1, 2)
    n = len(pts)
    if n == 0:
        return np.empty((0, 2), dtype=float)
    sent = pts if n > 1 else np.vstack([pts, pts])  # a LineString needs two points
    header = struct.pack("<BII", 1, _WKB_LINESTRING, len(sent))
    geometry = QgsGeometry()
    geometry.fromWkb(header + sent.tobytes())
    if geometry.isNull():
        raise RuntimeError("could not pack the points for the coordinate transform")
    if geometry.transform(transform) != Qgis.GeometryOperationResult.Success:
        raise RuntimeError(f"could not transform points from {source} to {target}")
    wkb = bytes(geometry.asWkb())
    order, kind, count = struct.unpack_from("<BII", wkb, 0)
    if (order, kind, count) != (1, _WKB_LINESTRING, len(sent)) or len(wkb) != (
        _WKB_HEADER + 16 * len(sent)
    ):
        raise RuntimeError(
            f"unexpected geometry back from the coordinate transform: header {(order, kind, count)}"
        )
    moved = np.frombuffer(wkb, dtype="<f8", offset=_WKB_HEADER).reshape(-1, 2)
    return moved[:n].astype(float)


def extent_in(
    frame: CubeFrame, crs: str, context: QgsCoordinateTransformContext
) -> tuple[float, float, float, float]:
    """`(xmin, ymin, xmax, ymax)` of `frame` in `crs`: its slice extent when it is
    already there, else the bounds of its outline, `EDGE_POINTS` a side, moved."""
    if frame.crs == crs:
        return slice_extent(frame)
    x_hat, y_hat = frame.axes()
    w, h = frame.nx * frame.cell, frame.ny * frame.cell
    t = np.linspace(0.0, 1.0, EDGE_POINTS + 1)
    local = np.concatenate(
        [
            np.column_stack([t * w, np.zeros_like(t)]),
            np.column_stack([np.full_like(t, w), t * h]),
            np.column_stack([t * w, np.full_like(t, h)]),
            np.column_stack([np.zeros_like(t), t * h]),
        ]
    )
    outline = np.asarray(frame.origin) + local[:, :1] * x_hat + local[:, 1:] * y_hat
    moved = transform_points(outline, frame.crs, crs, context)
    return (
        float(moved[:, 0].min()),
        float(moved[:, 1].min()),
        float(moved[:, 0].max()),
        float(moved[:, 1].max()),
    )


def gather_footprint(
    frame: CubeFrame, lattice: SiteLattice, context: QgsCoordinateTransformContext
) -> Footprint:
    """`frame`'s bilinear taps under each lattice pixel, kept to its own window.

    Only the pixels inside the frame's extent (plus one) are looked up and, for a
    frame in another CRS, transformed into it first. The result is a `Footprint`,
    the tight window around the pixels inside the frame (final review I1): every
    pixel outside it is outside the frame, so the tick composes over the window alone.
    """
    xmin, ymin, xmax, ymax = extent_in(frame, lattice.crs, context)
    p = lattice.pixel
    col0 = max(0, math.floor((xmin - lattice.x0) / p) - 1)
    col1 = min(lattice.width, math.ceil((xmax - lattice.x0) / p) + 1)
    row0 = max(0, math.floor((lattice.y1 - ymax) / p) - 1)
    row1 = min(lattice.height, math.ceil((lattice.y1 - ymin) / p) + 1)
    if col1 <= col0 or row1 <= row0:
        return footprint(bilinear_taps(frame, np.empty((0, 2))), 0, 0)
    cols = np.arange(col0, col1)
    rows = np.arange(row0, row1)
    # The same centres as `SiteLattice.pixel_centres`, restricted.
    xs = lattice.x0 + (cols.astype(float) + 0.5) * p
    ys = lattice.y1 - (rows.astype(float) + 0.5) * p
    grid_x, grid_y = np.meshgrid(xs, ys)
    centres = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    if frame.crs != lattice.crs:
        centres = transform_points(centres, lattice.crs, frame.crs, context)
    taps = bilinear_taps(frame, centres)
    return footprint(taps, row1 - row0, col1 - col0, row0, col0)
