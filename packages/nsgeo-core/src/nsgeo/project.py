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

import dataclasses
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from nsgeo.geometry.grid import INSTRUMENTS, Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.geometry.track import TrackFix, TrackPlacement
from nsgeo.mag import MagFile, MagSetup
from nsgeo.model.cut import Cut
from nsgeo.model.survey import Line, Site
from nsgeo.processing.base import build_step, get_step, param_problem, step_title
from nsgeo.processing.stack import StepStack
from nsgeo.slices.interpolate import METHODS
from nsgeo.velocity import VelocityModel
from nsgeo.velocity_fit import StoredFit
from nsgeo.velocity_source import SourceFit, VelocitySource

__all__ = [
    "ProjectError",
    "line_key",
    "load_site",
    "save_site",
]

SCHEMA_VERSION = 1
#: A site with cuts saves as 2, so a build that predates cuts refuses the file
#: instead of opening it and dropping the cuts on its next save. A site
#: without cuts still saves as `SCHEMA_VERSION`, and stays readable by those
#: builds (cut spec §3, plan call 3).
CUTS_SCHEMA_VERSION = SCHEMA_VERSION + 1
#: A site with any velocity source record saves as 3, for the same reason: an
#: older build would drop the record on its next save. A site without one
#: still saves as 1 or 2 (grid velocity spec §9).
VELOCITY_SOURCE_SCHEMA_VERSION = CUTS_SCHEMA_VERSION + 1
#: A site with any GPS line saves as 4 and only then gains a top-level `"crs"`
#: (GPS lines spec §15). A site without GPS lines still saves as 1 to 3.
TRACK_SCHEMA_VERSION = VELOCITY_SOURCE_SCHEMA_VERSION + 1
#: A site with a magnetometer grid or file saves as 5, for the same reason
#: (M19a spec C17; numbered 3 on its branch until it met main). A site
#: without mag still saves as 1 to 4.
MAG_SCHEMA_VERSION = TRACK_SCHEMA_VERSION + 1
READABLE_SCHEMA_VERSIONS = (
    SCHEMA_VERSION,
    CUTS_SCHEMA_VERSION,
    VELOCITY_SOURCE_SCHEMA_VERSION,
    TRACK_SCHEMA_VERSION,
    MAG_SCHEMA_VERSION,
)
_FIT_ID = re.compile(r"fit-(\d+)")


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
    # Written only for a mag grid, so a GPR site saves as it always did.
    if grid.instrument != "gpr":
        doc["instrument"] = grid.instrument
    if grid.velocity_source is not None:
        doc["velocity_source"] = grid.velocity_source.to_dict()
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
    instrument = doc.get("instrument", "gpr")
    if instrument not in INSTRUMENTS:
        raise ProjectError(
            f"grid {doc.get('id', '<unknown>')!r} has instrument {instrument!r}; "
            f"expected one of {INSTRUMENTS}"
        )
    source = None
    if "velocity_source" in doc:
        try:
            source = VelocitySource.from_dict(doc["velocity_source"])
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ProjectError(
                f"invalid velocity source for grid {doc.get('id', '<unknown>')!r}: {exc}"
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
        instrument=instrument,
        velocity_source=source,
    )


def _cut_to_dict(cut: Cut) -> dict[str, Any]:
    return {
        "id": cut.id,
        "name": cut.name,
        "grid_id": cut.grid_id,
        "vertices": [[x, y] for x, y in cut.vertices],
    }


def _cut_from_dict(doc: Any) -> Cut:
    try:
        vertices = doc["vertices"]
        if not isinstance(vertices, list):
            raise TypeError("vertices must be a list")
        pairs = []
        for vertex in vertices:
            if not isinstance(vertex, list) or len(vertex) != 2:
                raise TypeError(f"a vertex must be an [x, y] pair, got {vertex!r}")
            x, y = _finite(vertex[0]), _finite(vertex[1])
            if x is None or y is None:
                raise ValueError(f"a vertex must be two finite numbers, got {vertex!r}")
            pairs.append((x, y))
        for key in ("id", "name", "grid_id"):
            if not isinstance(doc[key], str):
                raise TypeError(f"{key} must be text")
        return Cut(doc["id"], doc["name"], doc["grid_id"], tuple(pairs))
    except (KeyError, TypeError, ValueError) as exc:
        name = doc.get("name") if isinstance(doc, dict) else None
        raise ProjectError(f"invalid cut {name!r}: {exc!r}") from exc


