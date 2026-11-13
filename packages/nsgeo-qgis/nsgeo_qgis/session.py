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

import copy
import dataclasses
import datetime as _dt
import json
import math
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from nsgeo.geometry import Grid, GridPlacement
from nsgeo.model import Cut, Line, Profile, Site, is_cut_key
from nsgeo.processing import Radargram, StepStack, retime_ns
from nsgeo.project import ProjectError, line_key, load_site, save_site
from nsgeo.slices import NORMALISATION_METHODS
from nsgeo.velocity import VelocityModel, resolve_velocity
from nsgeo.velocity_fit import StoredFit
from nsgeo.velocity_source import SourceFit, VelocitySource
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QObject, pyqtSignal

from nsgeo_qgis.line_edit import (
    CHANGED_ELSEWHERE,
    REMOVED,
    SAME_M,
    START_TOLERANCE_M,
    EditOutcome,
    GridEditReport,
    LineEdit,
    Skipped,
    followed_length,
    is_fitted,
    length_along,
    same_placement,
    span_m,
    width_across,
)

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


@dataclasses.dataclass(frozen=True)
class Pick:
    """One authored pick: a trace and a two-way time on one line.

    Time is the truth. `distance_m`, `depth_m` and `velocity_m_ns` are
    conveniences that can be recomputed from the line's geometry and its
    resolved velocity model, and are `None` when the line cannot supply
    them (a time-triggered acquisition has no distance axis).

    `feature_id` and `seq` are written null by M8 and exist now so that a
    horizon later is an ordered run of existing picks sharing a
    `feature_id`, needing no migration of an authored table (spec §4.2).
    `picks` is the one table `survey.nsgeo.json` cannot regenerate, and
    this project has already had to repair its storage twice; the cheap
    time to add these columns is before there are horizons to migrate.
    """

    line_key: str
    trace: int
    time_ns: float
    distance_m: float | None
    depth_m: float | None
    velocity_m_ns: float | None
    stack_json: str
    note: str
    created: str
    feature_id: str | None = None
    seq: int | None = None
    # #97: `time_ns` is measured from this radar-clock time. None means the
    # radar clock itself (a row written before the column existed).
    zero_ns: float | None = None

    @property
    def radar_ns(self) -> float:
        """The pick's time on the radar clock, the one that never moves."""
        return retime_ns(self.time_ns, self.zero_ns or 0.0, 0.0)


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


#: The slice scopes that each keep their own colours (#180).
COLOUR_SCOPES = ("grid", "site")


def _check_colour_scope(scope: str) -> None:
    if scope not in COLOUR_SCOPES:
        raise ValueError(f"unknown slice scope {scope!r}; expected one of {COLOUR_SCOPES}")


def _merge_resolution(
    old: dict[str, float | str], **fields: float | str | None
) -> dict[str, float | str] | None:
    """`old` with the non-None `fields` laid over it, or None when that
    changes nothing -- the caller's cue not to mark the survey dirty (#71).
    A string (the interpolation method) stays one; a number becomes a float."""
    new = {
        **old,
        **{k: v if isinstance(v, str) else float(v) for k, v in fields.items() if v is not None},
    }
    return None if new == old else new


def _fit_number(fit_id: str) -> int:
    """N of an id of the form `fit-N`; any other id counts as 0."""
    match = re.fullmatch(r"fit-(\d+)", fit_id)
    return int(match.group(1)) if match else 0


