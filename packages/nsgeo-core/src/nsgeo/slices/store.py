"""The cube on disk.

`.npz` rather than GeoTIFF because the core has numpy and nothing else --
writing a georeferenced raster needs GDAL, which lives on the plugin side.
The plugin converts on the way to the map; this is the working format a
rebuild reads.

The metadata rides as a JSON string in a 0-d array, so the file loads with
`allow_pickle=False`. Pickle in a data file is a remote-code-execution
surface in exchange for nothing here: every field is a number or a string.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis

STORE_VERSION = 1


class CubeStoreError(Exception):
    """Raised when a cube file is missing, unreadable, or not a cube."""


def _meta(cube: SliceCube) -> dict[str, Any]:
    return {
        "store_version": STORE_VERSION,
        "frame": {
            "origin": list(cube.frame.origin),
            "azimuth": cube.frame.azimuth,
            "cell": cube.frame.cell,
            "nx": cube.frame.nx,
            "ny": cube.frame.ny,
            "crs": cube.frame.crs,
        },
        "z": {"t0_ns": cube.z.t0_ns, "dz_ns": cube.z.dz_ns, "nz": cube.z.nz},
        "provenance": cube.provenance.to_dict(),
    }


def save_cube(cube: SliceCube, path: str | Path) -> None:
    """Write `cube` to `path`, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        mean=cube.mean.astype(np.float32, copy=False),
        count=cube.count.astype(np.int32, copy=False),
        meta=np.array(json.dumps(_meta(cube))),
    )


def load_cube(path: str | Path) -> SliceCube:
    """Read a cube written by `save_cube`."""
    path = Path(path)
    if not path.exists():
        raise CubeStoreError(f"no cube file at {path}")
    try:
        with np.load(path, allow_pickle=False) as bundle:
            if not {"mean", "count", "meta"} <= set(bundle.files):
                raise CubeStoreError(
                    f"{path} is not a cube: expected mean, count and meta, "
                    f"found {sorted(bundle.files)}"
                )
            mean = bundle["mean"].astype(np.float32, copy=False)
            count = bundle["count"].astype(np.int32, copy=False)
            meta = json.loads(str(bundle["meta"].item()))
    except CubeStoreError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise CubeStoreError(f"{path} could not be read as a cube: {exc}") from exc

    frame_doc = meta["frame"]
    z_doc = meta["z"]
    return SliceCube(
        frame=CubeFrame(
            origin=(float(frame_doc["origin"][0]), float(frame_doc["origin"][1])),
            azimuth=float(frame_doc["azimuth"]),
            cell=float(frame_doc["cell"]),
            nx=int(frame_doc["nx"]),
            ny=int(frame_doc["ny"]),
            crs=frame_doc["crs"],
        ),
        z=ZAxis(t0_ns=float(z_doc["t0_ns"]), dz_ns=float(z_doc["dz_ns"]), nz=int(z_doc["nz"])),
        mean=mean,
        count=count,
        provenance=Provenance.from_dict(meta["provenance"]),
    )
