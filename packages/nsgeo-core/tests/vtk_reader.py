"""Test helper: read back the appended-raw VTK XML files `nsgeo.vtkxml` writes."""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

_DTYPES = {"Float32": "<f4", "Float64": "<f8", "Int32": "<i4", "Int64": "<i8", "UInt8": "|u1"}


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(t) for t in text.split())


def read_vtk_xml(path: Path) -> dict:
    raw = Path(path).read_bytes()
    cut = raw.index(b"<AppendedData")
    blob = raw[raw.index(b"_", cut) + 1 :]
    root = ET.fromstring(raw[:cut] + b"</VTKFile>")

    def array(el: ET.Element) -> np.ndarray:
        off = int(el.get("offset"))
        (nbytes,) = struct.unpack_from("<Q", blob, off)
        dtype = np.dtype(_DTYPES[el.get("type")])
        a = np.frombuffer(blob, dtype=dtype, count=nbytes // dtype.itemsize, offset=off + 8)
        ncomp = int(el.get("NumberOfComponents", "1"))
        return a.reshape(-1, ncomp) if ncomp > 1 else a

    piece = root.find(".//Piece")
    doc: dict = {
        "point_data": {e.get("Name"): array(e) for e in piece.findall("PointData/DataArray")}
    }
    image = root.find("ImageData")
    if image is not None:
        doc["WholeExtent"] = tuple(int(v) for v in image.get("WholeExtent").split())
        doc["Origin"] = _floats(image.get("Origin"))
        doc["Spacing"] = _floats(image.get("Spacing"))
        doc["Scalars"] = piece.find("PointData").get("Scalars")
    else:
        doc["NumberOfPoints"] = int(piece.get("NumberOfPoints"))
        doc["points"] = array(piece.find("Points/DataArray"))
        for kind in ("Verts", "Lines", "Polys"):
            for e in piece.findall(f"{kind}/DataArray"):
                doc[f"{kind}_{e.get('Name')}"] = array(e)
    return doc
