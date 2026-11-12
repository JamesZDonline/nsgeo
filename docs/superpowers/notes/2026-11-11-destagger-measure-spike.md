# Measuring the destagger on grid-placed lines: spike notes (2026-11-11)

A throwaway spike for #159 (automatic destagger), run while designing it. It asks whether the
2026-11-06 stagger spike's method (`2026-11-06-stagger-spike.md` on branch `nsgeo-m17-gps`) still
recovers the right shift on **tape-placed** lines, unfitted and fitted to the grid's edges, and it
compares the answer with the values the user found by eye in the placement-corrections
walkthrough (2026-11-11).

The scripts are in [`2026-11-11-destagger-measure-spike/`](2026-11-11-destagger-measure-spike/).
They are throwaway quality and untested. The data is the user's and is never committed. No
coordinates appear here: every number is in grid-local metres, and the comparison images are not
committed because they are pictures of the user's site.

---

## Data

- **Nashville City Cemetery 2023, Grid 1.** 60 zigzag lines at 0.5 m on a 29.98 m grid, HS350,
  60 traces/m. **This is the same survey as `tests/data/local/with-dzg/`** (`FILE__001.DZT` has the
  same md5). The two acceptance cases in #159 (Grid 1 unfitted +0.15, the 60-line survey fitted
  −0.15) are therefore one survey seen two ways.
- **Nashville City Cemetery 2023, Grid 2.** 60 zigzag lines at 0.5 m on a 29.96 m grid. This is an
  independent case. Since 2026-11-11 it is in `tests/data/local/grid2/`, as links to the raw files,
  for #159's per-line tests.

Recorded line lengths: Grid 1 median 29.57 m (25.98–30.87), so the fit scale is a median of 1.014.
Grid 2 median 29.43 m (27.50–29.90), fit scale median 1.018.

## Method

The method is the 2026-11-06 spike's, with placement taken from `GridPlacement`
(`start + dir·(scale·i/tpm + travel_shift)`) instead of GPS:

1. Process each line with dewow (4 ns) and background mean removal, take the analytic envelope,
   then average into 8-sample time bins.
2. Place every trace on the grid's along axis. "Unfitted" uses scale 1 with each line starting at
   its edge. "Fitted" uses scale = length / recorded span with both ends on the edges.
3. Resample onto a 2 cm axis. Per time bin, divide by the median over all lines (a time gain),
   low-pass at 0.15 m and high-pass at 3 m. Zero the 2 m at each line's own ends, then normalise
   each line jointly over all bins.
4. Correlate each line against the **mean of its two neighbours** (opposite direction, by offset
   order), over lags of ±1 m. Express the lag as a shift in the line's own direction of travel and
   sum the curves over bins. Take the peak with a parabola. Half the neighbour disagreement, with
   its sign changed, is the destagger: `destagger = −shift / 2`.

## Results: the grid-wide value

Destagger in metres:

| Grid | Lines | Whole record (4–70 ns) | 14.9–19.7 ns (the depth the user judged) | After applying it |
|---|---|---|---|---|
| 1 | unfitted | **+0.152** (95% +0.140…+0.165) | +0.147 | neighbour shift −0.1 cm |
| 1 | fitted | **−0.065** (95% −0.057…−0.073) | −0.106 | +0.1 cm |
| 2 | unfitted | **+0.165** | +0.186 | −0.1 cm |
| 2 | fitted | **−0.059** | −0.051 | 0.0 cm |

- **Unfitted, the measurement matches the eye.** The user found +0.15 "much better", +0.10 too
  little and +0.25 a little too much.
- **The sign flips on fitting, without being told to.** A wheel reading 1.4% short, with lines
  started at their edges, pushes opposite neighbours apart by about (scale − 1) × length ≈ 0.4 m,
  the same at every point along the line. That looks exactly like stagger. Fitting removes it, and
  the remainder (+13 cm between neighbours on both grids) goes the other way.
- **Fitted, the eye chose −0.15 on Grid 1.** The whole-record value is −0.065. On the grid's most
  compact strong feature (a blob 24.5 m along, across 22–24 m) the straightest edges are at about
  −0.15. A box measurement there gives −0.127 at the judged depth (−0.114 over all depths). The
  blob sits in the far third of the grid, where the fitted lines want more (below).

## Depth and position along the line

Destagger by depth window (rows) and third of the grid along the lines (columns), whole grid,
normalised profiles:

