"""The files that make an export folder open in ParaView (no Qt or QGIS here).

`scene_record` builds export.json's content and checks it, so a missing field fails
loudly. `write_scene_files` writes it with the launcher scripts and the guide, from
the `.txt` templates beside this module (ParaView code never lives in a `.py` file).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

SCENE_FILES = ("open_scene.py", "open.sh", "open.bat", "README.md")
TEMPLATES = Path(__file__).parent / "paraview"

_DEFAULTS = {
    "iso_level": 2.5,
    "cloud_ramp": [[1.8, 0.0], [5.0, 0.6]],
    "strength_range": [0.0, 5.0],
    "paraview_checked": "6.2.1",
}
_REQUIRED = (
    "grid",
    "title",
    "stretch",
    "crs",
    "origin",
    "azimuth_deg",
    "cell_m",
    "dz_ns",
    "depth_step_m",
    "max_depth_m",
    "source",
    "fill",
    "volume",
    "amplitude_range",
    "slices",
    "n_picks",
    "nsgeo_version",
    "written_utc",
)
_SLICE_KEYS = {"depth_m", "x_m", "y_m", "lines_along"}


def scene_record(**fields: object) -> dict:
    """The content of export.json. Every key must be given except the four with defaults.

    Raises TypeError for an unknown or missing key and ValueError for a bad `slices`.
    """
    known = set(_REQUIRED) | set(_DEFAULTS)
    unknown = sorted(set(fields) - known)
    if unknown:
        raise TypeError(f"scene_record got unknown fields: {', '.join(unknown)}")
    missing = [k for k in _REQUIRED if k not in fields]
    if missing:
        raise TypeError(f"scene_record is missing fields: {', '.join(missing)}")
    record = {**_DEFAULTS, **fields}
    slices = record["slices"]
    if not isinstance(slices, dict) or set(slices) != _SLICE_KEYS:
        raise ValueError(f"slices must have exactly the keys {sorted(_SLICE_KEYS)}")
    if slices["lines_along"] not in ("x", "y"):
        raise ValueError("slices['lines_along'] must be 'x' or 'y'")
    return record


def write_scene_files(folder: Path, record: dict, paraview_path: str) -> None:
    """Write export.json and the four scene files into `folder`."""
    folder = Path(folder)
    (folder / "export.json").write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    for name in SCENE_FILES:
        text = (TEMPLATES / f"{name}.txt").read_text(encoding="utf-8")
        text = text.replace("{{PARAVIEW}}", paraview_path or "paraview")
        out = folder / name
        with open(out, "w", encoding="utf-8", newline="\r\n" if name == "open.bat" else "\n") as fh:
            fh.write(text)
        if name == "open.sh":
            os.chmod(out, out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def scene_title(grid_name: str, stretch: float) -> str:
    """The title the scene prints: the grid, the depth stretch, and what the legend means."""
    return f"{grid_name}  ·  depth stretched x{stretch:g}  ·  legend shows true depth"
