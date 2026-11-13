"""A slice coloured with the user's own QGIS symbology (#180).

With **my own colours** chosen in the Slices panel, the live slice layer keeps
whatever the user set in Layer Properties ▸ Symbology: the colour ramp, its
interpolation, the min/max. The plugin stops replacing the renderer, and
instead does three small things here:

* `seed_style` starts the user from what the plugin was showing: its palette as
  a gradient ramp QGIS's own editor can hold (`nsgeo.render.gradient_stops`),
  at the plugin's limit, as numbers the user typed ("User defined").
* `refit` follows QGIS's own min/max settings on every new slice. Numbers the
  user typed stay. A computed range (Min/max, Cumulative cut, Mean ± SD) is
  worked out again for the new slice by the same rule (`nsgeo.render.
  display_range`), over the whole slice or the current canvas as chosen;
  "Updated canvas" is left to QGIS, which refits it as it draws. Only the two
  end values move: the colours and their spacing along the ramp stay.
* `style_text` / `apply_style_text` carry the style as QGIS style XML (the
  Symbology category only), which is how it is remembered with the survey and
  in a saved cube, and how it reaches an export's `.qml`.

GUI thread only: everything here touches a QGIS layer.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from nsgeo.render import colormap, display_range, gradient_stops
from qgis.core import (
    QgsColorRampShader,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsMapLayer,
    QgsRasterLayer,
    QgsRasterMinMaxOrigin,
    QgsRasterShader,
    QgsReadWriteContext,
    QgsSingleBandGrayRenderer,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtXml import QDomDocument

#: `iface.showLayerProperties` page name for a raster's Symbology tab.
SYMBOLOGY_PAGE = "mOptsPage_Style"
#: QGIS's sample size when the min/max accuracy is "Estimate (faster)".
_ESTIMATE_SAMPLES = 250_000


def _member(enum: Any, *names: str) -> Any:
    """An enum member by its name in QGIS 3.42 and later, or by the one QGIS
    3.40 (the oldest this plugin supports) gave it."""
    for name in names:
        if hasattr(enum, name):
            return getattr(enum, name)
    raise AttributeError(f"{enum!r} has no member named any of {names}")


_LIMITS = QgsRasterMinMaxOrigin.Limits
_EXTENT = QgsRasterMinMaxOrigin.Extent
LIMIT_TYPED = _member(_LIMITS, "NotSet", "None_")  # "User defined"
LIMIT_MIN_MAX = _member(_LIMITS, "MinimumMaximum", "MinMax")
LIMIT_CUT = _member(_LIMITS, "CumulativeCut")
LIMIT_STD_DEV = _member(_LIMITS, "StdDev")
EXTENT_CANVAS = _member(_EXTENT, "FixedCanvas", "CurrentCanvas")  # "Current canvas"
EXTENT_UPDATED = _member(_EXTENT, "UpdatedCanvas")
_EXACT = _member(QgsRasterMinMaxOrigin.StatAccuracy, "Exact")

_KINDS = {
    LIMIT_MIN_MAX: "minimum_maximum",
    LIMIT_CUT: "cumulative_cut",
    LIMIT_STD_DEV: "std_dev",
}

Extent = tuple[float, float, float, float]


def seed_style(
    layer: QgsRasterLayer,
    colormap_name: str,
    limit: float,
    unipolar: bool,
    centre: float = 0.0,
) -> None:
    """Put the plugin's palette and limit on `layer` as an editable QGIS style.

    A pseudocolour renderer on band 1 whose source ramp is the palette as a
    gradient, classified continuously from it, between `centre - limit` (or 0
    for unipolar data) and `centre + limit` (or `limit`), held as user-defined numbers.
    """
    from nsgeo_qgis.slice_layer import apply_smooth_resampling

    stops = gradient_stops(colormap(colormap_name))
    ramp = QgsGradientColorRamp(
        QColor(*stops[0][1]),
        QColor(*stops[-1][1]),
        False,
        [QgsGradientStop(position, QColor(*rgb)) for position, rgb in stops[1:-1]],
    )
    lo = 0.0 if unipolar else float(centre) - float(limit)
    hi = float(limit) if unipolar else float(centre) + float(limit)
    function = QgsColorRampShader(lo, hi, ramp)
    function.setColorRampType(QgsColorRampShader.Type.Interpolated)
    function.classifyColorRamp()
    shader = QgsRasterShader(lo, hi)
    shader.setRasterShaderFunction(function)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    renderer.setClassificationMin(lo)
    renderer.setClassificationMax(hi)
    origin = renderer.minMaxOrigin()
    origin.setLimits(LIMIT_TYPED)
    renderer.setMinMaxOrigin(origin)
    layer.setRenderer(renderer)
    apply_smooth_resampling(layer)


def style_text(layer: QgsRasterLayer) -> str:
    """`layer`'s symbology as QGIS style XML."""
    doc = QDomDocument()
    error = layer.exportNamedStyle(doc, QgsReadWriteContext(), QgsMapLayer.StyleCategory.Symbology)
    if error:
        raise ValueError(f"could not read the layer's style: {error}")
    return doc.toString()