| | 2–10 m | 10–20 m | 20–28 m | all |
|---|---|---|---|---|
| **Grid 1 unfitted** 4–15 ns | +0.121 | +0.148 | +0.140 | +0.143 |
| 15–25 ns | +0.127 | +0.135 | +0.115 | +0.131 |
| 25–40 ns | +0.167 | +0.180 | +0.145 | +0.160 |
| 40–70 ns | +0.161 | +0.174 | +0.150 | +0.163 |
| **Grid 1 fitted** 4–15 ns | −0.068 | −0.062 | −0.088 | −0.075 |
| 15–25 ns | −0.075 | −0.085 | −0.123 | −0.094 |
| 25–40 ns | −0.031 | −0.051 | −0.066 | −0.050 |
| 40–70 ns | −0.031 | −0.052 | −0.068 | −0.049 |
| **Grid 2 unfitted** 4–15 ns | +0.120 | +0.163 | +0.149 | +0.141 |
| 15–25 ns | +0.191 | +0.159 | +0.210 | +0.183 |
| 25–40 ns | +0.238 | +0.234 | +0.240 | +0.209 |
| 40–70 ns | +0.243 | +0.232 | +0.216 | +0.245 |
| **Grid 2 fitted** 4–15 ns | −0.082 | −0.105 | −0.072 | −0.079 |
| 15–25 ns | −0.057 | −0.052 | −0.038 | −0.049 |
| 25–40 ns | −0.035 | −0.011 | −0.026 | −0.030 |
| 40–70 ns | −0.031 | +0.008 | −0.023 | −0.027 |

- **Deeper always wants 3–8 cm more forward shift.** This holds on both grids, both placements
  and every third of the lines. The 2026-11-06 GPS spike saw the same trend (−44 cm shallow, −55 cm
  deep between neighbours). Real features would not line up that consistently. Stagger proper, a
  positioning error, is the same at every depth (the user's point, which these numbers do not
  contradict). A guess at the cause: the antenna "looks" slightly ahead rather than straight down
  (a degree or two of tilt in the cart, or an asymmetric antenna pattern), so deeper reflectors
  appear further back along the direction of travel. That flips with direction just as stagger
  does. **Not established; out of scope for #159.**
- **On fitted Grid 1 the far third wants about 3 cm more** at most depths. A single stretch per
  line cannot follow a wheel that errs unevenly. That is leftover wheel error, not stagger.

## Per-line values

After the grid-wide value, each line was measured against its neighbours from independent halves
of the data:

| Case | Per-line residual IQR | Shallow vs deep: r, median \|diff\| | First vs second half along: r, median \|diff\| |
|---|---|---|---|
| Grid 1 unfitted | −5.4…+5.6 cm | 0.25, 4.9 cm | 0.08, 6.6 cm |
| Grid 1 fitted | −5.5…+4.3 cm | 0.26, 6.4 cm | −0.01, 9.1 cm |
| Grid 2 unfitted | −26.8…+6.5 cm | 0.51, 10.1 cm | 0.50, 11.3 cm |
| Grid 2 fitted | −7.5…+4.9 cm | 0.66, 6.7 cm | 0.12, 11.3 cm |

(The residual is the line's shift in its own direction of travel against the mean of its
neighbours.)

- **For most lines the per-line residual is noise.** It is about ±5 cm, and the halves disagree by
  about as much. Applying it would add wiggle.
- **A handful of lines are clearly off, consistently across all four halves.** Grid 2 lines 45
  (about −0.7 m), 27 and 28 (about −0.5 m) unfitted; lines 51 (−0.2 m) and 59 (+0.2 m) fitted;
  Grid 1 line 15 fitted (−0.14 m). These are the kind the user expects from a start off the
  baseline. Grid 2 line 44 agrees in three of four halves (−0.7 m unfitted, −0.4 m fitted).
- **Some are not consistent along the line.** Grid 1 lines 8 and 9 read about +0.25 m shallow
  and in the second half, +0.08 to +0.17 m deep, but about 0 in the first half (−0.10 and −0.10
  unfitted, +0.03 and +0.02 fitted). Grid 1's strong compact features sit mostly in the second half, so the
  first-half estimate may simply have little to match. An along-the-line halves test needs
  features in both halves to mean anything.
- **Some lines change partway along.** Grid 1 `FILE__011` is the known 4 m wheel slip: unfitted, its
  halves read +0.30 and −0.79 m. A shift cannot fix such a line.
- **Some estimates hit the ±1 m search limit** (Grid 1 fitted `FILE__029`, Grid 2 fitted
  `FILE__050`): no clear match.
- **What comparing against the mean of both neighbours cannot see.** It ignores anything that
  changes steadily across the grid. A real wall running at an angle is safe: it is not
  "straightened". By the same token, a baseline that is not square (each line's start a little
  further along than the last) is invisible to it.

## Per-line prototype (planning, 2026-11-11)

