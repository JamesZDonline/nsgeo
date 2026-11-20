# nsgeo GPS lines (M17) — design

Place GPR lines by the RTK GPS track that the GSSI controller records in a `.DZG` beside each
`.DZT`, so that a survey can be walked without tapes. From M17b, GPS lines come in through **Add
data ▾ ▸ GPR…** into a grid: an existing one, or a new one fitted around their tracks (decision
14). An outline, with holes, clips a grid's slices to any shape. M17a, built first, imports GPS
lines unattached.

Answers #134's "to decide" list: use 1 (free GPS lines) and use 3 (lines placed by GPS inside a
slice area) are in; use 2 (a GPS track drawn beside a tape placement as a check) is dropped. Four
milestones, M17a to M17d (§9; relettered on 2026-11-17, decision 14). Builds on the line-editing
bundle (#35, #64, #29; branch `nsgeo-line-editing`), which was not yet merged when this was written.

---

## 1. What this is for

In the user's words: *"the dream is that one could do a grid without the tapes and with
supplemental lines in arbitrary directions."*

**Why.** Tape grids are imprecise in practice. Laying one out "can be imprecise with tape measures
on uneven ground with students who are still learning", and most of the grids the user has tried
so far are not square. The wheel reads short on lumpy ground, and the cart gets lifted around
obstacles. The user trusts the RTK track over the tapes, which is the appeal: **GPS placement is
the new normal for these surveys, not a check on the tapes.**

**What the test survey shows** (§2). Placed as a tape grid would place it, the traces sit a median
0.31 m, a 95th percentile 0.78 m, and at worst 4.07 m from where the RTK track puts them. Almost all
of that is along the lines: start points scattered by about ±0.5 m on a baseline about 1.8° off
square, a wheel reading 1.5–3% short, and the cart carried 1.5–2 m past obstacles. Across the lines
the error is small (median 0.11 m), which is ordinary walking wander.

**Success.** On the 60-line survey in `packages/nsgeo-core/tests/data/local/with-dzg/`, the user
imports the files into a new grid fitted around their tracks, with no tapes laid out, and sees every
line on the map along the path it was walked. They outline the grid if they want, and get slices of
it in the Slices panel like any grid's. (Decision 14 replaced the first version: import unattached,
then fit an area and move the lines into it.) Lines with no RTK fix for a stretch
still place, and the user can see where that happened.

---

## 2. What the files contain

Measured on the 60 lines `FILE__001`–`FILE__060` in `tests/data/local/with-dzg/` (gitignored; a
different survey from the ten older local `FILE__001`–`010`, same HS350 settings). Recon scripts
were throwaway; every number here can be re-derived from the files.

- **Three files per line, matched by stem:** `.DZT` (data), `.DZG` (GPS log), `.DZX` (the sidecar
  nsgeo already reads: scan range, user marks).
- **The DZG holds exactly two sentence types, in pairs:** `$GSSIS,<trace>,-1` followed by one
  `$GNGGA`. Nothing else: no RMC, no GST, no other talker. All 2,999 NMEA checksums are valid.
- **`<trace>` is the 0-based DZT trace index.** It runs from early in the line to the last trace
  (`n_traces - 1`, occasionally `n - 2`), and matches the DZX scan range. The pairing of fix to trace
  is exact; no clock matching is needed or possible (the second field is always `-1`, so the
  controller records no time of its own).
- **Fix quality:** all 2,999 fixes are RTK fixed (GGA quality 4). HDOP 0.5–1.0. No dropout exists
  in any file, so the dropout behaviour of §5.3 has no real example yet.
- **Rate:** one GGA per second (UTC time steps of exactly 1.0 s while walking). At the median
  walking speed of 0.64 m/s that is a fix every ~0.6 m of line (p95 1.05 m, max 1.32 m), every
  14–62 traces.
- **Pauses leave nothing to clean up.** When the cart stops, the log skips ahead in time (gaps up
  to 74 s) and never repeats a trace number. Trace numbers only rise.
- **The first fix arrives late:** at trace 1–40 (median 20), up to 0.67 m into the line. The start
  of every line must be extrapolated. The last fix is at the last trace.
- **The wheel:** 60 traces/m (`unitsPerScan` 0.016667). Over the fixed span, GPS path length is
  1.02–1.03× the wheel distance (median 1.0298).
- **Slips and lifts are real and the GPS sees them.** `FILE__011` has 1,560 traces (26.0 m by
  wheel) on a 30 m path: the wheel slipped repeatedly (stretches where the GPS moved ~0.5 m in a
  second while the wheel counted 0.1 m). `FILE__016` and `FILE__028` moved 1.5–2 m while the wheel
  barely turned, exactly at the user's DZX marks: the cart was lifted past obstacles.
- **Altitude** is in every GGA (with the geoid separation). The site has ~1.3 m of relief.
- **The survey itself:** one ~30 × 30 m area, 60 zigzag lines (odd files one way, even the other),
  0.496 m apart by GPS, bearing 3.8°. The user lays lines 0.25 m in from the edge at 0.5 m spacing,
  so each line runs down the middle of its own 0.5 m strip (#69's default).
- **The antenna:** the GPS antenna sits on a mount directly over the GPR antenna's centre (user).
  Even so, the logged positions are about 24 cm behind the radar along the direction of travel;
  §7 has the measurement.
- **Walked lines leave real gaps.** Neighbouring lines are a median 0.49 m apart but 0.86 m at the
  95th percentile and up to 1.58 m; 12% of samples are more than 0.75 m apart, and lines sometimes
  touch. At the slices' default max distance (0.75× spacing = 0.375 m) a GPS-placed slice of this
  area is 3.5% holes inside the area, against 0.09% for the same lines placed by tape. They stay
  visible (decision 12).

**What we do not have:** other NMEA talkers (`$GPGGA`) or sentences, a multi-channel DZT with a
DZG, or a time-triggered (no wheel) line with a DZG. *(Updated 2026-11-13: a second GPS survey now
sits in `tests/data/local/grid2/` — 60 lines, 2,523 fixes, same structure — and it holds the first
real dropouts, see §15.)*

---

## 3. Decisions taken in brainstorming

These are the user's, in the order they were made.

1. **GPS is trusted over tapes.** Use 2 of #134 (draw the GPS track beside a tape placement to
   check it) is not wanted.
