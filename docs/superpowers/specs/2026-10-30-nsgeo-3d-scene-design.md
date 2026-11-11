# nsgeo M16: the 3-D scene, features built from your picks

You select a group of picks on the map and nsgeo builds a feature from them: a surface, a line or a body. A **3D view** button opens QGIS's own 3-D view of a grid, showing:

- your picks at their depths;
- your features;
- the Slices panel's current slice at its depth;
- your survey lines and cuts standing as walls.

Everything is built in 2-D and only looked at in 3-D.

---

## 1. What this is for

This is the second half of the 3-D brainstorm. The first half is M15, "cut anywhere" (`2026-10-30-nsgeo-cut-anywhere-design.md`). The research and spikes behind both are in `docs/superpowers/notes/2026-10-30-isosurface-3d-research.md`.

Two jobs, in the user's order:

1. **Checking a reading in depth.** The driving case is Sunnyside Grid 1 (M15 §1):
   - a bowl, from about 0.45 m at the rim to 0.8 m at the bottom;
   - a lower line just south-west of it at about 0.85 m;
   - a higher line across the north-west quarter at about 0.65–0.75 m.
   
   The user's reading is that the lower line rises past the bowl to meet the higher line near rim height. In 3-D that becomes a question you can see: does the line rise to meet the other one?
2. **Showing it to people who don't read slices.** The setting is live in QGIS on the user's laptop or a projector. Success is someone saying "oh, it's a bowl" within seconds, without first being taught what a slice is.

**What the spikes settled** (QGIS 3.44.7, on the real files):

- **The bowl reads as a picked surface coloured by depth, and in a vertical section.** It does **not** read as an isosurface. A thin reflecting layer breaks into tubes and fragments, and the result is very sensitive to the level.
- **Isosurfaces suit things that are solid in the radar,** such as a wall, a strongly reflecting fill or a void. They need a box around the target and a depth window. Without them the straight reflector at about 1.85 m comes into the scene, and the user identified that as a **fence reflection**, not a buried feature.
- **QGIS's own 3-D view does all of this from layers.** No new dependency is needed. The working pieces:
  - polygon meshes (MultiPolygonZ in a GeoPackage, rule-based colours);
  - mesh layers coloured by depth (2DM files);
  - one slice draped on a flat terrain lowered to its depth;
  - vertical polygons standing as walls.

**Order.** M16 follows M15. M15 delivers picks on cuts, the section maths, and cuts stored with the site, and M16 uses all three. M16's plans are written after M15 is built.

---

## 2. Starting state (what M16 can rely on)

- **From M15** (designed, not yet built):
  - cuts are stored in `survey.nsgeo.json` with a derived, read-only `cuts` layer;
  - picks can be made on cuts;
  - a core function samples the cube along any path and returns each column's world position;
  - the current layer switches the map between working on cuts and on lines.
- **Picks** (`picks` table):
  - Two fields were reserved for exactly this (`2026-09-18-nsgeo-qgis-plan3-design.md` §4.2): **`feature_id`** ("groups picks into one interpreted feature") and **`seq`** ("order within that feature"). Both are written null today.
  - Picks are the one authored table: migrate-and-verify rebuild, backup.
  - A pick's map position is written once; time is the truth; `depth_m` is stored beside it.
- **Slices:** the Slices panel shows its current slice through **one** `QgsRasterLayer` (`slice_layer.SliceLayer`), whose data source is re-pointed on every tick. It has This grid and Whole site scopes.
- **The profile view** shows either a survey line, its processed radargram, or (after M15) a cut's section.
- **Map selection:**
  - Selecting one line opens it.
  - **Selecting several does nothing today, deliberately.** `MapLink._on_selection`: "A multi-selection has no single answer, and guessing one is worse than doing nothing."