Written while planning #159, to give the per-line task a starting method:
[`per_line_block.py`](2026-11-11-destagger-measure-spike/per_line_block.py) with
[`per_line_common.py`](2026-11-11-destagger-measure-spike/per_line_common.py). It is throwaway, and its
thresholds are first guesses: clear peak ratio 0.25, own value at least 0.10 m, halves agree within
max(0.10 m, 30% of the residual), changes partway beyond 0.30 m.

**Method.**
1. Apply the grid value.
2. Measure each line's residual against the mean of its two neighbours, from the whole record and
   from four halves: shallow (4–25 ns), deep (25–70 ns), first half along and second half along.
3. Classify each line:
   - *No clear match:* the whole-record peak is not clear.
   - *Changes partway along:* both along halves are clear and differ by more than 0.30 m.
   - *Candidate:* the residual is at least 0.10 m, and one pair of halves (shallow/deep or
     first/second) is clear and agrees.
4. Solve each run of adjacent candidates jointly with the second-difference model:
   `x_k − mean(x_neighbours) = r_k`, in grid coordinates, on the run's own rows. Re-measure with the
   candidates corrected, solve for the increment, and repeat 3 times.
5. A candidate whose solved value stays under 0.10 m keeps the grid value. It was dragged by a bad
   neighbour.

**What it gets right.**
- Grid 2 unfitted: `FILE__045` +0.881 (residual −0.72), and `FILE__027` +0.665 and `FILE__028`
  +0.687 together.
- Grid 2 fitted: `FILE__051` +0.147 and `FILE__059` −0.287. `FILE__050` changes partway along.
- Grid 1 unfitted: `FILE__011` changes partway along.
- Injected into Grid 1 unfitted:
  - `FILE__031` moved +0.30 m comes back as +0.31. Its neighbours keep the grid value.
  - `FILE__031` and `FILE__032`, both moved +0.30 m, come back as +0.31 and +0.30.
- The re-measure loop converges in 2–3 passes (the last change is under 1.3 cm).

**What it gets wrong.**
- **A large move is under-measured.** `FILE__031` moved −0.50 m comes back as −0.43. With
  `FILE__032` also moved +0.30, they come back as −0.42 and +0.25. On fitted Grid 1, a −0.50 move
  of `FILE__022` beside a +0.30 move of `FILE__021` comes back as −0.34, and `FILE__021` loses its
  clear match.
- **Lines near the threshold come and go.** Adding a 0.02 m × rank skew changes which lines
  around ±0.10–0.20 m get own values (Grid 1 unfitted: 6 own values before, 6 after, but only 3
  are the same lines). Values of 0.5 m and more are stable.
- **Many own values.** Grid 2 unfitted gets 15 own values (25% of lines). Grid 1 gets 6
  unfitted and 2 fitted.
- **The mean of the neighbours goes two-peaked** when a neighbour is far off: half its energy
  matches each neighbour. A single correlation then reads 0 or the far neighbour's shift, not the
  linear model's half-way value. The re-measure loop helps only once the far neighbour is
  corrected.

**Tried and dropped.**
- Greedy coordinate ascent on pairwise neighbour curves. It moves the first of two adjacent off
  lines by their joint residual, then cannot find the second.
- An L1-sparse joint solve over all lines, iterated. It diverged next to a line with no clear
  match (Grid 2 fitted, `FILE__049` to `FILE__051`).
- Second differences built from pairwise peaks. Each pair has half the data, so the peaks were
  too noisy and lost `FILE__045`.

## Cost

Processing (read, dewow, background removal, envelope, bin) takes about 0.15 s per line:
10 lines took 1.75 s wall including start-up, with a peak of 260 MB resident. A 60-line grid is
therefore about 10 s to process. The correlation itself takes a few seconds more in this
unoptimised code. Re-measuring after a placement change only needs the resampling and
correlation, not the processing.

## Running the scripts

Run from the repository root with the dev venv. `destagger_panels.py` needs matplotlib, so use
`.venv-qgis`. Pass data paths as arguments:

```
destagger_spike.py <cache.npz> <survey.nsgeo.json> <grid id>     # grid value: unfitted, fitted, checks
destagger_spike.py <cache.npz> --dir <dzt folder> <length m>      # zigzag at 0.5 m, line 1 forward
grid_measure.py    <cache.npz> <survey.nsgeo.json> <grid id>     # depth x along-third table
local_measure.py   <cache.npz> <survey.nsgeo.json> <grid id>     # box and weighting variants
perline.py         <cache.npz> <survey.nsgeo.json> <grid id>     # per-line repeatability
per_line_block.py  <cache.npz> <survey.nsgeo.json> <grid id> [k:d ...] [skew]   # per-line prototype
destagger_panels.py <cache.npz> <survey> <grid> <t0> <t1> <out.png> "label:fit:shift" ...  # line strips (CROP=a0,a1,c0,c1)
```

The cache holds the processed, binned envelopes. It is built on the first run and reused after.