2. **GPS lines are imported unattached,** each placed from its own DZG, with no grid chosen first.
   *Superseded from M17b by decision 14: GPS lines go into a grid at import. M17a, built before it,
   imports them unattached.*
3. **The slice area is made afterwards.** It need not be rectangular. The cube behind it stays
   rectangular, just big enough to hold the outline, with cells outside the outline left empty.
   *From M17b the grid is made at import (decision 14); the outline is still drawn afterwards.*
4. **Lines join an area by being moved there** with Move to grid ▸ (line editing), not by falling
   inside it. *From M17b lines join a grid at import (decision 14); Move to grid ▸ still moves them
   later.*
5. **Fit to these tracks** stays in: select lines, press it, get a rectangle lined up with them,
   then reshape it. Its edges sit half a spacing outside the outer lines, matching the user's
   practice (§2). *From M17b the same fitting makes the new grid at import (decision 14).*
6. **No antenna-offset setting:** the mount is centred. *Reopened by the delay measurement (§7):
   the data shows a ~24 cm along-track shift regardless, so some along-track correction is needed;
   settled in decision 10.*
7. **When the RTK fix drops** (the user had no plan of their own and accepted this proposal):
   - only RTK-fixed positions (quality 4) are used; float and plain fixes are ignored;
   - the wheel bridges the gap: traces between two good fixes are spaced by trace count along a
     straight line between them, exactly what happens between ordinary fixes;
   - bridged stretches are drawn differently on the map (dotted, say) and named in the import
     summary ("FILE__012: 8.4 m without RTK fix");
   - a line's ends beyond its first and last good fixes carry on by wheel in the direction the line
     was heading; beyond a limit (about 2 m) the line is flagged;
   - a line with no fixed position at all cannot be placed by GPS: the import says so, and it can
     still be imported into a tape grid the usual way;
   - tests switch stretches of the real files to float or plain fixes, so test data still looks
     like what the cart writes.
8. **Profiles:** GPS lines in an area share the area's ruler the way #67 made tape-grid profiles
   share one. Each trace is placed by its position along the area's axis, so the zigzag lines line
   up (reversed lines mirror for free). A line at an angle to the area, or a line in no area, shows
   distance walked along its own path.
