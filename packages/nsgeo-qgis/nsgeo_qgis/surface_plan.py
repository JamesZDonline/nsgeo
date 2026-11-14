"""Surfaces' authored records and the wording of what a selection can and
cannot do (M16 B, spec §4 calls 8 and 10, §5.3).

Pure: no qgis import, so the pure tier and mypy run it. The text lives here,
not in widgets (the plugin boundary); `surfaces.py` raises it as `ValueError`s
and the dialog shows it unchanged.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
from nsgeo.slices import SurfaceSettings

KIND_SURFACE = "surface"
MAX_NAME = 80
MIN_PICKS = 3


def new_feature_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    """UTC ISO 8601 to the second, as the picks' `created`."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def settings_json(settings: SurfaceSettings) -> str:
    return json.dumps(settings.to_dict())


@dataclass(frozen=True)
class FeatureRecord:
    """One row of the site's `features` table: a named thing built from picks."""

    feature_id: str
    name: str
    grid_id: str
    kind: str
    settings: SurfaceSettings
    created: str

    def to_row(self) -> dict[str, str]:
        return {
            "feature_id": self.feature_id,
            "name": self.name,
            "grid_id": self.grid_id,
            "kind": self.kind,
            "settings_json": settings_json(self.settings),
            "created": self.created,
        }

    @staticmethod
    def from_row(row: Mapping[str, Any]) -> FeatureRecord:
        """A record from a table row (values may be QGIS NULLs, which read as
        empty). Settings that do not parse read as the defaults."""

        def text(name: str) -> str:
            value = row.get(name)
            return value if isinstance(value, str) else ""

        try:
            settings = SurfaceSettings.from_dict(json.loads(text("settings_json")))
        except (ValueError, TypeError, AttributeError):
            settings = SurfaceSettings()
        return FeatureRecord(
            feature_id=text("feature_id"),
            name=text("name"),
            grid_id=text("grid_id"),
            kind=text("kind") or KIND_SURFACE,
            settings=settings,
            created=text("created"),
        )


def clean_name(text: str) -> str:
    """The name as stored: trimmed, inner whitespace runs collapsed."""
    return " ".join(str(text).split())


def name_refusal(name: str, taken: Iterable[str], own: str | None = None) -> str:
    """Why `name` cannot be used, or "" when it can. Names compare case-folded
    and trimmed; `own` is the name of the record being renamed, which may keep
    it."""
    name = clean_name(name)
    if not name:
        return "Give the surface a name."
    if len(name) > MAX_NAME:
        return f"A surface name is at most {MAX_NAME} characters ({len(name)} typed)."
    mine = None if own is None else clean_name(own).casefold()
    for other in taken:
        folded = clean_name(other).casefold()
        if folded != mine and folded == name.casefold():
            return f"A surface called “{clean_name(other)}” already exists; names are unique."
    return ""


def _count(k: int, singular: str, plural: str) -> str:
    return f"{k} of these picks {singular if k == 1 else plural}"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def selection_refusal(
    *,
    n: int,
    unsaved: int,
    on_cuts: int,
    grids: Collection[str],
    spans_area: bool,
    no_grid: int = 0,
    unreadable: int = 0,
    minimum: int = MIN_PICKS,
) -> str:
    """Why the selected picks cannot make (or join) a surface, or "". Checked
    in order: none selected, unsaved, on cuts, not on a grid's line, two grids,
    too few or in a straight line. `minimum` is 3 for a new surface and 1 for
    picks added to one."""
    if n <= 0:
        return (
            "Select picks on the map first: make the picks layer current and use "
            "QGIS's Select tool."
        )
    if unsaved:
        return (
            "Save the picks layer's edits first; "
            f"{unsaved} of these picks {'is' if unsaved == 1 else 'are'} not saved yet."
        )
    if unreadable:
        return (
            f"{_count(unreadable, 'has', 'have')} no trace or time; edit or delete "
            f"{'it' if unreadable == 1 else 'them'} in the picks layer."
        )
    if on_cuts:
        return (
            f"{_count(on_cuts, 'is', 'are')} on a cut. "
            "Picks on cuts can join surfaces in a later version."
        )
    if no_grid:
        return (
            f"{_count(no_grid, 'is', 'are')} not on a line of a grid, so "
            f"{'it' if no_grid == 1 else 'they'} cannot be placed."
        )
    if len(grids) > 1:
        return (
            f"These picks are on {_and([f'Grid {g}' for g in sorted(grids)])}. "
            "A surface comes from one grid; select picks on one grid only."
        )
    if n < minimum or not spans_area:
        if minimum <= 1:
            return ""
        return (
            f"A surface needs at least {minimum} picks that are not in a straight line "
            f"({n} selected)."
        )
    return ""


