"""The survey definition file: survey.nsgeo.json.

This is the source of truth. It is human-readable, diffable, git-friendly, and
loadable with no QGIS present. Front ends derive display layers from it; those
layers are regenerable and are explicitly not the source of truth.

DZT paths are stored relative to the JSON file with POSIX separators, so a
project directory can be moved or shared across platforms intact — except
files outside that directory, which are refused unless the caller opts into
absolute paths (see `save_site`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site
from nsgeo.processing.stack import StepStack
from nsgeo.velocity import VelocityModel

SCHEMA_VERSION = 1


class ProjectError(Exception):
    """Raised when a survey definition file is malformed or unreadable."""


def _grid_to_dict(grid: Grid) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": grid.id,
        "origin": list(grid.origin),
        "azimuth": grid.azimuth,
        "size_x": grid.size_x,
        "size_y": grid.size_y,
        "crs": grid.crs,
        "default_spacing": grid.default_spacing,
    }
    if grid.velocity is not None:
        doc["velocity"] = grid.velocity.to_dict()
    return doc


def _grid_from_dict(doc: dict[str, Any]) -> Grid:
    velocity = None
    if "velocity" in doc:
        try:
            velocity = VelocityModel.from_dict(doc["velocity"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(
                f"invalid velocity for grid {doc.get('id', '<unknown>')!r}: {exc}"
            ) from exc
    return Grid(
        id=doc["id"],
        origin=(float(doc["origin"][0]), float(doc["origin"][1])),
        azimuth=float(doc["azimuth"]),
        size_x=float(doc["size_x"]),
        size_y=float(doc["size_y"]),
        crs=doc["crs"],
        default_spacing=float(doc["default_spacing"]),
        velocity=velocity,
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


def _line_key(line_path: str | Path, root: Path, *, allow_absolute: bool = False) -> str:
    """The string a line is stored and keyed by.

    Relative POSIX when the file is under `root`, which keeps the project
    portable. For a file outside `root`: its absolute POSIX path when
    `allow_absolute` is set, otherwise a ProjectError.
    """
    resolved = Path(line_path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        if allow_absolute:
            return resolved.as_posix()
        raise ProjectError(
            f"{resolved} is not under the project directory {root}; survey "
            f"files must live inside the folder that holds survey.nsgeo.json "
            f"so the project stays portable, or pass allow_absolute=True to "
            f"record an absolute path tied to this machine"
        ) from None


def save_site(site: Site, path: str | Path, *, allow_absolute: bool = False) -> None:
    """Write `site` to `path` as the survey.nsgeo.json source of truth.

    Paths are stored relative to the JSON file with POSIX separators so the
    project directory can be moved intact. A file outside that directory is
    refused unless `allow_absolute=True`, in which case its absolute POSIX path
    is stored — tying the survey file to this machine's mount points and drive
    letters. In-tree files stay relative even when the option is on.
    """
    path = Path(path)
    root = path.parent.resolve()
    lines_data = []
    keys_written: list[str] = []
    for line in site.lines:
        key = _line_key(line.path, root, allow_absolute=allow_absolute)
        keys_written.append(key)
        entry: dict[str, Any] = {
            "path": key,
            "placement": _placement_to_dict(line.placement),
        }
        stack = site.stacks.get(key)
        if stack is not None:
            entry["stack"] = stack.to_dicts()
        if line.velocity is not None:
            entry["velocity"] = line.velocity.to_dict()
        lines_data.append(entry)

    orphans = sorted(set(site.stacks) - set(keys_written))
    if orphans:
        raise ProjectError(
            f"stacks are keyed by paths that match no line: {orphans}; "
            f"expected one of {sorted(keys_written)}"
        )

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
        stored = Path(entry["path"])
        dzt = stored if stored.is_absolute() else root / stored
        if not dzt.exists():
            raise ProjectError(
                f"referenced file does not exist: {dzt} (stored as {entry['path']!r})"
            )
        velocity = None
        if "velocity" in entry:
            try:
                velocity = VelocityModel.from_dict(entry["velocity"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectError(f"invalid velocity for line {entry['path']!r}: {exc}") from exc
        lines.append(Line.open(dzt, _placement_from_dict(entry["placement"]), velocity=velocity))
        if "stack" in entry:
            try:
                stacks[entry["path"]] = StepStack.from_dicts(entry["stack"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectError(
                    f"invalid processing stack for line {entry['path']!r}: {exc}"
                ) from exc

    site = Site(grids=grids, lines=lines)
    site.stacks = stacks
    site.validate()
    return site
