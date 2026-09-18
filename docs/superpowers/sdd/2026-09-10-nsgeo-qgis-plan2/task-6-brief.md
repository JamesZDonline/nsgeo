### Task 6: `SiteSession` — the one place survey state lives

A `QObject` that owns the `Site`, its paths, per-line stacks, the current line and trace, and emits a signal on every change. Widgets read from it and never from each other. Also the only legal path for stack mutation.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/session.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`

**Interfaces:**
- Consumes: `Site`, `Line`, `Grid`, `Profile`, `StepStack`, `Radargram.from_profile`, `load_site`, `save_site`, `_line_key`, `resolve_velocity`
- Produces: `SiteSession(parent=None)` with signals `site_opened()`, `site_closed()`, `dirty_changed(bool)`, `grids_changed()`, `lines_changed()`, `line_opened(str)` (`""` = none), `line_loaded(str)`, `trace_changed(str, int)`, `selection_changed(str, int, int)` (`-1, -1` = cleared), `stack_changed(str)`, `picks_changed()`; properties `site`, `json_path`, `gpkg_path`, `site_name`, `root`, `is_open`, `dirty`, `current_key`, `current_trace`, `selection`; methods `new_site(folder)`, `open_site(json_path)`, `save(allow_absolute=None)`, `close_site()`, `line_key(line)`, `line_for_key(key)`, `keys()`, `grid(grid_id)`, `grid_for_line(line)`, `add_grid`, `replace_grid`, `remove_grid`, `set_grid_velocity`, `add_lines`, `remove_line`, `set_line_velocity`, `resolved_velocity(key)`, `stack_for(key)`, `append_step`, `insert_step`, `replace_step`, `remove_step`, `move_step`, `set_step_enabled`, `apply_stack_to_grid(key, grid_id) -> list[str]`, `open_line(key)`, `profiles_for(key)`, `set_profiles(key, profiles)`, `set_channel(key, channel)`, `channel(key) -> int`, `set_trace(key, index)`, `set_selection(key, start, end)`, `clear_selection()`, `SURVEY_FILE = "survey.nsgeo.json"`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`:

