# nsgeo slice interpolation — design

Split the Slices panel's one **Fill radius** knob into two separate operations: **interpolation**,
which fills the empty cells between lines using a method chosen from a dropdown, and
**smoothing**, which is optional and set separately along the grid's X and Y axes.

Supersedes the slices spec's §6.4 (`2026-09-18-nsgeo-slices-design.md`, "Filling between lines")
and the site spec's fill-radius call in §4.4 (`2026-10-16-nsgeo-site-view-design.md`). Everything
else in those specs stands. Closes #104.

---

## 1. What this is for

Today one control, **Fill radius**, does two jobs at once. Each cell's value is replaced by the
flat, unweighted mean of every binned cell within a disc of that radius. Cells with nothing
inside their disc stay blank. The user reports two failures from real use:

- **Holes.** Set the radius below half the line spacing and the cells midway between lines see
  neither line, so the slice is striped with nodata. The radius therefore can't be lowered to
  reduce smoothing.
- **Polka dots.** Any strong return becomes a round disc the size of the kernel, so a slice
  "looks like polka dots no matter what". The disc is the same size in every direction, so the
  radius needed to bridge the gap *across* lines (0.5 m apart) also blurs that far *along* each
  line, where traces are a few centimetres apart and the data could resolve much finer detail.

The user's ask, in their words: make smoothing and interpolation explicitly different operations;
pick the interpolation from a dropdown (IDW, kriging, minimum curvature); and adjust the smoothing
separately in x and y.

**Prior art the user named.** RADAN uses kriging by default, as the user understands it. Surfer's
minimum curvature has given good results in demonstrations the user has seen. The user has Surfer
grids of their own data, made with unrecorded settings. These grids are the acceptance check
(§10).

**Success.** At default settings, slices of the user's real grids have no holes between adjacent
lines at their nominal spacing and no disc-shaped artefacts. They are in the same ballpark as the user's Surfer grids.
Scrubbing through depth stays live for IDW and kriging.

---

## 2. Starting state

Read from `origin/main` at `2878db2` on 2026-11-02. Line numbers are from that commit.

| What | Where | State |
|---|---|---|
| The fill | `nsgeo-core/src/nsgeo/slices/fill.py:92` | `fill(values, counts, radius_cells)`: FFT convolution of `(mean×count, count)` with a flat disc, then divide. Cells whose weighted count is below 0.5 stay NaN. numpy only. |
| Stored cube | `nsgeo-core/src/nsgeo/slices/cube.py` | Per-cell mean and count, **unfilled**. Coverage does not vary with level (`cube.py:89`). The fill runs at view time, so it is never stored. |
| Slice extraction | `slices_engine.py:947` `_slice`, `:959` `slice_at` | Either a resident cube or the streaming path (`stream_slice`). Both return `(values, coverage)` for a z-window. |
| Shared stretch | `slices_engine.py:978` `shared_limit(thickness_levels, clip, radius_cells)` | Measured over every window's **filled** slice. |
| Dock control | `ui/slices_dock.py:476` `grid_radius_spin` | Fill radius in × line spacing, with an `= x m` readout. Remembered per grid (`remembered["radius_spacings"]`). Seeded from `DEFAULT_RADIUS_SPACINGS = 0.5` (`slices_plan.py:253`). |
| Radius in cells | `ui/slices_dock.py:2048` `radius_cells()` | Uses `cell_spin.value()`, not the engine's applied frame cell. This is bug #104. |
| Site scope | `site_engine.py:892` | `a * fill(values, cov, radius_cells_for(spacing, radius_spacings, res.cell)) + b`, one grid at a time, in each grid's own frame. The control is `radius_spacing_spin` (`slices_dock.py:502`). |
| Saved cube view | `slice_export.py:506` `ViewSettings` | Carries `radius_m`. Not part of the cube's identity (`cube_record`'s split). |
| Export metadata | `slice_export.py:301`, `site_export.py:238` | `NSGEO_FILL_RADIUS_CELLS` and `NSGEO_SITE_FILL_RADIUS_SPACINGS`. |
| Rotated-export warning | `plugin.py:994` | At radius 0, warns that cells dropped by the north-up resample are not recoverable. |
| Square cells | `nsgeo-core/src/nsgeo/slices/frame.py:10–13` | Docstring: rectangular cells rejected because "the fill radius already covers the real need". |
| User guide | `docs/guide/getting-started.md:383` | Describes Fill radius. |
| Dependency rule | `nsgeo-core/tests/test_boundary.py` | Core is numpy-only. scipy is allowed only as a function-level optional accelerator with a numpy fallback that agrees within tolerance (`2026-09-10-nsgeo-gpr-qgis-design.md` §Dependencies). |

