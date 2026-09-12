"""SiteSession: the one place survey state lives.

Every widget reads from the session and connects to its signals; no widget
holds survey state or talks to another widget directly. Every signal fires
only when a value actually changed, which is the loop guard for the
map<->profile link. Stack mutation goes through the methods here and nowhere
else, so the core's no-in-place-mutation rule stays true.

Main-thread only: every method call and every signal handler is expected to
run on the Qt main thread. A background loader (a QgsTask worker) must marshal
its result back to the main thread and call into the session from there --
none of this is protected by a lock.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from nsgeo.geometry.grid import Grid
from nsgeo.model.survey import Line, Profile, Site
from nsgeo.processing import Radargram, StepStack
from nsgeo.project import ProjectError, _line_key, load_site, save_site
from nsgeo.velocity import VelocityModel, resolve_velocity
from qgis.PyQt.QtCore import QObject, pyqtSignal

SURVEY_FILE = "survey.nsgeo.json"


class SiteSession(QObject):
    site_opened = pyqtSignal()
    site_closed = pyqtSignal()
    dirty_changed = pyqtSignal(bool)
    grids_changed = pyqtSignal()
    lines_changed = pyqtSignal()
    line_opened = pyqtSignal(str)  # "" when no line is current
    line_loaded = pyqtSignal(str)
    trace_changed = pyqtSignal(str, int)
    selection_changed = pyqtSignal(str, int, int)  # (-1, -1) when cleared
    stack_changed = pyqtSignal(str)
    picks_changed = pyqtSignal()
    presets_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._site: Site | None = None
        self._json_path: Path | None = None
        self._root: Path | None = None
        self._lines_by_key: dict[str, Line] = {}
        self._dirty = False
        self._allow_absolute = False
        self._profiles: dict[str, list[Profile]] = {}
        self._channel: dict[str, int] = {}
        self._current_key: str | None = None
        self._current_trace = -1
        self._selection: tuple[int, int] = (-1, -1)

    # ---- state ------------------------------------------------------------
    @property
    def site(self) -> Site | None:
        return self._site

    @property
    def is_open(self) -> bool:
        return self._site is not None

    @property
    def json_path(self) -> Path | None:
        return self._json_path

    @property
    def root(self) -> Path:
        self._require_path()
        assert self._root is not None  # set by _install whenever a path is
        return self._root

    @property
    def site_name(self) -> str:
        return self.root.name

    @property
    def gpkg_path(self) -> Path:
        return self.root / f"{self.site_name}.nsgeo.gpkg"

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def current_key(self) -> str | None:
        return self._current_key

    @property
    def current_trace(self) -> int:
        return self._current_trace

    @property
    def selection(self) -> tuple[int, int]:
        return self._selection

    def _require_site(self) -> Site:
        if self._site is None:
            raise ProjectError("no site is open")
        return self._site

    def _require_path(self) -> Path:
        if self._json_path is None:
            raise ProjectError("no site is open")
        return self._json_path

    def _set_dirty(self, flag: bool) -> None:
        if flag != self._dirty:
            self._dirty = flag
            self.dirty_changed.emit(flag)

    # ---- lifecycle --------------------------------------------------------
    def new_site(self, folder: str | Path) -> None:
        folder = Path(folder)
        if not folder.is_dir():
            raise ProjectError(f"{folder} is not a directory")
        json_path = folder / SURVEY_FILE
        if json_path.exists():
            raise ProjectError(f"{folder} already holds a {SURVEY_FILE}; open it instead")
        site = Site()
        save_site(site, json_path)  # write first; a failure installs nothing
        self._install(site, json_path)
        self.site_opened.emit()

    def open_site(self, json_path: str | Path) -> None:
        json_path = Path(json_path)
        site = load_site(json_path)
        self._install(site, json_path)
        self.site_opened.emit()

    def _install(self, site: Site, json_path: Path) -> None:
        if self._site is not None:
            self.close_site()
        self._site = site
        self._json_path = json_path
        self._root = json_path.parent.resolve()
        # One resolve() per line, exactly once, at install time -- not on
        # every cursor event. line_for_key()/keys() read this map only.
        self._lines_by_key = {self.line_key(ln): ln for ln in site.lines}
        self._profiles.clear()
        self._channel.clear()
        self._current_key = None
        self._current_trace = -1
        self._selection = (-1, -1)
        self._allow_absolute = False
        self._set_dirty(False)

    def save(self, *, allow_absolute: bool | None = None) -> None:
        if allow_absolute is not None:
            self._allow_absolute = allow_absolute
        site = self._require_site()
        site.validate()
        save_site(site, self._require_path(), allow_absolute=self._allow_absolute)
        self._set_dirty(False)

    def close_site(self) -> None:
        if self._site is None:
            return
        had_current_line = self._current_key is not None
        self._site = None
        self._json_path = None
        self._root = None
        self._lines_by_key = {}
        self._profiles.clear()
        self._channel.clear()
        self._current_key = None
        self._current_trace = -1
        self._selection = (-1, -1)
        self._allow_absolute = False
        self._set_dirty(False)
        if had_current_line:
            # Same "no line is current" transition remove_line() reports;
            # a widget bound only to line_opened must not keep a stale line.
            self.line_opened.emit("")
        self.site_closed.emit()

    # ---- keys and lookups -------------------------------------------------
    def line_key(self, line: Line) -> str:
        # Always computable; whether an absolute key may be *saved* is
        # decided in save() via allow_absolute.
        return _line_key(line.path, self.root, allow_absolute=True)

    def keys(self) -> list[str]:
        self._require_site()
        return list(self._lines_by_key)

    def line_for_key(self, key: str) -> Line:
        self._require_site()
        try:
            return self._lines_by_key[key]
        except KeyError:
            raise KeyError(f"no line with key {key!r}") from None

    def grid(self, grid_id: str) -> Grid:
        for g in self._require_site().grids:
            if g.id == grid_id:
                return g
        raise KeyError(f"no grid with id {grid_id!r}")

    def grid_for_line(self, line: Line) -> Grid | None:
        grid_id = getattr(line.placement, "grid_id", None)
        return self._require_site().frames.get(grid_id) if grid_id is not None else None

    # ---- grids ------------------------------------------------------------
    def add_grid(self, grid: Grid) -> None:
        site = self._require_site()
        if any(g.id == grid.id for g in site.grids):
            raise ValueError(f"a grid with id {grid.id!r} already exists")
        site.grids.append(grid)
        self._set_dirty(True)
        self.grids_changed.emit()

    def replace_grid(self, grid: Grid) -> None:
        site = self._require_site()
        for i, g in enumerate(site.grids):
            if g.id == grid.id:
                site.grids[i] = grid
                break
        else:
            raise KeyError(f"no grid with id {grid.id!r}")
        self._set_dirty(True)
        self.grids_changed.emit()
        self.lines_changed.emit()  # line geometry follows the frame

    def remove_grid(self, grid_id: str) -> None:
        site = self._require_site()
        users = [ln for ln in site.lines if getattr(ln.placement, "grid_id", None) == grid_id]
        if users:
            raise ValueError(f"grid {grid_id!r} still has {len(users)} line(s); remove them first")
        site.grids.remove(self.grid(grid_id))
        self._set_dirty(True)
        self.grids_changed.emit()

    def set_grid_velocity(self, grid_id: str, model: VelocityModel | None) -> None:
        self.replace_grid(dataclasses.replace(self.grid(grid_id), velocity=model))

    # ---- lines ------------------------------------------------------------
    def add_lines(self, lines: list[Line]) -> None:
        site = self._require_site()
        existing = set(self._lines_by_key)
        keyed: list[tuple[str, Line]] = []
        for line in lines:
            key = self.line_key(line)
            if key in existing:
                raise ValueError(f"line {key!r} is already in the site")
            existing.add(key)
            keyed.append((key, line))
        site.lines.extend(lines)
        self._lines_by_key.update(keyed)
        self._set_dirty(True)
        self.lines_changed.emit()

    def remove_line(self, key: str) -> None:
        site = self._require_site()
        line = self.line_for_key(key)
        site.lines.remove(line)
        del self._lines_by_key[key]
        site.stacks.pop(key, None)
        self._profiles.pop(key, None)
        self._channel.pop(key, None)
        self._set_dirty(True)
        if self._current_key == key:
            self._current_key = None
            self._current_trace = -1
            self._selection = (-1, -1)
            self.line_opened.emit("")
        self.lines_changed.emit()

    def set_line_velocity(self, key: str, model: VelocityModel | None) -> None:
        site = self._require_site()
        line = self.line_for_key(key)
        new_line = dataclasses.replace(line, velocity=model)
        site.lines[site.lines.index(line)] = new_line
        self._lines_by_key[key] = new_line  # same key: only the object changed
        self._set_dirty(True)
        self.lines_changed.emit()

    def resolved_velocity(self, key: str) -> VelocityModel:
        line = self.line_for_key(key)
        return resolve_velocity(line, self.grid_for_line(line))

    # ---- stacks -----------------------------------------------------------
    def stack_for(self, key: str) -> StepStack:
        site = self._require_site()
        stack = site.stacks.get(key)
        if stack is None:
            self.line_for_key(key)  # KeyError for unknown lines
            stack = StepStack()
            site.stacks[key] = stack
            self._attach_source(key, stack)
        return stack

    def _attach_source(self, key: str, stack: StepStack) -> None:
        profiles = self._profiles.get(key)
        if not profiles:
            # No profiles loaded (yet), or explicitly cleared: the stack must
            # not keep rendering a previous line's samples as if they were
            # still current.
            stack.source = None
            return
        stack.source = Radargram.from_profile(profiles[self._channel.get(key, 0)])

    def _touch_stack(self, key: str) -> None:
        self._set_dirty(True)
        self.stack_changed.emit(key)

    def append_step(self, key: str, step: Any) -> None:
        self.stack_for(key).append(step)
        self._touch_stack(key)

    def insert_step(self, key: str, index: int, step: Any) -> None:
        self.stack_for(key).insert(index, step)
        self._touch_stack(key)

    def replace_step(self, key: str, index: int, step: Any) -> None:
        self.stack_for(key).replace_step(index, step)
        self._touch_stack(key)

    def remove_step(self, key: str, index: int) -> None:
        self.stack_for(key).remove(index)
        self._touch_stack(key)

    def move_step(self, key: str, src: int, dst: int) -> None:
        stack = self.stack_for(key)
        if src == dst and 0 <= src < len(stack):
            return  # moving a step onto itself changes nothing
        stack.move(src, dst)
        self._touch_stack(key)

    def set_step_enabled(self, key: str, index: int, flag: bool) -> None:
        stack = self.stack_for(key)
        if stack.entries[index][1] == flag:
            return  # already in the requested state
        stack.set_enabled(index, flag)
        self._touch_stack(key)

    def apply_stack_to_grid(self, key: str, grid_id: str) -> list[str]:
        """Copy this line's stack onto every other line in the grid.
        Explicit button, never a side effect. Returns the keys changed."""
        site = self._require_site()
        dicts = self.stack_for(key).to_dicts()
        changed: list[str] = []
        for other, line in self._lines_by_key.items():
            if other == key or getattr(line.placement, "grid_id", None) != grid_id:
                continue
            fresh = StepStack.from_dicts(dicts)
            self._attach_source(other, fresh)
            site.stacks[other] = fresh
            changed.append(other)
            # Dirty before the emit: a synchronous stack_changed slot must
            # never see a change it is handling as if the site were clean.
            self._set_dirty(True)
            self.stack_changed.emit(other)
        return changed

    # ---- presets ----------------------------------------------------------
    def preset_names(self) -> list[str]:
        return sorted(self._require_site().presets)

    def save_preset(self, name: str, key: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("a preset needs a name")
        self._require_site().presets[name] = self.stack_for(key).to_dicts()
        self._set_dirty(True)
        self.presets_changed.emit()

    def apply_preset(self, name: str, key: str) -> None:
        site = self._require_site()
        fresh = StepStack.from_dicts(site.presets[name])
        self._attach_source(key, fresh)
        site.stacks[key] = fresh
        self._touch_stack(key)

    def delete_preset(self, name: str) -> None:
        self._require_site().presets.pop(name, None)
        self._set_dirty(True)
        self.presets_changed.emit()

    # ---- current line, samples, cursor ------------------------------------
    def open_line(self, key: str) -> None:
        self.line_for_key(key)
        if key == self._current_key:
            return
        self._current_key = key
        self._current_trace = -1
        self._selection = (-1, -1)
        self.line_opened.emit(key)

    def profiles_for(self, key: str) -> list[Profile] | None:
        return self._profiles.get(key)

    def set_profiles(self, key: str, profiles: list[Profile]) -> None:
        stack = self.stack_for(key)  # validates the key before anything is cached
        self._profiles[key] = list(profiles)
        self._channel.setdefault(key, 0)
        self._attach_source(key, stack)  # the only build: stack_for saw no profiles yet
        self.line_loaded.emit(key)

    def channel(self, key: str) -> int:
        return self._channel.get(key, 0)

    def set_channel(self, key: str, channel: int) -> None:
        profiles = self._profiles.get(key)
        if profiles is None or not 0 <= channel < len(profiles):
            raise IndexError(f"line {key!r} has no channel {channel}")
        if channel == self._channel.get(key, 0):
            return
        self._channel[key] = channel
        self._attach_source(key, self.stack_for(key))
        self.stack_changed.emit(key)

    def set_trace(self, key: str, index: int) -> None:
        if key != self._current_key:
            return
        n = self.line_for_key(key).n_traces
        index = max(0, min(int(index), n - 1))
        if index != self._current_trace:
            self._current_trace = index
            self.trace_changed.emit(key, index)

    def set_selection(self, key: str, start: int, end: int) -> None:
        if key != self._current_key:
            return
        n = self.line_for_key(key).n_traces
        lo, hi = sorted((int(start), int(end)))
        # Each end is clamped independently into [0, n - 1]. That means this
        # can never land on (-1, -1): clearing the selection is exclusively
        # clear_selection()'s job, and a caller cannot accidentally forge the
        # "cleared" sentinel by dragging off either edge.
        sel = (max(0, min(lo, n - 1)), max(0, min(hi, n - 1)))
        if sel != self._selection:
            self._selection = sel
            self.selection_changed.emit(key, sel[0], sel[1])

    def clear_selection(self) -> None:
        if self._selection != (-1, -1) and self._current_key is not None:
            self._selection = (-1, -1)
            self.selection_changed.emit(self._current_key, -1, -1)
