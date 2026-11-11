"""A cut's vertical section, read from the cube the Slices panel holds (cut spec §4.3, §4.4).

A cut is drawn on a grid, and the section beneath it is the cube read along
the path (`nsgeo.slices.section`). The plugin never builds a cube for it: the
cube, its finish settings, its fill weights and its palette are the Slices
panel's, so a cut shows what the slice shows, cut another way (plan call 5).

* **Which source.** In This grid, a cut on the grid the panel shows reads
  `SlicesDock.engine`; a cut on another grid has no source and says so
  (`NO_SOURCE_TEXT`), even when the site engine still holds that grid. In
  Whole site, a cut reads its grid's `SiteEngine` engine, finished with the
  site's settings and never with the site's gain (`SiteEngine._shown`'s
  `a * values + b`): normalising is for a map that joins grids, and a section
  belongs to one (cut spec call 10).
* **The cube.** Opening a cut builds the engine's resident cube under a wait
  cursor (`build_cube=True`); a hover preview never does (`NO_CUBE_TEXT`), so
  moving the pointer cannot freeze the canvas (cut spec §5).
* **Redraws.** Each section is cached with a fingerprint of everything it was
  made from. The Slices panel, the survey's cuts and grids, and closing the
  site each re-check the cache, and a section whose fingerprint moved is
  dropped and announced (`section_changed`), so the profile asks again. Every
  call resolves its source afresh: a cached section is never served from an
  engine the panel has let go of.
* **Minimum curvature** has no weights to reuse, so until it is solved a cut
  shows kriging at the same max distance and smoothing (`standing_in`, plan
  call 6; cut spec call 12). The working cut (the one opened, never a hover)
  is solved in the background once its section has rested `CUT_SOLVE_REST_MS`:
  one `CutLevelJob` per depth, on a worker of its own (`nsgeo-cut`, plan call
  8) so the slice's own refine never queues behind it, solved outward from the
  slice band's centre. Each landed row replaces the kriging row in place, and
  the profile is told at most every `CUT_REDRAW_MS`. Anything that changes the
  cut, its grid, the panel's settings, the open item or the site stops the
  solve, and a stopped solve lands nothing: a row is written only while the
  section it was made for is still the cached one.

**Measured** (Task 6, 2026-11-11, Sunnyside Grid 1 at its remembered settings: 0.05 m cell,
minimum curvature, max distance 0.5 spacings, smoothing Y 0.1 m, 463 depths; a 12 m cut across
the grid, this machine, offscreen):

* The cube build the first open pays: about 0.5 s.
* The first preview of a cut, or the redraw after a settings change (a kriging section built
  on the GUI thread): 0.9 s first, 1.4 s after a max-distance change. Over the 100 ms a hover
  should cost, but it is paid once per cut and setting, not per hover.
* A repeat preview on the same section (another column): 6 ms.
* Until the 12 m cut is solved: 99.5 s (0.215 s a depth), which is over the minute the spec
  hoped for. Task 1 measured the same rate on the ten real lines (0.2 s a depth); Grid 1's
  463 depths, not 211, make the total.

Qt only through `qgis.PyQt`.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from nsgeo.model import Cut
from nsgeo.slices import (
    FinishSettings,
    SectionColumns,
    ZAxis,
    column_distances,
    curvature_margin_cells,
    finish_section,
    plan_section_curvature,
    section_columns,
    section_crops,
    solve_section_level,
)
from qgis.core import Qgis
from qgis.PyQt.QtCore import QObject, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.refine import Refiner
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import PREVIEW_METHOD, SliceFinish

if TYPE_CHECKING:
    from nsgeo_qgis.ui.slices_dock import SlicesDock

NO_SOURCE_TEXT = "{name} is on {grid}. Show {grid} in the Slices panel to see it."
NO_CUBE_TEXT = "Select {name} to build {grid}'s cube for it."

#: How long the working cut's section rests before its minimum curvature is
#: solved, so a settings drag or a quick pass does not start a solve per step.
CUT_SOLVE_REST_MS = 300
#: The most often a landing solve redraws the profile.
CUT_REDRAW_MS = 250
#: The cut worker's thread-name prefix; tests and crash reports look for it.
CUT_THREAD_NAME_PREFIX = "nsgeo-cut"

SCOPE_LABELS = {"grid": "This grid", "site": "Whole site (not normalised)"}


@dataclass(frozen=True)
class CutSource:
    """Where a section's values come from, as the Slices panel stands now."""

    grid_id: str
    scope: str  # "grid" or "site"
    engine: SliceEngine
    finish: SliceFinish
    settings: FinishSettings
    palette: str
    unipolar: bool


