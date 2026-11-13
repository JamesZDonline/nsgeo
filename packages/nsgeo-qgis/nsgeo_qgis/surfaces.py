"""Surfaces: the site's authored surface records and which picks belong to
each (M16 B Task 2; spec §4 calls 8 and 10, §5.3). Membership only -- building
a surface is Task 3.

A surface is a row in `features` plus every `picks` row whose `feature_id`
names it. Both live in the GeoPackage and are written straight through the
data provider, like picks, so none of this dirties the session. Each refused
change raises `ValueError` carrying `surface_plan`'s text; each completed one
emits `session.features_changed` after the write.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nsgeo.model import is_cut_key
from nsgeo.slices import SurfaceSettings, picks_span_an_area

from nsgeo_qgis.layers import PickRow, SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.surface_plan import (
    KIND_SURFACE,
    FeatureRecord,
    clean_name,
    grid_mismatch_refusal,
    name_refusal,
    new_feature_id,
    now_iso,
    remove_refusal,
    selection_refusal,
)

if TYPE_CHECKING:
    from nsgeo_qgis.paraview_export import ParaViewExport


@dataclass(frozen=True)
class SelectionCheck:
    """What a selection of picks can do: `refusal` is "" when it can make (or
    join) a surface; `grid_id` is the one grid the picks are on; `moving` maps
    the name of each other surface that holds some of them to how many; `n` is
    the number selected."""

    refusal: str
    grid_id: str | None
    moving: dict[str, int] = field(default_factory=dict)
    n: int = 0
    # What each surface in `moving` keeps after the move (under 3 cannot rebuild).
    left: dict[str, int] = field(default_factory=dict)


class Surfaces:
    def __init__(
        self,
        session: SiteSession,
        layers: SiteLayers,
        export_for: Callable[[], ParaViewExport] | None = None,
    ) -> None:
        self.session = session
        self.layers = layers
        # Used from Task 3, where the plugin passes a factory bound to the
        # Slices dock; membership never needs it.
        self.export_for = export_for

    # ---- reading ------------------------------------------------------------
    def records(self) -> list[FeatureRecord]:
        return [r for r in self.layers.feature_records() if r.kind == KIND_SURFACE]

    def _record(self, feature_id: str) -> FeatureRecord:
        for record in self.records():
            if record.feature_id == feature_id:
                return record
        raise KeyError(f"no surface with id {feature_id!r}")

    def members(self, feature_id: str) -> list[PickRow]:
        return self.layers.members_by_feature().get(feature_id, [])

    def _grid_of(self, key: str) -> str | None:
        """The id of the grid line `key` is on, or None (no such line, or no grid)."""
        try:
            grid = self.session.grid_for_line(self.session.line_for_key(key))
        except KeyError:
            return None
        return None if grid is None else str(grid.id)

    def check(self, fids: Iterable[int], *, into: str | None = None) -> SelectionCheck:
        """Whether `fids` (picks-layer fids) can make a surface, or join the
        surface `into`. Nothing is written."""
        fids = list(dict.fromkeys(int(f) for f in fids))
        # Unsaved: added in editing mode, edited there, or gone from the table.
        # Saved but blank (no trace or time) is a different problem, worded so.
        pending = self.layers.unsaved_among(fids)
        saved = [f for f in fids if f not in pending]
        rows = self.layers.pick_rows(saved)
        unreadable = self.layers.unreadable_pick_ids(saved)
        unsaved = len(fids) - len(rows) - len(unreadable)
        on_cuts = 0
        no_grid = 0
        grids: set[str] = set()
        placed: list[tuple[float, float]] = []
        for row in rows:
            key = row.pick.line_key
            if is_cut_key(key):
                on_cuts += 1
                continue
            grid_id = self._grid_of(key)
            if grid_id is None or row.point is None:
                no_grid += 1
                continue
            grids.add(grid_id)
            placed.append(row.point)
        joining = None if into is None else self._record(into)
        spans = True
        if joining is None and len(placed) >= 3:
            spans = picks_span_an_area([p[0] for p in placed], [p[1] for p in placed])
        refusal = selection_refusal(
            n=len(fids),
            unsaved=unsaved,
            on_cuts=on_cuts,
            no_grid=no_grid,
            unreadable=len(unreadable),
            grids=grids,
            spans_area=spans,
            minimum=1 if joining is not None else 3,
        )
        grid_id = next(iter(grids)) if len(grids) == 1 else None
        if not refusal and joining is not None and grid_id != joining.grid_id:
            refusal = grid_mismatch_refusal(joining.name, joining.grid_id, str(grid_id))
        names = {r.feature_id: r.name for r in self.records()}
        held = self.layers.members_by_feature()
        moving: dict[str, int] = {}
        left: dict[str, int] = {}
        for row in rows:
            owner = row.pick.feature_id
            if owner in names and owner != into:
                moving[names[owner]] = moving.get(names[owner], 0) + 1
        for owner, name in names.items():
            if name in moving:
                left[name] = len(held.get(owner, [])) - moving[name]
        return SelectionCheck(refusal, grid_id, moving, len(fids), left)

    # ---- changes ------------------------------------------------------------
    def _refuse_name(self, name: str, own: str | None = None) -> str:
        taken = [r.name for r in self.records()]
        text = name_refusal(name, taken, own)
        if text:
            raise ValueError(text)
        return clean_name(name)

    def _changed(self) -> None:
        self.session.features_changed.emit()

    def create(
        self, name: str, fids: Iterable[int], settings: SurfaceSettings | None = None
    ) -> FeatureRecord:
        fids = list(fids)
        name = self._refuse_name(name)
        found = self.check(fids)
        if found.refusal:
            raise ValueError(found.refusal)
        assert found.grid_id is not None
        record = FeatureRecord(
            feature_id=new_feature_id(),
            name=name,
            grid_id=found.grid_id,
            kind=KIND_SURFACE,
            settings=settings or SurfaceSettings(),
            created=now_iso(),
        )
        # The row first, then the picks: a failure between them leaves a row
        # with no picks (removed below), never picks naming nothing.
        self.layers.write_feature(record)
        try:
            self.layers.set_pick_feature(fids, record.feature_id)
        except Exception:
            self.layers.remove_feature(record.feature_id)
            raise
        self._changed()
        return record

    def rename(self, feature_id: str, name: str) -> None:
        record = self._record(feature_id)
        name = self._refuse_name(name, own=record.name)
        self.layers.update_feature(feature_id, name=name)
        self._changed()

    def set_settings(self, feature_id: str, settings: SurfaceSettings) -> None:
        self._record(feature_id)
        self.layers.update_feature(feature_id, settings=settings)
        self._changed()

    def add_picks(self, feature_id: str, fids: Iterable[int]) -> None:
        fids = list(fids)
        found = self.check(fids, into=feature_id)
        if found.refusal:
            raise ValueError(found.refusal)
        already = {r.fid for r in self.members(feature_id)}
        fresh = [f for f in dict.fromkeys(fids) if f not in already]
        if not fresh:
            return
        self.layers.set_pick_feature(fresh, feature_id)
        self._changed()

    def remove_picks(self, feature_id: str, fids: Iterable[int]) -> None:
        self._record(feature_id)
        held = {row.fid for row in self.members(feature_id)}
        leaving = sorted(held & {int(f) for f in fids})
        if not leaving:
            return
        text = remove_refusal(len(held) - len(leaving))
        if text:
            raise ValueError(text)
        self.layers.set_pick_feature(leaving, None)
        self._changed()

    def delete(self, feature_id: str) -> None:
        """Remove the surface. Its picks all stay: they are cleared first, so
        a failure partway leaves a surface with fewer picks, never picks that
        name a surface which is gone."""
        self._record(feature_id)
        self.layers.clear_pick_feature(feature_id)
        self.layers.remove_feature(feature_id)
        self._changed()
