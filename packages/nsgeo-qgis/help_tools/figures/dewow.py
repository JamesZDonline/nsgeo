"""Dewow figures: one trace, the before / after panels, and the frequency response."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from nsgeo.io.dzt import DztHeader
from nsgeo.processing import Radargram, build_step

from help_tools.figures.common import antenna_mhz, panels, save, stack_of

DPI = 150
SPIKE_SAMPLES = 8192


def _response(dt_ns: float, window_ns: float) -> tuple[np.ndarray, np.ndarray]:
    """(frequency in MHz, |rfft|) of dewow applied to a unit spike."""
    x = np.zeros((SPIKE_SAMPLES, 1))
    x[SPIKE_SAMPLES // 2] = 1.0
    spike = Radargram(data=x, dt_ns=dt_ns, t0_ns=0.0)
    y = build_step("dewow", window_ns=window_ns).apply(spike).data[:, 0]
    return np.fft.rfftfreq(SPIKE_SAMPLES, dt_ns) * 1e3, np.abs(np.fft.rfft(y))


def measure(dt_ns: float, windows_ns: tuple[float, ...] = (2.0, 4.0, 8.0)) -> list[dict]:
    """The numbers the page quotes, measured on a spike through nsgeo's own dewow."""
    rows = []
    for window in windows_ns:
        f, h = _response(dt_ns, window)
        samples = int(round(window / dt_ns))
        peak = int(np.argmax(h))
        rows.append(
            {
                "window_ns": window,
                "samples": samples,
                "used_ns": samples * dt_ns,
                "half_power_mhz": float(f[np.argmax(h >= 1 / np.sqrt(2))]),
                "peak_gain": float(h[peak]),
                "peak_mhz": float(f[peak]),
            }
        )
    return rows


def _trace_figure(rg: Radargram, stack, out: Path) -> Path:
    k = rg.n_traces // 2
    t = rg.times_ns()
    raw = rg.data[:, k]
    mean = stack.difference(0).data[:, k]
    after = stack.intermediate(0).data[:, k]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10.5, 3.8), sharex=True, constrained_layout=True)
    a1.plot(t, raw, color="0.55", lw=0.8, label="Recorded trace")
    a1.plot(t, mean, color="#c0392b", lw=2.0, label="Running mean (the 'wow')")
    a1.legend(fontsize=8, loc="upper right", frameon=False)
    a1.set_title(f"One trace (trace {k}), before", fontsize=10, loc="left")
    a2.plot(t, after, color="#1f4e79", lw=0.8)
    a2.set_title("After: recorded trace minus running mean", fontsize=10, loc="left")
    a2.set_xlabel("Two-way time (ns)", fontsize=8)
    for a in (a1, a2):
        a.axhline(0, color="0.8", lw=0.6)
        a.tick_params(labelsize=7)
        a.set_yticks([])
        a.set_xlim(t[0], 40)
    return save(fig, out, dpi=DPI)


def _response_figure(dt_ns: float, header: DztHeader, out: Path) -> Path:
    f, h = _response(dt_ns, 4.0)
    m = f <= 1000
    fig, ax = plt.subplots(figsize=(7.5, 2.8), constrained_layout=True)
    ax.plot(f[m], h[m], color="#1f4e79", lw=1.6)
    ax.axhline(1, color="0.7", lw=0.6, ls="--")
    ax.axhline(1 / np.sqrt(2), color="0.85", lw=0.6, ls=":")
    mhz = antenna_mhz(header)
    if mhz is not None:
        ax.axvline(mhz, color="#c0392b", lw=1, ls=":")
        ax.text(mhz + 8, 0.08, f"{mhz} MHz\n(antenna centre)", fontsize=7, color="#c0392b")
    ax.set_xlabel("Frequency (MHz)", fontsize=8)
    ax.set_ylabel("Fraction of amplitude kept", fontsize=8)
    ax.set_title(
        "Dewow with the default 4 ns window, measured on a single spike", fontsize=10, loc="left"
    )
    ax.tick_params(labelsize=7)
    return save(fig, out, dpi=DPI)


def make(rg: Radargram, header: DztHeader, out_dir: Path) -> list[Path]:
    stack = stack_of(rg, [build_step("dewow")])
    return [
        _trace_figure(rg, stack, out_dir / "dewow_trace.png"),
        panels(
            stack,
            0,
            out_dir / "dewow_panels.png",
            "After dewow (window 4 ns)",
            "What dewow removed",
            header,
            dpi=DPI,
        ),
        _response_figure(rg.dt_ns, header, out_dir / "dewow_response.png"),
    ]