def _placement_to_dict(placement: Any) -> dict[str, Any]:
    if isinstance(placement, GridPlacement):
        doc: dict[str, Any] = {
            "type": "grid",
            "grid_id": placement.grid_id,
            "axis": placement.axis,
            "offset": placement.offset,
            "start_along": placement.start_along,
            "direction": placement.direction,
            "label": placement.label,
        }
        # Written only when corrected, so an uncorrected site saves as it
        # always did (placement corrections plan, call 13).
        if placement.scale != 1.0:
            doc["scale"] = placement.scale
        if placement.travel_shift != 0.0:
            doc["travel_shift"] = placement.travel_shift
        return doc
    if isinstance(placement, TrackPlacement):
        track: dict[str, Any] = {"type": "track", "crs": placement.crs}
        # As GridPlacement's corrections: written only when set.
        if placement.grid_id is not None:
            track["grid_id"] = placement.grid_id
        track["label"] = placement.label
        if placement.travel_shift != 0.0:
            track["travel_shift"] = placement.travel_shift
        track["fixes"] = [_fix_to_row(f) for f in placement.fixes]
        return track
    raise ProjectError(f"cannot serialise placement of type {type(placement).__name__}")


def _null_nan(value: float) -> float | None:
    """NaN is not JSON: a fix with no position writes `null`."""
    return None if math.isnan(value) else value


def _fix_to_row(fix: TrackFix) -> list[Any]:
    return [
        fix.trace,
        _null_nan(fix.x),
        _null_nan(fix.y),
        _null_nan(fix.lat),
        _null_nan(fix.lon),
        fix.alt_m,
        fix.geoid_m,
        fix.quality,
    ]


def _nan_null(value: Any) -> float:
    return math.nan if value is None else float(value)


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _fix_from_row(row: Any) -> TrackFix:
    if not isinstance(row, list) or len(row) != 8:
        raise TypeError(f"a fix must be a list of 8 values, got {row!r}")
    return TrackFix(
        trace=int(row[0]),
        x=_nan_null(row[1]),
        y=_nan_null(row[2]),
        lat=_nan_null(row[3]),
        lon=_nan_null(row[4]),
        alt_m=_opt_float(row[5]),
        geoid_m=_opt_float(row[6]),
        quality=int(row[7]),
    )


def _placement_from_dict(doc: dict[str, Any]) -> GridPlacement | TrackPlacement:
    kind = doc.get("type")
    if kind == "track":
        return TrackPlacement(
            fixes=tuple(_fix_from_row(r) for r in doc["fixes"]),
            crs=doc["crs"],
            grid_id=doc.get("grid_id"),
            label=doc.get("label"),
            travel_shift=float(doc.get("travel_shift", 0.0)),
        )
    if kind != "grid":
        raise ProjectError(f"unknown placement type {kind!r}")
    return GridPlacement(
        grid_id=doc["grid_id"],
        axis=doc["axis"],
        offset=float(doc["offset"]),
        start_along=float(doc.get("start_along", 0.0)),
        direction=int(doc.get("direction", 1)),
        label=doc.get("label"),
        scale=float(doc.get("scale", 1.0)),
        travel_shift=float(doc.get("travel_shift", 0.0)),
    )


def _mag_file_to_dict(mag: MagFile, key: str) -> dict[str, Any]:
    corrections: dict[str, dict[str, float]] = {}
    for row, (scale, shift) in enumerate(zip(mag.scales, mag.shifts)):
        entry: dict[str, float] = {}
        if scale != 1.0:
            entry["scale"] = scale
        if shift != 0.0:
            entry["travel_shift"] = shift
        if entry:
            corrections[str(row)] = entry
    return {
        "path": key,
        "grid_id": mag.grid_id,
        "setup": mag.setup.to_dict(),
        "corrections": corrections,
    }


