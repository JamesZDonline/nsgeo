# Stagger and GPS delay on a real zigzag survey — spike notes (2026-11-06)

A throwaway spike run while designing M17 (GPS lines, #134). It measured how far features shift
between neighbouring lines walked in opposite directions, on a real RTK-positioned survey, and it
tried several corrections. It answers most of #47's open "suggested shift" question on real data, so
it is kept here for #47 as well as for M17.

The scripts are in [`2026-11-06-stagger-spike/`](2026-11-06-stagger-spike/) (throwaway quality,
untested). The data is the user's and is never committed: 60 lines `FILE__001`–`FILE__060` (DZT +
DZG + DZX) in `packages/nsgeo-core/tests/data/local/with-dzg/`. Every number below is in local
metres in a frame fitted to the tracks. No coordinates appear here or in the scripts' output.

---

## The survey

One ~30 × 30 m area, 60 zigzag lines (odd files one way, even the other) about 0.5 m apart, GSSI
UtilityScan HS with an HS350 antenna, wheel-triggered at 60 traces/m, RTK GPS at 1 Hz (every fix RTK
fixed). The GPS antenna is believed to sit on a mount over the radar antenna's centre; the user was
not at this collection and cannot vouch for the mount. Walking speed varied a lot: per-line medians
0.33–1.09 m/s.

## Method (s1, s2)

1. **Process each line:** dewow (4 ns), background mean removal, analytic envelope, then average
   into time bins of 8 samples (~1.7 ns). (`s1_prepare.py`)
2. **Place each trace** by GPS as logged: linear interpolation between fixes by trace number,
   linear extrapolation past the first and last fix. Project onto the area's long axis, the mean
   direction of all lines. (`common.py`)
3. **Make an along-axis profile per line and time bin:** resample onto a common 2 cm axis, divide
   by the bin's median over all lines (a crude time gain), low-pass 0.15 m, high-pass 3 m (running
   mean), normalise each line jointly over all bins. **Leave out 2 m at each end**: both ends of every
   line are bright in every window, probably a start/stop artefact, and they would dominate the
   correlation.
4. **Cross-correlate each line against the mean of its two neighbours** (which run the other way),
   per time bin, over lags ±1 m. Express the lag as a shift of the line **in its own direction of
   travel**, so both directions add up instead of cancelling. Sum over bins, average over lines, and
   take the peak with a parabola for sub-step precision.
5. **Sweep a candidate correction** (delay τ applied by re-stamping each fix to the trace at
   `t − τ`, or a fixed along-track offset) and find where the shift crosses zero.

## Results

**As logged, opposite-direction neighbours are offset by −48 cm.** Each line's features sit behind
its neighbours' in its direction of travel. Neighbour correlation at zero lag is −0.56, against
+15 for same-direction pairs (k, k+2).

| Subset (τ = 0) | Shift vs neighbours |
|---|---|
| All lines, all bins (4–70 ns) | −48.3 cm |
| Bootstrap over lines, 95% | −49.9 to −46.9 cm |
| Per-line, median (IQR) | −47.2 (−51.7 to −43.9) cm |
| 4–15 ns / 15–25 / 25–40 / 40–70 ns | −43.7 / −47.4 / −54.7 / −54.4 cm |
| Lines 1–30 / 31–60 | −43.4 / −52.0 cm |
| Thirds along the lines, south → north | −46.8 / −59.0 / −48.2 cm |

**Honest uncertainty.** The bootstrap (±1.5 cm) only resamples lines. Across time windows and parts
of the area the estimate moves between about −44 and −59 cm, so a fair statement is **−48 ± ~6 cm
between neighbours**, i.e. 21–27 cm per line one way.

**Speed: mostly a fixed offset, partly a delay** (`s4_split.py`, 5 m windows within lines, shift
against the summed speed of the line and its neighbours):

| Walking speed (approx.) | One-way shift |
|---|---|
| 0.39 m/s | 21.5 cm |
| 0.65 m/s | 22.8 cm |
| 0.76 m/s | 25.5 cm |
| 0.90 m/s | 27.0 cm |
| 1.07 m/s | 28.2 cm |

A fit of `shift = 2 × (offset + τ × speed)` gives **offset 14.7 cm (95% 10.3–19.4) + τ 0.110 s
(0.047–0.165)**. The total is well determined; the split is not. Between lines (`s3_checks.py`) the
shift also correlates with speed (r = −0.71); that fit gave 12.6 cm + 0.153 s.

**Corrections tried** (`s6_verify.py`), all on the same profiles:

| Correction | Mean shift | Per-line IQR | Neighbour corr |
|---|---|---|---|
| None (raw GPS) | −48.3 cm | −51.7 to −43.9 | −0.56 |
| Delay only, 0.35 s | +0.3 cm | −4.4 to +4.7 | 17.1 |
| Fixed offset only, 23.5 cm | −0.8 cm | −5.2 to +0.4 | 17.9 |
| 14.7 cm + 0.11 s | −2.6 cm | −5.5 to −1.0 | 18.0 |

