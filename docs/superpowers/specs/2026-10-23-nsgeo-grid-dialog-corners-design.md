# nsgeo grid dialog: corners from the map, from any CRS (#27, #62, #63, and #28)

One change to one dialog. The **New grid** window gets a single corner table that can be filled
three ways (typed, clicked on the map, or read from a polygon), and one **Fit** places the grid.
While the window is open, the map shows which corner is which. Coordinates in any CRS are
converted on the way in. **Digitise on map** goes away.

Mock-up the user chose (option B): `.lavish/grid-dialog-corners.html` in the main checkout
(git-ignored).

---

## 1. What this is for

The user's last real grid set-up, in their words: *"I had gps points as corners and grid polygons
that had been drawn by a colleague. I also had a bunch of other gps points and overlay maps etc."*
They tried both routes in. *"I think I liked the polygon because it did a best fit to what was
there, as opposed to the choose on map which just took two points placed manually, (though this
did give me more control if I wanted it)."* When they used choose-on-map they clicked right on
the GPS corner points, and could tell from the map which point was which corner.

Three things got in the way, one per issue:

- **#27.** On **From polygon**, nothing says which vertex is which. *"Its total guess work as it
  is now."* A wrong guess doesn't fail. It rotates the grid, and every line placed in it, by
  90° or 180°.
- **#62.** Polygons and GPS fixes in EPSG:4326 are normal, and every route into the dialog
  refuses them or adopts an unusable CRS. *"its inconvenient to have to convert them on the fly."*
- **#63.** Clicking on the map gives control but no fit. Typing GNSS corners gives a fit but
  every number has to be typed. *"digitize on map and GNSS corners could be combined so that you
  can pick each GNSS corner from the map if you want and then fit to that."*

**What success looks like:** with the GPS corner points and the colleague's polygons loaded in a
4326 project, the user opens **New grid**, clicks the four GPS corners (or points at a polygon),
presses **Fit**, sees on the map where the grid landed and which way it runs, rounds the size
off, and clicks **OK**. Nothing is reprojected by hand, and nothing is guessed.

---

## 2. Starting state, on `main` at `21e0b5c`

| What | Where | State |
|---|---|---|
| Three tabs | `ui/grid_dialog.py:117-119` | **GNSS corners**, **Digitise on map**, **From polygon**. All three fill the same form below (Id, CRS, origin, azimuth, size, spacing, velocity). |
| Corner fit | `ui/grid_dialog.py:299` `fit_corners` | 4×5 table: corner, local x, local y, world E, world N. Rows with all four cells filled go to `nsgeo.geometry.fit.fit_grid_from_corners` (rigid, no scale, reflection forbidden). It overwrites origin, azimuth **and both sizes** (sizes = local extent). |
| Digitise | `ui/grid_dialog.py:353` `set_digitised`; `plugin.py:1296` `_start_digitise`; `maptools/digitise_tool.py` | Two clicks: origin, then any point along +Y. Sets origin and azimuth. `plugin.py:1315` then sets the grid CRS to the **canvas CRS**, so a 4326 canvas gives a grid OK can never accept. |
| From polygon | `ui/grid_dialog.py:369` `use_polygon`; `lookup.py:261` `corners_from_polygon` | Origin and +Y dropdowns labelled `vertex 0`…`vertex 3`. **Refuses** any geographic layer (`:375`). On success, overwrites the grid CRS with the layer's (`:434`). |
| +Y is not a real choice | `lookup.py:283-300` | Of the origin's two neighbours, only one gives a right-handed frame. The other is refused as mirrored. So the origin choice alone decides the frame. |
| Grid CRS default | `ui/grid_dialog.py:198` | The project CRS. In a 4326 project it is refused ("must use metres, not degrees") and the user must work out a UTM zone. |
| CRS guards | `ui/grid_dialog.py:451` `_crs_scale_error`, `:489` `_validate` | Refuses no authid, non-metre units, or a local scale error over 2% at the origin. Warns over 0.1%. These stay exactly as they are. |
| Modeless lifecycle | `plugin.py:1116` `open_grid_dialog`, `:94` `_finish_with_digitise_tool`, `:355` `unload` | Single instance; work in `finished`; a stranded map tool released on close; `reject()` in `unload`; a `destroyed` guard. Each of these is a past bug with a test. |
| Tests | `tests/qgis/test_plugin_grid_dialog.py` (49 tests), `tests/pure/test_pure_lookup.py` | 15 of them cover the digitise tool and its rubber band's lifetime. |
| User guide | `docs/guide/getting-started.md`, "Step 2: Place a grid" | Describes the three tabs. |