---

## 3. Decisions taken in brainstorming

**The user's decisions:**

1. Interpolation and smoothing are separate operations with separate controls.
2. Interpolation is chosen from a dropdown. The methods are **IDW, kriging and minimum
   curvature**.
3. Smoothing is set separately in **X and Y**, meaning the grid's (the cube frame's) own local
   axes, not map east and north.
4. Smoothing is **off by default**.
5. There is a **maximum distance**. Interpolation fills the gaps between neighbouring lines but
   does not invent values far from any data: beyond the survey edge, across a skipped line, or
   around an obstacle.
6. The same settings apply everywhere slices appear: the single-grid view, site scope, GeoTIFF
   export and saved cubes.
7. **Method settings use defaults only** for now: no variogram, tension or power controls. They
   can be exposed later if needed.
8. **The core stays numpy-only.** The existing rule (optional scipy accelerator with a numpy
   fallback) still applies, but nothing new is required.
9. **A wait is acceptable when the interpolation is set up**, as long as viewing slices
   afterwards is quick.
10. **Acceptance is a ballpark visual comparison** against the user's Surfer-gridded data (§10).
11. **This goes ahead of M15 (cut anywhere).** M15's approved design is revised afterwards onto
    these settings (§12).
12. **Max distance to data defaults to 0.75 × line spacing** (user, 2026-11-03; reverses 0.5
    after binning quantisation striped nominal gaps) (§5.2).

**Design calls made in this document** (the user hasn't seen these; each is marked *design call*
where it appears):

- The default method is **kriging**.
- A **None (binned only)** method is kept in the dropdown. It replaces today's "radius 0".
- **Fill radius is removed.** There is no "disc" option in the dropdown.
- Interpolation **never changes a cell that has data**. Only smoothing does.
- Smoothing is a Gaussian, and its X and Y values are standard deviations in metres.
- IDW and kriging are split into a one-time weight computation plus a cheap per-slice apply.
  Minimum curvature is solved per slice.
- The single-grid preview and export adopt the site's half-pitch lattice rule on rotated grids,
  so no data cell is dropped (§8).
- Survey and cube files stay readable both ways between 0.2.0 and this build. Old fill settings
  are ignored, not translated (§8).
- The work is delivered as two milestones: A covers everything except minimum curvature, B adds
  minimum curvature (§12).

---

## 4. The pipeline

Per displayed or exported slice, one grid at a time, in that grid's own frame:

```
cube / stream ──▶ z-window mean + coverage           (unchanged)
              ──▶ interpolate (method)                 fills empty cells; data cells untouched
              ──▶ blank beyond max distance            NaN where no data cell is near enough
              ──▶ smooth (σx, σy)                      optional; never fills a blank
              ──▶ site gain a·v + b (site scope only)  (unchanged)
              ──▶ stretch / palette / lattice / export (unchanged)
```

**The binned truth stays underneath** exactly as before. The cube stores means and counts.
Interpolation and smoothing are view settings, recorded in `ViewSettings`, and stay out of the
cube's identity. **Show coverage** is unchanged.

