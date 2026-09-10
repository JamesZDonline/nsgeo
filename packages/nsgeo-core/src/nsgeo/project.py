"""The survey definition file: survey.nsgeo.json.

This is the source of truth. It is human-readable, diffable, git-friendly, and
loadable with no QGIS present. Front ends derive display layers from it; those
layers are regenerable and are explicitly not the source of truth.

DZT paths are stored relative to the JSON file with POSIX separators, so a
project directory can be moved or shared across platforms intact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site
from nsgeo.processing.stack import StepStack

SCHEMA_VERSION = 1


class ProjectError(Exception):
    """Raised when a survey definition file is malformed or unreadable."""


def _grid_to_dict(grid: Grid) -> dict[str, Any]:
    return {
        "id": grid.id,
        "origin": list(grid.origin),
        "azimuth": grid.azimuth,
        "size_x": grid.size_x,
        "size_y": grid.size_y,
        "crs": grid.crs,
        "default_spacing": grid.default_spacing,
    }


def _grid_from_dict(doc: dict[str, Any]) -> Grid:
    return Grid(
        id=doc["id"],
        origin=(float(doc["origin"][0]), float(doc["origin"][1])),
        azimuth=float(doc["azimuth"]),
        size_x=float(doc["size_x"]),
        size_y=float(doc["size_y"]),
        crs=doc["crs"],
        default_spacing=float(doc["default_spacing"]),
    )


def _placement_to_dict(placement: Any) -> dict[str, Any]:
    if isinstance(placement, GridPlacement):
        return {
            "type": "grid",
            "grid_id": placement.grid_id,
            "axis": placement.axis,
            "offset": placement.offset,
            "start_along": placement.start_along,
            "direction": placement.direction,
            "label": placement.label,
        }
    raise ProjectError(f"cannot serialise placement of type {type(placement).__name__}")


def _placement_from_dict(doc: dict[str, Any]) -> GridPlacement:
    kind = doc.get("type")
    if kind != "grid":
        raise ProjectError(f"unknown placement type {kind!r}")
    return GridPlacement(
        grid_id=doc["grid_id"],
        axis=doc["axis"],
        offset=float(doc["offset"]),
        start_along=float(doc.get("start_along", 0.0)),
        direction=int(doc.get("direction", 1)),
        label=doc.get("label"),
    )


def save_site(site: Site, path: str | Path) -> None:
    path = Path(path)
    root = path.parent.resolve()
    lines_data = []
    for line in site.lines:
        try:
            rel = Path(line.path).resolve().relative_to(root).as_posix()
        except ValueError:
            raise ProjectError(
                f"{line.path} is not under the project directory {root}; survey "
                f"files must live inside the folder that holds survey.nsgeo.json "
                f"so the project stays portable"
            ) from None
        entry: dict[str, Any] = {
            "path": rel,
            "placement": _placement_to_dict(line.placement),
        }
        stack = site.stacks.get(rel)
        if stack is not None:
            entry["stack"] = stack.to_dicts()
        lines_data.append(entry)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "grids": [_grid_to_dict(g) for g in site.grids],
        "lines": lines_data,
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def load_site(path: str | Path) -> Site:
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{path} is not valid JSON: {exc}") from exc

    version = doc.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ProjectError(
            f"{path} declares schema version {version}, but this build reads "
            f"version {SCHEMA_VERSION}"
        )

    root = path.parent.resolve()
    grids = [_grid_from_dict(g) for g in doc.get("grids", [])]
    lines = []
    stacks: dict[str, StepStack] = {}
    for entry in doc.get("lines", []):
        dzt = root / entry["path"]
        if not dzt.exists():
            raise ProjectError(f"referenced file does not exist: {dzt}")
        lines.append(Line.open(dzt, _placement_from_dict(entry["placement"])))
        if "stack" in entry:
            stacks[entry["path"]] = StepStack.from_dicts(entry["stack"])

    site = Site(grids=grids, lines=lines)
    site.stacks = stacks
    site.validate()
    return site
