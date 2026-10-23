# nsgeo site view (Plan 4, M12) — design, with de-striping designed for later

M10 gave the core a slice cube and M11 put one grid's slices on the map. This phase is the last
row of the slices spec's milestone table — *"a site reads as one interpretation"* — and it
replaces that spec's §6.5 (directional de-striping) and §10 (site level) with what was decided in
brainstorming on 2026-10-15/16. Where this document and the slices spec disagree, this one wins
and the difference is stated.

| | Scope | Ends with |
|---|---|---|
| **M12** | The site view: a *Whole site* scope in the Slices dock, grid-to-grid normalisation, one site GeoTIFF that records what was done | Every grid's slice moves under one slider, on one scale, and exports as one file |
| *Later, unscheduled* | De-striping (§6): stagger correction and direction balancing | Zigzag stagger is gone from map, profile and slices alike |

**De-striping is not part of M12.** It was brainstormed alongside the site view and briefly
planned as a second plan, M12b; the user then moved it out entirely — it does not need the site
view, and the site view does not need it. Stagger reaches beyond slices into the map, the
profile, picks and line editing (issue #29), so it belongs with that work. §6 keeps what was
decided so it is not re-brainstormed from nothing; it is a design, not a commitment, and is
re-checked against the code when it is scheduled.

---

## 1. What this is for

The user's account of doing this today, before nsgeo:

> "I produced geotiffs with another software and then georeferenced those geotiffs into QGIS.
> The process was clunky and annoying. It was also hard to keep the grids looking like they were
> on the same scale. If I merged them into a single geotiff they had contrast issues because they
> were differently scaled, if I kept them individual I had to change each one individually when I
> wanted to look at different depths."

Three distinct pains, each with its own answer here:

1. **Georeferencing by hand.** Already gone: nsgeo knows where every grid is.
2. **Changing each grid individually to look at another depth.** One slider moves every grid.
3. **Grids not on the same scale.** Asked where the mismatch came from — the export stretching
   each file independently, or the grids genuinely differing (different days, ground
   conditions, gain settings) — the user said **both are possibilities**. So the site view
   needs both a shared stretch (which removes the first cause by construction) and
   normalisation (which addresses the second, explicitly).

How the user fixed (3) before: *"I'd adjust the color ramp until I got it so it looked 'as good
as I could make it'"* — and they asked for the standard, less arbitrary approaches, which §5
surveys. Their eye remains the final judge: they rejected a table of factors as something the
user would not use (*"The user can see if the result looks the way they want and choose a
different method/modify it if it doesn't"*), and asked for a manual adjustment.

**Success** is that a multi-grid site is explored with one control, looks like one survey when
the data allows it, is corrected in ways the user chose and can reverse, and exports as one
GeoTIFF that says what was done to it.

---

## 2. Decisions

Whose each decision is matters, so it is recorded. **User** means the user said it.
**Design call** means it was decided here, stated to the user during brainstorming, and not
objected to — it is open to correction.

| | Decision | Whose | Why |
|---|---|---|---|
| Panel | A **This grid / Whole site** scope switch at the top of the Slices dock | User (chose option A of three mockups) | One depth slider cannot disagree with itself; a separate Site dock would have two |
| Depth | The **existing Position slider**, whose readout shows the window in both ns and m | User | "the current slider in the panel does both, we can just keep that approach" — said when the user, asked whether they think in cm or ns, answered "usually centimeters, but if we don't have reliable rdp then we need to be able to do it in nanoseconds" |
| Depth across grids | **Grids line up by time.** The shared window is the same ns window in every grid; the readout lists each grid's depth range. Lining up by depth waits until after M13 | User (took the recommendation) | "I often have had one velocity per grid, but you're right M13 will be what opens up those possibilities in a real way" |
| Site layouts | Under 10 grids, usually laid at one bearing and at right angles — **but nothing may rely on that** | User | "sometimes I'm working with data someone else collected, and I'm interested in arbitrary lines with GPS recording as a potential future expansion" |
| Per-grid view | *This grid* stays exactly as M11 shipped it | User | |
| Presets | **Each grid has its own preset** | User | "Each grid probably needs their own preset" |
| Transform | **One transform for the whole site** | Design call | Envelope and squared amplitude are different units; a site mixing them cannot be normalised meaningfully |
| Stretch | **Shared across every included grid** by default | User (agreed) | Removes the per-file-stretch cause of mismatch by construction |
| Normalisation methods | **None** (default), **Background level**, **Edge match**, **Histogram match** | User picked these three of five | §5 |
| Normalisation default | **None** | Design call | It changes what the map says; it is always an act |
| Factors table | **None** | User | "I'm not sure how a table of adjustment factors is useful to them" |
| Manual adjustment | A **per-grid brightness multiplier** on top of the method | User | |
| Data on disk | **Never changed** by normalisation; applied when a slice is drawn or exported | Design call | Slices are derived (slices spec §1) |
| Site export | **One GeoTIFF covering every included grid**, a band per slice; per-grid files still come from *This grid* | User | "If we need individual grids we can do that from the individual grid part of the panel" |
| Provenance | The GeoTIFF **records the method and every grid's factors for every band** | User ("brilliant") | |
| Stagger | A **grid-wide shift to start, then line by line** | User | "I like to be able to control things line by line. but a global adjustment to start with might be good" |
| Stagger scope | Applies **everywhere a trace is positioned** — map, profile, slices, picks | Design call | It corrects *where* traces are; views that disagreed would be worse than none |
| Stagger storage | **Separate from the line's recorded start position** | Design call | The survey file keeps the field measurement and the correction apart |
| Direction balancing | **In**, for **any number of directions** | User | "I didn't mean to restrict it to two directions" |
| Per-line brightness matching | **Out, including from the later de-striping work** | Design call from the user's "brightness stripes are actually less of a common concern" | It also erases real features parallel to the lines (§5) |
| Real-data validation | Automated tests use the ten local lines, **split and perturbed** (§9); the acceptance walkthrough uses the **user's own multi-grid data, privately** | User | They have suitable data but cannot expose it to the repo |

---

## 3. Starting state

Checked against `main` at `19bf90b` (M11 merged), not assumed.

**One grid at a time, throughout.** `SliceEngine` (`nsgeo_qgis/slices_engine.py`) owns one
`SourceChoice` — one grid, one preset, one transform, one included-line set — prepares that
grid's lines in a `QgsTask`, and produces one slice per tick via `slice_at(window)`.
`SliceLayer` (`slice_layer.py`) is a single scratch float GeoTIFF named *Slice (live preview)*,
rewritten in place and `reloadData()`-ed every tick. The export (`slice_export.py`,
`GeoTiffSliceWriter`) writes one cube's bands through `to_north_up(values, frame)`, whose output
geotransform is anchored at **that frame's own bounding box** — so two grids exported separately
land on two pixel lattices that do not line up.

**Grids are frames, not containers.** `Grid` (`nsgeo/geometry/grid.py`) is
`id, origin, azimuth, size_x, size_y, crs, default_spacing, velocity`. Each grid has its own
optional velocity, which is why the same time window is a different depth in each grid. Nothing
in the model says which grids are neighbours; adjacency has to be computed from footprints.

**Lines already know their direction.** `GridPlacement` (`geometry/placement.py`) carries
`axis`, `offset`, `start_along` and `direction ∈ {+1, −1}`; the import dialog defaults to an
alternating zigzag. Trace positions are `start_along + direction · i / traces_per_metre`. There
is no stagger correction anywhere.

**What a grid remembers.** The survey JSON's `cubes` dict records a full recipe (grid, preset,
transform, lines, resolution, `ViewSettings`) — but only for a **saved** cube. A grid that has
been looked at but not saved remembers nothing, not even within a session: switching the Grid
combo resets the included lines and re-seeds the defaults (`SlicesDock._sync_included`). The
plugin has no settings infrastructure at all; its one `QSettings` key is
`nsgeo/slicesDockTabified`.

**The slider moves in time only.** Its range is the cube's z-levels; `current_window()` turns
the value into `top_ns` and calls `ZAxis.level_range`. Metres appear only in the readout, through
the velocity resolved for the first prepared line. There is **no depth → time conversion
anywhere** — `VelocityModel.depth_at` has no inverse.

**One preparation task at a time.** M11 found that two concurrent preparation tasks segfault;
`SliceEngine.set_source` cancels and waits for any in-flight task first. A site therefore
prepares its grids in sequence.

**Grids may differ in CRS.** Each `Grid` carries its own; the GeoPackage uses `grids[0].crs` and
reprojects the others (`layers.py`).

**The M11 GeoTIFF carries almost no provenance**: dataset metadata is only
`NSGEO_FILL_RADIUS_CELLS` and `NSGEO_FRAME_AZIMUTH_DEG`, plus a window label per band. What §4.7
asks the site export to record is new work, not an extension.

**Picks are positioned once.** A pick's map point is computed from its line and trace when it is
written and never recomputed — deliberately, because users may move picks by hand. Its stored
`distance_m` is likewise fixed. This matters to stagger (§6.1).

**The cost that dominates a tick is the fill**, not the bin: M10 measured 53 ms at 600 × 600
cells (radius 10) and 327 ms at ~1020 × 1020. A site fills once per grid per tick.

**Residency is automatic above 114 lines** (`choose_residency`: streaming while
`n_lines × 0.14 ms ≤ 16 ms`, else resident up to 1.5 GB). A site crosses that line quickly.
*M12 changed this to a per-trace estimate (ruling T3-c): see `slices_plan.choose_residency`.*

---

## 4. The site view (M12)

### 4.1 The scope switch

A two-way switch, **This grid | Whole site**, at the top of the Slices dock. *This grid* is the
M11 dock with no behavioural change. *Whole site* keeps the same Position, Resolution and Display
groups — the same widgets, not copies — but they now drive every included grid; Source becomes a
grid list; a Normalisation group appears; the export button becomes **Export site GeoTIFF…**.

Switching scope keeps the slider's window (and thickness), so dropping to one grid to inspect it
shows the same window. The mockup the user chose is `.lavish/m12-site-panel.html` (option A,
untracked); its layout is a guide, not a contract.

### 4.2 Source in site scope

- A **grid list**: one row per grid in the site, each with an include checkbox, the grid's name,
  **its preset**, its included-line count (`24 / 26`) and its preparation state
  (ready / preparing n of m / no lines). Selecting a row is how a grid is chosen for the
  per-grid actions below.
- **One transform combo** for the site.
- **Choose lines for ⟨grid⟩…** opens M11's line chooser for the selected row.
- A grid's preset is set in *This grid* scope, as today. *Design call, unconfirmed:* the site
  list shows the preset but does not edit it. The builder may put a combo in the row instead if
  it fits; either is acceptable.

**Every grid remembers its slice source** — preset and included lines — in the survey JSON,
whether or not a cube was ever saved, and *This grid* scope reads and writes the same record.
This is new persistent state; it must load tolerantly (a survey file without it is valid) and it
must not disturb the `cubes` record format.

Preparation is per grid and costs what M11 measured (~0.9 s per 24 lines). Grids prepare **one
at a time, in a queue** — never concurrently (§3: concurrent preparation segfaulted in M11) —
with per-grid progress in the list, and the site view draws each grid as soon as it is ready
rather than waiting for all of them. The status line reports the total held in memory across
grids.

### 4.3 Position across grids

The slider, readout and thickness work as in M11, over the site. **The slider spans the union of
the grids' time ranges**; a grid whose range does not cover the current window is drawn as nodata
for that slice, and the readout names it. *Design call:* the intersection would hide data the
user has; a blank grid that is named is honest.

**Grids line up by time** (user decision). The shared window is the same time window in every
grid — today's slider, unchanged — and the readout gains a quieter line listing each grid's depth
range through that grid's own velocity (`A 0.60–0.80 m · B 0.52–0.70 m · D 0.66–0.88 m`). The
user often has one velocity per grid, so these will differ, and the reader should see that they
do. Each grid's velocity is resolved as M11 resolves it for its readout.

**Lining up by depth is deferred until after M13**, whose velocity fitting is what will give each
grid a velocity worth trusting. Recorded so it is not rediscovered: it is a mode, not a readout.
Velocity is per line (`resolve_velocity`: line override, then grid, then header dielectric), so
"same depth" must either ignore per-line overrides or bin a different time range per line;
nothing records whether a velocity is trustworthy, so it would be a switch the user flips;
thickness and step become metres, so each grid's level count differs and the stretch pass and
the export's band planning (`plan_windows`) are rebuilt around depth windows; and `VelocityModel`
allows layers, so the depth → time inverse is piecewise. **M12 puts the window mapping behind one
function**, so time-only now does not block depth later.

### 4.4 Resolution in site scope

**One cell size for the site.** Each grid keeps its own grid-local frame and cube (slices spec
§3: a cell column must draw from a consistent set of traces), but they all use the site's cell
size so the mosaic is on one scale. *Design call:* it is seeded by M11's rule applied to the
**finest-spaced** grid, so no grid is under-resolved.

**The fill radius is a multiple of each grid's own line spacing** in site scope (*design call*),
defaulting to M11's 1.5 ×. The user sometimes works with other people's data, so grids in one
site can differ in spacing, and one radius in metres would over-smooth the fine grid or leave
stripes in the coarse one. With equal spacings it is exactly M11's behaviour. The control's
tooltip or readout gives the resulting metres per grid.

dz and the z-range follow the same union rule as §4.3. M11's step-size fixes (useful
`singleStep`, the cell-size floor that stops `0.001 m` crashing QGIS) apply unchanged.

