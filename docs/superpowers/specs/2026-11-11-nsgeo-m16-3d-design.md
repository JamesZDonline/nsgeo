# nsgeo M16: 3-D: volumes to explore, surfaces from your picks, the full scene in ParaView

nsgeo turns a grid into a **prepared volume**: a 3-D cube with one smooth body per reflection, balanced so that deep features show as clearly as shallow ones. **Export for ParaView** writes that volume to a folder ParaView opens ready to explore, together with your picks, your survey lines and your features:

- a cloud (volume rendering);
- an isosurface whose level you can change;
- slices in any direction;
- a box that cuts the scene down.

In QGIS you select picks on the map and nsgeo builds a **surface** from them, following the reflection you picked and leaving holes where the radar saw nothing. A surface shows on the 2-D map coloured by depth, and in QGIS's own 3-D view beside your picks.

This replaces the 2026-10-30 draft (`2026-10-30-nsgeo-3d-scene-design.md`, still only on branch `nsgeo-m15-cut-anywhere`). That draft put everything inside QGIS's 3-D view. A day of trials on Sunnyside Grid 1 changed that, and section 2 records what they settled.

---

## 1. What this is for

Two jobs, unchanged from the draft:

1. **Checking a reading in depth.** The driving case is Sunnyside Grid 1: a bowl, a higher line across the north-west quarter and a lower line south-west of the bowl. The trial has already done this once. A surface built from the user's 88 bowl picks, with its holes left in, showed that the bowl's south-west side is missing or disrupted. That changed the user's reading: *"I had been thinking that maybe it was a pool for water of some sort with a channel running off the south eastern side, but looking at this I realize that idea doesn't really 'hold water'."*
2. **Showing it to people who don't read slices.** The surface and the cloud both read at a glance, and both carry their depth stretch in the title.

**What's new is a third job: exploring a grid you haven't read yet.** The user: *"The 'bowl' was the impulse for this, but it isn't the only thing I ever expect to find, so I don't want to over-fit our solutions to that."* The volume views do this job, because they show everything strong without anyone picking it first.

**Why now:** the user wants to explore on their own (*"I think its time to build it so I can explore more on my own"*). The trial needed Claude to run scripts by hand.

**Why ParaView and not QGIS 3-D alone:**
- **QGIS 3-D is limited for volumes.** Measured on QGIS 3.44 in October:
  - no volume rendering;
  - one opaque slice per view;
  - every isosurface level change is a rebuild taking seconds;
  - walls come out banded;
  - a layer's vertical scale is ignored.
- **QGIS's 3-D engine is going away.** Qt 3D has been deprecated since Qt 6.8. In February 2026 the QGIS developers started discussing a move to another engine; there is no plan yet.
- **ParaView has none of these limits** and needs no new dependency in QGIS. nsgeo only writes files.

Simple 3-D stays in QGIS so the work stays in one package: *"I'd love to keep some basic visualizations in QGIS so it stays all in one package."*

---

## 2. What the trial settled

The trial ran on 2026-11-11 against Sunnyside Grid 1, using the user's `high_quality_cube_grid_1.npz`:
- 0.05 m cells, 0.1 ns levels (455 of them);
- preset try1 with squared amplitude;
- 0.071 m/ns;
- filled with the grid's remembered minimum-curvature settings.

ParaView was 6.2.1, on an NVIDIA GTX 1650 with 16 GB of RAM.

The prototypes are in `~/nsgeo-m4-check/m16-paraview-trial/`, on the user's machine only. They are not committed, because they hold the site's coordinates. The builder can read them:
- `export_vtk.py`: the VTK writers;
- `envelope_try.py`: the prepared volume;
- `build_features.py`: the surface builder;
- `grid1-envelope/open_envelope.py`: the ParaView setup script.

### 2.1 Volumes

