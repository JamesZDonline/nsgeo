"""Surfaces: the site's authored surface records, which picks belong to each (M16 B
Task 2; spec §4 calls 8 and 10, §5.3), and building one (Task 3; calls 2, 7, 9, 17).

A build gets its lines and its kept fill from `ParaViewExport.fill` at the grid's own 3-D
resolution, runs the core builder and writes `<site>/surfaces/<grid>/`: per surface an
`.npz` (the depth grid), a `.2dm` mesh and a `.dat` depth dataset named by feature id and a
build key, then `<id>.json` last, so a build is complete exactly when its json names its
files. A cancelled or failed build leaves the previous build's files and json untouched.

A surface is a row in `features` plus every `picks` row whose `feature_id` lists it (a pick
can be in several surfaces: ids joined by ";"). Both live in the GeoPackage and are written
straight through the data provider, like picks, so none of this dirties the session. Each refused
change raises `ValueError` carrying `surface_plan`'s text; each completed one
emits `session.features_changed` after the write.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import traceback
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import nsgeo
import numpy as np
from nsgeo.model import is_cut_key
from nsgeo.slices import (
    SurfaceSettings,
    build_surface,
    picks_span_an_area,
    surface_mesh,
    surface_volume,
)

from nsgeo_qgis.layers import PickRow, SiteLayers
from nsgeo_qgis.paraview_export import (
    ParaViewExportCancelled,
    _safe,
    _slab_levels,
    place_picks,
)
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.surface_plan import (
    IN_TRANSACTION_REFUSAL,
    INPUTS,
    KIND_SURFACE,
    MULTI_GRID_REFUSAL,
    WHY_NO_DEPTH,
    WHY_NO_LINE,
    WHY_NO_POSITION,
    FeatureRecord,
    clean_name,
    feature_ids,
    grid_mismatch_refusal,
    input_hash,
    mesh_2dm,
    mesh_dat,
    name_refusal,
    new_feature_id,
    now_iso,
    rebuild_refusal,
    remove_refusal,
    selection_refusal,
    skipped_refusal,
)

if TYPE_CHECKING:
    from nsgeo_qgis.paraview_export import ParaViewExport

# Of a build's progress, the share spent on the fill's levels and on the volume's slabs;
# the rest is the surfaces themselves.
_FILL_SHARE = 80
_VOLUME_SHARE = 95

_OWN_FILES = re.compile(r"[0-9a-f]{32}(-[0-9a-f]{8}\.(npz|2dm|dat)|\.json)(\.part)?")


@dataclass(frozen=True)
class SurfaceState:
    """`built`: a complete build exists; `stale`: the inputs (of `INPUTS`) that differ from
    that build's; `report`: its json (None until built)."""

    built: bool
    stale: tuple[str, ...]
    report: dict[str, Any] | None


@dataclass(frozen=True)
class BuildReport:
    feature_id: str
    name: str
    report: dict[str, Any]
    files: tuple[Path, ...]


@dataclass(frozen=True, eq=False)
class BuiltSurface:
    """A saved build: the npz's arrays beside its json."""

    report: dict[str, Any]
    depth_m: np.ndarray
    strength: np.ndarray
    cell: float
    origin: tuple[float, float]
    azimuth: float
    crs: str
    files: dict[str, Path]


