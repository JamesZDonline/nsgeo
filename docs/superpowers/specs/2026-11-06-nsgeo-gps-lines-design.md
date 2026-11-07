# nsgeo GPS lines (M17) — design

Place GPR lines by the RTK GPS track that the GSSI controller records in a `.DZG` beside each
`.DZT`, so that a survey can be walked without tapes. GPS lines are imported **unattached**. An
area for slices is drawn or fitted around them **afterwards**, and lines join it with **Move to
grid ▸**. The area can be any shape.

Answers #134's "to decide" list: use 1 (free GPS lines) and use 3 (lines placed by GPS inside a
slice area) are in; use 2 (a GPS track drawn beside a tape placement as a check) is dropped. Two
milestones, M17a and M17b (§9). Builds on the line-editing bundle (#35, #64, #29; branch
`nsgeo-line-editing`), which was not yet merged when this was written.

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
imports the files without making a grid first and sees every line on the map along the path it was
walked. They make an area with **Fit to these tracks**, reshape it if they want, move the lines into
it, and get slices of it in the Slices panel like any grid's. Lines with no RTK fix for a stretch
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
  area is 3.5% holes inside the area, against 0.09% for the same lines placed by tape. (Open, §14.)

**What we do not have:** a DZG with float or plain fixes, other NMEA talkers (`$GPGGA`) or
sentences, a multi-channel DZT with a DZG, or a time-triggered (no wheel) line with a DZG.

---

## 3. Decisions taken in brainstorming

These are the user's, in the order they were made.

1. **GPS is trusted over tapes.** Use 2 of #134 (draw the GPS track beside a tape placement to
   check it) is not wanted.
2. **GPS lines are imported unattached,** each placed from its own DZG, with no grid chosen first.
3. **The slice area is made afterwards.** It need not be rectangular. The cube behind it stays
   rectangular, just big enough to hold the outline, with cells outside the outline left empty.
4. **Lines join an area by being moved there** with Move to grid ▸ (line editing), not by falling
   inside it.
5. **Fit to these tracks** stays in: select lines, press it, get a rectangle lined up with them,
   then reshape it. Its edges sit half a spacing outside the outer lines, matching the user's
   practice (§2).
6. **No antenna-offset setting:** the mount is centred. *Reopened by the delay measurement (§7):
   the data shows a ~24 cm along-track shift regardless, so some along-track correction is needed;
   its form is open (§14).*
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
   - two milestones (§9). M17 stays where the roadmap puts it, after M15 and M16, unless the user
     says otherwise.

---

## 4. Claude's calls

Made without the user; each is open to veto.

- **C1. An area is an ordinary `Grid`.** It gains an optional outline (a polygon in grid-local
  metres; none means the rectangle). Everything that works on grids (Slices panel, Whole site, the
  Survey panel, velocities, exports, M15's cuts) then works on areas unchanged. There is no second
  kind of grid object.
- **C2. Membership is a `grid_id` on the GPS line's placement** (`None` when unattached). The
  plugin already decides membership by `getattr(line.placement, "grid_id", None)` everywhere it
  asks (session, Survey panel, line choice, site scope), so this slots in.
- **C3. Moving a GPS line changes only which grid it belongs to.** It never moves the line. Move to
  grid ▸ gains a **No grid** entry for GPS lines, so a line can be taken out of an area again.
  Tape lines keep line editing's behaviour (re-placed in the new grid's frame).
- **C4. A grid can hold both kinds of line,** e.g. GPS lines walked across an old tape grid. Each
  line keeps its own placement. Nothing warns about the mix; tape lines on that survey were
  typically 0.3 m off the GPS positions, so the result may not line up well.
- **C5. Unattached lines have no slices.** Slices come from areas. (`CubeFrame.for_points` exists
  for a frame around scattered tracks, but nothing needs it once areas are grids.)
- **C6. Bridged traces go into slices** like any other: they are placed, just less precisely.
- **C7. The area's line spacing** (`default_spacing`, used by the slices' default max distance of
  0.75× spacing) is measured from the selected tracks by Fit to these tracks, and can be typed over.
  An area drawn by hand with no tracks selected asks for it.
- **C8. Shared ruler or walked distance:** a GPS line shares the area's ruler when its overall
  direction is within about 20° of one of the area's axes; otherwise it uses distance walked. The
  builder may tune the angle.