---

## 3. Decisions

### Taken by the user

1. **Layout B: one corner table, no tabs.** Chosen from the mock-up over keeping two tabs.
2. **Digitise on map goes.** Picking corners and fitting them replaces it.
3. **The grid's CRS:** *"uses the project crs if its appropriate otherwise yes utm zone picked
   automatically."*
4. **Size is the user's call.** *"What I found myself doing was adjusting the size to what I
   thought was appropriate … once the best fit layout of the grid was established … I'd prefer
   to choose myself rather than have it make changes for me."* Agreed rule: Fit fills in the
   measured size as a starting point, and once the user has typed a size, a later Fit never
   overwrites it. This is the same "sticks once hand-typed" rule the user chose for #69.
5. **Corners only.** Bearing stakes and points inside the grid as control points: *"Its a cool
   idea but lets leave it out for now."* The table's four rows are always the grid's four
   corners.
6. **A grid whose size differs from the corners stays pinned at the origin corner.** Asked
   whether rounding 20.41 m to 20 m should pin the grid at the origin (the whole 0.41 m at the
   far edge) or centre it over the GPS corners (about 0.2 m at each edge): *"I think pinned at
   the origin corner is right."* Fit therefore always uses the measured size, a typed size
   never enters the fit, and the result does not depend on whether the size was typed before
   or after Fit.

### Calls made by Claude (check these)

These were listed on the mock-up page and the user raised no objection. They are still
Claude's calls, not the user's.

- **C1. Fit only runs when Fit is pressed.** Filling from a polygon, picking, rotating and editing
  cells never re-fit. Until Fit is pressed again, the role tags show the new corners and the
  dashed outline shows the old fit.
- **C2. Picks always snap** to the nearest vertex or point feature of any visible vector layer
  within 12 px, whatever the project's snapping settings. A snap marker shows where the click
  will land. A click with nothing in range gives a free point.
- **C3. The dialog hides while picking**, as Digitise does today, and the QGIS message bar says
  which corner to click next.
- **C4. The automatic CRS never replaces a CRS the user chose by hand**, and never changes an
  existing grid's CRS. The full rule is §4.4.
- **C5. #28 is folded in.** Picking a polygon on the map, and outlining the chosen one, answers
  "which feature is selected". #28's other half (which attribute column names the entries) is
  answered by showing the layer's display name, as `QgsFeaturePickerWidget` already does.
- **C6. Withdrawn.** C6 proposed letting a typed size feed the fit, which centres the grid. The
  user ruled the other way (decision 6).
- **C7. Filling from a polygon does not fit.** It fills the four rows. The user presses Fit.
- **C8. "Corners in" defaults to the project CRS** (EPSG:4326 if the project has none).
  Changing it converts the points already in the table. The same physical points are shown in
  the new CRS, never reinterpreted.
- **C9. A polygon's default origin** is the vertex whose +Y edge points closest to north. Rotate
  changes it.

