# nsgeo time and depth slices (Plan 4, M10–M12) — design

Plan 3 (M7–M9) gives the plugin the map ↔ profile link, picking, and a release. This phase adds
the third dimension: a volume binned from every line in a grid, sliced horizontally into the
amplitude maps archaeologists interpret, and navigated live.

The parent spec is `2026-09-10-nsgeo-qgis-plugin-design.md`, which listed timeslices as
"designed for, not built". This document is that design. Where the parent's assumptions and the
measurements here disagree, the measurements win and the difference is stated.

---

## 1. What this phase is for

A radargram answers "what is under this line". A slice answers "what is under this field", which
is the question an archaeologist actually asks. Every GPR package produces slices; the reason to
produce them here is that this plugin already knows where each trace is, which line it came
from, and how it was processed — so a slice can stay connected to the data it came from instead
of becoming a picture in a GIS.

Three things follow from that and shape everything below:

- Slices are **derived**, never a source of truth. The survey JSON and the DZT files remain the
  truth; a cube is regenerable, like the GeoPackage.
- A slice must be able to **say where it came from** — which lines, which recipe, how much data
  is under each cell.
- **Nothing runs automatically.** A cube is built by an explicit act, from an explicitly chosen
  preset, exactly as the step stack works today.

---

## 2. Starting state, measured

Checked against the merged code, not assumed.

**What exists and is reusable.** `Line.trace_coords(frames)` already returns per-trace world
coordinates, which is the entire geometric input a binner needs. `StepStack` and the step
registry give a recipe that is serialisable and reproducible. `Site.presets` already stores named
stacks keyed by name rather than by line — built for exactly this. `lookup.nearest_trace` and
M7's `MapLink` already implement map → profile. `render.py` maps amplitude to colour.

**What is missing.** There is no cube, no binning, no amplitude transform, and no raster output
of any kind. `render.py` maps amplitude **symmetrically about zero** (`to_index8`: `-limit → 0`,
`0 → 128`, `+limit → 255`), which is correct for bipolar radargrams and wrong for the unipolar
data a slice is made of. `SiteLayers` manages vector tables only; the parent spec already
recorded that float rasters must be GeoTIFFs beside the GeoPackage, because GeoPackage rasters
are 8-bit tiles.

**Measured facts about the real data** (`FILE__001.DZT`, the reference set of ten):

| | |
|---|---|
| samples per trace | 512 |
| range | 110.86 ns |
| native `dt` | **0.2165 ns** |
| `t0` | −11.09 ns |
| ε_r | 14 → v = 0.080 m/ns |
| shape after a four-step preset | 463 × 608 |

463 is prime, which matters in §6.2.

---

## 3. Decisions taken in brainstorming

| | Decision | Why |
|---|---|---|
| Product | A **3-D cube**, sliceable any way | Thickness and overlap become view parameters instead of rebuild parameters |
| Frame | **Grid-local cells**, resampled north-up only on export | A cell column then draws from a consistent set of traces; rotated GeoTIFFs are second-class in GDAL/QGIS |
| Extent | **One cube per grid**, mosaicked at site level | Grids differ in azimuth and velocity, and are not amplitude-comparable anyway |
| Recipe | **One preset for every line** | Amplitude comparability between lines is the premise of a slice |
| Transform | A **registered step**, usable on a profile | You can see on a radargram what the cube will be built from |
| Gridding | **Bin, then fill** — keep both | The binned array is honest; smoothing is a display choice. Also orientation-free (§6.4) |
| Empty cells | **Count array + nodata** | GPRSLICE writes 0, which is indistinguishable from no reflection |
| Storage | **mean + count**, filled at slice time | Search radius becomes a slider |
| Files | **`.npz` in core, GeoTIFF from the plugin** | Forced, not chosen: the core is numpy-only and cannot write a GeoTIFF |
| dz | **Native `dt` by default**, as a slider | Measured: native costs 83 MB and 44 ms. Nothing is bought by decimating |
| Residency | **Streaming by default**, resident cube opt-in | Measured: a slice binned on demand costs 3.6 ms and no cube |
| UI | A **Slices dock, tabified with Processing** | No new screen space; Processing has spare room below a ten-step stack |
| Stretch | **Shared across the cube**, per-slice override | Comparability by default, legibility on demand |
| Link | **Ambient hover + Select**, no new tool | M7 already built it; only the time-window band is new |