def grid_mismatch_refusal(name: str, surface_grid: str, picks_grid: str) -> str:
    return (
        f"“{name}” is on Grid {surface_grid}, and these picks are on Grid {picks_grid}. "
        "A surface comes from one grid."
    )


def feature_ids(value: object) -> tuple[str, ...]:
    """The surfaces a pick belongs to, from its `feature_id` column (call 8, amended): ids
    joined by ";". Read tolerantly (hand edits): split, strip, drop empties and repeats."""
    if value is None:
        return ()
    return tuple(dict.fromkeys(p.strip() for p in str(value).split(";") if p.strip()))


def join_feature_ids(ids: Iterable[str]) -> str | None:
    """The column value for `ids`, in order and without repeats; None when there are none."""
    kept = tuple(dict.fromkeys(i for i in ids if i))
    return ";".join(kept) if kept else None


def also_note(also: Mapping[str, int], n: int) -> str:
    """Informational: `also` maps the name of each other surface to how many of the `n`
    selected picks it holds. They join the new one and stay where they are."""
    items = [(name, k) for name, k in also.items() if k > 0]
    if not items:
        return ""
    if len(items) == 1 and items[0][1] >= n:
        if n == 1:
            return f"This pick is also in “{items[0][0]}”."
        return f"All {n} of these picks are also in “{items[0][0]}”."
    parts = [
        f"{k} of these picks {'is' if k == 1 else 'are'} also in “{name}”"
        if i == 0
        else f"{k} in “{name}”"
        for i, (name, k) in enumerate(items)
    ]
    return f"{_and(parts)}."


IN_TRANSACTION_REFUSAL = (
    "The picks layer is in editing mode, and this project groups edits into one transaction, "
    "so a change to a surface's picks would be undone if you discard the layer's edits. "
    "Save the picks layer's edits or leave editing mode, then try again."
)
NOTHING_TO_REMOVE = (
    "None of the picks selected on the map belong to this surface, so nothing was removed."
)


def remove_refusal(left: int) -> str:
    if left >= MIN_PICKS:
        return ""
    return (
        f"A surface needs at least {MIN_PICKS} picks; taking these out would leave {max(left, 0)}. "
        "Delete the surface instead."
    )


def delete_question(name: str, n_picks: int) -> str:
    stay = "Its pick stays; it stops" if n_picks == 1 else f"Its {n_picks} picks stay; they stop"
    return f"Delete “{name}”? {stay} belonging to it. Its map layer and built files go."


def rebuild_refusal(name: str, members: int) -> str:
    """Why a surface cannot be rebuilt, or "" (picks moved out of it can leave it with too few)."""
    if members >= MIN_PICKS:
        return ""
    return (
        f"“{name}” has {members} pick{'' if members == 1 else 's'} left, too few to rebuild; "
        f"a surface needs at least {MIN_PICKS}. Add picks to it, or delete it."
    )


MULTI_GRID_REFUSAL = "A build is of one grid's surfaces; these are on more than one grid."
WHY_NO_LINE = "their line isn't in this grid's slices"
WHY_NO_DEPTH = "their depth could not be found"
WHY_NO_POSITION = "their position on the line could not be found"


def skipped_text(skipped: Sequence[Mapping[str, Any]]) -> str:
    """`2 picks could not be placed (their line isn't in this grid's slices)`, or ""."""
    if not skipped:
        return ""
    why = list(dict.fromkeys(str(s.get("why", "")) for s in skipped))
    n = len(skipped)
    return f"{n} pick{'' if n == 1 else 's'} could not be placed ({_and([w for w in why if w])})"


def skipped_refusal(name: str, usable: int, skipped: Sequence[Mapping[str, Any]]) -> str:
    """Why skipping left too few picks to build, or "" when it did not."""
    if not skipped or usable >= MIN_PICKS:
        return ""
    return (
        f"“{name}”: {skipped_text(skipped)}, which leaves {usable} usable; "
        f"a surface needs at least {MIN_PICKS}. Check which lines the grid's slices use."
    )


