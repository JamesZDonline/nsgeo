"""Directional Gaussian smoothing of a slice (interpolation spec §6).

Smoothing is a separate, optional step after interpolation: a Gaussian per
frame axis, in metres, so the along-line and cross-line blur can be tuned
apart while the cells stay square. It averages over data only, so a blank cell
stays blank and a data cell beside a blank is not pulled toward zero.

numpy only, no scipy: the 1-D kernels are applied as shifted sums.
"""

from __future__ import annotations

import math

import numpy as np

SMOOTH_TRUNCATE_SIGMAS: float = 4.0  # kernel half-width, in sigmas (interpolation spec §6)


def _kernel(sigma_m: float, cell: float) -> np.ndarray:
    """Symmetric 1-D Gaussian weights, truncated at `SMOOTH_TRUNCATE_SIGMAS`."""
    sigma = sigma_m / cell
    radius = int(math.ceil(SMOOTH_TRUNCATE_SIGMAS * sigma))
    offsets = np.arange(-radius, radius + 1, dtype=float)
    return np.exp(-(offsets**2) / (2.0 * sigma**2))


def _blur(field: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    """`field` convolved with `kernel` along `axis`, zero beyond the edge."""
    radius = kernel.size // 2
    n = field.shape[axis]
    out = np.zeros_like(field)
    for offset in range(-min(radius, n - 1), min(radius, n - 1) + 1):
        src = [slice(None)] * 2
        dst = [slice(None)] * 2
        if offset >= 0:
            src[axis], dst[axis] = slice(offset, n), slice(0, n - offset)
        else:
            src[axis], dst[axis] = slice(0, n + offset), slice(-offset, n)
        out[tuple(dst)] += kernel[offset + radius] * field[tuple(src)]
    return out


def smooth(values: np.ndarray, cell: float, sigma_x_m: float, sigma_y_m: float) -> np.ndarray:
    """`values` blurred by a Gaussian of `sigma_x_m` along axis 1 and `sigma_y_m` along axis 0.

    Axis 1 is frame X, axis 0 is frame Y. Both the data (blank cells counted
    as zero) and the data mask are blurred with the same kernels and divided,
    so each result is a weighted mean of the finite cells near it. Cells that
    were NaN stay NaN, and a sigma of 0 leaves that axis untouched. Returns
    float32.
    """
    if not (sigma_x_m >= 0.0 and sigma_y_m >= 0.0):
        raise ValueError(f"smoothing sigmas must be >= 0, got {sigma_x_m}, {sigma_y_m}")
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    num = np.where(finite, values, 0.0)
    den = finite.astype(float)
    for sigma_m, axis in ((sigma_x_m, 1), (sigma_y_m, 0)):
        if sigma_m == 0.0:
            continue
        kernel = _kernel(sigma_m, cell)
        num = _blur(num, kernel, axis)
        den = _blur(den, kernel, axis)
    out = np.full(values.shape, np.nan, dtype=float)
    np.divide(num, den, out=out, where=finite)
    return out.astype(np.float32)
