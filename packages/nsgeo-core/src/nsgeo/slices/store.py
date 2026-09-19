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
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis

STORE_VERSION = 1


class CubeStoreError(Exception):
    """Raised when a cube file is missing, unreadable, or not a cube."""


def _npz_path(path: str | Path) -> Path:
    """Normalise to the `.npz` name `np.savez_compressed` actually writes.

    `np.savez_compressed` APPENDS `.npz` unless the name already ends with
    it -- it never touches an existing suffix. `Path.with_suffix` REPLACES
    the last suffix instead, which is a different rule: it silently
    aliased "grid.v1" and "grid.v2" onto the same "grid.npz", so a second
    save destroyed the first cube with no error anywhere. A version tag, a
    date, or a decimal in a user-typed cube name all contain a dot that is
    not an extension, so this must mirror numpy's own append rule, not
    Path's replace rule.
    """
    p = Path(path)
    return p if p.suffix == ".npz" else p.with_name(p.name + ".npz")


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
    path = _npz_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        mean=cube.mean.astype(np.float32, copy=False),
        count=cube.count.astype(np.int32, copy=False),
        meta=np.array(json.dumps(_meta(cube))),
    )


def load_cube(path: str | Path) -> SliceCube:
    """Read a cube written by `save_cube`.

    Every way a `.npz` can be a bad cube -- missing, truncated, an
    unrelated zip, malformed or incomplete metadata, metadata that
    disagrees with the arrays, an unsupported store version -- raises
    `CubeStoreError` and nothing else. A caller's only reasonable response
    to any of them is the same offer to rebuild, and a raw exception
    escaping here would reach that caller with no way to tell "corrupt"
    from "not built yet".
    """
    try:
        path = _npz_path(path)
    except ValueError as exc:
        raise CubeStoreError(f"{path!r} is not a usable cube path: {exc}") from exc
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

        store_version = meta["store_version"]
        if store_version != STORE_VERSION:
            raise CubeStoreError(
                f"{path} was written by cube store version {store_version!r}, "
                f"but this build reads version {STORE_VERSION}"
            )

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
    except CubeStoreError:
        raise
    except (
        OSError,
        EOFError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as exc:
        raise CubeStoreError(f"{path} could not be read as a cube: {exc}") from exc