@dataclass(frozen=True)
class SelectionCheck:
    """What a selection of picks can do: `refusal` is "" when it can make (or join) a
    surface; `grid_id` is the one grid the picks are on; `also` maps the name of each
    other surface that already holds some of them to how many (they stay there); `n` is
    the number selected."""

    refusal: str
    grid_id: str | None
    also: dict[str, int] = field(default_factory=dict)
    n: int = 0


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
        #: Greater than 0 while `build` runs: nothing may delete a grid's surface files then
        #: (`SurfaceLayers.sync` holds back its sweep).
        self.building = 0
        #: The refusals (too few picks left) of the surfaces the last `build` skipped.
        self.refused: list[str] = []

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
        also: dict[str, int] = {}
        for row in rows:
            for owner in feature_ids(row.pick.feature_id):
                if owner in names and owner != into:
                    also[names[owner]] = also.get(names[owner], 0) + 1
        return SelectionCheck(refusal, grid_id, also, len(fids))

    # ---- changes ------------------------------------------------------------
    def _refuse_name(self, name: str, own: str | None = None) -> str:
        taken = [r.name for r in self.records()]
        text = name_refusal(name, taken, own)
        if text:
            raise ValueError(text)
        return clean_name(name)

    def _refuse_in_transaction(self) -> None:
        """Membership writes go to the package at once; inside the user's open transaction
        group they would be discarded with it (see `SiteLayers.picks_in_open_transaction`)."""
        if self.layers.picks_in_open_transaction():
            raise ValueError(IN_TRANSACTION_REFUSAL)

    def _changed(self) -> None:
        self.session.features_changed.emit()

    def create(
        self, name: str, fids: Iterable[int], settings: SurfaceSettings | None = None
    ) -> FeatureRecord:
        fids = list(fids)
        self._refuse_in_transaction()
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
            self.layers.add_pick_feature(fids, record.feature_id)
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
        self._refuse_in_transaction()
        found = self.check(fids, into=feature_id)
        if found.refusal:
            raise ValueError(found.refusal)
        if self.layers.add_pick_feature(fids, feature_id):
            self._changed()

    def remove_picks(self, feature_id: str, fids: Iterable[int]) -> int:
        """Take `fids` out of the surface; returns how many were in it (0: nothing changed)."""
        self._record(feature_id)
        self._refuse_in_transaction()
        held = {row.fid for row in self.members(feature_id)}
        leaving = sorted(held & {int(f) for f in fids})
        if not leaving:
            return 0
        text = remove_refusal(len(held) - len(leaving))
        if text:
            raise ValueError(text)
        self.layers.remove_pick_feature(leaving, feature_id)
        self._changed()
        return len(leaving)

    def delete(self, feature_id: str) -> None:
        """Remove the surface. Its picks all stay (and keep their other surfaces): its id is
        taken out of them first, so a failure partway leaves a surface with fewer picks,
        never picks that name a surface which is gone."""
        self._record(feature_id)
        self._refuse_in_transaction()
        self.layers.clear_pick_feature(feature_id)
        self.layers.remove_feature(feature_id)
        self._changed()

    # ---- building (Task 3) ----------------------------------------------------
    def _export(self) -> ParaViewExport:
        if self.export_for is None:
            raise RuntimeError("surfaces cannot be built here: no 3-D export is attached")
        return self.export_for()

    def folder(self, grid_id: str) -> Path:
        """Where a grid's built surfaces go: `<site>/surfaces/<grid>`."""
        return Path(self.session.root) / "surfaces" / _safe(grid_id)

    def _json_path(self, record: FeatureRecord) -> Path:
        return self.folder(record.grid_id) / f"{record.feature_id}.json"

    def inputs(
        self, feature_id: str, members: dict[str, list[PickRow]] | None = None
    ) -> dict[str, str]:
        """What the surface's numbers depend on, one 16-hex hash per `INPUTS` name. Reads the
        record and the session only; nothing is prepared."""
        export = self._export()
        record = self._record(feature_id)
        session = self.session
        grid = session.grid(record.grid_id)
        choice = export.defaults(record.grid_id)
        source = export.source_choice(record.grid_id, choice)
        finish = export.fill_settings(record.grid_id)
        held = self.members(feature_id) if members is None else members.get(feature_id, [])
        picks = sorted(
            [r.pick.line_key, r.pick.trace, r.pick.time_ns, r.pick.zero_ns] for r in held
        )
        keys = sorted(source.line_keys)
        return {
            "picks": input_hash(picks),
            "settings": input_hash(record.settings.to_dict()),
            "source": input_hash(
                {
                    "preset": source.preset,
                    "steps": list(session.site.presets.get(source.preset, [])),
                    "transform": source.transform,
                    "lines": [[k, repr(session.line_for_key(k).placement)] for k in keys],
                    "grid": [list(grid.origin), grid.azimuth, grid.size_x, grid.size_y, grid.crs],
                }
            ),
            # The record's own depth, never the Slices panel's z1 or its engine's bounds (R10).
            "resolution": input_hash(
                {
                    "cell": choice.cell,
                    "dz_ns": choice.dz_ns,
                    "t1_ns": session.volume_record(record.grid_id).get("t1_ns"),
                }
            ),
            "fill": input_hash(
                [
                    finish.method,
                    finish.max_distance_m,
                    finish.search_radius_m,
                    finish.smooth_x_m,
                    finish.smooth_y_m,
                ]
            ),
            "volume": input_hash(
                {"period_ns": choice.settings.period_ns, "trend_m": choice.settings.trend_m}
            ),
            "velocity": input_hash(session.grid_depth_velocity(record.grid_id).to_dict()),
        }

    def _read_report(self, record: FeatureRecord) -> dict[str, Any] | None:
        """The surface's json when it is whole: it parses and the files it names exist."""
        path = self._json_path(record)
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            files = [path.parent / name for name in report["files"].values()]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None
        if not isinstance(report, dict) or not all(f.is_file() for f in files):
            return None
        return report

    def state(
        self, feature_id: str, members: dict[str, list[PickRow]] | None = None
    ) -> SurfaceState:
        record = self._record(feature_id)
        report = self._read_report(record)
        if report is None:
            return SurfaceState(False, (), None)
        try:
            now = self.inputs(feature_id, members)
        except (KeyError, IndexError, OSError, ValueError, RuntimeError):
            # The grid or a line is gone, or a file cannot be reached: say so, never raise.
            return SurfaceState(True, ("unavailable",), report)
        then = report.get("inputs", {})
        stale = tuple(name for name in INPUTS if now.get(name) != then.get(name))
        return SurfaceState(True, stale, report)

    def built(self, feature_id: str) -> BuiltSurface | None:
        record = self._record(feature_id)
        report = self._read_report(record)
        if report is None:
            return None
        folder = self.folder(record.grid_id)
        files = {kind: folder / name for kind, name in report["files"].items()}
        try:
            with np.load(files["npz"]) as npz:
                return BuiltSurface(
                    report=report,
                    depth_m=np.array(npz["depth_m"]),
                    strength=np.array(npz["strength"]),
                    cell=float(npz["cell"]),
                    origin=(float(npz["origin"][0]), float(npz["origin"][1])),
                    azimuth=float(npz["azimuth"]),
                    crs=str(npz["crs"]),
                    files=files,
                )
        except (OSError, ValueError, KeyError):
            return None

    def sweep(self, grid_id: str) -> list[Path]:
        """Delete the files in the grid's folder that no surface's json names, and any
        unfinished `.part`; files that are not nsgeo's own are never touched, and one that
        cannot be deleted (open elsewhere) is skipped. Returns what was deleted."""
        folder = self.folder(grid_id)
        if not folder.is_dir():
            return []
        keep: set[str] = set()
        for record in self.records():
            if _safe(record.grid_id) != _safe(grid_id):  # "Grid 1" and "Grid_1" share a folder
                continue
            path = self._json_path(record)
            if not path.exists():
                continue
            keep.add(path.name)
            try:
                keep.update(json.loads(path.read_text(encoding="utf-8"))["files"].values())
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                # A json that cannot be read cannot say what it owns: keep everything of its.
                keep.update(
                    p.name for p in folder.iterdir() if p.name.startswith(f"{record.feature_id}-")
                )
        gone: list[Path] = []
        for path in sorted(folder.iterdir()):
            if not path.is_file() or not _OWN_FILES.fullmatch(path.name):
                continue
            if path.name in keep and not path.name.endswith(".part"):
                continue
            try:
                path.unlink()
            except OSError:
                continue
            gone.append(path)
        return gone

    def build(
        self, feature_ids: Iterable[str], *, progress: Callable[[int, int], bool]
    ) -> list[BuildReport]:
        """Build each surface of `feature_ids` (all on one grid) at the grid's own 3-D
        resolution. `progress(done, total)` is called with a total of 100; False cancels with
        `ParaViewExportCancelled` and leaves every earlier build as it was. Synchronous."""
        ids = list(dict.fromkeys(feature_ids))
        if not ids:
            return []
        records = [self._record(i) for i in ids]
        grids = {r.grid_id for r in records}
        if len(grids) > 1:
            raise ValueError(MULTI_GRID_REFUSAL)
        everyone = self.layers.members_by_feature()
        members = {r.feature_id: everyone.get(r.feature_id, []) for r in records}
        # A surface left with too few picks is skipped and reported, so it never blocks the
        # others of its grid; when none can be built, the first refusal is the error.
        self.refused = []
        buildable = []
        for record in records:
            text = rebuild_refusal(record.name, len(members[record.feature_id]))
            if text:
                self.refused.append(text)
            else:
                buildable.append(record)
        if not buildable:
            raise ValueError(self.refused[0])
        records = buildable
        export = self._export()
        grid_id = records[0].grid_id
        folder = self.folder(grid_id)
        made: list[Path] = []
        self.building += 1
        try:
            choice, results = self._compute(export, grid_id, records, members, progress)
            # One snapshot, taken after the choice is remembered; `_write` reads nothing else.
            inputs = {r.feature_id: self.inputs(r.feature_id) for r in records}
            folder.mkdir(parents=True, exist_ok=True)
            reports = [
                self._write(folder, r, results[r.feature_id], choice, inputs[r.feature_id], made)
                for r in records
            ]
            # The jsons last: a build is complete exactly when its json names its files.
            out = []
            for record, report in zip(records, reports):
                part = folder / f"{record.feature_id}.json.part"
                made.append(part)
                part.write_text(json.dumps(report, indent=2), encoding="utf-8")
                os.replace(part, self._json_path(record))
                made.remove(part)
                # This record is complete: a later record's failure must not delete its files.
                for name in report["files"].values():
                    made.remove(folder / name)
                out.append(
                    BuildReport(
                        record.feature_id,
                        record.name,
                        report,
                        tuple(folder / n for n in report["files"].values()),
                    )
                )
        except BaseException as exc:
            # The traceback keeps the kept fill's memory map alive (see ParaViewExport.run).
            traceback.clear_frames(exc.__traceback__)
            for path in made:
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)
            raise
        finally:
            self.building -= 1
        return out

    def _compute(
        self,
        export: ParaViewExport,
        grid_id: str,
        records: list[FeatureRecord],
        members: dict[str, list[PickRow]],
        progress: Callable[[int, int], bool],
    ) -> tuple[Any, dict[str, dict[str, Any]]]:
        """Fill, volume and the core builder for each record, in memory; nothing is written.
        Returns the choice the build used (remembered, with its depth) and each result."""
        choice = export.defaults(grid_id)
        # The export dialog shows the depth step to four decimals, so an untouched dialog writes
        # that back: build with it, or the next export would call the surface stale (R11).
        if round(choice.dz_ns, 4) > 0.0:
            choice = replace(choice, dz_ns=round(choice.dz_ns, 4))

        def report(done: float) -> None:
            if not progress(int(done), 100):
                raise ParaViewExportCancelled("build cancelled")

        def fill_progress(done: int, total: int) -> bool:
            report(_FILL_SHARE * done / max(1, total))
            return True

        got = export.fill(grid_id, choice, progress=fill_progress)
        # Remember the choice with the depth the fill actually reached, as an explicit number
        # (rounded up, so the next fill is clipped at nothing it was not clipped at now): the
        # Slices panel's z1 never reaches a surface (R10).
        end = math.ceil(got.t1_ns * 1e4 - 1e-6) / 1e4
        end = round(end, 4)
        if end < got.t1_ns:
            end = round(end + 1e-4, 4)
        choice = replace(choice, t1_ns=end)
        window = max(1, int(round(choice.settings.period_ns / got.z.dz_ns)))
        vol = surface_volume(
            got.filled,
            got.z,
            got.velocity,
            choice.cell,
            choice.settings,
            slab_levels=_slab_levels(got.frame.n_cells, window),
            progress=lambda done, n: (
                report(_FILL_SHARE + (_VOLUME_SHARE - _FILL_SHARE) * done / max(1, n)) or True
            ),
        )
        prepared = {line.key for line in got.lines}
        out: dict[str, dict[str, Any]] = {}
        for k, record in enumerate(records):
            rows = [(r.pick.line_key, r.pick) for r in members[record.feature_id]]
            placed = place_picks(rows, got.lines, got.prov, got.frame, got.velocity)
            used: list[tuple[Any, Any]] = []
            skipped: list[dict[str, str]] = []
            for (key, pick), spot in zip(rows, placed):
                if spot is None:
                    why = WHY_NO_LINE if key not in prepared else WHY_NO_DEPTH
                elif not (math.isfinite(spot.x_m) and math.isfinite(spot.y_m)):
                    why = WHY_NO_POSITION
                else:
                    used.append((pick, spot))
                    continue
                skipped.append({"line_key": key, "why": why})
            text = skipped_refusal(record.name, len(used), skipped)
            if text:
                raise ValueError(text)
            try:
                surface = build_surface(
                    vol,
                    np.array([s.x_m for _, s in used]),
                    np.array([s.y_m for _, s in used]),
                    np.array([s.depth_m for _, s in used]),
                    record.settings,
                )
            except ValueError as exc:
                raise ValueError(f"“{record.name}”: {exc}") from exc
            out[record.feature_id] = {
                "surface": surface,
                "used": used,
                "skipped": skipped,
                "frame": got.frame,
            }
            report(_VOLUME_SHARE + (100 - _VOLUME_SHARE) * (k + 1) / len(records))
        del vol, got
        # Remembered last: a build that is refused or cancelled leaves the grid's choice alone.
        self.session.remember_volume(grid_id, **choice.to_record())
        return choice, out

    def line_label(self, key: str) -> str:
        line = self.session.line_for_key(key)
        return str(getattr(line.placement, "label", None) or line.path.stem)

    def _write(
        self,
        folder: Path,
        record: FeatureRecord,
        result: dict[str, Any],
        choice: Any,
        inputs: dict[str, str],
        made: list[Path],
    ) -> dict[str, Any]:
        """Write one surface's three files (each `.part`, then renamed; every path is added
        to `made` so a failure can remove them) and return its json document."""
        surface, frame = result["surface"], result["frame"]
        key = uuid.uuid4().hex[:8]
        names = {kind: f"{record.feature_id}-{key}.{kind}" for kind in ("npz", "2dm", "dat")}
        points, triangles, _cells = surface_mesh(surface.depth_m, surface.cell)
        x_hat, y_hat = frame.axes()
        origin = np.asarray(frame.origin, dtype=float)
        world = origin + points[:, :1] * x_hat + points[:, 1:2] * y_hat
        texts = {
            "2dm": mesh_2dm(world, -points[:, 2], triangles),
            "dat": mesh_dat(points[:, 2], len(triangles)),
        }

        def write(kind: str, put: Callable[[Any], None], binary: bool) -> None:
            final = folder / names[kind]
            part = final.with_name(final.name + ".part")
            made.append(part)
            with open(
                part, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})
            ) as f:
                put(f)
            os.replace(part, final)
            made.remove(part)
            made.append(final)

        write(
            "npz",
            lambda f: np.savez(
                f,
                depth_m=surface.depth_m,
                strength=surface.strength,
                cell=np.float64(surface.cell),
                origin=origin,
                azimuth=np.float64(frame.azimuth),
                crs=np.array(str(frame.crs)),
            ),
            True,
        )
        write("2dm", lambda f: f.write(texts["2dm"]), False)
        write("dat", lambda f: f.write(texts["dat"]), False)
        fit = surface.fit
        outliers = []
        for o in fit.outliers:
            pick, spot = result["used"][o.index]
            outliers.append(
                {
                    "line_key": spot.line_key,
                    "label": self.line_label(spot.line_key),
                    "distance_m": pick.distance_m,
                    "trace": pick.trace,
                    "time_ns": pick.time_ns,
                    "picked_m": o.picked_m,
                    "surface_m": o.surface_m,
                    "reason": o.reason,
                }
            )
        return {
            "feature_id": record.feature_id,
            "name": record.name,
            "grid": record.grid_id,
            "kind": record.kind,
            "built_utc": now_iso(),
            "nsgeo_version": nsgeo.__version__,
            "inputs": inputs,
            "resolution": {"cell": choice.cell, "dz_ns": choice.dz_ns},
            "settings": record.settings.to_dict(),
            "offset_m": float(surface.offset_m),
            "offset_votes": int(surface.offset_votes),
            "offset_at_limit": int(surface.offset_at_limit),
            "offset_reliable": bool(surface.offset_reliable),
            "fit": {
                "picks": len(result["used"]),
                "within_2cm": fit.within_close,
                "within_5cm": fit.within_near,
                "further": fit.further,
                "at_edge": fit.at_edge,
                "on_holes": fit.on_holes,
            },
            "outliers": outliers,
            "skipped": result["skipped"],
            "cells": int(np.isfinite(surface.depth_m).sum()),
            "region_cells": int(surface.region.sum()),
            "files": names,
        }
