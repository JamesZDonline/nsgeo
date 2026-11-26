"""The Mag panel's map as a GeoTIFF: one float32 band in nT, NaN for no data.

Written through `slice_export.write_north_up`, as the GPR slice export is, so
the file has the same creation options, projection and nodata. GUI-thread work:
one band of at most `MAG_EXPORT_MAX_PIXELS` pixels.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from nsgeo.render import PercentileClip

from nsgeo_qgis.export_pipeline import ExportBand
from nsgeo_qgis.mag_engine import MagMosaic, MagSettings
from nsgeo_qgis.slice_export import write_north_up

BAND_DESCRIPTION = "Magnetic gradient (nT)"


def is_mag_export(path: Path | str) -> bool:
    """Whether the GeoTIFF at `path` is a mag export (`NSGEO_INSTRUMENT=mag`); False
    when it cannot be read."""
    from osgeo import gdal

    try:
        ds = gdal.Open(str(path))
        if ds is None:
            return False
        try:
            return (ds.GetMetadata() or {}).get("NSGEO_INSTRUMENT") == "mag"
        finally:
            ds = None
    except Exception:  # noqa: BLE001 -- unreadable: treat as a GPR export
        return False


def write_mag_geotiff(
    path: Path, mosaic: MagMosaic, settings: MagSettings, *, spacings: Sequence[float]
) -> None:
    """Write `mosaic` to `path`: one band, NaN nodata, in the mosaic's CRS.

    The dataset metadata names the instrument, the unit, the grids and the
    settings the map was made with; `spacings`, each grid's traverse
    spacing in `mosaic.grids` order, turns the reach into metres per grid: one
    number when they agree, else one per grid, comma-joined in that order. A file the
    writer could not finish is left for the caller to delete.
    """
    finish = settings.finish
    if len(spacings) != len(mosaic.grids):
        raise ValueError("one traverse spacing is needed for each grid in the map")
    # The metres the map's own fill used for each grid (`SliceFinish.in_metres`).
    reach = [finish.in_metres(spacing).max_distance_m for spacing in spacings]
    distances = str(reach[0]) if len(set(reach)) == 1 else ",".join(str(r) for r in reach)

    def tag_dataset(dataset: object) -> None:
        dataset.SetMetadata(  # type: ignore[attr-defined]
            {
                "NSGEO_INSTRUMENT": "mag",
                "NSGEO_UNITS": "nT",
                "NSGEO_GRIDS": ",".join(mosaic.grids),
                "NSGEO_CELL_M": str(settings.cell),
                "NSGEO_INTERPOLATION": finish.method,
                "NSGEO_MAX_DISTANCE_M": distances,
                "NSGEO_SMOOTH_X_M": str(finish.smooth_x_m),
                "NSGEO_SMOOTH_Y_M": str(finish.smooth_y_m),
            }
        )

    write_north_up(
        path,
        mosaic.lattice,
        [BAND_DESCRIPTION],
        [ExportBand(mosaic.array, {})],
        clip=PercentileClip(),
        tag_dataset=tag_dataset,
        tag_band=lambda band, index, shown: None,
    )
