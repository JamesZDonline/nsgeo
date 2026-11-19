import sys, runpy
import numpy as np
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2], sys.argv[3] + ".tmp.npz"]
g = runpy.run_path(sys.argv[2] + "/s2_delay.py", run_name="s2")
L, u, gps_xy, profiles, shifts, peak, south, A = (g[k] for k in ["L", "u", "gps_xy", "profiles", "shifts", "peak", "south", "A"])
def run(tau, off, lab):
    al = [gps_xy(ln, tau) @ u + off * (-1.0 if south[i] else 1.0) for i, ln in enumerate(L)]
    F = profiles(al); C = shifts(F)
    s, h = peak(C.sum(axis=1).mean(axis=0))
    pl = np.array([peak(C[k].sum(axis=0))[0] for k in range(len(L))])
    near = np.mean([(F[k] * F[k + 1]).sum() / A.size for k in range(len(L) - 1)])
    print(f"{lab:34s} mean shift {s*100:+5.1f} cm  per-line IQR [{np.percentile(pl,25)*100:+.1f}, {np.percentile(pl,75)*100:+.1f}]  neighbour corr {near:.2f}")
run(0.0, 0.0, "raw GPS")
run(0.35, 0.0, "latency only 0.35 s")
run(0.0, 0.235, "fixed offset only 23.5 cm")
run(0.11, 0.147, "offset 14.7 cm + 0.11 s")