def _mag_file_from_dict(entry: Any, root: Path) -> MagFile:
    try:
        stored = Path(entry["path"])
        grid_id = entry["grid_id"]
        if not isinstance(grid_id, str):
            raise TypeError("grid_id must be text")
    except (KeyError, TypeError) as exc:
        raise ProjectError(f"invalid mag file entry {entry!r}: {exc!r}") from exc
    path = stored if stored.is_absolute() else root / stored
    if not path.exists():
        raise ProjectError(f"referenced file does not exist: {path} (stored as {entry['path']!r})")
    try:
        setup = MagSetup.from_dict(entry.get("setup", {}))
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as exc:
        raise ProjectError(f"invalid setup for mag file {entry['path']!r}: {exc}") from exc
    try:
        mag = MagFile.open(path, grid_id, setup)
    except (OSError, ValueError) as exc:
        raise ProjectError(f"cannot read mag file {entry['path']!r}: {exc}") from exc
    corrections = entry.get("corrections", {})
    if not isinstance(corrections, dict):
        raise ProjectError(f"invalid correction for mag file {entry['path']!r}: not an object")
    scales = list(mag.scales)
    shifts = list(mag.shifts)
    for key, fix in corrections.items():
        try:
            row = int(key)
        except (TypeError, ValueError):
            raise ProjectError(
                f"invalid correction for mag file {entry['path']!r}: {key!r} is not a traverse"
            ) from None
        if not 0 <= row < mag.n_rows:
            raise ProjectError(
                f"correction for traverse {row} of mag file {entry['path']!r}, "
                f"which has {mag.n_rows} traverses (0 to {mag.n_rows - 1})"
            )
        if not isinstance(fix, dict):
            raise ProjectError(
                f"invalid correction for traverse {row} of mag file {entry['path']!r}: "
                f"expected an object"
            )
        if "scale" in fix:
            scale = _finite(fix["scale"])
            if scale is None or scale <= 0:
                raise ProjectError(
                    f"invalid correction for traverse {row} of mag file {entry['path']!r}: "
                    f"scale must be a finite number above 0"
                )
            scales[row] = scale
        if "travel_shift" in fix:
            shift = _finite(fix["travel_shift"])
            if shift is None:
                raise ProjectError(
                    f"invalid correction for traverse {row} of mag file {entry['path']!r}: "
                    f"travel_shift must be a finite number"
                )
            shifts[row] = shift
    return dataclasses.replace(mag, scales=tuple(scales), shifts=tuple(shifts))


