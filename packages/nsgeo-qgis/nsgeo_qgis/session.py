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
from nsgeo.project import ProjectError, line_key, load_site, save_site
from nsgeo.velocity import VelocityModel, resolve_velocity
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QObject, pyqtSignal

SURVEY_FILE = "survey.nsgeo.json"
# Fixed, not derived from the folder name. Final review, I5: the survey
# JSON is deliberately portable -- save_site()'s docstring says the
# project directory can be moved intact -- and naming the package after
# the directory broke that for the one table the JSON is not the source
# of truth for. Renaming Site1/ to Kavusan2026/ once the fieldwork had a
# name left every authored pick in Site1.nsgeo.gpkg, unreachable and
# unmentioned. See _resolve_package() for the packages already
# written under the old rule.
GPKG_FILE = "site.nsgeo.gpkg"
_GPKG_SUFFIX = ".nsgeo.gpkg"
# SQLite finds these by the database's *current* filename, so renaming the
# database alone orphans them. See _resolve_package(). `-shm` is not even
# movable in principle -- it is shared memory backing a live `-wal`,
# meaningless once detached from it.
_SQLITE_JOURNALS = ("-wal", "-shm", "-journal")


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


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
    # Spec §3.3: the WEAK notion of "what the pointer is over". It drives
    # the profile view and the trace cursor and nothing else, ever. It is
    # never a write target and never dirties the session -- see
    # set_preview() for why that distinction is load bearing.
    preview_changed = pyqtSignal(str, int)  # ("", -1) when cleared
    stack_changed = pyqtSignal(str)
    picks_changed = pyqtSignal()
    presets_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._site: Site | None = None
        self._json_path: Path | None = None
        self._root: Path | None = None
        self._gpkg_path: Path | None = None
        self._lines_by_key: dict[str, Line] = {}
        self._dirty = False
        self._allow_absolute = False
        self._profiles: dict[str, list[Profile]] = {}
        self._channel: dict[str, int] = {}
        self._current_key: str | None = None
        self._current_trace = -1
        self._selection: tuple[int, int] = (-1, -1)
        self._preview_key: str | None = None
        self._preview_trace = -1

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
        """The site's GeoPackage, resolved once when the site was opened.

        Normally `root / GPKG_FILE`: one fixed name, deliberately
        independent of what the directory is called. `site_name` above is
        a *display* label (the legend group, the survey tree's root) and
        is meant to follow a rename; this is a file path and must not.

        Resolved rather than recomputed because `_resolve_package()` can
        legitimately land on a package still carrying its pre-I5 name --
        see there. Recomputing would mean re-running that decision on
        every access, including after `ensure_tables()` has created files
        under the directory, which is precisely how the first version of
        this got stuck.
        """
        self._require_path()
        assert self._gpkg_path is not None  # set by _install whenever a path is
        return self._gpkg_path

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

    @property
    def preview_key(self) -> str | None:
        return self._preview_key

    @property
    def preview_trace(self) -> int:
        return self._preview_trace

    @property
    def display_key(self) -> str | None:
        """The line the profile should be SHOWING -- the preview when there
        is one, otherwise the working line.

        Deliberately distinct from `current_key`, which is the line every
        write resolves through. A caller that is about to change data wants
        `current_key`; a caller that is about to draw wants this. Getting
        those two confused is exactly the C2 defect class (a write target
        resolved from a different source than the thing the user believes
        they are editing), so they do not share a name.
        """
        return self._preview_key or self._current_key

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
        self._gpkg_path = self._resolve_package(self._root)
        self._set_dirty(False)

    @staticmethod
    def _sqlite_journals(package: Path) -> list[Path]:
        """Journal files SQLite would resolve from `package`'s current name.

        A GeoPackage is a SQLite database, and SQLite derives `-wal`,
        `-shm` and `-journal` from whatever the database file is called
        *now*. That is the whole reason the package cannot simply be
        renamed: the journals do not follow it, and everything committed
        since the last checkpoint lives in them.
        """
        found = []
        for suffix in _SQLITE_JOURNALS:
            journal = package.with_name(package.name + suffix)
            if journal.exists():
                found.append(journal)
        return found

    def _resolve_package(self, root: Path) -> Path:
        """Which file is this site's GeoPackage, adopting a legacy one when safe.

        Packages already written carry whatever the folder was called when
        they were created, and once that folder has been renamed no rule
        can re-derive the name -- which is the I5 defect itself. So this
        globs for `*.nsgeo.gpkg` rather than guessing, and renames a single
        find into place. It never copies and never deletes: the worst it
        does is leave a package where it is and use it there.

        The outcomes, in the order they are decided:

        * No legacy package: `GPKG_FILE`, created on demand by
          `SiteLayers.ensure_tables()`.
        * `GPKG_FILE` already exists: use it. Adopting would have to
          overwrite the site's own package, so nothing is touched -- but
          the stray is named at Warning, because it may hold picks and
          nothing else in the UI would ever mention it.
        * More than one legacy package: do not guess, and say so at
          Critical. The adopted one is the file the site then writes into,
          so choosing wrong is worse than choosing none.
        * Either name has a SQLite journal beside it: **use the legacy
          package where it is**, under its old name, without renaming
          anything. See below.
        * Otherwise: adopt it, by renaming it to `GPKG_FILE`.

        The journal case is the subtle one, and the first version of it was
        wrong in a way worth recording. It *declined* -- resolved to
        `GPKG_FILE` and told the user to clear the journal by hand. But
        `site_opened` reaches `SiteLayers.ensure_tables()` in the same
        open, which creates an empty `GPKG_FILE`; from then on the
        "already exists" branch above fires forever and the legacy package
        could never be adopted, even by a user who did exactly what the
        message said. The branch written to protect the picks made losing
        them permanent, and printed advice that could not work.

        Using the package where it is fixes that at the root, because no
        competing file is ever created. It is also simply more correct:
        *opening* a database with a hot journal is what SQLite recovery is
        for, and only *renaming* it was ever unsafe. The user's picks are
        on screen on the first open, the ordinary clean close checkpoints
        the journal away, and the next open adopts with nothing asked of
        anyone. Rejected alongside it: suppressing the on-demand creation
        for that open (the site comes up with no layers at all, which is a
        worse answer to "your package is fine, we just cannot rename it");
        and treating an empty `GPKG_FILE` as adoptable (it needs a second
        handle on the package to decide what "empty" means, and then a
        two-step rename that can half-complete).

        Both names are checked, not just the legacy one: renaming *onto* a
        name that already has a journal beside it hands the rescued
        package a foreign one, which SQLite then replays over it --
        observed as an adopted package that logged success and then would
        not open, showing only the unrelated journal's tables. Nothing in
        the plugin can create that state on its own, but the bug fixed
        just above is exactly what pushed users into renaming by hand, and
        `mv` touches no sidecars.

        The alternative to a fixed basename, considered and rejected, was
        recording the package filename in the survey JSON. That is
        `nsgeo.project`'s format -- portable, human-readable, and shared
        with anything else that ever reads a site -- so it would push a
        QGIS-plugin-private detail into the core's contract, and leave a
        recorded name that can itself go stale when the file is renamed by
        hand. A fixed basename cannot.

        Runs for `new_site()` too. One behaviour rather than two:
        `new_site()` refuses a folder that already holds a survey file, so
        a legacy package there belongs to a project whose JSON is gone, and
        adopting it hands those picks back instead of stranding them beside
        a fresh empty package.
        """
        target = root / GPKG_FILE
        try:
            legacy = sorted(
                p for p in root.glob(f"*{_GPKG_SUFFIX}") if p.name != GPKG_FILE and p.is_file()
            )
        except OSError as exc:
            # Opening a site must not fail because its directory could not
            # be listed; the package itself is created on demand later.
            _log(f"could not check {root} for an older site package: {exc}")
            return target
        if not legacy:
            return target
        names = ", ".join(p.name for p in legacy)
        if target.exists():
            _log(
                f"{root} also holds {names}, which this site does not use; "
                f"its data is only reachable by renaming it to {GPKG_FILE} by hand"
            )
            return target
        if len(legacy) > 1:
            _log(
                f"{root} holds more than one older site package ({names}) and none "
                f"named {GPKG_FILE}; not guessing which one belongs to this site -- "
                f"rename the right one to {GPKG_FILE} by hand",
                Qgis.MessageLevel.Critical,
            )
            return target
        found = legacy[0]
        journals = self._sqlite_journals(found) + self._sqlite_journals(target)
        if journals:
            _log(
                f"{', '.join(j.name for j in journals)} is present, so a SQLite database "
                f"here was not closed cleanly; renaming one away from its journal discards "
                f"everything committed since the last checkpoint. Using {found.name} where "
                f"it is for now -- your picks are all there. It will be renamed to "
                f"{GPKG_FILE} automatically the next time this site is opened after a "
                f"clean close."
            )
            return found
        try:
            found.rename(target)
        except OSError as exc:
            # Still readable where it is, so use it there rather than
            # resolving to a name that does not exist and coming up empty.
            _log(
                f"could not rename {found.name} to {GPKG_FILE}: {exc}; "
                f"using it where it is instead",
                Qgis.MessageLevel.Critical,
            )
            return found
        _log(
            f"adopted {found.name} as {GPKG_FILE}: a site package is no longer "
            "named after its folder, so a renamed folder no longer orphans its picks",
            Qgis.MessageLevel.Info,
        )
        return target

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
        self._gpkg_path = None
        self._lines_by_key = {}
        self._profiles.clear()
        self._channel.clear()
        self._current_key = None
        self._current_trace = -1
        self._selection = (-1, -1)
        self._preview_key = None
        self._preview_trace = -1
        self._allow_absolute = False
        self._set_dirty(False)
        if had_current_line:
            # Same "no line is current" transition remove_line() reports;
            # a widget bound only to line_opened must not keep a stale line.
            self.line_opened.emit("")
        self.site_closed.emit()

    # ---- keys and lookups -------------------------------------------------
    def line_key(self, line: Line) -> str:
        # The `line_key` called here is `nsgeo.project`'s module-level
        # function, not this method: a class attribute never shadows a
        # global inside a method body. Sharing the name is the point --
        # the session must key by exactly what `save_site` writes and
        # `load_site` reads back, and there is one function for all three.
        #
        # Always computable; whether an absolute key may be *saved* is
        # decided in save() via allow_absolute.
        return line_key(line.path, self.root, allow_absolute=True)

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
        # The removed line can be current, previewed, or both at once --
        # the session never forbids preview_key == current_key, that is a
        # UI-level convention (ProfileDock's), not a rule enforced here.
        # Both fields are reset here directly rather than through
        # clear_preview(): that helper couples its reset to its own
        # emission, and when a line is both current and previewed,
        # clearing one field at a time would leave the OTHER still naming
        # a line already gone from _lines_by_key while its signal fires.
        # So both resets happen first, and only then does anything emit.
        dropped_current = self._current_key == key
        dropped_preview = self._preview_key == key
        if dropped_current:
            self._current_key = None
            self._current_trace = -1
            self._selection = (-1, -1)
        if dropped_preview:
            self._preview_key = None
            self._preview_trace = -1
        # Every field is reset BEFORE any emission. A slot reading
        # display_key during either signal must never see the key that was
        # just deleted.
        #
        # Order between the two is load-bearing, not arbitrary: line_opened
        # first, THEN preview_changed. ProfileDock (Task 2) keeps its own
        # _working_key and, on preview_changed telling it the preview
        # ended, re-renders that key. If preview_changed fired first, that
        # would run while the dock's _working_key still named the line
        # being deleted here -> line_for_key(deleted) -> KeyError inside a
        # slot -> qFatal() in the LTR container. Emitting line_opened("")
        # first makes the dock drop _working_key before anything asks it
        # to render.
        if dropped_current:
            self.line_opened.emit("")
        if dropped_preview:
            self.preview_changed.emit("", -1)
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
            # Re-selecting the line already open -- reachable in normal
            # use, not just a defensive corner case: Task 5 promotes a
            # line from the attribute table's selectionChanged, which
            # fires there too, with the pointer nowhere near the map. A
            # stale preview must not survive this. Unlike the main path
            # below, there is no line_opened to follow and drive a
            # render, so THIS branch emits -- clear_preview() is exactly
            # right. Do not "tidy" the two branches to match; the
            # asymmetry is deliberate.
            self.clear_preview()
            return
        self._current_key = key
        self._current_trace = -1
        self._selection = (-1, -1)
        # Promotion ends the preview. Reset WITHOUT emitting
        # preview_changed: a listener told "preview cleared" would snap the
        # view back to the OLD working line, and be told to render the new
        # one an instant later by line_opened -- two renders and a visible
        # flash for one user gesture. line_opened is the single signal that
        # drives that render, and ProfileDock clears its own preview on it.
        self._preview_key = None
        self._preview_trace = -1
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

    # ---- preview (spec §3.3) ----------------------------------------------
    def set_preview(self, key: str | None, trace: int = -1) -> None:
        """Set what the pointer is over. NOT a write target, ever.

        `current_key` is not merely what is displayed: `replace_step`,
        `apply_to_grid`, `apply_preset` and `remove_step` all resolve
        their target through it, and the processing dock binds to it. If
        hovering the map moved `current_key`, moving the pointer would
        silently repoint every destructive operation in the plugin -- edit
        a parameter, and it lands on a line the user only passed over,
        with no error and no cue. That is C2's defect class exactly, and
        C2 is already on this codebase's record. Hence a second, weaker
        notion that cannot reach any of those paths.

        Never sets dirty: a preview is a view state, not an edit. Never
        touches `_current_key`, `_current_trace` or `_selection`.
        """
        if key is None:
            self.clear_preview()
            return
        line = self.line_for_key(key)  # raises KeyError before anything changes
        index = -1 if trace < 0 else max(0, min(int(trace), line.n_traces - 1))
        if (key, index) == (self._preview_key, self._preview_trace):
            return  # loop guard: a marker update that round-trips is a no-op
        self._preview_key, self._preview_trace = key, index
        self.preview_changed.emit(key, index)

    def clear_preview(self) -> None:
        if self._preview_key is None and self._preview_trace == -1:
            return
        self._preview_key, self._preview_trace = None, -1
        self.preview_changed.emit("", -1)
