"""The site GeoTIFF: one file over every included grid, which records what was done.

Spec 4.7 and 6. The bands are made by `export_pipeline.run_export` from a
snapshot of the live site (`site_export_spec`), taken on the GUI thread, and
written by `GeoTiffSiteWriter.write_bands` on the export task's worker thread:
band by band, never a resident cube beyond what the memory budget allows.

What the file records (Ruling 6; the key names are part of the format).
Dataset level, all strings: `NSGEO_SITE_TRANSFORM`, `NSGEO_SITE_NORMALISATION`,
`NSGEO_SITE_CELL_M` (the export cell), `NSGEO_SITE_PIXEL_M` (the export pixel),
`NSGEO_SITE_RESAMPLING` (always `bilinear`), `NSGEO_SITE_INTERPOLATION` (the method key),
`NSGEO_SITE_MAX_DISTANCE_SPACINGS`, `NSGEO_SITE_SMOOTH_X_M`, `NSGEO_SITE_SMOOTH_Y_M`
(interpolation spec §8; the coverage companion carries none of the four),
`NSGEO_SITE_Z_UNIT` (always `ns`) and `NSGEO_SITE_GRIDS` (compact JSON list of
`SiteGridRecord`s), and `NSGEO_SITE_LEFT_OUT` (Ruling F-2: a compact JSON object of
grid id to `SiteEngine.grid_state`, such as `"no lines"` or `"failed: ..."`, for
each included grid the file does not hold; present only when there is one). Band
level: `NSGEO_WINDOW_NS` (`lo,hi` on the site axis),
`NSGEO_GRID_DEPTHS_M` and `NSGEO_GRID_FACTORS` (compact JSON objects, grid id to
`[lo, hi]` / `[a, b]`, or `null` where the grid is absent at that time).

Trap 5: every grid's depths, and the description, derive from that grid's own
`window_on` result, never from the requested window -- a window overhanging a
grid's axis is thinner there. A grid with no velocity has `null` depths and no
depth text in the description. Normalisation is per slice, so the factors are
those the export measured on that band's own binned cells.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
from nsgeo.render import Normalizer
from nsgeo.slices import (
    CubeFrame,
    SiteLattice,
    SliceWindow,
    ZAxis,
    plan_windows,
    window_depths_m,
    window_on,
    window_times_ns,
)
from nsgeo.velocity import VelocityModel
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
)

from nsgeo_qgis.export_pipeline import ExportBand, ExportGrid, ExportSpec
from nsgeo_qgis.site_engine import SiteEngine
from nsgeo_qgis.slice_export import apply_band_windows, write_north_up
from nsgeo_qgis.slices_plan import SliceFinish

_SEPARATORS = (",", ":")


@dataclass(frozen=True)
class SiteGridRecord:
    """One grid as the export saw it. `velocity` is `VelocityModel.to_dict()`."""

    grid_id: str
    preset: str
    velocity: dict[str, Any] | None
    gain: float
    line_spacing_m: float
    azimuth_deg: float
    crs: str


@dataclass(frozen=True)
class SiteBand:
    """One band: a window on `site_z`, its description, and each grid's depths.

    `depths[g]` is None where the grid is absent at this time (or has no velocity).
    """

    window: SliceWindow
    description: str
    depths: dict[str, tuple[float, float] | None]


@dataclass(frozen=True)
class SiteExportPlan:
    lattice: SiteLattice
    site_z: ZAxis
    bands: tuple[SiteBand, ...]
    transform: str
    method: str
    cell_m: float
    #: None on the coverage companion, which was never interpolated or smoothed.
    finish: SliceFinish | None
    grids: tuple[SiteGridRecord, ...]
    #: Ruling F-2: included grids the file does not hold, grid id to state.
    left_out: dict[str, str] = field(default_factory=dict)
    #: A counts raster (the coverage companion): its resampling is the largest count.
    coverage: bool = False


def band_window_ns(site_z: ZAxis, window: SliceWindow) -> tuple[float, float]:
    """`(top_ns, thickness_ns)` of a site-axis window, as `slice_at` takes it."""
    return (site_z.t0_ns + window.k0 * site_z.dz_ns, window.n_levels * site_z.dz_ns)


def _describe(
    lo: float, hi: float, depths: Mapping[str, tuple[float, float] | None], absent: set[str]
) -> str:
    parts = [f"{lo:.1f}-{hi:.1f} ns"]
    for grid_id, d in depths.items():
        if grid_id in absent:
            parts.append(f"{grid_id} no data")
        elif d is not None:
            parts.append(f"{grid_id} {d[0]:.2f}-{d[1]:.2f} m")
    return " · ".join(parts)


def plan_site_export(
    site_engine: SiteEngine,
    thickness_levels: int,
    step_levels: int,
    *,
    cell: float,
    lattice: SiteLattice,
    transform: str,
    method: str,
    finish: SliceFinish,
    gains: Mapping[str, float],
    velocities: Mapping[str, VelocityModel | None],
    left_out: Mapping[str, str] | None = None,
) -> SiteExportPlan:
    """The bands a site export would write, without writing anything.

    `cell` and `lattice` are the export's own, never the live ones: the file
    records the settings it was made with. `left_out` maps each included grid
    the file will not hold to its state (Ruling F-2); the caller knows what was
    included, the engine only what it was sent. GUI thread: it reads the live
    engines and the session.
    """
    site_z = site_engine.site_z
    ready = site_engine.ready_grids
    if site_z is None or not ready:
        raise RuntimeError("no site geometry: prepare the grids and set a resolution first")
    records = []
    for grid_id in ready:
        engine = site_engine.engine_for(grid_id)
        grid = site_engine.session.grid(grid_id)
        velocity = velocities.get(grid_id)
        records.append(
            SiteGridRecord(
                grid_id=grid_id,
                preset=engine.choice.preset,
                velocity=velocity.to_dict() if velocity is not None else None,
                gain=float(gains.get(grid_id, 1.0)),
                line_spacing_m=float(grid.default_spacing),
                azimuth_deg=float(grid.azimuth),
                crs=grid.crs,
            )
        )
    bands = []
    for window in plan_windows(site_z, thickness_levels, step_levels):
        top, thickness = band_window_ns(site_z, window)
        depths: dict[str, tuple[float, float] | None] = {}
        absent: set[str] = set()
        for grid_id in ready:
            z = site_engine.engine_for(grid_id).z
            grid_window = window_on(z, top, thickness) if z is not None else None
            velocity = velocities.get(grid_id)
            if grid_window is None:
                depths[grid_id] = None
                absent.add(grid_id)
            elif velocity is None:
                depths[grid_id] = None
            else:
                depths[grid_id] = window_depths_m(z, grid_window, velocity)
        lo, hi = window_times_ns(site_z, window)
        bands.append(SiteBand(window, _describe(lo, hi, depths, absent), depths))
    return SiteExportPlan(
        lattice=lattice,
        site_z=site_z,
        bands=tuple(bands),
        transform=transform,
        method=method,
        cell_m=float(cell),
        finish=finish,
        grids=tuple(records),
        left_out=dict(left_out or {}),
    )


def coverage_plan_of(plan: SiteExportPlan) -> SiteExportPlan:
    """The counts companion's plan: the first band's window, raw counts.

    No normalisation, no interpolation, no manual gain: its plan says so (method
    "none", no finish, every recorded gain 1.0) rather than repeating the values
    file's processing, and `coverage=True` tags its resampling `largest_count`.
    """
    first = plan.bands[0]
    return replace(
        plan,
        bands=(replace(first, description="coverage: traces per cell"),),
        method="none",
        finish=None,
        grids=tuple(replace(g, gain=1.0) for g in plan.grids),
        coverage=True,
    )


def world_to_frame(
    source: str, target: str, context: QgsCoordinateTransformContext
) -> Callable[[np.ndarray], np.ndarray]:
    """A function taking (n, 2) points in `source` to `target`, safe off the GUI thread.

    It holds two authids and a copy of the project's transform context taken on
    the GUI thread, and builds a fresh `QgsCoordinateTransform` on every call, so
    no transform object is shared between threads. A missing transform raises: an
    invalid `QgsCoordinateTransform` returns its input unchanged while reporting
    success, which would draw a grid in the wrong place without a word.
    """

    def move(points: np.ndarray) -> np.ndarray:
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem(source), QgsCoordinateReferenceSystem(target), context
        )
        if not transform.isValid():
            raise RuntimeError(f"no coordinate transform from {source} to {target}")
        out = np.empty((len(points), 2), dtype=float)
        for i, (x, y) in enumerate(np.asarray(points, dtype=float)):
            moved = transform.transform(QgsPointXY(float(x), float(y)))
            out[i] = (moved.x(), moved.y())
        return out

    return move


def site_export_spec(
    site_engine: SiteEngine,
    cell: float,
    pixel: float,
    windows: tuple[tuple[float, float], ...],
    *,
    method: str,
    finish: SliceFinish,
    gains: Mapping[str, float],
    coverage: bool = False,
) -> ExportSpec:
    """The whole-site export at `cell` and `pixel`, snapshotted on the GUI thread.

    Reads the live engines and the session once. The grids carry the engines' OWN
    prepared lines (not copies: `estimate_export` leaves them out of what it
    holds on that basis), their frames at `cell`, their own time axes, and the
    finish in each grid's metres. A grid in another CRS than the lattice gets
    `world_to_frame`, built here from a copy of the project's transform context.
    A ready grid with no axis at the site's resolution is absent from every band
    and so left out of the spec. Nothing in the result refers back to an engine.
    """
    lattice = site_engine.lattice_at(cell, pixel)
    session = site_engine.session
    context = QgsProject.instance().transformContext()
    grids = []
    for grid_id in site_engine.ready_grids:
        engine = site_engine.engine_for(grid_id)
        if engine is None or engine.z is None:
            continue
        model = session.grid(grid_id)
        frame = CubeFrame.for_grid(model, cell)
        move = None if frame.crs == lattice.crs else world_to_frame(lattice.crs, frame.crs, context)
        spacing = float(model.default_spacing)
        grids.append(
            ExportGrid(
                grid_id=grid_id,
                lines=engine.prepared_lines(),
                frame=frame,
                z=engine.z,
                finish=finish.in_metres(spacing),
                spacing_m=spacing,
                gain=float(gains.get(grid_id, 1.0)),
                world_to_frame=move,
            )
        )
    return ExportSpec(
        grids=tuple(grids),
        lattice=lattice,
        windows=tuple(windows),
        method="none" if coverage else method,
        coverage=coverage,
    )


def _json(value: Any) -> str:
    return json.dumps(value, separators=_SEPARATORS)


@dataclass(frozen=True, eq=False)
class SiteJob:
    """What one site export hands the task: the snapshot and the plans, for the values
    file and, when asked, the counts companion. Built on the GUI thread."""

    spec: ExportSpec
    plan: SiteExportPlan
    coverage_spec: ExportSpec | None
    coverage_plan: SiteExportPlan | None


def site_windows(plan: SiteExportPlan) -> tuple[tuple[float, float], ...]:
    """Each band's `(top_ns, thickness_ns)` on the site's axis."""
    return tuple(band_window_ns(plan.site_z, band.window) for band in plan.bands)


def site_export_job(
    site_engine: SiteEngine,
    thickness_levels: int,
    step_levels: int,
    cell: float,
    pixel: float,
    *,
    transform: str,
    method: str,
    finish: SliceFinish,
    gains: Mapping[str, float],
    velocities: Mapping[str, VelocityModel | None],
    left_out: Mapping[str, str] | None = None,
    coverage: bool = False,
) -> SiteJob:
    """Plan and snapshot a site export at `cell` and `pixel` (GUI thread, reads the engines).

    The plan names the export's own cell and lattice; the spec is what
    `run_export` makes the bands from. With `coverage`, the counts companion's
    spec (the first band's window) and plan are built too.
    """
    lattice = site_engine.lattice_at(cell, pixel)
    plan = plan_site_export(
        site_engine,
        thickness_levels,
        step_levels,
        cell=cell,
        lattice=lattice,
        transform=transform,
        method=method,
        finish=finish,
        gains=gains,
        velocities=velocities,
        left_out=left_out,
    )
    windows = site_windows(plan)
    spec = site_export_spec(
        site_engine, cell, pixel, windows, method=method, finish=finish, gains=gains
    )
    if not coverage:
        return SiteJob(spec, plan, None, None)
    counts = site_export_spec(
        site_engine, cell, pixel, windows[:1], method="none", finish=finish, gains={}, coverage=True
    )
    return SiteJob(spec, plan, counts, coverage_plan_of(plan))


class GeoTiffSiteWriter:
    """Writes a `SiteExportPlan`'s slices to a multi-band GeoTIFF, band by band."""

    def write_bands(
        self,
        path: str | Path,
        plan: SiteExportPlan,
        bands: Iterable[ExportBand],
        *,
        clip: Normalizer,
        progress_band: Callable[[int], None] | None = None,
    ) -> float:
        """Write `bands` (already on `plan.lattice`) and return the stretch limit.

        `NSGEO_GRID_FACTORS` are each band's own factors, those the export
        measured. Worker-thread safe (see `slice_export.write_north_up`).
        """

        def tag_dataset(dataset: Any) -> None:
            _tag_dataset(dataset, plan)

        def tag_band(band: Any, index: int, shown: ExportBand) -> None:
            band_plan = plan.bands[index]
            lo, hi = window_times_ns(plan.site_z, band_plan.window)
            band.SetMetadataItem("NSGEO_WINDOW_NS", f"{lo},{hi}")
            band.SetMetadataItem("NSGEO_GRID_DEPTHS_M", _json(_depths(band_plan)))
            band.SetMetadataItem("NSGEO_GRID_FACTORS", _json(_factors(plan, shown.factors)))

        return write_north_up(
            path,
            plan.lattice,
            [band.description for band in plan.bands],
            bands,
            clip=clip,
            tag_dataset=tag_dataset,
            tag_band=tag_band,
            progress_band=progress_band,
        )


def _tag_dataset(dataset: Any, plan: SiteExportPlan) -> None:
    """The dataset-level keys: what was done, the export cell and pixel, the resampling."""
    for key, value in {
        "NSGEO_SITE_TRANSFORM": plan.transform,
        "NSGEO_SITE_NORMALISATION": plan.method,
        "NSGEO_SITE_CELL_M": str(plan.cell_m),
        "NSGEO_SITE_PIXEL_M": str(plan.lattice.pixel),
        "NSGEO_SITE_RESAMPLING": "largest_count" if plan.coverage else "bilinear",
        "NSGEO_SITE_Z_UNIT": "ns",
        "NSGEO_SITE_GRIDS": _json([vars(g) for g in plan.grids]),
    }.items():
        dataset.SetMetadataItem(key, value)
    if plan.left_out:
        # Ruling F-2: absent, not `{}`, when nothing was left out.
        dataset.SetMetadataItem("NSGEO_SITE_LEFT_OUT", _json(plan.left_out))
    if plan.finish is not None:
        # Absent, not zero, on a file that was never interpolated.
        for key, value in {
            "NSGEO_SITE_INTERPOLATION": plan.finish.method,
            "NSGEO_SITE_MAX_DISTANCE_SPACINGS": str(plan.finish.max_distance_spacings),
            "NSGEO_SITE_SMOOTH_X_M": str(plan.finish.smooth_x_m),
            "NSGEO_SITE_SMOOTH_Y_M": str(plan.finish.smooth_y_m),
        }.items():
            dataset.SetMetadataItem(key, value)


def _factors(
    plan: SiteExportPlan, factors: Mapping[str, tuple[float, float]]
) -> dict[str, list[float] | None]:
    return {
        g.grid_id: list(factors[g.grid_id]) if g.grid_id in factors else None for g in plan.grids
    }


def _depths(band: SiteBand) -> dict[str, list[float] | None]:
    return {g: list(d) if d is not None else None for g, d in band.depths.items()}


def apply_site_temporal_properties(layer: QgsRasterLayer, plan: SiteExportPlan) -> None:
    """Wire the Temporal Controller to the site's bands, one-to-one (see M11's)."""
    apply_band_windows(layer, [window_times_ns(plan.site_z, band.window) for band in plan.bands])