**Interpolation input.** Each cell with `count > 0` is one datum at its cell centre, valued at its
window mean. Counts are not used as weights (*design call*). The binned mean already averages a
busy cell's traces, and weighting by count would make densely sampled along-line cells dominate
even more.

**Data cells are exact** (*design call*). After interpolation, every cell with data holds exactly
its binned value. IDW and kriging are exact interpolators at their data points. Minimum curvature
is solved with data cells held fixed (§5.4). Only smoothing (§6) changes a data cell.

**Gains commute.** The site-scope gain `a·v + b` is applied after interpolation and smoothing, as
it is applied after the fill today (site spec §4.6). That ordering is correct only if every
method satisfies `f(a·x + b) = a·f(x) + b` for the same coverage. IDW (weights sum to 1),
ordinary kriging (weights sum to 1), minimum curvature (linear, and reproduces constants) and
normalised smoothing all satisfy it. The tests must assert it for every method (§9).

---

## 5. Interpolation

### 5.1 The dropdown

| Entry | What it does | Default settings (fixed this round) |
|---|---|---|
| None (binned only) | No interpolation. Empty cells stay blank. Equivalent to today's radius 0. | — |
| Inverse distance (IDW) | Weighted mean of neighbours, weight = 1/d². | Power 2. |
| Kriging | Ordinary point kriging at cell centres. | Linear variogram, no nugget, isotropic. |
| Minimum curvature | Smoothest surface through the data cells (Briggs-type biharmonic solve). | Tension 0. |

The default is **Kriging** (*design call*). It is the user's understanding of RADAN's default, and
it is also Surfer's default.

**Kriging needs no variogram fitting at these defaults.** With a linear variogram γ(h) = s·h and
no nugget, the ordinary-kriging weights do not depend on the slope s; only the kriging variance
does. "Defaults only" therefore means no fitted parameters at all, and the weights depend only on
where the data cells are.

### 5.2 Max distance to data

A cell is filled only if the nearest data cell's centre is within this distance of its own
centre. Otherwise it is NaN. This applies to all three methods, and it is the only place a hole
can appear. It is the replacement for today's radius as the "how far to trust" control.

