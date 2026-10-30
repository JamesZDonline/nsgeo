"""Stolt f-k migration: move diffracted energy back to what diffracted it.

A buried object is not recorded where it is. The antenna sees it from every
position that can reach it, so it is written into the radargram as a
hyperbola whose tails are real energy sitting in the wrong place. Migration
moves that energy back.

Constant velocity, exploding-reflector: the solver works at `vm = v / 2`,
the half velocity that makes a one-way downward continuation reproduce the
two-way record. The output stays in **time**, on the input's own axis --
`VelocityModel` relabels it to depth exactly as it does today. Migration
does not change what a sample means; it changes which sample the energy is
in.

numpy only (`fft2`, `ifft2`, `fftfreq`, `searchsorted`), as the core
requires.
"""

from __future__ import annotations

import numpy as np


def migrate_fk(
    data: np.ndarray,
    *,
    dt_ns: float,
    dx_m: float,
    velocity_m_ns: float,
) -> np.ndarray:
    """Migrate `data` (samples x traces) at a constant `velocity_m_ns`.

    Returns an array of the same shape, on the same time axis.
    """
    arr = np.asarray(data, dtype=float)
    n_samples, n_traces = arr.shape
    vm = velocity_m_ns / 2.0

    # The farthest energy can move laterally is the migration aperture,
    # vm * t_max. That is what the pad has to cover, so the FFT's circular
    # wrap cannot fold energy leaving one end of the line back into the
    # other. It is physically determined; there is no fraction to tune.
    if n_traces == 1:
        pad, n_pad = 0, 1
    else:
        pad = int(np.ceil(vm * (n_samples * dt_ns) / dx_m))
        n_pad = 1 << int(n_traces + 2 * pad - 1).bit_length()
    padded = np.zeros((n_samples, n_pad), dtype=float)
    padded[:, pad : pad + n_traces] = arr

    spectrum = np.fft.fft2(padded)
    omega = 2.0 * np.pi * np.fft.fftfreq(n_samples, d=dt_ns)  # rad/ns
    kx = 2.0 * np.pi * np.fft.fftfreq(n_pad, d=dx_m)  # rad/m

    # searchsorted needs the frequency axis ascending; fftfreq is not.
    order = np.argsort(omega)
    omega_asc = omega[order]
    spectrum_asc = spectrum[order, :]

    # The image is wanted on the input's own time axis, so take the vertical
    # wavenumber grid as kz = omega / vm: then vm * kz is the input's own
    # frequency grid and the inverse transform lands on the same sampling.
    kz = omega_asc / vm
    root = np.sqrt(kx[None, :] ** 2 + kz[:, None] ** 2)

    # omega carries kz's sign. Dropping that sign maps the negative
    # frequencies onto the positive ones, destroys the Hermitian symmetry
    # and leaves an image with an imaginary part as large as its real one.
    omega_map = np.sign(kz)[:, None] * vm * root

    idx = np.searchsorted(omega_asc, omega_map)
    idx = np.clip(idx, 1, n_samples - 1)
    lo, hi = idx - 1, idx
    span = omega_asc[hi] - omega_asc[lo]
    frac = (omega_map - omega_asc[lo]) / span
    mapped = (
        np.take_along_axis(spectrum_asc, lo, axis=0) * (1.0 - frac)
        + np.take_along_axis(spectrum_asc, hi, axis=0) * frac
    )

    # Obliquity: the Jacobian d(omega)/d(kz) of the change of variable.
    # Positive everywhere, because omega and kz share a sign.
    with np.errstate(invalid="ignore", divide="ignore"):
        obliquity = vm * np.abs(kz)[:, None] / root
    mapped *= np.where(root > 0.0, obliquity, 0.0)

    # Steep dips map to frequencies the record does not contain. Without
    # this they would read the band edge instead and smear it across the
    # image; this is where the evanescent region gets left behind, since
    # |omega_map| >= vm*|kx| holds by construction and energy below that
    # line -- which corresponds to no propagating wave -- is never read.
    mapped[(omega_map < omega_asc[0]) | (omega_map > omega_asc[-1])] = 0.0

    unsorted = np.empty_like(mapped)
    unsorted[order, :] = mapped
    return np.real(np.fft.ifft2(unsorted))[:, pad : pad + n_traces]
