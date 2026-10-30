# nsgeo M15: cut anywhere, a vertical section along any line you draw

You draw a line on the map and the profile view shows the cube's vertical section beneath it. It works the way a survey line already does: hover to preview, select to open, a cursor that tracks between map and profile, and picks. The cuts are stored, so M16's 3-D scene can stand them upright later.

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

**Order.** This is M15; the 3-D scene is M16. They are separate milestones, at the user's request. M15 runs alongside M14 (migration, in progress in another session), not after it. Building waits until #67 (grid-aligned profiles, branch `nsgeo-grid-profiles`, built, walkthrough pending) has merged, because #67 rewrites the profile view this milestone extends.

---

## 2. Starting state (main at `7069959`, with #67 at `828e8e7` unmerged)

- **Profiles come only from recorded lines.** `ProfileDock._show_line` is built around a `Line`: its header, its `StepStack` (`session.stack_for`), channels, the difference view, the time cutoff and velocity fits.
- **The map link** (`map_link.py`):
  - Hover works through `QgsMapCanvas.xyCoordinates` with a 50 ms dwell (`HOVER_DWELL_MS`), so it never takes the canvas from the active tool.
  - Selecting a feature in the `lines` layer opens it (`_on_selection` → `session.open_line`).
  - Cursor tracking relies on one fact: **the line geometry's vertex index is the trace index** (`_track_displayed_line`).
  - The session keeps `current_key` (the working line) apart from `preview_key`. Writes such as `add_pick` refuse anything but the working line.
- **Picks** (`session.Pick`, the `picks` table in `layers.py`):
  - Fields: `line_key`, `trace`, `time_ns`, `distance_m`, `depth_m`, `velocity_m_ns`, `stack_json`, `note`, `created`, `feature_id`, `seq`.
  - Time is the truth. A pick's map position is written once (`_pick_point`) and never recomputed.
  - `picks` is the only authored table. It gets a migrate-and-verify rebuild (`_rebuild_picks`) and a backup (`_recover_picks_backup`).
- **The site GeoPackage's rules** (`layers.py` docstring):
  - `grids`, `lines` and `marks` are derived and read-only. Picks are authored.
  - Writes go through the loaded layer's provider.
  - Known issues: unsaved edits in the picks layer are lost when a CRS change rebuilds it (#22). Moving the `.gpkg` alone loses its `-wal` changes (#23).
- **Slices** (`slices_engine.py`):
  - One `SliceEngine` holds one source: a `SourceChoice` (grid, preset, transform, line keys) plus a `Resolution`.
  - Preparation (load, preset, transform) is the expensive step. A resident cube is built on demand (`SliceEngine.cube`) and is "a latency optimisation, never a capability".
  - The fill radius is a view setting.
  - The Slices panel has a **This grid** scope and a **Whole site** scope (M12).
- **Core geometry:**
  - `CubeFrame` (`nsgeo/slices/frame.py`) maps world to frame-local metres, azimuth included (`to_local`).
  - The flat cell id is `iy * nx + ix`.
  - `fill` (`nsgeo/slices/fill.py`) fills one level.
- **Test data:** the real-data fixtures are `nsgeo-core/tests/data/local/FILE__001`–`010`. The Sunnyside site used in the spike is at `~/nsgeo-m4-check/Sunnyside/`, with raw DZTs on `/mnt/DataStorage/VISR/Sunnyside_2023/`. Grid 1 is 20 × 16 m at an azimuth of 10.497°, with 40 lines 0.5 m apart along grid y.

---

## 3. Decisions

### Taken by the user

1. **A separate milestone (M15).** It comes before the 3-D scene (M16), runs alongside M14, and is built after #67 merges.
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

### Calls made by Claude (check these)

1. **Velocity fitting is off on cuts.**
   - Why: a hyperbola fit assumes the profile crosses the target squarely. A cut at a slant shows a wider hyperbola and would return a wrong velocity without any warning.
   - What the user sees: the **Velocity** button is greyed out while a cut is open, with a tooltip saying why.
2. **A pick on a cut says it came from a cut, and from which cube.**
   - Why: line picks sit on recorded traces, cut picks on filled-in data, and the user must be able to tell them apart later.
   - How: `stack_json` carries the cube's provenance (preset, transform, line keys, cell, fill radius) in place of a line's stack. The key says it is a cut (see 4.6).
3. **Deleting a cut never deletes its picks.** A pick whose cut no longer exists stays on the map, at the position it was written to. That covers a deleted cut, and a cut that was never saved before the site closed, since picks go straight into the GeoPackage while cuts wait for **Save site**. Selecting such a pick says its cut is gone and opens nothing.
4. **A redrawn cut is a new cut,** with a new id and the next default name. The old cut's picks stay with the old cut, so they become orphans if it is deleted (call 3). Carrying picks across to a redrawn path is not attempted.
5. **A cut is read in the order it was drawn.** Distance 0 is the first click, at the profile's left. A cut is never mirrored, unlike #67's reversed survey lines.
6. **A cut's grid is the grid under its first vertex.** A first click outside every grid is refused, with a message. The part of a cut beyond its grid's edge shows as blank columns.
7. **The section shows every time level,** with no slice-thickness averaging. Its horizontal fill uses the Slices panel's fill radius for that grid, so a cut and a slice at the same depth agree where they cross.
8. **The section maths lives in `nsgeo-core`, numpy only,** and returns each column's world position. M16 reuses it to stand cuts upright.
9. **Finishing a cut opens it in the profile.** The user drew it in order to see it.
10. **"The cube the Slices panel uses" means the scope on screen.** The panel can hold two sources for one grid at once: This grid's engine, and Whole site's per-grid engines, which stay prepared after you leave Whole site. They can differ in transform, cell and fill radius.
    - **This grid scope:** a cut on the grid being shown reads that grid's engine. A cut on any other grid gets the 4.4 message.
    - **Whole site scope:** a cut reads its grid's site engine, using that engine's transform, cell and fill. It does **not** apply the site view's per-depth normalisation (`SiteEngine._shown`'s `a·fill(v)+b`, re-measured for every window).
    - **Why no normalisation:** it balances grids against each other. Applied to a section, it would become a depth-varying gain that depends on which other grids are included, and it would need every included grid binned at every level. Depth balance on a profile is the display gain's job.
    - **What the title says:** in Whole site scope it reads "site view, not normalised", so a cut is never mistaken for the normalised site slice.

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
- **Cursor tracking:** works both ways along the cut, exactly as for lines.
- **The working item and the mode are separate.** Making another layer current while a cut is open leaves the cut open and working. Hovering then previews lines, and selecting a line opens it, just as it would replace an open line today.
- **The profile shows:**
  - across: distance along the cut, in metres;
  - down: time, with the depth axis lines already get, at the grid's velocity;
  - the title: the cut's name, its grid and its length.