---

## 4. Prior art, and where we differ

Sources, and how closely each was read: **in full** — USGS OFR 02-166's `GPRSLICE` chapter
(Lucius & Powers 2002), RGPR's `.sliceInterp` source, and Geolitix's slices documentation.
**Secondhand** — Conyers's and Goodman's conventions, taken from literature summaries citing
them rather than from the books themselves, and De Angeli et al. (2022) from its abstract, the
publisher having refused the full text. The conventions below are well attested across those
summaries, but the numbers in them are rules of thumb we have not verified at source.

**GPRSLICE** builds a voxel volume by binning. Each cell has a **search box** defaulting to the
cell size and independently resizable (`box_Xsize/Ysize/Zsize`), so cells can overlap or leave
gaps; traces in the box are stacked, transformed (`xfrm_method` = `NONE`/`ABS`/`SQR`/`INST`/`POW`),
averaged over the Z box, and accumulated. Empty cells are written as 0 and the advice is to
enlarge the box rather than interpolate.

**RGPR** interpolates instead. Each trace is spline-resampled onto a common z-vector, then every
z-level is interpolated from scattered (x, y, v) points by multilevel B-splines (`MBA::mba.surf`)
and masked outside a convex hull. It interpolates **signed** amplitude; an envelope is a
preprocessing choice, not part of slicing.