- **QGIS 3-D from Python, measured:**
  - `iface.createNewMapCanvas3D(name)` and `iface.mapCanvases3D()` exist (3.44).
  - **Vertical scale:** a vector layer's `elevationProperties().setZScale()` has **no** effect in 3-D, so stretch must be baked into Z or set per renderer. 3-D symbols take a data-defined height (`QgsAbstract3DSymbol.PropertyHeight`), and the mesh 3-D symbol has its own vertical scale.
  - **The mesh renderer:** `QgsMeshLayer3DRenderer` is not in Python. Build it from a `<renderer-3d type="mesh">` element through `QgsApplication.renderer3DRegistry()`. It draws nothing unless `setVerticalDatasetGroupIndex` names a group.
  - **A slice at depth:** `QgsFlatTerrainSettings.setElevationOffset`, with the slice raster draped.
  - **Rendering in tests:** offscreen QPA renders a black frame, so render tests need xvfb plus Mesa. Layer-level tests do not.
  - **Engine risk:** Qt 3D has been deprecated since Qt 6.8 and QGIS is discussing a replacement. A plugin that only produces layers and sets renderers is insulated from a swap.
- **QGIS range:** 3.40–4.99. Custom 3-D map tools (`Qgs3DMapTool`) are 4.x only, so M16 needs none.

---

## 3. Decisions

### Taken by the user

1. **Features are built from a selection of picks.** The user proposed it: *"what about selecting a collection of picks and then generating the surface based on the reflections associated with them?"* The picks say which reflection; nsgeo follows it through the cube between them.
2. **Three kinds of feature: surface, line and body.**
   - **Lines:** accepted with a yes. Pick along a linear feature on a few cuts, and nsgeo draws it in 3-D at its depth.
   - **Bodies (isosurfaces):** *"Let's add them in here."* A body uses the same gesture: nsgeo puts a box around the selected picks and wraps the strong reflections inside it at an adjustable level. The user's reply to that: *"That sounds right."*
3. **Built in 2-D, looked at in 3-D.** The user was unsure where generation should happen. Claude recommended 2-D, and the user accepted the full playback ("sounds good"). Selection already works on the map, QGIS 3.44 gives plugins no 3-D tools, and a view-only scene survives a 3-D engine swap.
4. **A 3D view button on the nsgeo toolbar.** The view it opens shows your picks.
5. **A slice at its depth, following the Slices panel.** It is the one slice the panel is showing; step through depths in the panel and it moves up and down. Confirmed with a yes.
6. **Survey lines and cuts can stand as walls, several at once.** *"The ability to turn on lines or cuts would also be great"*, and *"being able to open multiple could be useful."*
7. **The milestone shape** (playback accepted): two plans, the ParaView export split off into its own issue, and stills from the 3-D view's own "Save as image".

### Calls made by Claude (check these)

1. **Walls follow the profile view and the map selection.** The line or cut open in the profile stands as a wall, and so does every line or cut selected on the map. A single selection still opens the line in the profile; a multi-selection, which does nothing today, puts up several walls.
   - Why: it needs no new controls, and it uses a gesture that is free.
   - The current-layer switch (M15 decision 11) already decides whether the map is selecting lines or cuts.
2. **A pick belongs to at most one feature,** through the reserved `feature_id`. `seq` orders a line's picks.
   - Why: the schema was designed this way, and changing it means migrating authored rows.
   - Making a feature from picks that already belong to another asks before moving them.
3. **Feature definitions are saved as you go, beside the picks; survey layout waits for Save site.**
   - **Storage:** a definition (id, name, kind, grid, parameters, created) lives in a new authored, **non-spatial** `features` table in `site.nsgeo.gpkg`. nsgeo writes it immediately through its loaded layer's provider, as it writes picks. Membership lives on the picks (`feature_id`, `seq`).
   - **The principle:** interpretation (picks, features) is saved as you go; survey layout (grids, cuts) is saved with **Save site**.
   - **Why:** the reviewer found that keeping definitions in `survey.nsgeo.json` while membership is written at once lets an unsaved close split a feature from its picks. A deleted feature would come back empty, and moved picks would point at a feature that no longer exists.
   - **What it costs:** a table with no geometry has no CRS, so a CRS change never rebuilds it, and it needs none of the picks' migrate-and-verify machinery beyond a schema check. It is never edited in QGIS.
   - **The geometry:** built geometry is derived and regenerable, written to the site folder, and carries provenance (cube source, parameters, which picks).