- **No marks** for bends or crossings (decision 5).
- **Display gain** applies as for a line. Processing, difference, channels and the time cutoff do not apply. Their controls are hidden or greyed out while a cut is open.
- **#67's per-grid ruler and its held view** do not apply to a cut. A cut opens fitted to its own length.

### 4.4 When there is nothing to show

If the Slices panel's current scope has no prepared source for the cut's grid (call 10), the profile names the cut and its grid and says what to do. For example: "Cut 3 is on Grid 1. Show Grid 1 in the Slices panel to see it." Nothing builds silently. If the panel changes source or scope (preset, transform, lines, cell, fill or scope), an open cut redraws from the new one or shows this message.

### 4.5 Picks on a cut

- Pick mode works on an open cut as on a line. Picks go into the same `picks` table.
- `distance_m` is the distance along the cut. `depth_m` and `velocity_m_ns` are filled as for a line.
- The map position is the point on the cut at that distance, written once.
- Selecting a cut's pick on the map opens the cut and puts the cursor on it, as `_jump_to_feature` does for line picks.
- A pick whose cut no longer exists follows call 3.

### 4.6 Identity

A cut has a stable id that never changes when it is renamed. Its session key cannot collide with a line key, since line keys are file paths. Picks reference it through `line_key`. The key format is the builder's call.

---

## 5. Performance

- **Hovering** over a cut whose grid is prepared should feel like hovering over a line. The section is small: Grid 1's cube is 234 levels × 80 × 100 cells, and a 12 m cut at half a cell is about 120 columns.
- **The expensive step** is getting a cube for the grid. Preparation is about 0.9 s for 24 lines, followed by binning. If a cut needs a resident cube the engine doesn't hold, that work must not freeze the canvas on hover.
- **Measure, don't guess,** on Grid 1:
  - the first preview after the panel has prepared the grid;
  - a repeat preview;
  - the redraw after the panel changes its fill radius.

---

## 6. Goals, non-goals, anti-goals

**Goals**
- Draw a cut and see its section beside the map, with cursor tracking, on any grid with a prepared source.
- Store cuts with the site, so they can be reused later and survive a CRS rebuild (their layer is derived, so it is simply refilled).
- Picks on cuts that can be told apart from line picks.
- Section maths in the core, ready for M16.

