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

from functools import lru_cache

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


def _smooth_size(n: int) -> int:
    """The smallest integer >= n whose only prime factors are 2, 3 and 5.

    numpy's FFT is fastest at such lengths and slowest at large primes.
    Because a linear convolution padded further only gains trailing zeros,
    rounding the transform size up is free of any effect on the cropped
    result -- measured 1.1x to 3.2x faster across the sizes a slice
    actually reaches, with the worst case (1021x1019 at r=10) falling from
    361 ms to 114 ms.

    Must never return less than `n`: a short transform would WRAP the
    convolution and corrupt the edges of the slice. Cheap cluster (M11
    final review): "silently" was wrong -- the failure is loud, not
    silent. A short crop makes the numerator and denominator arrays come
    back smaller than `(ny, nx)`, and `fill`'s own `np.divide(num, den,
    out=np.full((ny, nx), np.nan), ...)` then raises on the shape
    mismatch rather than returning a quietly-wrong array.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    candidate = n
    while True:
        rest = candidate
        for prime in (2, 3, 5):
            while rest % prime == 0:
                rest //= prime
        if rest == 1:
            return candidate
        candidate += 1


@lru_cache(maxsize=4)
def _kernel_spectrum(radius_cells: int, shape: tuple[int, int]) -> np.ndarray:
    """The disc's transform at a padded size, cached across calls.

    The radius is a live slider (spec 9.2), so the same kernel is
    transformed again on every tick at an unchanged slice shape. Bounded
    at four entries because each is a complex128 array of roughly
    `shape[0] * (shape[1] // 2 + 1) * 16` bytes -- 9.3 MB at the largest
    size measured here, so ~37 MB worst case, released by
    `clear_kernel_cache()`.

    The returned array is SHARED. `fill` only multiplies with it and never
    writes into it; any future caller must do the same or take a copy.
    """
    return np.fft.rfft2(disc_kernel(radius_cells), s=shape)


def clear_kernel_cache() -> None:
    """Drop the cached kernel spectra. Called when a slice source is
    closed, so a large cube's spectra do not outlive the session that
    needed them."""
    _kernel_spectrum.cache_clear()


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
    finite = np.isfinite(values)
    numerator = np.where(finite, values, 0.0) * counts
    # The denominator must convolve the SAME masked counts the numerator
    # uses, not raw `counts`: a NaN value with a non-zero count would
    # otherwise contribute 0 to the numerator but full weight to the
    # denominator, dragging the weighted mean toward zero. `cube.py`
    # documents NaN iff count 0 as an invariant, but nothing here enforces
    # it, so this must hold even if that invariant is ever violated.
    counts_for_denominator = np.where(finite, counts, 0.0)

    shape = (_smooth_size(ny + 2 * r), _smooth_size(nx + 2 * r))
    spectrum = _kernel_spectrum(r, shape)
    num = np.fft.irfft2(np.fft.rfft2(numerator, s=shape) * spectrum, s=shape)
    den = np.fft.irfft2(np.fft.rfft2(counts_for_denominator, s=shape) * spectrum, s=shape)
    num = num[r : r + ny, r : r + nx]
    den = den[r : r + ny, r : r + nx]

    out = np.divide(num, den, out=np.full((ny, nx), np.nan), where=den >= min_count)
    return out.astype(np.float32)
