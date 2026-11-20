"""A fill built off the GUI thread, landed only where the engine still wants it (#193).

A `FillJob` is a `RefineJob`: `run(should_stop)` executes on a worker and uses
only numpy and what it captured when it was made (a copy of the populated
mask, the immutable frame and settings). It touches no Qt, session or QGIS
object and never the engine. `land()` runs on the GUI thread afterwards and
asks the engine to hold the result; the engine refuses when anything the job
was made for has moved (`SliceEngine._land_fill`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from nsgeo.slices import (
    CubeFrame,
    FillWeights,
    FinishSettings,
    SliceFill,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nsgeo.slices import Footprint
    from qgis.core import QgsCoordinateTransformContext

    from nsgeo_qgis.site_engine import SiteEngine
    from nsgeo_qgis.site_geometry import SiteLattice
    from nsgeo_qgis.slices_engine import SliceEngine


class FillJob:
    def __init__(
        self,
        engine: SliceEngine,
        populated: np.ndarray,
        frame: CubeFrame,
        settings: FinishSettings,
        grid_id: str | None,
        key: tuple[Any, ...],
        epoch: int,
        warm_north_up: bool = False,
    ) -> None:
        self._engine = engine
        #: This grid's: also plan the north-up resample for `frame` after the
        #: fill, so the landing draw's first `to_north_up` is one sample. A fill
        #: refused at landing leaves the plan as an extra LRU entry, harmless.
        self.warm_north_up = warm_north_up
        self._populated = populated
        self._settings = settings
        self.grid_id = grid_id
        self.key = key
        self.frame = frame
        self.epoch = epoch
        self.fill: SliceFill | None = None
        self.preview: FillWeights | None = None
        #: Written by the worker, read by the GUI thread: a float store.
        self.fraction = 0.0

    def run(self, should_stop: Callable[[], bool]) -> None:
        """Worker thread. Raises `SolveStopped` when stopped and holds nothing."""

        # Lazy: the engine imports this module. The one fill rule lives there,
        # beside `_fill_for`, so both paths share it and its test seams.
        from nsgeo_qgis.slices_engine import build_fill

        def report(part: float) -> None:
            self.fraction = max(self.fraction, part)

        self.fill, self.preview = build_fill(
            self._populated,
            self.frame.cell,
            self._settings,
            should_stop=should_stop,
            progress=report,
        )
        if self.warm_north_up and not should_stop():
            from nsgeo.slices import warm_north_up_plan

            warm_north_up_plan(self.frame)
        self.fraction = 1.0

    def land(self) -> bool:
        """GUI thread: hold the fill if the engine still wants it.

        Installed: the job keeps its `fill` and `preview` (the engine holds the
        same objects, so nothing is freed by letting go), because a later job
        may read them on the worker. Refused: the job lets go of its fill,
        preview and mask, so a stale job kept by a caller never holds a refused
        fill beside the next build. A reader must therefore treat
        `fill is None` as "this work is stale: measure nothing".
        """
        installed = False
        try:
            installed = self._engine._land_fill(self)
            return installed
        finally:
            if not installed:
                self.fill = None
                self.preview = None
                self._populated = np.zeros(0, dtype=bool)


class FootprintJob:
    """One grid's footprint on the site lattice, gathered off the GUI thread (#193).

    A `RefineJob` like `FillJob`. Everything is captured on the GUI thread when
    the job is made: the grid id, the engine's frame, the lattice and a copy of
    the project's transform context. `run` calls `site_geometry.gather_footprint`
    with those alone (numpy and a `QgsCoordinateTransform` built inside, which is
    not a QObject), never the engine or the project. `land` runs on the GUI
    thread and the engine refuses a footprint whose lattice or frame has moved
    or whose grid is no longer ready (`SiteEngine._land_footprint`).
    """

    def __init__(
        self,
        engine: SiteEngine,
        grid_id: str,
        frame: CubeFrame,
        lattice: SiteLattice,
        context: QgsCoordinateTransformContext,
    ) -> None:
        self._engine = engine
        self.grid_id = grid_id
        self.frame = frame
        self.lattice = lattice
        self._context = context
        self.footprint: Footprint | None = None
        self.fraction = 0.0

    def run(self, should_stop: Callable[[], bool]) -> None:
        """Worker thread. One call is not interruptible; a stop before it skips it."""
        from nsgeo_qgis import site_geometry

        if should_stop():
            return
        self.footprint = site_geometry.gather_footprint(self.frame, self.lattice, self._context)
        self.fraction = 1.0

    def land(self) -> bool:
        """GUI thread: hold the footprint if the engine still wants it. Refused
        or not, the job keeps nothing the engine does not hold."""
        installed = False
        try:
            installed = self._engine._land_footprint(self)
            return installed
        finally:
            if not installed:
                self.footprint = None