def line_key(line_path: str | Path, root: Path, *, allow_absolute: bool = False) -> str:
    """The one string a line is stored, keyed and looked up by.

    Save, load and the front end's session all derive their key from this
    function and from nothing else. That is the whole point of it being
    public: `save_site` keying by a canonicalised path while `load_site`
    keyed by the raw stored string agreed only when the stored string was
    already in canonical form, and where they disagreed the saved
    processing stack became invisible in the UI and the project could never
    be saved again.

    Relative POSIX when the file is under `root`, which keeps the project
    portable. For a file outside `root`: its absolute POSIX path when
    `allow_absolute` is set, otherwise a ProjectError.

    "Under `root`" is decided lexically first -- `os.path.normpath`, which
    collapses `.` and `..` without following symlinks -- and only then by
    `Path.resolve()`. That order is deliberate. A `data/` subdirectory
    symlinked onto an external disk is an ordinary arrangement when GPR
    data runs to gigabytes, and resolving first would call such a line
    out-of-tree: the next plain save is refused outright, and the
    `allow_absolute` fallback rewrites a deliberately portable
    `data/L0.DZT` into a path tied to this machine's mount points, which
    then fails to open anywhere else. Keeping it lexical leaves the stored
    form exactly as the user wrote it, so a save is also idempotent -- the
    survey file stays diffable rather than churning its paths.

    The `resolve()` fallback still covers the reverse case: a path that
    reaches inside `root` by a route that is not lexically under it -- a
    symlinked project directory, or macOS's `/tmp` -> `/private/tmp` --
    which would otherwise be misread as out of tree.

    `root` is expected to be absolute (every caller passes
    `json_path.parent.resolve()`); a relative `line_path` is taken against
    the current directory, as `resolve()` has always done.
    """
    path = Path(line_path)
    lexical = Path(os.path.normpath(path if path.is_absolute() else Path.cwd() / path))
    try:
        return lexical.relative_to(root).as_posix()
    except ValueError:
        pass
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path(root).resolve()).as_posix()
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
        key = line_key(line.path, root, allow_absolute=allow_absolute)
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
        if line.velocity_fits:
            entry["velocity_fits"] = {fid: fit.to_dict() for fid, fit in line.velocity_fits.items()}
        if line.velocity_source is not None:
            entry["velocity_source"] = line.velocity_source.to_dict()
        if line.fit_serial > 0:
            entry["fit_serial"] = line.fit_serial
        lines_data.append(entry)

    orphans = sorted(set(site.stacks) - set(keys_written))
    if orphans:
        raise ProjectError(
            f"stacks are keyed by paths that match no line: {orphans}; "
            f"expected one of {sorted(keys_written)}"
        )

    has_gps = site.has_gps_lines()
    crs = site.effective_crs() if has_gps else None
    if has_gps and crs is None:
        raise ProjectError("GPS lines need the site's CRS, but the site has none")
    if has_gps:
        for line in site.lines:
            placed = getattr(line.placement, "crs", None)
            if isinstance(line.placement, TrackPlacement) and placed != crs:
                raise ProjectError(
                    f"line {line.path.name} is placed in {placed}, but the site is in {crs}"
                )
    has_record = any(g.velocity_source is not None for g in site.grids) or any(
        ln.velocity_source is not None for ln in site.lines
    )
    has_mag = bool(site.mag_files) or any(g.instrument == "mag" for g in site.grids)
    # The highest feature the site holds names the version, so a build that
    # cannot read that feature refuses the file instead of dropping it.
    if has_mag:
        version = MAG_SCHEMA_VERSION
    elif has_gps:
        version = TRACK_SCHEMA_VERSION
    elif has_record:
        version = VELOCITY_SOURCE_SCHEMA_VERSION
    else:
        version = CUTS_SCHEMA_VERSION if site.cuts else SCHEMA_VERSION
    doc = {
        "schema_version": version,
        "grids": [_grid_to_dict(g) for g in site.grids],
        "lines": lines_data,
    }
    if crs is not None:
        doc["crs"] = crs
    if site.cuts:
        doc["cuts"] = [_cut_to_dict(c) for c in site.cuts]
    if site.mag_files:
        doc["mag_files"] = [
            _mag_file_to_dict(m, line_key(m.path, root, allow_absolute=allow_absolute))
            for m in site.mag_files
        ]
    if site.mag_setup is not None:
        doc["mag_setup"] = site.mag_setup.to_dict()
    if site.mag_view:
        doc["mag_view"] = site.mag_view
    if site.presets:
        doc["presets"] = site.presets
    if site.cubes:
        doc["cubes"] = site.cubes
    if site.slice_sources:
        doc["slice_sources"] = site.slice_sources
    if site.site_view:
        doc["site_view"] = site.site_view
    if site.slice_colours:
        doc["slice_colours"] = site.slice_colours
    if site.import_presets:
        doc["import_presets"] = site.import_presets
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


_RESOLUTION_KEYS = (
    "cell",
    "dz_ns",
    "t0_ns",
    "t1_ns",
    "max_distance_spacings",
    "smooth_x_m",
    "smooth_y_m",
)