@dataclass(frozen=True)
class CutSection:
    """One cut's section, ready to draw."""

    key: str
    values: np.ndarray  # (nz, n) float32, NaN where blank
    z: ZAxis
    columns: SectionColumns
    method: str  # the method drawn: "kriging" while it stands in for minimum curvature
    standing_in: bool
    solved: tuple[int, int]  # (depths done, depths in all) of the real minimum-curvature solve
    source: CutSource
    provenance_json: str


class _SolveInputs:
    """What every depth of one solve shares: the cube, the crops and their plans.

    Built by the first job, on the worker, so the crops' multigrid plans never
    cost the GUI thread a frame. Only the worker touches it after that.
    """

    def __init__(
        self, cube: Any, columns: SectionColumns, settings: FinishSettings, spacing: float
    ):
        self.cube = cube
        self.columns = columns
        self.settings = settings
        self.spacing = spacing
        self.crops: tuple[Any, ...] | None = None
        self.plans: tuple[Any, ...] = ()

    def prepare(self) -> None:
        if self.crops is not None:
            return
        frame = self.cube.frame
        margin = curvature_margin_cells(self.settings, frame.cell, self.spacing)
        crops = section_crops(self.columns, frame, margin)
        self.plans = plan_section_curvature(
            self.cube.coverage() > 0, crops, frame.cell, self.settings.max_distance_m
        )
        self.crops = crops


class CutLevelJob:
    """One depth of a cut's minimum-curvature solve (a `RefineJob`)."""

    def __init__(self, level: int, inputs: _SolveInputs) -> None:
        self.level = level
        self.result: np.ndarray | None = None
        self._inputs = inputs

    def run(self, should_stop: Callable[[], bool]) -> None:
        inputs = self._inputs
        inputs.prepare()
        assert inputs.crops is not None
        self.result = solve_section_level(
            inputs.cube.level(self.level),
            inputs.columns,
            inputs.crops,
            inputs.plans,
            inputs.settings,
            inputs.cube.frame.cell,
            should_stop,
        )