4. **A feature records the cube source it was built from, and rebuilding is explicit.**
   - **The source is This grid's:** the Slices panel's This grid engine for the feature's grid. Whole site engines are never used for features.
   - **Building:** building or rebuilding needs that grid prepared in This grid scope. Otherwise the message M15 uses: "Show Grid 1 in the Slices panel."
   - **Stale:** a feature is marked stale when its grid's This grid source differs from the one it was built from, or when its picks or parameters change. If the grid isn't prepared, its state is "not checked", not stale. Switching scope or grid therefore never marks anything stale.
   - **Showing stale features:** the 3-D view keeps showing the last build, labelled as stale, until you rebuild.
   - **Why:** a scene should not churn while you present it, and a body rebuild costs seconds.
5. **Honesty rules for the builders:**
   - a surface leaves holes where the reflection fades and never smooths over them;
   - tracking never moves more than its window away from the surface interpolated between picks;
   - where a built surface or line misses one of its own picks by more than a sample, that is reported, not hidden.
6. **One grid per feature,** as for cuts. Picks from two grids are refused with a message.
7. **Minimum picks:** a surface needs 3 that are not in a straight line, a line needs 2, and a body needs 1.
8. **Depth is drawn as Z = −depth × stretch, with the ground at 0, and true depth is always kept in the attributes.** "Ground at 0" is in one place, so the later topographic-correction milestone can replace it with an elevation.
9. **Vertical stretch:** one value for the whole scene, adjustable from nsgeo, default ×3 (what the spikes used). The 3-D view's title states it, e.g. "nsgeo 3D · Grid 1 · depth ×3", so a non-specialist is never shown stretched depth as true depth.
10. **Colours:**
    - surfaces are coloured by depth, with one ramp shared by every surface in a grid so depths compare;
    - each line has one strong colour;
    - each body has one colour.
    
    The depth ramp's legend shows in the Layers panel.
11. **The scene is one grid: the one the Slices panel shows in This grid scope.**
    - **What is in it:** that grid's picks, features and walls, its slice, and an extent and camera framed on it. Showing a different grid in the panel moves the scene to it.
    - **Whole site scope:** the scene keeps its last grid and hides the slice. A site slice is one time window, which sits at a different depth in each grid.
    - **Why:** the reviewer found that a site-wide scene breaks the one-plane slice. A flat terrain spans the whole scene, so a slice from one grid would be an opaque plane across every grid, hiding the others' features and walls. Every driving case so far is one grid.
    - Site-wide scenes are a later concern.
12. **The 3-D view is QGIS's own.**
    - nsgeo opens or reuses one view named for nsgeo, and sets its layers, terrain, lighting and camera.
    - Rotating, zooming and "Save as image" are QGIS's.
    - The camera position is not saved; features are, and they are regenerated.
13. **The feature list gets a lavish mockup review before it is built.** It covers making, naming, rebuilding and deleting features, and showing their stale state.

---

## 4. Behaviour

### 4.1 Making a feature

