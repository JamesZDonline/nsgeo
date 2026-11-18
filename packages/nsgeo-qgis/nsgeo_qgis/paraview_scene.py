"""The files that make an export folder open in ParaView (no Qt or QGIS here).

`scene_record` builds export.json's content and checks it, so a missing field fails
loudly. `write_scene_files` writes it with the launcher scripts and the guide, from
the `.txt` templates beside this module (ParaView code never lives in a `.py` file).
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Sequence
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
    "skipped_lines": [],
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
    "features",
    "nsgeo_version",
    "written_utc",
)
_SLICE_KEYS = {"depth_m", "x_m", "y_m", "lines_along"}
_FEATURE_KEYS = {"index", "name", "stale", "picks", "within_2cm", "on_holes"}


def feature_label(name: str, stale: bool) -> str:
    """What the scene calls a surface: "Surface: <name>", and " (stale)" when its inputs have
    changed since it was built (it still shows that build)."""
    return f"Surface: {name}" + (" (stale)" if stale else "")


def scene_record(**fields: object) -> dict:
    """The content of export.json. Every key must be given except the five with defaults.

    Raises TypeError for an unknown or missing key and ValueError for a bad `slices` or a bad
    `features` (a list of `{index, name, stale, picks, within_2cm, on_holes}`, `index` counting
    from 0 in order).
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
    features = record["features"]
    if not isinstance(features, list) or any(
        not isinstance(f, dict) or set(f) != _FEATURE_KEYS for f in features
    ):
        raise ValueError(f"features must be a list of dicts with exactly {sorted(_FEATURE_KEYS)}")
    if [f["index"] for f in features] != list(range(len(features))):
        raise ValueError("features must be numbered 0, 1, 2, ... in order")
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
    #: Built surfaces of the grid (all go in features.vtp), and how many of them are stale.
    n_surfaces: int
    n_stale_surfaces: int
    export_bytes: int
    cache_bytes: int
    free_bytes: int


def fill_margin_bytes(cache_bytes: int) -> int:
    """Free space to leave beyond the fill cache: its file is sparse and memory-mapped, so a
    disk that fills while it is written kills the program (SIGBUS) rather than raising."""
    return max(HEADROOM_BYTES, cache_bytes // 10)


def export_margin_bytes(export_bytes: int) -> int:
    """Free space to leave beyond the export's files (an ordinary write fails cleanly)."""
    return max(50_000_000, min(export_bytes // 10, 250_000_000))


def fill_refusal(cache_bytes: int, free_bytes: int) -> str:
    """Why the fill cache cannot be written, or "" when it fits with its margin."""
    if cache_bytes <= 0:
        return ""
    need = cache_bytes + fill_margin_bytes(cache_bytes)
    if free_bytes >= need:
        return ""
    return (
        f"not enough free disk space for the fill kept for quick re-exports: it needs "
        f"{format_bytes(need)} and only {format_bytes(free_bytes)} is free"
    )


def export_refusal(export_bytes: int, free_bytes: int) -> str:
    """Why the export's files cannot be written, or "" when they fit with their margin."""
    need = export_bytes + export_margin_bytes(export_bytes)
    if free_bytes >= need:
        return ""
    return (
        f"not enough free disk space for the export: it needs {format_bytes(need)} "
        f"and only {format_bytes(free_bytes)} is free"
    )


def disk_refusal(summary: ExportSummary) -> str:
    """Why this export cannot go ahead on this disk, or "": the fill, then (the fill being
    written first) the export's files in what is left. `ParaViewExport.run` refuses on the
    same two grounds, so a dialog that disables its buttons here never meets them."""
    reason = fill_refusal(summary.cache_bytes, summary.free_bytes)
    if reason:
        return reason
    return export_refusal(summary.export_bytes, summary.free_bytes - max(0, summary.cache_bytes))


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
    refusal = disk_refusal(summary)
    if refusal:
        return f"{refusal}; free some space, or choose a coarser cell or depth step"
    free = format_bytes(summary.free_bytes)
    if not disk_is_short(summary):
        return f"{free} free"
    return (
        f"only {free} free; this export needs about {format_bytes(disk_needed_bytes(summary))} "
        f"(its files and fill, and {format_bytes(HEADROOM_BYTES)} to spare)"
    )


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def surfaces_text(n_surfaces: int, n_stale: int) -> str:
    """ "none", "2", or "3 (1 stale)": the surfaces the export will carry."""
    if n_surfaces <= 0:
        return "none"
    return f"{n_surfaces} ({n_stale} stale)" if n_stale else str(n_surfaces)


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
        ("Surfaces", surfaces_text(summary.n_surfaces, summary.n_stale_surfaces)),
        ("Size", size_text(summary)),
        ("Disk", disk_text(summary)),
    ]


def cell_hint(panel_cell: float | None) -> str:
    return "Slices panel: not set" if panel_cell is None else f"Slices panel: {panel_cell:g} m"


def dt_hint(native_dt_ns: float) -> str:
    return f"files: {native_dt_ns:.4g} ns"


def t1_hint(depth_m: float | None, record_end_ns: float) -> str:
    """Beside "Down to": the depth it reaches at the grid's velocity, and where the record ends."""
    end = f"the record ends at {record_end_ns:.1f} ns"
    return end if depth_m is None else f"{depth_m:.2f} m; {end}"


def shallow_t1_message(t1_ns: float, dz_ns: float) -> str:
    return (
        f"Down to must be at least one depth step ({dz_ns:.3f} ns) past time zero; "
        f"it is {t1_ns:.3f} ns"
    )


_SKIPPED_SHOWN = 3


def skipped_text(keys: Sequence[str]) -> str:
    """ "N lines could not be prepared: a, b, c" (the first few and a count when many), or ""."""
    if not keys:
        return ""
    shown = ", ".join(keys[:_SKIPPED_SHOWN])
    more = len(keys) - _SKIPPED_SHOWN
    if more > 0:
        shown += f", and {more} more"
    noun = "line" if len(keys) == 1 else "lines"
    return f"{len(keys)} {noun} could not be prepared: {shown}"


def exported_message(grid_id: str, folder: Path, skipped: Sequence[str] = ()) -> str:
    text = f"Exported {grid_id} for ParaView to {folder}"
    note = skipped_text(skipped)
    return f"{text}. {note}" if note else text


def how_to_open_message(
    grid_id: str, folder: Path, *, windows: bool = False, skipped: Sequence[str] = ()
) -> str:
    script = "open.bat" if windows else "open.sh"
    return (
        f"{exported_message(grid_id, folder, skipped)}. To open it, run {script} there, "
        "or set ParaView in the export dialog."
    )


def launch_failed_message(
    grid_id: str,
    folder: Path,
    paraview: str,
    *,
    windows: bool = False,
    skipped: Sequence[str] = (),
) -> str:
    script = "open.bat" if windows else "open.sh"
    return (
        f"{exported_message(grid_id, folder, skipped)}. ParaView could not be started from "
        f"{paraview}. Run {script} there, or fix the ParaView path in the export dialog."
    )


CANCELLED_MESSAGE = "ParaView export cancelled"


def in_use_message(folder: Path) -> str:
    return f"{folder} is in use, probably by ParaView; close it and export again"