def _finite(value: object) -> float | None:
    """`value` as a finite float, or None: for a non-number, a bool, NaN, an
    infinity, or an integer too large for a float. JSON sets no limit on an
    integer's size and `float()` overflows on one, so without the last a
    hand-edited value blocked the survey from opening instead of reading as
    unset (Review Focus 2, #71). Shared by the loader's tolerant cleaners."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


_FINISH_KEYS = ("method", "max_distance_spacings", "smooth_x_m", "smooth_y_m")


def _clean_resolution(value: object) -> dict[str, float | str]:
    """A remembered resolution (#71), each field kept only if usable.

    Fields are vetted one by one, so a single damaged value reads as unset
    and the rest still restore: the dock then seeds that field as it would
    for a grid nobody had tuned. A z range is judged as a pair, because an
    empty or reversed one is unusable as a whole -- keeping either end alone
    would pair it with a seed it was never chosen against.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, float | str] = {}
    numbers: dict[str, float] = {}
    for key in _RESOLUTION_KEYS:
        number = _finite(value.get(key))
        if number is not None:
            numbers[key] = number
    for key in ("cell", "dz_ns"):
        if key in numbers and numbers[key] <= 0:
            del numbers[key]
    for key in ("max_distance_spacings", "smooth_x_m", "smooth_y_m"):
        if numbers.get(key, 0.0) < 0:
            del numbers[key]
    if "t0_ns" in numbers and "t1_ns" in numbers and numbers["t1_ns"] <= numbers["t0_ns"]:
        del numbers["t0_ns"], numbers["t1_ns"]
    out.update(numbers)
    # The interpolation method is a string, kept only if this build knows it
    # (interpolation spec §8): an unknown one reads as unset.
    method = value.get("method")
    if isinstance(method, str) and method in METHODS:
        out["method"] = method
    return out


_VOLUME_POSITIVE = ("cell", "dz_ns", "stretch", "period_ns", "trend_m", "t1_ns")


