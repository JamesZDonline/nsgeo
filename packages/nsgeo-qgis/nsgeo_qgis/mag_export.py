"""The Mag panel's map as a GeoTIFF: one float32 band in nT, NaN for no data.

Written through `slice_export.write_north_up`, as the GPR slice export is, so
the file has the same creation options, projection and nodata. GUI-thread work:
one band of at most `MAG_EXPORT_MAX_PIXELS` pixels.
"""

from __future__ import annotations

from pathlib import Path

from nsgeo.mag import MagSetup
from nsgeo.render import PercentileClip

from nsgeo_qgis.export_pipeline import ExportBand
from nsgeo_qgis.mag_engine import MagMosaic, MagSettings
from nsgeo_qgis.slice_export import write_north_up

BAND_DESCRIPTION = "Magnetic gradient (nT)"


def write_mag_geotiff(
    path: Path, mosaic: MagMosaic, settings: MagSettings, *, spacing_m: float | None = None
) -> None:
    """Write `mosaic` to `path`: one band, NaN nodata, in the mosaic's CRS.

    The dataset metadata names the instrument, the unit, the grids and the
    settings the map was made with; `spacing_m`, the traverse spacing (the
    first shown file's), turns the reach into metres. A file the writer could not finish is
    left for the caller to delete.
    """
    finish = settings.finish
    spacing = spacing_m if spacing_m is not None else MagSetup().spacing_m

    def tag_dataset(dataset: object) -> None:
        dataset.SetMetadata(  # type: ignore[attr-defined]
            {
                "NSGEO_INSTRUMENT": "mag",
                "NSGEO_UNITS": "nT",
                "NSGEO_GRIDS": ",".join(mosaic.grids),
                "NSGEO_CELL_M": str(settings.cell),
                "NSGEO_INTERPOLATION": finish.method,
                "NSGEO_MAX_DISTANCE_M": str(finish.max_distance_spacings * spacing),
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