# ---- what a build depends on -------------------------------------------------------------
#: What a surface's numbers depend on, in the order the panel lists them (spec call 9).
INPUTS = ("picks", "settings", "source", "resolution", "fill", "volume", "velocity")

STALE_REASONS: dict[str, str] = {
    "picks": "its picks changed",
    "settings": "its settings changed",
    "source": "the grid's processing, lines or placement changed",
    "resolution": "the grid's 3-D cell or depth step changed",
    "fill": "the grid's fill method or distances changed",
    "volume": "the 3-D wave period or depth balance changed",
    "velocity": "the grid's velocity changed",
    "unavailable": "its grid or lines can't be read right now",
}


def input_hash(value: Any) -> str:
    """16 hex characters of the sha1 of `value` as sorted JSON."""
    text = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def stale_text(stale: Iterable[str]) -> str:
    """The line the panel shows for a stale surface ("" when nothing changed)."""
    names = set(stale)
    order = (*INPUTS, "unavailable")
    reasons = [STALE_REASONS[name] for name in order if name in names]
    reasons += [f"{n} changed" for n in sorted(names) if n not in STALE_REASONS]
    if not reasons:
        return ""
    return (
        f"Stale: {_and(reasons)} since it was built. "
        "The map and the next export show the last build."
    )


# ---- the fit report ---------------------------------------------------------------------
def _cm(metres: float) -> str:
    return f"{abs(metres) * 100.0:.1f} cm"


def offset_text(report: Mapping[str, Any]) -> str:
    """Where the picks sit against the strongest swing; says plainly when the offset is
    unreliable (most picks found their strongest swing only at the search limit)."""
    votes = int(report.get("offset_votes", 0))
    if votes <= 0:
        return "no pick had a swing in reach, so the offset could not be measured"
    offset = float(report.get("offset_m", 0.0))
    if abs(offset) < 0.0005:
        text = "your picks sit on the strongest swing"
    else:
        side = "above" if offset > 0 else "below"
        text = f"your picks sit {_cm(offset)} {side} the strongest swing"
    if not report.get("offset_reliable", True):
        text += (
            "; most of your picks found their strongest swing only at the 5 cm search limit; "
            "a stronger reflection out of reach may be pulling this surface — check the picks"
        )
    return text


def _fit(report: Mapping[str, Any]) -> Mapping[str, Any]:
    fit = report.get("fit", {})
    return fit if isinstance(fit, Mapping) else {}