class SiteSession(QObject):
    site_opened = pyqtSignal()
    site_closed = pyqtSignal()
    dirty_changed = pyqtSignal(bool)
    grids_changed = pyqtSignal()
    lines_changed = pyqtSignal()
    cuts_changed = pyqtSignal()
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
        self._open_serial = 0
        # Set by SiteLayers' own constructor (see set_pick_store). None
        # until then, which is the normal state of a session built by a
        # test that has no layers at all.
        self._pick_store: Any | None = None

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

    def keys_on_grid(self, grid_id: str) -> list[str]:
        """The keys of every line placed on `grid_id`, in survey order.
        `KeyError` for a grid the site does not have."""
        self.grid(grid_id)
        return [
            key
            for key, line in self._lines_by_key.items()
            if getattr(line.placement, "grid_id", None) == grid_id
        ]

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

    # ---- the site's CRS ---------------------------------------------------
    def site_crs(self) -> str | None:
        """The CRS the site is in: its own, else the first grid's, else None (P9)."""
        site = self._site
        return None if site is None else site.effective_crs()

    def set_site_crs(self, crs: str) -> None:
        """Give a site with no CRS one. It is never changed once set."""
        site = self._require_site()
        current = self.site_crs()
        if current is not None:
            raise ValueError(f"the site already uses {current}")
        site.crs = crs
        self._set_dirty(True)

    # ---- grids ------------------------------------------------------------
    def add_grid(self, grid: Grid) -> None:
        site = self._require_site()
        if any(g.id == grid.id for g in site.grids):
            raise ValueError(f"a grid with id {grid.id!r} already exists")
        site.grids.append(grid)
        self._set_dirty(True)
        self.grids_changed.emit()

    def replace_grid(self, grid: Grid) -> GridEditReport:
        """Swap in an edited grid. A reversed line starts at the far edge,
        so when the grid's length along an axis changes, every reversed line
        on that axis moves with the edge, keeping its inset (line editing
        spec §3 call 6 for the message; the rule itself is decision 4 and
        §4.3). A fitted line, of either direction, is fitted again to the
        new length instead (placement corrections plan, call 7), and is
        counted once, as refitted, never as moved. Lines whose offset now
        lies outside a changed width are reported, not moved. All of it
        happens before anything is emitted, then one `grids_changed` and
        one `lines_changed`."""
        site = self._require_site()
        for i, g in enumerate(site.grids):
            if g.id == grid.id:
                old = g
                site.grids[i] = grid
                break
        else:
            raise KeyError(f"no grid with id {grid.id!r}")
        moved: list[tuple[str, float, int]] = []
        refitted: list[tuple[str, float, int]] = []
        outside: list[str] = []
        for axis in ("y", "x"):
            old_len, new_len = length_along(old, axis), length_along(grid, axis)
            old_wid, new_wid = width_across(old, axis), width_across(grid, axis)
            on_axis = [
                (key, line)
                for key, line in self._lines_by_key.items()
                if isinstance(line.placement, GridPlacement)
                and line.placement.grid_id == grid.id
                and line.placement.axis == axis
            ]
            if abs(new_len - old_len) > SAME_M:
                count = refit = 0
                for key, line in on_axis:
                    span = span_m(line.n_traces, line.header.traces_per_metre)
                    fitted = span > 0 and is_fitted(line.placement, span, old_len)
                    placement = followed_length(line.placement, old_len, new_len, span)
                    if not same_placement(placement, line.placement):
                        self._replace_line(key, dataclasses.replace(line, placement=placement))
                    count += line.placement.direction == -1 and not fitted
                    refit += fitted
                if count:
                    moved.append((axis, new_len, count))
                if refit:
                    refitted.append((axis, new_len, refit))
            if abs(new_wid - old_wid) > SAME_M:
                for key, line in on_axis:
                    offset = line.placement.offset
                    if offset < -START_TOLERANCE_M or offset > new_wid + START_TOLERANCE_M:
                        outside.append(line.placement.label or Path(key).stem)
        self._set_dirty(True)
        self.grids_changed.emit()
        self.lines_changed.emit()  # line geometry follows the frame
        return GridEditReport(grid.id, tuple(moved), tuple(outside), tuple(refitted))

    def _replace_line(self, key: str, new_line: Line) -> None:
        """Put `new_line` where the line under `key` stood, in both indexes.
        Same key: only the object changed."""
        site = self._require_site()
        old = self._lines_by_key[key]
        site.lines[site.lines.index(old)] = new_line
        self._lines_by_key[key] = new_line

    def remove_grid(self, grid_id: str, *, with_lines: bool = False) -> None:
        """Remove a grid. One that still has lines is refused unless
        `with_lines`, which removes those lines with it in the same change
        (#31): one dirty mark, one `grids_changed`, and one `lines_changed`
        if there were any lines to go. The grid's remembered slice source
        and its site-view entry are forgotten with it (M12)."""
        site = self._require_site()
        grid = self.grid(grid_id)
        keys = self.keys_on_grid(grid_id)
        if keys and not with_lines:
            raise ValueError(f"grid {grid_id!r} still has {len(keys)} line(s); remove them first")
        site.grids.remove(grid)
        # M12: the grid's remembered slice source and its place in the
        # site view go with it, so neither outlives the grid on save.
        site.slice_sources.pop(grid_id, None)
        # A cut on a removed grid would make validate() refuse every save
        # (cut spec §4.2). Its picks stay: they are authored data.
        gone_cuts = [c for c in site.cuts if c.grid_id == grid_id]
        site.cuts = [c for c in site.cuts if c.grid_id != grid_id]
        cut_keys_gone = [c.key for c in gone_cuts]
        if grid_id in site.site_view.get("grids", []):
            site.site_view["grids"] = [g for g in site.site_view["grids"] if g != grid_id]
        lines_dropped = self._drop_lines(keys)
        cuts_dropped = self._reset_cuts(cut_keys_gone)
        self._set_dirty(True)
        self._announce_dropped(
            lines_dropped[0] or cuts_dropped[0], lines_dropped[1] or cuts_dropped[1]
        )
        self.grids_changed.emit()
        if keys:
            self.lines_changed.emit()
        if gone_cuts:
            self.cuts_changed.emit()

    def set_grid_velocity(self, grid_id: str, model: VelocityModel | None) -> None:
        # The report is empty: a velocity change moves no line.
        # A bare number has no source: the record goes (grid velocity spec §7.2).
        self.replace_grid(
            dataclasses.replace(self.grid(grid_id), velocity=model, velocity_source=None)
        )

    def apply_grid_velocity(
        self, grid_id: str, model: VelocityModel | None, source: VelocitySource | None
    ) -> None:
        """Set a grid's velocity and the record of where it came from, in one
        `grids_changed`. Nothing changes, signals or marks the survey dirty when
        the grid already holds both (an untouched Apply, spec 7.2 rule 1)."""
        grid = self.grid(grid_id)
        if grid.velocity == model and grid.velocity_source == source:
            return
        self.replace_grid(dataclasses.replace(grid, velocity=model, velocity_source=source))

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
        self.remove_lines([key])

    def remove_lines(self, keys: Iterable[str]) -> None:
        """Remove every line in `keys`, with their stacks, as one change:
        one dirty mark and one `lines_changed`, however many lines (#31 --
        each `lines_changed` rebuilds the survey tree and the map layers).

        All or nothing: every key is checked before anything is removed,
        so an unknown key raises `KeyError` with the site untouched.
        """
        self._require_site()
        unique = list(dict.fromkeys(keys))
        for key in unique:
            self.line_for_key(key)
        if not unique:
            return
        dropped = self._drop_lines(unique)
        self._set_dirty(True)
        self._announce_dropped(*dropped)
        self.lines_changed.emit()

    def _drop_lines(self, keys: list[str]) -> tuple[bool, bool]:
        """Take `keys` (all known) out of the site and every per-line
        cache, and reset the current and preview lines if they were among
        them. Emits nothing; returns (dropped current, dropped preview)
        for `_announce_dropped`.

        The removed lines can include the current line, the previewed
        line, or one line that is both -- the session never forbids
        preview_key == current_key, that is a UI-level convention
        (ProfileDock's), not a rule enforced here. Both fields are reset
        here directly rather than through clear_preview(): that helper
        couples its reset to its own emission, and when a line is both
        current and previewed, clearing one field at a time would leave
        the OTHER still naming a line already gone from _lines_by_key
        while its signal fires. So every reset happens here, and only the
        caller emits, afterwards.
        """
        site = self._require_site()
        going = {id(self._lines_by_key[key]) for key in keys}
        site.lines[:] = [ln for ln in site.lines if id(ln) not in going]
        for key in keys:
            del self._lines_by_key[key]
            site.stacks.pop(key, None)
            self._profiles.pop(key, None)
            self._channel.pop(key, None)
        dropped_current = self._current_key in keys
        dropped_preview = self._preview_key in keys
        if dropped_current:
            self._current_key = None
            self._current_trace = -1
            self._selection = (-1, -1)
        if dropped_preview:
            self._preview_key = None
            self._preview_trace = -1
        return dropped_current, dropped_preview

    def _announce_dropped(self, dropped_current: bool, dropped_preview: bool) -> None:
        """Report what `_drop_lines` reset, after every field is already
        reset: a slot reading display_key during either signal must never
        see a key that was just deleted.

        Order between the two is load-bearing, not arbitrary: line_opened
        first, THEN preview_changed. ProfileDock (Task 2) keeps its own
        _working_key and, on preview_changed telling it the preview
        ended, re-renders that key. If preview_changed fired first, that
        would run while the dock's _working_key still named a line
        already deleted -> line_for_key(deleted) -> KeyError inside a
        slot -> qFatal() in the LTR container. Emitting line_opened("")
        first makes the dock drop _working_key before anything asks it
        to render.
        """
        if dropped_current:
            self.line_opened.emit("")
        if dropped_preview:
            self.preview_changed.emit("", -1)

    def edit_lines(
        self,
        edits: Sequence[LineEdit],
        *,
        grid_id: str | None = None,
        order: Sequence[str] | None = None,
    ) -> EditOutcome:
        """Apply every edit, and an optional survey order for `grid_id`, as
        one change: one dirty mark and one `lines_changed` (line editing spec
        §3 call 14). The table that built the edits may be stale, so each
        edit is re-checked here and a line is skipped, and named in the
        outcome, when it was removed (`REMOVED`), when its placement is no
        longer the one the table saw (`CHANGED_ELSEWHERE`), or when its new
        grid no longer exists. The rest still apply.

        A key is the file path, so editing never changes one: the current
        and preview lines, stacks, profiles, velocity, fits and channels all
        stay attached. `ValueError` for `order` without `grid_id` or a key
        edited twice; `KeyError` for an unknown `grid_id`, before anything
        changes."""
        site = self._require_site()
        if order is not None and grid_id is None:
            raise ValueError("an order needs the grid it orders")
        keys = [e.key for e in edits]
        if len(set(keys)) != len(keys):
            raise ValueError("a line may be edited only once per change")
        # A repeated key would fill two slots with one line and drop another
        # from the survey file, and the strict zip below only notices after
        # the slots are written (line editing spec §3 call 14).
        if order is not None and len(set(order)) != len(order):
            raise ValueError("an order may name a line only once")
        if grid_id is not None:
            self.grid(grid_id)
        frames = site.frames
        skipped: list[Skipped] = []
        applied: list[tuple[str, GridPlacement, GridPlacement]] = []  # key, old, new
        for edit in edits:
            label = edit.seen.label or Path(edit.key).stem
            line = self._lines_by_key.get(edit.key)
            if line is None:
                skipped.append(Skipped(edit.key, label, REMOVED))
                continue
            current = line.placement
            if not isinstance(current, GridPlacement) or current != edit.seen:
                skipped.append(Skipped(edit.key, label, CHANGED_ELSEWHERE))
                continue
            try:
                new = edit.placed(frames)
            except KeyError:
                gone = edit.grid_id or current.grid_id
                skipped.append(Skipped(edit.key, label, f"its new grid {gone!r} no longer exists"))
                continue
            if same_placement(new, current):
                continue
            applied.append((edit.key, current, new))
        for key, _, new in applied:
            line = self._lines_by_key[key]
            self._replace_line(key, dataclasses.replace(line, placement=new))
        # A line that changed grid joins the new grid at the end of the survey
        # order, the way an imported line does, and leaves the old grid's
        # remembered slice lines.
        moved = [key for key, old, new in applied if new.grid_id != old.grid_id]
        for key, old, new in applied:
            if new.grid_id == old.grid_id:
                continue
            remembered = site.slice_sources.get(old.grid_id, {}).get("lines")
            if isinstance(remembered, list):
                remembered[:] = [k for k in remembered if k != key]
        if moved:
            by_object = {id(line): key for key, line in self._lines_by_key.items()}
            going = set(moved)
            site.lines[:] = [ln for ln in site.lines if by_object[id(ln)] not in going] + [
                self._lines_by_key[k] for k in by_object.values() if k in going
            ]
        reordered = False
        if order is not None and grid_id is not None:
            on = self.keys_on_grid(grid_id)
            want = [k for k in order if k in on] + [k for k in on if k not in order]
            if want != on:
                by_key = dict(self._lines_by_key)
                slots = [
                    i
                    for i, ln in enumerate(site.lines)
                    if getattr(ln.placement, "grid_id", None) == grid_id
                ]
                for i, k in zip(slots, want, strict=True):
                    site.lines[i] = by_key[k]
                reordered = True
        # Rebuilt in survey order from the lines themselves; a key is never
        # recomputed (the file path is the key).
        key_of = {id(line): key for key, line in self._lines_by_key.items()}
        rebuilt = {key_of[id(ln)]: ln for ln in site.lines}
        self._lines_by_key.clear()
        self._lines_by_key.update(rebuilt)
        if applied or reordered:
            self._set_dirty(True)
            self.lines_changed.emit()
        return EditOutcome(
            changed=tuple(key for key, _, _ in applied),
            reordered=reordered,
            skipped=tuple(skipped),
        )

    def move_lines(self, keys: Iterable[str], grid_id: str) -> EditOutcome:
        """Move lines to another grid, keeping each one's inset from the edge
        it starts at (line editing spec §3 calls 7 and 1). Lines already on
        `grid_id` are left out; a key that is gone is skipped and named."""
        self._require_site()
        self.grid(grid_id)
        edits: list[LineEdit] = []
        skipped: list[Skipped] = []
        for key in dict.fromkeys(keys):
            line = self._lines_by_key.get(key)
            if line is None:
                skipped.append(Skipped(key, Path(key).stem, REMOVED))
            elif isinstance(line.placement, GridPlacement) and line.placement.grid_id != grid_id:
                edits.append(LineEdit(key, seen=line.placement, grid_id=grid_id))
        outcome = self.edit_lines(edits)
        return dataclasses.replace(outcome, skipped=tuple(skipped) + outcome.skipped)

    def set_line_velocity(self, key: str, model: VelocityModel | None) -> None:
        site = self._require_site()
        line = self.line_for_key(key)
        # A bare number has no source: the record goes (grid velocity spec §7.2).
        new_line = dataclasses.replace(line, velocity=model, velocity_source=None)
        site.lines[site.lines.index(line)] = new_line
        self._lines_by_key[key] = new_line  # same key: only the object changed
        self._set_dirty(True)
        self.lines_changed.emit()

    def apply_line_velocity(
        self, key: str, model: VelocityModel | None, source: VelocitySource | None
    ) -> None:
        """Set a line's velocity and the record of where it came from, in one
        `lines_changed`. Nothing changes, signals or marks the survey dirty when
        the line already holds both (an untouched Apply, spec 7.2 rule 1)."""
        site = self._require_site()
        line = self.line_for_key(key)
        if line.velocity == model and line.velocity_source == source:
            return
        new_line = dataclasses.replace(line, velocity=model, velocity_source=source)
        site.lines[site.lines.index(line)] = new_line
        self._lines_by_key[key] = new_line
        self._set_dirty(True)
        self.lines_changed.emit()

    def add_velocity_fit(self, key: str, fit: StoredFit) -> str:
        """Store a hyperbola fit on the line under a fresh id and return it.
        Stores only: no velocity changes (`set_line_velocity` does that)."""
        site = self._require_site()
        line = self.line_for_key(key)
        highest = max((_fit_number(i) for i in line.velocity_fits), default=0)
        n = max(line.fit_serial, highest) + 1
        fit_id = f"fit-{n}"
        new_line = dataclasses.replace(
            line, velocity_fits={**line.velocity_fits, fit_id: fit}, fit_serial=n
        )
        site.lines[site.lines.index(line)] = new_line
        self._lines_by_key[key] = new_line
        self._set_dirty(True)
        self.lines_changed.emit()
        return fit_id

    def remove_velocity_fit(self, key: str, fit_id: str) -> None:
        """Delete a stored fit. A velocity it set stays, and so does the record
        of it: the record copies the fit's numbers, so it stays reproducible
        and shows the member as deleted (grid velocity spec §7.3)."""
        site = self._require_site()
        line = self.line_for_key(key)
        if fit_id not in line.velocity_fits:
            raise KeyError(f"line {key!r} has no stored fit {fit_id!r}")
        fits = {i: f for i, f in line.velocity_fits.items() if i != fit_id}
        new_line = dataclasses.replace(line, velocity_fits=fits)
        site.lines[site.lines.index(line)] = new_line
        self._lines_by_key[key] = new_line
        self._set_dirty(True)
        self.lines_changed.emit()

    def member_state(self, member: SourceFit, grid_id: str | None = None) -> str:
        """Where a record's member stands now: `"present"`, `"deleted"`,
        `"line removed"`, `f"line moved to grid {gid}"` (only when `grid_id` is
        given and the line is on another grid) or `"line moved off this grid"`
        (the line is no longer on any grid)."""
        self._require_site()
        line = self._lines_by_key.get(member.line_key)
        if line is None:
            return "line removed"
        if not any(member.names(i, f) for i, f in line.velocity_fits.items()):
            return "deleted"
        if grid_id is not None:
            now = getattr(line.placement, "grid_id", None)
            if now is None:
                return "line moved off this grid"
            if now != grid_id:
                return f"line moved to grid {now}"
        return "present"

    def member_fit(self, member: SourceFit) -> StoredFit | None:
        """The stored fit `member` copied, or None unless it is still `"present"`."""
        self._require_site()
        line = self._lines_by_key.get(member.line_key)
        if line is None:
            return None
        fit = line.velocity_fits.get(member.fit_id)
        return fit if fit is not None and member.names(member.fit_id, fit) else None

    def resolved_velocity(self, key: str) -> VelocityModel:
        if is_cut_key(key):  # a cut takes its grid's velocity, never a line's (cut spec call 16)
            return self.grid_depth_velocity(self.cut_for_key(key).grid_id)
        line = self.line_for_key(key)
        return resolve_velocity(line, self.grid_for_line(line))

    # ---- cuts (cut spec §4.2) ------------------------------------------------
    def cut_keys(self) -> list[str]:
        """Every cut's key, in drawing order. `keys()` stays lines-only."""
        return [c.key for c in self._require_site().cuts]

    def cut_keys_on_grid(self, grid_id: str) -> list[str]:
        """The keys of the cuts drawn on `grid_id`, in drawing order."""
        return [c.key for c in self._require_site().cuts if c.grid_id == grid_id]

    def _require_key(self, key: str) -> None:
        """`KeyError` unless `key` names a line or a cut."""
        if is_cut_key(key):
            self.cut_for_key(key)
        else:
            self.line_for_key(key)

    def _reset_cuts(self, keys: Sequence[str]) -> tuple[bool, bool]:
        """Reset the working and previewed item if it is one of `keys`.

        Emits nothing; returns (dropped current, dropped preview) for
        `_announce_dropped`, like `_drop_lines`. A caller that drops lines
        and cuts together resets both first and announces once, so
        `line_opened` always precedes `preview_changed`.
        """
        dropped_current = self._current_key in keys
        dropped_preview = self._preview_key in keys
        if dropped_current:
            self._current_key = None
            self._current_trace = -1
            self._selection = (-1, -1)
        if dropped_preview:
            self._preview_key = None
            self._preview_trace = -1
        return dropped_current, dropped_preview

    def cut_for_key(self, key: str) -> Cut:
        for cut in self._require_site().cuts:
            if cut.key == key:
                return cut
        raise KeyError(f"no cut with key {key!r}")

    def add_cut(self, grid_id: str, vertices: Sequence[tuple[float, float]]) -> str:
        """Add a cut on `grid_id` (vertices in grid metres) and return its key.

        `KeyError` for an unknown grid, `ValueError` from `Cut.new` for fewer
        than two different points. The name is `Cut {n}`, one past the highest
        `Cut <n>` there is, so a deleted name is not handed out again while a
        higher one stays.
        """
        site = self._require_site()
        self.grid(grid_id)
        highest = 0
        for existing in site.cuts:
            m = re.fullmatch(r"Cut (\d+)", existing.name)
            if m:
                highest = max(highest, int(m.group(1)))
        cut = Cut.new(grid_id, vertices, f"Cut {highest + 1}")
        site.cuts.append(cut)
        self._set_dirty(True)
        self.cuts_changed.emit()
        return cut.key

    def rename_cut(self, key: str, name: str) -> None:
        site = self._require_site()
        name = name.strip()
        if not name:
            raise ValueError("a cut needs a name")
        old = self.cut_for_key(key)
        site.cuts[site.cuts.index(old)] = dataclasses.replace(old, name=name)
        self._set_dirty(True)
        self.cuts_changed.emit()

    def remove_cut(self, key: str) -> None:
        """Delete a cut. Its picks stay where they are (picks are authored data)."""
        site = self._require_site()
        site.cuts.remove(self.cut_for_key(key))
        self._set_dirty(True)
        self._announce_dropped(*self._reset_cuts([key]))
        self.cuts_changed.emit()

    def grid_depth_velocity(self, grid_id: str) -> VelocityModel:
        """The velocity every cut and every slice on `grid_id` uses (cut spec
        call 16; grid velocity spec 10): the grid's own, else the HEADER
        velocity of the grid's first line in survey order. That line's own
        override is ignored: a line override must never move a cut pick or a
        slice's depths. `KeyError` when the grid has neither."""
        grid = self.grid(grid_id)
        if grid.velocity is not None:
            return grid.velocity
        keys = self.keys_on_grid(grid_id)
        if not keys:
            raise KeyError(f"grid {grid_id!r} has no velocity and no line to take one from")
        return VelocityModel.from_dielectric(self.line_for_key(keys[0]).header.epsr)

    # ---- stacks -----------------------------------------------------------
    def stack_for(self, key: str, *, insert: bool = True) -> StepStack:
        """The `StepStack` for `key`, building an empty one (with its
        source attached from whatever profiles are cached for `key`) the
        first time anything asks for it.

        `insert=False` builds and returns that same stack WITHOUT storing
        it in `site.stacks` -- for a read that must not otherwise plant an
        empty stack for a line nobody has actually edited (Finding 4, M7
        final review: `set_profiles` and `ProfileDock.current_radargram`
        both use it on the preview path, which spec §3.3 says must touch
        nothing). Every write path here (`append_step` and its siblings)
        keeps calling with the default `insert=True`, exactly as before
        this parameter existed.
        """
        site = self._require_site()
        stack = site.stacks.get(key)
        if stack is None:
            self.line_for_key(key)  # KeyError for unknown lines
            stack = StepStack()
            if insert:
                site.stacks[key] = stack
            self._attach_source(key, stack)
        return stack

    def line_zero(self, key: str, *, load: bool = False) -> float | None:
        """The radar-clock time the line's own stack calls 0.

        0.0 with no enabled time_zero step (nothing is loaded for that). The
        source's answer once one is attached. With no source, None, unless
        `load` reads the line and runs a copy of the stack. None on any
        failure, which is logged: this never raises, and never plants a stack.

        A cut has no zero of its own: its times are on its cube's clock
        (cut spec call 18), so it answers None at once and logs nothing.
        """
        if is_cut_key(key):
            return None
        try:
            stack = self.stack_for(key, insert=False)
            if not stack.sets_time_zero():
                return 0.0
            if stack.source is not None:
                return float(stack.zero_ns())
            if not load:
                return None
            profiles = self.line_for_key(key).load()
            probe = StepStack.from_dicts(stack.to_dicts())
            probe.source = Radargram.from_profile(profiles[self.channel(key)])
            return float(probe.zero_ns())
        except Exception as exc:  # noqa: BLE001 -- a read must not raise; the caller falls back
            _log(f"could not find where line {key} has its time zero: {exc}")
            return None

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

    # ---- cubes --------------------------------------------------------------
    def record_cube(self, cube_id: str, record: dict[str, Any]) -> None:
        """Record a saved slice cube's recipe in `site.cubes[cube_id]`.

        Cheap cluster (M11 final review): `plugin.save_cube` used to
        write `session.site.cubes[cube_id] = record` and then call
        `session._set_dirty(True)` directly -- the only external caller
        of that private method anywhere in this repo. Every other site
        mutation goes through a `SiteSession` method of its own (see
        `save_preset` immediately above, for the closest parallel); this
        is that method for cubes.
        """
        self._require_site().cubes[cube_id] = dict(record)
        self._set_dirty(True)

    # ---- slice sources and the site view ---------------------------------------
    def slice_source(self, grid_id: str) -> dict[str, Any] | None:
        """A copy of the grid's remembered slice source, or None."""
        entry = self._require_site().slice_sources.get(grid_id)
        return None if entry is None else copy.deepcopy(entry)

    def _update_source(self, grid_id: str, **changes: Any) -> None:
        sources = self._require_site().slice_sources
        old = sources.get(grid_id)
        new = {**(old or {}), **changes}
        if new == old:
            return
        sources[grid_id] = new
        self._set_dirty(True)

    def remember_slice_source(
        self, grid_id: str, *, preset: str, lines: tuple[str, ...] | None
    ) -> None:
        """Remember the user's preset and line choice for a grid (`lines=None`
        is "every line"). Keeps an existing gain."""
        self._update_source(grid_id, preset=preset, lines=None if lines is None else list(lines))

    def slice_resolution(self, grid_id: str) -> dict[str, float | str]:
        """A copy of the grid's remembered resolution (#71), or {}."""
        entry = self._require_site().slice_sources.get(grid_id) or {}
        return dict(entry.get("resolution", {}))

    def remember_slice_resolution(
        self,
        grid_id: str,
        *,
        cell: float | None = None,
        dz_ns: float | None = None,
        t0_ns: float | None = None,
        t1_ns: float | None = None,
        method: str | None = None,
        max_distance_spacings: float | None = None,
        smooth_x_m: float | None = None,
        smooth_y_m: float | None = None,
    ) -> None:
        """Merge the given resolution fields into the grid's record (#71);
        None leaves a field as it is. Keeps the preset, lines and gain."""
        merged = _merge_resolution(
            self.slice_resolution(grid_id),
            cell=cell,
            dz_ns=dz_ns,
            t0_ns=t0_ns,
            t1_ns=t1_ns,
            method=method,
            max_distance_spacings=max_distance_spacings,
            smooth_x_m=smooth_x_m,
            smooth_y_m=smooth_y_m,
        )
        if merged is not None:
            self._update_source(grid_id, resolution=merged)

    def grid_gain(self, grid_id: str) -> float:
        entry = self._require_site().slice_sources.get(grid_id, {})
        return float(entry.get("gain", 1.0))

    def set_grid_gain(self, grid_id: str, gain: float) -> None:
        if not (math.isfinite(gain) and gain > 0):
            raise ValueError(f"gain must be a positive number, got {gain!r}")
        self._update_source(grid_id, gain=float(gain))

    def site_view(self) -> dict[str, Any]:
        """A copy of the remembered site-view choices."""
        return copy.deepcopy(self._require_site().site_view)

    def set_site_view(
        self,
        *,
        grids: tuple[str, ...] | None = None,
        transform: str | None = None,
        normalisation: str | None = None,
    ) -> None:
        """Merge the given site-view choices; None leaves a field as it is."""
        if normalisation is not None and normalisation not in NORMALISATION_METHODS:
            raise ValueError(
                f"unknown normalisation {normalisation!r}; expected one of {NORMALISATION_METHODS}"
            )
        view = self._require_site().site_view
        new = dict(view)
        if grids is not None:
            new["grids"] = list(grids)
        if transform is not None:
            new["transform"] = transform
        if normalisation is not None:
            new["normalisation"] = normalisation
        if new == view:
            return
        self._require_site().site_view = new
        self._set_dirty(True)

    def slice_colours(self, scope: str) -> dict[str, Any]:
        """A copy of a slice scope's remembered colours (#180), or {}.

        `scope` is `"grid"` (This grid) or `"site"` (Whole site). The record is
        `{"own": bool, "style": str}`, each key optional: `own` is True when the
        slice uses the user's own QGIS symbology, `style` that symbology."""
        _check_colour_scope(scope)
        return dict(self._require_site().slice_colours.get(scope, {}))

    def set_slice_colours(
        self, scope: str, *, own: bool | None = None, style: str | None = None
    ) -> None:
        """Merge the given colour choices into a scope's record; None leaves a
        field as it is. Marks the site unsaved only when something changed."""
        _check_colour_scope(scope)
        colours = self._require_site().slice_colours
        old = colours.get(scope, {})
        new = dict(old)
        if own is not None:
            new["own"] = bool(own)
        if style is not None:
            new["style"] = style
        if new == old:
            return
        colours[scope] = new
        self._set_dirty(True)

    def site_resolution(self) -> dict[str, float | str]:
        """A copy of Whole site's remembered resolution (#71), or {}."""
        return dict(self._require_site().site_view.get("resolution", {}))

    def remember_site_resolution(
        self,
        *,
        cell: float | None = None,
        dz_ns: float | None = None,
        t0_ns: float | None = None,
        t1_ns: float | None = None,
        method: str | None = None,
        max_distance_spacings: float | None = None,
        smooth_x_m: float | None = None,
        smooth_y_m: float | None = None,
    ) -> None:
        """Merge the given fields into Whole site's remembered resolution
        (#71), apart from every grid's own; None leaves a field as it is."""
        merged = _merge_resolution(
            self.site_resolution(),
            cell=cell,
            dz_ns=dz_ns,
            t0_ns=t0_ns,
            t1_ns=t1_ns,
            method=method,
            max_distance_spacings=max_distance_spacings,
            smooth_x_m=smooth_x_m,
            smooth_y_m=smooth_y_m,
        )
        if merged is None:
            return
        site = self._require_site()
        site.site_view = {**site.site_view, "resolution": merged}
        self._set_dirty(True)

    # ---- current line, samples, cursor ------------------------------------
    def open_line(self, key: str) -> None:
        self._require_key(key)
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
        self._open_serial += 1  # before the emit, so every slot of this open reads the same value
        self.line_opened.emit(key)

    @property
    def open_serial(self) -> int:
        """Counts the items opened as the working item (`open_line` moving it).
        Moved before `line_opened` is emitted, so a listener can tell what it did
        during this open from what it did earlier, whatever order the slots run in."""
        return self._open_serial

    def profiles_for(self, key: str) -> list[Profile] | None:
        return self._profiles.get(key)

    def set_profiles(self, key: str, profiles: list[Profile]) -> None:
        # Finding 4 (M7 final review): this is where a hover-triggered
        # background load actually lands -- verified by experiment that
        # THIS call, not ProfileDock.current_radargram's later one, is
        # what plants the empty StepStack in every currently reachable
        # path (current_radargram only ever runs once profiles_for(key)
        # is already truthy, which requires set_profiles to have run
        # first). A key that is ONLY previewed right now, and is not also
        # the working line, must not persist one purely because its data
        # finished loading -- spec §3.3's promise that a preview touches
        # nothing. The moment that stops being true -- promoted to
        # current, or a real edit lands -- the next stack_for() call
        # (default insert=True) creates it for real, same as any other
        # line.
        insert = key == self._current_key or key != self._preview_key
        stack = self.stack_for(key, insert=insert)  # validates the key before anything is cached
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
        if is_cut_key(key):
            # The column count belongs to the section, so only the bottom clamps (plan call 4).
            index = max(-1, int(index))
        else:
            index = max(0, min(int(index), self.line_for_key(key).n_traces - 1))
        if index != self._current_trace:
            self._current_trace = index
            self.trace_changed.emit(key, index)

    def set_selection(self, key: str, start: int, end: int) -> None:
        if key != self._current_key:
            return
        lo, hi = sorted((int(start), int(end)))
        n = 1 << 62 if is_cut_key(key) else self.line_for_key(key).n_traces
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

    # ---- picks (spec §4) --------------------------------------------------
    @property
    def pick_store(self) -> Any | None:
        # The read half of set_pick_store. Observed by tests, no production
        # caller: the write path reaches the store through _pick_store
        # directly. Kept anyway -- it is the symmetric public counterpart
        # to a public setter, and it is what lets the registration test
        # assert without reaching into the private attribute.
        return self._pick_store

    def set_pick_store(self, store: Any) -> None:
        """Register the object that actually writes picks.

        Spec §4.1 names `session.add_pick`, and the invariant it enforces
        (a pick targets the WORKING line) belongs here beside
        `set_trace`'s and `set_selection`'s identical guards. The *write*
        cannot be here: this object holds no `QgsVectorLayer`, and the
        parent spec §4.3 rule 2 forbids opening a second OGR handle on a
        GeoPackage QGIS already has open. `SiteLayers` holds the loaded
        layer and registers itself from its own constructor.

        This makes the reference cycle session <-> layers explicit.
        Deliberate: neither class defines `__del__`, so Python's cycle
        collector handles it, and `plugin.unload()` drops both together.
        """
        self._pick_store = store

    def add_pick(self, key: str, trace: int, time_ns: float, *, zero_ns: float = 0.0) -> Pick:
        """Author one pick on the WORKING line.

        `time_ns` is measured from `zero_ns` (the zero of the view it was
        clicked on), so its radar time is `time_ns + zero_ns`. That radar time
        is clamped into the header window, then stored measured from the
        line's own zero (`line_zero`), with that zero; when the line's zero is
        unknown it is stored on the radar clock with no zero (#97).

        `key` must be `current_key`. This is the same guard `set_trace`
        and `set_selection` carry, and it exists here rather than only in
        the dock for the reason spec §3.3 gives: `current_key` is what
        every destructive operation resolves through, and a preview must
        never reach one. M7's reviews found three separate attempts by a
        preview to reach a write; the structural answer is to refuse in
        the session, where no caller can forget.

        Unlike `set_trace`, this RAISES rather than returning silently. A
        trace that does not move is invisible and harmless; a pick that
        does not appear is authored data lost with no message. The caller
        is `plugin.py`'s relay, which puts the reason on the message bar.

        `picks_changed` is emitted only after the store's write returns:
        announcing a pick that is not on disk is the worst report
        available for the one table `survey.nsgeo.json` cannot
        regenerate.

        Does NOT dirty the session. A pick goes straight into the
        GeoPackage; `survey.nsgeo.json` is untouched, so `Save site`
        would have nothing to write and prompting for it would be a lie.
        """
        if key != self._current_key:
            raise ValueError(
                f"a pick targets the working line ({self._current_key!r}), not {key!r}; "
                f"select the line on the map to work on it"
            )
        if self._pick_store is None:
            raise RuntimeError("no pick store is attached to this session; cannot author a pick")
        if not math.isfinite(time_ns):
            raise ValueError(f"a pick needs a finite two-way time, not {time_ns!r}")
        if not math.isfinite(zero_ns):
            raise ValueError(f"a pick needs a finite time zero, not {zero_ns!r}")
        line = self.line_for_key(key)
        index = max(0, min(int(trace), line.n_traces - 1))
        # The view emits a pick for any left click in the widget, and
        # ViewTransform.time_of_y does not clamp -- a click in the top
        # margin yields a time before the record starts. Clamped into the
        # line's own recorded window, the same way the trace is.
        #
        # Final review, Minor 8: `t_end` here is `t0 + (n_samples - 1) *
        # dt_ns` -- the time of the LAST sample -- while
        # `ViewTransform.t_end` is `t0 + n_samples * dt_ns`, one whole
        # sample interval later. That is deliberate, not a mismatch to
        # reconcile: a pick names a sample, and `n_samples - 1` is the
        # last one that actually exists, so this errs inward rather than
        # clamping to a time no sample was ever recorded at. Do not
        # "fix" the two to match.
        t0 = float(line.header.position_ns)
        t_end = t0 + (line.header.n_samples - 1) * float(line.header.dt_ns)
        lo, hi = (t0, t_end) if t0 <= t_end else (t_end, t0)
        radar = max(lo, min(retime_ns(float(time_ns), float(zero_ns), 0.0), hi))
        zero = self.line_zero(key)
        time = radar if zero is None else retime_ns(radar, 0.0, zero)
        distance_m, depth_m, velocity_m_ns = self.derived_pick_fields(key, index, time)
        pick = Pick(
            line_key=key,
            trace=index,
            time_ns=time,
            zero_ns=zero,
            distance_m=distance_m,
            depth_m=depth_m,
            velocity_m_ns=velocity_m_ns,
            # insert=False: reading the stack to record it must not be
            # what creates one. M7's Finding 4 is the same shape -- a
            # hovered line persisted an empty StepStack purely because
            # something asked for it.
            stack_json=json.dumps(self.stack_for(key, insert=False).to_dicts()),
            note="",
            created=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        )
        self._pick_store.write_pick(pick)
        self.picks_changed.emit()
        return pick

    def derived_pick_fields(
        self, key: str, trace: int, time_ns: float
    ) -> tuple[float | None, float, float]:
        """`(distance_m, depth_m, velocity_m_ns)` for a pick at `trace` and
        `time_ns` on line `key`, from the line's current placement and
        resolved velocity. `add_pick` records these, and `SiteLayers.
        follow_lines` re-derives them whenever a line or grid changes, so
        both read them from one place (line editing spec §4.4).

        `KeyError` for an unknown key. No clamping: `add_pick` clamps the
        trace and time before calling, and a stored pick is followed with
        the values it already holds.
        """
        line = self.line_for_key(key)
        model = self.resolved_velocity(key)
        # A plain list, not a numpy array: `depth_at`/`velocity_at` both
        # call `np.asarray` on whatever they are handed, so this keeps
        # numpy out of session.py's imports entirely for one scalar.
        times = [time_ns]
        return (
            self._pick_distance(line, trace),
            float(model.depth_at(times)[0]),
            float(model.velocity_at(times)[0]),
        )

    def add_cut_pick(
        self, key: str, column: int, distance_m: float, time_ns: float, stack_json: str
    ) -> Pick:
        """Author one pick on the WORKING cut (cut spec §4.5, calls 2 and 12).

        A cut pick is a distance along the cut and a time. `column` is the
        section column it was made on, stored in `trace` for the record
        only: a column's index changes with the cell size, so nothing ever
        places the pick by it. The distance is clamped into the cut. The
        time is on the cube's clock (call 18) and is stored as given,
        never converted, and never clamped to a line's window since a cut
        has none. `stack_json` is the section's provenance, in place of a
        line's stack.

        Refuses like `add_pick`: only the working key, and a raise rather
        than a silent no-op, since a pick that does not appear is authored
        data lost. Does not dirty the session, for the reason `add_pick`
        gives.
        """
        if not is_cut_key(key) or key != self._current_key:
            raise ValueError(
                f"a cut pick targets the working cut ({self._current_key!r}), not {key!r}; "
                f"select the cut to work on it"
            )
        if self._pick_store is None:
            raise RuntimeError("no pick store is attached to this session; cannot author a pick")
        if not math.isfinite(time_ns) or not math.isfinite(distance_m):
            raise ValueError(
                f"a pick needs a finite distance and time, not {distance_m!r} and {time_ns!r}"
            )
        cut = self.cut_for_key(key)
        distance = max(0.0, min(float(distance_m), cut.length_m))
        depth_m, velocity_m_ns = self.derived_cut_pick_fields(key, distance, float(time_ns))
        pick = Pick(
            line_key=key,
            trace=max(0, int(column)),
            time_ns=float(time_ns),
            distance_m=distance,
            depth_m=depth_m,
            velocity_m_ns=velocity_m_ns,
            stack_json=stack_json,
            note="",
            created=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        )
        self._pick_store.write_pick(pick)
        self.picks_changed.emit()
        return pick

    def derived_cut_pick_fields(
        self, key: str, distance_m: float, time_ns: float
    ) -> tuple[float | None, float | None]:
        """`(depth_m, velocity_m_ns)` for a pick on cut `key` at `time_ns`,
        from the cut's velocity (cut spec call 16), or `(None, None)` when
        its grid has neither a velocity nor a line to take one from.

        `distance_m` takes no part in the maths (a cut has one velocity):
        it is in the signature so a caller hands over a pick's whole
        position, as `derived_pick_fields` takes its trace. `KeyError` for
        a key that names no cut.
        """
        cut = self.cut_for_key(key)
        try:
            model = self.grid_depth_velocity(cut.grid_id)
        except KeyError:
            return (None, None)
        times = [time_ns]
        return (float(model.depth_at(times)[0]), float(model.velocity_at(times)[0]))

    @staticmethod
    def _pick_distance(line: Line, index: int) -> float | None:
        """Distance along the line at `index`, or None when the line has
        no distance axis at all. `Line.distance_along()` raises
        `ValueError` for a time-triggered acquisition
        (`traces_per_metre <= 0`); `ProfileDock._safe_distance` and
        `SiteLayers._line_points` already treat that as a property of the
        file rather than an error. Time is the truth here, so a missing
        distance is a null field, not a refused pick.
        """
        if index < 0:
            # NumPy would wrap a negative index to the far end of the line;
            # a hand-edited trace below zero has no distance, like one past
            # the end.
            return None
        try:
            return float(line.distance_along()[index])
        except (ValueError, IndexError):
            return None

    def picks_for(self, key: str) -> list[Pick]:
        """Every pick on `key`, ordered by (trace, time).

        Empty rather than raising when no store is attached: this is read
        from a render slot, and a raise there reaches `qFatal()` in the
        CI container. Reading is not authoring, so unlike `add_pick`
        there is no invariant to protect -- a preview may show its own
        line's picks.
        """
        if self._pick_store is None:
            return []
        picks: list[Pick] = self._pick_store.picks_for(key)
        return picks

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
        self._require_key(key)  # raises KeyError before anything changes
        index = -1 if trace < 0 else int(trace)
        if not is_cut_key(key):
            index = min(index, self.line_for_key(key).n_traces - 1)
        if (key, index) == (self._preview_key, self._preview_trace):
            return  # loop guard: a marker update that round-trips is a no-op
        self._preview_key, self._preview_trace = key, index
        self.preview_changed.emit(key, index)

    def clear_preview(self) -> None:
        if self._preview_key is None and self._preview_trace == -1:
            return
        self._preview_key, self._preview_trace = None, -1
        self.preview_changed.emit("", -1)
