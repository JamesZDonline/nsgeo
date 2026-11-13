"""Export one grid for ParaView: the prepared volume at its own 3-D resolution (M16 A).

`ParaViewExport.run` writes `<site>/paraview/<grid>/` and nothing else. It never
touches what the Slices panel shows or holds (spec call 2):

* The lines come from the panel's engine only when it is already prepared on the same
  source (read, never changed). Otherwise a standalone `SliceEngine` prepares them, and
  only when neither the panel's grid engine nor the site engine has a task alive, because
  two real preparations at once segfault (`slices_engine.py`, lines 86-111).
* The cube is binned here, at the 3-D cell and depth step, and never promoted into the
  panel's engine. Its fill is written level by level to a memory-mapped file in
  `<site>/paraview/.cache/`, so it never sits in memory beside the cube and a second
  export that changes only the stretch, or the blur, reuses it.
* Everything is written to `<grid>.partial` and swapped in at the end, so a cancelled or
  failed export leaves the previous one whole.

No Qt widgets here: the dialog (Task 4) calls `estimate` as its settings change and
`run` on its button.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import traceback
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nsgeo
import numpy as np
from nsgeo.processing import (
    TIME_BASE_TIME_ZERO,
    Radargram,
    StepStack,
    retime_ns,
    sets_time_zero,
    time_base_of,
)
from nsgeo.slices import (
    CubeFrame,
    PreparedLine,
    VolumeStopped,
    ZAxis,
    build_cube,
    fill_levels,
    plan_fill,
    plan_line,
    prepare_volume,
    surface_mesh,
)
from nsgeo.vtkxml import write_image_data, write_poly_data
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)
from qgis.PyQt.QtCore import QEventLoop

from nsgeo_qgis.paraview_scene import (
    ExportSummary,
    export_refusal,
    fill_refusal,
    in_use_message,
    scene_record,
    scene_title,
    shallow_t1_message,
    write_scene_files,
)
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import (
    MAX_FRAME_CELLS,
    SliceFinish,
    SourceChoice,
    VolumeChoice,
    default_cell,
    export_size_bytes,
    frame_cells,
    smallest_safe_cell,
    too_fine_for_export,
    volume_choice,
)
from nsgeo_qgis.ui.site_scope import default_preset, source_keys, transform_value

#: The most points a line takes in lines.vtp.
MAX_LINE_POINTS = 200

#: How many amplitudes a slab adds to the sample the colour range is read from.
_RANGE_SAMPLE = 20_000

#: Working-set target for one slab: (slab levels + RMS window) x cells.
_SLAB_ELEMENTS = 16_000_000

_BUSY = (
    "Slices are still preparing; wait for them to finish, then export again "
    "(two preparations at once are not safe)."
)


class ParaViewExportCancelled(Exception):
    """The progress callback returned False; nothing of this export was kept."""


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def paraview_folder(session: Any, grid_id: str) -> Path:
    """Where a grid's export goes: `<site>/paraview/<grid>`."""
    return Path(session.root) / "paraview" / _safe(grid_id)


def _depth_levels(z: ZAxis) -> int:
    """How many levels of `z` lie at or after time zero: the volume's depth levels."""
    return int(np.count_nonzero(z.times_ns() >= -1e-9))


def _lines_range(lines: Sequence[PreparedLine]) -> tuple[float, float]:
    """The two-way time range every line covers (as `SliceEngine.prepared_z_bounds`)."""
    t0 = max(line.t0_ns for line in lines)
    t1 = min(line.t0_ns + (line.data.shape[0] - 1) * line.dt_ns for line in lines)
    if not t1 > t0:
        raise ValueError("the lines share no time range, so there is nothing to export")
    return t0, t1


def _clip(t0: float, t1: float, choice: VolumeChoice) -> tuple[float, float]:
    """The range with its end at the choice's deepest time when that is earlier; a ValueError,
    in words, when that leaves nothing after the range's start."""
    if choice.t1_ns is None:
        return t0, t1
    clipped = min(t1, choice.t1_ns)
    if not clipped > t0:
        raise ValueError(shallow_t1_message(choice.t1_ns, choice.dz_ns))
    return t0, clipped


def _levels(t0: float, t1: float, choice: VolumeChoice) -> tuple[ZAxis, int]:
    """The depth axis of the range and its levels at or after time zero (at least two)."""
    z = ZAxis.from_range(t0, t1, choice.dz_ns)
    nd = _depth_levels(z)
    if nd < 2:
        if choice.t1_ns is not None:
            raise ValueError(shallow_t1_message(choice.t1_ns, choice.dz_ns))
        raise ValueError("the lines have no depth range to export")
    return z, nd


def _effective_t1(choice: VolumeChoice, record_end: float) -> float | None:
    """The deepest time as it affects the fill: None when it reaches the record's end."""
    t1 = choice.t1_ns
    return None if t1 is None or t1 >= record_end - 1e-6 else round(t1, 6)


_HEX16 = "[0-9a-f]{16}"


def _cache_name(grid_id: str, settings_key: str, full_key: str) -> str:
    return f"{_safe(grid_id)}-{settings_key}-{full_key}.npy"


