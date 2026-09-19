"""Filling the space between lines.

At 0.5 m line spacing and 0.10 m cells about 80% of cells are empty, so
this is most of the picture rather than a cosmetic afterthought.

The fill is one operation: convolve the numerator (value x count) and the
denominator (count) with the same radial kernel, then divide. That single
form is GPRSLICE's oversized search box, and inverse-distance weighting
with a radius, and a uniform disc -- only the kernel differs. Because it
consumes the stored pair rather than replacing it, the radius stays a
slider and the unfilled truth is always still underneath.

numpy only: the convolution goes through rfft2, which needs no scipy.
"""

from __future__ import annotations

import numpy as np


def disc_kernel(radius_cells: int) -> np.ndarray:
    """A flat disc of the given radius, as a (2r+1, 2r+1) float array.

    A disc rather than a square: a box kernel is separable and faster, but
    it is anisotropic and prints square artefacts into the slice, which
    read as structure.
    """
    if radius_cells < 0:
        raise ValueError(f"radius_cells must be >= 0, got {radius_cells}")
    r = int(radius_cells)
    yy, xx = np.ogrid[-r : r + 1, -r : r + 1]
    return ((xx * xx + yy * yy) <= r * r).astype(float)


def fill(
    values: np.ndarray,
    counts: np.ndarray,
    radius_cells: int,
    min_count: float = 0.5,
) -> np.ndarray:
    """Smear (values, counts) with a disc and return the weighted mean.

    Cells whose weighted count stays below `min_count` remain NaN: beyond
    the radius there is no evidence, and inventing a value there is exactly
    the failure mode a coverage-aware design exists to avoid.
    """
    values = np.asarray(values, dtype=float)
    counts = np.asarray(counts, dtype=float)
    if values.shape != counts.shape:
        raise ValueError(
            f"values and counts must have the same shape, got {values.shape} and {counts.shape}"
        )
    if values.ndim != 2:
        raise ValueError(f"expected a 2-D slice, got shape {values.shape}")
    if radius_cells < 0:
        raise ValueError(f"radius_cells must be >= 0, got {radius_cells}")
    if radius_cells == 0:
        out = np.where(counts > 0, values, np.nan)
        return out.astype(np.float32)

    r = int(radius_cells)
    ny, nx = values.shape
    kernel = disc_kernel(r)
    numerator = np.where(np.isfinite(values), values, 0.0) * counts

    shape = (ny + 2 * r, nx + 2 * r)
    spectrum = np.fft.rfft2(kernel, s=shape)
    num = np.fft.irfft2(np.fft.rfft2(numerator, s=shape) * spectrum, s=shape)
    den = np.fft.irfft2(np.fft.rfft2(counts, s=shape) * spectrum, s=shape)
    num = num[r : r + ny, r : r + nx]
    den = den[r : r + ny, r : r + nx]

    out = np.divide(num, den, out=np.full((ny, nx), np.nan), where=den >= min_count)
    return out.astype(np.float32)