- **Squared amplitude, balanced level by level, failed.** The user: *"too much noise and the features appear as little flat disks stacked on top of each other, not as cohesive features."* There were two causes:
  - **Squaring keeps every swing of the wave.** One reflection becomes 2–3 thin bright layers about 1.2 ns (4 cm) apart.
  - **Balancing each level on its own** boosted quiet levels into noise.
- **The prepared volume worked.** The user: *"that looks lots closer to what I was expecting!"* The recipe:
  1. Take the mean of the squared amplitude over one wave period (2.5 ns, 25 levels) down each column, then the square root. This is the local RMS amplitude: one smooth body per reflection.
  2. Blur sideways with a Gaussian of 0.1 m that keeps holes as holes.
  3. Divide by the depth trend: each level's median over covered cells, smoothed over 0.15 m of depth.

  On Grid 1 the result has a median of 1.00, p95 1.60, p99 2.45 and p99.9 4.04. An isosurface at 2.5 shows cohesive bodies. The cloud is see-through below 1.8 and reaches 0.6 opacity at 5.
- **Lumps remain:** *"we still have weird lumps."* The likely cause is that every depth level is filled on its own between lines 0.5 m apart. A reflection that changes depth from one line to the next is filled as separate pieces at each depth. This was not tested; see §5.1, step 5.
- **The bowl does not read as a bowl in a volume view,** because it is a thin dipping reflector. It reads as a surface built from picks. This matches October's finding. Volume views are for things that are solid in the radar, and for exploring.

### 2.2 Surfaces from picks

The user made 88 bowl picks on lines 20–33.

- **The user picks consistently.** Their picks sit a median 3.6 cm (about 1 ns) above the strongest swing of the reflection, with an interquartile range of 2.7–4.8 cm. Their earlier line picks sat 2.1 cm and 3.9 cm above.
- **The surface builder that worked:**
  1. Join the picks into a guide sheet.
  2. Measure the picks' offset from the strongest swing.
  3. In each cell, follow that swing within ±2 cm of the guide moved by the offset.
  4. Move the result back by the offset.
  5. Leave a hole where the reflection is no stronger than typical for its depth.
  6. Never join neighbouring cells more than 6 cm apart in depth.