- **Default 0.75 × line spacing** (the user's decision of 2026-11-03, reversing 0.5). Binning
  puts each datum at its cell centre, up to half a cell from its line, so two lines a spacing `s`
  apart become data rows `floor(s / c)` or `ceil(s / c)` cells apart at cell `c`. Where that is
  even, the middle cell is `ceil(s / c) · c / 2` from both, more than 0.5 × `s`: at 0.5 × spacing,
  straight lines at their nominal offsets striped (20 of 26 gaps for 0.75 m lines at a 0.2 m
  cell, 13 of 39 for 0.5 m lines at 0.15 m). That middle cell is at most `(s + c) / 2` from data,
  which is ≤ 0.75 × `s` whenever the cell is at most half the spacing, so 0.75 closes every
  nominal gap with room for a line that wanders a little. A skipped line still shows: its gap is
  2 × spacing, and at 0.5 m lines and a 0.2 m cell the stripe's nearest cells are 0.4 m from
  data, beyond 0.375 m.
- **Compared in metres and inclusively** (distance ≤ max distance, with a small tolerance, e.g.
  1e-9 m). The distance is never rounded to whole cells. A cell exactly on the limit fills: at
  0.5 × spacing the midpoint of an aligned gap sits on it, and a rounding or strict comparison
  would turn that gap into a stripe. Tested for both odd and even numbers of cells between lines.
- Expressed in **× line spacing with an `= x m` readout** and remembered per grid, exactly as
  `grid_radius_spin` is today. Site scope uses each grid's own spacing.
- Cell-centre distances come from the **engine's applied frame cell**, never
  `cell_spin.value()`. This fixes #104 by construction.
- Disabled when the method is None.

### 5.3 The neighbourhood (IDW and kriging)

**The search neighbourhood is not the max distance.** If a cell next to line A only looked as far
as the max distance, it would not see line B. Its estimate would come from one side, and where
line B enters the search the result would jump. Hard search cut-offs are a classic source of
stripes and seams in kriged maps.

Along-line sampling is far denser than across-line, so the k nearest data cells to any point
between lines will often all lie on the nearest line. A plain nearest-k search therefore
extrapolates from one line instead of interpolating between two.

Constraints on the builder's neighbourhood:

1. Every filled cell lying between two adjacent lines draws data from **both** lines.
2. No visible discontinuity from neighbourhood switching. Adjacent filled cells on a smooth input
   field must not differ by more than the field itself varies (tested, §9).
3. The search reaches far enough to satisfy (1) when one line is missing and max distance has
   been raised to bridge the gap.

A sector search (quadrant or octant, the nearest few data cells per sector, out to a search
radius of about 2 × line spacing) is the conventional answer and the suggested starting point.
Sector count, k per sector and the search radius are the **builder's call** within those
constraints, and the chosen values are recorded in code comments with the evidence.

Data lie on the cell lattice, so the neighbour search is a lookup over nearby cell offsets. No
KD-tree or scipy is needed.

### 5.4 Minimum curvature

Solve the biharmonic (minimum-curvature) equation over the whole frame on the cell lattice, with
data cells fixed at their values, tension 0, and natural (zero-curvature) conditions at the frame
edge. Then blank beyond the max distance. The iterative scheme (e.g. red–black relaxation with a
coarse-to-fine start, as in Smith & Wessel 1990) and its convergence tolerance are the **builder's
call**. The chosen tolerance is recorded and tested against a reference case (§9).

**Known behaviour:** at tension 0, minimum curvature overshoots near sharp changes, so a strong
return can produce a faint ring of opposite sign between lines. This is the standard
characteristic of the method and is accepted for this round. Exposing tension is the first
setting to add if the walkthrough shows it matters.

---

## 6. Smoothing

- **Gaussian, separable**, with independent standard deviations **σX and σY in metres** along
  the frame's local X and Y axes (*design call*: σ rather than a full width, stated in the
  tooltip).
- **Default 0 in both** (off). Each axis is independent: σY = 0 with σX > 0 smooths along X only.
- **Normalised over valid cells.** Smooth `value × mask` and `mask` and divide, so a blank cell
  never pulls its neighbours toward zero and edges don't darken. **Smoothing never fills a blank
  cell.** Blanks are decided by §5.2 only.
- In **metres, not × line spacing.** Smoothing is about the size of the features being kept, not
  the acquisition geometry. In site scope each grid is smoothed in its own frame's axes with the
  same σ values.
- Remembered per grid, like max distance.
- numpy only. FFT or direct 1-D convolution is the **builder's call**; `fill.py`'s
  `_smooth_size` padding helper may be reused.

Cells stay square. Update `frame.py:10–13` to say that directional smoothing now covers the real
need for X/Y difference, so the old reference to "the fill radius" goes.

---

## 7. Responsiveness

