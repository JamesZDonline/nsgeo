# nsgeo M19: magnetometer data — design

nsgeo's first instrument other than GPR. Bartington Grad601 gradiometer grids are imported onto
nsgeo grids, cleaned up, and drawn on the QGIS map in the project's coordinate system, beside the
GPR. A strip of mag readings then sits above the radargram in the Profile panel, so a GPR line or a
cut can be read against the mag along the same ground.

Brainstormed 2026-11-05 and 2026-11-12. The roadmap places M19 after M18 (issue cleanup). It is
built in three chunks, M19a, M19b and M19c (§7). **#180** (slice colours from QGIS's own
symbology) is built before M19 and is what gives mag its min/max in nT (§4, decision 8).

---

## 1. What this is for

The author surveys with a Bartington Grad601 and has been using TerraSurveyor "to orient the grids
and do some basic smoothing, spike removal, etc". In their words:

> I want it all in one place, and in one coordinate system together with my other GIS data so that
> I can see everything together without having a separate georeferencing step. I also hope there
> can be some synergy between processing methods for the final gpr rasters and the mag data
> (smoothing techniques etc). I also hope for some analytical integration between gpr and mag
> datasets.

On integration:

> Having them aligned could help me see where anomalies align in meaningful ways, I would also like
> to examine the GPR profile and a magnetics profile across the same area and see if there are
> correspondences in returns that can aid interpretation. Truthfully, I'm not certain at this point
> what all the options might be, I'm still researching what integration methods include.

Asked what would send them back to TerraSurveyor once this works: *"nothing. My hope is to do
everything here."*

**What success looks like.** The author imports a morning's 30 × 30 m mag grids onto the site,
cleans them up in a few clicks, and sees one seamless mag map on the QGIS map, in the same
coordinate system as their GPR grids and other GIS layers. They lay out 20 × 20 m GPR grids over
the anomalies. Later, opening a GPR line or drawing a cut across one of those anomalies, they see
the mag readings above the radargram and can tell whether a reflector sits under a mag high.

## 2. Starting state (main at `5b67903`)

What M19 can reuse, and what it cannot.

- **Grids.** `Grid` (`nsgeo/geometry/grid.py`) is an affine frame: origin, azimuth, size, CRS,
  default line spacing, optional velocity. It holds no lines. Grids are created and edited in the
  grid dialog (`ui/grid_dialog.py`), which can take corners from the map.
- **Lines are GPR-specific.** `Line` (`nsgeo/model/survey.py`) is one DZT file: a `DztHeader`, a
  placement, a trace count, velocity fits. A line's key is its DZT path (`project.line_key`).
- **Placement.** `GridPlacement` (`nsgeo/geometry/placement.py`) puts trace `i` at
  `start_along + direction * (scale * i / traces_per_metre + travel_shift)`, at `offset` across the
  grid. `scale` is #3's stretch to the grid's edges, `travel_shift` is #47's destagger. Both are set
  in **Edit lines** (`ui/edit_lines_dialog.py`, `line_edit.py`). **Measure** (#159,
  `nsgeo/destagger/`) finds the destagger from the data. It compares each line with the mean of
  its opposite-direction neighbours. Its input, `MeasureLine`, carries GPR envelope bins and a
  `DztHeader`. `traces_per_metre` comes from the `DztHeader`, so placement is GPR-shaped at the
  type level, though not in its maths. Measure's front end is GPR-specific beyond `MeasureLine`:
  it excludes lines by `traces_per_metre` and groups them by time settings (`measure.py`), keeps
  only bins after 4 ns and wants 8 of them (`profiles.time_window`), divides each bin by its median
  over all lines (`profiles.py`, which is about 0 on a zeroed mag grid), reads DZT samples
  (`destagger_job.py`), and has `MIN_CORRELATION` and `CLEAR_RATIO` tuned on GPR. Its core
  (`pair_curves`, `line_curves`, `grid_peak`) carries over as it is.