- **How the picks are joined decides the large shapes:**

  | Join | Within 2 cm | 2–5 cm | On a hole |
  |---|---|---|---|
  | Minimum curvature (core's solver, 2 m reach) | 82 of 88 | 3 | 3 |
  | Inverse distance (puts a spike on every pick) | 57 | 28 | 3 |

  The user: *"either looks plausible to me. If I had to pick I'd guess the detailed smooth join."*
- **Smoothing the result lost detail.** A 0.08 m blur fitted 77 of 88 within 2 cm. The user: *"I thought it looked WAY better than this smoothed version. This feels like we lost a lot of detail."* The small stair-steps that remain are one depth sample each, about 3.5 mm.
- **Without picks,** following the strongest reflection in a fixed 0.35–0.95 m window jumped between reflections and did not read as a bowl.
- **Linear features came out patchy.** The higher line came out within 2 cm of 18–20 of its 30 picks, with 10 picks on holes. The lower line had 8 of its 13 picks on holes. On each line the user often placed a second pick where the reflection had faded to ordinary strength (0.5–1.0 × typical). A threshold of 1.5 × typical left most of those picks on holes; 1.0 is the setting that worked.

### 2.3 ParaView

Measured with the 691 MB export (0.05 m cells; three float32 arrays):
- loads in 0.7 s;
- an isosurface level change takes 1.2–1.5 s, for 0.5–2.4 M triangles;
- volume rendering turns smoothly.

ParaView 6.2 broke several things a 5.x-style script relied on:
- colour preset names ("Inferno (matplotlib)" is now "Inferno");
- `ColorBy(display, None)` now raises;
- legend number formats are now `{:.1f}` (std::format), not `%.1f`;
- a script run with `paraview --script=` gets no `__file__`, so the folder has to be passed in, for example through an environment variable set by a launcher.

What worked:
- Contour passes the cube's point arrays through, so an isosurface can be coloured by a true-depth array.
- A slice coloured by amplitude, with no-data cells as NaN at NaN opacity 0, shows holes as holes.
- A Clip with a Box keeps part of an isosurface, and its box can be dragged.

ParaView's volume cropping properties (`UseCropping`, `CroppingOrigin`, `CroppingScale`) exist, but how their numbers map to the box was unclear, so the trial left cropping the cloud out.

### 2.4 Coordinates and depth

- **The trial wrote grid-local metres:** x along grid X (0–20 m) and y along grid Y (0–16 m).
- **ImageData z must rise with index,** so the deepest level comes first.
- **Depth is ×3 in Z,** with true depth kept as an array, and every legend shows true depth.
- **Linear depth needs a constant velocity.** That holds for Grid 1, which has one velocity layer.

---

## 3. Starting state (what M16 relies on)

On main (414b6aa or later):

- **The This grid engine** (`slices_engine.py`) builds a binned `SliceCube` (`nsgeo.slices.cube`) per grid from the grid's preset and transform. It holds the cube and remembers the grid's fill settings: method, cell, max distance and smoothing (`slice_sources` in `survey.nsgeo.json`). `finish_slice` (`nsgeo.slices.finish`) fills and smooths one level as the Slices panel shows it.
- **Saved cubes** (`nsgeo.slices.store`) record their time base (`time_base`, #97).
- **Exports** (`slice_export.py`, `site_export.py`) stream band by band in a `QgsTask`, with a memory estimate, and never promote the engine's residency. M16's export follows the same rules.
- **Picks** live in the authored `picks` table in `site.nsgeo.gpkg`, rebuilt with migrate-and-verify and backed up.
  - Columns include `time_ns`, `zero_ns` (the clock each time is measured from, #97), `depth_m`, `velocity_m_ns`, `stack_json`, `feature_id` (str) and `seq` (int).
  - `feature_id` and `seq` were reserved for exactly this (`2026-09-18-nsgeo-qgis-plan3-design.md` §4.2) and are written null today.
- **Minimum curvature:** core has `nsgeo.slices.curvature.plan_curvature` with a multigrid solver (#111).
- **The core is numpy-only.** No SciPy, and no `pip install` into the QGIS interpreter.
- **QGIS range:** 3.40–4.99.
- **QGIS 3-D from Python, measured in October on 3.44:**
  - `iface.createNewMapCanvas3D` exists.
  - A layer's `setZScale` has no effect in 3-D, so stretch has to be baked into Z or set per renderer.
  - `QgsMeshLayer3DRenderer` is not in Python. It is built from a `<renderer-3d type="mesh">` element through `QgsApplication.renderer3DRegistry()`, and draws nothing unless `setVerticalDatasetGroupIndex` names a group.
  - Offscreen QPA renders a black frame, so render tests need xvfb plus Mesa.
  - Custom 3-D map tools are 4.x only.
- **M15 (cut anywhere)** is built on `nsgeo-m15-cut-anywhere` but not merged. M16 plans A–C (§8) don't need it. Plan D does.

---

## 4. Decisions

### Taken by the user

1. **Basic 3-D stays in QGIS, and the full scene goes to ParaView.** The user proposed adding ParaView and accepted the split: *"I think that looks right."*
2. **Volume views are part of M16, not only surfaces.** *"Yes the surface view may be best for this feature, in which case, great we should have that as an option. but it doesn't mean it should be the only option out there."*
3. **The volume is prepared as in §2.1,** not shown as squared amplitude.
4. **Surfaces are built from a selection of picks in QGIS,** and shown there on the 2-D map and in the 3-D view. This carries over from the October draft (*"what about selecting a collection of picks and then generating the surface based on the reflections associated with them?"*), and the user confirmed it during this rethink.
5. **No smoothing that loses detail.** Surfaces are unsmoothed by default.
6. **Joining picks with minimum curvature is the default.** The user called this a guess (*"If I had to pick"*), so the other join stays available (call 6).
7. **Build it so the user can explore without Claude.**
8. **3-D has its own resolution per grid.**
   - Each grid has a 3-D cell size and depth step. At first use they start from what the Slices panel shows for that grid.
   - They are set when exporting, next to a size estimate.
   - Browsing slices at other settings never changes the export or a surface.
   - Changing the 3-D settings marks that grid's surfaces as needing a rebuild.

   The user chose this when asked by the builder check. The alternative was that 3-D always uses whatever the Slices panel shows.

### Calls made by Claude (check these)

1. **Surfaces are the only feature kind in M16.** The October draft also had lines and bodies:
   - **Lines:** a linear feature is built as a narrow surface. The trial showed that this answers the depth question (the lower line sits about 20 cm below the higher one).
   - **Bodies:** these come from ParaView's isosurface on the prepared volume, where the level can be changed live.

   Line and body features become a follow-up issue.
2. **The prepared volume follows the grid's own slice settings, except resolution.**
   - It uses the grid's remembered source (preset, transform, lines) and its remembered fill (method, max distance, smoothing), so it matches what the Slices panel would show for that grid.
   - Cell size and depth step are 3-D's own (user decision 8).
   - Exporting or building a surface never changes what the Slices panel shows, and never needs the grid to be on screen there. A cube the panel already holds is reused only when it matches the 3-D resolution; otherwise the task bins its own.
   - The export states every one of these settings.
3. **The prepared volume has three parameters:**
   - **Wave period,** default 2.5 ns. The builder may derive it from the data (§11).
   - **Sideways blur,** default 0.1 m.
   - **Depth-trend window,** default 0.15 m.

   They live with the grid's slice settings and are written into the export. Every transform is brought to squared amplitude before the RMS: a bipolar cube, an envelope cube and an absolute-value cube are all squared, and a squared cube goes in as it is. That makes the result true RMS amplitude whatever the transform, so the scene's defaults (tuned on squared data) hold for every grid. Taking the square root of an envelope directly would compress contrast: a reflection 3× typical would read as about 1.7×.
4. **The export is one grid at a time, in grid-local metres.** The CRS, origin and azimuth go in the export's metadata so a later site-wide export can place grids together. Site-wide scenes are a later concern, as in the draft.
5. **Depth stretch** defaults to ×3, can be changed at export, and is baked into Z. True depth is kept as an array, and the scene's title states the stretch.
6. **The surface builder** works as in §2.2, with these parameters and defaults:

   | Parameter | Default |
   |---|---|
   | join | minimum curvature (other choice: exact at picks, by inverse distance) |
   | window | ±2 cm |
   | strength test | 1.0 × typical for the depth |
   | smoothing | off (0 m) |

   It also refines each cell's depth between samples (§5.3), so that sampling steps are not mistaken for detail.
7. **A surface reports its fit:** how many picks lie within 2 cm and within 5 cm of it, and how many sit on holes, with the outliers listed. It also reports the measured offset ("your picks sit 3.6 cm above the strongest swing"). That gives the user a way to spot a pick on the wrong reflection.
8. **Membership and storage carry over from the draft:**
   - A pick can belong to several features. `feature_id` holds the list: ids joined by `;`, in the order they were added (a single id is a list of one). The user decided this on 2026-11-13, after the walkthrough, replacing "at most one feature": making a second surface from picks already in the first took them away from it. Creating or adding to a surface adds its id and removes nothing; removing or deleting takes out only that surface's id.
   - Feature definitions are kept in a new authored, non-spatial `features` table in `site.nsgeo.gpkg`, written as you go like picks.
   - Built geometry is derived, regenerable, written into the site folder, and records its provenance.
9. **Staleness, widened from the draft's call 4.** A surface records everything its numbers depend on, and goes stale when any of these changes:
   - the source (grid, preset, transform, lines);
   - the grid's 3-D cell size and depth step;
   - the fill settings;
   - the volume parameters;
   - the grid's velocity;
   - its picks;
   - its own parameters.

   The Slices panel's scope, grid and resolution never make a surface stale. Rebuilding is always explicit, so a scene never changes during a presentation. Stale surfaces keep showing their last build, labelled as stale.
10. **One grid per feature.** A surface needs at least 3 picks that are not in a straight line. Picks from two grids are refused with a message.
11. **QGIS's 3-D view shows the scene grid's picks and surfaces, with the stretch in its title.**
    - It shows no slice and no walls, since ParaView does both better.
    - It opens from a **3D view** toolbar button that is greyed out until a site is open.
    - nsgeo only adds layers and sets renderers, so an engine change in QGIS doesn't reach it.
12. **On the 2-D map, a surface is a layer coloured by depth,** with one ramp per grid so depths compare. This is the map form of the 3-D surface.
13. **Running ParaView:**
    - An nsgeo setting holds the path to ParaView.
    - **Open in ParaView** writes the export and starts ParaView on it.
    - If the setting is empty, it writes the export and says how to open it.
    - Generated scripts are checked against ParaView 6.2. Older 6.x versions are best effort, and the export says which version it was checked on.
14. **The export goes in the site folder at `paraview/<grid>/`,** replacing the previous export of that grid. It states its size before writing it, because on the user's machine (97% full) 0.7 GB matters.
15. **The feature list UI gets a lavish mockup review before it's built.** It covers making, naming, rebuilding, deleting, staleness and the fit report.
16. **The 3-D fill is a spike inside Plan A, adopted only if it helps.** It compares the level-by-level fill against a fill that follows a reflection's dip between lines. It is adopted only if it visibly reduces the lumps on Grid 1 in the walkthrough. Otherwise it becomes an issue.
17. **The surface builder follows the trial's recipe exactly, because that recipe produced the result the user preferred.** Two details §2.2 doesn't spell out, and that §5.3 now does:
    - the strength test uses strength without the sideways blur or the 3-D fill, so blurring never moves the edge of a hole;
    - a 3×3 median of the cell depths removes single-cell jumps and never fills a hole.

    Where the written recipe and the trial's numbers disagree, the trial's numbers are the acceptance test, and the recipe changes to meet them.

---

## 5. Behaviour

### 5.1 The prepared volume (core, numpy-only)

The input is a grid's `SliceCube` at the grid's 3-D resolution (decision 8, call 2), plus the grid's fill settings and volume parameters (call 3). The output is a 3-D strength array on a uniform depth axis, with NaN where nothing was covered. Steps:

1. **Fill each level** exactly as `finish_slice` does for the Slices panel.
2. **Bring it to squared amplitude.** Square it unless the cube is already squared (call 3).
3. **Take the RMS over one wave period** down each column, then the square root.
4. **Blur sideways** with a Gaussian that keeps holes as holes (`nsgeo.slices.smooth`).
5. **Fill in 3-D,** if the spike adopts it (call 16).
6. **Balance against the depth trend** (§2.1).
7. **Resample to a uniform depth axis** when the grid's velocity has more than one layer. Depth comes from the grid's velocity model. Grid 1 needs no resampling.

**It works in depth slabs** with an overlap of one wave period, never holding a second full copy of the cube. Filling dominates the cost: 154 s for Grid 1 at 0.05 m and 455 levels, single-threaded. So:
- preparation runs as a cancellable task with progress;
- the result is reused until the source or the parameters change.

The builder chooses how to cache it (§11).

### 5.2 Export for ParaView

**Where it starts:** an **Export for ParaView** action for a grid, defaulting to the one the Slices panel is showing. Its dialog shows:
- the grid's 3-D cell size and depth step, which are editable and remembered per grid (decision 8);
- the depth stretch;
- the size the export will take on disk, updated as the settings change.

**Open in ParaView** does the same and then launches ParaView (call 13).

**The folder `<site>/paraview/<grid>/` holds:**

| File | Contents |
|---|---|
| `cube.vti` | The prepared volume as ImageData, in grid-local metres. Arrays: `strength` (the balanced value); `amplitude` (the filled, unipolar value, for slices, NaN where nothing was covered); `true_depth_m` (the builder may drop it, §11). |
| `picks.vtp` | The grid's picks at their depths, with `true_depth_m`, `line` and `feature`. |
| `lines.vtp` | The survey lines at ground level, plus the grid outline. |
| `features.vtp` | The grid's built surfaces, with `true_depth_m`, `feature` and a stale flag. Stale features are included and labelled. |
| `walls.vts` (Plan D) | Lines and cuts standing as curtains, coloured by amplitude. |
| `open_scene.py` | The ParaView setup script. |
| `open.sh` / `open.bat` | Launchers that pass the folder in. |
| `README.md` | A one-page guide, adapted from the trial's `THINGS-TO-TRY.md`. |
| `export.json` | Provenance: source, fill settings, volume parameters, stretch, CRS, origin, azimuth, ParaView version checked, nsgeo version. |

**The scene `open_scene.py` sets up:**
- **On at first:**
  - the cloud, coloured by strength;
  - picks, as balls coloured by true depth;
  - lines;
  - an outline box;
  - a title giving the grid name and stretch.
- **Hidden at first:**
  - an isosurface on strength, starting at 2.5 and coloured by true depth;
  - the isosurface clipped by a draggable box;
  - a depth slice, a slice along a line and a slice across the lines, coloured like the Slices panel (black is strong);
  - each feature.

Colour scales are set last, so no colouring call rescales them. Depth uses one ramp, shared by picks, features and the isosurface.

**Writing:** VTK XML with appended raw binary data, from numpy (the trial's writer). The volume is written in slabs, so peak memory stays near one array. In the trial, a naive write peaked at 3.7 GB.

### 5.3 Surfaces from picks

**Making one:**
1. With the picks layer current, select picks with QGIS's Select tool.
2. Ask nsgeo for a surface, from the toolbar or the feature list (call 15), and give it a name.
3. nsgeo:
   - sets `feature_id` on the picks;
   - records the definition (name, grid, parameters, created);
   - builds the surface in a task;
   - adds it to the map, the 3-D view and the next export.

You can add picks to a surface, remove them, change its parameters, rebuild it, rename it and delete it. Deleting a surface takes its id out of its picks' `feature_id` and never deletes a pick.

**The builder (core):**
1. Put the picks on the cube's clock: each pick's `time_ns` is measured from its `zero_ns`, and the cube's clock is its time base.
2. Convert the picks to depth with the grid's velocity, as the cube does.
3. Join the picks into a guide over the area they cover: their convex hull plus 0.3 m, intersected with the covered cells.
4. Measure the offset: the median, over the picks, of the distance from each pick to the strongest swing within 5 cm of it.
5. In each cell, take the strongest swing within the window of guide + offset.
6. Refine that depth between samples (a parabola through the peak and its two neighbours, or something better).
7. Keep the cell if its strength passes the test; otherwise leave a hole. The strength here is the prepared volume's, but **without the sideways blur and without the 3-D fill** (call 17).
8. Remove single-cell jumps with a 3×3 median of the cell depths. This never fills a hole (call 17).
9. Subtract the offset.
10. Mesh the cells, never joining neighbours more than 6 cm apart in depth.
11. Smooth only if the surface's smoothing is set above 0.

**It reports** the offset and the fit (call 7). A builder that would need to move more than its window to reach a pick reports that pick, rather than honouring or ignoring it in silence.

**Honesty rules** (from the draft, kept):
- a surface leaves holes where the reflection fades, and never smooths over them;
- tracking never leaves its window;
- misfits are reported, not hidden.

### 5.4 In QGIS

- **The 2-D map:** each surface is a layer coloured by depth (call 12). The format is the builder's choice: the October spike drew one mesh layer in both 2-D and 3-D.
- **The 3-D view:**
  - The **3D view** button opens nsgeo's own 3-D view, or brings it forward if it is already open. It shows the scene grid's picks at their depths and its surfaces (call 11), framed on the grid.
  - The scene grid is the one the Slices panel shows in This grid scope. In Whole site scope the view keeps its last grid.
  - The view updates for new picks and for rebuilt or stale surfaces without being reopened. Stale surfaces are labelled.
  - Rotating, zooming and "Save as image" are QGIS's own.

### 5.5 Cuts (Plan D, after M15 merges)

- Picks on cuts can join surfaces, exactly like picks on lines.
- The export gains `walls.vts`: every line, and every saved cut on the grid, as a curtain coloured like the profile view. They are hidden at first in the scene, one item each.

---

## 6. Performance

Measured in the trial, unless marked as a target:

| What | Time or size |
|---|---|
| Filling Grid 1 (0.05 m, 455 levels, minimum curvature) | 154 s, single-threaded; the task's target is to never freeze QGIS |
| Steps 2–6 of the prepared volume | a few seconds |
| Export at full resolution, three arrays | 691 MB, 23 s to write |
| Loading in ParaView | 0.7 s |
| Changing the isosurface level | 1.2–1.5 s |
| Building three surfaces, including computing strength for the whole cube | 9 s; tracking one surface takes under a second |
| Opening the QGIS 3-D view (target) | a few seconds |

Ten surfaces on a grid must stay usable in QGIS 3-D; record the time.

---

## 7. Goals, non-goals, anti-goals

**Goals**

- Export any prepared grid for ParaView in one action, and open it ready to explore.
- Build surfaces from selected picks in QGIS, store them with the site, rebuild them, and see them on the map and in QGIS 3-D.
- Reproduce the trial on Grid 1 without Claude: the cloud and isosurface, and a bowl surface at least as good as the trial's (82 of 88 picks within 2 cm with the minimum-curvature join).

**Non-goals**

- Line and body feature kinds (call 1).
- Site-wide scenes and features across grids.
- Picking or editing inside a 3-D view.
- Volume rendering or slices inside QGIS 3-D.
- Automatic feature detection without picks.
- Topographic correction.
- Saving a camera or scene state.
- Bundling or installing ParaView.

**Anti-goals** (failures even if it technically works)

- A surface that smooths over a gap the radar didn't see. The south-west of the bowl must stay a hole.
- A surface that wanders off the reflection the picks named.
- Stretched depth shown without saying so.
- A prepared volume that quietly differs from the grid's slice settings.
- A scene that changes under you because a source changed somewhere else.
- Losing a pick, or a pick's membership, through feature edits.
- Writing a large export without stating its size first.
- Freezing QGIS while preparing or exporting.

---

## 8. Plans and order

Each plan has 3–6 tasks.

| Plan | What it does | Needs M15? |
|---|---|---|
| **A. Prepared volume and Export for ParaView** | Core volume (§5.1); VTK writers; scene script and guide; the export task and the launch setting; the 3-D fill spike (call 16) | No |
| **B. Surfaces from picks** | `features` table and membership; the core builder (§5.3); the feature list, after its mockup review; surfaces in the export; the 2-D depth layer | No |
| **C. QGIS 3-D view** | The 3D view button, picks and surfaces at depth, live updates, labelled stretch | No |
| **D. Cuts** | Picks on cuts join surfaces; walls in the export | Yes (after M15 merges) |

**Order:** A, B, C, then D.

A on its own already lets the user explore any grid in ParaView. B and C add the surfaces.

---

## 9. Testing and the walkthrough

Real files come first, and synthetic data only where it mirrors them. Every input class needs a test that actually feeds it.

1. **The prepared volume, on the real fixture lines** (`CAMPUS_LINES`, `GPS_LINES`):
   - it is unipolar;
   - a column through a known reflection has one hump where the squared cube has several;
   - each level's median is about 1 after balancing;
   - uncovered cells stay NaN;
   - processing in slabs gives the same result as all at once.
2. **The writers:** a numpy reader in the tests round-trips every array, shape and origin. A test runs the generated script under `pvpython` when a ParaView path is configured, and is skipped otherwise. CI has no ParaView; the walkthrough runs it for real.
3. **The surface builder, on a real reflector in the fixtures:**
   - every pick within the window lands within 2 cm;
   - holes appear where strength fails;
   - the surface never leaves the window;
   - shifting all picks by 1 ns is recovered as the offset;
   - a pick on another reflection is reported;
   - the two joins differ as described;
   - smoothing is off by default;
   - picks on a different clock (`zero_ns`) land on the cube's clock.
4. **Membership,** as in the draft:
   - moving picks between features;
   - deleting a feature leaves its picks;
   - picks from two grids are refused;
   - too few picks are refused;
   - a feature edited, then the site closed without Save site, is exactly as last edited;
   - a CRS change leaves the `features` table alone.
5. **Staleness:** each input in call 9 marks a surface stale when it changes. Changing the Slices panel's scope, grid, cell size or depth step never does.
6. **QGIS 3-D:**
   - opening it and reusing it;
   - the layers it holds;
   - the stretch in the title;
   - QGIS 3.44 and 4.2.

   Render checks need xvfb plus Mesa.
7. **The export:**
   - its stated size matches what it writes;
   - it can be cancelled midway, leaving nothing half-written that looks complete;
   - peak memory is measured.

**Walkthrough** on Sunnyside Grid 1, in a fresh QGIS profile, before any merge decision:
1. Set Grid 1's 3-D resolution to the trial's: 0.05 m cells and 0.1 ns. Every trial figure assumes it, and the files' native step is 0.2165 ns. Check that the size estimate is about 0.7 GB, then export Grid 1 and open it in ParaView. Check the cloud, the isosurface at 2.5 and the three slices, and check that the title states the stretch.
2. Make the bowl surface from the 88 bowl picks. Check that the fit is at least the trial's, that the south-west hole is there, and that the offset is reported.
3. Switch the join and compare.
4. See the surface on the 2-D map and in QGIS 3-D.
5. Make the higher and lower lines as surfaces and judge whether their depth relationship reads.
6. Check the 3-D fill spike's result by eye (call 16).

---

## 10. Documentation

`docs/guide/getting-started.md` gains:
- **Export for ParaView:** what's in the folder, how to open it, and the stretch.
- **Making a surface from picks:** how to pick for a good surface, using the trial's lessons. Pick only where the reflection is clear, and pick the same part of the wave each time.
- **The 3D view.**
- **"Where your data lives":** surfaces, like picks, are saved as you go in `site.nsgeo.gpkg`, while exports and built geometry are regenerable files in the site folder.

The export's own `README.md` is the ParaView guide.

---

## 11. Left to the builder

- **Wave period:** whether to estimate it from the data (for example, the dominant frequency of the processed traces) or keep 2.5 ns, measured on the real files.
- **Caching the prepared volume:** how, and where. It is derived, regenerable, and records its provenance.
- **Dropping `true_depth_m`:** whether to leave it out of `cube.vti` and compute it in ParaView with a Calculator, which saves a third of the size. If so, the isosurface must still be colourable by true depth.
- **The sub-sample peak method.**
- **The file format for built surfaces in QGIS:** a 2DM mesh, GeoPackage TIN or MultiPolygonZ, or both. Provenance is required either way.
- **How stretch reaches QGIS 3-D:** baked Z, or the mesh symbol's vertical scale.
- **Where the feature list lives,** after its mockup review.
- **The exact names and layout of the ParaView scene,** within §5.2.
- **The 3-D fill method for the spike** (call 16).
- **How the tasks split within each plan,** keeping to 3–6 per plan.