def apply_style_text(layer: QgsRasterLayer, text: str) -> None:
    """Put a style from `style_text` on `layer`. Raises `ValueError` when QGIS
    cannot read it."""
    doc = QDomDocument()
    parsed = doc.setContent(text)
    if not (parsed[0] if isinstance(parsed, tuple) else bool(parsed)):
        raise ValueError("the saved colours are not a QGIS style")
    ok, error = layer.importNamedStyle(doc, QgsMapLayer.StyleCategory.Symbology)
    if not ok:
        raise ValueError(f"QGIS could not apply the saved colours: {error}")


def refit(
    layer: QgsRasterLayer,
    array: np.ndarray,
    geotransform: tuple[float, ...],
    canvas_extent: Extent | None = None,
) -> bool:
    """Work a computed min/max out again for a new slice; True when it moved.

    `array` is what the layer now reads, north-up on `geotransform`.
    `canvas_extent` is the map view in the layer's CRS, for "Current canvas".
    Typed numbers ("User defined"), "Updated canvas" (QGIS refits as it
    draws), a renderer with no min/max, and a slice with no range to fit all
    leave the style as it is.
    """
    renderer = layer.renderer()
    if renderer is None:
        return False
    origin = renderer.minMaxOrigin()
    kind = _KINDS.get(origin.limits())
    if kind is None or origin.extent() == EXTENT_UPDATED:
        return False
    values = array
    if origin.extent() == EXTENT_CANVAS and canvas_extent is not None:
        values = crop(array, geotransform, canvas_extent)
    exact = origin.statAccuracy() == _EXACT
    fitted = display_range(
        values,
        kind,
        lower=origin.cumulativeCutLower(),
        upper=origin.cumulativeCutUpper(),
        sd_factor=origin.stdDevFactor(),
        max_samples=None if exact else _ESTIMATE_SAMPLES,
    )
    if fitted is None or fitted == style_range(layer):
        return False
    return set_range(layer, *fitted)


def set_range(layer: QgsRasterLayer, lo: float, hi: float) -> bool:
    """Move the style's two end values to `lo` and `hi`, keeping the colours.

    A pseudocolour ramp's stops keep their places along it: each value moves
    in proportion. A grey renderer's contrast stretch takes the new ends.
    Other renderers have no range to move (False).
    """
    renderer = layer.renderer()
    if isinstance(renderer, QgsSingleBandPseudoColorRenderer):
        clone = renderer.clone()
        function = clone.shader().rasterShaderFunction()
        if not isinstance(function, QgsColorRampShader):
            return False
        items = function.colorRampItemList()
        old = _item_range(clone)
        moved = []
        for index, item in enumerate(items):
            value = item.value
            if math.isfinite(value):
                if old is None:
                    share = index / max(len(items) - 1, 1)
                else:
                    share = (value - old[0]) / (old[1] - old[0])
                value = lo + share * (hi - lo)
            moved.append(QgsColorRampShader.ColorRampItem(value, item.color, _label(value)))
        function.setColorRampItemList(moved)
        function.setMinimumValue(lo)
        function.setMaximumValue(hi)
        clone.shader().setMinimumValue(lo)
        clone.shader().setMaximumValue(hi)
        clone.setClassificationMin(lo)
        clone.setClassificationMax(hi)
        layer.setRenderer(clone)
        return True
    if isinstance(renderer, QgsSingleBandGrayRenderer) and renderer.contrastEnhancement():
        clone = renderer.clone()
        clone.contrastEnhancement().setMinimumValue(lo)
        clone.contrastEnhancement().setMaximumValue(hi)
        layer.setRenderer(clone)
        return True
    return False