9. **Calls the user reviewed and accepted in chat:**
   - lines at an angle go into slices like any other line; evening out how differently the antenna
     sees a feature from each direction belongs with de-striping (#47), later;
   - altitude is read and stored with each line, unused for now (topographic correction later);
   - lat/long are converted into the project CRS if it is usable, else the automatic UTM zone, the
     same rule the grid dialog uses (#62). (Once a site has a CRS, every import uses that: C12.)
   - the existing tape import is unchanged: importing into a tape grid still places by the tapes,
     even when a DZG sits beside the DZT. GPS placement comes through its own **Import GPS
     lines…** action;
   - milestones (§9; three since decision 11). M17 stays where the roadmap puts it, after M15 and M16, unless the user
     says otherwise.
10. **The along-track correction is destagger's job (#47), for tape and GPS lines alike** (after the
    delay spike, §7). The shift's cause is unknown and the mount may sit differently from one survey
    to the next, so it is measured per survey, not remembered as a constant. The user may build
    destagger earlier, as an add-on to another milestone, because it fixes tape grids too.
    - The correction is an along-track shift applied along each line's direction of travel, stored
      separately from what the line recorded (#47's design), one model for both kinds of line.
    - M17 lets the user type that shift for GPS lines: set for a whole import, editable per line.
      If destagger lands first, M17's GPS lines plug into its shift; if M17 lands first, destagger
      extends M17's. *Destagger landed first* (#47's stagger half in PR #160, automatic Measure in
      #159 / PR #168; §15), so M17a's `TrackPlacement.travel_shift` is `GridPlacement`'s field
      under the same name, and the Survey panel calls it "destagger" for both kinds of line. #47
      stays open for its other half, direction balancing. Measure works on grid lines only; M17c
      extends it to GPS lines in a grid (§9; moved from M17d at the M17b walkthrough).
    - A delay term (seconds, scaled by walking speed) is measurable only on GPS lines. It is worth
      4–11 cm here; whether nsgeo carries it is for destagger to decide.
11. **True-distance profiles are in M17, as their own middle chunk** (after the builder check
    raised it; the user, 2026-11-06). A GPS line's profile, migration and velocity fit use each
    trace's true distance, and a lift shows as a gap. Estimated medium (2–3 tasks), so it was M17b
    and the areas M17c. Relettered on 2026-11-17: true-distance profiles are M17c, GPS lines in
    grids M17b, the rest of the areas M17d (decision 14, §9).

12. **GPS slices show their gaps** (the user, 2026-11-06). An area keeps the slices' usual default
    max distance (0.75× its spacing), so the slivers where walked lines drifted apart stay blank:
    they are real thin coverage, and a tape placement only hides them by assuming even spacing. To
    fill them for a figure, the user raises max distance for that grid, as today.
13. **An outline can have holes** (the user, 2026-11-16). On one survey, roads along the top and
    bottom edges of a grid gave high-amplitude reflections down the whole profile, and they
    overwhelmed the features of interest in the slices. An outline drawn inside the roads blanks
    them; a road through the middle of a grid is conceivable, and needs a hole, since one outline
    cannot cut a strip out of the middle and keep both sides. Blanked cells (outside the outline
    or in a hole) must also drop out of the slices' colour stretch, so a masked road no longer
    sets the colours (§5.4).
14. **One Add data menu, and GPS lines always go into a grid** (the user, 2026-11-17, during the
    M17a walkthrough). Replaces decisions 2–4 from M17b on; M17a was built and walked through
    before it, and the milestones were relettered (§9).
    - A toolbar **Add data ▾** menu replaces the separate import buttons. Its entries name the
      instrument: **GPR…** now, the magnetometer when M19 lands.
    - The GPR dialog has a switch between **Grid** (placed by the tapes, today's Import DZT…) and
      **GPS** (placed by each file's DZG).
    - With GPS, the lines go into a grid: an existing one picked from a list, or a new one the user
      names, fitted around the files' tracks. The user asked for a minimum oriented bounding
      rectangle. Claude suggested lining it up with the lines instead, because a pure minimum-area
      rectangle can come out turned a degree or two from the lines where their starts are ragged
      (this survey's start line was 1.8° off square) and puts the outer lines on its edge; the user
      agreed. So a new grid is §6.3's fitting: turned to the lines' main direction, edges half a
      spacing outside the outer lines, along edges at the extreme trace positions. Only when the
      lines share no main direction does it fall back to the minimum-area rectangle.
    - Lines imported unattached by M17a keep loading. Move to grid ▸ puts them into a grid, and Fit
      to these tracks makes one around them.
    - **GPS available is said once, at import.** With the switch on Grid, the dialog notes how many
      of the chosen files have a usable GPS log beside them. Nothing marks it after that: not the
      Survey panel, the map or the summary. In the user's words, they choose how to import, "but not
      be nagged if they decide they trust the grid more than the gps".
15. **The Add data dialog as mocked up** (the user, 2026-11-19, two rounds of the M17b mock-up,
    `.lavish/m17b-add-data.html`, built on session D's dialogs with its Processing preset box).
    - **A new grid is made in the dialog** (option A+): Target grid lists **New grid** first, then
      the site's GPR grids. New grid shows a Name (filled in, not used by another grid, before
      Import is enabled), a Spacing measured from the tracks that can be typed over, and a Fitted
      line with the rectangle's size and azimuth. The rectangle is drawn dashed on the map while
      the dialog is open, follows the files as they are added and removed, and goes when the dialog
      closes. Import makes the grid and adds the lines in one step; velocity and corners are set
      afterwards with Edit grid…, as for any grid. Not the Grid dialog first (option B).
    - **The switch reads "Place lines by: Grid | GPS".**
    - **The mode it opens in:** Grid the first time, then the mode last used. A grid's own
      shortcut (the Survey panel's **Import DZT files…**, renamed **Add GPR data…**) opens in GPS
      mode when the grid's lines are all GPS lines, in Grid mode when they are all tape lines, and
      in the last-used mode when it is empty or holds both. *From the walkthrough (2026-11-20,
      W5):* the toolbar's GPS mode always starts on **New grid**; the grid the Survey panel points
      at is the Grid mode's target only. A grid's own Add GPR data… starts both modes on it.
    - **Files GPS cannot place** (no DZG, or no RTK-fixed position): the user asked whether they
      could be placed by offset, start and direction instead of being dropped. Chosen: **handed on
      to Grid mode** (option B). Import places the GPS lines (and makes the grid); when files were
      left over, the dialog stays open, switched to Grid mode on that grid with only those files,
      each one's offset and direction guessed from the GPS lines either side of it in file order,
      shown amber with a note naming the neighbours. Import places them; Cancel leaves them out.
      The guess is made only when those neighbours run along one of the grid's axes; otherwise the
      rows start as Grid mode starts them. Not dropped (A), and not tape cells inside the GPS
      table (C), where a typed offset would move each time a file changed a new grid's fit.
    - **Into an existing grid**, the table gains an **Outside <grid>** column (metres of each line
      outside the rectangle, amber), and a line wholly outside is refused ("outside <grid>"):
      almost always the wrong grid. Claude's call, shown in the mock-up and approved with it.
    - **Edge cases shown and approved:** switching mode keeps the files (each mode keeps its own
      settings); a single line leaves Spacing empty until typed and makes a grid one spacing wide;
      lines with no main direction get the smallest rectangle, and Fitted says so; the new grid is
      fitted from the ready rows only; a magnetometer grid is never listed.
---

## 4. Claude's calls

Made without the user; each is open to veto.

- **C1. An area is an ordinary `Grid`.** It gains an optional outline (a polygon in grid-local
  metres; none means the rectangle). Everything that works on grids (Slices panel, Whole site, the
  Survey panel, velocities, exports, M15's cuts) then works on areas unchanged. There is no second
  kind of grid object.
- **C2. Membership is a `grid_id` on the GPS line's placement** (`None` when unattached: from M17b
  only lines imported by M17a, which the loader keeps reading; decision 14). The
  plugin already decides membership by `getattr(line.placement, "grid_id", None)` everywhere it
  asks (session, Survey panel, line choice, site scope), so this slots in.
- **C3. Moving a GPS line changes only which grid it belongs to.** It never moves the line. Move to
  grid ▸ lists grids only: from M17b a GPS line always has one (decision 14), so the first
  version's **No grid** entry is dropped.
  Tape lines keep line editing's behaviour (re-placed in the new grid's frame).
- **C4. A grid can hold both kinds of line,** e.g. GPS lines walked across an old tape grid. Each
  line keeps its own placement. Nothing warns about the mix; tape lines on that survey were
  typically 0.3 m off the GPS positions, so the result may not line up well.
- **C5. Unattached lines have no slices.** Slices come from grids; from M17b only M17a's lines can
  be unattached (decision 14). (`CubeFrame.for_points` exists
  for a frame around scattered tracks, but nothing needs it once areas are grids.)
- **C6. Bridged traces go into slices** like any other: they are placed, just less precisely.
- **C7. The area's line spacing** (`default_spacing`, used by the slices' default max distance of
  0.75× spacing) is measured from the tracks whenever a grid is fitted to them (at import from M17b,
  or by Fit to these tracks), and can be typed over.
  An area drawn by hand with no tracks selected asks for it.
- **C8. Shared ruler or walked distance:** a GPS line shares the area's ruler when its overall
  direction is within about 20° of one of the area's axes; otherwise it uses distance walked. The
  builder may tune the angle.
- **C9. Switching a tape-placed line to GPS is an action on the line, in place** (revised
  2026-11-16, after the user asked how a re-imported line would be known as the same one). The
  first version was remove-and-re-import, then Move to grid ▸. A line is known by its file path
  (`nsgeo.project.line_key`), so picks did come back (they wait in the picks layer, #35), but
  removing a line drops its processing stack, velocity override and stored fits (`_drop_lines`),
  and the removal question does not say so. Instead, **Place by GPS** on one or more tape lines
  (Survey panel) reads the DZG beside each line's own DZT and swaps its `GridPlacement` for a
  `TrackPlacement` with the same `grid_id`, the way an edit swaps placements today: the key is
  unchanged, so processing, velocity, fits (stored by trace and time) and picks all stay, and picks
  follow the new positions as they do after any edit. It takes a destagger value as Import GPS
  lines… does. The tape line's own `travel_shift` (destagger, from #47) is not carried over: it
  corrected where the tape placement put the traces, and once GPS places the line a different offset
  applies (the GPS's position relative to the radar, §7: −48 cm between neighbours by GPS against
  −30 cm by tape on the same lines), so the value is measured again (typed, or by Measure once M17c
  extends it to GPS lines). A line with no usable DZG is refused with the import's reasons. M17a's
  import refuses a file already in the site with "already in the site"; it does not tell the user to
  remove it.
- **C10. The saved project holds the fixes it placed the line from** (trace index, projected
  position, quality, altitude), so reopening a project gives identical positions even if the DZG is
  moved, edited or lost. A DZG is small (~50–100 fixes per line).
- **C11. Time-triggered lines with a DZG place by GPS too.** Tape placement refuses them (no
  traces per metre); GPS placement needs only trace numbers, and bridging by trace count is bridging
  by time. Placing them comes free. Anything that needs a trace spacing (migration) still refuses
  them today; once M17c gives migration true spacing (decision 11), a GPS line needs no wheel
  for it either.
- **C12. A site has one CRS of its own** (from the builder check). Today a site borrows the first
  grid's (`grids[0].crs`, in `layers.py`, `site_engine._site_crs` and the grid dialog's
  `_choose_crs`), so a site holding only GPS lines would have none, and the map draws nothing while
  a site has no grids (`SiteLayers.refresh` returns early). The site gets a `crs` saved in
  `survey.nsgeo.json`: an existing site takes its first grid's; a new site takes it from its first
  grid or its first GPS import, by decision 9's rule. Every GPS import projects into the site's
  CRS, so all lines and grids of a site share one CRS and slices never meet a mismatch. The stored
  fixes keep their latitude and longitude as read (C10), so re-projecting stays possible.
- **C13. The outline is #130's perimeter, and any grid can have one** (from the builder check).
  #130 proposes exactly this model: an optional polygon in grid-local metres, inside the grid's
  rectangle, that only clips. One field serves both, and nothing marks a grid as an "area". The
  polygon may have holes (decision 13). So:
  - drawing or reshaping an outline never moves the grid's frame. The outline stays inside the
    rectangle; to grow past it, the user edits the grid's rectangle in the grid dialog, where the
    existing rules for any tape lines on it apply;
  - an outline drawn for a new area sets the rectangle once, at creation: the smallest at the
    area's azimuth that holds it;
  - editing a grid's origin, azimuth or size moves its outline with it (it is in grid-local metres)
    while GPS lines stay put, as they do for any grid edit;
  - this delivers #130's slices mask and drawing tools for tape grids too. #130's other half, placing
    each tape line's start and end where it crosses the perimeter, stays out of scope.

---

## 5. The core (`nsgeo-core`, numpy only)

### 5.1 The DZG reader

A new `nsgeo.io.dzg`. It reads a DZG into per-fix records: trace index, latitude, longitude,
altitude and geoid separation, fix quality, HDOP, satellite count, UTC time. It pairs each GGA with
the `$GSSIS` immediately before it.

Tolerant of what we have not seen yet, strict about what would misplace a trace:

- any GGA talker (`$GNGGA`, `$GPGGA`, …); other sentences ignored;
- a sentence with a bad checksum is dropped and counted;
- a GGA with no preceding `$GSSIS`, or a `$GSSIS` with no GGA, is dropped and counted;
- trace numbers that fall, or that lie outside `0 .. n_traces - 1`, are an error for that line,
  not something to repair silently. (None occur in the real files.)

The reader is also where the matching DZG for a DZT is found: by stem, either case, the way
`nsgeo.io.dzx.sidecar_for` finds the DZX.

### 5.2 `TrackPlacement`

A second implementation of the existing `Placement` protocol (`nsgeo/geometry/placement.py`), with
the fixes it uses in a projected CRS (metres), `grid_id` (C2), and `label`.

- `trace_coords`: positions interpolated by trace index between RTK-fixed anchors (§5.3), ignoring
  `frames` (a GPS line needs no grid to be placed).
- `distance_along`: cumulative path length along those positions (distance walked), as the first
  spec (`2026-09-10-nsgeo-gpr-qgis-design.md`, Placement) always said.
- JSON round trip in `nsgeo/project.py` as a new placement type (today `_placement_to_dict` raises
  for anything but `GridPlacement`). Stores the fixes (C10).
- An along-track shift (decision 10), applied along the line's direction of travel to every
  trace position, stored apart from the fixes. Zero by default.
- Exposes the bridged stretches (trace ranges and metres) and whether either end ran past the
  extrapolation limit, for the import summary and the map.

### 5.3 Fixes, bridges and ends

- Anchors are quality-4 fixes only (decision 7).
- Between two anchors, traces are spaced evenly by trace index along the straight segment. A
  stretch is **bridged** when the anchors on either side are further apart than ordinary fixes are
  (they were separated by ignored fixes). The builder picks the rule; "an ignored fix lies between
  them" is the obvious one.
- Before the first anchor and after the last, traces continue by wheel along the line's heading at
  that end (taken from the nearest anchors). Beyond about 2 m the line is flagged. On the real files
  the start runs 0.0–0.67 m, the end 0 m.
- No anchors at all: the line cannot be placed by GPS (decision 7).

### 5.4 The area outline

`Grid` gains an optional outline: a closed polygon in grid-local metres, with zero or more holes
(decision 13), each a closed polygon inside it. The cube frame is the grid's rectangle as now
(`CubeFrame.for_grid`). A cell is kept when its centre is inside the outline and in no hole; every
other cell is left empty in every slice and export: AND the outline's cell mask into the same place
the interpolation's `reach_mask` already removes cells too far from data. JSON round trip, with a
schema change only when an outline exists (the way M15 handles `schema_version`).

- **The colour stretch ignores masked cells.** `limit_over_slices` already measures only finite
  values; the masked cells must be blank (NaN) by the time `shared_limit` reads the cube, and a
  test must show it: a cube whose masked region holds values far above the rest gets the same
  limit as a cube without them.
- **The fill runs before the mask.** Traces outside the outline or in a hole still feed cells
  inside it, up to the max distance (and minimum curvature can overshoot a little beside a strong
  contrast). That keeps an outline's edge from going thin, but a cell just inside a road's edge can
  still be bright; the guide says to draw the outline a little inside the road.
- **Profiles are untouched:** an outline masks slices and exports only.

---

## 6. The plugin

### 6.1 Import GPS lines…

*M17a as built. From M17b, Add data ▾ ▸ GPR… replaces it (§6.5, decision 14).*

A new action, not tied to a grid. The user picks DZT files. For each, the DZG beside it is read, the
fixes are converted to the site's CRS (decision 9; `utm_epsg` in `ui/grid_dialog.py` has the
fallback), and the line is added with a `TrackPlacement` and no grid.

One summary at the end names: lines placed; bridged stretches per line, with metres; lines whose
ends ran past the limit; lines refused and why (no DZG, no fixed position, unreadable DZG). Nothing
is refused silently, and nothing is placed from a bad fix silently.

Where the action lives (toolbar, Survey panel, or both) is the builder's call.

### 6.2 Map, Survey panel, profiles

- **Map:** `layers.py` draws GPS lines along their path, today skipping any line with no grid
  ("trackless lines arrive with TrackPlacement, later"). Bridged stretches are drawn differently.
  The lines layer's fields today come from `GridPlacement` (`axis`, `offset_m`, `start_along_m`,
  `direction`, and `length_m` from the wheel); GPS lines need sensible values or blanks there, a
  field saying how the line is placed, and `length_m` as distance walked.
- **Survey panel:** unattached GPS lines sit in the existing no-grid section; GPS lines in an area
  sit under it. GPS and tape lines should be told apart at a glance.
- **Profiles:** decision 8 and C8. The ruler code (`ui/ruler.py`, `ProfileDock._ruler_for`) keys a
  ruler by `(grid_id, axis)` and reads `placement.axis`; GPS lines need an axis derived from their
  direction within the area, and distances projected onto that axis rather than walked.
  From M17c the view draws each trace at its true distance on whichever ruler the line uses
  (decision 11). A projected distance can step backwards where the operator did; the builder must
  keep it monotonic.
- **Edit lines…** (line editing's table): GPS lines appear with their grid, and their tape-only
  fields read-only or blank. Move to grid ▸ follows C3.

### 6.3 Making and reshaping an area

- **Fit to these tracks:** from a selection of GPS lines (Survey panel or map), make a grid lined
  up with them (from M17b the same fitting makes a new grid at import, §6.5): azimuth from the
  lines' main direction, cross edges half a spacing outside the
  outer lines' mean positions or further to hold every trace (the M17b walkthrough, §16), along
  edges at the extreme trace positions, spacing measured (C7).
  It opens in the grid dialog, so the user can name it and set a velocity before OK.
  When the lines share no main direction (supplemental lines at every angle), the rectangle is the
  minimum-area one around every trace, with the same half-spacing margin (decision 14).
- **Draw an outline:** click points on the map to make the outline, for a new area or on any
  existing grid (C13). For a new area the rectangle is the smallest one at the area's azimuth that
  holds it.
- **Reshape:** move, add and remove outline points after the area exists, inside its rectangle
  (C13).
- **Holes:** draw a hole inside an outline, reshape it and remove it (decision 13). A grid with no
  outline gets one equal to its rectangle when its first hole is drawn.

How drawing and reshaping look and behave is open: mock it up (lavish) and agree it with the user
before building, as with the grid dialog (#80). The grid dialog's map corner picking (#63) and its
overlay are the obvious things to build on.

### 6.4 Slices

An area is a grid (C1), so This grid and Whole site work as they do; the only changes are the
outline mask (§5.4) and that GPS lines bin at their own positions, which `trace_coords` already
gives. Whole site's per-grid engines take areas like any grid.

### 6.5 Add data (from M17b, decision 14)

- **Add data ▾ ▸ GPR…** opens one dialog for GPR files with a **Grid / GPS** switch. **Grid**
  behaves as today's Import DZT…. **GPS** is M17a's table (its rows, amber and red cells, destagger
  and coordinates) plus a grid choice: an existing GPR grid, or **New grid** with a name.
- **A new grid** is fitted when the user imports: decision 14's rectangle, in the site's CRS, with
  its spacing measured (C7) and shown so it can be typed over. Whether it opens in the grid dialog
  before the lines are added, as Fit to these tracks does, is for the mock-up.
- **GPS available, in Grid mode only:** a plain note beside the switch, e.g. "12 of 20 files have
  a GPS log beside them". Usable means at least one RTK fix, so a log with none is not counted; the
  dialog reads the logs it would read in GPS mode. The note is the only place this shows (decision
  14): no marker on Survey panel rows, the map or the import summary.
- **An existing grid** takes the lines as they are. Traces outside its rectangle are not in its
  slices, so the summary says how many metres of each line fall outside.
- **Has to handle:** a single line (a new grid one spacing wide, spacing typed); lines walked in
  every direction (the minimum-area fallback); a mag grid is never offered.
- **The old entries:** the toolbar's Import DZT… and Import GPS lines… fold into Add data. The
  Survey panel's per-grid **Import DZT files…** stays as a shortcut that opens the dialog with that
  grid chosen. The layout is mocked up (lavish) and agreed with the user before building, as M17a's
  dialog was. *Done 2026-11-19: decision 15 records the mock-up's answers, and §16 the calls M17b's
  plan makes.*

---

## 7. GPS delay

Measured on the 60 lines by a throwaway spike before this spec was finished. The user expected the
delay to be low. It is not.

**Method.** Traces were placed by GPS as logged (interpolated by trace number). For each line,
envelope profiles along the area's long axis (4–70 ns, the 2 m at each end left out) were
cross-correlated against the mean of its two neighbours, which run the other way. A shift that
belongs to the direction of travel shows up as opposite-direction neighbours offset against each
other.

**Result.**
- Opposite-direction neighbours are offset by **−48 cm** (bootstrap 95% −50 to −47 cm): each line's
  features sit about **24 cm behind** where they belong, relative to its direction of travel.
  Neighbour correlation is −0.56 as logged against +15 for same-direction pairs.
- Steady across the area, within limits: across time windows and parts of the area the estimate
  ranges from −44 to −59 cm, so a fair figure is **−48 ± ~6 cm** between neighbours (21–27 cm per
  line). The bootstrap above only resamples lines. Equal shares per direction are *assumed*: a
  comparison between opposite-direction lines cannot apportion the disagreement between them.
- **Mostly a fixed offset, partly a delay.** Walking speed varied from about 0.35 to 1.1 m/s. The
  one-way shift grows only from ~21 cm on the slowest stretches to ~28 cm on the fastest. Fitting
  against speed within lines gives about 15 cm (10–19) of fixed along-track offset plus about 0.11 s
  (0.05–0.17) of delay. The total is well determined; the split is not.
- A 0.35 s delay alone, a 23.5 cm offset alone, or 15 cm + 0.11 s together all bring the mean shift
  within 3 cm, and neighbour correlation rises to about 18. On the strongest compact feature
  (22–28 ns) the logged placement draws a sawtooth between alternate lines; corrected, a compact
  blob.
- Tape placement is not clean either: its opposite-direction offset is −30 cm (the zigzag stagger
  of #47, plus a short-reading wheel squeezing features toward each line's start).

**So nsgeo needs an along-track correction for GPS lines.** The user believes the GPS antenna is
centred over the radar, so the fixed part may come from the radar side (where the controller counts
a trace from) rather than the mount. Either way it is a shift along the direction of travel, and a
zigzag survey can measure it.

**Mast tilt is a separate, smaller error** (user, 2026-11-06: the GPS is fixed to the cart about
1 m above the radar, so it leans with the slope). It leans downhill whichever way the cart travels,
so it moves both directions' positions the same way: it causes **no stagger**, only an absolute
shift of `h · sin(slope)`. From the GGA altitudes this site slopes ~1.6° overall, ~2° (median) and
~5° (p90) over 3 m stretches: 3.5 cm typical, 8.5 cm on the steeper stretches, ~17 cm per 10° on a
steep site. It is correctable later from the altitude record and the mast height (§12).

**Decided (decision 10).** The full measurement, its method and what it means for destaggering
are in `docs/superpowers/notes/2026-11-06-stagger-spike.md`.

---

## 8. Where the code stands

*Written 2026-11-06. Main has moved since; §15 lists what changed and supersedes this section
where they differ.*

- **`Placement` protocol** with one implementation, `GridPlacement`. `nsgeo/project.py` serialises
  only that.
- **Grid membership** is `getattr(line.placement, "grid_id", None)` across the plugin (`session.py`
  `keys_on_grid` / `grid_for_line`, `ui/survey_dock.py`, `ui/line_choice_dialog.py`,
  `ui/site_scope.py`), so a `TrackPlacement` with a `grid_id` is a member wherever membership is
  asked.
- **The first spec's promise** that GPS support "touches nothing else" is no longer true. Several
  places read `GridPlacement`-only fields: `layers.py` (the lines layer), `lookup.py`,
  `ui/profile_dock.py` and `ui/ruler.py` (rulers, #67), `ui/survey_dock.py`,
  `ui/line_choice_dialog.py`; on the line-editing branch also `line_edit.py`, `session.py` and
  `slices_engine.py`. A builder should grep `placement.` on the merged main before planning.
- **Lines with no grid** are skipped on the map (`layers.py`, `refill_lines`) and listed in the
  Survey panel's no-grid section.
- **Slices:** `CubeFrame.for_grid` / `for_points` (`nsgeo/slices/frame.py`); empty cells beyond
  max distance come from `reach_mask` (`nsgeo/slices/interpolate.py`).
- **Velocity:** `resolve_velocity(line, grid)` already falls back from line override to grid to
  the header's dielectric, so an unattached line gets depths without change.
- **Line editing** (unmerged when written): Move to grid ▸, Edit lines…, picks that follow their
  line through any move and through remove-and-re-import (#35), and the slices engine re-preparing
  when a line's placement changes. M17b and M17d need it merged.
- **Profiles assume one equal column per trace** (`ui/view_transform.py`: `x_of_trace` /
  `trace_of_x` are linear in trace index; `ui/profile_view.py` calls them in ~15 places). The
  ruler side already maps trace to metres through each line's own distance array
  (`ui/ruler.py`: `trace_to_metres` / `metres_to_trace`), so it handles uneven spacing.
- **Trace spacing for processing** is one number, `Radargram.dx_m`, from the header's traces per
  metre (`nsgeo/processing/base.py`); migration is its only user. The velocity fit takes metres per
  trace as `distance[1] - distance[0]` (`ProfileDock._velocity_axis`).

---

## 9. Milestones

Each gets its own plan (3–6 tasks), build and walkthrough on its own QGIS profile.

- **M17a — GPS lines.** DZG reader; `TrackPlacement` with bridges, ends and its JSON round trip;
  Import GPS lines… with its summary; the typed along-track shift (decision 10), set for an import
  and editable per line; map paths with bridged stretches; Survey panel; profiles labelled in
  distance walked (still one column per trace); picks, processing and velocity on GPS lines as on
  any line. Useful on its own: free transects and supplemental lines.
- **M17b — Add data and GPS grids** (decision 14). Add data ▾ ▸ GPR… with its Grid / GPS switch
  (§6.5, mock-up first); GPS lines into an existing grid or a new one fitted around them; GPS lines
  working in grids: slices and Whole site (they bin at their own positions through `trace_coords`),
  the Survey panel under their grid, Edit lines (tape-only fields read-only), Move to grid ▸ (C3),
  grid edits that leave GPS lines where they are (C13), profiles in distance walked until M17c's
  shared rulers; Fit to these tracks from a selection, for lines M17a imported unattached. GPS lines
  never join a mag grid.
- **M17c — True-distance profiles** (decision 11; M17b before 2026-11-17). The profile view draws
  every trace at its true distance, with a visible gap where the cart was lifted; picks, the
  velocity-fit curve, hover, mirroring, the gain strip and the Difference view follow. The velocity
  fit uses each trace's true distance; migration re-samples a GPS line to even spacing, migrates and
  maps back. Tape lines, being evenly spaced, look exactly as before. **Also, moved from M17d at the
  M17b walkthrough (the user, 2026-11-20):** shared rulers (decision 8, C8), so a GPS line in a
  grid is drawn on the grid's ruler and a reversed line is mirrored like a reversed tape line (W11:
  "It makes interpretation much harder when lines aren't consistent like that"); and destagger's
  Measure (#159) for GPS lines in a grid (§15; W8: destagger was prioritized because of the GPS
  lines' stagger). Shared rulers are exact for zigzag lines only with true distance, which is why
  they travel together. With these M17c may need two plans (3–6 tasks each). Expect a fix round
  after the walkthrough: the profile view is where walkthroughs have found the most (#67, the time
  cutoff, the gain strip).
- **M17d — Outlines and the rest of the areas.** Grid outline with holes and its mask, which the
  colour stretch ignores (decision 13); drawing and reshaping; Place by GPS for tape lines (C9).
  Needs line editing merged.

---

## 10. Testing

- **Committed tests use synthetic DZGs** written by a test helper that copies the real structure:
  `$GSSIS`/`$GNGGA` pairs, 1 Hz fixes every 14–62 traces, a first fix 1–40 traces in, a last fix
  at the last trace, pause gaps in time with no repeated trace, valid checksums, made-up
  coordinates.
- **Dropouts** are tested from real files switched locally: a stretch of fixes rewritten to
  quality 5 or 1 (and moved off the track by a plausible amount), so the bridged result can be
  checked against the true positions that were hidden.
- **Real-data tests** on `with-dzg/` skip when the files are absent, as the existing local-data
  tests do. Because CI can never notice such a test missing (the #125 lesson), each milestone's
  walkthrough lists the real-data checks by name.
- **Privacy.** No real coordinate, from a DZG or a DZT header, goes into any committed file: tests,
  fixtures, docs or figures. Figures use local metres. (`tests/data/local/README.md`.)

---

## 11. Manual checkpoints

- **M17a walkthrough** on the 60 lines: import without a grid; every line on the map along its path;
  `FILE__011` drawn at its full ~30 m (not the wheel's 26 m); `FILE__016` and `FILE__028` stretched
  across their obstacle lifts; profiles labelled in distance walked; the summary's wording. The dropout
  display can only be walked on a locally degraded copy, since no real dropout exists.
- **M17b walkthrough:** Add data ▾ ▸ GPR… with GPS on the 60 lines into a new grid: the rectangle
  lined up with the lines, half a spacing outside the outer ones; slices of it. The second survey
  into an existing grid, with a line partly outside it named in the summary. A tape import through
  the same dialog, unchanged, with its note counting the files that have a GPS log and no marker
  anywhere after import. M17a's unattached lines moved into a grid, and a grid fitted around
  others. Edit lines with GPS rows; editing the grid leaves its GPS lines in place.
- **M17c walkthrough:** `FILE__016` and `FILE__028` show their lifts as gaps; a feature lines up on
  neighbouring profiles across a lift; picks, a velocity fit and mirroring on a GPS line; a tape
  line looks unchanged; a velocity fitted on a GPS line vs the same diffraction by wheel spacing;
  zigzag GPS profiles line up on one ruler, the reversed lines mirrored; Measure on a GPS grid's
  zigzag.
- **M17d walkthrough:** reshape a grid's outline; slices
  with nothing outside the outline; Whole site with a GPS grid beside an existing tape grid. On the
  survey with roads along two edges: an outline inside the roads, and the slices' colours no longer
  set by them; a hole across the middle. Place by GPS on a tape line with processing, a fit and
  picks: all three stay.

---

## 12. Out of scope

- #134's use 2 (a GPS track drawn beside a tape placement as a check).
- Direction balancing between lines walked in different directions (#47).
- Topographic correction (altitude is stored for it).
- Mast-tilt correction (§7): the GPS sits ~1 m above the radar and leans downhill on slopes. Needs
  the mast height and the slope from the altitude record; belongs with topographic correction.
- #130's placing of tape lines from where they cross the perimeter (the outline and its mask are in,
  C13).
- Slices of unattached lines (C5).
- Other GPS formats (MALA, Sensors & Software), live GPS, post-processed (PPK) corrections.

---

## 13. Left to the builder

- Where Import GPS lines… lives, and the summary's form (M17a; from M17b, Add data ▾, §6.5).
- The bridged-stretch rule (§5.3) and how ends take their heading.
- The ruler angle threshold (C8, ~20°).
- How the map shows bridged stretches and GPS-vs-tape lines, within the existing symbology (#66).
- Drawing and reshaping the outline, after a mock-up the user has agreed (§6.3).
- Schema versioning details for the new placement type and the outline.

---

## 14. Questions raised after brainstorming

The delay spike and the builder check raised three questions; the user answered all three on
2026-11-06: the along-track correction (decision 10), true-distance profiles (decision 11) and
gaps in GPS slices (decision 12). The builder check's other two questions became Claude's calls
C12 (a site-level CRS) and C13 (the outline is #130's perimeter, on any grid).

On 2026-11-16, after M17a was built, the user added holes to the outline (decision 13) and asked
how a re-imported line would be known as the same line, which revised C9 to an in-place
**Place by GPS**.

On 2026-11-17, walking through M17a, the user replaced the separate GPS import with one **Add
data ▾** menu and made GPS lines always go into a grid (decision 14), which relettered the
milestones: M17b GPS grids, M17c true-distance profiles, M17d outlines and the rest.

On 2026-11-19 the user answered the M17b mock-up in two rounds (decision 15), adding the hand-on
of files GPS cannot place to Grid mode.

On 2026-11-20, walking through M17b, the user had a fitted grid hold every trace (§16), and moved
shared rulers (mirrored GPS profiles) and Measure for GPS lines from M17d into M17c (§9).

---

## 15. What main changed before planning (2026-11-13)

Main moved ~300 commits between this design and the M17a plan. What matters here:

- **Line editing is merged** (PR #137, in 0.3.0): Edit lines…, Move to grid ▸ and picks that follow
  their line through any move or re-import. The later milestones' dependency is met.
- **Placement corrections and destagger are merged** (#3 and #47 in PR #160, #159 in PR #168).
  `GridPlacement` now has `scale` and `travel_shift`; `travel_shift` is metres, moving every trace
  forward along the line's own direction of travel, stored apart from `start_along`. That is exactly
  decision 10's model, so **`TrackPlacement` takes a `travel_shift` with the same name and meaning**,
  and the Survey panel names it "destagger" for both kinds of line. **Measure** in Edit lines
  (`nsgeo.destagger.measure`) reads `GridPlacement` fields (`axis`, `offset`, `direction`), so it
  works on grid lines only; extending it to GPS lines in a grid is M17c's (moved from M17d,
  2026-11-20).
- **Cuts are merged** (M15, PR #172), with schema 2 for a site with cuts. **Velocity sources** took
  schema 3 (PR #186). A site with GPS lines therefore saves as **schema 4**.
- **M19a (magnetometer grids) is built on its own branch, not merged.** It adds `Grid.instrument`
  (`"gpr"` / `"mag"`), mag files on `Site`, its own schema bump (numbered 3 on its branch, so it must
  renumber when it meets main), and mag rows in the Survey panel. Whichever of M17a and M19a merges
  second renumbers its schema constant to the next free number and expects conflicts in
  `project.py`, `session.py` and `ui/survey_dock.py`. GPS lines never join a mag grid (M17b: neither
  the import's grid list nor Move to grid ▸ offers one).
- **Slices changed underneath** (#113 packed cube, #111 multigrid, #107/#108 whole site at fine
  cells). M17d's outline mask must be re-checked against the packed cube's covered-cells model when
  its plan is written.
- **Real data:** `tests/real_data.py` now lists each survey separately (#141): `GPS_LINES` (this
  spec's 60 lines) and `GRID2_LINES` (a second 60-line survey from the same site, with DZGs). The
  second survey holds the first real dropouts:
  - `FILE__039`: three float fixes (quality 5) at traces 190, 212, 239, between RTK fixes at traces
    149 and 246, 1.83 m apart. The float fixes sit 1–37 cm off the straight bridge, which supports
    decision 7 (float is not trusted).
  - `FILE__042`: two float fixes at traces 1753 and 1754, between RTK fixes at 1739 and 1755 (the
    last trace), 0.39 m apart.
  These become real-data tests for bridges, so dropout behaviour no longer rests on synthetic data
  alone.
- **The CRS rule** (#62) lives in `GridDialog` methods (`_choose_crs`, `_usable_at`, `_crs_check`,
  `_crs_scale_error`), reading the site's CRS as `site.grids[0].crs`. M17a moves the rule into a
  module both dialogs use, and gives the site its own CRS (C12).

---

## 16. M17b's calls (2026-11-19, with its plan)

Made by Claude while planning M17b; each is open to veto at the walkthrough.

- **The fit** (§6.3, decision 14), in the core's `nsgeo.geometry.track_fit`:
  - A line's direction is its last trace's position minus its first, as an axis (a line and its
    reverse point the same way). Lines shorter than 1 m have none and do not vote.
  - The **main direction** is the length-weighted mean of those axes (on doubled angles). Lines
    within 20° of it (C8's angle) run **along** it. The lines share a main direction when the
    along lines hold more than half of the summed first-to-last lengths (so an evenly
    cross-hatched survey has none); one line always does.
  - **Spacing** is the median gap between neighbouring along lines, each line taken at its mean
    position across the main direction. None with fewer than two along lines, or with no main
    direction: the dialog then waits for a typed one.
  - **The rectangle:** +Y along the main direction (azimuth folded into −90°…90°, stored as
    0…360); along edges at the extreme trace positions of every line; cross edges half a spacing
    outside the outer along lines' mean positions, or further where any trace lies beyond that, so
    every trace is inside. *Changed at the walkthrough (2026-11-20, W3):* the first version
    widened only for lines that are not along, which left an eighth of a wandering outer line's
    traces out of the slices; the user: "grow the grid to hold every trace. Why throw away data?"
    With no main direction, the smallest-area rectangle around every trace, half a spacing
    outside it on all four sides, +Y along its longer side.
- **Metres outside a grid:** the walked length of every trace-to-trace step whose midpoint lies
  outside the rectangle. A line is wholly outside when no trace lies inside.
- **The hand-on guess:** a leftover file's offset is interpolated by file position between the
  nearest placed GPS lines before and after it (each at its mean position across the grid's axis);
  at an end, one grid spacing further on per file, away from the line before; its direction is
  opposite the line before it in file order (placed or guessed), or opposite the line after it for
  the first file. Made only when every neighbour used runs within 20° of the same grid axis.
- **GPS lines in Edit lines…:** a GPS row's Label, Destagger and Grid can be edited; Offset, Dir,
  Start and Scale show "—" and cannot. Bulk changes to those four, Fit to grid edges and Measure
  leave GPS rows alone and the status line says how many. Moving a GPS line to another grid only
  changes its grid (C3).
- **Fit to these tracks** is offered on a Survey panel selection of GPS lines only (the map's
  selection is the panel's since #57). It opens Add grid… filled in with the fitted rectangle and
  spacing, the Id left blank; OK adds the grid and moves the lines into it. One line gets the
  Grid dialog's default spacing to start from.
- **#222:** GPS lines in a grid hide on zoom-out by their grid's spacing like any line; GPS lines
  in no grid (from M17a) use the spacing measured from their own tracks.
- **Messages:** the dialog reports each Import as it happens (it can stay open for the hand-on), not
  only when it closes.