1. Make the picks layer current and select a group of picks with QGIS's Select tool. They can be on survey lines, on cuts, or both.
2. Ask nsgeo for a feature (toolbar or feature list, the builder's call with the mockup) and choose a kind and a name.
3. nsgeo sets `feature_id` (and `seq` for a line) on those picks, records the definition, builds the geometry, and adds it to the map and to any open 3-D view.

You can add picks to a feature, remove picks from it, rebuild it, rename it and delete it. Deleting a feature clears `feature_id` on its picks but never deletes them.

### 4.2 The three kinds

**Surface.** nsgeo interpolates the picks' times over the area the picks span, which gives a guide surface. In each cube cell it looks within a window above and below the guide for the strongest reflection, and puts the surface there. Where nothing passes a strength test, it leaves a hole.

- **Output:** a depth surface coloured by depth, in 3-D and as a depth map on the 2-D map. The spike's mesh-layer form drew both from one layer.
- **Parameters:** window and strength threshold, with defaults.
- **Spike evidence:** the naive version ("strongest reflection between 0.35 and 1.0 m in a box") already read as a bowl. The picks replace the fixed window with a guide that follows the bowl's own dip.

**Line.** The picks are ordered along the feature (`seq`), and the path between them is followed in plan. Along that path, nsgeo follows the reflection within a window around the depth interpolated between neighbouring picks.

- **Output:** a 3-D line at its depth, plus its plan on the 2-D map.
- **The point of it:** to show whether the lower line rises to meet the higher line.

**Body.** A box around the picks in plan, with a margin, spanning their depth range plus a margin. Inside the box: fill, smooth 3×3×3, balance each level, then extract an isosurface at an adjustable level.

- **Output:** a closed surface in 3-D, plus its outline on the 2-D map (the builder may leave the outline out if it adds clutter).
- **Spike timings:** extraction in numpy takes under a second for 33 k triangles, and QGIS draws it in about 1.4 s.
- **Level:** one control, rebuilt on change. Its scale (percentile within the box, or percent of the box's maximum) is the builder's call, stated in the UI.

### 4.3 The 3-D view

- **Opening it:** a **3D view** toggle on the nsgeo toolbar, greyed out until a site is open. It opens nsgeo's 3-D view, or brings it forward if it is already open.
- **What it shows:**
  - picks at their depths;
  - features;
  - the current slice at its depth (4.4);
  - walls (4.5).
  
  Basemaps and the derived grids, lines and marks layers are not draped into the scene, unless the builder finds the grid outline helps.
- **The camera** opens framed as call 11 describes.
- **Live updates:** new or rebuilt features, new picks and stretch changes appear without reopening the view.

### 4.4 The slice

The Slices panel's current slice, for the scene's grid, sits at its depth (centre of its window) × stretch. Stepping through depths in the panel moves it.

- **No slice showing, or Whole site scope:** no slice is drawn (call 11).
- **Opaque:** the slice hides what is below it, which is why there is only one.
- **Mechanism, the builder's call after measuring on Grid 1:**
  - **Draped terrain:** the slice draped on a flat terrain lowered with `setElevationOffset`, with the scene's extent held to the grid. The risk to verify is that re-pointing `SliceLayer`'s data source refreshes the drape without reopening the view.
  - **Mesh sheet:** one sheet covering only cells with data. The spike rewrote 30 k vertices in about 0.6 s; it would have to come in under the "feels live" bar, or move without freezing QGIS.
  - **Rule for either:** the slice never extends past the grid.

### 4.5 Walls

- **Which walls stand:** the line or cut open in the profile view, plus every line and cut selected on the map. Clearing the selection takes those walls down.
- **What a wall shows:** what the profile view would show for it. For a survey line that is its processed radargram; for a cut, its section (M15). The same display gain and depth axis apply.
- **Many walls at once:** walls are opaque. Ten adjacent lines 0.5 m apart make a solid block. A message, or nothing, is fine there; the cost to watch is time and memory, and section 5 sets the limit.
- **Technical risk:** drawing a wall sharply. The spike's vertical polygons in 12 grey classes were legible but banded. Plan 1 opens with a short spike comparing classed polygons with a textured vertical polygon (`QgsPhongTexturedMaterialSettings`), so plan 2's approach is settled before plan 2 starts.

---

## 5. Performance

Measure on Sunnyside Grid 1 (cube 234 × 80 × 100 at 0.2 m):

- **Building a surface:** expected well under a second for the bowl.
- **Building a body:** under a second to extract, about 1.4 s to draw at 33 k triangles.
- **Opening the 3-D view:** target a few seconds.
- **Moving the slice one step:** should feel live.
- **Putting up one wall:** should feel live.
- **Walls at once:** put up ten, and record the time and the memory.

Building a feature must not freeze QGIS. Use a task if it can take more than about 0.2 s.

---

## 6. Goals, non-goals, anti-goals

**Goals**

- Surfaces, lines and bodies built from your picks, rebuildable, stored with the site.
- A 3-D view, opened from the toolbar, that shows your picks, features, the current slice and walls at true relative depth with a stated stretch.
- The bowl reads as a bowl, and the lower line's rise (or not) is visible.

**Non-goals**

- Selecting or picking inside the 3-D view.
- Volume rendering.
- Topographic correction.
- The ParaView export, which gets its own issue.
- Saving a camera or a scene.
- Features across grids.
- Automatic feature detection without picks.

**Anti-goals** (failures even if it technically works)

- A smooth surface over a gap the radar did not see. Holes stay holes.
- A surface that has wandered off the reflection the picks named.
- Stretched depth shown without saying so.
- Something in the scene that isn't real, like the fence reflection, because nsgeo put it there rather than the user.
- A scene that changes under you mid-presentation because a source changed elsewhere.
- Losing a pick's membership, or a pick itself, through feature edits.

---

## 7. Documentation

`docs/guide/getting-started.md`:

- the toolbar table gains **3D view**;
- a new step after cuts covers making a feature from picks, its three kinds, opening the 3-D view, the following slice, walls from selection, the stretch, and "Save as image";
- "Where your data lives" says that features, like picks, are your own work and are saved as you go in `site.nsgeo.gpkg`, and that built geometry is regenerable files in the site folder.

---

## 8. Testing and the walkthrough

Real files first. Synthetic data only where it mirrors them. Each input class needs a test that actually feeds it:

1. **Surface tracking on a real reflector in the fixtures:**
   - the surface passes within a sample of every pick;
   - it leaves holes where amplitude fails the threshold;
   - it never departs from the guide by more than the window;
   - a pick placed on the wrong reflector is reported, not silently honoured or ignored.
2. **Line tracking** along picks on two crossing lines or cuts, including picks given out of order.
3. **Body extraction** in a box, checked against a synthetic sphere's area and volume only as far as that mirrors real data. Also:
   - a box that clips the grid edge;
   - a box over a coverage hole;
   - a level above the box's maximum, which gives an empty body and a message, not an error.
4. **Membership:**
   - picks moved between features (call 2);
   - deleting a feature leaves its picks;
   - picks from two grids are refused;
   - too few picks are refused;
   - a feature made, edited or deleted, then the site closed **without** Save site: the feature and its membership are exactly as last edited (call 3);
   - a CRS change leaves the `features` table untouched.
5. **Staleness** (call 4):
   - Changing the This grid source for a feature's grid, its picks or its parameters marks it stale. The scene keeps the last build, labelled, until a rebuild.
   - Switching to Whole site scope, or showing another grid, never marks anything stale.
   - Building with the grid unprepared gives the message.
6. **The 3-D view:**
   - opening and reusing it;
   - the layers it contains;
   - the slice moving with the panel;
   - walls following the profile and the selection;
   - the stretch, and the title stating it;
   - QGIS 3.44 and 4.2.
   
   Render checks need xvfb plus Mesa. Layer-level checks need nothing extra.
7. **Depth:** Z equals −depth × stretch, with true depth in the attributes, for picks, features and walls alike.

**Walkthrough** on Sunnyside Grid 1, deployed to a fresh QGIS profile before any merge decision:

1. Pick the bowl on three or four cuts and make a surface.
2. Pick the lower line and the higher line on cuts and make two lines.
3. Open the 3-D view.
4. Sweep the slice down through the bowl.
5. Put up walls on two cuts.
6. Judge whether a non-specialist would read the bowl, and whether the lower line's relation to the higher one is visible.

---

## 9. Left to the builder

- The interpolation behind a surface's guide (numpy only; no SciPy in the core), and the defaults for windows and thresholds, which are measured on the real files.
- How a line's path runs between picks in plan.
- The file formats for built geometry (mesh layer, GeoPackage tables or both), within call 3.
- Where the feature list lives, after its mockup review (call 13).
- How stretch is applied per layer type: baked Z, data-defined height, or the mesh symbol's vertical scale.
- How the scene's layer list is kept free of draped basemaps.
- How walls are drawn, after plan 1's spike.
- How the work splits across the two plans, keeping plan 1 to the 3-D view, picks, the slice, surfaces and lines, and plan 2 to bodies and walls, 3–6 tasks each.