def style_range(layer: QgsRasterLayer) -> tuple[float, float] | None:
    """The two end values the style colours between, or None if it has none."""
    renderer = layer.renderer()
    if isinstance(renderer, QgsSingleBandPseudoColorRenderer):
        shown = _pseudocolour_range(renderer)
        if shown is None:
            return None
        lo, hi = shown
    elif isinstance(renderer, QgsSingleBandGrayRenderer) and renderer.contrastEnhancement():
        enhancement = renderer.contrastEnhancement()
        lo, hi = enhancement.minimumValue(), enhancement.maximumValue()
    else:
        return None
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None
    return float(lo), float(hi)


def legend_text(layer: QgsRasterLayer | None) -> str:
    """The Slices panel's Legend line while the slice wears the user's colours."""
    base = "your own colours"
    if layer is None or layer.renderer() is None:
        return base
    origin = layer.renderer().minMaxOrigin()
    if origin.limits() in _KINDS and origin.extent() == EXTENT_UPDATED:
        return f"{base} · fitted to the map view"
    shown = style_range(layer)
    if shown is None:
        return f"{base} (Layer Properties ▸ Symbology)"
    return f"{base} · {shown[0]:.3g} – {shown[1]:.3g}"


def crop(array: np.ndarray, geotransform: tuple[float, ...], extent: Extent) -> np.ndarray:
    """The cells of a north-up `array` that touch `extent` (xmin, ymin, xmax,
    ymax, in the array's CRS); an empty array when they do not overlap."""
    x0, px, _, y0, _, py = geotransform
    xmin, ymin, xmax, ymax = extent
    rows, cols = array.shape
    c0 = max(0, int(math.floor((xmin - x0) / px)))
    c1 = min(cols, int(math.ceil((xmax - x0) / px)))
    r0 = max(0, int(math.floor((ymax - y0) / py)))
    r1 = min(rows, int(math.ceil((ymin - y0) / py)))
    if c1 <= c0 or r1 <= r0:
        return array[:0, :0]
    return array[r0:r1, c0:c1]


def _pseudocolour_range(renderer: Any) -> tuple[float, float] | None:
    """A pseudocolour renderer's classification range. `clone()` does not copy
    the renderer's own (it reads NaN after one, measured on QGIS 3.44); its
    shader's, which it does copy, stands in."""
    lo, hi = renderer.classificationMin(), renderer.classificationMax()
    if math.isfinite(lo) and math.isfinite(hi):
        return float(lo), float(hi)
    function = renderer.shader().rasterShaderFunction() if renderer.shader() else None
    if not isinstance(function, QgsColorRampShader):
        return None
    lo, hi = function.minimumValue(), function.maximumValue()
    if math.isfinite(lo) and math.isfinite(hi):
        return float(lo), float(hi)
    finite = [item.value for item in function.colorRampItemList() if math.isfinite(item.value)]
    if finite:
        return float(finite[0]), float(finite[-1])
    return None


def _item_range(renderer: Any) -> tuple[float, float] | None:
    """The range the ramp's items were placed over: the renderer's own, else
    their first and last finite values; None when neither is a range."""
    shown = _pseudocolour_range(renderer)
    if shown is not None and shown[1] > shown[0]:
        return shown
    return None


def _label(value: float) -> str:
    return f"{value:.4g}" if math.isfinite(value) else ""