### 4.5 Display in site scope

- **Stretch: shared across the site.** The Stretch combo's M11 options, *shared across the
  cube* and *this slice*, become *shared across the site* and *this slice* in site scope. The
  limit is measured over every included grid's **filled** windows (as `SliceEngine.shared_limit`
  already does for one grid — the core's `display.shared_limit` is not what the plugin uses)
  **after normalisation and manual adjustment**, so turning normalisation on cannot leave the
  stretch fitted to the uncorrected data.
- **One preview layer**, *Site slice (live preview)*: every included grid resampled onto one
  common north-up lattice (§4.7) and written into M11's existing `SliceLayer` mechanism. One
  layer means one renderer, so the shared stretch is shared by construction. *Design call:* one
  layer per grid with identical renderers was the alternative; it needs no common lattice for
  display but keeps the stretch in sync only by discipline, and multiplies the layer churn M11
  worked to avoid.
- Palette and coverage as in M11. Coverage in site scope is the union of the grids' counts on
  the same lattice.
- The profile band (M11's time-window overlay on the radargram) is unchanged: grids line up by
  time, so the band is the same window whichever grid's line is open.

### 4.6 Normalisation

A **Normalisation** group in site scope: a method combo and a per-grid manual adjustment.

**What every method shares:**

- **Computed per slice.** Factors are recomputed for each window shown or exported, because the
  mismatch between blocks changes with depth: Ernenwein & Kvamme (2008) needed different
  range-gain curves per survey block, the usual cause being moisture-dependent attenuation.
  One factor per grid would be right at one depth and wrong at the rest.
- **Measured on binned cells, applied to the displayed slice.** Statistics come from cells with
  `count > 0` before the fill, because the fill invents values between lines. The factor is
  applied after the fill — equivalent for a gain, since the fill is a weighted mean.
- **A background statistic that ignores strong reflectors.** Following GPR-Slice's documented
  rule, a region's *background level* is the **mean of its weakest 75% of populated cells**.
  The mismatch lives in the weak background, and an anomaly sitting on a seam must not drive the
  correction. The 75% is fixed, not a user control.
- **Measured on magnitude, applied to the value** (*design call*). The Transform combo defaults
  to *none*, so a site slice can be signed amplitude, where "weakest" and a ratio of levels are
  undefined. Background levels are therefore measured on `|v|` — identical to `v` for the
  unipolar transforms — and the resulting gain multiplies `v`, which is physically right for
  signed amplitude too. Histogram match needs no change: mean and σ are defined either way.
- **The site's overall brightness does not drift.** Gains are normalised so their geometric mean
  over included grids is 1, rather than pinning one reference grid.
- **Off by default**, and never written into the cube, the `.npz` or the lines.

**The methods**, for grid *i* at the current slice:

1. **Background level.** `g_i = B_site / B_i`, where `B_i` is grid *i*'s background level and
   `B_site` the geometric mean of the `B_i`. Needs no neighbours, so it works for any grid.
   Its weakness, stated in GPR-Slice's own manual: it assumes each grid holds a similar mix of
   features, so a grid dense with walls is turned down.
2. **Edge match (global).** For every pair of grids that share an edge (§4.6.1), take a strip of
   populated cells on each side of the seam and measure each strip's background level,
   `S_ij` (grid *i*'s side) and `S_ji`. Solve for all log-gains `x_i = ln g_i` at once by
   weighted least squares on `x_i + ln S_ij = x_j + ln S_ji`, one equation per seam, weighted as
   §4.6.1 says. Solving every grid simultaneously rather than chaining pairs is the point:
   sequential merging propagates and accumulates joining errors (Minty et al. 2003, continental
   aeromagnetic compilations; the "bundle" balancing of image mosaicking). The two differ only
   where seams form a loop — a 2 × 2 block of grids, say — where a chain of pairwise matches
   would close with a contradiction and the global solve spreads it. Uses only where grids meet,
   so archaeology in a grid's interior does not bias it.
   - Each **connected group** of grids has one free constant; it is set so the group's
     background matches the site's (method 1's rule), and the gains then renormalised to
     geometric mean 1.
   - A grid that **touches no other** takes method 1's factor.
3. **Histogram match.** A gain *and* shift, `v' = a_i v + b_i`, chosen so grid *i*'s mean and
   standard deviation over populated cells match the site's pooled mean and standard deviation —
   GPR-Slice's ±3σ juncture matching expressed directly. It matches spread as well as level, and
   can therefore flatten a real difference in contrast between grids; that is the user's call to
   make by eye. It is the one method that shifts, so on unipolar data it can produce values
   below zero; the renderer clamps them like any value below the stretch.

**Manual adjustment.** Select a grid in the site list and set its brightness multiplier (a spin
box defaulting to ×1.00 with a useful step, per M11's lesson, and a reset). It multiplies on top
of the method's factor, is constant with depth so the method's depth-following survives, and is
saved per grid in the survey JSON. It works with method *None* too — which makes the user's old
workflow, adjusting by eye, available as a deliberate act.

**No factors table** (user decision). The user judges the map.

#### 4.6.1 Seams

The user's grids are laid **edge to edge, without overlap strips**. A seam is defined by
**proximity, not by touching edges** (*design call*), because two rectangles at slightly
different bearings never share a segment exactly — at a 2° difference their edges drift 0.7 m
apart over 20 m:

- Grid *i*'s strip against grid *j* is its populated cells within a distance `w` of grid *j*'s
  footprint, and vice versa. `w` is *builder's call*, on the order of one line spacing, since
  Geoplot uses the readings either side of the edge and GPR-Slice the adjacent radargram.
- *i* and *j* share a seam when **both** strips hold at least a minimum number of populated
  cells (*builder's call*), so a corner contact or a sliver does not count as a seam.
- The seam's weight in the solve is the smaller strip's cell count.

The user lays their own grids at one bearing and at right angles, but works with other people's
data too and wants arbitrary GPS-recorded lines later, so nothing may depend on alignment. This
reduces to the ordinary edge strips for grids laid parallel or at right angles, and degrades
gracefully — fewer cells, then no seam, then method 1's fallback — as bearings diverge. Each
strip is measured in its own grid's frame.

Overlap-based fitting (Minty 2000) and feathering or blending across seams (GridKnit,
GPR-Slice's post-correction low-pass) were considered and **rejected**: the first because the
user does not survey with overlap, the second because it hides a step rather than correcting it
and smears real data near every boundary.

### 4.7 The common lattice and the site export

**One north-up pixel lattice for the site**, in **the site's CRS — the one the GeoPackage
already uses, `grids[0].crs`**: the union of the included grids' footprints, pixel size equal to
the site cell size, anchored on a whole multiple of the cell size so it is stable as grids are
included or excluded. Every grid's slice is resampled onto it by nearest neighbour from its
grid-local cells, which is `to_north_up`'s existing rule with a target lattice passed in rather
than derived from one frame; for a grid in another CRS, the lattice's pixel centres are
transformed into that grid's CRS before `cell_index`. The display (§4.5) and the export use the
same lattice.

- **The size guard applies to the lattice.** M11's cell-size floor (`MAX_FRAME_CELLS`) is per
  grid; a site's lattice spans its grids' bounding box, which for grids far apart is mostly empty
  and can be far larger than any one grid. The same cap applies to the lattice as a whole, with
  the same warning M11 gives.
- A pixel covered by **no** grid is nodata. A pixel covered by **more than one** (a rotated grid's
  corner overlapping a neighbour) takes the mean of the covering grids' normalised values —
  *design call*; rare when grids abut.
- **Gather indices are computed once per grid per lattice**, not per tick or per band. M11's
  Task 6 recorded the per-band re-solve as ~1.4 s for 39 bands of one cube; a site multiplies it
  by the grid count, and the live preview would pay it on every tick.
- **The rotated-grid cell loss.** M11 measured `to_north_up` dropping 15–18% of frame cells at
  rotated azimuths (output pixel = cell size, nearest neighbour), and decided not to fix it for a
  single-grid export, because the fill usually spreads any isolated cell first. In a site, mixed
  azimuths are normal, so the builder must **re-examine this decision** for the site lattice and
  record the outcome either way.

**Export site GeoTIFF…** writes one multi-band float32 GeoTIFF on that lattice, a band per slice,
using M11's creation options (`INTERLEAVE=BAND`, `TILED=NO`, `COMPRESS=DEFLATE`, `PREDICTOR=3`,
`BIGTIFF=IF_SAFER`) and its band-by-band writing, so no grid's cube need be resident. Values are
**normalised and manually adjusted**, as shown.

**It records what was done** (user: "brilliant"), in GDAL metadata a reader can see without our
plugin:

- dataset level: the transform; the normalisation method; each included grid's id, preset name,
  velocity and manual multiplier; the site cell size and fill radius; the z unit of the bands;
- per band: the shared time window in ns, **each grid's depth range** for it (they differ when
  velocities do, §4.3), and **each grid's normalisation factor(s) for that band**.

The exact key names and their format are *builder's call*; they must be plain enough to read in
`gdalinfo`.

**Temporal properties** as M11 sets them: grids line up by time, so each band has one ns range.
(W10, the user's unresolved trouble with the Temporal Controller, is not in scope.)

### 4.8 Responsiveness

A tick in site scope costs, per included grid, a bin, **a fill** and a gather onto the lattice,
plus the normalisation statistics. The fill dominates (§3), so a ten-grid site at M11's default
resolutions could spend several hundred milliseconds per tick where one grid spent tens. The
builder must **measure a realistic site** — ten grids (the user's sites have fewer), 20 m and
50 m on a side, 0.5 m line spacing, default resolution; synthetic lines are fine for a timing
measurement — before choosing how to keep a drag responsive, and record the numbers.
How (a coarser fill while dragging, caching filled slices, filling only visible grids, or
something else) is *builder's call*; the constraint is that dragging the slider must not feel
worse than M11 does for one grid, and the slice shown when the drag stops must be the full one.

Residency stays per grid and automatic, as M11 decides it.

### 4.9 M11 leftovers taken in

- The gather-index hoist and the rotated-cell-loss re-examination (§4.7).
- **Not taken in:** the residency checkbox's placement (W13). Slices spec §9.2 puts residency in
  settings, M11 Ruling AN put it in Display because the plugin has **no settings infrastructure**
  (§3), and building one is out of proportion here. It stays where it is; W13 stays open.
- **Out:** W10 (Temporal Controller), issues #31–#33.

---

## 5. Normalisation: prior art and why these three

How closely each source was read: **in full** — GPR-SLICE v7.0 manual, *Mosaic Correction*
(pp. 323–337). **Summary only** — Ernenwein & Kvamme 2008 (publisher refused the full text);
Minty 2000 and Minty et al. 2003 (abstracts and citing descriptions); Geoplot's Edge Match and
Zero Mean Grid/Traverse (from survey reports and user guides that describe them); GridKnit (vendor
sheet); VIPS `im_global_balance` and ArcGIS colour balancing (documentation pages).

| Approach | Used by | Outcome here |
|---|---|---|
| Whole-grid background matching (trimmed) | GPR-Slice *0-median / 0-mean grid* with *%max cutoff* | **Method 1** |
| Edge matching, pair by pair | Geoplot *Edge Match* (additive, magnetometry); GPR-Slice *XYZ Edge Match* | Superseded by method 2 |
| Edge matching, all grids at once | Minty et al. 2003; mosaic "bundle" balancing; VIPS `im_global_balance` | **Method 2** |
| Overlap regression | Minty 2000 | Rejected: no overlap strips |
| Histogram matching | GPR-Slice *XYZ Histogram Matching* (±3σ) | **Method 3** |
| Feathering / blending / Poisson seam editing | GridKnit blending; GPR-Slice low-pass after correction | Rejected: hides the step |
| Manual regaining by eye | GPR-Slice *Mosaic Correction* gain ± / DC ± | **The manual adjustment** |

**Multiplicative, not additive** (methods 1 and 2): wetter ground and different gain settings
scale amplitude, signed or not. Geoplot's edge match subtracts an offset because magnetometry
measures nT about a background level, where an offset is the natural error.

---

## 6. De-striping (designed, not scheduled)

Not built in M12 (see the top of this document). When it is scheduled, its export metadata joins
§4.7's list (each grid's stagger shift, whether direction balancing was on).

Three different problems were separated in brainstorming; two are in.

### 6.1 Stagger — the main job

On zigzag surveys, features jump back and forth between alternate lines, because the recorded
position lags differently going out and coming back (walking speed, odometer lag). The user:
*"stagger happens."* The standard fix is Geoplot's *destagger*: shift the reverse-direction lines
along their length.

- **A grid-wide shift**, applied to every `direction = −1` line in the grid (both axes, if the
  grid has x and y lines), **then a per-line shift** on top, for any line. The effective
  along-line position of trace *i* becomes
  `start_along + direction · i / tpm + (direction = −1 ? grid_shift : 0) + line_shift`.
  The sign convention is *builder's call* but must be one convention, shown in the UI in words
  (e.g. "moves return lines forward along their direction of travel").
- **Stored separately from `start_along`**, in the grid and line records of the survey JSON, so
  the field measurement and its correction stay apart and either can be reset.
- **Applied everywhere positions are computed** — `trace_coords`, therefore the map's line
  features, the profile ↔ map link, slice binning.
- **Picks.** A pick's map point is computed once and never recomputed, deliberately, so that a
  pick the user moved by hand is not overwritten (§3). Stagger collides with that rule.
  *Design call:* a pick still sitting where nsgeo placed it (its geometry equals the position
  computed from its line and trace before the shift) moves with its line, and its `distance_m`
  is updated; a pick the user has moved by hand stays put and is reported, so the user decides.
  Related to issue #35 (picks do not follow a grid that moves).
- **A suggested shift** — *design call, the user did not say either way*: at the current slice,
  slide the return lines' window-averaged amplitude series against their neighbouring outward
  lines' and take the shift with the best summed correlation over all pairs, within a bounded
  search range. Offered as a suggestion; the user accepts it or adjusts by eye.
- **Selecting and adjusting a single line** needs UI nsgeo does not have (issue #29: lines cannot
  be edited after import). Its layout is to be mocked up (lavish) and agreed with the user when
  de-striping's plan is written; this document does not fix it.

### 6.2 Direction balancing

When every line in one direction differs from every line in another — out against back on a
zigzag, or an x pass against a y pass done another day (GPR-Slice's manual reports the latter) —
traces are grouped **by heading**, each group's background level is brought to a common level by
a gain (the §4.6 rules: per slice, binned cells, trimmed statistic, geometric mean 1), and a cell
covered by several groups takes the **mean of the group means**, so each direction counts equally
instead of by trace count. This generalises slices spec §6.5, which grouped headings mod 180° and
so could not separate out from back; here headings are grouped mod 360°, into as many groups as
the data has. Off by default.

For grid placements a line's heading is exact from `(axis, direction)`; computing per-trace
heading from coordinates (spec §6.5) is the designed-for path for RTK lines and is not needed
until nsgeo reads DZG. Carrying a group index through binning changes the streaming path and, if
group sums are stored, the `.npz` format — the builder must version it.

### 6.3 Out

**Per-line brightness matching** (Geoplot *zero mean traverse*, GPR-Slice *0-mean-line*): out,
because the user rarely needs it and, per GPR-Slice's own manual, it erases real features that
run parallel to the lines. If it returns, the brainstorm's suggestion was to match each line to
its near neighbours rather than the whole grid, so broad trends survive.

---

## 7. Non-goals and anti-goals

**Not doing:** de-striping (later, §6); lining grids up by depth (after M13, §4.3); overlap-strip fitting; seam
feathering or blending; per-line brightness matching; the Temporal Controller (W10); netCDF;
topographic correction; editing presets from the site list (unless the builder finds it free).

**Would be a failure even if it worked:**

- Normalisation that is on by default, or that changes the cube, the `.npz` or the lines.
- Two controls that can disagree about what depth is on the map.
- A site view that still makes the user repeat an action per grid to look at another depth.
- A site GeoTIFF that cannot say, by itself, what was done to its values.
- (De-striping, later) A stagger correction that only one view knows about.

---

## 8. Left to the builder

Seam tolerance and strip width; concurrency of grid preparation; where the per-grid source,
manual multiplier and stagger values sit in the survey JSON (tolerant loading required); metadata
key names; the stagger sign convention and suggestion's search range; whether the site list's
preset column is editable; how the site engine is composed (one `SliceEngine` per grid is the
obvious shape, not a requirement).

---

## 9. Testing and validation

The rules of the slices spec §11 carry forward: two tiers, real data as the primary validation,
properties not just examples, no new orphans. What is new is that **no real multi-grid survey can
be committed or read by the test suite**. The user has such data and will use it privately. So:

**Automated, on the ten local real lines, perturbed with known answers:**

- **A real seam.** Split the real grid into two grids along a line boundary — a genuine shared
  edge with the same ground continuing across it. Dim one side by a known gain that grows with
  depth; every method must recover it within a stated tolerance, and edge match must do so
  without any reference to the interior.
- **A chain.** Split into three grids in a row with known gains; the global edge match must
  recover all of them. On a chain the global and pairwise solves coincide (one equation per
  seam), and the test asserts that they agree.
- **A loop** — where the global solve earns its place — is a property of the solver, so it is
  tested on the solver directly: seam statistics for a 2 × 2 block with inconsistent seams, where
  the global solve must spread the closure error and a sequential chain must be shown to dump it
  on the last seam. (The real lines all run one way and a placement cannot hold part of a line,
  so a real-data loop would need derived files; it is not worth it.)
- **Isolated grid fallback**, **geometric mean of gains = 1**, **histogram match hits the site's
  mean and σ**, **manual multiplier composes with every method**.
- **Mixed azimuths.** Place the real halves as grids at different azimuths: the data is real, the
  placement invented — enough to test the common lattice, seam detection across rotation, and
  the export arithmetic.
- **Export round trip.** Read the site GeoTIFF back: lattice, band count, nodata, and the
  recorded method and per-band factors.
- **(De-striping, later) Stagger.** First establish whether the local lines were walked zigzag (the user
  believes so but is not sure): a feature crossing the lines aligns across adjacent lines only
  under the right direction assumption. If they were, they may carry real stagger, and the
  suggestion is tested on unaltered data; in any case, shift alternate lines by a known distance
  and the suggestion must recover it.
- **(De-striping, later) Direction balancing** needs x and y lines over the same cells, which the local data
  cannot supply — the one part tested on synthetic data only, and the brief must say so.

**Manual, the acceptance gate:** a walkthrough on the user's own multi-grid data, run by the user,
before M12's merge decision. Nothing from that data is committed. This is the check that
the tests cannot make — whether a real multi-day site looks right — and every M11 walkthrough
round found defects a green suite missed.
