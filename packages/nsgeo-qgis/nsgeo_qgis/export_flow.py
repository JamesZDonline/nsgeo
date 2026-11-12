"""What the plugin hands the export dialog and the task, apart from the widgets.

The dialog's `preview(cell, pixel)` callables, the stretch rule of the coverage
companion and the plain words for a failed export. GUI thread: the previews
read the live engines through the snapshot builders.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import numpy as np
from nsgeo.slices import SiteLattice

from nsgeo_qgis.export_pipeline import (
    OVERVIEW_FACTOR,
    CoveredCache,
    ExportSpec,
    estimate_export,
)
from nsgeo_qgis.site_engine import SiteEngine
from nsgeo_qgis.site_export import site_export_spec
from nsgeo_qgis.slice_export import grid_export_spec
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import (
    ExportPreview,
    SliceFinish,
    bands_detail,
    slices_text,
)


class CountsClip:
    """The coverage view's own stretch: one to the largest count (`display_limit`)."""

    def limit(self, values: np.ndarray) -> float:
        finite = np.asarray(values, dtype=float)
        finite = finite[np.isfinite(finite)]
        return max(1.0, float(finite.max())) if finite.size else 1.0


def _preview(
    spec: ExportSpec,
    cell: float,
    pixel: float,
    windows: Sequence[tuple[float, float]],
    finish: SliceFinish,
    coverage: bool,
    grids: tuple[str, ...] | None,
    normalisation: str | None,
    cache: CoveredCache,
) -> ExportPreview:
    estimate = estimate_export(spec, cache)
    lattice: SiteLattice = spec.lattice
    file_bytes = estimate.file_bytes
    if coverage:
        # The counts companion's one band exists beside the values file.
        file_bytes += int(lattice.n_pixels * 4 * OVERVIEW_FACTOR)
    return ExportPreview(
        cell=cell,
        pixel=pixel,
        width_px=lattice.width,
        height_px=lattice.height,
        bands=len(windows),
        bands_detail=bands_detail(windows),
        slices=slices_text(finish),
        grids=grids,
        normalisation=normalisation,
        file_bytes=file_bytes,
        held_bytes=estimate.held_bytes,
    )


def site_preview(
    site: SiteEngine,
    windows: Sequence[tuple[float, float]],
    *,
    method: str,
    finish: SliceFinish,
    gains: Mapping[str, float],
    coverage: bool,
    normalisation: str,
) -> Callable[[float, float], ExportPreview]:
    """The whole-site dialog's `preview`: the snapshot at (cell, pixel), sized."""
    grids = tuple(site.ready_grids)
    cache: CoveredCache = {}

    def preview(cell: float, pixel: float) -> ExportPreview:
        spec = site_export_spec(
            site, cell, pixel, tuple(windows), method=method, finish=finish, gains=gains
        )
        return _preview(spec, cell, pixel, windows, finish, coverage, grids, normalisation, cache)

    return preview


def grid_preview(
    engine: SliceEngine,
    windows: Sequence[tuple[float, float]],
    *,
    finish: SliceFinish,
    coverage: bool,
) -> Callable[[float, float], ExportPreview]:
    """This grid's dialog's `preview`: no Grids and no Normalisation rows."""
    cache: CoveredCache = {}

    def preview(cell: float, pixel: float) -> ExportPreview:
        spec = grid_export_spec(engine, cell, pixel, tuple(windows), finish)
        return _preview(spec, cell, pixel, windows, finish, coverage, None, None, cache)

    return preview


def plain_export_error(raw: str | None) -> str:
    """A failed export's cause in plain words. The raw text goes to the log, not the bar."""
    text = (raw or "").lower()
    if "no space left" in text or "errno 28" in text or "disk full" in text:
        return "there is not enough free disk space to finish it"
    if "permission" in text or "errno 13" in text or "being used by another process" in text:
        return (
            "the file could not be written; check that you may save there "
            "and that no other program has it open"
        )
    if "no coordinate transform" in text:
        return "a grid's coordinate system cannot be converted to the site's"
    if "memory" in text or "unable to allocate" in text:
        return "it ran out of memory; try a larger export cell or pixel"
    return "something went wrong; the details are in the QGIS message log"