def _clean_volume(value: object) -> dict[str, float | str]:
    """A grid's remembered 3-D settings (M16), each field kept only if usable.

    Only the eight fields the export reads survive; a damaged one reads as unset
    and the rest still restore, as `_clean_resolution` does.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, float | str] = {}
    for key in (*_VOLUME_POSITIVE, "blur_m"):
        number = _finite(value.get(key))
        if number is None or number < 0 or (number == 0 and key in _VOLUME_POSITIVE):
            continue
        out[key] = number
    if isinstance(value.get("transform"), str):
        out["transform"] = value["transform"]
    return out


def _clean_slice_source(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(entry.get("preset"), str):
        out["preset"] = entry["preset"]
    if "lines" in entry:
        lines = entry["lines"]
        if lines is None:
            out["lines"] = None
        elif isinstance(lines, list) and all(isinstance(k, str) for k in lines):
            out["lines"] = list(lines)
    gain = _finite(entry.get("gain"))
    if gain is not None and gain > 0:
        out["gain"] = gain
    resolution = _clean_resolution(entry.get("resolution"))
    if resolution:
        out["resolution"] = resolution
    volume = _clean_volume(entry.get("volume"))
    if volume:
        out["volume"] = volume
    view_stretch = _finite(entry.get("view_stretch"))
    if view_stretch is not None and view_stretch > 0:
        out["view_stretch"] = view_stretch
    return out


def _clean_site_view(view: dict[str, Any], known: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    grids = view.get("grids")
    if isinstance(grids, list):
        out["grids"] = [g for g in grids if isinstance(g, str) and g in known]
    for key in ("transform", "normalisation"):
        if isinstance(view.get(key), str):
            out[key] = view[key]
    resolution = _clean_resolution(view.get("resolution"))
    if resolution:
        out["resolution"] = resolution
    return out


def _clean_import_presets(value: object, known_grid_ids: set[str]) -> dict[str, Any]:
    """The remembered import presets (#129), each field kept only if usable.

    A non-object reads as empty; a grid the site does not have, or a value
    that is neither a string nor null, is dropped.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    grids = value.get("grids")
    if isinstance(grids, dict):
        kept = {
            gid: name
            for gid, name in grids.items()
            if gid in known_grid_ids and (name is None or isinstance(name, str))
        }
        if kept:
            out["grids"] = kept
    if "site" in value and (value["site"] is None or isinstance(value["site"], str)):
        out["site"] = value["site"]
    return out


_COLOUR_SCOPES = ("grid", "site", "mag")


def _clean_mag_view(value: object, known_mag_grids: set[str]) -> dict[str, Any]:
    """The Mag panel's remembered choices, each key kept only if usable.

    Like every display choice, a damaged value reads as unset and never
    blocks a survey from opening. The finish fields are vetted by the
    rules of `_clean_resolution`.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    if value.get("scope") in ("grid", "site"):
        out["scope"] = value["scope"]
    grid = value.get("grid")
    if isinstance(grid, str) and grid in known_mag_grids:
        out["grid"] = grid
    cell = _finite(value.get("cell"))
    if cell is not None and cell > 0:
        out["cell"] = cell
    finish = _clean_resolution(value.get("finish"))
    finish = {k: v for k, v in finish.items() if k in _FINISH_KEYS}
    if finish:
        out["finish"] = finish
    if isinstance(value.get("palette"), str):
        out["palette"] = value["palette"]
    return out


def _clean_slice_colours(value: object) -> dict[str, dict[str, Any]]:
    """The remembered slice colours (#180), each field kept only if usable.

    A display choice never blocks a survey from opening: a value of the wrong
    type, or a scope this build does not know, reads as unset.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for scope in _COLOUR_SCOPES:
        entry = value.get(scope)
        if not isinstance(entry, dict):
            continue
        kept: dict[str, Any] = {}
        if isinstance(entry.get("own"), bool):
            kept["own"] = entry["own"]
        if isinstance(entry.get("style"), str):
            kept["style"] = entry["style"]
        if kept:
            out[scope] = kept
    return out


def _held(specs: dict[str, Any], params: dict[str, Any], skip: set[str], lead: str) -> str:
    """One sentence listing the saved settings not already named, by label."""
    items = [f"{specs[k].label} {v!r}" for k, v in params.items() if k not in skip]
    if not items:
        return ""
    listed = items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
    return f"{lead} {listed}."


#: Steps that stay on when a setting is reset: turning Time zero off would
#: move every time after it.
_STAYS_ON = ("time_zero",)


def _repair_steps(
    entries: list[dict[str, Any]], where: str, notes: list[str]
) -> list[dict[str, Any]]:
    """Saved steps whose settings the rules now refuse, made loadable.

    A refused setting with a default is reset to it and the step turned off
    (Time zero stays on). A refused setting with no default, a missing
    required one, or a step that cannot be built removes the step. Each
    change adds one plain-language note. Structural faults (an entry that is
    not an object, no step name, unknown step or setting) still raise.
    Returns new dicts; `entries` is untouched.
    """
    if not isinstance(entries, list):
        raise TypeError(f"a stack must be a list of steps, got {type(entries).__name__}")
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError(f"a step must be an object, got {type(entry).__name__}")
        name = entry["step"]
        cls = get_step(name)
        params = entry.get("params", {})
        if not isinstance(params, dict):
            raise TypeError(f"step {name!r}: params must be an object")
        specs = {s.name: s for s in cls.schema()}
        unknown = sorted(set(params) - set(specs))
        if unknown:
            raise ValueError(
                f"step {name!r} has no parameter(s) {unknown}; it takes {sorted(specs)}"
            )
        title = step_title(name)
        removed = f"{where}: {title} is removed. "
        again = "Add it again with the settings you want."
        fixed = dict(params)
        # Everything wrong with the step is collected first, so one note
        # names it all; whether the step goes is decided after.
        missing = [s for s in specs.values() if s.required and s.name not in params]
        refused: list[tuple[Any, Any, str]] = []
        for spec in specs.values():
            if spec.name in params:
                reason = param_problem(spec, params[spec.name])
                if reason is not None:
                    refused.append((spec, params[spec.name], reason))
                    if not spec.required:
                        fixed[spec.name] = spec.default
        if missing or any(spec.required for spec, _, _ in refused):
            parts = []
            for spec, value, reason in refused:
                tail = f", and {spec.label} has no default" if spec.required else ""
                parts.append(f"Its {spec.label} was {value!r}, which {reason}{tail}.")
            for spec in missing:
                parts.append(f"It has no {spec.label}, which it needs.")
            named = {spec.name for spec, _, _ in refused}
            held = _held(specs, params, named, "It also held")
            notes.append(f"{removed}{' '.join(parts)} {held + ' ' if held else ''}{again}")
            continue
        repaired = {**entry, "params": fixed}
        note = None
        sentences: list[str] = []
        if refused:
            sentences = [
                f"Its {spec.label} was {value!r}, which {reason}; it is now {spec.default!r}."
                for spec, value, reason in refused
            ]
            was_on = bool(entry.get("enabled", True))
            if not was_on:
                note = (
                    f"{where}: {title} (already off) had "
                    f"{'a setting' if len(refused) == 1 else 'settings'} reset. "
                    f"{' '.join(sentences)} The step stays off, as it was saved."
                )
            elif name in _STAYS_ON:
                sentences = [t.replace("Its ", f"{title}'s ", 1) for t in sentences]
                note = (
                    f"{where}: {' '.join(sentences)} The step stays on, because "
                    f"turning {title} off would move every time after it."
                )
            else:
                repaired["enabled"] = False
                note = (
                    f"{where}: {title} is turned off. {' '.join(sentences)} "
                    "Check the step and turn it back on."
                )
        try:
            build_step(name, **fixed)
        except (TypeError, ValueError) as exc:
            held = _held(specs, params, set(), "It held")
            built = " ".join([*sentences, f"It could not be built: {exc}.", held])
            notes.append(f"{removed}{built.strip()} {again}")
            continue
        if note is not None:
            notes.append(note)
        out.append(repaired)
    return out


def load_site(path: str | Path) -> Site:
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{path} is not valid JSON: {exc}") from exc

    version = doc.get("schema_version")
    if version not in READABLE_SCHEMA_VERSIONS:
        raise ProjectError(
            f"{path} declares schema version {version}, but this build reads "
            f"versions {list(READABLE_SCHEMA_VERSIONS)}"
        )

    root = path.parent.resolve()
    grids = [_grid_from_dict(g) for g in doc.get("grids", [])]
    lines = []
    stacks: dict[str, StepStack] = {}
    load_notes: list[str] = []
    for entry in doc.get("lines", []):
        stored = Path(entry["path"])
        dzt = stored if stored.is_absolute() else root / stored
        if not dzt.exists():
            raise ProjectError(
                f"referenced file does not exist: {dzt} (stored as {entry['path']!r})"
            )
        # Keyed through `line_key`, not by the raw stored string: the two
        # agree only when the file already happens to hold the canonical
        # spelling. A hand-edited "./L0.DZT" -- or a `data/` symlinked onto
        # an external disk -- otherwise loads a stack under a key no save
        # and no session lookup will ever compute, which shows the line as
        # unprocessed and then refuses every later save as an orphan.
        # `allow_absolute` is not a policy decision here: a project saved
        # with the out-of-tree opt-in must still load. Whether an absolute
        # path may be *written* stays `save_site`'s call.
        key = line_key(dzt, root, allow_absolute=True)
        velocity = None
        if "velocity" in entry:
            try:
                velocity = VelocityModel.from_dict(entry["velocity"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectError(f"invalid velocity for line {entry['path']!r}: {exc}") from exc
        fits: dict[str, StoredFit] = {}
        try:
            for fid, fit_doc in entry.get("velocity_fits", {}).items():
                fits[fid] = StoredFit.from_dict(fit_doc)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"invalid velocity fit for line {entry['path']!r}: {exc}") from exc
        try:
            placement = _placement_from_dict(entry["placement"])
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"invalid placement for line {entry['path']!r}: {exc}") from exc
        source = None
        if "velocity_source" in entry:
            try:
                source = VelocitySource.from_dict(entry["velocity_source"])
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise ProjectError(
                    f"invalid velocity source for line {entry['path']!r}: {exc}"
                ) from exc
        else:
            # An older file's pick becomes a one-member record (spec §7.1).
            # A pick naming a fit that is gone is dropped, as before.
            from_fit = entry.get("velocity_from_fit")
            if isinstance(from_fit, str) and from_fit in fits:
                label = placement.label or Path(entry["path"]).stem
                member = SourceFit.of(key, from_fit, label, fits[from_fit])
                source = VelocitySource.from_fits([member], None)
        serial = entry.get("fit_serial", 0)
        if not isinstance(serial, int) or isinstance(serial, bool) or serial < 0:
            serial = 0
        for fid in fits:
            found = _FIT_ID.fullmatch(fid)
            if found:
                serial = max(serial, int(found.group(1)))
        line = Line.open(dzt, placement, velocity=velocity)
        lines.append(
            dataclasses.replace(line, velocity_fits=fits, velocity_source=source, fit_serial=serial)
        )
        if "stack" in entry:
            where = f"Line {Path(entry['path']).name}"
            if placement.grid_id:
                where += f" (grid {placement.grid_id})"
            try:
                stacks[key] = StepStack.from_dicts(_repair_steps(entry["stack"], where, load_notes))
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectError(
                    f"invalid processing stack for line {entry['path']!r}: {exc}"
                ) from exc

    file_crs = doc.get("crs")
    if file_crs is not None and not isinstance(file_crs, str):
        raise ProjectError(f"{path}: 'crs' must be text, got {type(file_crs).__name__}")
    site = Site(grids=grids, lines=lines)
    site.crs = file_crs
    site.stacks = stacks
    site.load_notes = load_notes

    mag_entries = doc.get("mag_files", [])
    if not isinstance(mag_entries, list):
        raise ProjectError(f"{path}: 'mag_files' must be a list, got {type(mag_entries).__name__}")
    site.mag_files = [_mag_file_from_dict(entry, root) for entry in mag_entries]
    mag_setup = doc.get("mag_setup")
    if isinstance(mag_setup, dict):
        try:
            site.mag_setup = MagSetup.from_dict(mag_setup)
        except (OverflowError, TypeError, ValueError):
            site.mag_setup = None

    cuts = doc.get("cuts", [])
    if not isinstance(cuts, list):
        raise ProjectError(f"{path}: 'cuts' must be a list, got {type(cuts).__name__}")
    site.cuts = [_cut_from_dict(entry) for entry in cuts]
    known_grids = {g.id for g in grids}
    for cut in site.cuts:
        if cut.grid_id not in known_grids:
            raise ProjectError(f"cut {cut.name!r} references unknown grid {cut.grid_id!r}")

    presets = doc.get("presets", {})
    if not isinstance(presets, dict):
        raise ProjectError(
            f"{path}: 'presets' must be an object keyed by name, got {type(presets).__name__}"
        )
    repaired_presets: dict[str, list[dict[str, Any]]] = {}
    for name, dicts in presets.items():
        try:
            repaired_presets[name] = _repair_steps(dicts, f"Preset {name!r}", load_notes)
            StepStack.from_dicts(repaired_presets[name])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"invalid preset {name!r}: {exc}") from exc
    site.presets = repaired_presets

    cubes = doc.get("cubes", {})
    if not isinstance(cubes, dict):
        raise ProjectError(
            f"{path}: 'cubes' must be an object keyed by id, got {type(cubes).__name__}"
        )
    site.cubes = dict(cubes)

    slice_sources = doc.get("slice_sources", {})
    if not isinstance(slice_sources, dict):
        raise ProjectError(
            f"{path}: 'slice_sources' must be an object keyed by grid id, "
            f"got {type(slice_sources).__name__}"
        )
    known = {g.id for g in grids}
    # Tolerant: an entry for an unknown grid, or one that is not an object,
    # is dropped; inside an entry a key of the wrong type is dropped too
    # (it reads as "unset"), so a hand-edited file never blocks opening.
    site.slice_sources = {
        gid: _clean_slice_source(entry)
        for gid, entry in slice_sources.items()
        if gid in known and isinstance(entry, dict)
    }

    site_view = doc.get("site_view", {})
    if not isinstance(site_view, dict):
        raise ProjectError(f"{path}: 'site_view' must be an object, got {type(site_view).__name__}")
    site.site_view = _clean_site_view(site_view, known)
    site.slice_colours = _clean_slice_colours(doc.get("slice_colours", {}))
    site.mag_view = _clean_mag_view(
        doc.get("mag_view"), {g.id for g in grids if g.instrument == "mag"}
    )
    site.import_presets = _clean_import_presets(doc.get("import_presets", {}), known)

    site.validate()
    return site
