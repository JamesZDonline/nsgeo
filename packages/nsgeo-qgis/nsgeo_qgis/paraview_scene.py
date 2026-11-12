"""The files that make an export folder open in ParaView (no Qt or QGIS here).

`scene_record` builds export.json's content and checks it, so a missing field fails
loudly. `write_scene_files` writes it with the launcher scripts and the guide, from
the `.txt` templates beside this module (ParaView code never lives in a `.py` file).
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from nsgeo_qgis.slices_plan import METHOD_LABELS, format_bytes

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


# ---- what the export dialog says (wording lives here, not in widgets) -----------------

#: Free space an export should leave beyond what it writes.
HEADROOM_BYTES = 500_000_000


@dataclass(frozen=True)
class ExportSummary:
    """What an export would write, from `ParaViewExport.summary`; nothing is prepared for it."""

    folder: Path
    replaces: bool
    nx: int
    ny: int
    nd: int
    max_depth_m: float
    fill_method: str
    n_picks: int
    n_lines: int
    export_bytes: int
    cache_bytes: int
    free_bytes: int


def disk_needed_bytes(summary: ExportSummary) -> int:
    """Free space the export asks for: its files, the fill it will keep, and some headroom."""
    return summary.export_bytes + summary.cache_bytes + HEADROOM_BYTES


def disk_is_short(summary: ExportSummary) -> bool:
    return summary.free_bytes < disk_needed_bytes(summary)


def size_text(summary: ExportSummary) -> str:
    size = f"about {format_bytes(summary.export_bytes)}"
    if summary.cache_bytes <= 0:
        return f"{size}; fill already kept"
    return f"{size}, plus {format_bytes(summary.cache_bytes)} fill kept for quick re-exports"


def disk_text(summary: ExportSummary) -> str:
    free = format_bytes(summary.free_bytes)
    if not disk_is_short(summary):
        return f"{free} free"
    return (
        f"only {free} free; this export needs about {format_bytes(disk_needed_bytes(summary))} "
        f"(its files and fill, and {format_bytes(HEADROOM_BYTES)} to spare)"
    )


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def summary_rows(summary: ExportSummary) -> list[tuple[str, str]]:
    """The dialog's read-only rows, label and text, in order."""
    folder = f"{summary.folder}{os.sep}"
    if summary.replaces:
        folder += " (replaces the last export)"
    return [
        ("Folder", folder),
        (
            "Volume",
            f"{summary.nx} \u00d7 {summary.ny} cells \u00d7 {summary.nd} depths, "
            f"0 \u2013 {summary.max_depth_m:.2f} m",
        ),
        ("Fill", METHOD_LABELS.get(summary.fill_method, summary.fill_method)),
        ("Also", f"{_count(summary.n_picks, 'pick')}, {_count(summary.n_lines, 'line')}"),
        ("Size", size_text(summary)),
        ("Disk", disk_text(summary)),
    ]


def cell_hint(panel_cell: float | None) -> str:
    return "Slices panel: not set" if panel_cell is None else f"Slices panel: {panel_cell:g} m"


def dt_hint(native_dt_ns: float) -> str:
    return f"files: {native_dt_ns:.4g} ns"


def exported_message(grid_id: str, folder: Path) -> str:
    return f"Exported {grid_id} for ParaView to {folder}"


def how_to_open_message(grid_id: str, folder: Path, *, windows: bool = False) -> str:
    script = "open.bat" if windows else "open.sh"
    return (
        f"{exported_message(grid_id, folder)}. To open it, run {script} there, "
        "or set ParaView in the export dialog."
    )


def launch_failed_message(
    grid_id: str, folder: Path, paraview: str, *, windows: bool = False
) -> str:
    script = "open.bat" if windows else "open.sh"
    return (
        f"{exported_message(grid_id, folder)}, but ParaView could not be started from "
        f"{paraview}. Run {script} there, or fix the ParaView path in the export dialog."
    )


CANCELLED_MESSAGE = "ParaView export cancelled"