**Convention** (Conyers; Goodman's GPR-SLICE; Geolitix): spatially averaged squared amplitude or
Hilbert envelope; a window of at least one pulse width and no thicker than the smallest expected
target; kriging or IDW with a search radius; cell size no smaller than the trace spacing and no
larger than half the line spacing; search radius about 1.5 × line spacing.

**Where we differ, and why:**

1. **Bin first, fill second, keep both.** GPRSLICE bins and stops; RGPR interpolates and never
   bins. Binning at 0.5 m line spacing is defensible because the data is near-gridded, and it
   keeps the honest measurement separable from the cosmetic step. It is also the only one of the
   two that is orientation-free without extra machinery (§6.4).
2. **Coverage is recorded.** Neither stores a count. A zero that means "no data" reading as "no
   reflection" is a defect, and fixing it is free.
3. **Thickness is a view parameter.** Both fix it at build time. A fine-dz cube makes it a
   slider, so Conyers's rule can be satisfied by eye rather than by arithmetic.
4. **The transform is inspectable.** It is a step you can put on a profile, not a hidden mode.
5. **One multi-band GeoTIFF per cube**, where everyone else writes `slice01…slice40`.
6. **The slice stays attached to the profiles.** No other package does this, and it is the point.

---

## 5. The data model

All of §5 and §6 lives in `nsgeo-core`: numpy only, no QGIS, no Qt.

### 5.1 `CubeFrame`, which is not a `Grid`

```python
@dataclass(frozen=True)
class CubeFrame:
    origin: tuple[float, float]   # world coordinates of the (0, 0) cell corner
    azimuth: float                # degrees clockwise from north to +Y, as Grid
    cell: float                   # metres; square cells
    nx: int
    ny: int
    crs: str
```

A `Grid` is a survey frame: continuous extents in metres, a default line spacing, an optional
velocity. A cube frame is a raster: integer cell counts and a cell size. Reusing `Grid` would
mean inventing a fake grid for lines that belong to none.

That case is not hypothetical. **Arbitrary paths are the reason this type exists.** Binning
consumes per-trace world coordinates and never learns that lines were parallel — GPRSLICE states
the same property of its own volume — so RTK-positioned lines from a future DZG reader need no
new algorithm, only a frame that does not come from a `Grid`. Two constructors:

- `CubeFrame.for_grid(grid, cell)` — origin, azimuth and extents from the grid.
- `CubeFrame.for_points(xy, cell, azimuth=None)` — an oriented bounding box over the traces,
  the equivalent of RGPR's `obbox`, with a caller-supplied azimuth as an override.

Cells are square. A rectangular cell would let the cross-line and along-line resolutions be
tuned separately, which sounds useful and is not: it bakes an acquisition artefact into the
product, and the fill radius already covers the real need.

### 5.2 `ZAxis`

```python
@dataclass(frozen=True)
class ZAxis:
    t0_ns: float
    dz_ns: float
    nz: int
```

Two-way time, not depth. Depth is derived through the existing `VelocityModel`, exactly as the
profile's second axis already is, so a cube built under one velocity relabels under another
without rebinning. `dz_ns` defaults to the native `dt` of the grid's first line.

An elevation-referenced z-axis — RGPR supports one, and it is what topographic correction
eventually needs — is **designed for and not built**: nothing in the cube's shape assumes the
axis is time, only this class does.

### 5.3 `SliceCube`

```python
@dataclass(frozen=True)
class SliceCube:
    frame: CubeFrame
    z: ZAxis
    mean: np.ndarray     # (nz, nx*ny) float32, NaN where count == 0
    count: np.ndarray    # (nx*ny,) int32 — traces contributing to each cell
    provenance: Provenance
```

**Z-major, `(nz, ncells)`, is measured rather than assumed.** The scatter and the slice
extraction want opposite memory orders; §7.3 has the numbers.

**Count is per cell, not per (level, cell).** That is exact only when every line spans the whole
z-window, so the builder **rejects** a line whose time range does not cover it, names the line,
and offers to shrink the window — rather than silently counting a zero-padded level as data.
Per-grid cubes make this nearly always true, since files from one survey share a range setting.
The exact general form factorises as `count(z, cell) = Σ_lines valid(line, z) × traces(line, cell)`,
both factors small; that is the designed-for extension if mixed ranges ever matter.

`Provenance` records what a reader needs to trust the thing: the line keys, the preset name and
its serialised steps, the transform, the velocity model, the build time, and the core version.

### 5.4 On disk

The core writes `slices/<grid_id>__<name>.npz` holding `mean`, `count`, and a JSON metadata
blob. The survey JSON gains a `cubes` list recording the recipe and pointing at the file.

Derived, like the GeoPackage: the JSON is the truth, the `.npz` is regenerable, and a missing
one is an offer to rebuild rather than an error. `.npz` rather than GeoTIFF because the core has
numpy and nothing else; the plugin converts, with GDAL, on the way to the map.

---

## 6. Processing

### 6.1 The pipeline, and why the tiers matter

```
per line:  load → preset → transform  │  resample to ZAxis → bin into (sum, count)
           └─────── tier 1 ───────────┘  └──────────── tier 2 ────────────────────┘
                 cached; depends on              depends on dz, z-range, cell
                 the preset only
                                                  │
                                       tier 3:    └→ z-window → coarsen → fill → colour
```

The split is the whole performance story. Tier 1 is expensive and depends on **neither** dz nor
cell size, so caching it makes every geometric parameter cheap to change. §7 measures all three.

### 6.2 Amplitude transforms are steps

Three new entries in the existing step registry, each a pure `Radargram → Radargram`:

| step | what | cost, per line |
|---|---|---|
| `amp_abs` | absolute value | 0.2 ms |
| `amp_square` | `A²`, the convention's energy measure | 0.2 ms |
| `amp_envelope` | Hilbert analytic-signal modulus | 26 ms |

`amp_envelope` is numpy-only: build the analytic signal by doubling the positive frequencies of
a full FFT and zeroing the negative half. No scipy, matching the core's constraint.

**Do not pad the FFT.** The envelope is the most expensive single step — twice the whole
four-step preset — because `time_zero` leaves 463 samples, a prime length and the worst case for
an FFT. Zero-padding to 480 is 2.2× faster, and it was measured and rejected: the transform is
non-local, so padding shifts the result by 1.3% through the interior and 13% in the last rows.
The envelope lives in the cached tier where 0.6 s happens once, so exactness is the better trade.
Reflect-padding is worse than zero-padding (2.6% interior), not better.

These steps make the data **unipolar**, which `render.py` must know about. The `Step` protocol
gains an optional class attribute `unipolar: bool = False`; these three set it `True`, and the
renderer consults the last enabled step. See §8.

### 6.3 Binning

Per line, two things are precomputed because they change only when their input changes:

- From the `ZAxis` and the line's own `dt`/`t0`: the source `(index, weight)` pair per target
  level. Source times are uniform, so this is closed-form and the resample is two gathers and a
  blend across all traces at once — no per-trace loop.
- From the cell size: the trace order that sorts by cell id, the run starts, the unique cells,
  and the traces per cell. Traces are then grouped by `np.add.reduceat` in one vectorised pass
  rather than a Python loop over cells or levels.

The accumulation is `cube[:, uniq] += reduceat(resampled[:, order], starts, axis=1)` and
`count[uniq] += n`. Streaming a single window is the same operation restricted to the levels in
that window.

The build accumulates **sums** and divides once at the end, so what `SliceCube` stores is the
mean. Consumers that need the sum again — the fill in §6.4 is the only one — reconstruct it as
`mean × count`. Storing the mean rather than the sum keeps the array directly readable by every
other consumer without a division on each access, and keeps one number per cell rather than two.

**No search box at bin time.** GPRSLICE oversizes the box to avoid empty cells; we bin at the
cell size and fill afterwards (§6.4), which is the same operation applied later and reversibly.

### 6.4 Filling between lines

At 0.5 m line spacing and 0.10 m cells, about 80% of cells are empty. Filling is most of the
picture, not a nicety.

The fill is a **kernel-weighted smear of the (sum, count) pair** — numerator and denominator
convolved with the same radial kernel, then divided, with cells whose weighted count stays below
a threshold left as nodata. That single operation is GPRSLICE's oversized search box, and IDW
with a radius, and a uniform disc; only the kernel differs. Default: a uniform disc of radius
1.5 × line spacing, following the convention.

Implemented by FFT convolution (4.7–7.2 ms on a 300 × 300 slice), with a separable box-cumsum
variant (1.7–1.9 ms) available. The box kernel is square and prints square artefacts, so it is
the fast path and not the default.

Because the fill consumes `mean × count` and `count` rather than replacing either, **the radius
is a slider and the unfilled truth is always still underneath** — which is what the coverage view
shows.

### 6.5 Directional de-striping

The model has always put `axis` on the placement rather than the grid, so one grid can hold
lines running both ways. Generalised here to **per-trace heading**, computed from consecutive
trace coordinates and binned into heading classes (default two, mod 180°). Each class bins into
its own (sum, count); the combination is the mean of the class means, so a cell covered in both
directions weights each equally instead of by trace count.

For grid lines this reduces exactly to the x/y case, so one implementation serves both, and it
extends to arbitrary RTK paths unchanged. Off by default: it is only meaningful where classes
overlap, and with a single direction it is a no-op that costs memory.

### 6.6 Slice extraction

A slice is `mean[k0:k1].mean(axis=0)` reshaped to `(ny, nx)` — or, streaming, the same window
binned directly. Depth labels come from the velocity model.

**Thickness and step are independent, and nothing here assumes slices tile.** Thickness is
`k1 - k0`; step is how far `k0` advances between slices. Discrete abutting slices
(0–5, 5–10, 10–15 ns) are simply the case `step == thickness`; overlapping slices
(0–5, 2.5–7.5, 5–10 ns) are `step < thickness`, and cost nothing extra because both are views
onto the same fine-dz cube.

Overlap is the standard practice and is worth defaulting to, for three reasons:

1. **A reflector on a boundary is halved in both neighbours.** With abutting slices, a feature at
   exactly 5 ns appears weakly in 0–5 and weakly in 5–10 and strongly in neither. With 50%
   overlap there is always a window centred within a quarter-thickness of any depth.
2. **Thickness and step answer different questions.** Thickness is set by physics — at least one
   pulse width, so that variation in the transmitted pulse does not bias the average, and no
   thicker than the smallest expected target. Step is set by how finely the interpreter wants to
   look. Forcing them equal conflates a constraint with a preference.
3. **Stepping through a stack reads better.** A feature emerging and fading across overlapping
   slices is legible; across abutting ones it flickers.

The cost is interpretive rather than computational, and the UI should not hide it: **overlapping
slices are not independent observations.** Three consecutive slices sharing data are not three
confirmations, and a stack stepped at 1 ns with 5 ns windows does not have 1 ns vertical
resolution — resolution is set by thickness, and ultimately by the pulse width. The depth
readout therefore always shows the window's full range rather than its centre, so what is being
averaged stays visible.

GPRSLICE reaches the same place by a different route: its layers tile by construction, but
`box_Zsize` widens the sampling window independently of the layer, so "a horizontal slice between
10 and 20 ns" with `box_Zsize = 20` actually averages 5–25 ns. Our `(thickness, step)` pair is
that decoupling stated directly.

---

## 7. Performance and residency, measured

All figures: the ten real files cycled to the stated line count, the four-step preset
`time_zero → dewow → background_mean → gain_agc`, 30 × 30 m, z 0–50 ns, one core, QGIS not
running. Scripts were throwaway spikes; the numbers are reproduced in the tests as a smoke guard
(§11), not as assertions on absolute timing.

### 7.1 The three tiers

| Tier | Work | Per line | 24 lines | Re-runs when |
|---|---|---|---|---|
| 1 | load + preset + envelope | 13 + 26 ms | **0.93 s** | the preset or transform changes |
| 2 | resample + bin | 1.8 ms | **44 ms** | dz, cell size or z-range moves |
| 3 | z-window, coarsen, fill, colour | — | **< 8 ms** | thickness, radius or stretch moves |

Tier 1 caches in ~28 MB per 24 lines at float32.

### 7.2 dz and cell size interact

They do not add independently. The scatter writes `nz × (cells this line crosses)` values, and a
line crosses twice as many cells when the cell halves, so cost is a **product**, ≈ `nz / cell`
per line. It is *not* `nz / cell²`, the rate the cube itself grows at, because binning only
touches cells a line passes through.

| dz | cell | rebuild, 24 lines | cube |
|---|---|---|---|
| 1.0 ns | 0.10 m | 11 ms | 18 MB |
| 0.5 ns | 0.10 m | 22 ms | 36 MB |
| 0.217 ns (native) | 0.10 m | 44 ms | 83 MB |
| 0.217 ns | 0.05 m | 83 ms | **331 MB** |

Against a separable prediction the finest corner measured **2.0×**. The consequence for the UI:
halving the cell doubles the time and quadruples the cube, so **the guard is a memory readout,
not a timer**. Time never becomes the thing that stops you.

### 7.3 Cube layout

| Layout | rebuild, native/0.10 | rebuild, native/0.05 | extract a slice |
|---|---|---|---|
| `(nz, ncells)` z-major | 44 ms | 83 ms | **0.6 / 3.0 ms** |
| `(ncells, nz)` cell-major | **43 ms** | **71 ms** | 4.5 / 22.4 ms |

Cell-major builds 3–15% faster; z-major extracts 7× faster. Slicing happens on every thickness
and depth tick, a rebuild only when dz or cell size moves. **Z-major**, paying 15% on the rare
operation to make the constant one free.

### 7.4 Residency: the cube never has to be in RAM

If tier 1 is cached, a slice can be binned on demand from only the levels in the window:

| Lines | Cached lines | Resident cube | Streamed, per tick |
|---|---|---|---|
| 24 | 28 MB | 53 ms build, then 0.56 ms | **3.6 ms** |
| 60 | 70 MB | 128 ms build, then 0.70 ms | **8.6 ms** |
| 120 | 140 MB | 248 ms build, then 0.72 ms | **17.2 ms** |

Streaming costs ~0.14 ms per line per tick and drops the cube entirely. Every operation that
looks like it needs a volume streams too: a vertical section bins one row of cells at all levels;
a cross-slice map accumulates a 2-D result slice by slice; a multi-band GeoTIFF is written a band
at a time. **A resident cube is a latency optimisation, never a capability.**

Note the inversion: by 120 lines the cached *lines* (140 MB) cost more than the cube (83 MB).
Cube memory grows with resolution and not with line count; cache memory the reverse. A policy
that only attacks the cube does nothing for a large site.

| Residency | Holds | Per tick | Chosen when |
|---|---|---|---|
| Cube resident | lines + cube | 0.6 ms | both fit the budget |
| **Streaming** (default) | lines only | ~0.14 ms × lines | the cube would not fit |
| On-disk lines | one line at a time | seconds | the line cache would not fit |

The level is chosen from a RAM budget, the line count and the cube size, reported in the UI, and
overridable. **The mode changes latency, never what is adjustable** — only the third tier gives
up live sliders, and it converts them to apply-on-release rather than removing them.

Because streaming is the default, the build dialog **warns and requires confirmation** above the
budget rather than hard-capping: a user with 64 GB should not be blocked by a default, and an
over-budget cube degrades to streaming instead of failing.

**Unmeasured, and flagged as such**: the on-disk tier. Memory-mapping the processed lines is the
intended implementation and is preferable to re-running the preset per tick, but it has no number
yet and needs its own spike before M10 commits to it. All figures above are also without a live
QGIS canvas competing for the CPU; expect streaming ticks to be somewhat worse in practice.

---

## 8. Rendering: unipolar is a new case

`render.py` maps amplitude symmetrically about zero. A slice of `|A|` or `A²` has no negative
side, so the existing path wastes half the colour table and puts the data floor at mid-grey.

Added alongside the existing normalisers, not replacing them:

- `UnipolarClip(percentile)` — `0 → 0`, `limit → 255`, NaN reserved for nodata rather than
  mapped to the middle of the table.
- Unipolar colour tables, and a documented rule that a bipolar table on unipolar data is a
  configuration error rather than a style choice.

The renderer selects between them from the `unipolar` attribute of the last enabled step (§6.2),
so the profile view and the slice renderer agree without either of them guessing.

**Stretch scope** is a separate axis from polarity: shared across the whole cube by default so
depths stay comparable, with a per-slice override for reading a deep, attenuated slice. In
streaming mode the shared limit is one extra full pass at build time, and two numbers to store.

---

## 9. The plugin

GPL side. No signal processing; the AST boundary test applies to everything here.

### 9.1 The build dialog

Grid, preset, transform, cell size, z-range, dz, and a table of the lines that will contribute.
A line carrying its own saved stack is listed and explicitly marked as **using the preset
instead**, because a cube built from mixed recipes has no comparable amplitudes and the user
should see that decision being made rather than discover it later.

A live readout of cube dimensions, memory and the residency level that will result. Build runs
as a `QgsTask` with per-line progress, following `loader.py`'s established pattern and its
recorded traps (task references, exception handling in slots).

### 9.2 The Slices dock

A `QDockWidget` **tabified with the Processing dock** rather than a fourth dock competing for
screen space — a sub-ten-step stack leaves room below it. A separate widget rather than a tab
inside `processing_dock.py`, so it can be torn off to see both at once and because issue #21
already records that file as overloaded.

Contents: the cube and its provenance in one place; slice position, thickness and step; cell size
and fill radius; stretch scope and palette; a coverage toggle; export. Position, thickness, cell
size, radius and dz are **live sliders**, with `shift + scroll` on the canvas cycling depth — the
convention users of other packages already have. Depth is labelled in both ns and m.

### 9.3 The link is already built

M7 §3.2 makes hover ambient via `xyCoordinates` and deliberately does **not** intercept clicks;
§3.4 makes QGIS's ordinary Select tool the promotion gesture. A slice raster changes none of
that: hovering a slice is hovering the map, the existing nearest-line preview fires with the
raster underneath, and selecting a line feature still promotes it.

So the only new thing is **one overlay**: the active slice's time window drawn as a band across
whichever radargram the profile is showing. That is what answers "is this anomaly real, or is the
fill inventing a feature between two lines?" — by pointing at it.

### 9.4 Layers and export

One **multi-band GeoTIFF per cube, a band per slice** — not per z-level — float32 with NaN
nodata, written north-up by resampling out of the grid-local frame once at export. Everyone else
writes a file per slice; one file lets a band slider drive it and keeps the artefact coherent.
Written band by band, so export never requires a resident cube.

**Bands are slices, which is where `step` finally matters.** Exploration in the dock is
continuous: drag the depth slider at a fixed thickness and there is no stepping at all. Export
has to choose discrete bands, so it is the moment the `(thickness, step)` pair becomes a finite
set — `n_bands = (z_range − thickness) / step + 1`. Halving the step doubles the file.

Each band carries its own description recording the window it averages, in both ns and m, so the
overlap is legible from the file itself rather than only from the dialog that made it. A reader
opening the GeoTIFF in five years can see that band 7 is 15.0–20.0 ns and band 8 is 17.5–22.5 ns,
and that they therefore share half their data.

The raw cube is not what is exported: it stays in the `.npz`, which is what a rebuild reads.

The layer joins the site's layer group. Coverage exports as a companion single-band raster when
asked. Existing GeoPackage rules are untouched: rasters live beside it, never inside it.

---

## 10. Site level: many grids, one interpretation

Per-grid cubes are the unit of computation; they are not the unit of interpretation. An anomaly
crossing a grid boundary becomes two rasters, and with independent stretches it shows a visible
step — the classic edge-matching problem.

M12 adds a **site view**: each grid's slice at the same time window, mosaicked under one shared
stretch, with grid-to-grid normalisation as an explicit, inspectable operation. Keeping it
explicit is the point — it is a decision that changes what the map says, and it should be
arguable in print rather than buried inside one large interpolation.

---

## 11. Testing

Unchanged in structure from Plan 2 and Plan 3, which is deliberate:

- **Two tiers.** A pure tier with no QGIS; a `tests/qgis` tier that skips wholesale when the
  bindings are absent. The conftest guards apply: no unhandled modal, and any exception escaping
  a Qt slot fails the test.
- **Real data is the primary validation.** The ten real GSSI files are the reference; synthetic
  fixtures only as far as they mirror them.
- **Properties, not just examples**, for the binner: total count equals the number of contributing
  traces; a cube binned at cell `c` and then coarsened by `f` equals one binned at `c × f`;
  streaming a window equals the corresponding slice of a resident cube, exactly; an empty cell is
  NaN and never 0.
- **The envelope is pinned against its own definition**, not against a padded approximation, so
  the rejected optimisation cannot reappear silently.
- **A smoke benchmark** asserting the tier boundaries hold in the right order of magnitude —
  guarding the shape of §7, never absolute timings, which vary by machine.
- **No new orphans.** Plan 3 §6's rule carries forward: every new signal and public method has a
  caller, checked by grepping for the `connect`.

---

## 12. Out of scope

**Designed for, not built:** elevation-referenced (topographically corrected) cubes; per-(level,
cell) coverage for mixed time ranges; vertical sections cut across lines; cross-slice anomaly
extraction into a single synchronic map, as De Angeli et al. (2022) do for Falerii Novi;
isosurfaces and any 3-D rendering.

**Out entirely:** migration; velocity analysis and the layered-velocity editor; the DZG reader
and `TrackPlacement` (the cube supports arbitrary paths; reading them is separate work);
kriging; horizon-guided slices that follow a picked surface; writing processed radargrams to
disk; instruments other than GPR.

---

## 13. Plans

Three plans of 3–6 tasks, each written when the previous milestone is done, so it reflects what
was built rather than what was predicted.

| | Milestone | Ends with |
|---|---|---|
| M10 | `CubeFrame`, `ZAxis`, `SliceCube`, transform steps, binning and streaming, unipolar render, `.npz` | The core can turn a grid into slices, with no UI |
| M11 | Build dialog, Slices dock, live navigation, coverage, the profile band, multi-band GeoTIFF | An archaeologist can make and read a slice |
| M12 | Site mosaic, grid-to-grid normalisation, directional de-striping, export polish | A site reads as one interpretation |

The on-disk residency spike (§7.4) runs before M10 commits to an implementation.