- **Slices.** Binning is 3-D: `PreparedLine` (`nsgeo/slices/binning.py`) is `(n_samples, n_traces)`
  data with `dt_ns`/`t0_ns` plus `(n_traces, 2)` world coordinates, and `plan_line(line, frame, z)`
  resamples in time onto a `ZAxis`. GeoTIFF export lives in the plugin (`nsgeo_qgis/slice_export.py`,
  `site_export.py`): it takes a `SliceEngine` or `SiteEngine` and writes time-window bands with
  temporal metadata. What is truly 2-D, and indifferent to what the numbers are: interpolation
  (`interpolate.py`, `curvature.py`: None, IDW, kriging, minimum curvature, with a max distance),
  directional smoothing (`smooth.py`), `finish_slice`, the pixel rule (`resample.py`) and
  `display.to_north_up`. So mag reuses the finish and the pixel rule as they are. It needs its own
  2-D binning (or a one-level use of the 3-D one), and a one-band GeoTIFF writer factored out of
  the export code rather than copied (this counts in M19a's size).
- **Whole site** (`nsgeo/slices/site.py`, `site_engine.py`) composes grids onto one lattice and
  can normalise them: `find_seams` finds where grids meet, and `edge_match_solve` solves one gain
  per grid by weighted least squares over the seams. The solve is in log gains, so it is
  multiplicative.
- **Display.** Bipolar slices are coloured symmetrically about zero from a percentile of |values|
  (`nsgeo/render.py`). #180 hands slice colouring to QGIS's own symbology. The slice preview layer
  is a float32 GeoTIFF with a `QgsSingleBandPseudoColorRenderer` (`slice_layer.py`).
- **Profile panel** (`ui/profile_dock.py`, `ui/profile_view.py`). A toolbar row, then the profile
  view with the gain strip on its right, then the velocity strip. Survey lines and cuts (M15,
  `nsgeo/model/cut.py`, `cut_sections.py`) both open here, with a shared hover cursor between map
  and profile.
- **The survey file** (`nsgeo/project.py`). Schema version 1, or 2 when the site has cuts, so a
  build that predates cuts refuses the file rather than dropping them on save.
- **Panels.** Docks are listed in the Panels menu (#84).

## 3. The Grad601 files (measured 2026-11-12)

Six real grids are at `packages/nsgeo-core/tests/data/local/mag-data/example1–6.dat`. They are
gitignored, and are never to be committed. The author confirmed the setup: **30 × 30 m grids, 0.5 m
between traverses, 8 readings per metre, two sensors, walked zigzag.**

- **Format.** Tab-separated text, CRLF, no header: 60 rows × 240 values, in nT to 2 decimals.
  Nothing in the file says the grid's size, spacing, walking pattern or position. All of it has to
  come from the author at import.
- **Rows are traverses.** Readings vary smoothly along a row (median |step| 0.12–0.35 nT, example3's fill left out) and much
  less smoothly across rows (1.05–1.65 nT).
- **The download has already flipped the return traverses**, so every row runs the same way:
  neighbouring rows correlate when compared as stored (r ≈ 0.4–0.7) and not when one is reversed
  (r ≈ 0). The zigzag still shows as stagger: neighbouring rows are offset along the row by about
  ±4 readings (≈ 0.5 m), alternating in sign from row to row. Rows two apart agree.
- **Each pass logs two rows, two apart.** Interior blocks of missing data fall on rows 49 and 51 of
  example4 and rows 33 and 35 of example6, at the same columns. With sensors 1 m apart and
  traverses 0.5 m apart, one pass gives rows `i` and `i + 2`, and the return pass gives `i + 1` and
  `i + 3`.
- **Row levels repeat every 4 rows.** For example, example1's row means by `row mod 4` are 3.68,
  4.08, 4.24 and 2.90 nT. That is two sensors × two walking directions, each with its own zero:
  sensor calibration plus the heading error that changes with direction. This is the striping that
  destriping removes.
- **The grid's level is not zero.** Grid means are 3.3–4.1 nT before any cleanup (example3's fill
  left out).
- **Missing data is written as 0.00.**
  - example3 was only partly walked. Every row ends in a run of zeros, 82 to 222 readings long.
  - example4 and example6 have interior runs of exactly 12 zeros (1.5 m) on both rows of one pass.
  - Genuine 0.00 readings also occur where the field crosses zero: 3 to 15 per grid, and never
    more than 2 in a row.
- **Saturation.** The instrument was on its 100 nT range. Negative readings pin at exactly
  −100.00. Positive readings clip a little below 100, and the level differs between grids: 99.0
  in example2, 99.1–99.2 in example5.
- **No pinned reading is a lone spike.** Every one is the clipped peak of a real anomaly about
  1 m wide: example3 row 14 runs −20.5, −72.5, **−100**, −92.2, −45.9; example6 row 32 and
  example2 row 24 are the same shape. All 25 of example5's are one iron dipole across four
  traverses (rows 48–51, columns 220–232): runs of 4 and 8 pinned at +99.1–99.2, then 6 and 7
  at −100. The builder check found only about 5 genuine single-reading spikes in all six files.

## 4. Decisions

### Taken by the author

1. **Grad601 first.** These files, from the instrument download. Other instruments and formats come
   later (§8).
2. **Mag grids and GPR grids are separate grids, and they overlap.** *"GPR is much slower than
   mag, so often we'll do large 30x30m grids of mag and then more targeted 20x20s of the things we
   want to investigate within them."* A mag grid never has to line up with a GPR grid.
3. **The usual setup is 30 × 30 m, 0.5 m traverses, 8 readings per metre, two sensors, zigzag**
   (confirmed against the files, §3).
4. **The cleanup, in the author's order:**
   > Mag is delightfully simple compared to GPR. If the calibration was off, some destriping may be
   > necessary (i.e. one sensor was calibrated differently than the other. Then, a despike,
   > destagger, some resampling/smoothing, and some color scale adjustment (min/max selection) is
   > usually enough. Normalization across grids may be necessary if multiple grids are collected
   > across a time period.
5. **Each row is a traverse placed on the grid the way a GPR line is,** so the existing destagger,
   Measure and stretch-to-the-edges work on mag. *(Proposed by Claude, accepted.)*
6. **Shared processing runs mostly from GPR to mag.** Interpolation, smoothing, export and
   cross-grid normalisation already exist for GPR slices. Mag reuses them rather than getting
   copies.
7. **Colour control is its own issue, #180, built before M19.** The slice layer's colours come
   from QGIS's own Symbology tab: a colour ramp, a typed min/max, a cumulative cut. *"I think I'm
   happy with it staying in the slices panel."* Mag's min/max in nT is the same mechanism, applied
   to the mag layer.
8. **The mag strip.** *"Two profile windows stacked on top of each other, aligned along the cut line
   horizontally and the mag is just a line with a fill under it going up and down."* From the
   mockup (`.lavish/m19-mag-strip.html`, local), the author chose:
   - **one panel**, with the strip above the radargram, sharing zoom, pan, Fit and the cursor;
   - **two-colour fill:** red above zero, blue below.
9. **Deeper integration waits for the author's reading** (Conyers on GPR and magnetometry).
   M19 builds the mag strip and leaves a placeholder (§6.7).
10. **No reason to go back to TerraSurveyor** is the bar (§9, anti-goals).

### Calls made by Claude (check these)

1. **A grid has an instrument.** `Grid` gains an instrument, GPR or mag. Existing grids and files
   are GPR. The grid dialog asks for it when a grid is made. The GPR panels (Slices, Whole site,
   cuts) use only GPR grids, and the Mag panel uses only mag grids.
2. **Mag readings are not `Line`s.** A mag file is one new kind of entry on a mag grid, holding its
   traverses. Each traverse has a placement with the same fields and maths as `GridPlacement`
   (`axis`, `offset`, `start_along`, `direction`, `scale`, `travel_shift`). Whether that is
   `GridPlacement` itself, with the header dependency removed, or a sibling is left to the builder
   (§10). The rule: nothing about stagger or stretch is written twice.
3. **The Survey panel shows one row per mag file,** under its grid, not one row per traverse. A
   30 m grid has 60 traverses.
4. **Edit lines works on a mag grid.** It lists the grid's traverses, with the same Destagger
   column, grid value, Measure and stretch, so stagger is fixed the way the author already fixes
   it for GPR. Measure gets a mag input (§6.4). Move to grid does not apply: a mag file moves as a
   whole, by reassigning it to another mag grid.
5. **The setup is remembered.** The file has none, so import asks for it once and remembers it for
   the site. The next file from the same survey takes one click.
6. **Missing data:** a run of **4 or more** consecutive 0.00 readings (≥ 0.5 m at 8 per metre) is
   no data, wherever it falls in the row. A shorter run is kept as real readings. §3 shows interior
   dummy blocks of 12, trailing runs of 82+, and real zeros never more than 2 in a row. The length
   is a setting with 4 as its default.
7. **Mag traverses are not drawn on the map as lines.** The mag grid's outline and the mag raster
   show the coverage. *(Assumed to avoid clutter; easy to add later.)*
8. **A new Mag panel** in the Panels menu holds the mag source, the cleanup recipe, the finish
   (cell, interpolation, max distance, smoothing, reusing the Slices panel's finish widgets),
   normalisation and Export. The Slices panel stays GPR-only, with no depth controls hidden or
   repurposed. Destagger stays in Edit lines, as for GPR. **Mock up the Mag panel with lavish
   before M19a is planned.**
9. **The cleanup recipe is saved and reusable,** like a GPR preset: one recipe per site by default,
   with a per-grid override.
10. **Zero the grid is on by default.** It shifts the grid so its median is 0 nT. Grids sit at
    3.3–4.1 nT raw (§3), and a colour range centred on zero needs a zero background. It is the
    lightest possible step: one constant per grid.
11. **Destripe balances sensor-and-direction groups, not traverses.** It is off by default, as the
    author said it is needed only "if the calibration was off". When on, it shifts each group of
    traverses so its median is 0 nT. A group is one sensor walking one direction, so the author's
    setup has four groups (§3). Groups are worked out from the setup, so it needs no knowledge of
    which physical sensor is which. **Zero each traverse** is a second option for grids where
    traverses wander individually. It is not the default, because it erases real features that run
    along the traverses (the reason #47's design dropped per-line brightness matching).
12. **Despike** compares each reading with the median of a window along its traverse. A reading
    further than a threshold from that median, measured in median absolute deviations, is replaced
    by the median. The window and threshold can be changed. **What despike is for is the author's
    call (§5):** removing glitches while keeping iron anomalies whole, or suppressing iron. §3
    shows that pinned readings are clipped anomaly peaks, not spikes, so the first draft's rule
    (always replace pinned readings) would notch real anomalies and is withdrawn.
13. **Normalise across grids is additive.** The same seams (`find_seams`) and the same
    weighted least squares over them as `edge_match_solve`, solving one **offset** per grid in nT
    instead of one gain. It is off by default and is a Mag panel choice, like the GPR Whole site
    normalisation.
14. **The mag map is one site mosaic** of the mag grids chosen in the Mag panel (all of them by
    default), drawn as one live preview layer, like the GPR Whole site. Export writes it as a
    one-band float32 GeoTIFF in the project's CRS. A per-grid view is the same mosaic with one grid
    chosen.
15. **The mag strip reads the finished mosaic** (after cleanup, destagger, interpolation, smoothing
    and normalisation) bilinearly, at each GPR trace's map position for a survey line and at each
    column's position for a cut. Where no mag grid covers the line, the strip is blank and hatched.
    It appears only when mag covers some part of the line.
16. **The strip's nT range** follows the mag layer's own min/max when the author has set one
    through #180. Otherwise it fits the readings along the line shown. Zero is always marked.
17. **A survey file with mag saves at a new schema version,** following the cuts pattern, so an
    older build refuses it instead of dropping the mag on its next save. A site without mag saves
    as before.
18. **Raw files are read where they are,** stored relative to the survey file like DZT paths. They
    are never rewritten. The cleanup is a recipe, not an edited copy.
19. **One file per mag grid.** A Grad601 grid downloads as one file, and zero-the-grid, destripe
    groups and Measure all assume one sitting. "An existing mag grid" at import means one laid out
    in advance and still empty. Importing onto a grid that already has a file asks, then replaces
    it. Reassigning a file moves it to an empty mag grid only.
20. **The setup can be changed after import** (TerraSurveyor's "orient the grids", which the
    author named). **Change setup…** on a mag file re-derives every traverse's placement from the
    new setup. Typed destagger and stretch stay with their traverse (destagger is measured along
    the traverse's own travel, so it keeps its meaning when the start corner changes). The survey
    file therefore stores each file's setup plus per-traverse corrections, not only finished
    placements.
21. **Mag settings belong to the site, and the mag engine to the session.** The recipe, finish and
    normalisation are saved in the survey file from M19a. The mag strip reads every mag grid with
    its saved settings, whether or not the Mag panel is open and whichever grids the panel's
    preview shows.

## 5. Not decided (the author's)

- **What despike is for** (call 12): glitches only, keeping iron whole, or suppressing iron.
  Asked 2026-11-12.
- **Where example1–6 lie, and which real survey has a GPR grid over a mag grid** (§10). Asked
  2026-11-12. The builder check's edge test suggests example1–3 are neighbours (example2's
  traverse ends match example3's starts, r = 0.8; example1's last traverses match example2's
  first, r = 0.46).
- Whether mag traverses should be drawn on the map after all (call 7).
- The Mag panel's layout. A lavish mockup is reviewed before M19a is planned (call 8).

## 6. Behaviour

### 6.1 Import (M19a)

1. **Import mag grids…** (next to the GPR import). The author picks one or more `.dat` files.
2. For each file, they choose its mag grid. It can be an existing mag grid, or a new one made
   through the grid dialog, which can take corners from the map.
3. They give the setup once:
   - the direction traverses run along the grid (its x or y);
   - the corner and side the first traverse starts from;
   - the traverse spacing and the first traverse's offset (default half a spacing in);
   - readings per metre;
   - the number of sensors and their separation;
   - the walking pattern, zigzag or parallel;
   - whether the download has already flipped the return traverses (default yes, as in §3).
4. The setup is checked against the file. 60 rows at 0.5 m and 240 readings at 8 per metre is
   30 × 30 m. A file that does not fit its grid is reported before anything is added. The author
   can still go ahead, and nothing is cropped or stretched silently.
5. Each row becomes a traverse with a placement: its offset across the grid, its start, and its
   direction of travel. For zigzag, travel alternates even though the stored rows have been
   flipped, so destagger knows which way each traverse was walked.
6. Missing data (call 6) becomes no data. The import summary says how many readings that was, and
   where.

### 6.2 The mag map (M19a)

- One live layer, **Mag (live preview)**, shows the mosaic of the chosen mag grids in the
  project's CRS. Readings are binned into cells on each grid's frame, then interpolated, then
  smoothed, using the same finish as slices (`finish_slice`). They are then composed onto one
  lattice with the pixel rule.
- The Mag panel sets the cell size, interpolation method, max distance and smoothing. Defaults
  suit 0.5 m traverses with 0.125 m readings, for example a 0.125 m cell and max distance 0.75 ×
  spacing. The builder confirms them on the real files.
- **Export** writes the mosaic as a one-band float32 GeoTIFF and adds it to the project.
- Colours: the default is a symmetric grey ramp centred on zero. The author's own min/max and ramp
  go through #180's mechanism.

### 6.3 Cleanup (M19b)

The recipe runs in this order, on readings, before binning:

1. **Zero the grid** (on): grid median to 0 nT.
2. **Destripe** (off): each sensor-and-direction group to median 0, or each traverse to median 0.
3. **Despike** (default and behaviour per the author's answer to call 12).

Destagger is not a recipe step. It is placement, in Edit lines (6.4). Resampling and smoothing are
the finish (6.2). Normalisation is a site choice (6.5). That matches the author's order (decision
4).

Each step shows what it did on the grid it ran on: how many readings it replaced, and the offset
each group was moved by. Every change can be undone by turning the step off. The raw readings are
never changed.

### 6.4 Destagger on mag (M19a for the typed value, M19b for Measure)

- Edit lines on a mag grid lists its traverses (call 4). A typed grid value and per-traverse values
  work from M19a, because they are placement.
- **Measure** (M19b) gets a mag front end: line selection, the comparison profile (readings in
  place of GPR envelope bins, with no time window and no per-bin median normalisation), and its
  thresholds re-tuned on the real files. The core (`pair_curves`, `line_curves`, `grid_peak`) is
  reused, so the comparison is still each traverse against the mean of its opposite-direction
  neighbours. Measure's "neighbours" are adjacent traverses. With two sensors, adjacent rows come from different passes
  walked in opposite directions (§3), so the existing rule applies as it is. The builder checks
  that Measure on the real files finds about ±0.25 m per traverse (§3's ±4 readings between
  neighbours, halved).

### 6.5 Normalise across grids (M19b)

An additive edge match (call 13). Seams come from the mosaic. Grids that touch no other grid keep
their zero-the-grid level. The panel shows each grid's offset.

### 6.6 The mag strip (M19c)

As mocked up, and as chosen (decision 8):

- The strip sits above the radargram in the Profile panel, sharing its horizontal axis, for survey
  lines and for cuts. A splitter sets its height. A **Mag** checkbox in the toolbar hides it, and
  the choice is remembered.
- Fill: red above zero, blue below, with the line drawn on top. A dashed zero line.
- Zoom, pan, Fit and #67's held windows apply to both plots together. The hover cursor runs
  through both, and the readout adds the nT value at the cursor.
- The strip's left axis is in nT (call 16), and its label names the mag grid or grids it reads.
- Blank and hatched where no mag covers the line. A line with no mag at all shows no strip.
- When the mag changes (a recipe or finish change in the Mag panel), the strip redraws.
- GPS-placed lines (M17) get the strip without extra work, since they carry map coordinates.

### 6.7 Integration, beyond the strip (placeholder)

Recorded so it is not lost: correlation between mag and GPR maps, combined interpretation layers,
and whatever the author's reading of Conyers suggests. Nothing here is built in M19. The mag strip
is the first integration piece, and it puts mag and GPR on one footing (one CRS, one lattice rule,
one profile axis) that later integration can build on.

## 7. Chunks and order

| Chunk | What | Size |
|---|---|---|
| (before) | **#180**, slice colours from QGIS's own symbology | S |
| **M19a** | Grid instrument; import with remembered setup; mag files and traverses in the model and survey file; missing data; the Mag panel with finish; the mag mosaic layer and export; typed destagger and stretch in Edit lines | L (spec + 5–6 task plan) |
| **M19b** | Cleanup recipe (zero, destripe, despike); Measure on mag; additive normalisation across grids | M |
| **M19c** | The mag strip in the Profile panel | M |

Each chunk gets its own plan, build, walkthrough and merge. M19a is planned after #180 merges,
against #180's real interface, because the mag layer's colours and the strip's nT range (call 16)
both go through it.

## 8. Goals, non-goals, anti-goals

**Goals**
- Grad601 grids on the map in the project's CRS, with no georeferencing outside nsgeo.
- The author's whole cleanup chain (decision 4) inside nsgeo.
- One processing code path for interpolation, smoothing, export, normalisation and destagger,
  shared with GPR.
- Mag read against GPR along any line or cut.

**Non-goals (later, if asked)**
- Other instruments and formats: FM256, Geoscan, Sensys, TerraSurveyor exports, XYZ.
- Mag placed by GPS.
- TerraSurveyor functions the author did not list: deslope, high-pass and low-pass filters beyond
  smoothing, the periodic filter, interpolating to a finer reading interval, cutting areas out by
  hand.
- A profile of a single mag traverse.
- Analytics combining mag and GPR beyond the strip (§6.7).

**Anti-goals (failures even if the feature works)**
- Anything that sends the author back to TerraSurveyor for a step in their chain.
- Mag code paths that copy GPR ones. Interpolation, smoothing, export, edge match, destagger and
  colouring that behave differently for the two instruments, without a reason.
- Real 0.00 readings silently thrown away, or dummy zeros silently drawn as data.
- Destripe on by default, or zeroing each traverse by default (it erases features along the
  traverses).
- Raw files edited in place.
- GPR panels that start listing mag grids, or the reverse.

## 9. Documentation

- The guide gains a mag section: the setup at import, the cleanup order, destagger in Edit lines,
  normalisation and export.
- A help page for each cleanup step, in the style of the processing-step help pages.
- The README's *Not built yet: instruments other than GPR* line changes when M19a merges, and the
  roadmap is updated as each chunk merges.

## 10. Testing and the walkthrough

**Real files first** (the author's rule: synthetic data is trusted only as far as it mirrors real
data). The six `.dat` files, in the local real-data tests, skipped when absent:

- shape 60 × 240, read with CRLF and tabs;
- example3's trailing runs and example4's and example6's interior 12-zero blocks become no data,
  while every run of 1–2 zeros stays as data;
- after destripe, the spread of the four `row mod 4` group medians falls to near 0;
- despike behaves as the author's answer to call 12 says, checked on the clipped peaks and
  example5's dipole that §3 names;
- Measure on each grid finds a destagger near ±0.25 m, and after it is applied, neighbouring rows'
  best lag (§3's method) falls to about 0;
- a mosaic of two grids placed side by side has a seam the additive edge match closes.

The real files live only in the main checkout's `packages/nsgeo-core/tests/data/local/`, which a
worktree does not have. The plan links them into the build worktree, and the real-data tests are
confirmed to have run, not skipped, before a chunk is called green.

Synthetic fixtures only for what the files do not contain: a parallel-walked grid, one sensor, a
file that does not fit its grid.

**Walkthrough** per chunk, deployed to a fresh QGIS profile before any merge decision. M19c's
walkthrough needs a GPR grid lying over a mag grid from the same site. **Open: which real survey
provides that** (to ask the author).

## 11. Left to the builder

- How traverses are modelled (call 2), provided placement maths is shared, not duplicated, and
  Edit lines and Measure take mag traverses.
- How the Mag panel's engine relates to `SliceEngine` and `SiteEngine`. A mag grid is a cube with
  one level, but forcing it through the GPR source choice (preset, transform, time axis) is not
  required.
- Default despike window and threshold, and default cell size, set and recorded from the real
  files.
- The survey file's shape for mag files, setups and recipes, within call 17.
- How the strip shares the profile view's horizontal transform.