- **C9. Switching an old tape-placed line to GPS** is remove-and-re-import through Import GPS
  lines…, then Move to grid ▸. Picks follow the line through that (line editing, #35). No dedicated
  button.
- **C10. The saved project holds the fixes it placed the line from** (trace index, projected
  position, quality, altitude), so reopening a project gives identical positions even if the DZG is
  moved, edited or lost. A DZG is small (~50–100 fixes per line).
- **C11. Time-triggered lines with a DZG place by GPS too.** Tape placement refuses them (no
  traces per metre); GPS placement needs only trace numbers, and bridging by trace count is bridging
  by time. Placing them comes free. Anything that needs a trace spacing (migration) still refuses
  them, as it does today, unless §14's question 2 changes that.
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
  rectangle, that only clips. One field serves both, and nothing marks a grid as an "area". So:
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

`Grid` gains an optional outline: a closed polygon in grid-local metres. The cube frame is the
grid's rectangle as now (`CubeFrame.for_grid`). Cells outside the outline are left empty in every
slice and export: AND the outline's cell mask into the same place the interpolation's `reach_mask`
already removes cells too far from data. JSON round trip, with a schema change only when an outline
exists (the way M15 handles `schema_version`).

---

## 6. The plugin

### 6.1 Import GPS lines…

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
- **Edit lines…** (line editing's table): GPS lines appear with their grid, and their tape-only
  fields read-only or blank. Move to grid ▸ follows C3.

### 6.3 Making and reshaping an area

- **Fit to these tracks:** from a selection of GPS lines (Survey panel or map), make a grid lined
  up with them: azimuth from the lines' mean direction, cross edges half a spacing outside the
  outer lines' mean positions, along edges at the extreme trace positions, spacing measured (C7).
  It opens in the grid dialog, so the user can name it and set a velocity before OK.
- **Draw an outline:** click points on the map to make the outline, for a new area or on any
  existing grid (C13). For a new area the rectangle is the smallest one at the area's azimuth that
  holds it.
- **Reshape:** move, add and remove outline points after the area exists, inside its rectangle
  (C13).

How drawing and reshaping look and behave is open: mock it up (lavish) and agree it with the user
before building, as with the grid dialog (#80). The grid dialog's map corner picking (#63) and its
overlay are the obvious things to build on.

### 6.4 Slices

An area is a grid (C1), so This grid and Whole site work as they do; the only changes are the
outline mask (§5.4) and that GPS lines bin at their own positions, which `trace_coords` already
gives. Whole site's per-grid engines take areas like any grid.

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
- Consistent everywhere: every time window and both halves of the area give the same answer, and
  southbound and northbound lines agree within 1 cm.
- **Mostly a fixed offset, partly a delay.** Fitting against speed changes within lines splits it
  into about 15 cm (10–19) of fixed along-track offset plus about 0.11 s (0.05–0.17) of delay. The
  total is pinned to about ±1.5 cm; the split is much less certain.
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

**Open (the user's call, §14):** the form of the setting, its default, and whether nsgeo estimates
it from a zigzag.

---

## 8. Where the code stands

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
  when a line's placement changes. M17b needs it merged.

---

## 9. Milestones

Each gets its own plan (3–6 tasks), build and walkthrough on its own QGIS profile.

- **M17a — GPS lines.** DZG reader; `TrackPlacement` with bridges, ends and its JSON round trip;
  Import GPS lines… with its summary; map paths with bridged stretches; Survey panel; profiles with
  distance walked; picks, processing and velocity on GPS lines as on any line. Useful on its own:
  free transects and supplemental lines.
- **M17b — GPS areas.** Grid outline and its mask; Fit to these tracks; drawing and reshaping;
  Move to grid ▸ for GPS lines (C3); shared rulers (decision 8, C8); slices of areas. Needs line
  editing merged.

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
  across their obstacle lifts; profiles in distance walked; the summary's wording. The dropout
  display can only be walked on a locally degraded copy, since no real dropout exists.
- **M17b walkthrough:** Fit to these tracks on the 60 lines; reshape the outline; move the lines in
  and one back out; zigzag profiles line up on one ruler; slices of the area with nothing outside
  the outline; Whole site with an area beside an existing tape grid.

---

## 12. Out of scope

- #134's use 2 (a GPS track drawn beside a tape placement as a check).
- Direction balancing between lines walked in different directions (#47).
- Topographic correction (altitude is stored for it).
- #130's placing of tape lines from where they cross the perimeter (the outline and its mask are in,
  C13).
- Slices of unattached lines (C5).
- Other GPS formats (MALA, Sensors & Software), live GPS, post-processed (PPK) corrections.

---

## 13. Left to the builder

- Where Import GPS lines… lives, and the summary's form.
- The bridged-stretch rule (§5.3) and how ends take their heading.
- The ruler angle threshold (C8, ~20°).
- How the map shows bridged stretches and GPS-vs-tape lines, within the existing symbology (#66).
- Drawing and reshaping the outline, after a mock-up the user has agreed (§6.3).
- Schema versioning details for the new placement type and the outline.

---

## 14. Open questions for the user

From the delay spike and the builder check. The answers go into §3 and the sections named.

1. **The along-track correction (§7).** Its form (one shift in metres, or a fixed offset plus a
   delay), its default, and whether nsgeo estimates it from a zigzag area.
2. **Profiles and trace spacing for GPS lines.** The profile view draws one equal-width column per
   trace, and migration and the velocity fit take their spacing from the wheel. On a GPS line the
   traces are not evenly spaced along the ground: lifts and slips squeeze metres into a few traces,
   and the wheel reads 1.5–3% short (15% on `FILE__011`). Either keep one column per trace with the
   wheel's spacing (zigzag profiles line up except near lifts and slips), or resample GPS lines to
   even spacing along the walked path so that the profile, migration and velocity fit all see true
   metres.
3. **Holes in GPS slices (§2).** Walked lines leave real gaps up to 1.58 m. At the default max
   distance a GPS area's slice is 3.5% holes. Either keep the default and show them as real gaps, or
   give areas a different default.

