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
requires. `C_M_PER_NS` is imported from `nsgeo.velocity`: the first import
out of `nsgeo.processing.*` into another core module by any step. There is
no runtime cycle -- `velocity.py` is a numpy-only leaf whose model imports
are TYPE_CHECKING-only -- and a second copy of the speed of light would be
worse than the precedent.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from nsgeo.processing.base import REQUIRED, ParamSpec, Radargram, register
from nsgeo.velocity import C_M_PER_NS

#: How far from zero a time zero may sit and still be migrated, in ns.
#:
#: Expressed in time rather than in implied depth, deliberately. The residual
#: is produced by `time_zero`'s sample pick, which is a time quantity; the
#: measured band it leaves across its three threshold settings on the real
#: lines is -0.69 to +0.82 ns, so 2.0 ns leaves better than twice the
#: headroom while still refusing an uncorrected -11.09 ns by 5.5x; and a
#: threshold that moved with the number in the velocity box would make the
#: refusal depend on something unrelated to the fault it reports.
MAX_T0_NS = 2.0

#: How many times the record's own length to transform over, in time.
#:
#: The Stolt map reads the spectrum between its sampled frequencies, and
#: how well that reads depends on how fast the spectrum turns: an event at
#: two-way time `t` turns `t * d_omega` radians per bin. Over the record's
#: own length alone, `d_omega = 2*pi/T` makes that a half turn per bin at
#: the bottom even with the origin centred -- right at the limit, and the
#: collapse measurably decays towards it. Doubling the transform halves
#: `d_omega` and leaves a quarter turn, which holds the focus flat across
#: the whole record. Measured on the real lines' sampling, focus at 0.5 m
#: through 3.5 m: 0.98 0.92 0.68 0.33 0.13 0.08 0.08 over the record alone,
#: 0.98 0.98 0.97 0.97 0.96 0.95 0.92 doubled. It costs about 3x the
#: transform (110 ms to 354 ms on a 512 x 640 line).
_T_OVERSAMPLE = 2


