import sys
sys.path.insert(0, "packages/nsgeo-core/src")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from nsgeo.processing import Radargram, build_step

dt = 0.21653111279010773
n = 8192
def response(W):
    x = np.zeros((n, 1)); x[n // 2] = 1.0
    y = build_step("dewow", window_ns=W).apply(Radargram(data=x, dt_ns=dt, t0_ns=0.0)).data[:, 0]
    H = np.abs(np.fft.rfft(y)); f = np.fft.rfftfreq(n, dt) * 1e3  # MHz
    return f, H
for W in (2.0, 4.0, 8.0):
    f, H = response(W)
    w = int(round(W / dt))
    half = f[np.argmax(H >= 1 / np.sqrt(2))]
    pk = np.argmax(H)
    print(f"W={W} w={w} used={w*dt:.3f}ns half-power={half:.0f}MHz peak={H[pk]:.3f}@{f[pk]:.0f}MHz")
f, H = response(4.0)
fig, ax = plt.subplots(figsize=(7.5, 2.8), constrained_layout=True)
m = f <= 1000
ax.plot(f[m], H[m], color="#1f4e79", lw=1.6)
ax.axhline(1, color="0.7", lw=0.6, ls="--")
ax.axhline(1/np.sqrt(2), color="0.85", lw=0.6, ls=":")
ax.axvline(350, color="#c0392b", lw=1, ls=":")
ax.text(358, 0.08, "350 MHz\n(antenna centre)", fontsize=7, color="#c0392b")
ax.set_xlabel("Frequency (MHz)", fontsize=8)
ax.set_ylabel("Fraction of amplitude kept", fontsize=8)
ax.set_title("Dewow with the default 4 ns window, measured on a single spike", fontsize=10, loc="left")
ax.tick_params(labelsize=7)
fig.savefig(".lavish/help-pages/dewow_response.png", dpi=150)
