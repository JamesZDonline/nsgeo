"""Stolt f-k migration (#TBD).

The synthetic point diffractor is the test that catches a sign error in the
omega->kz map, an fftshift slip and a wrong obliquity factor. It is written
against the real data's own numbers -- 0.2165 ns sampling, 60 traces/m, a
350 MHz antenna -- so that what passes here is the geometry and the
bandwidth the local lines actually have.
"""

from __future__ import annotations

import numpy as np
from nsgeo.processing.migration import migrate_fk

# The real local lines: dt 0.2165 ns, 60 traces/m, HS350US at 350 MHz, and
# M13's measured velocity.
V, DT_NS, DX_M = 0.0733, 0.2165, 1 / 60.0
FC_GHZ = 0.35


def _diffraction(
    n_samples, n_traces, dt_ns, dx_m, v, apex_trace, apex_t_ns, fc_ghz=FC_GHZ, amplitude=1.0
):
    """The hyperbola a single point scatterer writes into a zero field.

    Two-way time at lateral offset `x` from a scatterer whose apex is at
    `apex_t_ns`: `sqrt(apex_t_ns**2 + (2x/v)**2)`. A Ricker wavelet of
    centre frequency `fc_ghz` is laid along it, scaled by `(apex/t)**1.5`
    for geometrical spreading.

    Band-limited rather than a bare spike on purpose: a spike is broadband
    to Nyquist, and the hyperbola's moveout reaches about two samples per
    trace on its steep tails, so a spike synthetic is spatially aliased and
    the test would be measuring that aliasing instead of the solver.
    """
    times = np.arange(n_samples, dtype=float) * dt_ns
    data = np.zeros((n_samples, n_traces), dtype=float)
    for trace in range(n_traces):
        x = (trace - apex_trace) * dx_m
        t = np.sqrt(apex_t_ns**2 + (2 * x / v) ** 2)
        if t > times[-1]:
            continue
        arg = (np.pi * fc_ghz * (times - t)) ** 2
        data[:, trace] = amplitude * (apex_t_ns / t) ** 1.5 * (1 - 2 * arg) * np.exp(-arg)
    return data


def _focus(out, row, trace, half=8):
    """Fraction of the image's energy inside a small box around
    (row, trace) -- the measure that tells a collapse from a narrowing.

    Energy, so sums of squares: the sum of |amplitude| over a 512 x 640
    image is dominated by a broad low-amplitude artefact floor spread over
    300,000 pixels, and would report a perfect focus and a smear as nearly
    the same number.
    """
    box = out[max(row - half, 0) : row + half + 1, max(trace - half, 0) : trace + half + 1]
    return float((box**2).sum() / (out**2).sum())


def test_a_point_diffractor_collapses_to_its_apex():
    n_samples, n_traces = 512, 640
    apex_trace, apex_t_ns = 320, 40.0
    data = _diffraction(n_samples, n_traces, DT_NS, DX_M, V, apex_trace, apex_t_ns)

    out = migrate_fk(data, dt_ns=DT_NS, dx_m=DX_M, velocity_m_ns=V)

    peak = np.unravel_index(np.argmax(np.abs(out)), out.shape)
    assert abs(peak[1] - apex_trace) <= 2
    assert abs(peak[0] - round(apex_t_ns / DT_NS)) <= 2
    # The collapse, not merely a narrowing: most of the energy inside a small
    # box around the apex. 0.5 is a literal chosen to sit above what blurring
    # achieves and below a true collapse, not derived from anything the solver
    # computes. Measured: 0.10 unmigrated, 0.70 migrated at this velocity,
    # 0.21 and 0.14 at 0.6x and 1.6x of it.
    assert _focus(out, peak[0], peak[1]) > 0.5


def test_a_constant_field_migrates_to_nothing():
    """What pins the obliquity factor.

    A constant carries no propagating wave, so there is nothing for
    migration to move and the image is empty. The factor `vm*|kz|/root` is
    what makes that true: it is zero at `kz == 0`, which is the whole of a
    constant field's spectrum. Drop the factor and the constant comes
    through untouched; invert it and `kz == 0` divides by zero.
    """
    out = migrate_fk(np.full((256, 256), 5.0), dt_ns=DT_NS, dx_m=DX_M, velocity_m_ns=V)
    assert np.abs(out).max() < 1e-9