Added after the builder check (also Claude's calls):

- **C10. The site's own CRS comes first.** The automatic CRS prefers the CRS the site already
  uses (`grids[0].crs`) over the project CRS, when it is usable at the grid's location. This
  matters because `seam_masks` (`nsgeo-core/.../slices/site.py:342`) returns all-False for two
  grids in different CRSs, so a mixed site silently loses edge levelling in the site view. It
  stretches the user's "uses the project crs if its appropriate" to cover the site's other
  grids.
- **C11. Changing the grid CRS by hand keeps the grid where it is on the ground.** Origin E/N
  and Azimuth are converted into the new CRS. Sizes are unchanged. Today the numbers are
  reinterpreted, which can move a grid by kilometres with OK still enabled.
- **C12. Rotate swaps the two Size boxes, typed state included.** A typed length belongs to a
  physical edge, and one Rotate hands that edge to the other axis. This is not changing what
  the user typed: the same edge keeps the same length.
- **C13. "off by" is live.** It is the distance from each filled corner to the matching corner
  of the grid as the form defines it now, recomputed on every change. It never goes stale after
  a size edit or a Rotate. The status line's RMS stays the last Fit's.
- **C14. Mirrored corners are refused, not fitted.** With three or more corners filled, a
  left-handed set (for example +X and +Y picked the wrong way round) is refused with a message
  naming the likely swap. It is never fitted into a plausible frame with a large RMS.

---

## 4. Behaviour

### 4.1 The dialog

Top to bottom (see the mock-up, option B):

- **Corners** group:
  - **Corners in** (`QgsProjectionSelectionWidget`). The coordinate columns are headed
    **lon, lat** when it is geographic, **E, N** otherwise.
  - The table has four fixed rows: **origin**, **+X**, **+X+Y**, **+Y**. Its columns are the
    coordinates, **from**, a **Pick** button, and **off by**.
    - **from** says where the point came from: `typed`; for a pick, the snapped layer and
      feature (by the layer's display expression), or `free click`; for a polygon,
      `v2 · NE` (vertex index and compass position, §4.6). Editing a cell by hand turns that
      row's **from** into `typed`.
    - **off by** shows the distance in metres from that corner to the matching corner of the
      grid as the form defines it now (C13). It is blank while that grid can't be drawn
      (§4.8).
  - Buttons: **Pick all**, **⟳ Rotate**, **Clear**, **Fit**. A status line under them shows
    `rigid fit RMS 0.09 m from 3 corners`, any fit error, and today's mirrored-or-not-square
    caution.
  - A row under a divider ("or fill all four from a polygon"): a polygon layer combo, a feature
    picker, **Pick on map**, **Fill**.
- The existing form: Id, CRS (with its hint), Origin E/N, Azimuth, Size X/Y, Default spacing,
  Velocity. Under Size, a hint appears when the measured size differs from a typed one:
  `the corners measure 20.41 × 19.87 m · your size is kept`, with a small **Use these** button
  that copies the measured size in and clears the typed state.
- OK / Cancel, with OK's rules unchanged.

The tab widget, the local x/y columns, the **Digitise on map** tab, `digitise_requested`,
`set_digitised` and the separate **Use polygon** path all go.

### 4.2 Fit

Pressing **Fit**:

1. Settles the grid CRS (§4.4) from the filled corners.
2. Transforms every filled row from **Corners in** into the grid CRS (§4.5).
3. Works out the local frame from the corners alone (decision 6). Typed sizes play no part.
   For each axis, the length is the mean of that axis's measured edges between filled rows:
   - X edges: origin → +X, and +Y → +X+Y
   - Y edges: origin → +Y, and +X → +X+Y

   The corners' local positions are then (0, 0), (sx, 0), (sx, sy), (0, sy). The fitted grid
   passes through the corners as closely as a rigid rectangle can, and its origin is the
   fitted origin corner. A typed size then extends from that origin, which is what pins the
   grid there.
4. Refuses, with a message in the status line and nothing changed, when:
   - fewer than two rows are filled; or
   - an axis that a filled row needs has no measured edge. For example, only the origin and
     +X+Y are filled: "pick a corner next to the origin"; or
   - three or more corners are filled and they are left-handed (C14).
5. Runs `fit_grid_from_corners` and sets Origin E/N and Azimuth.
6. Sets each Size box that has not been typed to its measured length, where that axis was
   measured. An axis that was not measured is left alone.
7. Fills **off by** and the status line.

The fit maths stays in `fit_grid_from_corners`. Steps 3 and 4 are new pure code (§5).

### 4.3 Typed sizes

A Size box counts as **typed** once the user changes it (typing or the spin arrows). A box set
by Fit or **Use these** does not count. When the dialog opens on an existing grid, both sizes
count as typed. **Use these** clears the typed state of both boxes.

### 4.4 The grid's CRS

The grid CRS widget is **automatic** until the user picks a CRS in it by hand. It is never
automatic when the dialog edits an existing grid. While it is automatic:

- **At open:** the first of these that is usable at the map canvas's centre (C10):
  1. the site's CRS (`grids[0].crs`), when the site has grids;
  2. the project CRS;
  3. the UTM zone of the canvas centre (WGS 84, EPSG:326zz north, 327zz south).

  If there is no usable canvas centre, it stays on the project CRS with today's hint, plus
  "a UTM zone will be picked when you fit corners".
- **At every Fit:** decided again, the same way, from the centroid of the filled corners.
- **By hand:** when the user picks a CRS, Origin E/N and Azimuth are converted into it (C11).
  The azimuth is converted by transforming the origin and a point 100 m along +Y, then taking
  the bearing between them. Nothing is converted while the origin is still (0, 0).
- "Usable" means it passes `_validate`'s three checks (authid, metres, scale error at most
  `CRS_SCALE_REFUSE`) at that location. A CRS that only draws the 0.1% warning is still usable,
  and is kept.
- When the dialog picked a UTM zone, the hint says so and why, for example `picked for you: the
  project CRS (EPSG:4326) is in degrees`.

The pure part is `utm_epsg(lon, lat) -> int | None`. Zone = `floor((lon + 180) / 6) + 1`, wrapped
into 1–60. It returns `None` beyond ±84° latitude. The Norway and Svalbard exceptions are not
needed: they are an MGRS convention, and a standard zone's scale is fine there.

### 4.5 Coordinate conversion

Every conversion uses `QgsCoordinateTransform` with `QgsProject.instance()`'s transform context:

- a pick: canvas CRS → **Corners in**
- a polygon's vertices: layer CRS → **Corners in**
- a change to **Corners in**: old → new, for every filled row
- Fit: **Corners in** → grid CRS
- the overlay: grid CRS or **Corners in** → canvas CRS

A failed transform (`QgsCsException`) puts a message in the status line and leaves the row or
field as it was. It is never swallowed silently. Values show 8 decimals in degrees and 3 in
metres.

### 4.6 From a polygon

Pick a polygon by clicking it (**Pick on map**: the topmost visible polygon feature under the
click, from any polygon layer, which then sets the layer combo and the feature picker) or with the
combos. **Fill**:

1. Reads the first ring of the first part and drops the closing vertex. Anything other than four
   vertices is refused with today's message.
2. Converts the vertices to **Corners in**.
3. Assigns the four roles so the frame is right-handed (the rule in `corners_from_polygon`), with
   the origin at the vertex whose +Y edge points closest to north (C9).
4. Labels each row `v<i> · <compass>`, where compass is the vertex's 8-way direction from the
   ring's centroid.

**⟳ Rotate** moves every role one corner round the frame, keeping it right-handed. Four presses
return to the start. It works the same whichever way the rows were filled. The **from** labels
travel with their points, and the two Size boxes swap, typed state included (C12).

### 4.7 Picking on the map

A new one-click map tool replaces `DigitiseGridTool`:

- **Snapping (C2):** its own `QgsMapCanvasSnappingUtils` with its own `QgsSnappingConfig`
  (enabled, all layers, vertex type, 12 px). A `QgsSnapIndicator` shows the match as the cursor
  moves. The project's snapping settings are neither read nor changed.
- **Pick** on a row: the dialog hides. The message bar says `Click the +X corner. Right-click or
  Esc cancels.` One click fills that row, then the dialog returns.
- **Pick all:** walks origin → +X → +X+Y → +Y, with the message bar showing `(n of 4)`.
  Right-click skips the current corner and leaves its row as it was. Esc stops and keeps what
  was picked. After the last corner, the dialog returns. It does not fit (C1).
- **Pick on map** for a polygon: the same tool in a feature mode, one click.
- Switching to another map tool cancels, as Digitise does today, and the dialog always comes back.
- The message is removed from the message bar when picking ends, however it ends.

Every lifecycle rule `plugin.py` applies to the digitise tool carries over to the new tool:
release a stranded tool on close, `unload` mid-pick, re-showing a hidden dialog when **Add grid**
is clicked again, and giving every canvas item back to the scene. The tests that pin those rules
carry over rather than being deleted.

### 4.8 The map overlay

While the dialog exists, whether shown or hidden mid-pick, the map shows:

- a marker and a role tag on each filled row's point, for example `origin`, or
  `origin · v0 SW` for a polygon vertex;
- the chosen polygon's outline, while a feature is chosen;
- the grid as the form defines it right now, as a dashed outline with an arrow from the origin
  along +Y. It is drawn only when the grid CRS is usable, the origin is not (0, 0) and both
  sizes are above 0.

It is redrawn when a row, the form's origin, azimuth, size or CRS, **Corners in**, or the canvas
CRS changes. It is removed when the dialog finishes, however it finishes, and on `unload`. Every
canvas item is taken back off the scene, following `digitise_tool.py`'s `dispose()` rule. The
builder chooses how it is drawn (rubber bands, vertex markers, one custom `QgsMapCanvasItem`).
Nothing is added to the project or the layer tree.

---

## 5. Where the code goes

- **Pure, Qt-free, in `nsgeo_qgis/lookup.py`** (already under CI's mypy run):
  - `utm_epsg`
  - the local-frame and refusal rules of §4.2 steps 3–4, returning the local positions and
    measured sizes
  - role assignment and the default origin for a ring
  - Rotate
  - compass labels

  `corners_from_polygon` is either reused or replaced. If it is replaced, delete it with its
  tests.
- **`ui/grid_dialog.py`:** the table, the CRS rules, the conversions and the typed-size state.
- **`maptools/`:** the pick tool.
- **The overlay:** a small class of its own, owned by the dialog, with a `dispose()`.
- **`plugin.py`:** `_start_digitise` is replaced by the pick flow, and
  `_finish_with_digitise_tool` is generalised.
- **`nsgeo-core`:** no changes.

---

## 6. Goals, non-goals, anti-goals

**Goals**
- A 4326 polygon or 4326 GPS points give a correct grid in a UTM zone, with no reprojection by
  hand.
- It is always visible on the map which corner is the origin and which way +Y runs.
- One way to place a grid: four corners, then Fit.

**Non-goals**
- Control points other than the four corners (user's ruling).
- Showing which coordinate operation QGIS chose. The project's transform context decides, as
  everywhere else in QGIS.
- Auto-fitting, and reading corner roles from attribute names such as "SW".
- Saving the picked corners in the site file. As today, only the grid is saved.
- Making grid velocity optional. That is #4.

**Anti-goals** (each has happened in this plugin before)
- A convincing fit on wrong numbers, such as degrees treated as metres, or a mirrored frame that
  reports a small RMS.
- The dialog changing what the user set: a typed size, or a CRS chosen by hand.
- A pick flow that can leave the dialog hidden with no way back.
- Canvas items left in the scene after the dialog closes.

---

## 7. Documentation

Rewrite "Step 2: Place a grid" in `docs/guide/getting-started.md` for the one corner table:
typing, Pick and Pick all, Fill from a polygon, Rotate, Fit, the automatic CRS, and the size rule.
Remove every mention of **Digitise on map** from user-facing text. That includes
`nsgeo_qgis/metadata.txt` (`about` and the changelog line) and the root `README.md`. The
0.1.0 release notes stay as they are, because they are history.

---

## 8. Testing and the walkthrough

**Pure** (`tests/pure/test_pure_lookup.py`):
- `utm_epsg`:
  - zone edges at 6° boundaries
  - ±180°
  - the southern hemisphere
  - beyond ±84°
- the local frame and refusal rules:
  - two, three and four corners
  - an axis that is needed but unmeasured
- the fit does not depend on typed sizes: the same corners give the same origin and azimuth
  whatever the Size boxes hold (QGIS tier)
- role assignment:
  - clockwise and anticlockwise rings
  - the default origin at several azimuths
- Rotate:
  - four presses return to the start
  - the frame stays right-handed

**QGIS tier**:
- **A UTM rectangle with known corners**, converted to 4326 and stored as a 4326 polygon layer.
  In a 4326 project, Fill and Fit give the UTM zone, origin, azimuth and sizes to within 1 mm.
  This replaces `test_use_polygon_refuses_a_geographic_crs_layer`.
- **Picks:** picks on a 4326 canvas land in the table converted correctly. A pick near a point
  feature snaps to it, and a pick away from everything is free.
- **Pick all and cancelling:** right-click skips a corner, Esc stops, and switching tools
  cancels. Each of these brings the dialog back and clears the message bar.
- **The automatic CRS rule:**
  - a usable project CRS is kept
  - a 4326 project gets a UTM zone
  - a UTM project far outside its zone gets the right zone
  - a CRS chosen by hand is never replaced
  - an existing grid's CRS is never changed
- **Typed sizes:**
  - a typed size survives Fit
  - **Use these** clears the typed state
  - an existing grid opens with both sizes typed
- **"Corners in":** changing it converts the points already in the table, and converting back
  restores them.
- **The overlay:** its items appear and are redrawn on edits. Nothing is left in the canvas scene
  after OK, Cancel, a close mid-pick, or `unload`.
- **Lifecycle:** every digitise lifecycle test is ported to the pick tool.

The local qgis suite must also be run with the `sys.excepthook` / `sys.unraisablehook` check, so
that a slot exception cannot pass locally and abort CI.

**Walkthrough** (deploy to a new QGIS profile, results recorded on an Artifact with `db`). It
uses the user's own data: the GPS corner points and the colleague's grid polygons, in a 4326
project and then in a UTM project. The checks cover:
- each way to fill the table, and Rotate
- the map overlay
- the size rule
- the automatic CRS
- that the resulting grid lines up with the GPS points and the overlay maps

The user's data is private and is never committed.

---

## 9. Left to the builder

- How the overlay is drawn, and its colours. The mock-up uses magenta role tags and a blue dashed
  outline.
- Which way Rotate turns.
- Whether `corners_from_polygon` is reused or replaced.
- Exact wording of messages, inside the rules above.
- The plan's task split. Roughly five or six tasks: pure helpers; table and Fit; the CRS rules
  and conversions; the pick tool and plugin wiring; the overlay; polygon fill, docs and the
  walkthrough.