```python
from __future__ import annotations

import json

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.project import ProjectError
from nsgeo.velocity import VelocityModel

from nsgeo_qgis.session import SURVEY_FILE, SiteSession

from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


def _lines(folder, n=3):
    out = []
    for i in range(n):
        p = synthetic_dzt(folder / "raw", f"FILE__00{i + 1}.DZT", n_traces=60 + i)
        out.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1 if i % 2 == 0 else -1, p.stem)))
    return out


class Spy:
    def __init__(self, signal):
        self.calls: list = []
        signal.connect(lambda *a: self.calls.append(a))


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    return s


def test_new_site_writes_the_survey_file_and_derives_the_gpkg_name(qgis_app, tmp_path):
    s = SiteSession()
    opened = Spy(s.site_opened)
    s.new_site(tmp_path)
    assert (tmp_path / SURVEY_FILE).is_file()
    assert s.site_name == tmp_path.name
    assert s.gpkg_path == tmp_path / f"{tmp_path.name}.nsgeo.gpkg"
    assert s.is_open and not s.dirty
    assert opened.calls == [()]
    with pytest.raises(ProjectError, match="already"):
        s.new_site(tmp_path)


def test_grids_and_lines_mark_dirty_and_round_trip(session, tmp_path):
    dirty = Spy(session.dirty_changed)
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path))
    assert session.dirty and dirty.calls[0] == (True,)
    assert session.keys() == ["raw/FILE__001.DZT", "raw/FILE__002.DZT", "raw/FILE__003.DZT"]
    session.save()
    assert not session.dirty
    back = SiteSession()
    back.open_site(tmp_path / SURVEY_FILE)
    assert [g.id for g in back.site.grids] == ["A"]
    assert back.keys() == session.keys()


def test_duplicate_grid_ids_and_line_keys_are_refused(session, tmp_path):
    session.add_grid(GRID)
    with pytest.raises(ValueError, match="A"):
        session.add_grid(GRID)
    lines = _lines(tmp_path)
    session.add_lines(lines)
    with pytest.raises(ValueError, match="FILE__001"):
        session.add_lines(lines[:1])


def test_remove_grid_refuses_while_lines_reference_it(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    with pytest.raises(ValueError, match="1 line"):
        session.remove_grid("A")
    session.remove_line("raw/FILE__001.DZT")
    session.remove_grid("A")
    assert session.site.grids == []


def test_remove_line_drops_its_stack_and_closes_it_if_current(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    key = "raw/FILE__001.DZT"
    session.append_step(key, build_step("dewow"))
    session.open_line(key)
    opened = Spy(session.line_opened)
    session.remove_line(key)
    assert key not in session.site.stacks
    assert session.current_key is None
    assert opened.calls == [("",)]


def test_velocity_resolution_and_override(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    assert session.resolved_velocity(key) == VelocityModel.from_dielectric(14.0)
    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    assert session.resolved_velocity(key) == VelocityModel.constant(0.09)
    session.set_line_velocity(key, VelocityModel.constant(0.07))
    assert session.resolved_velocity(key) == VelocityModel.constant(0.07)
    session.set_line_velocity(key, None)
    assert session.resolved_velocity(key) == VelocityModel.constant(0.09)


def test_stack_mutations_emit_and_go_through_the_stack(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    changed = Spy(session.stack_changed)
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("background_mean"))
    session.insert_step(key, 0, build_step("time_zero"))
    session.set_step_enabled(key, 1, False)
    session.move_step(key, 2, 0)
    session.replace_step(key, 1, build_step("time_zero", mode="sample", sample=3))
    session.remove_step(key, 0)
    names = [s.name for s, _ in session.stack_for(key).entries]
    assert names == ["time_zero", "dewow"]
    assert session.stack_for(key).entries[1][1] is False
    assert len(changed.calls) == 7 and all(c == (key,) for c in changed.calls)


def test_profiles_feed_the_stack_source_and_channel_switching(session, tmp_path):
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    loaded = Spy(session.line_loaded)
    session.set_profiles(key, lines[0].load())
    assert loaded.calls == [(key,)]
    src = session.stack_for(key).source
    assert src is not None and src.n_traces == 60 and src.data.dtype.kind == "f"
    assert session.channel(key) == 0
    with pytest.raises(IndexError):
        session.set_channel(key, 1)


def test_apply_stack_to_grid_copies_independent_stacks(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 3))
    a, b, c = session.keys()
    session.append_step(a, build_step("dewow", window_ns=6.0))
    changed = session.apply_stack_to_grid(a, "A")
    assert changed == [b, c]
    assert session.stack_for(b).to_dicts() == session.stack_for(a).to_dicts()
    assert session.stack_for(b) is not session.stack_for(a)
    session.replace_step(a, 0, build_step("dewow", window_ns=2.0))
    assert session.stack_for(b).to_dicts()[0]["params"]["window_ns"] == 6.0


def test_trace_and_selection_emit_only_on_change_and_only_for_the_current_line(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    a, b = session.keys()
    session.open_line(a)
    trace = Spy(session.trace_changed)
    sel = Spy(session.selection_changed)
    session.set_trace(a, 10)
    session.set_trace(a, 10)
    session.set_trace(a, 999)  # clamped to the last trace
    session.set_trace(b, 5)  # not current: ignored
    assert trace.calls == [(a, 10), (a, 59)]
    session.set_selection(a, 30, 20)
    session.set_selection(a, 30, 20)
    session.clear_selection()
    assert sel.calls == [(a, 20, 30), (a, -1, -1)]
    assert session.current_trace == 59


def test_open_line_resets_trace_and_selection(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    a, b = session.keys()
    session.open_line(a)
    session.set_trace(a, 4)
    session.set_selection(a, 1, 2)
    session.open_line(b)
    assert (session.current_key, session.current_trace, session.selection) == (b, -1, (-1, -1))
    with pytest.raises(KeyError):
        session.open_line("nope")


def test_save_out_of_tree_line_needs_allow_absolute(qgis_app, tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    s = SiteSession()
    s.new_site(site_dir)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "elsewhere", "X.DZT")
    s.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    with pytest.raises(ProjectError, match="allow_absolute"):
        s.save()
    s.save(allow_absolute=True)
    doc = json.loads((site_dir / SURVEY_FILE).read_text())
    assert doc["lines"][0]["path"].startswith("/")
    s.add_grid(Grid("B", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    s.save()  # the opt-in is remembered for the session
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.session'`