**IDW and kriging: weights once, apply per slice.** Their weights depend only on where the data
cells are, and coverage does not vary with level. So compute, once per (frame, populated-cell
mask, method, max distance), a sparse table of `(target cell, source cells, weights)`. Each slice
is then a gather and weighted sum. **Key the cache on the populated mask itself**, not on an
assumption that coverage is level-independent. If per-level coverage ever arrives (slices spec
§12's deferred "mixed time ranges"), the cache misses correctly rather than being silently wrong.

- **Setup** may take seconds on a large grid. It must not freeze QGIS: run it off the GUI thread
  using the existing task pattern, or keep it short enough to be imperceptible. Show a busy
  state, and cancel or restart it when the cell size, method, max distance or line set changes.
  The approach is the **builder's call**. Measure and record setup time on the real grid and on
  the site spec §4.8's 50 m synthetic grid at the default cell.
- **Per slice:** a depth, thickness or step change with IDW or kriging must not be slower than
  today's fill at the same grid and cell size. Record before and after numbers.
- **Memory:** the weights table counts toward the engine's memory estimate (`MemoryEstimate`),
  so a very fine cell on a large grid is warned about, not discovered as a crash.

**Minimum curvature: solved per slice.** It has no reusable weights. Measure the solve on the real
grid and the 50 m synthetic, and record the numbers. While a slider is being dragged the panel
must not freeze. The slice shown when the drag stops must be the full minimum-curvature result
(the same rule as site spec §4.8). How to bridge the drag (a lagging last result, a cheaper
preview, a warm start from the previous slice) is the **builder's call**, recorded with the
measurements.

**Shared stretch.** `shared_limit` is measured over every window's final slice (interpolated and
smoothed), as it is measured over filled slices today. That is cheap for IDW and kriging. For
minimum curvature it means solving every window, so the builder may compute it in the background
and use the current slice's stretch until it is ready. Whatever is chosen is recorded, and the
final limit must come from minimum-curvature slices, not another method's.

**Export** of a multi-band GeoTIFF runs every band through the full pipeline, with progress and
cancel through the existing export path. Minimum curvature makes this slower. That is acceptable.

---

## 8. The plugin

**Dock.** A new **Interpolation** group sits between Resolution and Display. Fill radius leaves the
Resolution group.

| Control | Kind | Notes |
|---|---|---|
| Method | combo | None (binned only) / Inverse distance (IDW) / Kriging / Minimum curvature. Default Kriging. |
| Max distance to data | spin, × line spacing, `= x m` readout | Default 0.75 (§5.2). Disabled for None. Site scope: the per-grid metres go in the tooltip, as `site_scope.radius_tooltip` does today. |
| Smoothing X | spin, metres | Default 0. |
| Smoothing Y | spin, metres | Default 0. |

Each control gets a tooltip in the style of the existing ones, saying what it does in plain
language. All four are remembered per grid, like `radius_spacings` today, and re-seeded from the
defaults by the same path. Single-grid and site scope share these controls. Today's
`grid_radius_spin`/`radius_spacing_spin` pair collapses into one max-distance control, because
both are already in × line spacing.

**Saved settings, both directions** (*design call*: no `SCHEMA_VERSION` bump, and 0.2.0 must
still open what this build saves). Two places hold fill settings today:

- **Saved cube records.** `ViewSettings` gains `method`, `max_distance_spacings`, `smooth_x_m`
  and `smooth_y_m`. `from_dict` must still read a record written by 0.2.0. A record with
  `radius_m` and none of the new keys loads with the new defaults, and its old `radius_m` is
  ignored, because there is no faithful mapping from a disc radius to a method. Going the other
  way, 0.2.0's `from_dict` raises if `radius_m` is missing, so this build **keeps writing
  `radius_m`**, set to the max distance in metres. That is a sensible disc radius for 0.2.0 to
  show. Under None it is 0, so 0.2.0 shows that cube unfilled, as this build does (final review
  of milestone A).
- **Remembered per-grid and site resolutions** (`slice_sources[g].resolution`,
  `site_view.resolution`, cleaned by `project.py:235` `_clean_resolution` against
  `_RESOLUTION_KEYS`). The new numeric keys join `_RESOLUTION_KEYS`. The method is a string, so
  it needs its own tolerant cleaner: a known method name is kept, and anything else reads as
  unset. An old remembered `radius_spacings` is **ignored, not mapped onto max distance**.
  Mapping 0.2.0's seeded 0.5 would bring back the holes this work removes. 0.2.0's cleaner
  already drops keys it doesn't know, so files saved by this build open in 0.2.0, which seeds
  its own radius default.