def migrate_fk(
    data: np.ndarray,
    *,
    dt_ns: float,
    dx_m: float | None,
    velocity_m_ns: float,
    t0_ns: float = 0.0,
    _pad_traces: int | None = None,
) -> np.ndarray:
    """Migrate `data` (samples x traces) at a constant `velocity_m_ns`.

    Returns an array of the same shape, on the same time axis.

    Refuses rather than guessing, four ways -- a migration run on a file
    with no spatial axis, or on an uncorrected time zero, produces a
    confident image that is wrong by half a metre and that nothing
    downstream will ever flag.

    `_pad_traces` forces the pad width, in traces each side, instead of
    deriving it. Underscore-prefixed because it is not a user parameter and
    must never reach `schema()`: it exists so a test can measure the wrap
    the derived pad prevents, by asking for no pad at all.
    """
    if dx_m is None or not dx_m > 0:
        raise ValueError(
            "migration needs the spacing between traces and this file has none: "
            "it was collected on a timer rather than a survey wheel, so there is "
            "no spatial axis to migrate along"
        )
    if not velocity_m_ns > 0:
        raise ValueError(f"migration velocity must be greater than zero, got {velocity_m_ns}")
    if abs(t0_ns) > MAX_T0_NS:
        depth_m = velocity_m_ns / 2.0 * abs(t0_ns)
        raise ValueError(
            f"time zero is not corrected: this record starts at {t0_ns:.2f} ns, which "
            f"puts everything in it {depth_m:.2f} m off. Correct it with a Time zero "
            f"step (time_zero) ahead of migration."
        )
    arr = np.asarray(data, dtype=float)
    if not np.all(np.isfinite(arr)):
        bad = int(np.count_nonzero(~np.isfinite(arr).all(axis=0)))
        raise ValueError(
            f"{bad} of {arr.shape[1]} traces hold samples that are not finite; one "
            "of them would spread across the whole image through the transform"
        )
    n_samples, n_traces = arr.shape
    vm = velocity_m_ns / 2.0

    # The farthest energy can move laterally is the migration aperture,
    # vm * t_max. That is what the pad has to cover, so the FFT's circular
    # wrap cannot fold energy leaving one end of the line back into the
    # other. It is physically determined; there is no fraction to tune.
    if _pad_traces is not None:
        # Exactly what was asked for, with no rounding up: rounding 640
        # traces to 1024 would itself be a 384-trace pad, which is not the
        # unpadded case a measurement needs.
        pad = int(_pad_traces)
        n_pad = n_traces + 2 * pad
    elif n_traces == 1:
        # The Add-step dialog probes a candidate step against one trace on
        # every keystroke. Padding that to the aperture would cost a
        # 512 x 512 transform per keypress for an answer that cannot differ.
        pad, n_pad = 0, 1
    else:
        pad = int(np.ceil(vm * (n_samples * dt_ns) / dx_m))
        n_pad = 1 << int(n_traces + 2 * pad - 1).bit_length()

    # Twice the record in time, so the frequency axis is sampled at twice
    # the rate the interpolation below needs. See `_T_OVERSAMPLE`. The
    # aperture above is deliberately computed from the REAL record length:
    # the extra rows are empty, and energy cannot migrate out of them.
    n_rows = _T_OVERSAMPLE * n_samples
    padded = np.zeros((n_rows, n_pad), dtype=float)
    padded[:n_samples, pad : pad + n_traces] = arr

    spectrum = np.fft.fft2(padded)
    omega = 2.0 * np.pi * np.fft.fftfreq(n_rows, d=dt_ns)  # rad/ns
    kx = 2.0 * np.pi * np.fft.fftfreq(n_pad, d=dx_m)  # rad/m

    # searchsorted needs the frequency axis ascending; fftfreq is not.
    order = np.argsort(omega)
    omega_asc = omega[order]
    spectrum_asc = spectrum[order, :]

    # Move the time origin to the middle of the record before interpolating,
    # and put it back afterwards. This is what makes the interpolation
    # well-posed rather than merely more accurate. The spectrum of an event
    # at time `t` turns through `t * d_omega` radians per bin; measured from
    # the start of the record that is up to a full turn per bin at the
    # bottom, which is past Nyquist along the frequency axis, and an aliased
    # phasor cannot be recovered by any interpolator -- an eight-point sinc
    # does no better than the two-point form here. Measured from the middle
    # it is at most half a turn, and with `_T_OVERSAMPLE` a quarter.
    t_centre = 0.5 * n_samples * dt_ns
    spectrum_asc = spectrum_asc * np.exp(1j * omega_asc * t_centre)[:, None]

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
    idx = np.clip(idx, 1, n_rows - 1)
    lo, hi = idx - 1, idx
    span = omega_asc[hi] - omega_asc[lo]
    frac = (omega_map - omega_asc[lo]) / span
    mapped = (
        np.take_along_axis(spectrum_asc, lo, axis=0) * (1.0 - frac)
        + np.take_along_axis(spectrum_asc, hi, axis=0) * frac
    )
    mapped *= np.exp(-1j * omega_map * t_centre)

    # Obliquity: the Jacobian d(omega)/d(kz), `vm*|kz|/root`, divided by the
    # `vm` that taking the output on the input's own time grid has already
    # absorbed. What is left is dimensionless and equals 1 at zero dip, so a
    # flat reflector comes through at its own amplitude. Keeping the `vm`
    # scales the whole image by the velocity the user typed -- a factor of
    # 27 at 0.0733 m/ns.
    with np.errstate(invalid="ignore", divide="ignore"):
        obliquity = np.abs(kz)[:, None] / root
    mapped *= np.where(root > 0.0, obliquity, 0.0)

    # Steep dips map to frequencies the record does not contain. Without
    # this they would read the band edge instead and smear it across the
    # image; this is where the evanescent region gets left behind, since
    # |omega_map| >= vm*|kx| holds by construction and energy below that
    # line -- which corresponds to no propagating wave -- is never read.
    mapped[(omega_map < omega_asc[0]) | (omega_map > omega_asc[-1])] = 0.0

    unsorted = np.empty_like(mapped)
    unsorted[order, :] = mapped
    return np.real(np.fft.ifft2(unsorted))[:n_samples, pad : pad + n_traces]


@register
class MigrateFk:
    """Stolt f-k migration as a processing step.

    One parameter. The trace spacing is not one: it comes from the file's
    own header, through `Radargram.dx_m`. The padding is not one either --
    it is the migration aperture `vm * t_max`, which is physically
    determined, and the user has no way to calibrate a fraction.
    """

    name = "migrate_fk"
    title = "Migration (Stolt f-k)"
    group = "Migration"
    order = 1

    def __init__(self, velocity_m_ns: float) -> None:
        self.velocity_m_ns = velocity_m_ns

    @property
    def params(self) -> dict[str, Any]:
        return {"velocity_m_ns": self.velocity_m_ns}

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(
                name="velocity_m_ns",
                kind="float",
                label="Velocity",
                default=REQUIRED,
                unit="m/ns",
                min=0.0,
                max=C_M_PER_NS,
                help=(
                    "How fast the wave travels. Measure it by fitting a diffraction "
                    "hyperbola; the field starts at whatever this line resolves to."
                ),
            ),
        )

    def apply(self, rg: Radargram) -> Radargram:
        migrated = migrate_fk(
            rg.data,
            dt_ns=rg.dt_ns,
            dx_m=rg.dx_m,
            velocity_m_ns=self.velocity_m_ns,
            t0_ns=rg.t0_ns,
        )
        # replace(), not a new Radargram: dx_m and anything else the record
        # carries has to survive the step.
        return rg.replace(data=migrated)