- [ ] **Step 3: Implement `session.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/session.py`:

```python
"""SiteSession: the one place survey state lives.

Every widget reads from the session and connects to its signals; no widget
holds survey state or talks to another widget directly. Every signal fires
only when a value actually changed, which is the loop guard for the
map<->profile link. Stack mutation goes through the methods here and nowhere
else, so the core's no-in-place-mutation rule stays true.
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

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._site: Site | None = None
        self._json_path: Path | None = None
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
        return self._require_path().parent.resolve()

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
        self._install(Site(), json_path)
        save_site(self._require_site(), json_path)
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
        self._site = None
        self._json_path = None
        self._profiles.clear()
        self._channel.clear()
        self._current_key = None
        self._current_trace = -1
        self._selection = (-1, -1)
        self._set_dirty(False)
        self.site_closed.emit()

    # ---- keys and lookups -------------------------------------------------
    def line_key(self, line: Line) -> str:
        # Always computable; whether an absolute key may be *saved* is
        # decided in save() via allow_absolute.
        return _line_key(line.path, self.root, allow_absolute=True)

    def keys(self) -> list[str]:
        return [self.line_key(ln) for ln in self._require_site().lines]

    def line_for_key(self, key: str) -> Line:
        for line in self._require_site().lines:
            if self.line_key(line) == key:
                return line
        raise KeyError(f"no line with key {key!r}")

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
        existing = set(self.keys())
        for line in lines:
            key = self.line_key(line)
            if key in existing:
                raise ValueError(f"line {key!r} is already in the site")
            existing.add(key)
        site.lines.extend(lines)
        self._set_dirty(True)
        self.lines_changed.emit()

    def remove_line(self, key: str) -> None:
        site = self._require_site()
        line = self.line_for_key(key)
        site.lines.remove(line)
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
        site.lines[site.lines.index(line)] = dataclasses.replace(line, velocity=model)
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
        if profiles:
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
        self.stack_for(key).move(src, dst)
        self._touch_stack(key)

    def set_step_enabled(self, key: str, index: int, flag: bool) -> None:
        self.stack_for(key).set_enabled(index, flag)
        self._touch_stack(key)

    def apply_stack_to_grid(self, key: str, grid_id: str) -> list[str]:
        """Copy this line's stack onto every other line in the grid.
        Explicit button, never a side effect. Returns the keys changed."""
        site = self._require_site()
        dicts = self.stack_for(key).to_dicts()
        changed: list[str] = []
        for line in site.lines:
            other = self.line_key(line)
            if other == key or getattr(line.placement, "grid_id", None) != grid_id:
                continue
            fresh = StepStack.from_dicts(dicts)
            self._attach_source(other, fresh)
            site.stacks[other] = fresh
            changed.append(other)
            self.stack_changed.emit(other)
        if changed:
            self._set_dirty(True)
        return changed

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
        self._profiles[key] = list(profiles)
        self._channel.setdefault(key, 0)
        self._attach_source(key, self.stack_for(key))
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
        sel = (max(0, lo), min(n - 1, hi))
        if sel != self._selection:
            self._selection = sel
            self.selection_changed.emit(key, sel[0], sel[1])

    def clear_selection(self) -> None:
        if self._selection != (-1, -1) and self._current_key is not None:
            self._selection = (-1, -1)
            self.selection_changed.emit(self._current_key, -1, -1)
```

- [ ] **Step 4: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: SiteSession, the single owner of plugin survey state

Holds the Site, its paths, per-line stacks, the current line, trace and
selection, and emits a signal on every real change. Stack edits go
through replace_step and friends so the core's no-mutation rule holds;
apply-to-grid copies stacks rather than sharing them. Out-of-tree lines
need an explicit allow_absolute on save, mapping to the core's opt-in."
```

---

