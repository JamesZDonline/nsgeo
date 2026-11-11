# nsgeo whole site at fine cells — design

Make fine cells work everywhere slices are drawn and written. **Milestone A (#107):** Whole site
never refuses a fine cell. Every map picture blends the cells around each pixel instead of copying
the nearest one, and any reason a picture can't be drawn is said plainly in the panel. **Milestone
B (#108):** the GeoTIFF export can be finer than the live view, both in the cell the grids are
worked out at and in the pixel the file is written at. It streams to disk in the background.

Supersedes, in the site spec (`2026-10-16-nsgeo-site-view-design.md`):
- §4.7's "resampled onto it by nearest neighbour" and "the same cap applies to the lattice";
- M12 Ruling 2 (half the cell for a rotated grid, `lattice_pixel`).

Supersedes, in the interpolation spec (`2026-11-02-nsgeo-slice-interpolation-design.md`):
- §8's "the single-grid preview and export adopt the site's half-pitch lattice rule".

Supersedes the "nearest, not bilinear" rationale in `to_north_up`'s docstring.

Everything else in those specs stands.

Closes #107, #108, #112. Defers #138.

---

## 1. What this is for

The 2026-11-05 field walkthrough (check D2) set Whole site to a 0.05 m cell on a ten-grid site and
got a toast the author could not follow. The Position slider then said "not prepared". Leaving out
the three outlying grids made it work. The author's words:

> I'd like to understand why it fails so we could talk about how to make the process more durable.
> At minimum it would be nice if we could get it to process the whole thing when I click export
> geotiff, so I could set things up at a lower resolution and export at a higher one, but making it
> more durable in real time would be preferable

**What fine cells are for** (author, 2026-11-06): seeing exactly where a feature's boundary is, so
it can be measured and its shape judged, and making publication-quality figures. Figures are made
in QGIS, and files may be shared with ArcGIS or other GIS users.

**Sites will grow.** The author expects sites up to about 120 × 120 m. Setting up at a coarse cell
and exporting at a fine one has to work at that size.

**Amplitudes are compared relatively, never as absolute values** (author, 2026-11-06). A pixel
holding a blend of neighbouring cells loses nothing that matters.

## 2. Starting state

- **The site picture.** Whole site composes every included grid onto one north-up picture, the
  site lattice (`SiteLattice.covering`, `nsgeo/slices/site.py`). It covers the rectangle around
  all the included grids, empty ground included. Each lattice pixel copies the nearest cell of each
  grid under it (`SiteEngine._gather` → `Footprint` → `compose_footprints`), and overlaps take the
  mean.
- **Half pitch.** If any grid is rotated, the lattice pixel is half the cell (`lattice_pixel`, M12
  Ruling 2). This grid's preview and export do the same through `to_north_up`
  (`nsgeo/slices/display.py`). On the walkthrough site every grid is rotated, so a 0.05 m cell is
  drawn and exported at 0.025 m, which is four times the pixels.
- **The refusal.** `SiteEngine._rebuild_geometry` refuses any lattice over `MAX_FRAME_CELLS`
  (4,000,000, `slices_plan.py`). That cap was sized for one grid's interpolation weights, about
  96 B a cell. A lattice pixel costs nothing like that. At 0.05 m the walkthrough site needs
  2,582 × 3,035 = 7.84 M pixels at 0.025 m, and is refused.
- **The stretch.** The shared display stretch is measured on each grid's own finished cells
  (`SiteEngine._measure`), not on the composed picture. Changing the pixel rule does not move it.
- **The site export.** `export_site` (`site_export.py`) writes the live lattice band by band, one
  `SiteEngine.slice_at` per band, on the GUI thread behind a progress dialog with a cancel button.
  It can be no finer than the live view.
- **This grid's export.** `slice_export.py` resamples each band through `to_north_up`, so it also
  writes at half pitch.
- **Both export formats.** Both write float32 GeoTIFF with NaN nodata, using `GeoTiffSliceWriter.OPTIONS`
  (DEFLATE, PREDICTOR=3, spec 9.5), and add the written file to the project as a layer.

### Measured on real data (2026-11-06)

Walkthrough site Grid 1: 0.05 m cells, azimuth 10.497°, kriging, 15–20 ns. The render is in
`.lavish/half-pitch-bilinear/` (gitignored; real data).

| | Nearest cell, half pitch (today) | Bilinear, cell size |
|---|---|---|
| Pixels for the grid | 701,504 | 176,217 |
| Cells never drawn | 0 | 0 |
| Whole site at 0.05 m | 7.84 M | about 1.96 M |

- **Nearest cell at the cell size** (the problem half pitch solves) drops 3,123 of the grid's
  113,598 cells, 2.7%, at this angle. M11 measured 15–18% at steeper angles.
- **At half pitch, zoomed in,** 23% of screen pixels show a neighbouring cell, not the cell under
  them. That is the staircase along every edge.
- **A bilinear file at the cell size, drawn with QGIS's "zoomed in: bilinear" resampling,** looks
  almost the same as bilinear computed straight from the cells at screen resolution.
- **Drawn with QGIS's default (nearest),** the bilinear file shows 0.05 m blocks. The author still
  judged it better than today, though not as good as the smoothed one.

## 3. Decisions taken in brainstorming

**The author's:**

1. **Bilinear at the cell size, drawn smooth, everywhere.** This grid and Whole site, the live map
   and the exported files. Half pitch retires.
2. **Export pixel.** It defaults to the cell size, and a finer one can be asked for. It is a
   separate setting from the export cell.
3. **Normalisation is measured again on the export's own data** when the export cell differs from
   the live one. It is not carried over from the screen (author, 2026-11-10). It is measured on the
   cells as binned at the export cell, before interpolation, as site spec §4.6 measures it everywhere
   else, because interpolation invents values.
4. **Sharpen-as-you-zoom is out of this work** (filed as #138). Past the whole-site limit, the live
   view is a coarser preview with a plain note.
5. **The cube interface** (author, 2026-11-10). The export reads cubes only through
   `SliceCube.slice_levels()` and `coverage()`, and sizes memory only through `estimate_memory`. It
   never reads `cube.mean` directly. #113, which stores only covered cells in a resident cube, is
   built alongside, and its layout must drop in without touching the export. #113's plan (branch
   `nsgeo-packed-cube`, plan call 11) adds a required `n_covered` argument to `estimate_memory`.
   So the export sizes memory through the engine's own `estimate()`, which wraps it, and milestone
   B is built on top of #113 once that merges (*design call*).
6. **Minimum-curvature timings are a worst case** (author, 2026-11-10). Today's ~11 s per band on a
   50 m grid at 0.05 m is what #111, the multigrid solver built alongside, will cut. The export is
   not designed around it, but must stay usable at that speed: progress, cancel, and the GUI stays
   responsive.

**Mine** (*design call*; each was put to the author and not objected to):

7. **The edge rule.** A pixel is blank exactly where the nearest cell is blank. Inside the data it
   blends only the neighbours that hold a value, re-weighted to sum to one. The data's outline
   does not move: blending neither grows nor shrinks it.
8. **Coverage stays counts.** The coverage view and the coverage companion file show trace counts,
   and blending would invent fractional counts. See §5.4.
9. **The whole site gets its own limit,** set by measurement (§5.2). It is no longer
   `MAX_FRAME_CELLS`, which keeps its job for single grid frames.
10. **Milestone A's export refuses** with the plain reason when the full-cell site picture is over
    the limit. It never writes the preview, and milestone B replaces the refusal.
11. **Manual per-grid multipliers are carried into a finer export as typed.** They are settings,
    not measurements.
12. **This grid's export gets the same export cell and export pixel fields** as the site export.
13. **A QGIS style file is written next to every exported GeoTIFF:** colour ramp, stretch, and
    zoomed-in bilinear resampling. Any QGIS project then opens the file looking the same. Other GIS
    software gets the values and picks its own colours.
14. **The everyday export is tiled, band-interleaved, with internal overviews**, not a COG. See
    §6.3 for the measurement and the open question on hosting.
15. **A small export dialog.** There is none today: both exports go straight to a save-file box
    (`plugin.py:964`, `plugin.py:1138`). The Export button opens an nsgeo dialog holding the path,
    the export cell, the export pixel, the estimated size and the free disk space. Its layout is
    reviewed as a mock-up before it is built.
16. **The style file's stretch is measured on the export's own bands as they are written,** by the
    same percentile rule as `limit_over_slices`, and the `.qml` is written last. No extra pass. The
    file's look then follows its own data, as its normalisation does.
17. **A target already open in QGIS.** If a project layer reads the target file, or its coverage
    companion, the export says so and offers to replace it or cancel. Replacing removes the layer,
    writes the file, and adds it again with the new style. Windows cannot replace a file QGIS holds
    open (`slice_layer.py`'s module docstring).

## 4. Goals, non-goals, anti-goals

**Goals**

- Whole site draws the walkthrough site at 0.05 m live, all ten grids included.
- Whole site never refuses because the picture is too big. It draws a coarser preview and says so.
- One pixel rule for every picture: bilinear at the cell size, drawn smooth.
- Every reason a picture cannot be drawn is in plain words, in the panel, and stays there.
- An export can be finer than the live view, in cell and in pixel. It runs in the background,
  streams to disk, and renormalises on its own data.
- Exported files open quickly at any zoom in any GIS, and open looking right in QGIS.

**Non-goals**

- Sharpen-as-you-zoom (#138).
- Paying nothing for empty ground between grids, a sparse lattice. The author declined this on
  2026-11-05 because big gaps are expected to be uncommon.
- Faster per-grid preparation at fine cells: that is #111 and #113.
- Exact cell values in every pixel.
- A rotated-geotransform export. GIS support for those is uneven (#112's notes).

**Anti-goals.** Any of these makes the work a failure, even if it otherwise works.

- An export that silently writes the coarse preview picture.
- A data outline that moves because of the pixel rule.
- A cancelled or failed export that leaves a half-written file at the target path.
- An export that reads cube storage directly.
- A file whose metadata names settings it was not made with.
- A slice that is drawn but whose panel still says "not prepared".

## 5. Milestone A — the live view (#107)

### 5.1 The pixel rule

- **The rule.** For each output pixel centre: transform it into the grid's frame
  (`CubeFrame.to_local`, `cell_index`). Find the four cell centres around it, and blend them by
  distance with bilinear weights. Neighbours outside the frame or blank are dropped and the rest
  re-weighted. If the nearest cell is blank, or outside the frame, the pixel is blank (decision 7).
- **Where it applies.** The site lattice's per-grid lookups (today `_gather`/`Footprint`),
  `to_north_up` for This grid's preview and export, and any new export path.
- **Pixel size.** `lattice_pixel` returns the cell for every azimuth, and half pitch retires. Keep
  the scale-aware edge snap in `SiteLattice.covering`. `snap_azimuth` (Ruling F-5) only feeds
  `lattice_pixel` today, so it goes quiet. Remove it, or give it the new job of treating a frame a
  hair off a right angle as axis-aligned before sampling. The builder chooses.
- **Axis-aligned grids on the site lattice.** The lattice is anchored on whole multiples of the
  pixel, and a grid's origin is wherever it was laid out. So an axis-aligned grid's cells generally
  sit a fraction of a cell off the pixel centres. Today each pixel copies the nearest cell, so values
  are exact but shifted by up to half a cell. Bilinear blends by the offset, so positions are right
  and values soften slightly. Accepted, per decision 1. On This grid, `to_north_up` anchors on the
  frame itself, so an axis-aligned grid is reproduced exactly.
- **Overlaps between grids.** Still the mean of the grids' blended values.
- **Drawn smooth.** Every slice layer the plugin adds sets QGIS's zoomed-in resampling to bilinear:
  This grid's preview, Whole site's preview, and exported layers.
- **Tests.** `compose` and `compose_footprints` are tested to be bit-identical. Change both
  together, or retire `compose` if nothing else uses it.

### 5.2 The whole-site limit

- **The site's own pixel limit.** It is set from what a site pixel actually costs: the per-grid
  lookups, the per-redraw accumulators, and the output array, against a target redraw time.
  The candidate is about 16 M pixels; the builder measures and sets it, and records the measurement.
- **Slim the accumulators.** `compose_footprints` sums in float64 with an int64 count today; float32
  sums and a small integer count cut that.
- **Single-grid frames** keep `MAX_FRAME_CELLS`. That limit is about the interpolation weights.
- **For scale:** the walkthrough site at 0.05 m is about 1.96 M pixels. A fully surveyed
  120 × 120 m site at 0.05 m is 5.76 M. At 0.025 m it is about 23 M, which is over a 16 M limit.

### 5.3 Past the limit: a coarser preview

- **How it is drawn.** If the site picture at the cell size is over the limit, double the pixel until
  it fits and draw that. The grids are still binned, interpolated, smoothed and normalised at the
  chosen cell; only the picture's pixel changes.
- **The panel says so,** where the slice's status is shown, and keeps saying it while the preview is
  up. For example: "Preview drawn at 0.10 m pixels; the grids are at 0.05 m." Not a toast.
- **The export never takes the preview lattice.** `plan_site_export` takes the live lattice today.
  Give the export its own full-cell lattice, and refuse in milestone A if that is over the limit
  (decision 10).

### 5.4 Coverage

- **Counts are never blended within a grid.** The coverage view and the coverage companion file
  never blend one cell's count with its neighbours'. Where grids overlap, counts average as they do
  today (`compose_footprints`, `site_export.py`'s "coverage is composed like values"), unless the
  builder finds a reason to change that and records it.
- **No cell's count may be hidden by the pixel rule.** Coverage exists to find gaps, so a zero-count
  cell that no pixel shows hides a real gap. The rule that meets this is the builder's. For example:
  nearest cell at half the cell for coverage only, or a pixel showing the smallest count among the
  cells it touches. If coverage keeps a finer pixel than the amplitude picture, it is checked
  against the limit separately.

### 5.5 Plain reasons

- **Where they appear.** Every refusal that remains is shown in the Slices panel, where the slider
  says "not prepared" today, and stays until the cause is fixed. A toast may also appear, but it is
  never the only place. Remaining refusals include a single grid's frame over `MAX_FRAME_CELLS`, and
  milestone A's export over the limit.
- **What they say.** What is too big, and why, in plain words. What to do about it. For the site,
  name the grids whose removal shrinks the rectangle most. The old toast's wording, "the site lattice
  would be … at 0.025 m, more than the 4,000,000 a slice can be drawn at …", is the example of what
  not to write.
- **Showing the pixel size (#112).** When the pixel differs from the cell, the panel shows the pixel
  size next to the cell: the preview case in §5.3, or a finer export pixel. The export's success
  message states both. With half pitch gone, they are otherwise equal.

## 6. Milestone B — the export (#108)

### 6.1 What the user sets

- **Two new fields on both export dialogs,** site and This grid:
  - **Export cell.** How finely the grids are binned and interpolated. It defaults to the live cell.
  - **Export pixel.** How finely the file is written. It defaults to the export cell, can be set
    finer, and is never coarser than the export cell.
- **A finer pixel** is bilinear evaluated at that pixel, so the file looks smooth in any viewer.
  Each halving of the pixel quadruples the file; the dialog shows the estimated size.
- **Everything else comes from the live view:** interpolation method, max distance, smoothing,
  normalisation method, manual multipliers, thickness and step, transform, and which grids are
  included.

### 6.2 How it runs

- **In the background.** It runs off the GUI thread, with progress and a cancel button. The live
  view stays usable. Follow the plugin's known traps for `QgsTask` and exceptions in slots
  (environment facts).
- **At an export cell different from the live one,** each grid is rebuilt at the export cell:
  binning, interpolation, smoothing. The live engines are never touched; the export uses its own.
  Normalisation (background level, edge match, histogram) is measured again on each band's cells
  as binned at the export cell (decision 3). Manual multipliers are carried as typed (decision 11).
- **At the live cell**, the export may reuse the live engines' prepared state, but still writes at
  the export pixel.
- **Streamed.** The file is written band by band. No more than one band of the full site picture
  is held at a time, and no whole cube beyond what `estimate_memory` and the residency rule allow.
- **The cube interface** is `slice_levels()`, `coverage()`, and memory through the engine's
  `estimate()` (decision 5).
- **The order of work is measured, then chosen:**
  - band by band, holding every grid's fill weights;
  - or grid by grid, holding one grid's weights and accumulating the file window by window, with
    a count so overlaps still average.

  The deciding facts are memory per grid at the export cell and the time per band. Record the
  measurement. Edge match needs every grid's seams at once, so a grid-by-grid order has to handle
  that.
- **Worst-case timing.** Minimum curvature at ~11 s per band and grid (decision 6). The progress
  shows the band and grid it is on, and cancel takes effect within one grid's band.

### 6.3 The file

- **Format, as now.** float32 GeoTIFF, NaN nodata, DEFLATE with PREDICTOR=3.
- **Layout, new.** Tiled, band-interleaved, with internal overviews built with nodata-aware AVERAGE
  resampling, so empty ground does not bleed into grid edges. BIGTIFF when needed.
- **Why not a COG** (measured 2026-11-10, GDAL 3.8.4, the GDAL under the author's QGIS 3.44.7 on
  Linux). On a 40-band, 1300 × 1500 px test file:
  - GDAL 3.8's COG driver has no band interleave, so it writes every band into each tile.
  - Reading one band took about 1 s from the COG against 0.04 s band-interleaved. QGIS draws one
    band at a time, so stepping through depths would be about 25× slower, and worse with more bands.
  - The COG copy also took 14 s against about 5 s for overviews in place, and the file was 25%
    larger.
  - Metadata, band descriptions and NaN nodata all survived the COG copy.
- **Hosting online.** Hosting is an open question for the author (§9).
- **Disk.** Check free space before starting, using the estimate shown in the dialog.
- **Write safely.** Write to a temporary name in the target directory and rename on success. A
  cancel or failure removes the temporary file and leaves any existing file at the target path
  alone.
- **Metadata.**
  - Every existing key stays.
  - `NSGEO_SITE_CELL_M` is the export cell, and `NSGEO_SITE_PIXEL_M` the export pixel.
  - Add a key naming the resampling (`bilinear`).
  - The per-band `NSGEO_GRID_FACTORS` are the factors the export itself measured.
  - This grid's file has none of the cell, pixel or resampling keys today. It only has
    `NSGEO_INTERPOLATION`, `NSGEO_MAX_DISTANCE_M`, `NSGEO_SMOOTH_X_M`, `NSGEO_SMOOTH_Y_M` and
    `NSGEO_FRAME_AZIMUTH_DEG`. It gains cell, pixel and resampling keys. Key names are part of the
    format, so the plan names them.
- **Style file.** A `.qml` with the same base name: colour ramp, stretch (decision 16) and
  zoomed-in bilinear resampling (decision 13). Check that QGIS picks it up as the default style when the file is added
  to a fresh project. The coverage companion gets its own.
- **Temporal properties.** Applied to the added layer as now.

## 7. Testing

- **Real data first** (the standing rule). The walkthrough site:
  - ten grids;
  - Grid5 and Grid8 near 90°, the others 4–10° off north;
  - the survey file and cubes are in the author's local check folder, never committed.

  Synthetic grids only as far as they mirror those.
- **The pixel rule:**
  - on a rotated grid, every cell with data feeds some pixel;
  - the outline matches nearest-cell's to the pixel;
  - on This grid (`to_north_up`), an axis-aligned grid at the cell size reproduces the cells
    exactly. That is not expected on the site lattice (§5.1);
  - blank neighbours are re-weighted, not averaged as zero.
- **The limit and the preview:**
  - the walkthrough site at 0.05 m draws at the cell size;
  - a cell that pushes it over the limit draws a preview with the note;
  - the export over the limit refuses in milestone A, and never writes the preview lattice.
- **The export:**
  - export cell ≠ live cell rebuilds and renormalises: factors differ from the live ones where the
    data does;
  - cancel mid-band leaves nothing at the target path;
  - metadata round-trips, the `.qml` is written, and overviews exist and do not bleed.
- **The cube interface.** A test, or a review check, that the export path never touches
  `cube.mean`. Write it as a contract #113's packed cube can run against.

## 8. Manual checkpoints

Human gates, tracked and reported, never passed silently.

1. **Milestone A walkthrough** on the deployed plugin, on the walkthrough site:
   - Whole site at 0.05 m with all ten grids draws, and depth scrubbing is usable;
   - zoomed in on a feature edge, it is smooth: no staircase, no blocks;
   - a cell fine enough to go over the limit shows the preview note, and the author can read it;
   - a remaining refusal reads plainly;
   - This grid looks the same way.
2. **Milestone B walkthrough:**
   - export the site at a finer cell (0.025 m), and at the live cell with a finer pixel;
   - cancel one mid-way;
   - open the files in a fresh QGIS project (the style file applies) and step through depths;
   - if the author has access, open one in ArcGIS or another GIS.

## 9. Open for the author

- **Hosting online.** What happens when the author decides to host exports?
  - One COG per depth band, written by an option on the export. This avoids the interleave problem
    entirely, and is how such files are usually served.
  - Or a multi-band COG once the GDAL under the author's QGIS supports band interleave. That is
    believed to be GDAL 3.11 or later, not yet confirmed.
  - Or leave it to a later issue.

## 10. Left to the builder

- The whole-site limit's value, from measurement (§5.2).
- How the bilinear lookups are stored, for example four ids and four weights per pixel, or ids and
  fractions, and whether `compose` survives.
- The coverage rule that meets §5.4.
- The export's order of work (§6.2), its threading mechanism, and its overview levels.
- QGIS's zoomed-out resampling setting.
- Splitting each milestone into a 3–6 task plan.

## 11. Overlaps

- **#113** (packed resident cube) and **#111** (multigrid minimum curvature) are built on their own
  branches at the same time. They will meet this work in `slices_engine.py` and `site_engine.py`.
  The export goes through the engine and cube interfaces only (decision 5).
- **#138** (sharpen as you zoom) builds on milestone A's preview and pixel rule.
- **#112** closes here: half pitch goes, and the pixel size is shown when it differs (§5.5).
