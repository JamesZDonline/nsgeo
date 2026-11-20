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
    CurvaturePlan,
    FillWeights,
    FinishSettings,
    SliceFill,
    plan_fill,
)

from nsgeo_qgis.slices_plan import PREVIEW_METHOD

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
        s = self._settings
        md, sr = s.max_distance_m, s.search_radius_m
        cell = self.frame.cell
        curvature = s.method == "min_curvature"
        # Minimum curvature also builds the kriging preview; progress covers both.
        share = 0.7 if curvature else 1.0

        def report(part: float) -> None:
            self.fraction = max(self.fraction, min(share, part * share))

        fill = plan_fill(
            self._populated, cell, s.method, md, sr, should_stop=should_stop, progress=report
        )
        preview: FillWeights | None = None
        if isinstance(fill, CurvaturePlan):

            def report_preview(part: float) -> None:
                self.fraction = max(self.fraction, min(1.0, share + part * (1.0 - share)))

            built = plan_fill(
                self._populated,
                cell,
                PREVIEW_METHOD,
                md,
                sr,
                should_stop=should_stop,
                progress=report_preview,
            )
            assert isinstance(built, FillWeights)  # kriging plans weights
            preview = built
        self.fill, self.preview = fill, preview
        self.fraction = 1.0

    def land(self) -> bool:
        """GUI thread: hold the fill if the engine still wants it."""
        return self._engine._land_fill(self)
