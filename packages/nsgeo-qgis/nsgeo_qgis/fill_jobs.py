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
    ) -> None:
        self._engine = engine
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
        self.fraction = 1.0

    def land(self) -> bool:
        """GUI thread: hold the fill if the engine still wants it. Either way
        the job lets go of its fill, preview and mask, so a stale job kept by
        a caller never holds a refused fill beside the next build."""
        try:
            return self._engine._land_fill(self)
        finally:
            self.fill = None
            self.preview = None
            self._populated = np.zeros(0, dtype=bool)
