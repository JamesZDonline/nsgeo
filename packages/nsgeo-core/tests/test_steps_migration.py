"""Stolt f-k migration (#TBD).

The synthetic point diffractor is the test that catches a sign error in the
omega->kz map, an fftshift slip and a wrong obliquity factor. It is written
against the real data's own numbers -- 0.2165 ns sampling, 60 traces/m, a
350 MHz antenna -- so that what passes here is the geometry and the
bandwidth the local lines actually have.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing.base import Radargram, build_step
from nsgeo.processing.migration import migrate_fk

# The real local lines: dt 0.2165 ns, 60 traces/m, HS350US at 350 MHz, and
# M13's measured velocity.
V, DT_NS, DX_M = 0.0733, 0.2165, 1 / 60.0
FC_GHZ = 0.35

#: The real lines, gitignored and so absent on CI (see test_real_files.py).
DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []


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


def _flank_row(out, apex_trace, near=40, far=120):
    """Energy-weighted mean sample row of whatever is left on the two
    flanks, in a lateral band clear of the apex itself.

    Which way the residual opens. Energy still *below* the apex is an
    under-collapsed hyperbola; energy *above* it is an over-migrated smile.
    A test that only checks the correct velocity cannot tell migration from
    blurring, and one that only checks that a wrong velocity blurs cannot
    tell the two kinds of wrong apart.
    """
    cols = np.r_[apex_trace - far : apex_trace - near, apex_trace + near : apex_trace + far]
    weights = (out[:, cols] ** 2).sum(axis=1)
    rows = np.arange(out.shape[0], dtype=float)
    return float((weights * rows).sum() / weights.sum())


def _wrong_velocity_case(mult):
    apex_trace, apex_t_ns = 320, 40.0
    data = _diffraction(512, 640, DT_NS, DX_M, V, apex_trace, apex_t_ns)
    out = migrate_fk(data, dt_ns=DT_NS, dx_m=DX_M, velocity_m_ns=V * mult)
    peak = np.unravel_index(np.argmax(np.abs(out)), out.shape)
    return out, _focus(out, peak[0], peak[1]), _flank_row(out, apex_trace), apex_t_ns / DT_NS


def test_too_slow_a_velocity_leaves_a_downward_residual():
    """0.6x the truth: measured focus 0.215, flank energy 50 rows below the
    apex. The 10-row margin is a sign test with room, not a tuned number."""
    _, focus, flank, apex_row = _wrong_velocity_case(0.6)
    assert focus < 0.5
    assert flank > apex_row + 10


def test_too_fast_a_velocity_produces_an_upward_smile():
    """1.6x the truth: measured focus 0.144, flank energy 31 rows above the
    apex -- the opposite side from the under-migrated case."""
    _, focus, flank, apex_row = _wrong_velocity_case(1.6)
    assert focus < 0.5
    assert flank < apex_row - 10


# ---- refusals ------------------------------------------------------------
#
# Migration that runs on uncorrected time zero, or on trace index because the
# file has no spatial axis, produces a confident image that is wrong by half a
# metre, and nothing downstream will ever flag it. Each refusal names its fix.


def _plain(n_samples=128, n_traces=32, t0_ns=0.0, dx_m=DX_M):
    return Radargram(data=np.zeros((n_samples, n_traces)), dt_ns=DT_NS, t0_ns=t0_ns, dx_m=dx_m)


@pytest.mark.parametrize("dx_m", [None, 0.0, -1.0])
def test_refuses_when_there_is_no_trace_spacing(dx_m):
    step = build_step("migrate_fk", velocity_m_ns=V)
    with pytest.raises(ValueError, match="survey wheel"):
        step.apply(_plain(dx_m=dx_m))


def test_refuses_a_velocity_of_zero():
    """The schema's `min=0.0` looks like it catches this and does not:
    `_out_of_bounds` tests `value < spec.min`, so exactly 0.0 is accepted,
    and a hand-edited project or preset can carry it. `vm = 0` makes the
    omega->kz map identically zero and the obliquity factor 0/0 -- a NaN
    image with no complaint -- and it would make 0 the de-facto sentinel
    that an empty value has to stay free to mean later."""
    step = build_step("migrate_fk", velocity_m_ns=0.0)
    with pytest.raises(ValueError, match="greater than zero"):
        step.apply(_plain())


def test_refuses_a_velocity_faster_than_light():
    with pytest.raises(ValueError, match="velocity_m_ns"):
        build_step("migrate_fk", velocity_m_ns=0.4)


def test_refuses_an_uncorrected_time_zero():
    """-11.086 ns is what every local FILE__0NN.DZT carries raw."""
    step = build_step("migrate_fk", velocity_m_ns=V)
    with pytest.raises(ValueError, match="time_zero"):
        step.apply(_plain(t0_ns=-11.086))


def test_refuses_non_finite_samples():
    """One dropped trace must not silently blank the line: a single NaN
    spreads across the whole image through the FFT."""
    rg = _plain()
    data = rg.data.copy()
    data[10, 3] = np.nan
    step = build_step("migrate_fk", velocity_m_ns=V)
    with pytest.raises(ValueError, match="not finite"):
        step.apply(rg.replace(data=data))


@pytest.mark.parametrize("t0_ns", [-0.6929, -0.4764, +0.8228])
def test_accepts_what_time_zero_actually_leaves(t0_ns):
    """What the shipped `time_zero` leaves on the real lines, at its three
    threshold settings: 0.15 -> -0.6929, 0.20 (the default) -> -0.4764,
    0.40 -> +0.8228. All three must migrate. An earlier draft of the design
    set the tolerance at 0.02 m of implied depth error and refused two of
    them outright, and refused the default above about 0.084 m/ns."""
    out = build_step("migrate_fk", velocity_m_ns=V).apply(_plain(t0_ns=t0_ns))
    assert out.t0_ns == t0_ns


@pytest.mark.parametrize("velocity_m_ns", [0.0250, 0.2500])
def test_the_time_zero_tolerance_is_in_time_not_depth(velocity_m_ns):
    """MAX_T0_NS is 2.0 ns, and the refusal must not move with the number in
    the velocity box: 1.9 ns passes and 2.1 ns is refused at a velocity ten
    times the other one. A tolerance derived from velocity passes one and
    fails the other."""
    step = build_step("migrate_fk", velocity_m_ns=velocity_m_ns)
    step.apply(_plain(t0_ns=1.9))
    with pytest.raises(ValueError, match="time_zero"):
        step.apply(_plain(t0_ns=2.1))


# ---- the pad -------------------------------------------------------------


@pytest.mark.parametrize("n_traces", [640, 974])
def test_padding_removes_the_wrap_at_the_far_end(n_traces):
    """A measurement, not an assertion that padding happened.

    The artefact the pad exists to prevent is the FFT's circular wrap:
    energy migrating off one end of the line reappearing at the other. So
    put a diffractor 1 m from the left end, migrate with the derived pad and
    with none, and compare what lands in the rightmost tenth of the line --
    where nothing was recorded and nothing should arrive.

    Two lengths, because rounding the transform up to a power of two is
    itself padding and can hide the absence of the real one. 640 is a real
    line (the local files are 606-666) and rounds to 1024 whatever the pad
    is, so a pad of zero still leaves 384 traces of zero fill and measures
    as if it worked. 974 + 2*244 rounds to 2048 with 830 traces of slack,
    while 974 + 2*24 rounds to 1024 with 24 -- less than the aperture, so
    the wrap lands in the data. Measured: 4256x with the derived pad, 2.6x
    with a tenth of it or none at all.
    """
    n_samples = 512
    data = _diffraction(n_samples, n_traces, DT_NS, DX_M, V, 60, 40.0)
    far = slice(int(n_traces * 0.9), n_traces)

    padded = migrate_fk(data, dt_ns=DT_NS, dx_m=DX_M, velocity_m_ns=V)
    unpadded = migrate_fk(data, dt_ns=DT_NS, dx_m=DX_M, velocity_m_ns=V, _pad_traces=0)

    assert (unpadded[:, far] ** 2).sum() > 10 * (padded[:, far] ** 2).sum()


def test_a_line_shorter_than_the_pad_still_migrates():
    """A 1 m stub is about 60 traces against a 244-trace aperture. It must
    migrate -- no wrap, no crash, no division by a zero-width window."""
    data = _diffraction(512, 60, DT_NS, DX_M, V, 30, 40.0)

    out = migrate_fk(data, dt_ns=DT_NS, dx_m=DX_M, velocity_m_ns=V)

    assert out.shape == data.shape
    assert np.all(np.isfinite(out))
    assert np.abs(out).max() > 0.0


# ---- edges ---------------------------------------------------------------


def test_a_velocity_near_c_empties_the_image_rather_than_inventing_one():
    """At 0.29 m/ns nearly every mapped frequency lands outside the band the
    record actually contains, so there is nothing left to image. The result
    must be visibly empty -- an image a user can tell is wrong -- rather
    than the band edge smeared across it by an extrapolated interpolation.
    """
    data = _diffraction(512, 640, DT_NS, DX_M, V, 320, 40.0)

    out = migrate_fk(data, dt_ns=DT_NS, dx_m=DX_M, velocity_m_ns=0.29)

    assert (out**2).sum() < 0.01 * (data**2).sum()


def test_output_preserves_shape_dt_and_t0():
    """Picks, map-to-profile cursor sync and cube binning all index by
    trace, and `StepStack.difference()` refuses a step that changes the
    sample count. Asserted on a real line, not a square array."""
    if not FILES:
        pytest.skip("no real DZT files in tests/data/local")
    header = read_header(FILES[0])
    data = read_samples(FILES[0], header)[0]
    rg = Radargram(data=np.asarray(data, dtype=float), dt_ns=header.dt_ns, t0_ns=0.0, dx_m=1 / 60.0)

    out = build_step("migrate_fk", velocity_m_ns=V).apply(rg)

    assert out.data.shape == rg.data.shape
    assert out.dt_ns == rg.dt_ns
    assert out.t0_ns == rg.t0_ns
    assert out.dx_m == rg.dx_m


def _top_kx_fraction(image):
    """Fraction of the image's energy in the top quarter of the spatial
    frequency band -- the trace-to-trace oscillation end of it."""
    power = np.abs(np.fft.fft(image, axis=1)) ** 2
    top = np.abs(np.fft.fftfreq(image.shape[1])) > 0.375
    return float(power[:, top].sum() / power.sum())


def test_migration_does_not_manufacture_trace_to_trace_oscillation():
    """What zeroing the out-of-band region is for.

    Steep dips map to frequencies the record does not contain. Left to
    itself the interpolation extrapolates from the band edge instead, by a
    factor that grows without bound as the dip steepens -- so the artefact
    arrives at the top of the spatial band, as oscillation from one trace
    to the next.

    White noise, because real GPR data is band-limited and has nothing near
    its own Nyquist to extrapolate from: with a 350 MHz wavelet the cut is
    unreachable, and this is the input that reaches it. The standard is the
    record itself, not a chosen number: migration must not leave more of
    the image at the top of the band than the record put there. Measured
    0.25 in, 0.15 out; without the cut, 0.70.
    """
    noise = np.random.default_rng(0).normal(size=(512, 256))

    out = migrate_fk(noise, dt_ns=DT_NS, dx_m=DX_M, velocity_m_ns=V)

    assert _top_kx_fraction(out) <= _top_kx_fraction(noise)
