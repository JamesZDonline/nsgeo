# nsgeo M15: cut anywhere, a vertical section along any line you draw

You draw a line on the map and the profile view shows the cube's vertical section beneath it. It works the way a survey line already does: hover to preview, select to open, a cursor that tracks between map and profile, and picks. The cuts are stored, so M16's 3-D scene can stand them upright later.

**Revised 2026-11-06** against main `be2acee` (merged into this branch at `3c2a6ab`). The design was approved on 2026-10-30. Since then, slice interpolation (#110, #122) replaced the fill radius this design was written against, #67 merged, and line editing (#29, #64, #35) is close to merging. What changed:

- §2 is rewritten for current main.
- Calls 2, 7 and 10 now use the interpolation settings in place of the fill radius.
- Calls 11–15 are new: how a column takes its value, what a cut pick is, the slice band, cursor tracking, and smoothing.
- Calls 16–17 came from the builder check: which velocity a cut uses, and how it is coloured.
- Two new decisions, taken by the user on 2026-11-06: minimum curvature on cuts (§4.7) and cuts that move with their grid (§4.8).
- §5 has measurements on Grid 1's real cubes. §6 and §8 gain the matching goals and tests.

**Revised again 2026-11-11** against main `d8acb01` (merged into this branch at `0ae1471`), and against the time-zero branch (#97, `nsgeo-time-zero` `6e42814`, about to merge). What changed:

- §2 adds what has merged since: line editing, the packed cube (#113), multigrid minimum curvature (#111), the pixel rule (#107), placement corrections (#3, #47) and the optional grid velocity (#4). It also adds time zero (#97).
- **Call 11 is revised.** A column now takes the bilinear blend the slice view shows (#107's pixel rule), not its nearest cell's value.
- **Call 2 adds the cube's time base** (#97).
- **Call 18 is new:** a cut's times are on its cube's clock (#97's hand-off).
- §4.7 and §5 are re-measured with the multigrid solver: about 20 s for a 12 m cut on Grid 1 at 0.05 m, down from about a minute. During the build, crops had to reach six line spacings rather than 1 m to meet 0.1% along the lines, so expect about 40 s.
- §1's order follows the README roadmap.

---

## 1. What this is for

This came out of the 3-D brainstorm (research note `docs/superpowers/notes/2026-10-30-isosurface-3d-research.md`). The driving case is Sunnyside Grid 1:

- **A bowl.** In slices it is a ring that shrinks from about 0.56 m to 0.88 m and fills in at the bottom.
- **A higher line.** It crosses the grid's north-west quarter at about 0.65–0.75 m (15–18 ns).
- **A lower line.** It runs just south-west of the bowl at about 0.85 m (20–23 ns), perpendicular to the higher one.

The user's reading, in their words: *"one line starts below the bowl, runs up slightly as it goes past it, and ends into the perpendicular line at an elevation around the height of the top of the bowl or a little above, but I'm not sure."*

Slices cannot settle that. A feature whose depth changes along its length shifts position from slice to slice, the same way the bowl's ring does. A vertical section along the feature shows its depth directly. Today nsgeo shows sections only along the recorded lines. The lower line crosses them at an angle, so no recorded profile follows it.

The spike that led here cut the saved Grid 1 cube along a north–south line through the bowl. The bowl read at once as one reflector, dipping from about 0.45 m to 0.8 m and back over about 4.5 m. A second cut, drawn by eye along the lower line, was suggestive but not conclusive. The user needs to draw the cut themselves, exactly along the feature. That is this milestone.

**What success looks like.** The user draws a cut along the lower line, holding the profile beside the map. Moving the cursor along the cut shows the line's depth at each point, against the bowl's rim and bottom, all the way to where it meets the higher line. They can pick it, and the picks land on the map.

**Order.** This is M15; the 3-D scene is M16. They are separate milestones, at the user's request. The README roadmap (2026-11-11) puts two items before it:
- the time base (#97), because cut picks store times;
- measuring the destagger shift automatically (#159).

It also suggests doing #36 (edit or delete a pick from the profile) early, before cuts bring picking to a second kind of profile.

---

## 2. Starting state (main at `d8acb01`, with #97 about to merge)

- **Profiles come only from recorded lines.** `ProfileDock._show_line` is built around a `Line`: its header, its `StepStack` (`session.stack_for`), channels, the difference view, the time cutoff, display gain and velocity fits (saved, applied and deleted, #85/#90).
- **#67 is merged** (`ui/ruler.py`, `ProfileDock._ruler_for`, `_set_axes_holding`, `_held`):
  - each grid and axis has one ruler, and reversed lines are mirrored onto it;
  - the view's window is held per ruler, so a glance at a cross-line does not lose a zoom.
- **The slice band.** The Slices panel's current window is drawn on the profile as a band (`SlicesDock.window_changed` → `ProfileDock.set_slice_band`). #131 asks for a button to hide it.
- **The map link** (`map_link.py`, unchanged since the first draft):
  - Hover works through `QgsMapCanvas.xyCoordinates` with a 50 ms dwell (`HOVER_DWELL_MS`), so it never takes the canvas from the active tool.
  - Selecting a feature in the `lines` layer opens it (`_on_selection` → `session.open_line`).
  - Cursor tracking relies on one fact: **the line geometry's vertex index is the trace index** (`_track_displayed_line`).
  - The session keeps `current_key` (the working line) apart from `preview_key`. Writes such as `add_pick` refuse anything but the working line.
- **Picks** (`session.Pick`, the `picks` table in `layers.py`):
  - Fields: `line_key`, `trace`, `time_ns`, `distance_m`, `depth_m`, `velocity_m_ns`, `stack_json`, `note`, `created`, `feature_id`, `seq`.
  - `picks` is the only authored table. It gets a migrate-and-verify rebuild (`_rebuild_picks`) and a backup (`_recover_picks_backup`).
- **Line editing** (merged, PR #137, released in 0.3.0) makes picks follow their line:
  - `SiteLayers.follow_lines` re-derives every line pick's map position, `distance_m`, `depth_m` and `velocity_m_ns` from its trace and time, whenever grids or lines change and when a site opens (its spec §4.4).
  - A pick's depth and velocity follow its line's current velocity (its decision 7, the user's ruling).
  - A pick whose key is not a site line is left exactly where it is. Its spec names M15's cut picks as one such case and leaves re-placing them to M15.
- **Placement corrections** (#3, #47, merged): a line's placement gains `scale` (fitting it to its grid) and `travel_shift` (the destagger). Lines and their picks follow them. A grid edit refits fitted lines. Cuts are unaffected, except that the cube under them changes.
- **The grid velocity is optional** (#4, merged). Unset, a line falls back to its header. Call 16 already allows for this.
- **Time zero** (#97, branch `nsgeo-time-zero`, built, about to merge). It relabels the clock: the row the Time zero step lands on reads 0 ns.
  - A `Radargram` carries `zero_ns`, the radar-clock time it calls 0.
  - A line pick gains a `zero_ns` column. `SiteLayers.follow_zero` moves a line's picks to its current zero when that line is opened or its stack changes (`_follow_key`, `SiteSession.line_zero`).
  - A cube's z axis is on the time-zero clock of its preset (its decision 9). Its time base is `time_base_of(provenance.steps)`, which gives `"time_zero"` or `"radar"`.
  - The profile converts the slice band from the cube's clock to the line's.
  - Its hand-off to M15 (its §13): cut picks write `time_ns` on the cube's clock and leave the zero column empty, and their provenance carries the cube's time base.
- **The site GeoPackage's rules** (`layers.py` docstring):
  - `grids`, `lines` and `marks` are derived and read-only. Picks are authored.
  - Writes go through the loaded layer's provider.
  - Known issues: unsaved edits in the picks layer are lost when a CRS change rebuilds it (#22). Moving the `.gpkg` alone loses its `-wal` changes (#23).
- **Slices** (`slices_engine.py`, `slices_plan.py`, `site_engine.py`):
  - One `SliceEngine` holds one source: a `SourceChoice` (grid, preset, transform, line keys) plus a `Resolution`.
  - Preparation (load, preset, transform) is the expensive step. A resident cube is built on demand (`SliceEngine.cube`) and is "a latency optimisation, never a capability".
  - **The cube is read only through its read path** (#113, packed cube): `level(k)`, `slice_levels(k0, k1)`, `values_at(cells, k0, k1)` and `coverage()`. It stores only covered cells.
  - **The pixel rule** (#107, milestone A): every slice picture is the bilinear blend of the four cells around each pixel centre, at the cell size. A pixel is blank exactly where its nearest cell is blank or outside the frame. In code this is `nsgeo.slices.resample`: `bilinear_taps(frame, world)` and `sample(values, taps)`. Whole site may draw a coarser lattice as a preview, but its per-grid engines keep the cell.
  - **The fill radius is gone.** A slice is finished by a `SliceFinish`: the method, the max distance to data (in line spacings), and smoothing X and Y (in metres, along the grid's own axes). The methods are None, IDW, kriging (the default) and minimum curvature. These settings are remembered per grid (`slice_sources[g].resolution`) and for the site (`site_view.resolution`). `SliceFinish.in_metres(spacing)` turns them into the core's `FinishSettings`.
  - **The pipeline per slice** (interpolation spec §4): window mean, then interpolate, then blank beyond the max distance, then smooth, then (site scope only) the site gain `a·v + b`. A data cell is never changed except by smoothing. Every step is linear, and coverage is the same at every level.
  - **IDW and kriging** are planned once per grid and settings (`plan_fill` → `FillWeights`, cached by the engine) and applied per slice. `FillWeights.apply_at(values, cells)` gives chosen cells without building the whole slice.
  - **Minimum curvature** (`CurvaturePlan`) is solved per slice, over the cells near the data, with a multigrid preconditioner (#111, about 4–5× faster at fine cells). It has no weights, and its `apply_at` is the whole solve, indexed. In the panel, kriging stands in while the depth moves. After a 300 ms rest, minimum curvature is solved on one background thread (`PendingSolve`, `refine.py`) and replaces it.
  - The Slices panel has a **This grid** scope and a **Whole site** scope (M12). Whole site keeps per-grid engines, and `SiteEngine._shown` applies `a * draw(...) + b` per window.
- **Core geometry:**
  - `CubeFrame` (`nsgeo/slices/frame.py`) maps world to frame-local metres, azimuth included (`to_local`).
  - The flat cell id is `iy * nx + ix`.
  - The finishing code is `nsgeo/slices/interpolate.py`, `curvature.py`, `smooth.py` and `finish.py` (`finish_slice`).
- **Test data:**
  - The real-data fixtures are in `nsgeo-core/tests/data/local/`, listed per survey since #141 (`tests/real_data.py`'s `CAMPUS_LINES`, `tests/real_lines.py`). The Sunnyside survey is there too (`needs_sunnyside` in the plugin's `plugin_testing.py`).
  - The Sunnyside site is at `~/nsgeo-m4-check/Sunnyside/`, with raw DZTs on `/mnt/DataStorage/VISR/Sunnyside_2023/`. Grid 1 is 20 × 16 m at an azimuth of 10.497°, with 40 lines 0.5 m apart along grid y.
  - **Grid 1's remembered settings** (survey file, 2026-11-06): 0.05 m cells, **minimum curvature**, max distance 0.5 × line spacing, smoothing Y 0.1 m. The driving case runs under minimum curvature.
  - Saved Grid 1 cubes: `grid1cube.npz` (0.2 m, 234 levels, 100 × 80) and `mincurv_cube.npz` (0.05 m, 211 levels, 400 × 320).

---

## 3. Decisions

### Taken by the user

1. **A separate milestone (M15).** It comes before the 3-D scene (M16). It was to wait for #67, which has since merged.
2. **A cuts layer plus a drawing tool.**
   - A toolbar tool draws a cut: select the tool, click a path on the map.
   - Cuts show in a layer of their own.
3. **Cuts are stored like grids, and changing one means redrawing it.** Asked whether dragging a cut's vertices with QGIS's editing tools was worth extending the picks' data-safety code, the user said *"I think redrawing is fine at least for now."*
   - Cuts live in `survey.nsgeo.json`.
   - The `cuts` table is derived and read-only, refilled by nsgeo like `grids` and `lines`.
   - A new or deleted cut needs **Save site**, as a new grid does.
   - Renaming and deleting go through nsgeo.
4. **A cut works with the profile view the way the lines layer does:**
   - hovering previews it;
   - selecting it opens it;
   - the map marker and the profile cursor track each other along it.
5. **No marks on the profile for bends or survey-line crossings.** The user: *"I'm imagining it would get the cursor tracking that currently exists for the lines, so I can tell exactly where I am… I'm concerned about the profile getting too cluttered."* The map already shows the survey lines, so the cursor shows whether you are on a recorded trace or between lines.
6. **Picks work on cuts.**
7. **A cut shows the cube the Slices panel uses for its grid.** If that grid has no prepared source, the profile says so. It never builds one silently.
8. **No processing on cuts.** The processing panel does not apply. The profile's display gain does.
9. **A cut belongs to one grid and stops at that grid's edge.** Cuts across grids are a later concern.
10. **Topographic correction** (elevation rather than depth below the ground) is a later milestone. Nothing here may assume it never comes.
11. **The current layer decides whether the map works on cuts or on lines.**
    - **The problem:** the reviewer found that on Grid 1 a survey line is within hover reach along almost all of a cut, because lines are 0.5 m apart. Under today's nearest-wins hover, pausing on a cut to read a depth would flip the profile to a recorded line.
    - **The user's idea:** a toggle, so the two never mix in one gesture. I proposed using QGIS's current layer as that toggle, and the user agreed: *"what's selected makes sense."*
    - **Cuts layer current:** hover, cursor tracking and selection work on cuts only, and survey lines are ignored.
    - **Any other layer current:** survey lines behave exactly as today.
    - **Why it costs nothing to learn:** QGIS's Select tool already selects only in the current layer, so opening a cut by selection needs the cuts layer current anyway.
    - **Helpers:** turning the **Cut** tool on makes the cuts layer current. The profile title always says whether a cut or a line is showing.
12. **Minimum curvature on a cut shows kriging at once.** Minimum curvature is then solved near the cut in the background and replaces it (§4.7). This was Claude's recommendation, and the user took it on 2026-11-06. The user plans to work on the solver speed-up (#111) soon. Nothing in M15 waits for it.
13. **A cut moves with its grid, and its picks follow it,** as line picks follow their line under line editing (§4.8). The user agreed on 2026-11-06.

### Calls made by Claude (check these)

1. **Velocity fitting is off on cuts.**
   - Why: a hyperbola fit assumes the profile crosses the target squarely. A cut at a slant shows a wider hyperbola and would return a wrong velocity without any warning.
   - What the user sees: the **Velocity** button is greyed out while a cut is open, with a tooltip saying why.
2. **A pick on a cut says it came from a cut, and from what.** *(Revised 2026-11-06.)*
   - Why: line picks sit on recorded traces, cut picks on interpolated data, and the user must be able to tell them apart later.
   - How: `stack_json` carries, in place of a line's stack:
     - the engine's `provenance()`: preset name and steps, transform, line keys, velocity;
     - the resolution: cell and level step;
     - the finish **as drawn when the pick was made**: the method, the max distance in metres, smoothing X and Y. If kriging was standing in for minimum curvature (§4.7), it says kriging.
     - the scope: This grid, or Whole site (not normalised);
     - the cube's time base, `time_base_of(provenance.steps)` (#97's hand-off; call 18). *(Added 2026-11-11.)*
   - The key says it is a cut (see 4.6).
3. **Deleting a cut never deletes its picks.** A pick whose cut no longer exists stays on the map, at the position it was last written to. That covers a deleted cut, and a cut that was never saved before the site closed, since picks go straight into the GeoPackage while cuts wait for **Save site**. Selecting such a pick says its cut is gone and opens nothing.
4. **A redrawn cut is a new cut,** with a new id and the next default name. The old cut's picks stay with the old cut, so they become orphans if it is deleted (call 3). Carrying picks across to a redrawn path is not attempted.
5. **A cut is read in the order it was drawn.** Distance 0 is the first click, at the profile's left. A cut is never mirrored, unlike #67's reversed survey lines.
6. **A cut's grid is the grid under its first vertex.** A first click outside every grid is refused, with a message. The part of a cut beyond its grid's edge shows as blank columns.
7. **The section shows every level, finished as the slices are.** *(Revised 2026-11-06.)*
   - Every level the cube holds, with no slice-thickness averaging.
   - Each level is finished with the Slices panel's settings for that grid: method, max distance and smoothing. It is the same pipeline as a slice (§2), read at the cut's cells only.
   - Why: a cut and a slice at the same depth must agree where they cross. Every step is linear and coverage is the same at every level. So the cut's levels, averaged over the slice's window, give the slice's values at those cells.
   - Beyond the max distance, a column is blank, as the slice is.
8. **The section maths lives in `nsgeo-core`, numpy only,** and returns each column's world position. M16 reuses it to stand cuts upright.
9. **Finishing a cut opens it in the profile.** The user drew it in order to see it.
10. **"The cube the Slices panel uses" means the scope on screen.** *(Revised 2026-11-06.)* The panel can hold two sources for one grid at once: This grid's engine, and Whole site's per-grid engines, which stay prepared after you leave Whole site. They can differ in transform, cell and finish settings.
    - **This grid scope:** a cut on the grid being shown reads that grid's engine, with that grid's remembered finish. A cut on any other grid gets the 4.4 message.
    - **Whole site scope:** a cut reads its grid's site engine, with the site's finish at that grid's line spacing. It does **not** apply the site gain (`SiteEngine._shown`'s `a * draw(...) + b`, re-measured for every window).
    - **Why no site gain:** it balances grids against each other. Applied to a section, it would become a depth-varying gain that depends on which other grids are included, and it would need every included grid binned at every level. Depth balance on a profile is the display gain's job.
    - **What the title says:** in Whole site scope it reads "site view, not normalised", so a cut is never mistaken for the normalised site slice.
11. **A column takes the value the slice view shows at that point.** *(Revised 2026-11-11, for #107.)*
    - **The rule:** each column is the bilinear blend of the four finished cells around it. It is blank exactly where its nearest cell is blank or outside the frame. This is #107's pixel rule, through the same code (`bilinear_taps`, `sample`).
    - **Why:** since #107, every slice picture is drawn this way. A column read from its nearest cell, as the first draft had it, would show steps the slice does not have, and differ from the slice between cell centres.
    - **The outline is unchanged.** A column is blank exactly where the nearest-cell rule would blank it.
    - **The section still needs no cell from beyond the four** around each column, so it reads only those, plus the crops that smoothing and minimum curvature need (§5).
12. **A cut pick is a distance along the cut and a time.** *(New.)* That is its truth, as a trace and a time is a line pick's. `trace` stores the column it was made on, for the record only. It is never used to place the pick, because a column's index changes with the cell size.
13. **The slice band shows on a cut** as on a line. *(New.)* It is how the user relates the cut to the slice on screen. #131's hide button, when it comes, applies to both.
14. **Cursor tracking on a cut projects onto the cut's path.** *(New.)* A line's vertices are its traces. A cut's vertices are the user's clicks, so the vertex trick does not carry over. The point on the path gives the distance, and the distance gives the column.
15. **Smoothing applies to cuts.** *(New.)* It follows from call 7: the slice is smoothed, so the cut is too. Smoothing reaches across the cut, so a section needs the finished cells around the cut, not only those under it (§5).
16. **A cut's velocity is its grid's own velocity.** *(New, from the builder check.)*
    - **The rule:** the grid's own velocity (`Grid.velocity`). If the grid has none, use the first line's header velocity (its dielectric, in survey order), as #4's fallback does. A line's own override is ignored. *(Tightened during Task 2, 2026-11-11: "the velocity the first line resolves to" would have let that line's override in.)*
    - **What uses it:** the depth axis, a cut pick's `depth_m` and `velocity_m_ns`, and their re-derivation (§4.8). The title shows the velocity in use.
    - **Why it needs no engine:** picks are re-derived when a site opens and on every grid or line change, often with nothing prepared. A rule tied to the prepared engine would leave cut-pick depths stale at those moments, or flip between two rules.
    - **Why not a line's own override:** a cut crosses many lines, and one line's own velocity says nothing about the others. So a line override never moves a cut pick. A grid velocity change does.
    - **Where it can differ:** the Slices panel's depth readout uses the first *prepared* line's resolved velocity. The two differ only when the grid has no velocity of its own, or when that line carries its own override. On Sunnyside every grid has a velocity and no line has an override.
17. **A cut is coloured like the slices.** *(New, from the builder check.)*
    - **The palette:** the Slices panel's palette for the cut's source. Grid 1's cubes are squared (`amp_square`), so they have no negative values, and the user's slices use `amp_black_high`.
    - **Why not the profile's colours:** the profile's list is bipolar only, and `render.UNIPOLAR_COLORMAPS` calls a bipolar table on unsigned data a configuration error.
    - **Over the palette:** the profile's percentile slider and display gain apply, since a slice's per-window stretch does not suit a section that spans every depth.
    - **The profile's own colour list** is greyed out while a cut is open, and comes back unchanged for a line.
    - **Blank columns** (beyond the max distance or past the grid's edge) must not read as zero, or as "no reflection". How they are drawn is the builder's call.
    - **Why:** the section and the slice then look alike side by side, which the walkthrough's comparison relies on.
18. **A cut's times are on its cube's clock.** *(New 2026-11-11, #97's hand-off.)*
    - **The axis:** the section's time axis is the cube's z axis. When the preset sets a time zero, that is time below each line's own first break (#97 decision 9). Depth is measured from there at the cut's velocity (call 16).
    - **Picks:** a cut pick's `time_ns` is on that clock, and its `zero_ns` column stays empty. A reader must not take an empty zero on a cut key to mean the radar clock. The provenance's time base (call 2) says which clock it is.
    - **No re-zeroing:** #97's re-zeroing (`follow_zero`, run when a line opens or its stack changes) never touches a cut key, and opening a cut logs nothing about time zero. A cut's picks never change time.
    - **A pick made on another clock.** If the preset's time zero is turned on or off after cut picks were made, the cube's clock changes under them. A column has no single line zero to convert by, since it lies between lines.
      - Such a pick (its recorded time base differs from the cube's) is left out of the profile's overlay. The title adds ` · {n} picks on another clock`.
      - It stays on the map and in the table, unchanged.
      - Why: drawing it at its stored time would put it on a reflection it was not made on, which #97 lists as an anti-goal. The roadmap puts #97 before M15 so that this stays rare.
    - **The slice band on a cut** is drawn as the Slices panel gives it, with no conversion, because the cut and the band share the cube's clock. #97 converts the band only for a line, whose stack may set a different zero.

---

## 4. Behaviour

### 4.1 Drawing a cut

- A **Cut** toggle on the nsgeo toolbar, beside **Pick** and **Velocity**. It is greyed out until a site is open.
- While it is on:
  - each left click adds a vertex;
  - right-click or Enter finishes;
  - Esc cancels;
  - Backspace removes the last vertex, as in QGIS's own digitizing.
- A cut needs at least two distinct vertices. A first click outside every grid is refused on the message bar.
- On finish:
  - the cut joins the site with a default name ("Cut 1", "Cut 2", …);
  - the site is marked unsaved, as after adding a grid;
  - the cuts layer redraws;
  - the cut opens in the profile;
  - the tool stays on for the next cut until it is toggled off, as **Pick** does.

### 4.2 The cuts layer

- **Storage:** cuts live in `survey.nsgeo.json` (decision 3). **Save site** writes them, and closing with unsaved cuts prompts, as it does for unsaved grids.
- **The layer:** a derived `cuts` table (LineString) in `site.nsgeo.gpkg`, refilled from the session like `grids` and `lines`, read-only in QGIS, and shown in the site's layer group.
- **Style:** it must not be mistakable for a survey line. The style and its position in the legend are the builder's call (#68 set the current order).
- **Renaming and deleting** go through nsgeo. Deleting a cut that has picks asks first, and says the picks will stay on the map. Changing a cut's path means drawing a new cut (call 4).

### 4.3 Seeing a cut

- **Which kind the map works on:** set by the current layer (decision 11). Everything below applies while the cuts layer is current.
- **Hover:** hovering near a cut previews its section after the same dwell as a line. Among cuts, the nearest wins, as among lines.
- **Select:** selecting a cut with QGIS's Select tool opens it, through the same path that opens a line.
- **Cursor tracking:** works both ways along the cut, as for lines (call 14).
- **The working item and the mode are separate.** Making another layer current while a cut is open leaves the cut open and working. Hovering then previews lines, and selecting a line opens it, just as it would replace an open line today.
- **The profile shows:**
  - across: distance along the cut, in metres;
  - down: time, with the depth axis lines already get, at the cut's velocity (call 16);
  - colours: the Slices panel's palette for the source, under the profile's percentile and display gain (call 17);
  - the slice band (call 13);
  - the title: the cut's name, its grid, its length, and the method drawn ("Kriging", "Minimum curvature", or kriging standing in while minimum curvature is solved, §4.7). In Whole site scope it adds "site view, not normalised" (call 10).
- **No marks** for bends or crossings (decision 5).
- **Display gain** applies as for a line. Processing, difference, channels, the time cutoff and velocity do not apply. Their controls are hidden or greyed out while a cut is open.
- **#67's per-grid ruler and its held view** do not apply to a cut. A cut opens fitted to its own length.

### 4.4 When there is nothing to show

If the Slices panel's current scope has no prepared source for the cut's grid (call 10), the profile names the cut and its grid and says what to do. For example: "Cut 3 is on Grid 1. Show Grid 1 in the Slices panel to see it." Nothing builds silently. If the panel changes the source, scope or settings (preset, transform, lines, cell, method, max distance, smoothing or scope), an open cut redraws from the new one or shows this message.

### 4.5 Picks on a cut

- Pick mode works on an open cut as on a line. Picks go into the same `picks` table.
- A cut pick is a distance along the cut and a time (call 12). `distance_m` is that distance. `depth_m` and `velocity_m_ns` come from the cut's velocity (call 16), as the profile's depth axis does.
- The map position is the point on the cut at that distance.
- Selecting a cut's pick on the map opens the cut and puts the cursor on it, as `_jump_to_feature` does for line picks.
- A pick whose cut no longer exists follows call 3.

### 4.6 Identity

A cut has a stable id that never changes when it is renamed. Its session key cannot collide with a line key, since line keys are file paths. Picks reference it through `line_key`. The key format is the builder's call.

### 4.7 Minimum curvature on a cut (decision 12)

The interpolation spec left this to M15 (its §12). Minimum curvature has no reusable weights, so a section needs a solve at every level. On Grid 1 at its remembered 0.05 m cell, a whole-frame solve is 0.30 s a level with #111's multigrid, about a minute for all 211 levels (§5). It was 2.2 s, about 8 minutes, before #111.

On real single levels, kriging is not a close stand-in. In the gaps between lines it differed from minimum curvature by 5–7% of the level's range at the 99th percentile, and by up to 43% in the worst cells. The interpolation spec's 0.5% was a synthetic grid's window mean. A cut that silently showed kriging would break the first anti-goal.

**What was decided:**

- **Kriging at once.** Under minimum curvature, a cut first shows kriging at the same max distance and smoothing, so the blanks are the same. The title says kriging is standing in.
- **Minimum curvature behind it.** For the working cut, minimum curvature is solved at every level in the background and replaces kriging when done. The title shows how far it has got.
- **Solved near the cut.** Each level is solved on crops around the cut, not the whole frame. A spike on `mincurv_cube.npz` crossed the cut on crops reaching 1 m beyond it, in 2–4 m pieces. It matched the whole-frame solve on the cut's cells to within 0.003% of the range. Re-measured with multigrid and the bilinear columns of call 11 (2026-11-11), crops reaching 1 m (plus one cell for the blend), in 4 m pieces, took 0.10 s a level, about 20 s for a 12 m cut. They were within 0.0015% of the whole-frame solve at 0.05 m and 0.07% at 0.2 m. That cut was diagonal, though.
  - **Built with a wider reach (2026-11-11).** On the ten real lines, cuts along the lines missed 0.1% by up to 3% with a 1 m reach. Minimum curvature through lines one cell wide couples across the lines the way a spline couples across its knots.
  - **So the reach is counted in line spacings:** six (3 m at 0.5 m). That gives a worst error of 2.2e-5 of the range, at about 0.2 s a level for a 12 m cut at 0.05 m, so about 40 s for Grid 1.
  - **The requirement stands:** agreement within 0.1% of the level's range. Crop sizes are the builder's call.
  - **Crops only at a short max distance (2026-11-11, M15 final review).** The six-spacing reach rests on coupling that falls by a fixed factor per line crossed. A coverage hole has no lines to cross, so there the coupling reaches much further.
    - Measured on the ten real lines with 1, 2 and 3 m holes, cuts across the hole at nine levels:
      - at 0.75 spacings, crops missed 0.1% in 6 of 9 cases (1.1e-3 to 2.75e-3);
      - at 0.5 spacings, every case passed (worst 6.6e-4).
    - So crops are used only up to a max distance of 0.5 line spacings. Above it, including the default 0.75, each level solves the whole frame with the engine's own plan, then smooths and samples. That agrees with the slice by construction.
    - Cost: about 0.30 s a level on Grid 1 against 0.215 s on crops, so about 140 s for its 463 levels.
- **Only the working cut.** Hover previews show kriging and start no solve.
- **Kept, and discarded.** A solved section is kept while the source and settings hold. Any change in 4.4's list discards it.
- **Fair to the slices.** A cut's solve must not hold the slice's own refinement back by more than one level's solve. Whether the two share `refine.py`'s thread is the builder's call.
- **Exports** are not affected: there is no cut export in M15.
- **Picks** may be made while kriging stands in. Call 2 records that they were.
- **A faster solver** (#111, which the user plans to take on) would shorten the wait without changing any of this. The solve goes through `CurvaturePlan`, so a faster plan speeds cuts and slices alike.

**Not chosen:**

- **Kriging only, labelled.** Nothing solved, at no cost, but a cut disagrees with the slice between lines.
- **Refuse.** Under minimum curvature, a cut says to switch method.

### 4.8 When a cut's grid moves (decision 13)

Line editing makes a line pick follow its line through a grid edit, a line edit and a velocity change (the user's ruling on #35, and its decision 7). A cut drawn on a feature in the data should stay on that feature when the grid's placement is corrected, since the data moves with the grid.

**What was decided:**

- **Stored in the grid's frame.** A cut is stored in its grid's frame-local metres, with its grid's id. This settles the first draft's open question in §9, whether a cut's grid is stored or recomputed. An **Edit grid…** change moves the cut with the grid, and the `cuts` layer is refilled from the new placement.
- **Picks follow.** Cut picks follow through line editing's `follow_lines` path. Their map position is re-derived from their distance along the cut. Their depth and velocity are re-derived from the cut's velocity (call 16). A grid velocity change with no move still re-derives depth and velocity, as for lines. A line's own override does not.
- **Removing a grid** removes its cuts with it, since they have no position without it. The prompt says how many cuts and picks are involved. Their picks stay on the map (call 3).
- **Distance stays put.** A cut's length and its picks' `distance_m` never change under a grid move. Only the map position does.

**Not chosen:** cuts fixed on the map, with their picks written once, as the first draft had it. A grid moved after drawing leaves the cut where it was, over different cells.

---

## 5. Performance

**Measured** on 2026-11-06, and again on 2026-11-11 after #111 (multigrid) and #107 (bilinear columns, call 11). One thread, on Grid 1's saved cubes, with a 12 m diagonal cut and columns at half a cell. These are spike numbers, not the build's. The build records its own.

| | 0.2 m cells (234 levels, 100 × 80) | 0.05 m cells (211 levels, 400 × 320) |
|---|---|---|
| Kriging plan (the engine already holds it) | 0.02 s | 1.0 s |
| Kriging section, every level, the four cells around each column only | 11 ms | 33 ms |
| Kriging on whole levels, then the blend, every level | 0.07 s | 1.0 s |
| Kriging section with smoothing Y 0.1 m, finishing whole levels | 0.12 s | 2.2 s |
| Minimum curvature, one level, whole frame | 0.02 s (was 0.04 s) | 0.30 s, 15 iterations (was 2.2 s, 863) |
| Minimum curvature, every level, whole frame | about 5 s (was 8 s) | about 1 min (was 8 min) |
| Minimum curvature, every level, on crops round the cut (±1 m + 1 cell, 4 m pieces, planned once; superseded, see §4.7) | about 2 s; within 0.07% | about 20 s (0.10 s a level); within 0.0015% on a diagonal cut, but up to 3% along the lines |
| The same with crops reaching six line spacings (as built) | 0.02 s a level (the ten real lines) | 0.07–0.20 s a level (the ten real lines); worst 2.2e-5 of the range; Grid 1 is measured in Task 6 |
| Kriging against minimum curvature, one level, gap cells | 99th percentile 5.5–7.4%, worst 17–28% of the range | 99th percentile 5.1–5.9%, worst 35–43% |

**Requirements:**

- **Hover.** Over a cut on a prepared grid under None, IDW or kriging, with or without smoothing, hover should feel like hovering over a line. The cut cells alone are tens of milliseconds even at 0.05 m. Smoothing done on whole levels is not (2.3 s), so it must be done on a crop around the cut. The crop size is the builder's call.
- **Weights.** A cut reuses the weights its engine already holds and never plans its own.
- **Getting a cube** is the expensive step. Preparation is about 0.9 s for 24 lines, followed by binning. If a cut needs a resident cube the engine doesn't hold, that work must not freeze the canvas on hover.
- **Minimum curvature** follows §4.7 and must never freeze the canvas.
- **Measure, don't guess,** on Grid 1 at its remembered settings:
  - the first preview after the panel has prepared the grid;
  - a repeat preview;
  - the redraw after a settings change;
  - under minimum curvature, the time until the walkthrough cut is solved.

---

## 6. Goals, non-goals, anti-goals

**Goals**
- Draw a cut and see its section beside the map, with cursor tracking, on any grid with a prepared source.
- A cut and a slice agree where they cross, under every method, with smoothing on or off.
- Store cuts with the site, so they can be reused later and survive a CRS rebuild (their layer is derived, so it is simply refilled).
- Picks on cuts that can be told apart from line picks.
- Section maths in the core, ready for M16.

**Non-goals**
- The 3-D scene, curtains, picked surfaces and isosurfaces (all M16).
- Cuts across more than one grid.
- Processing on a cut.
- Thickness averaging on a cut.
- Exporting a cut.
- Marks for bends or crossings.
- Topographic correction.
- A site-scope cube for cuts beyond whatever the panel's site scope already prepares for the cut's grid.

**Anti-goals** (failures even if the feature technically works)
- A cut that quietly shows a different cube or a different method from the slices. The user would compare a section and a slice and get contradictory answers. Kriging standing in for minimum curvature is acceptable only while the title says so.
- A pick from a cut that, months later, cannot be told from one on a recorded trace.
- Losing a drawn cut without warning: closing with unsaved cuts must prompt, and a CRS rebuild must refill them.
- A pick losing the way back to a cut that still exists, for example after a rename.
- A velocity from a slanted cut presented as if it were sound.
- A profile cluttered with markings the user did not ask for.
- A cut's background solve that leaves the slices waiting.

---

## 7. Documentation

`docs/guide/getting-started.md`:
- **The toolbar table** (§2) gains **Cut**.
- **A short step after "Make a pick"** explains:
  - drawing a cut and reading it;
  - that a cut needs its grid prepared in the Slices panel, and uses the panel's interpolation settings;
  - that under minimum curvature a cut shows kriging first, then the finished section;
  - that the map works on cuts while the cuts layer is current, and on lines otherwise.
- **§4, Where your data lives:**
  - `survey.nsgeo.json` holds the cuts, and **Save site** writes them;
  - the GeoPackage's **cuts** layer is redrawn from it and is read-only, like grids and lines;
  - a cut moves with its grid, and its picks with it;
  - a pick on a cut stays on the map if its cut is deleted.

The help-pages branch is separate and is not edited here. Note the new tool in its ledger.

---

## 8. Testing and the walkthrough

Real files first. Synthetic data only where it mirrors them. Each of these input classes needs a test that actually feeds it:

1. **A cut drawn exactly along a recorded line.** Under None, its section matches the cube's values in the cells that line binned into, level by level, at the columns on cell centres, and their blend between them (call 11). This is the anchor test.
2. **An oblique cut on a rotated grid** (Grid 1's 10.497°, or a fixture frame at a non-zero azimuth). Columns land in the right cells and blend the right four (call 11); checked against `CubeFrame.to_local`, `cell_index` and `bilinear_taps`, not against a copy of the code under test.
3. **A cut that runs past its grid's edge,** a cut along a gap between lines, and a cut through a coverage hole. These give blank columns, or interpolated ones within the max distance, never another grid's data.
4. **Degenerate input:**
   - a single click;
   - two clicks on the same point;
   - a first click outside every grid;
   - a very long cut;
   - a cut with a hundred vertices.
5. **Pick round trip.**
   - A pick on a cut lands on the map at the right point on the cut and reopens the cut when selected.
   - **Renaming the cut:** its picks still lead back to it.
   - **Deleting the cut:** its picks stay on the map, and selecting one says the cut is gone.
   - **A cut never saved:** a pick made on it, after the site closes without saving, behaves the same way.
   - **A CRS rebuild:** both the pick and the cut survive.
   - **A change of cell:** a pick made at one cell size reopens at the same distance and time at another (call 12).
   - **The clock** (call 18):
     - a cut pick leaves the zero column empty and records the cube's time base;
     - opening a cut with picks writes nothing and logs nothing about time zero;
     - after the preset's time zero is turned on, a pick made before is left out of the overlay and counted in the title;
     - the slice band on a cut is unconverted.
6. **Draw tool and storage.**
   - A finished cut marks the site unsaved. **Save site** writes it, and reopening restores both the cut and its layer.
   - Closing with unsaved cuts prompts.
   - Esc leaves nothing behind.
   - The cuts layer cannot be edited in QGIS.
7. **No prepared source** gives the message, not a silent build.
   - A change of panel source or settings redraws an open cut.
   - **This grid scope:** a cut on a grid other than the one shown gets the message, even when a site engine for its grid is still prepared.
   - **Whole site scope:** the section equals the site engine's finished values (interpolated, blanked, smoothed) without the site gain, and the title says so.
8. **Velocity is greyed out** on a cut and comes back on a line.
   - **The cut's velocity** (call 16): the grid's own velocity, or the first line's when the grid has none. A grid with no velocity whose lines' header dielectrics differ takes the first line's.
   - **Colours** (call 17): a cut on a squared cube draws in the slices' palette, blank columns do not read as zero, and the profile's colour choice is unchanged when a line opens again.
9. **Preview against working state.** Hovering a cut while a line is the working line never lets a write reach the cut, the same guard `add_pick` has.
10. **The current-layer switch** (decision 11), on Grid 1's real 0.5 m line spacing:
    - **Cuts layer current:** with the pointer settled on a cut within reach of a survey line, the profile stays on the cut.
    - **Lines layer current:** the same spot behaves as today.
    - **Changing the current layer** mid-hover never leaves a stale preview.
    - **Turning the Cut tool on** makes the cuts layer current.
11. **A cut agrees with the slice** (call 7), on Grid 1's real data, for None, IDW, kriging and minimum curvature, with smoothing off and on. The cut's levels, averaged over a slice window, equal the slice view's values at the cut's cells. Minimum curvature is held to the solver's tolerance.
12. **Minimum curvature on a cut** (§4.7):
    - the near-cut solve matches the whole-frame solve on the cut's cells within 0.1% of the range, on real levels, for a cut along X, along Y and diagonal;
    - kriging shows first and the title says so;
    - kriging is replaced when the solve is done;
    - a settings change discards the solve;
    - a pick made while kriging stands in records kriging;
    - a hover preview starts no solve;
    - the slice's own refinement still lands while a cut is solving.
13. **A grid that moves** (§4.8):
    - **Edit grid…** moves the cut and its picks, and their `distance_m` is unchanged;
    - a grid velocity change re-derives the cut picks' depth and velocity, and a line's own override leaves them alone;
    - with no engine prepared, a site opening re-derives them the same way;
    - removing a grid removes its cuts after a prompt, and their picks stay on the map.

**Walkthrough** on Sunnyside Grid 1 at its remembered settings (0.05 m, minimum curvature, smoothing Y 0.1 m), deployed to a fresh QGIS profile before any merge decision:
- draw a cut along the lower line, through to the higher line;
- watch it go from kriging to minimum curvature;
- read its depth against the bowl;
- check it against a slice at the line's depth where the two cross;
- pick it;
- redraw it as a new cut, delete the old one, and confirm the old picks stay on the map.

---

## 9. Left to the builder

- How the session represents a cut: a kind of line, or a parallel source the profile dock can show. The dock is currently built around `Line`. Pick whichever keeps one code path for hover, select, cursor and picks, and does not grow two copies of every feature.
- How cuts are laid out in `survey.nsgeo.json`, the `cuts` table's fields beyond an id and a name, and the key format.
  - Say whether `schema_version` moves, and what 0.2.0 then does with a site that has cuts.
  - Today 0.2.0 refuses any other `schema_version`. With no bump, it would open the site and drop the cuts on its next save.
- How the tool is built: a `QgsMapToolCapture` subclass, or nsgeo's own tool with snapping.
- Where renaming and deleting live in nsgeo's UI. Next to the site's grids and lines in the survey panel is the obvious place.
- The column spacing, as long as it is at most half a cube cell and each column has an exact map position.
- Whether the section reads a resident cube or streams levels, within section 5's limits.
- The crop sizes for smoothing and for minimum curvature, within §5 and §4.7's limits.
- How a cut's background solve is scheduled against the slices' (§4.7).
- How cut picks join `follow_lines` (§4.8).
- The cuts layer's style and legend position.