**Non-goals**
- The 3-D scene, curtains, picked surfaces and isosurfaces (all M16).
- Cuts across more than one grid.
- Processing on a cut.
- Marks for bends or crossings.
- Topographic correction.
- A site-scope cube for cuts beyond whatever the panel's site scope already prepares for the cut's grid.

**Anti-goals** (failures even if the feature technically works)
- A cut that quietly shows a different cube from the slices. The user would compare a section and a slice and get contradictory answers.
- A pick from a cut that, months later, cannot be told from one on a recorded trace.
- Losing a drawn cut without warning: closing with unsaved cuts must prompt, and a CRS rebuild must refill them.
- A pick losing the way back to a cut that still exists, for example after a rename.
- A velocity from a slanted cut presented as if it were sound.
- A profile cluttered with markings the user did not ask for.

---

## 7. Documentation

`docs/guide/getting-started.md`:
- **The toolbar table** (§2) gains **Cut**.
- **A short step after "Make a pick"** explains three things:
  - drawing a cut and reading it;
  - that a cut needs its grid prepared in the Slices panel;
  - that the map works on cuts while the cuts layer is current, and on lines otherwise.
- **§4, Where your data lives:**
  - `survey.nsgeo.json` holds the cuts, and **Save site** writes them;
  - the GeoPackage's **cuts** layer is redrawn from it and is read-only, like grids and lines;
  - a pick on a cut stays on the map if its cut is deleted.

The help-pages branch is separate and is not edited here. Note the new tool in its ledger.

---

## 8. Testing and the walkthrough

Real files first. Synthetic data only where it mirrors them. Each of these input classes needs a test that actually feeds it:

1. **A cut drawn exactly along a recorded line.** Its section matches the cube's values in the cells that line binned into, level by level. This is the anchor test.
2. **An oblique cut on a rotated grid** (Grid 1's 10.497°, or a fixture frame at a non-zero azimuth). Columns land in the right cells; checked against `CubeFrame.to_local`, not against a copy of the code under test.
3. **A cut that runs past its grid's edge,** a cut along a gap between lines, and a cut through a coverage hole. These give blank columns, or filled ones within the fill radius, never another grid's data.
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
6. **Draw tool and storage.**
   - A finished cut marks the site unsaved. **Save site** writes it, and reopening restores both the cut and its layer.
   - Closing with unsaved cuts prompts.
   - Esc leaves nothing behind.
   - The cuts layer cannot be edited in QGIS.
7. **No prepared source** gives the message, not a silent build.
   - A change of panel source redraws an open cut.
   - **This grid scope:** a cut on a grid other than the one shown gets the message, even when a site engine for its grid is still prepared.
   - **Whole site scope:** the section equals the site engine's filled values, without normalisation, and the title says so.
8. **Velocity is greyed out** on a cut and comes back on a line.
9. **Preview against working state.** Hovering a cut while a line is the working line never lets a write reach the cut, the same guard `add_pick` has.
10. **The current-layer switch** (decision 11), on Grid 1's real 0.5 m line spacing:
    - **Cuts layer current:** with the pointer settled on a cut within reach of a survey line, the profile stays on the cut.
    - **Lines layer current:** the same spot behaves as today.
    - **Changing the current layer** mid-hover never leaves a stale preview.
    - **Turning the Cut tool on** makes the cuts layer current.

**Walkthrough** on Sunnyside Grid 1, deployed to a fresh QGIS profile before any merge decision:
- draw a cut along the lower line, through to the higher line;
- read its depth against the bowl;
- pick it;
- redraw it as a new cut, delete the old one, and confirm the old picks stay on the map.

---

## 9. Left to the builder

- How the session represents a cut: a kind of line, or a parallel source the profile dock can show. The dock is currently built around `Line`. Pick whichever keeps one code path for hover, select, cursor and picks, and does not grow two copies of every feature.
- How cuts are laid out in `survey.nsgeo.json` (a schema addition: say whether `schema_version` moves), the `cuts` table's fields beyond an id and a name, and the key format.
- How the tool is built: a `QgsMapToolCapture` subclass, or nsgeo's own tool with snapping.
- Where renaming and deleting live in nsgeo's UI. Next to the site's grids and lines in the survey panel is the obvious place.
- The column spacing, as long as it is at most half a cube cell and each column has an exact map position.
- Whether the section reads a resident cube or streams levels, within section 5's limits.
- How a cut's grid is recorded: stored at draw time, or recomputed.
- The cuts layer's style and legend position.
