"""The `.qml` written beside an exported GeoTIFF (spec 6.3, decisions 13 and 16).

A QGIS project that adds the file then draws it as the plugin did: the same
colour ramp, the stretch measured on the export's own bands, and bilinear
resampling when zoomed in. Other GIS software ignores the file and reads the
values. GUI-thread only: it builds a QGIS layer.
"""

from __future__ import annotations

from pathlib import Path

from nsgeo.render import colormap
from qgis.core import QgsRasterLayer, QgsSingleBandPseudoColorRenderer

from nsgeo_qgis.slice_layer import apply_smooth_resampling, build_shader


def write_style(path: str | Path, *, limit: float, colormap_name: str, unipolar: bool) -> Path:
    """Save `<stem>.qml` beside `path` and return it.

    QGIS applies a `.qml` of the same base name as the layer's default style
    when the raster is added. An existing one is replaced. Raises `OSError`
    when QGIS cannot write it.
    """
    path = Path(path)
    layer = QgsRasterLayer(str(path), path.stem, "gdal")
    if not layer.isValid():
        raise OSError(f"QGIS cannot read {path} to style it")
    shader = build_shader(colormap(colormap_name), limit, unipolar)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    renderer.setClassificationMin(0.0 if unipolar else -float(limit))
    renderer.setClassificationMax(float(limit))
    layer.setRenderer(renderer)
    apply_smooth_resampling(layer)
    out = path.with_suffix(".qml")
    message, ok = layer.saveNamedStyle(str(out))
    if not ok:
        raise OSError(f"could not write the style file {out}: {message}")
    return out
