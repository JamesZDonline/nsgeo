"""RGB byte array -> QImage, and a cache keyed on (radargram, display settings).

Everything numeric happens in nsgeo.render. Display gain (percentile,
colormap) is not a processing step and is never recorded in a stack.
"""

from __future__ import annotations

import numpy as np
from nsgeo.processing import Radargram
from nsgeo.render import DEFAULT_COLORMAP, PercentileClip, colormap, decimate_columns, to_rgb8
from qgis.PyQt.QtGui import QImage


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    """Wrap an (H, W, 3) uint8 array as an RGB888 QImage that owns its memory.

    `QImage(buffer, ...)` never copies the buffer it is given -- it just
    points at it, so the QImage would show garbage (or crash) the moment
    `rgb`'s array is garbage collected. `.copy()` forces Qt to allocate its
    own storage and copy the pixels in before this function returns, so the
    caller may drop every reference to `rgb` immediately afterwards.

    `np.ascontiguousarray` also guarantees the row stride handed to QImage
    (`3 * w`) is the array's *actual* stride: QImage.Format_RGB888 wants
    each row 32-bit aligned, but that only matters when Qt has to invent a
    stride of its own. Passing the true, explicit stride of a C-contiguous
    buffer sidesteps that entirely -- there is no default for Qt to get
    wrong, and no padding for the copy to reproduce incorrectly.
    """
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class RadargramImage:
    """One radargram rendered once per display setting. Pan and zoom draw
    sub-rectangles of `image`; only a new radargram or a display change
    re-runs numpy."""

    def __init__(
        self,
        rg: Radargram,
        percentile: float = 99.0,
        colormap_name: str = DEFAULT_COLORMAP,
        max_width: int = 8192,
    ) -> None:
        self.rg = rg
        self.percentile = percentile
        self.colormap_name = colormap_name
        self.max_width = max_width
        self.limit = PercentileClip(percentile).limit(rg.data)
        self._image: QImage | None = None

    @property
    def image(self) -> QImage:
        if self._image is None:
            data = decimate_columns(self.rg.data, self.max_width)
            self._image = rgb_to_qimage(to_rgb8(data, self.limit, colormap(self.colormap_name)))
        return self._image

    def with_display(
        self, percentile: float | None = None, colormap_name: str | None = None
    ) -> RadargramImage:
        return RadargramImage(
            self.rg,
            self.percentile if percentile is None else percentile,
            self.colormap_name if colormap_name is None else colormap_name,
            self.max_width,
        )

    def with_radargram(self, rg: Radargram) -> RadargramImage:
        return RadargramImage(rg, self.percentile, self.colormap_name, self.max_width)
