"""Surfaces' authored records and the wording of what a selection can and
cannot do (M16 B, spec §4 calls 8 and 10, §5.3).

Pure: no qgis import, so the pure tier and mypy run it. The text lives here,
not in widgets (the plugin boundary); `surfaces.py` raises it as `ValueError`s
and the dialog shows it unchanged.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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


def move_note(moving: Mapping[str, int], n: int, left: Mapping[str, int] | None = None) -> str:
    """The warning that picks already in surfaces will move (call 3): `moving`
    maps each such surface's name to how many of the `n` picks it holds, and
    `left` to how many it keeps; one left with fewer than 3 cannot be rebuilt."""
    items = [(name, k) for name, k in moving.items() if k > 0]
    if not items:
        return ""
    names = _and([f"“{name}”" for name, _ in items])
    if len(items) == 1 and items[0][1] >= n:
        held = f"All {n} are in {names}"
    else:
        parts = [
            f"{k} of them are in “{name}”" if i == 0 else f"{k} in “{name}”"
            for i, (name, k) in enumerate(items)
        ]
        held = _and(parts)
    note = f"{held}; they will move to this surface, and {names} will need a rebuild."
    short = [
        f"“{name}” is left with {k} pick{'' if k == 1 else 's'}"
        for name, _ in items
        if left is not None and (k := left.get(name, MIN_PICKS)) < MIN_PICKS
    ]
    if short:
        note += f" {_and(short)}, too few to rebuild."
    return note


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