**Exports.** `NSGEO_FILL_RADIUS_CELLS` is replaced by `NSGEO_INTERPOLATION` (method),
`NSGEO_MAX_DISTANCE_M`, `NSGEO_SMOOTH_X_M` and `NSGEO_SMOOTH_Y_M`. The site export's
`NSGEO_SITE_FILL_RADIUS_SPACINGS` is replaced by `NSGEO_SITE_INTERPOLATION`,
`NSGEO_SITE_MAX_DISTANCE_SPACINGS`, `NSGEO_SITE_SMOOTH_X_M` and `NSGEO_SITE_SMOOTH_Y_M`.

**The north-up resample stops dropping cells** (*design call*). Ruling AE accepted that the
single-grid north-up resample (`to_north_up`, pixel = cell) drops 15–18% of a rotated frame's
cells, because the disc fill spread every cell into its neighbours first. That premise no
longer holds. Interpolation never touches a data cell and smoothing is off by default, so a
dropped data cell would simply be lost from the preview and the export. The user's real grids
are rotated (Grid 1 at 10.497°). The single-grid preview and export therefore adopt the site
lattice's existing rule, Ruling 2 (`slices/site.py:136` `lattice_pixel`): pitch = cell, or
cell / 2 when the frame is rotated. At half pitch every rotated cell contains a pixel centre.
The radius-0 warning at `plugin.py:994` is removed rather than moved, because there is nothing
left to warn about. A rotated single-grid export has four times the pixels it had in 0.2.0,
which is the same cost site exports already pay.

**Site scope.** Each grid is interpolated with its own weights in its own frame, then blanked
with its own spacing × the shared multiple, then smoothed. Seam statistics stay measured on
binned (`count > 0`) cells before interpolation, unchanged.

**Guide.** Rewrite `docs/guide/getting-started.md` step 3, and add a short paragraph on what the
three methods do and when to pick each. The guide is written for archaeologists, not
geophysicists.

**Retiring the disc fill.** `fill()` and `disc_kernel()` leave the slice path. Whether
`fill.py` is deleted or kept for its helpers is the **builder's call**. No dead public API should
remain in `nsgeo.slices`. One unmerged branch, `nsgeo-m14`, has a test that imports `fill` from
`nsgeo.slices`. Whichever of the two merges second updates that test.

---

## 9. Testing

Core tests are pure numpy. The real-data tests use the grids under
`nsgeo-core/tests/data/local` and skip when they are absent, as `test_real_files.py` does.
Synthetic inputs mirror the real geometry: lines at 0.5 m spacing, traces a few centimetres
apart, the default cell.

**Every method (IDW, kriging, minimum curvature):**

- Data cells come back exactly unchanged (minimum curvature: within its recorded tolerance).
- A constant field is reproduced exactly.
- Affine equivariance: `f(a·x + b) == a·f(x) + b` for the same coverage.
- Cells beyond the max distance are NaN, and cells within it are finite.
- An all-blank input gives an all-blank output, and a single data cell does not crash.
- No holes between adjacent lines at nominal spacing at the default max distance. A line offset
  by 0.1 × spacing leaves a stripe at 0.5 that closes at 0.6. A skipped line leaves a blank
  stripe.
- No neighbourhood discontinuity (§5.3): on a smooth synthetic field sampled on line geometry, the
  largest step between adjacent filled cells is bounded by the field's own gradient × cell size,
  plus a tolerance.

**Method-specific:**

- Kriging weights sum to 1, and the result is independent of the variogram slope.
- IDW at a point equidistant from two data cells gives their mean.
- Minimum curvature reproduces a plane exactly (within tolerance), and matches a small reference
  case solved by direct dense linear algebra.

**Weights cache:** the precomputed apply equals the direct computation. A changed populated mask
misses the cache, and an unchanged one hits it.

**Smoothing:** σ = 0 is the identity. σX alone spreads a single spike only along X. Blanks stay
blank. An edge cell next to a blank is not pulled toward zero.