class CutSections(QObject):
    """Sections for the survey's cuts, from the Slices panel's engines."""

    section_changed = pyqtSignal(str)  # a cached section's inputs moved: ask again

    def __init__(
        self, session: SiteSession, slices_dock: SlicesDock, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.slices_dock = slices_dock
        self._cache: dict[str, tuple[tuple[Any, ...], CutSection]] = {}
        #: Cuts last answered with a message, and what they wait for: "source"
        #: (no engine shows their grid) or "cube" (a preview with none built).
        #: A cut with nothing cached would never be announced otherwise.
        self._waiting: dict[str, str] = {}
        #: The working cut's minimum curvature (cut spec §4.7). `_working` is
        #: the key waiting out its rest or being solved, `_stamp` the cached
        #: section's fingerprint it was armed for; `_levels` is each cached
        #: standing-in section's solved depths, under that same stamp.
        self._working: str | None = None
        self._stamp: tuple[Any, ...] | None = None
        self._levels: dict[str, tuple[tuple[Any, ...], set[int]]] = {}
        self._band: tuple[float, float] | None = None
        self._refiner = Refiner(self, thread_name_prefix=CUT_THREAD_NAME_PREFIX)
        self._rest = QTimer(self)
        self._rest.setSingleShot(True)
        self._rest.timeout.connect(self._start_solve)
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.timeout.connect(self._flush_redraw)
        self._connections = [
            (slices_dock.slice_changed, self._on_inputs_changed),
            (slices_dock.window_changed, self._on_window_changed),
            (session.cuts_changed, self._on_inputs_changed),
            (session.grids_changed, self._on_inputs_changed),
            (session.site_closed, self._on_inputs_changed),
            (session.line_opened, self._on_item_opened),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)

    # ---- the source ---------------------------------------------------------
    def source_for(self, grid_id: str) -> CutSource | None:
        """What a cut on `grid_id` reads now, or None when the panel shows no such grid.

        Never builds anything, and never returns an engine that is not
        prepared for `grid_id` (cut spec call 10).
        """
        dock = self.slices_dock
        if not self.session.is_open:
            return None
        try:
            scope = dock.scope()
            if scope == "site":
                if grid_id not in dock.site_engine.ready_grids:
                    return None
                engine = dock.site_engine.engine_for(grid_id)
                finish = dock.site_finish.value()
            else:
                engine = dock.engine
                choice = engine.choice
                if not engine.is_prepared or choice is None or choice.grid_id != grid_id:
                    return None
                finish = dock.grid_finish.value()
            if engine is None or engine.frame is None or engine.z is None or engine.choice is None:
                return None
            settings = engine.finish_settings(finish)
            return CutSource(
                grid_id=grid_id,
                scope=scope,
                engine=engine,
                finish=finish,
                settings=settings,
                palette=dock.palette_combo.currentText(),
                unipolar=engine.output_unipolar,
            )
        except Exception as exc:  # noqa: BLE001 -- reported, then no source
            _log(
                f"could not resolve a cut's source on {grid_id}: {exc}", Qgis.MessageLevel.Critical
            )
            return None

    # ---- sections -----------------------------------------------------------
    def section(self, key: str, *, build_cube: bool) -> CutSection | str:
        """The cut's section, or the message to show in its place.

        `build_cube` is True when the user opened the cut (the build waits
        under a cursor) and False for a hover preview, which never builds.
        """
        cut = self._cut(key)
        if cut is None:
            self._cache.pop(key, None)
            self._waiting.pop(key, None)
            return ""
        source = self.source_for(cut.grid_id)
        if source is None:
            self._cache.pop(key, None)
            self._waiting[key] = "source"
            return NO_SOURCE_TEXT.format(name=cut.name, grid=cut.grid_id)
        engine = source.engine
        if not engine.has_cube:
            if not build_cube:
                self._waiting[key] = "cube"
                return NO_CUBE_TEXT.format(name=cut.name, grid=cut.grid_id)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                engine.cube()
            except Exception as exc:  # noqa: BLE001 -- no lines, a vanished source
                _log(f"could not build {cut.grid_id}'s cube: {exc}", Qgis.MessageLevel.Warning)
                self._waiting[key] = "source"
                return NO_SOURCE_TEXT.format(name=cut.name, grid=cut.grid_id)
            finally:
                QApplication.restoreOverrideCursor()
        self._waiting.pop(key, None)
        stamp = self._fingerprint(cut, source)
        cached = self._cache.get(key)
        if cached is not None and cached[0] == stamp:
            section = cached[1]
        else:
            section = self._build(key, cut, source)
            self._cache[key] = (stamp, section)
            self._levels[key] = (stamp, set())
        if build_cube and section.standing_in:
            self._arm(key, stamp)
        return section

    def column_at(self, key: str, distance_m: float) -> int | None:
        """The index of the column nearest `distance_m` along the cut (cut spec call 14).

        Columns are fixed by the cut and the cell, so this needs no section
        and no cube; None when the cut has no source.
        """
        cut = self._cut(key)
        if cut is None:
            return None
        source = self.source_for(cut.grid_id)
        if source is None:
            return None
        frame = source.engine.frame
        assert frame is not None  # source_for checked
        along = column_distances(cut.length_m, frame.cell / 2.0)
        return int(np.argmin(np.abs(along - distance_m)))

    def _cut(self, key: str) -> Cut | None:
        """The cut, or None when it is gone or the site is closed."""
        if not self.session.is_open:
            return None
        try:
            return self.session.cut_for_key(key)
        except KeyError:
            return None

    # ---- minimum curvature, behind the kriging (cut spec §4.7) ----------------
    def _arm(self, key: str, stamp: tuple[Any, ...]) -> None:
        """The working cut's section stands in for minimum curvature: solve it
        once it has rested. Already armed for this very section, nothing
        moves, so a redraw of it never restarts the rest."""
        if self._working == key and self._stamp == stamp:
            return
        self._cancel()
        self._working = key
        self._stamp = stamp
        self._rest.start(CUT_SOLVE_REST_MS)

    def _cancel(self) -> None:
        """Stop the solve and the rest; nothing more lands. Safe at any time."""
        self._rest.stop()
        self._redraw.stop()
        self._refiner.cancel()
        self._working = None
        self._stamp = None

    def _on_window_changed(self, lo_ns: float, hi_ns: float) -> None:
        """Remember the slice band: the next solve starts at its centre."""
        try:
            self._band = (float(lo_ns), float(hi_ns))
        except Exception as exc:  # noqa: BLE001 -- a slot on a pyqtSignal
            _log(f"could not note the slice band: {exc}", Qgis.MessageLevel.Warning)

    def _on_item_opened(self, key: str) -> None:
        """Opening anything but the working cut stops its solve."""
        try:
            if self._working is not None and key != self._working:
                self._cancel()
        except Exception as exc:  # noqa: BLE001 -- a slot on a pyqtSignal
            _log(f"could not stop a cut's solve: {exc}", Qgis.MessageLevel.Warning)

    def _centre_level(self, z: ZAxis) -> int:
        """The depth the slice band sits on, or the middle of the axis."""
        if self._band is None:
            return z.nz // 2
        lo, hi = self._band
        k0, k1 = z.level_range(lo, max(hi - lo, z.dz_ns * 0.5))
        return (k0 + k1 - 1) // 2

    def _start_solve(self) -> None:
        """The rest is over: one job per depth still owed, centre outward."""
        try:
            key, stamp = self._working, self._stamp
            if key is None or stamp is None:
                return
            cut = self._cut(key)
            source = None if cut is None else self.source_for(cut.grid_id)
            cached = self._cache.get(key)
            if cut is None or source is None or cached is None or cached[0] != stamp:
                self._cancel()
                return
            section = cached[1]
            engine = source.engine
            if not section.standing_in or not engine.has_cube:
                self._cancel()
                return
            done = self._levels[key][1]
            nz = section.z.nz
            centre = self._centre_level(section.z)
            owed = sorted(
                (k for k in range(nz) if k not in done), key=lambda k: (abs(k - centre), k)
            )
            if not owed:
                self._finish(key)
                return
            grid = self.session.grid(cut.grid_id)
            inputs = _SolveInputs(
                engine.cube(), section.columns, source.settings, grid.default_spacing
            )
            jobs = [CutLevelJob(k, inputs) for k in owed]
            self._refiner.start(jobs, self._on_landed, self._on_failed)
        except Exception as exc:  # noqa: BLE001 -- a slot on a timer
            _log(f"could not start a cut's minimum curvature: {exc}", Qgis.MessageLevel.Critical)
            self._cancel()

    def _on_landed(self, job: Any) -> None:
        """A depth is solved: its row replaces the kriging row, if the section
        it was made for is still the one cached."""
        try:
            key, stamp = self._working, self._stamp
            cached = None if key is None else self._cache.get(key)
            if key is None or cached is None or cached[0] != stamp or job.result is None:
                return
            section = cached[1]
            section.values[job.level] = job.result
            levels = self._levels[key][1]
            levels.add(job.level)
            if len(levels) >= section.z.nz:
                self._finish(key)
            elif not self._redraw.isActive():
                self._redraw.start(CUT_REDRAW_MS)
        except Exception as exc:  # noqa: BLE001 -- a refine callback
            _log(f"could not land a cut's depth: {exc}", Qgis.MessageLevel.Critical)

    def _on_failed(self, message: str) -> None:
        try:
            _log(f"a cut's minimum curvature failed: {message}", Qgis.MessageLevel.Critical)
            self._cancel()
        except Exception as exc:  # noqa: BLE001 -- a refine callback
            _log(f"could not report a cut's failure: {exc}", Qgis.MessageLevel.Critical)

    def _flush_redraw(self) -> None:
        try:
            key = self._working
            if key is not None:
                self._publish(key, finished=False)
        except Exception as exc:  # noqa: BLE001 -- a slot on a timer
            _log(f"could not redraw a cut's section: {exc}", Qgis.MessageLevel.Critical)

    def _finish(self, key: str) -> None:
        """Every depth is solved: the section is minimum curvature now."""
        self._redraw.stop()
        self._publish(key, finished=True)
        self._cancel()

    def _publish(self, key: str, *, finished: bool) -> None:
        """Replace the cached section by one that says how far the solve is, and
        tell the profile. The rows are shared, so nothing is copied."""
        stamp, section = self._cache[key]
        nz = section.z.nz
        done = nz if finished else len(self._levels[key][1])
        if finished:
            doc = json.loads(section.provenance_json)
            doc["finish"]["method"] = "min_curvature"
            doc.pop("standing_in_for", None)
            section = dataclasses.replace(
                section,
                method="min_curvature",
                standing_in=False,
                solved=(nz, nz),
                provenance_json=json.dumps(doc),
            )
        else:
            section = dataclasses.replace(section, solved=(done, nz))
        self._cache[key] = (stamp, section)
        self.section_changed.emit(key)

    # ---- building -----------------------------------------------------------
    def _fingerprint(self, cut: Cut, source: CutSource) -> tuple[Any, ...]:
        """Everything a section is made from. Cheap: it builds nothing."""
        engine = source.engine
        return (
            id(engine),
            engine.choice,
            engine.frame,
            engine.z,
            engine.cube_generation,
            source.settings,
            source.scope,
            source.palette,
            source.unipolar,
            cut,
            self.session.grid(cut.grid_id),
        )

    def _build(self, key: str, cut: Cut, source: CutSource) -> CutSection:
        engine = source.engine
        cube = engine.cube()
        columns = section_columns(cube.frame, np.asarray(cut.vertices, dtype=float))
        fill, preview = engine.section_fills(source.finish)
        standing_in = source.settings.method == "min_curvature"
        if standing_in:
            assert preview is not None  # built with the plan
            fill = preview
        values = finish_section(cube, fill, columns, source.settings)
        method = PREVIEW_METHOD if standing_in else source.settings.method
        nz = cube.z.nz
        return CutSection(
            key=key,
            values=values,
            z=cube.z,
            columns=columns,
            method=method,
            standing_in=standing_in,
            solved=(0, nz) if standing_in else (nz, nz),
            source=source,
            provenance_json=self._provenance_json(cut, source, cube.provenance, cube, method),
        )

    @staticmethod
    def _provenance_json(
        cut: Cut, source: CutSource, cube_provenance: Any, cube: Any, method: str
    ) -> str:
        """What a reader needs to trust the section (cut spec call 2)."""
        settings = source.settings
        doc: dict[str, Any] = {
            "kind": "cut",
            "cut_id": cut.id,
            "cut_name": cut.name,
            "grid_id": cut.grid_id,
            "scope": SCOPE_LABELS[source.scope],
            "cube": cube_provenance.to_dict(),
            "resolution": {"cell": cube.frame.cell, "dz_ns": cube.z.dz_ns},
            "finish": {
                "method": method,
                "max_distance_m": settings.max_distance_m,
                "smooth_x_m": settings.smooth_x_m,
                "smooth_y_m": settings.smooth_y_m,
            },
        }
        if settings.method != method:
            doc["standing_in_for"] = settings.method
        return json.dumps(doc)

    # ---- redraws ------------------------------------------------------------
    def _on_inputs_changed(self) -> None:
        """Announce each cut whose answer may now differ, once.

        A cached section whose inputs moved is dropped. A cut waiting on a
        message (nothing cached, so the walk of the cache alone would never
        reach it) is announced when what it waited for is there: a source, or
        a held cube for a preview. The profile then asks again.

        A slot on Qt signals: it reports rather than raises.
        """
        try:
            if not self.session.is_open:
                self._cancel()
                self._cache.clear()
                self._waiting.clear()
                self._levels.clear()
                return
            for key in list(self._cache):
                if self._cut(key) is None:
                    del self._cache[key]
                    self._levels.pop(key, None)
                elif not self._still_current(key):
                    del self._cache[key]
                    self._levels.pop(key, None)
                    self.section_changed.emit(key)
            for key, reason in list(self._waiting.items()):
                cut = self._cut(key)
                if cut is None:
                    del self._waiting[key]
                    continue
                source = self.source_for(cut.grid_id)
                ready = source is not None and (reason == "source" or source.engine.has_cube)
                if reason == "cube" and source is None:
                    ready = True  # the message changes to "show the grid"
                if ready:
                    del self._waiting[key]
                    self.section_changed.emit(key)
            # What moved may have been what the solve was for; one that was
            # re-armed above for the rebuilt section is left alone.
            if self._working is not None:
                cached = self._cache.get(self._working)
                if cached is None or cached[0] != self._stamp:
                    self._cancel()
        except Exception as exc:  # noqa: BLE001 -- a slot on a pyqtSignal
            _log(f"could not refresh a cut's section: {exc}", Qgis.MessageLevel.Warning)

    def _still_current(self, key: str) -> bool:
        cut = self.session.cut_for_key(key)
        source = self.source_for(cut.grid_id)
        if source is None:
            return False
        return bool(self._fingerprint(cut, source) == self._cache[key][0])

    def dispose(self) -> None:
        """Disconnect and forget. Called from `unload`; safe twice."""
        for signal, slot in self._connections:
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(slot)
        self._connections = []
        self._cancel()
        self._refiner.shutdown()
        self._cache.clear()
        self._waiting.clear()
        self._levels.clear()