After any of them the shift by thirds along the line is within ±2 cm. In a slice (s5, s7) the
strongest compact feature (22–28 ns) turns from a sawtooth between alternate lines into a compact
blob.

**Control: the same lines placed by tape** (a nominal 0.5 m grid fitted to the tracks, each line
started at its edge and spaced by the wheel) show **−29.9 cm** between neighbours, per-line median
−30.6 cm, IQR −37.0 to −23.5 cm, p90 |shift| 46 cm. Tape lines are much less consistent line to line
than GPS lines, because the wheel's length error (1.5–3% short here, 15% on `FILE__011`) differs per
line and grows along it (#47's 2026-11-06 comment explains why).

**A second, cruder check** (`s8_feature_peaks.py`): for 15 compact bright spots in three windows,
compare where north-going and south-going lines see each spot's peak. In 13 of 15 the south-going
lines see it further north (median gap 0.31 m, mean 0.39 m; one spot reverses, one shows none).
The direction is confirmed independently; the size is noisier by this method.

## Caveats

- **Symmetry is assumed, not measured.** A comparison between opposite-direction lines measures only
  their disagreement. It cannot say how much belongs to each direction. ("Southbound only" and
  "northbound only" in s2 agree to 1 cm because they are the same pairs counted from each side.)
  Splitting it equally is right for a delay, and for a mount offset when the cart is turned round at
  each end of a line. It would be wrong if the cart is pushed one way and pulled back.
- **The cause is not established.** A mount offset, a delay in stamping the GGA, and where the
  controller counts a trace from (a radar-side offset) all look alike. The tape control's −30 cm
  suggests part of it may be radar-side, but the wheel's length error confounds that. Shallower
  windows give a smaller shift than deeper ones (−44 vs −55 cm); unexplained.
- **This is one survey, and the mount may sit differently next time.** Do not hard-code these values.
- **Mast tilt is not the cause, and causes no stagger.** The GPS is fixed to the cart about 1 m above
  the radar (user), so on a slope it leans downhill by `h · sin(slope)`. It leans downhill whichever
  way the cart travels, so both directions' positions move the same way: an absolute error, not a
  disagreement between neighbours. From the GGA altitudes this site slopes ~1.6° overall and ~2°
  (median) / ~5° (p90) over 3 m stretches: 3.5 cm typical, 8.5 cm on the steeper stretches. A later
  correction could take the slope from the altitude record and the mast height.

## What it means for #47 (destagger)

1. **The "suggested shift" works on real data.** Cross-correlating each line's along-axis envelope
   profile against its opposite-direction neighbours, over many time bins at once, recovers the
   shift with a sharp peak. The details that mattered: envelope after dewow + background removal; a
   per-bin time gain; a 3 m high-pass so slow brightness trends don't dominate; leaving out 2 m at
   the line ends; summing correlation curves over bins before finding the peak; sub-step parabola.
   One slice's worth of time (as #47 proposed) would work, but many bins are much more robust.
2. **Model the shift along each line's direction of travel, applied to every line,** half the
   neighbour disagreement each way. For tape lines this differs from "shift the reverse lines" only
   by a translation of the whole grid along its axis; for GPS lines it keeps features at their true
   positions. One model then serves tape and GPS lines alike.
3. **Grid-wide first, then per line, as #47 designed.** On GPS lines, after the grid-wide shift the
   per-line residual is about ±5 cm (IQR), so per-line refinement matters little. Tape lines vary
   far more (IQR ~13 cm, p90 46 cm), mostly from length error, which a shift cannot fix: #3's
   stretch-to-the-edges first, then the shift.
4. **A speed term can only come from GPS lines.** Tape lines carry no time, so for them the shift is
   one fixed number. For GPS lines a delay term is measurable (0.11 s here) and worth 4–11 cm at
   normal walking speeds.
5. **An acceptance case exists:** these 60 lines, raw GPS placement, expect ~−48 cm between
   neighbours and a compact blob at 22–28 ns once corrected; tape placement, expect ~−30 cm.

## Running the scripts

All read the private data and write only where they are told. From the repository root, with the
dev venv (`.venv/bin/python -I`):

```
s1_prepare.py <with-dzg dir> <out>/prepared.npz            # ~1 min: process + bin all 60 lines
s2_delay.py   <out>/prepared.npz <scripts dir> <out>/delay.npz   # sweep, windows, bootstrap, tape control
s3_checks.py / s4_split.py / s6_verify.py  <out>/prepared.npz <scripts dir> <out>/x  # each reruns s2
s5_slices.py  <out>/prepared.npz <scripts dir> <out>/slices.npz <offset m> <delay s>
s7_plot.py    <out>/slices.npz <out>                         # the two comparison PNGs (not committed)
s8_feature_peaks.py <with-dzg dir>                           # the per-feature cross-check
r1_dzg_survey.py / r2_dzg_gridfit.py <with-dzg dir>          # DZG structure and tape-vs-GPS placement recon
```

The comparison images are not committed: they are pictures of the user's site.
