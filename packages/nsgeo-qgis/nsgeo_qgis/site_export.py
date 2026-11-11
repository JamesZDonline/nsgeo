"""The site GeoTIFF: one file over every included grid, which records what was done.

Spec 4.7. Unlike `slice_export`'s per-grid file there is no resample here:
`SiteEngine.slice_at` already returns an array on the site lattice, normalised
and filled exactly as the dock shows it, so a band is written as it came.

Written band by band, one `slice_at` per band, never a resident cube (spec
9.4), like M11's `export_slices`.

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
those of the band's own `SiteSlice`.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from nsgeo.render import Normalizer
from nsgeo.slices import (
    SiteLattice,
    SliceWindow,
    ZAxis,
    plan_windows,
    window_depths_m,
    window_on,
    window_times_ns,
)
from nsgeo.velocity import VelocityModel
from osgeo import gdal
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsRasterLayer

from nsgeo_qgis.export_pipeline import ExportBand
from nsgeo_qgis.site_engine import SiteEngine, SiteSlice
from nsgeo_qgis.slice_export import (
    ExportCancelled,
    band_time_range,
    creation_options,
    write_north_up,
)
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
    #: The CRS as WKT, taken on the GUI thread; None lets the writer resolve it itself.
    crs_wkt: str | None = None


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
    transform: str,
    method: str,
    finish: SliceFinish,
    gains: Mapping[str, float],
    velocities: Mapping[str, VelocityModel | None],
    left_out: Mapping[str, str] | None = None,
) -> SiteExportPlan:
    """The bands a site export would write, without writing anything.

    `left_out` maps each included grid the file will not hold to its state
    (Ruling F-2); the caller knows what was included, the engine only what
    it was sent.
    """
    if site_engine.export_refusal is not None:
        raise RuntimeError(site_engine.export_refusal)
    lattice, site_z = site_engine.lattice, site_engine.site_z
    ready = site_engine.ready_grids
    if lattice is None or site_z is None or not ready:
        raise RuntimeError("no site geometry: prepare the grids and set a resolution first")
    records = []
    cell = None
    for grid_id in ready:
        engine = site_engine.engine_for(grid_id)
        if cell is None and engine.frame is not None:
            cell = engine.frame.cell
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
    if cell is None:
        cell = lattice.pixel  # every grid lacks an axis: nothing is drawn anyway
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


class SiteWriter(Protocol):
    def write(
        self, path: str | Path, plan: SiteExportPlan, slices: Iterable[SiteSlice]
    ) -> None: ...


def _json(value: Any) -> str:
    return json.dumps(value, separators=_SEPARATORS)


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
            crs_wkt=plan.crs_wkt,
            clip=clip,
            tag_dataset=tag_dataset,
            tag_band=tag_band,
            progress_band=progress_band,
        )

    def write(self, path: str | Path, plan: SiteExportPlan, slices: Iterable[SiteSlice]) -> None:
        if not plan.bands:
            raise ValueError("an export plan needs at least one band")
        lattice = plan.lattice
        with warnings.catch_warnings():
            # As `GeoTiffSliceWriter.write`: ExceptionMgr makes GDAL failures raise, and
            # the filter silences the one-time UseExceptions FutureWarning.
            warnings.simplefilter("ignore", FutureWarning)
            with gdal.ExceptionMgr(useExceptions=True):
                dataset = None
                try:
                    dataset = gdal.GetDriverByName("GTiff").Create(
                        str(path),
                        lattice.width,
                        lattice.height,
                        len(plan.bands),
                        gdal.GDT_Float32,
                        options=creation_options(lattice.width, lattice.height),
                    )
                    dataset.SetGeoTransform(lattice.geotransform)
                    dataset.SetProjection(QgsCoordinateReferenceSystem(lattice.crs).toWkt())
                    _tag_dataset(dataset, plan)
                    written = 0
                    iterator = iter(slices)
                    for index, (band_plan, shown) in enumerate(zip(plan.bands, iterator)):
                        if shown.array.shape != (lattice.height, lattice.width):
                            raise ValueError(
                                f"band {index + 1} is {shown.array.shape}, not the lattice's "
                                f"{(lattice.height, lattice.width)}"
                            )
                        band = dataset.GetRasterBand(index + 1)
                        band.SetNoDataValue(float("nan"))
                        band.SetDescription(band_plan.description)
                        lo, hi = window_times_ns(plan.site_z, band_plan.window)
                        band.SetMetadataItem("NSGEO_WINDOW_NS", f"{lo},{hi}")
                        band.SetMetadataItem("NSGEO_GRID_DEPTHS_M", _json(_depths(band_plan)))
                        band.SetMetadataItem(
                            "NSGEO_GRID_FACTORS", _json(_factors(plan, shown.factors))
                        )
                        band.WriteArray(shown.array)
                        written += 1
                    if written != len(plan.bands):
                        raise ValueError(
                            f"expected {len(plan.bands)} slices (one per planned band), got "
                            f"{written}"
                        )
                    if next(iterator, None) is not None:
                        raise ValueError(f"more slices than the plan's {len(plan.bands)} bands")
                finally:
                    # Close() surfaces a write error that garbage collection would swallow.
                    if dataset is not None:
                        dataset.Close()
                    dataset = None


def _tag_dataset(dataset: Any, plan: SiteExportPlan) -> None:
    """The dataset-level keys: what was done, the export cell and pixel, the resampling."""
    for key, value in {
        "NSGEO_SITE_TRANSFORM": plan.transform,
        "NSGEO_SITE_NORMALISATION": plan.method,
        "NSGEO_SITE_CELL_M": str(plan.cell_m),
        "NSGEO_SITE_PIXEL_M": str(plan.lattice.pixel),
        "NSGEO_SITE_RESAMPLING": "bilinear",
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


def export_site(
    site_engine: SiteEngine,
    path: str | Path,
    thickness_levels: int,
    step_levels: int,
    *,
    transform: str,
    method: str,
    finish: SliceFinish,
    gains: Mapping[str, float],
    velocities: Mapping[str, VelocityModel | None],
    writer: SiteWriter | None = None,
    left_out: Mapping[str, str] | None = None,
    progress: Callable[[int, int], bool] | None = None,
) -> SiteExportPlan:
    """Plan, then write one band at a time: one `slice_at` per band, no cube held.

    `progress(done, total)` is called before each band and once more as
    `(total, total)`; a False return raises `ExportCancelled` before the next
    band is computed (`slice_export.export_slices`). `slice_at` is the full
    result by default, so a band is never a preview (plan call 11)."""
    plan = plan_site_export(
        site_engine,
        thickness_levels,
        step_levels,
        transform=transform,
        method=method,
        finish=finish,
        gains=gains,
        velocities=velocities,
        left_out=left_out,
    )
    writer = writer if writer is not None else GeoTiffSiteWriter()

    def _slices() -> Iterable[SiteSlice]:
        total = len(plan.bands)
        for done, band in enumerate(plan.bands):
            if progress is not None and not progress(done, total):
                raise ExportCancelled()
            top, thickness = band_window_ns(plan.site_z, band.window)
            yield site_engine.slice_at(top, thickness, finish=finish, method=method, manual=gains)
        if progress is not None:
            progress(total, total)

    writer.write(path, plan, _slices())
    return plan


def apply_site_temporal_properties(layer: QgsRasterLayer, plan: SiteExportPlan) -> None:
    """Wire the Temporal Controller to the site's bands, one-to-one (see M11's)."""
    props = layer.temporalProperties()
    ranges = {
        index + 1: band_time_range(*window_times_ns(plan.site_z, band.window))
        for index, band in enumerate(plan.bands)
    }
    props.setFixedRangePerBand(ranges)
    props.setMode(Qgis.RasterTemporalMode.FixedRangePerBand)
    props.setIsActive(True)


def write_site_coverage(site_engine: SiteEngine, path: str | Path, plan: SiteExportPlan) -> Path:
    """`<stem>_coverage.tif` beside `path`: one band, the composed coverage.

    At the first band's window. Coverage is composed like values (Ruling 7);
    `slice_at(coverage=True)` already gives NaN where nothing is covered.
    """
    path = Path(path)
    out = path.with_name(f"{path.stem}_coverage.tif")
    first = plan.bands[0]
    top, thickness = band_window_ns(plan.site_z, first.window)
    shown = site_engine.slice_at(
        top,
        thickness,
        finish=SliceFinish(),  # coverage mode shows counts; the finish is not read
        method="none",
        manual={},
        coverage=True,
    )
    # The companion is raw counts: no normalisation, no interpolation, no manual gain. Its
    # plan says so (method "none", no finish, every recorded gain 1.0) rather
    # than repeating the values file's processing.
    coverage_plan = replace(
        plan,
        bands=(replace(first, description="coverage: traces per cell"),),
        method="none",
        finish=None,
        grids=tuple(replace(g, gain=1.0) for g in plan.grids),
    )
    GeoTiffSiteWriter().write(out, coverage_plan, [shown])
    return out
