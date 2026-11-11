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
  call 6; cut spec call 12). The solve itself comes with Task 6.

Qt only through `qgis.PyQt`.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from nsgeo.model import Cut
from nsgeo.slices import (
    FinishSettings,
    SectionColumns,
    ZAxis,
    column_distances,
    finish_section,
    section_columns,
)
from qgis.core import Qgis
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import PREVIEW_METHOD, SliceFinish

if TYPE_CHECKING:
    from nsgeo_qgis.ui.slices_dock import SlicesDock

NO_SOURCE_TEXT = "{name} is on {grid}. Show {grid} in the Slices panel to see it."
NO_CUBE_TEXT = "Select {name} to build {grid}'s cube for it."

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
        self._connections = [
            (slices_dock.slice_changed, self._on_inputs_changed),
            (session.cuts_changed, self._on_inputs_changed),
            (session.grids_changed, self._on_inputs_changed),
            (session.site_closed, self._on_inputs_changed),
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
            return cached[1]
        section = self._build(key, cut, source)
        self._cache[key] = (stamp, section)
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
                self._cache.clear()
                self._waiting.clear()
                return
            for key in list(self._cache):
                if self._cut(key) is None:
                    del self._cache[key]
                elif not self._still_current(key):
                    del self._cache[key]
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
        self._cache.clear()
        self._waiting.clear()
