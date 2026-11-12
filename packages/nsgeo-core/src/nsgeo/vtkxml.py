"""Streaming VTK XML writers: ImageData (.vti) and PolyData (.vtp), numpy only.

Both write the appended-raw layout (little endian, UInt64 length headers) that
ParaView and VTK read directly. `write_image_data` takes each array as a
callable that yields chunks, so a volume never has to sit in memory whole.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Callable

import numpy as np

__all__ = ["image_data_bytes", "write_image_data", "write_poly_data"]

_HEADER_ALLOWANCE = 4096
_TYPES = {
    np.dtype("float32"): "Float32",
    np.dtype("float64"): "Float64",
    np.dtype("int32"): "Int32",
    np.dtype("int64"): "Int64",
}


def _num(values: Sequence[float]) -> str:
    return " ".join(repr(float(v)) for v in values)


def _tag(name: str | None, vtk_type: str, offset: int, ncomp: int = 1) -> str:
    label = f' Name="{name}"' if name else ""
    return (
        f'<DataArray type="{vtk_type}"{label} NumberOfComponents="{ncomp}" '
        f'format="appended" offset="{offset}"/>'
    )


def image_data_bytes(shape: tuple[int, int, int], n_arrays: int) -> int:
    """The exact payload of `write_image_data` plus a fixed header allowance (4096)."""
    nx, ny, nz = shape
    return n_arrays * (8 + 4 * nx * ny * nz) + _HEADER_ALLOWANCE


def write_image_data(
    path: Path,
    *,
    origin: tuple[float, float, float],
    spacing: tuple[float, float, float],
    shape: tuple[int, int, int],
    arrays: Sequence[tuple[str, Callable[[], Iterator[np.ndarray]]]],
) -> int:
    """Write float32 point arrays on a regular grid; returns the bytes written.

    `shape` is (nx, ny, nz). Each array's callable yields chunks in VTK order (x
    fastest, then y, then z rising). The file goes to `path` + ".part" and is then
    renamed; an array of the wrong length raises ValueError and leaves no file.
    """
    path = Path(path)
    nx, ny, nz = shape
    n = nx * ny * nz
    if not arrays:
        raise ValueError("write_image_data needs at least one array")
    ext = f"0 {nx - 1} 0 {ny - 1} 0 {nz - 1}"
    per = 8 + 4 * n
    tags = "\n".join(_tag(name, "Float32", i * per) for i, (name, _) in enumerate(arrays))
    head = (
        '<?xml version="1.0"?>\n'
        '<VTKFile type="ImageData" version="1.0" byte_order="LittleEndian" header_type="UInt64">\n'
        f'<ImageData WholeExtent="{ext}" Origin="{_num(origin)}" '
        f'Spacing="{_num(spacing)}" Direction="1 0 0 0 1 0 0 0 1">\n'
        f'<Piece Extent="{ext}">\n<PointData Scalars="{arrays[0][0]}">\n{tags}\n'
        "</PointData>\n<CellData/>\n</Piece>\n</ImageData>\n"
        '<AppendedData encoding="raw">\n_'
    )
    part = path.with_name(path.name + ".part")
    try:
        with open(part, "wb") as f:
            f.write(head.encode())
            for name, make in arrays:
                f.write(struct.pack("<Q", 4 * n))
                count = 0
                for chunk in make():
                    flat = np.ascontiguousarray(chunk, dtype="<f4").ravel()
                    count += flat.size
                    if count > n:
                        break
                    f.write(flat.tobytes())
                if count != n:
                    raise ValueError(f"array {name!r} gave {count} values, expected {n}")
            f.write(b"\n</AppendedData>\n</VTKFile>\n")
            size = f.tell()
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return size


def _cells(groups: Sequence[Sequence[int]]) -> tuple[np.ndarray, np.ndarray]:
    conn = np.array([i for g in groups for i in g], dtype=np.int64)
    offs = np.cumsum([len(g) for g in groups]).astype(np.int64)
    return conn, offs


def write_poly_data(
    path: Path,
    points: np.ndarray,
    point_data: Mapping[str, np.ndarray],
    *,
    verts: Sequence[Sequence[int]] = (),
    lines: Sequence[Sequence[int]] = (),
    polys: Sequence[Sequence[int]] = (),
) -> int:
    """Write points, point arrays and vertex, line and polygon cells; returns bytes written."""
    path = Path(path)
    pts = np.asarray(points, dtype="<f4").reshape(-1, 3)
    names = list(point_data)
    arrays = []
    for name in names:
        a = np.ascontiguousarray(point_data[name]).ravel()
        if a.dtype not in _TYPES:
            raise ValueError(f"array {name!r} has unsupported dtype {a.dtype}")
        if a.size != len(pts):
            raise ValueError(f"array {name!r} has {a.size} values for {len(pts)} points")
        arrays.append(a.astype(a.dtype.newbyteorder("<")))
    vc, vo = _cells(verts)
    lc, lo = _cells(lines)
    pc, po = _cells(polys)
    blobs = [pts.ravel(), *arrays, vc, vo, lc, lo, pc, po]
    offsets, pos = [], 0
    for b in blobs:
        offsets.append(pos)
        pos += 8 + b.nbytes
    k = len(arrays)
    pd_tags = "\n".join(
        _tag(n, _TYPES[a.dtype], offsets[1 + i]) for i, (n, a) in enumerate(zip(names, arrays))
    )
    rest = offsets[1 + k :]
    xml = (
        '<?xml version="1.0"?>\n'
        '<VTKFile type="PolyData" version="1.0" byte_order="LittleEndian" header_type="UInt64">\n'
        "<PolyData>\n"
        f'<Piece NumberOfPoints="{len(pts)}" NumberOfVerts="{len(vo)}" '
        f'NumberOfLines="{len(lo)}" NumberOfStrips="0" NumberOfPolys="{len(po)}">\n'
        f"<PointData>\n{pd_tags}\n</PointData>\n"
        f"<Points>\n{_tag(None, 'Float32', offsets[0], 3)}\n</Points>\n"
        f"<Verts>\n{_tag('connectivity', 'Int64', rest[0])}\n"
        f"{_tag('offsets', 'Int64', rest[1])}\n</Verts>\n"
        f"<Lines>\n{_tag('connectivity', 'Int64', rest[2])}\n"
        f"{_tag('offsets', 'Int64', rest[3])}\n</Lines>\n"
        f"<Polys>\n{_tag('connectivity', 'Int64', rest[4])}\n"
        f"{_tag('offsets', 'Int64', rest[5])}\n</Polys>\n"
        "</Piece>\n</PolyData>\n"
        '<AppendedData encoding="raw">\n_'
    )
    part = path.with_name(path.name + ".part")
    try:
        with open(part, "wb") as f:
            f.write(xml.encode())
            for b in blobs:
                f.write(struct.pack("<Q", b.nbytes))
                f.write(b.tobytes())
            f.write(b"\n</AppendedData>\n</VTKFile>\n")
            size = f.tell()
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return size