def fit_rows(report: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Picks, Offset, Cover and Built, as the mockup's fit block."""
    fit = _fit(report)
    picks = int(fit.get("picks", 0))
    parts = [
        f"{int(fit.get('within_2cm', 0))} of {picks} within 2 cm",
        f"{int(fit.get('within_5cm', 0))} within 5 cm",
    ]
    if int(fit.get("further", 0)):
        parts.append(f"{int(fit['further'])} further away")
    if int(fit.get("at_edge", 0)):
        parts.append(f"{int(fit['at_edge'])} at the window's edge")
    parts.append(f"{int(fit.get('on_holes', 0))} on holes")
    skipped = skipped_text(report.get("skipped", []))
    cells, region = int(report.get("cells", 0)), int(report.get("region_cells", 0))
    if region > 0 and cells >= region:
        cover = f"all {cells:,} cells; no holes"
    elif region > 0:
        share = round(100.0 * cells / region)
        cover = f"{cells:,} of {region:,} cells ({share}%); the rest are holes"
    else:
        cover = "no cell was inside the picks' area"
    res = report.get("resolution", {})
    built = str(report.get("built_utc", ""))[:16].replace("T", " ")
    rows = [
        ("Picks", " · ".join(parts)),
        ("Offset", offset_text(report)),
        ("Cover", cover),
        (
            "Built",
            f"{built} UTC at {float(res.get('cell', 0.0)):g} m, "
            f"{float(res.get('dz_ns', 0.0)):g} ns",
        ),
    ]
    if skipped:
        rows.insert(1, ("Skipped", skipped))
    return rows


def outlier_line(outlier: Mapping[str, Any]) -> str:
    """One outlier as the panel lists it: `FILE__023 at 4.15 m · picked 0.62 m · on a hole`."""
    where = str(outlier.get("label", "")) or str(outlier.get("line_key", ""))
    if outlier.get("distance_m") is not None:
        where += f" at {float(outlier['distance_m']):.2f} m"
    text = f"{where} · picked {float(outlier.get('picked_m', 0.0)):.2f} m"
    surface = outlier.get("surface_m")
    reason = outlier.get("reason", "")
    if surface is None or reason == "hole":
        return text + " · on a hole"
    gap = float(surface) - float(outlier.get("picked_m", 0.0))
    text += f" · surface {float(surface):.2f} m ({_cm(gap)})"
    if reason == "edge":
        return text + " · held at the window's edge"
    return text + " · beyond the window"


def built_message(name: str, report: Mapping[str, Any]) -> str:
    """The message bar's line after a build."""
    fit = _fit(report)
    text = (
        f"Built “{name}”: {int(fit.get('within_2cm', 0))} of {int(fit.get('picks', 0))} picks "
        f"within 2 cm, {int(fit.get('on_holes', 0))} on holes."
    )
    offset = offset_text(report)
    text = f"{text} {offset[0].upper()}{offset[1:]}."
    skipped = skipped_text(report.get("skipped", []))
    return f"{text} {skipped}." if skipped else text


def empty_message(name: str) -> str:
    return (
        f"“{name}” built empty: no cell passed the strength test. Lower the strength test, "
        "or check that the picks are on a reflection."
    )


# ---- the mesh files ---------------------------------------------------------------------
def mesh_2dm(world_xy: np.ndarray, z: np.ndarray, triangles: np.ndarray) -> str:
    """A 2DM mesh: vertices `ND i x y z` and triangles `E3T i a b c 1`, numbered from 1."""
    lines = ["MESH2D"]
    lines += [
        f"ND {i + 1} {x:.4f} {y:.4f} {v:.5f}"
        for i, (x, y, v) in enumerate(zip(world_xy[:, 0], world_xy[:, 1], z))
    ]
    lines += [f"E3T {i + 1} {a + 1} {b + 1} {c + 1} 1" for i, (a, b, c) in enumerate(triangles)]
    return "\n".join(lines) + "\n"


def mesh_dat(values: np.ndarray, n_elements: int) -> str:
    """An ASCII DAT scalar dataset "depth (m)" with one value per vertex."""
    lines = [
        "DATASET",
        'OBJTYPE "mesh2d"',
        "BEGSCL",
        f"ND {len(values)}",
        f"NC {n_elements}",
        'NAME "depth (m)"',
        "TS 0 0.0",
    ]
    lines += [f"{v:.5f}" for v in values]
    lines.append("ENDDS")
    return "\n".join(lines) + "\n"


#: Appended to a surface's map layer name when its inputs have changed since its build.
STALE_SUFFIX = " (stale)"


def layer_name(name: str, stale: bool) -> str:
    """The map layer's name: the surface's, labelled when it shows an out-of-date build."""
    return name + STALE_SUFFIX if stale else name


def merge_range(shared: tuple[float, float] | None, low: float, high: float) -> tuple[float, float]:
    """`shared` widened to take in the depths `low` to `high`: the one range every surface of a
    grid is coloured over, so equal colours mean equal depths."""
    if shared is None:
        return (low, high)
    return (min(shared[0], low), max(shared[1], high))


# ---- the New surface dialog and the Surfaces panel ---------------------------------------
def selection_label(n: int, grid_id: str | None, labels: Sequence[str]) -> str:
    """`88 picks selected, all on Grid 1 (lines FILE__020 to FILE__033).`"""
    if n <= 0:
        return "No picks selected."
    text = f"{n} pick{'' if n == 1 else 's'} selected"
    if grid_id is None:
        return text + "."
    labels = sorted(set(labels))
    where = f"on Grid {grid_id}" if n == 1 else f"all on Grid {grid_id}"
    if len(labels) == 1:
        return f"{text}, {where} (line {labels[0]})."
    if len(labels) > 1:
        return f"{text}, {where} (lines {labels[0]} to {labels[-1]})."
    return f"{text}, {where}."


_JOIN_NAMES = {"min_curvature": "smooth", "idw": "inverse-distance"}


def join_name(join: str) -> str:
    return _JOIN_NAMES.get(join, join)


def settings_summary(settings: SurfaceSettings) -> str:
    """The folded Settings' one line: `smooth join · window ±2 cm · ...`."""
    smoothing = (
        "no smoothing" if settings.smoothing_m <= 0 else f"smoothing {settings.smoothing_m:.2f} m"
    )
    return (
        f"{join_name(settings.join)} join · window ±{settings.window_m * 100:g} cm · "
        f"strength {settings.strength:.1f} × typical · {smoothing}"
    )


def state_text(built: bool, stale: Iterable[str]) -> str:
    """The panel's state column: "not built", "stale" or nothing."""
    if not built:
        return "not built"
    return "stale" if list(stale) else ""


def fit_short(report: Mapping[str, Any] | None) -> str:
    """`80/84`: picks within 2 cm over picks placed, "" before a build."""
    if not report:
        return ""
    fit = _fit(report)
    return f"{int(fit.get('within_2cm', 0))}/{int(fit.get('picks', 0))}"


LOCKED_PICKS_TEXT = (
    "The site file is locked, most likely because the picks layer has unsaved edits. "
    "Save the picks layer's edits, or leave editing mode on it, and try again."
)


FILE_LOCKED_TEXT = (
    "Another program has the site file open (Windows locks a file while it is in use). "
    "Close it there, then try again."
)


def write_failure_text(message: str) -> str:
    """A refused write as the user should read it: QGIS's "database is locked" (a picks layer in
    editing mode under the project's automatic transaction groups) says what to do."""
    lowered = message.lower()
    if "database is locked" in lowered:
        return LOCKED_PICKS_TEXT
    if "locked a portion of the file" in lowered:
        return FILE_LOCKED_TEXT
    return message


def build_outcome(name: str, report: Mapping[str, Any]) -> tuple[str, bool]:
    """The message after one surface's build and whether it is a warning: an empty surface, an
    offset that could not be trusted, picks left out, or picks at the window's edge."""
    if int(report.get("cells", 0)) <= 0:
        return empty_message(name), True
    fit = _fit(report)
    warn = (
        not report.get("offset_reliable", True)
        or bool(report.get("skipped"))
        or int(fit.get("at_edge", 0)) > 0
    )
    return built_message(name, report), warn


def skipped_surfaces_text(names: Sequence[str]) -> str:
    """What the export's message says of surfaces it could not put in the scene, or ""."""
    if not names:
        return ""
    listed = _and([f"“{n}”" for n in names])
    noun = "Surface" if len(names) == 1 else "Surfaces"
    return (
        f"{noun} {listed} {'was' if len(names) == 1 else 'were'} left out: "
        "the coordinate system of the build could not be converted to this export's."
    )


# ---- more wording the panel, the dialog and the build flow show -----------------------------
PREPARING_LINES = "Preparing lines…"
NO_LONGER_MEMBER = "That pick is no longer in the surface; rebuild to refresh the list."
EXPORT_RUNNING = (
    "an export is already running; wait for it to finish, or cancel it in the task list."
)


def not_built_text(n_picks: int) -> str:
    picks = f"{n_picks} pick{'' if n_picks == 1 else 's'}"
    return f"Not built yet ({picks}). Rebuild to put it on the map."


def outlier_header(window_m: float, n: int) -> str:
    text = (
        f"Picks the surface doesn't follow ({n}): on a hole, at the window's edge, "
        f"or more than {window_m * 100:g} cm off"
    )
    return text + ("; click one to select it on the map:" if n else "")


def build_title(names: Sequence[str]) -> str:
    """The progress dialog's label: `Building “Bowl”`, or `Building 3 surfaces`."""
    if len(names) == 1:
        return f"Building “{names[0]}”"
    return f"Building {len(names)} surfaces"


def resolution_hint(
    grid_id: str | None, cell: float | None = None, dz_ns: float | None = None
) -> str:
    """The New surface dialog's line on the 3-D resolution a build uses."""
    if grid_id is None or cell is None or dz_ns is None:
        return "Built at the grid's 3-D resolution, the one its ParaView export uses."
    return (
        f"Built at Grid {grid_id}'s 3-D resolution ({cell:g} m, {dz_ns:g} ns), "
        "the one its ParaView export uses."
    )


def build_failure_text(names: Sequence[str], exc: BaseException) -> str:
    """Why a build failed. A refusal (ValueError, RuntimeError) is already worded; anything else
    (a full disk, a locked file, a lookup) is named after the surfaces it stopped."""
    if isinstance(exc, (ValueError, RuntimeError)):
        return write_failure_text(str(exc))
    listed = _and([f"“{n}”" for n in names])
    return f"Could not build {listed}: {write_failure_text(str(exc)) or type(exc).__name__}"


DELETE_TITLE = "Delete surface"
DELETE_BUTTON = "Delete"
