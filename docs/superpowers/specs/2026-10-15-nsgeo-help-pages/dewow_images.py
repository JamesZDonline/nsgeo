"""Throwaway: dewow figures from campus line FILE__007 for the help-page mockup."""
import sys
from pathlib import Path
sys.path.insert(0, "packages/nsgeo-core/src")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.processing import Radargram, build_step
from nsgeo.processing._util import running_mean
from nsgeo.render import PercentileClip, colormap, to_rgb8

OUT = Path(".lavish/help-pages")
p = Path("packages/nsgeo-core/tests/data/local/FILE__007.DZT")
h = read_header(p)
data = read_samples(p, h)[0].astype(float)
rg = Radargram(data=data, dt_ns=h.dt_ns, t0_ns=h.position_ns)
out = build_step("dewow").apply(rg)
w = int(round(4.0 / rg.dt_ns))
print("dt", rg.dt_ns, "window samples", w)

lut = colormap("grey_black_high")
t = rg.times_ns()
x_m = np.arange(rg.n_traces) / h.traces_per_metre

def panel(ax, arr, title):
    lim = PercentileClip().limit(arr)
    ax.imshow(to_rgb8(arr, lim, lut), aspect="auto",
              extent=[x_m[0], x_m[-1], t[-1], t[0]], interpolation="nearest")
    ax.set_ylim(50, t[0])
    ax.set_title(title, fontsize=10, loc="left")
    ax.set_xlabel("Distance along line (m)", fontsize=8)
    ax.tick_params(labelsize=7)

fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.2), sharey=True, constrained_layout=True)
panel(axes[0], rg.data, "Before")
panel(axes[1], out.data, "After dewow (window 4 ns)")
panel(axes[2], rg.data - out.data, "What dewow removed")
axes[0].set_ylabel("Two-way time (ns)", fontsize=8)
fig.savefig(OUT / "dewow_panels.png", dpi=150)

# One trace: raw, the running mean it subtracts, and the result.
k = rg.n_traces // 2
raw = rg.data[:, k]
mean = running_mean(rg.data, w, axis=0)[:, k]
fig, (a1, a2) = plt.subplots(2, 1, figsize=(10.5, 3.8), sharex=True, constrained_layout=True)
a1.plot(t, raw, color="0.55", lw=0.8, label="Recorded trace")
a1.plot(t, mean, color="#c0392b", lw=2.0, label="Running mean (the 'wow')")
a1.axhline(0, color="0.8", lw=0.6)
a1.legend(fontsize=8, loc="upper right", frameon=False)
a1.set_title(f"One trace (trace {k}), before", fontsize=10, loc="left")
a2.plot(t, raw - mean, color="#1f4e79", lw=0.8)
a2.axhline(0, color="0.8", lw=0.6)
a2.set_title("After: recorded trace minus running mean", fontsize=10, loc="left")
a2.set_xlabel("Two-way time (ns)", fontsize=8)
for a in (a1, a2):
    a.tick_params(labelsize=7)
    a.set_yticks([])
    a.set_xlim(t[0], 40)
fig.savefig(OUT / "dewow_trace.png", dpi=150)

# Frequency response of x - boxcar(x) for the default window.
f = np.linspace(0, 1000, 2000)  # MHz
W = w * rg.dt_ns  # ns, as implemented
H = 1 - np.sinc(f * 1e-3 * W)
fig, ax = plt.subplots(figsize=(6.5, 2.8), constrained_layout=True)
ax.plot(f, np.abs(H), color="#1f4e79", lw=1.6)
ax.axhline(1, color="0.75", lw=0.6, ls="--")
ax.axvline(350, color="#c0392b", lw=1, ls=":")
ax.text(355, 0.1, "350 MHz\n(antenna centre)", fontsize=7, color="#c0392b")
ax.set_xlabel("Frequency (MHz)", fontsize=8)
ax.set_ylabel("Amplitude kept", fontsize=8)
ax.set_title(f"How much of each frequency survives a {W:.2f} ns dewow", fontsize=10, loc="left")
ax.tick_params(labelsize=7)
fig.savefig(OUT / "dewow_response.png", dpi=150)
i3 = np.argmin(np.abs(np.abs(H[:400]) - 1/np.sqrt(2)))
print("half-power", f[i3], "peak", np.abs(H).max(), "at", f[np.argmax(np.abs(H))], "W", W)