**Plugin:** the dock controls and per-grid memory; a `ViewSettings` round trip, including a 0.2.0
record carrying only `radius_m`, and a record from this build read by 0.2.0's `from_dict` (a
copy of that function as a fixture); remembered resolutions that carry an old `radius_spacings`
or a damaged method name; a rotated single-grid export at half pitch keeping every data cell;
the export metadata keys; site gains commuting with every
method; #104's scenario (refuse a Resolution after a cell edit, export, and check that the
recorded max distance matches the frame's cell); the numpy-only boundary test still passing.

**Real data:** run every method on the local grids. Assert that data cells are unchanged.
Record, rather than assert, any blank stripes at the default max distance, because real lines
wander. Record the timings from §7.

---

## 10. Manual checkpoints

These are human gates. They are tracked and reported, never passed silently.

1. **Walkthrough on the deployed plugin** (ns-geo profile, per the usual build-and-walkthrough
   rule), on the user's real grids:
   - at defaults, no polka dots and no holes between lines at their nominal spacing. Any stripe
     from a wandering line closes when max distance is raised a little;
   - a skipped line or obstacle shows as blank;
   - Smoothing X and Y each act along the expected grid axis;
   - depth scrubbing is live with IDW and kriging;
   - minimum curvature (milestone B) is usable while dragging and correct when the drag stops;
   - site scope, saved cubes and GeoTIFF export carry the settings.
2. **Ballpark against Surfer.** The user supplies Surfer-gridded versions of one or more of their
   grids, settings unknown. The comparison is visual and done by the user, with nsgeo set to the
   matching method (kriging or minimum curvature) at defaults. The question is "same ballpark",
   not pixel agreement.

---

## 11. Out of scope

- Exposing method parameters (variogram model, nugget, range, anisotropy; IDW power; tension).
  These are the first follow-up if the walkthrough or the Surfer comparison calls for them.
- Variogram fitting.
- Other methods (natural neighbour, triangulation, splines, nearest neighbour, moving average).
- Interpolating across depth (3-D); each slice is interpolated on its own.
- Using counts as data weights or measurement error.
- Rectangular cells, de-striping, and changes to binning. The north-up resample changes only as
  §8 says: the single-grid pitch adopts the site's Ruling 2.
- Any new dependency.

---

## 12. Milestones

Two milestones, each planned as 3–6 tasks.

**A — Interpolation split.** None, IDW and kriging (with the weights cache and the neighbourhood
constraints), max distance, Smoothing X/Y, the dock group and per-grid memory, site scope, saved
cubes, export metadata, #104, the guide, and retiring the disc fill. Walkthrough (§10.1, minus
the minimum-curvature item), then merge.

**B — Minimum curvature.** The solver, its per-slice responsiveness and shared-stretch handling,
export, and the guide's paragraph. Walkthrough plus the Surfer comparison (§10.2), then merge.

The Surfer comparison waits for B because it is only meaningful once both methods the user
named are present. Kriging can be eyeballed against the Surfer grids during A's walkthrough if the
user wants an early read.

**Relationship to M15 (cut anywhere).** The user's call: this work goes first. M15's approved
design (`2026-10-30-nsgeo-cut-anywhere-design.md` on `nsgeo-m15-cut-anywhere`) is revised
afterwards. Its sections, its cut-pick provenance (`stack_json`) and its site-scope reads are
currently written against the fill radius. No cut pick has been saved yet, so there is no legacy
format to carry. Two things milestone A owes that revision:

- **An API a cut can use.** Applying the IDW or kriging weights to any single level, and to
  only the cells under a cut, must be possible without filling a whole slice. Every method is
  linear, so per-level interpolation then window-averaging agrees with the slice view.
- **Minimum curvature on cuts is left to the M15 revision.** It has no reusable weights, so a
  section through every level costs a full-frame solve per level. M15 decides between leaving
  it off cuts, solving lazily, or accepting the cost.