def _cache_files(cache_dir: Path, grid_id: str, suffix: str = ".npy") -> list[Path]:
    """This grid's cache files (or, with suffix ".npy.part", its unfinished ones) and no
    other grid's (`A` must not match `A-2`)."""
    if not cache_dir.is_dir():
        return []
    pattern = re.compile(rf"{re.escape(_safe(grid_id))}-{_HEX16}-{_HEX16}{re.escape(suffix)}")
    return sorted(f for f in cache_dir.iterdir() if pattern.fullmatch(f.name))


def _npy_bytes(shape: tuple[int, int, int]) -> int:
    """A float32 .npy of `shape` on disk: the data and the 128-byte header."""
    return 128 + 4 * shape[0] * shape[1] * shape[2]


def _slab_levels(cells: int, window: int) -> int:
    return int(min(64, max(4, _SLAB_ELEMENTS // max(1, cells) - window)))


def _spans(n: int, step: int) -> list[tuple[int, int]]:
    return [(j, min(j + step, n)) for j in range(0, n, step)]


@dataclass(frozen=True)
class FilledGrid:
    """A grid's prepared lines and its kept, filled cube (M16 B): what `ParaViewExport.fill` hands
    to the export and to surface builds. `filled` is a read-only memory map, `(nz, ny, nx)`."""

    lines: list[PreparedLine]
    prov: Any
    frame: CubeFrame
    z: ZAxis
    velocity: Any
    filled: np.ndarray
    skipped_lines: list[str]
    #: Where the fill's depth axis ends, in ns on the cube's clock (the lines' end, or earlier).
    t1_ns: float


@dataclass(frozen=True)
class PlacedPick:
    """A pick on the cube: its line, its (clamped) trace, frame-local metres and true depth."""

    line_key: str
    trace: int
    x_m: float
    y_m: float
    depth_m: float


def place_picks(
    rows: Sequence[tuple[str, Any]],
    lines: Sequence[PreparedLine],
    prov: Any,
    frame: CubeFrame,
    velocity: Any,
) -> list[PlacedPick | None]:
    """Each `(line_key, pick)` of `rows` on the cube's clock, in order. A pick whose line is not
    among `lines`, or whose depth is not finite, is None."""
    on_zero = time_base_of(prov.steps) == TIME_BASE_TIME_ZERO
    by_key = {line.key: line for line in lines}
    found: list[tuple[int, PreparedLine, int, float]] = []
    for i, (key, p) in enumerate(rows):
        line = by_key.get(key)
        if line is None:
            continue
        target = line.zero_ns if on_zero else 0.0
        trace = min(max(int(p.trace), 0), line.coords.shape[0] - 1)
        found.append((i, line, trace, float(retime_ns(p.time_ns, p.zero_ns or 0.0, target))))
    out: list[PlacedPick | None] = [None] * len(rows)
    if not found:
        return out
    depth = np.asarray(
        velocity.depth_at(np.asarray([f[3] for f in found], dtype=float)), dtype=float
    )
    for (i, line, trace, _), d in zip(found, depth):
        if not math.isfinite(float(d)):
            continue
        x, y = frame.to_local(line.coords[trace : trace + 1])[0]
        out[i] = PlacedPick(line.key, trace, float(x), float(y), float(d))
    return out


class ParaViewExport:
    """Writes a grid's ParaView folder. `dock` is the Slices dock (read only). `surfaces` (a
    `Surfaces`) puts the grid's built surfaces in features.vtp; without it that file is empty."""

    def __init__(self, session: Any, dock: Any, surfaces: Any = None) -> None:
        self.session = session
        self.dock = dock
        self.surfaces = surfaces
        self._zero_probes: dict[tuple[str, str], float] = {}
        # picks_for scans every pick of the site, so a grid's count is read once for as long
        # as this object lives (the dialog's lifetime).
        self._pick_counts: dict[str, int] = {}
        #: Lines of the last `run` that could not be prepared and so are not in its export.
        self.skipped_lines: list[str] = []
        #: Surfaces of the last `run` left out of features.vtp (their CRS cannot be reached).
        self.skipped_surfaces: list[str] = []

    # ---- settings ----------------------------------------------------------
    def defaults(self, grid_id: str) -> VolumeChoice:
        """The grid's 3-D choice: its record, with the Slices panel's values filling gaps."""
        grid = self.session.grid(grid_id)
        resolution = self.session.slice_resolution(grid_id)
        cell = resolution.get("cell")
        if not isinstance(cell, float) or not cell > 0.0:
            floor = max(0.01, smallest_safe_cell(grid.size_x, grid.size_y))
            cell = default_cell(grid.default_spacing, floor)
        dz = resolution.get("dz_ns")
        if not isinstance(dz, float) or not dz > 0.0:
            keys = source_keys(self.session, grid_id)
            if not keys:
                raise ValueError(f"grid {grid_id!r} has no lines to export")
            dz = float(self.session.line_for_key(keys[0]).header.dt_ns)
        t1 = resolution.get("t1_ns")
        return volume_choice(
            self.session.volume_record(grid_id),
            cell_default=float(cell),
            dz_default=float(dz),
            transform_default=transform_value(self.dock.transform_combo.value()),
            t1_default=t1 if isinstance(t1, float) and t1 > 0.0 else None,
        )

    def _source(self, grid_id: str, choice: VolumeChoice) -> SourceChoice:
        preset = default_preset(self.session, grid_id)
        if preset is None:
            raise ValueError(
                "this site has no processing preset yet; save one in Processing, then export"
            )
        keys = source_keys(self.session, grid_id)
        if not keys:
            raise ValueError(f"grid {grid_id!r} has no lines to export")
        return SourceChoice(grid_id, preset, choice.transform, keys)

    def source_choice(self, grid_id: str, choice: VolumeChoice) -> SourceChoice:
        """What the grid's cube is made from (preset, transform, lines); prepares nothing."""
        return self._source(grid_id, choice)

    def fill_settings(self, grid_id: str) -> Any:
        """The grid's fill: method, max distance, search radius and smoothing."""
        return self._finish(grid_id)

    def _frame(self, grid_id: str, choice: VolumeChoice) -> CubeFrame:
        grid = self.session.grid(grid_id)
        cells = frame_cells(grid.size_x, grid.size_y, choice.cell)
        if cells > MAX_FRAME_CELLS:
            safe = smallest_safe_cell(grid.size_x, grid.size_y)
            raise ValueError(too_fine_for_export(choice.cell, grid_id, cells, safe))
        return CubeFrame.for_grid(grid, choice.cell)

    # ---- the size, before anything is prepared ----------------------------
    def estimate(self, grid_id: str, choice: VolumeChoice) -> int:
        """About how many bytes `cube.vti` will take. Cheap, and prepares nothing: it reads
        the panel's engine when that matches, else the first line's header and, for a preset
        that sets time zero, a probe of where that first line's zero falls."""
        frame = self._frame(grid_id, choice)
        source = self._source(grid_id, choice)
        t0, t1 = self._time_range(source, choice)
        _z, nd = _levels(t0, t1, choice)
        return export_size_bytes(frame.nx, frame.ny, nd)

    def panel_values(self, grid_id: str) -> tuple[float | None, float, float | None]:
        """`(the Slices panel's cell for this grid or None, the files' own depth step in ns,
        where the record ends in ns or None)`: what the dialog's hints show beside the 3-D
        cell and depth step, and the reach of "Down to"."""
        cell = self.session.slice_resolution(grid_id).get("cell")
        keys = source_keys(self.session, grid_id)
        if not keys:
            raise ValueError(f"grid {grid_id!r} has no lines to export")
        dt = float(self.session.line_for_key(keys[0]).header.dt_ns)
        try:
            end: float | None = self._record_range(self._source(grid_id, self.defaults(grid_id)))[1]
        except ValueError:
            end = None  # no preset or no shared range: the summary says so
        return (float(cell) if isinstance(cell, float) and cell > 0.0 else None), dt, end

    def summary(self, grid_id: str, choice: VolumeChoice) -> ExportSummary:
        """What an export of `choice` would write and what the disk offers. Cheap (as
        `estimate` and `cache_bytes`, which it uses) and prepares nothing, so a dialog can
        call it on every edit. Raises the same ValueError as `estimate` for a cell that is
        too fine, or a grid that cannot be exported."""
        frame = self._frame(grid_id, choice)
        source = self._source(grid_id, choice)
        t0, t1 = self._time_range(source, choice)
        _z, nd = _levels(t0, t1, choice)
        velocity = self.session.resolved_velocity(source.line_keys[0])
        max_depth = float(velocity.depth_at(np.asarray([t1], dtype=float))[0])
        folder = paraview_folder(self.session, grid_id)
        if grid_id not in self._pick_counts:
            self._pick_counts[grid_id] = sum(
                len(self.session.picks_for(k)) for k in source.line_keys
            )
        n_picks = self._pick_counts[grid_id]
        states = self._surface_states(grid_id)
        return ExportSummary(
            folder=folder,
            replaces=folder.is_dir(),
            nx=frame.nx,
            ny=frame.ny,
            nd=nd,
            max_depth_m=max_depth,
            fill_method=str(self._finish(grid_id).method),
            n_picks=n_picks,
            n_lines=len(source.line_keys),
            n_surfaces=len(states),
            n_stale_surfaces=sum(1 for st in states if st.stale),
            export_bytes=self.estimate(grid_id, choice),
            cache_bytes=self.cache_bytes(grid_id, choice),
            free_bytes=int(shutil.disk_usage(Path(self.session.root)).free),
        )

    def _surface_states(self, grid_id: str) -> list[Any]:
        """The state of each built surface of the grid, in the surfaces' order."""
        if self.surfaces is None:
            return []
        out = []
        for record in self.surfaces.records():
            if record.grid_id == grid_id:
                state = self.surfaces.state(record.feature_id)
                if state.built and self.surfaces.built(record.feature_id) is not None:
                    out.append(state)
        return out

    def cache_bytes(self, grid_id: str, choice: VolumeChoice) -> int:
        """The bytes the fill cache will add: 0 when this grid's cache for these settings is
        already on disk. Cheap, like `estimate`: with the panel's lines the key is exact;
        without them a cache file of the grid with the shape this export needs counts."""
        frame = self._frame(grid_id, choice)
        source = self._source(grid_id, choice)
        t0, t1 = self._time_range(source, choice)
        shape = (_levels(t0, t1, choice)[0].nz, frame.ny, frame.nx)
        cache_dir = paraview_folder(self.session, grid_id).parent / ".cache"
        found = _cache_files(cache_dir, grid_id)
        full = _npy_bytes(shape)
        skey = self._settings_key(
            source, choice, self._finish(grid_id), frame, self._record_range(source)[1]
        )
        engine = self._panel_engine(source)
        if engine is not None:
            # The exact name is known from the panel's prepared lines.
            lines = list(engine.prepared_lines())
            full_key = self._cache_key(
                lines, engine.provenance(), choice, t0, t1, self._finish(grid_id), frame
            )
            name = _cache_name(grid_id, skey, full_key)
            return 0 if any(f.name == name for f in found) else full
        # Without prepared lines only the settings are known: a file made from these settings
        # and this shape is this run's cache. Anything else, the run writes anew.
        for f in found:
            if f.name.startswith(f"{_safe(grid_id)}-{skey}-"):
                with contextlib.suppress(Exception):
                    if np.lib.format.open_memmap(f, mode="r").shape == shape:
                        return 0
        return full

    def _finish(self, grid_id: str) -> Any:
        grid = self.session.grid(grid_id)
        return (
            SliceFinish()
            .updated(self.session.slice_resolution(grid_id))
            .in_metres(grid.default_spacing)
        )

    def _panel_engine(self, source: SourceChoice) -> SliceEngine | None:
        engine = self.dock.engine
        if source.same_source(engine.choice) and engine.is_prepared and not engine.has_live_task:
            return engine  # type: ignore[no-any-return]
        return None

    def _time_range(self, source: SourceChoice, t1_ns: float | None = None) -> tuple[float, float]:
        """The range the lines share, its end clipped to `t1_ns` (the export's "Down to")."""
        t0, t1 = self._record_range(source)
        return _clip(t0, t1, t1_ns)

    def _record_range(self, source: SourceChoice) -> tuple[float, float]:
        engine = self._panel_engine(source)
        bounds = engine.prepared_z_bounds() if engine is not None else None
        if bounds is not None:
            return bounds
        steps = list(self.session.site.presets.get(source.preset, []))
        zero = 0.0
        if sets_time_zero(steps):
            zero = self._zero_of(source.line_keys[0], steps)
        t0, t1 = -math.inf, math.inf
        for key in source.line_keys:
            h = self.session.line_for_key(key).header
            t0 = max(t0, h.position_ns)
            t1 = min(t1, h.position_ns + (h.n_samples - 1) * h.dt_ns)
        if sets_time_zero(steps):
            # The preset moves the clock to the first break and crops what comes before it.
            t0, t1 = 0.0, t1 - zero
        if not t1 > t0:
            raise ValueError("the lines share no time range, so there is nothing to export")
        return t0, t1

    def _zero_of(self, key: str, steps: Sequence[dict[str, Any]]) -> float:
        """Where the preset puts time zero on one line: one read of one file, kept."""
        memo = (key, json.dumps(list(steps), sort_keys=True, default=str))
        if memo not in self._zero_probes:
            stack = StepStack.from_dicts([dict(s) for s in steps])
            profiles = self.session.line_for_key(key).load()
            stack.source = Radargram.from_profile(profiles[self.session.channel(key)])
            self._zero_probes[memo] = float(stack.zero_ns())
        return self._zero_probes[memo]

    # ---- the lines ----------------------------------------------------------
    def _prepared(self, source: SourceChoice) -> tuple[list[PreparedLine], Any]:
        """`(lines, provenance)` for `source`: the panel's, or a standalone engine's."""
        engine = self._panel_engine(source)
        if engine is not None:
            return list(engine.prepared_lines()), engine.provenance()
        if (
            self.dock.engine.has_live_task
            or self.dock.site_engine.has_live_task
            or self.dock.site_engine.is_running
            or self.dock.foreign_preparing
        ):
            raise RuntimeError(_BUSY)
        errors: list[str] = []
        own = SliceEngine(self.session, on_error=errors.append)
        # Registered with the dock for the whole preparation, so neither of its engines can
        # start one beside it; and the wait takes no user input, so nothing re-enters.
        with self.dock.foreign_preparation(own):
            try:
                own.set_source(source)
                if not own.wait_for_preparation(
                    timeout_ms=600_000, flags=QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
                ):
                    raise RuntimeError("preparing the lines took too long")
                lines = list(own.prepared_lines())
                if not lines:
                    detail = f": {'; '.join(errors)}" if errors else ""
                    raise RuntimeError(f"no lines could be prepared{detail}")
                return lines, own.provenance()
            finally:
                own.dispose()

    # ---- the fill ------------------------------------------------------------
    def fill(
        self, grid_id: str, choice: VolumeChoice, *, progress: Callable[[int, int], bool]
    ) -> FilledGrid:
        """The grid's prepared lines and its filled cube at `choice`, kept as a memory-mapped
        file in `<site>/paraview/.cache/` (the export's own cache: an export and a surface
        build of one grid and choice share it). `progress(done, total)` counts the fill's
        levels; False cancels (ParaViewExportCancelled) and keeps nothing of this fill."""
        state = {"done": 0, "total": 0}

        def announce(frame: CubeFrame, z: ZAxis) -> None:
            state["total"] = z.nz

        def step(n: int = 1) -> None:
            state["done"] += n
            if not progress(state["done"], state["total"]):
                raise ParaViewExportCancelled("cancelled")

        try:
            return self._fill_grid(grid_id, choice, step, announce)
        except BaseException as exc:
            traceback.clear_frames(exc.__traceback__)  # see `run`: a mapped file cannot be deleted
            raise

    def _fill_grid(
        self,
        grid_id: str,
        choice: VolumeChoice,
        step: Callable[[int], None],
        announce: Callable[[CubeFrame, ZAxis], None],
    ) -> FilledGrid:
        """Everything `run` does before the volume: the frame and source checks, the sweep of
        unfinished cache files, the lines, the fill (or the kept one) and its opened map.
        `announce(frame, z)` is called once the depth axis is known, before any `step`."""
        frame = self._frame(grid_id, choice)  # before anything is prepared or written
        source = self._source(grid_id, choice)
        folder = paraview_folder(self.session, grid_id)
        # What a crash or a full disk left of this grid's fill: nothing else reads it.
        for stale in _cache_files(folder.parent / ".cache", grid_id, ".npy.part"):
            with contextlib.suppress(OSError):
                stale.unlink()
        lines, prov = self._prepared(source)
        got = {line.key for line in lines}
        self.skipped_lines = sorted(k for k in source.line_keys if k not in got)
        t0, record_end = _lines_range(lines)
        t0, t1 = _clip(t0, record_end, choice)
        z, _nd = _levels(t0, t1, choice)
        finish = self._finish(grid_id)
        velocity = self.session.resolved_velocity(lines[0].key)
        announce(frame, z)
        cache_dir = folder.parent / ".cache"
        cache_part: Path | None = None
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            skey = self._settings_key(source, choice, finish, frame, record_end)
            key = self._cache_key(lines, prov, choice, t0, t1, finish, frame)
            cache = cache_dir / _cache_name(grid_id, skey, key)
            shape = (z.nz, frame.ny, frame.nx)
            if cache.exists():
                step(z.nz)
            else:
                # The cache is a sparse, memory-mapped file: a disk that fills under it ends the
                # program (SIGBUS), so refuse before it exists rather than fail in it.
                reason = fill_refusal(_npy_bytes(shape), shutil.disk_usage(cache_dir).free)
                if reason:
                    raise ValueError(reason)
                cache_part = cache.with_name(cache.name + ".part")
                self._fill(lines, prov, frame, z, finish, shape, cache_part, step)
                os.replace(cache_part, cache)
                cache_part = None
                for old in _cache_files(cache_dir, grid_id):
                    if old != cache:
                        old.unlink(missing_ok=True)
            filled = np.lib.format.open_memmap(cache, mode="r")
        except BaseException as exc:
            # As `run` does: let go of the frames (and the map they hold) before deleting.
            traceback.clear_frames(exc.__traceback__)
            if cache_part is not None:
                with contextlib.suppress(OSError):
                    cache_part.unlink(missing_ok=True)
            raise
        return FilledGrid(lines, prov, frame, z, velocity, filled, list(self.skipped_lines), t1)

    # ---- the run -------------------------------------------------------------
    def run(
        self,
        grid_id: str,
        choice: VolumeChoice,
        *,
        progress: Callable[[int, int], bool],
        paraview_path: str = "",
    ) -> Path:
        """Write the grid's folder and return it. `progress(done, total)` counts the fill
        levels, the volume's trend slabs and the written slabs; False cancels
        (ParaViewExportCancelled) and leaves any earlier export as it was."""
        grid = self.session.grid(grid_id)
        folder = paraview_folder(self.session, grid_id)
        cache_dir = folder.parent / ".cache"
        partial = folder.with_name(folder.name + ".partial")
        state = {"done": 0, "total": 0}
        spans: list[tuple[int, int]] = []

        def step(n: int = 1) -> None:
            state["done"] += n
            if not progress(state["done"], state["total"]):
                raise ParaViewExportCancelled("export cancelled")

        def tick_trend() -> bool:
            step()
            return True

        def announce(frame: CubeFrame, z: ZAxis) -> None:
            window = max(1, int(round(choice.settings.period_ns / z.dz_ns)))
            spans.extend(_spans(_depth_levels(z), _slab_levels(frame.n_cells, window)))
            state["total"] = z.nz + 3 * len(spans)

        try:
            got = self._fill_grid(grid_id, choice, step, announce)
            frame, z = got.frame, got.z
            lines, prov, velocity, filled = got.lines, got.prov, got.velocity, got.filled
            nd = _depth_levels(z)
            finish = self._finish(grid_id)
            window = max(1, int(round(choice.settings.period_ns / z.dz_ns)))
            slab = _slab_levels(frame.n_cells, window)
            vol = prepare_volume(
                filled,
                z,
                velocity,
                choice.cell,
                choice.settings,
                slab_levels=slab,
                progress=lambda done, n: tick_trend(),
            )
            reason = export_refusal(
                export_size_bytes(frame.nx, frame.ny, nd), shutil.disk_usage(cache_dir).free
            )
            if reason:
                raise ValueError(reason)
            if partial.exists():
                shutil.rmtree(partial)
            partial.mkdir(parents=True)
            amp_p99 = self._write_cube(partial, vol, frame, choice, spans, step)
            features = self._write_features(partial, grid_id, frame, choice)
            n_picks = self._write_picks(
                partial,
                lines,
                prov,
                frame,
                choice,
                velocity,
                {f["feature_id"]: f["index"] for f in features},
            )
            features = [{k: v for k, v in f.items() if k != "feature_id"} for f in features]
            self._write_lines(partial, lines, frame, grid)
            record = self._record(
                grid, grid_id, choice, frame, lines, prov, finish, vol, amp_p99, n_picks, features
            )
            record["skipped_lines"] = list(self.skipped_lines)
            write_scene_files(partial, record, paraview_path)
            self._swap(partial, folder)
        except BaseException as exc:
            # The traceback keeps the finished fill's frames, and with them its memory map,
            # alive; Windows will not delete a file that is mapped. Let go of them first,
            # and never let a failed delete replace the cancel or the error being raised
            # (the next run deletes what is left).
            traceback.clear_frames(exc.__traceback__)
            shutil.rmtree(partial, ignore_errors=True)
            if isinstance(exc, VolumeStopped):
                raise ParaViewExportCancelled(str(exc)) from exc
            raise
        return folder

    # ---- the pieces ----------------------------------------------------------
    def _settings_key(
        self,
        source: SourceChoice,
        choice: VolumeChoice,
        finish: Any,
        frame: CubeFrame,
        record_end: float,
    ) -> str:
        """The part of a cache's name that is known without preparing any line: the lines and
        where they are placed, the preset, transform, cell, depth step, finish and frame, and the
        nsgeo version. `_cache_key` adds to this only what comes from prepared lines (their
        data shape, dt, t0, zero and coordinates, and the shared time range t0..t1); every
        other input of it is here, so a name that matches on this part alone cannot be stale
        for any reason `cache_bytes` could see."""
        doc = {
            "nsgeo": nsgeo.__version__,
            "lines": [
                [k, repr(self.session.line_for_key(k).placement)] for k in sorted(source.line_keys)
            ],
            "steps": list(self.session.site.presets.get(source.preset, [])),
            "transform": choice.transform,
            "cell": choice.cell,
            "dz_ns": choice.dz_ns,
            "t1_ns": _effective_t1(choice, record_end),
            "finish": [
                finish.method,
                finish.max_distance_m,
                finish.search_radius_m,
                finish.smooth_x_m,
                finish.smooth_y_m,
            ],
            "frame": [list(frame.origin), frame.azimuth, frame.cell, frame.nx, frame.ny],
        }
        return hashlib.sha1(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()[:16]

    @staticmethod
    def _cache_key(
        lines: Sequence[PreparedLine],
        prov: Any,
        choice: VolumeChoice,
        t0: float,
        t1: float,
        finish: Any,
        frame: CubeFrame,
    ) -> str:
        per_line = [
            [
                line.key,
                list(line.data.shape),
                line.dt_ns,
                line.t0_ns,
                line.zero_ns,
                hashlib.sha1(np.ascontiguousarray(line.coords).tobytes()).hexdigest(),
            ]
            for line in sorted(lines, key=lambda ln: ln.key)
        ]
        doc = {
            "nsgeo": nsgeo.__version__,
            "lines": per_line,
            "steps": list(prov.steps),
            "transform": choice.transform,
            "cell": choice.cell,
            "dz_ns": choice.dz_ns,
            "t0": t0,
            "t1": t1,
            "finish": [
                finish.method,
                finish.max_distance_m,
                finish.search_radius_m,
                finish.smooth_x_m,
                finish.smooth_y_m,
            ],
            "frame": [list(frame.origin), frame.azimuth, frame.cell, frame.nx, frame.ny],
        }
        text = json.dumps(doc, sort_keys=True, default=str)
        return hashlib.sha1(text.encode()).hexdigest()[:16]

    @staticmethod
    def _fill(
        lines: Sequence[PreparedLine],
        prov: Any,
        frame: CubeFrame,
        z: ZAxis,
        finish: Any,
        shape: tuple[int, int, int],
        part: Path,
        step: Callable[[int], None],
    ) -> None:
        plans = [plan_line(line, frame, z) for line in lines]
        cube = build_cube(lines, plans, frame, z, prov)
        weights = plan_fill(
            cube.coverage() > 0,
            frame.cell,
            finish.method,
            finish.max_distance_m,
            finish.search_radius_m,
        )
        out = np.lib.format.open_memmap(part, mode="w+", dtype=np.float32, shape=shape)
        done = {"n": 0}

        def tick(k: int, nz: int) -> bool:
            step(k - done["n"])
            done["n"] = k
            return True

        try:
            fill_levels(cube, weights, finish, out, progress=tick)
            out.flush()
        finally:
            del out

    @staticmethod
    def _write_cube(
        folder: Path,
        vol: Any,
        frame: CubeFrame,
        choice: VolumeChoice,
        spans: list[tuple[int, int]],
        step: Callable[[int], None],
    ) -> float:
        """cube.vti, deepest slab first: strength, then amplitude (each recomputed per slab,
        nothing held on disk beside the file), then true depth. Returns the amplitude's p99."""
        nd = vol.depths_m.size
        ny, nx = frame.ny, frame.nx
        depths = vol.depths_m.astype(np.float32)
        max_depth = float(vol.depths_m[-1])
        depth_step = float(vol.depths_m[1] - vol.depths_m[0])
        s = choice.stretch
        samples: list[np.ndarray] = []
        covered = vol.covered

        def strength_pass() -> Iterator[np.ndarray]:
            for j0, j1 in reversed(spans):
                _, strength = vol.slab(j0, j1)
                step()
                yield strength[::-1]

        def amplitude_pass() -> Iterator[np.ndarray]:
            for j0, j1 in reversed(spans):
                amp, _ = vol.slab(j0, j1)
                vals = amp[:, covered].ravel()
                vals = vals[np.isfinite(vals)]
                if vals.size:
                    stride = max(1, vals.size // _RANGE_SAMPLE)
                    samples.append(vals[::stride])
                step()
                yield amp[::-1]

        def depth_pass() -> Iterator[np.ndarray]:
            for j0, j1 in reversed(spans):
                yield np.broadcast_to(depths[j0:j1][::-1, None, None], (j1 - j0, ny, nx))

        write_image_data(
            folder / "cube.vti",
            origin=(choice.cell / 2.0, choice.cell / 2.0, -max_depth * s),
            spacing=(choice.cell, choice.cell, depth_step * s),
            shape=(nx, ny, nd),
            arrays=[
                ("strength", strength_pass),
                ("amplitude", amplitude_pass),
                ("true_depth_m", depth_pass),
            ],
        )
        if not samples:
            return 1.0
        p99 = float(np.percentile(np.concatenate(samples), 99.0))
        return p99 if math.isfinite(p99) and p99 > 0.0 else 1.0

    def _write_picks(
        self,
        folder: Path,
        lines: Sequence[PreparedLine],
        prov: Any,
        frame: CubeFrame,
        choice: VolumeChoice,
        velocity: Any,
        feature_index: dict[str, int] | None = None,
    ) -> int:
        """picks.vtp: each pick at its cube-clock time, converted with the volume's velocity.
        `feature` is the index (in export.json's `features`) of the pick's built surface, or -1."""
        feature_index = feature_index or {}
        order = {line.key: i for i, line in enumerate(sorted(lines, key=lambda ln: ln.key))}
        rows = [(line.key, p) for line in lines for p in self.session.picks_for(line.key)]
        spots = place_picks(rows, lines, prov, frame, velocity)
        placed = [p for p in spots if p is not None]
        feature = np.asarray(
            [
                feature_index.get(str(pick.feature_id), -1)
                for (_key, pick), spot in zip(rows, spots)
                if spot is not None
            ],
            dtype=np.int32,
        )
        depth = np.asarray([p.depth_m for p in placed], dtype=float)
        local = np.asarray([[p.x_m, p.y_m] for p in placed], dtype=float).reshape(-1, 2)
        line_index = np.asarray([order[p.line_key] for p in placed], dtype=np.int32)
        points = (
            np.column_stack([local, -depth * choice.stretch]) if depth.size else np.empty((0, 3))
        )
        write_poly_data(
            folder / "picks.vtp",
            points,
            {"true_depth_m": depth.astype(np.float32), "line": line_index, "feature": feature},
            verts=[[i] for i in range(len(depth))],
        )
        return int(depth.size)

    def _write_features(
        self, folder: Path, grid_id: str, frame: CubeFrame, choice: VolumeChoice
    ) -> list[dict[str, Any]]:
        """features.vtp: every built surface of the grid, stale ones included (they show their
        last build), as triangles at `(x, y, -depth * stretch)` in the cube's frame. Returns
        each surface's scene entry (with its `feature_id`, which the caller removes)."""
        points: list[np.ndarray] = []
        depth: list[np.ndarray] = []
        feature: list[np.ndarray] = []
        stale: list[np.ndarray] = []
        polys: list[list[int]] = []
        entries: list[dict[str, Any]] = []
        self.skipped_surfaces = []
        count = 0
        records = [] if self.surfaces is None else self.surfaces.records()
        for record in records:
            if record.grid_id != grid_id:
                continue
            built = self.surfaces.built(record.feature_id)
            if built is None:
                continue
            index = len(entries)
            is_stale = bool(self.surfaces.state(record.feature_id).stale)
            local, triangles, _cells = surface_mesh(built.depth_m, built.cell)
            if len(local):
                # The build's own frame to world, then to this export's frame: the same unless
                # the grid has moved since the build.
                x_hat, y_hat = CubeFrame(
                    built.origin, built.azimuth, built.cell, 1, 1, built.crs
                ).axes()
                world = (
                    np.asarray(built.origin, dtype=float)
                    + local[:, :1] * x_hat
                    + local[:, 1:2] * y_hat
                )
                if str(built.crs) != str(frame.crs):
                    world = self._reproject(world, str(built.crs), str(frame.crs))
                    if world is None:
                        self.skipped_surfaces.append(record.name)
                        continue
                xy = frame.to_local(world)
                points.append(np.column_stack([xy, -local[:, 2] * choice.stretch]))
                depth.append(local[:, 2].astype(np.float32))
                feature.append(np.full(len(local), index, dtype=np.int32))
                stale.append(np.full(len(local), 1 if is_stale else 0, dtype=np.uint8))
                polys.extend((triangles + count).tolist())
                count += len(local)
            fit = built.report.get("fit", {})
            entries.append(
                {
                    "feature_id": record.feature_id,
                    "index": index,
                    "name": record.name,
                    "stale": is_stale,
                    "picks": int(fit.get("picks", 0)),
                    "within_2cm": int(fit.get("within_2cm", 0)),
                    "on_holes": int(fit.get("on_holes", 0)),
                }
            )
        write_poly_data(
            folder / "features.vtp",
            np.vstack(points) if points else np.empty((0, 3)),
            {
                "true_depth_m": np.concatenate(depth) if depth else np.empty(0, np.float32),
                "feature": np.concatenate(feature) if feature else np.empty(0, np.int32),
                "stale": np.concatenate(stale) if stale else np.empty(0, np.uint8),
            },
            polys=polys,
        )
        return entries

    @staticmethod
    def _reproject(world: np.ndarray, source: str, target: str) -> np.ndarray | None:
        """`world` (n, 2) from the CRS `source` to `target`; None when either is unknown or a
        point cannot be moved."""
        src, dst = QgsCoordinateReferenceSystem(source), QgsCoordinateReferenceSystem(target)
        if not (src.isValid() and dst.isValid()):
            return None
        transform = QgsCoordinateTransform(src, dst, QgsProject.instance().transformContext())
        try:
            moved = [transform.transform(QgsPointXY(float(x), float(y))) for x, y in world]
        except Exception:  # noqa: BLE001 -- QgsCsException: a point outside the CRS's domain
            return None
        out = np.array([[p.x(), p.y()] for p in moved], dtype=float)
        return out if np.isfinite(out).all() else None

    @staticmethod
    def _write_lines(
        folder: Path, lines: Sequence[PreparedLine], frame: CubeFrame, grid: Any
    ) -> None:
        """lines.vtp: each line at ground level (at most 200 points), and the grid outline."""
        pts: list[np.ndarray] = []
        cells: list[list[int]] = []
        count = 0
        for line in lines:
            local = frame.to_local(line.coords)
            if len(local) > MAX_LINE_POINTS:
                pick = np.unique(
                    np.linspace(0, len(local) - 1, MAX_LINE_POINTS).round().astype(int)
                )
                local = local[pick]
            pts.append(np.column_stack([local, np.zeros(len(local))]))
            cells.append(list(range(count, count + len(local))))
            count += len(local)
        sx, sy = float(grid.size_x), float(grid.size_y)
        pts.append(np.array([[0, 0, 0], [sx, 0, 0], [sx, sy, 0], [0, sy, 0]], dtype=float))
        cells.append([count, count + 1, count + 2, count + 3, count])
        write_poly_data(folder / "lines.vtp", np.vstack(pts), {}, lines=cells)

    def _record(
        self,
        grid: Any,
        grid_id: str,
        choice: VolumeChoice,
        frame: CubeFrame,
        lines: Sequence[PreparedLine],
        prov: Any,
        finish: Any,
        vol: Any,
        amp_p99: float,
        n_picks: int,
        features: list[dict[str, Any]],
    ) -> dict[str, Any]:
        depths = vol.depths_m
        local = [frame.to_local(line.coords) for line in lines]
        spread_x = sum(float(np.ptp(c[:, 0])) for c in local)
        spread_y = sum(float(np.ptp(c[:, 1])) for c in local)
        along = "x" if spread_x > spread_y else "y"
        a, b = (0, 1) if along == "x" else (1, 0)  # along-line axis, across-lines axis
        across = sorted(float(np.mean(c[:, b])) for c in local)
        along_all = np.concatenate([c[:, a] for c in local])
        mid_along = float((along_all.min() + along_all.max()) / 2.0)
        mid_across = across[len(across) // 2]
        x_m, y_m = (mid_along, mid_across) if along == "x" else (mid_across, mid_along)
        return scene_record(
            grid=grid_id,
            title=scene_title(grid_id, choice.stretch),
            stretch=float(choice.stretch),
            crs=str(frame.crs),
            origin=[float(frame.origin[0]), float(frame.origin[1])],
            azimuth_deg=float(frame.azimuth),
            cell_m=float(choice.cell),
            dz_ns=float(choice.dz_ns),
            depth_step_m=float(depths[1] - depths[0]),
            max_depth_m=float(depths[-1]),
            source={
                "preset": str(prov.preset_name),
                "transform": str(prov.transform),
                "lines": len(lines),
                "line_keys": sorted(line.key for line in lines),
                "time_base": time_base_of(prov.steps),
            },
            fill={
                "method": str(finish.method),
                "max_distance_m": float(finish.max_distance_m),
                "search_radius_m": float(finish.search_radius_m),
                "smooth_x_m": float(finish.smooth_x_m),
                "smooth_y_m": float(finish.smooth_y_m),
            },
            volume={k: float(v) for k, v in choice.settings.to_dict().items()},
            amplitude_range=[0.0, float(amp_p99)],
            slices={
                "depth_m": float(depths[len(depths) // 2]),
                "x_m": float(x_m),
                "y_m": float(y_m),
                "lines_along": along,
            },
            n_picks=int(n_picks),
            features=features,
            nsgeo_version=str(nsgeo.__version__),
            written_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    @staticmethod
    def _swap(partial: Path, folder: Path) -> None:
        """Put `partial` in place of `folder`; the old export goes only after the new one is in."""
        old = folder.with_name(folder.name + ".old")
        if old.exists():
            shutil.rmtree(old)
        had = folder.exists()
        if had:
            try:
                folder.rename(old)
            except PermissionError as exc:  # Windows: a program has the folder open
                raise RuntimeError(in_use_message(folder)) from exc
        try:
            partial.rename(folder)
        except BaseException:
            if had:
                with contextlib.suppress(OSError):
                    old.rename(folder)
            raise
        if had:
            shutil.rmtree(old, ignore_errors=True)
