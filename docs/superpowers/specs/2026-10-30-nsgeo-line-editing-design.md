# nsgeo: line editing — Edit lines, move lines between grids, picks that follow their line

Issues #35, #64 and #29 together, plus the two cases added to #29 from the #67 walkthrough. After import, you can fix any line's placement in a table of the grid's lines, change several lines at once, and move lines to another grid. A grid edit that changes the grid's length takes its reversed lines with the far edge. Through all of it, every pick stays on its line.

---

## 1. What this is for

The correction table in **Import DZT files** is the only place a line's placement can be set. Fixing a line afterwards means removing it and importing it again, which:
- puts it at the bottom of the Survey panel (#29 part 2);
- leaves its picks where the old placement put them (#35, second comment);
- has to be done once per line.

**The case that settled it (#29, third comment).** On the user's real Sunnyside site, all 15 reversed lines on Grid 5 have Start = 16 m, but the grid is 15 m long. Every other grid's reversed lines start exactly at its length, so Grid 5 was most likely 16 m when imported and was shortened later. Since #67 the profile shows each of those lines starting about 1 m past the grid's far edge. The slices carry the same ~1 m stagger on every other line. Fixing it today means remove-and-re-import, 15 times. Start is read-only in the import table, so it is worse than that.

The user's words for what they wanted instead: *"I would have liked to be able to open an interface (maybe the Add lines dialog) that included all of the lines currently in the grid. There I could edit lines as I need. Selecting a group of lines and bulk editing them would seem like one good way to do that."*

**What a pick is (#35, the user's ruling).** *"A pick is a selected trace and time-depth on a particular line. If the line moves because the grid moves, the trace and time-depth will remain the same relative to that line and the pick should be changed accordingly."* The same applies to any other edit that moves a line. That is why #35 is in this bundle: without it, every edit here strands picks.

**What success looks like.** The user opens **Edit lines…** on Sunnyside Grid 5, selects all 30 lines, clicks **Snap to grid edge**, and clicks OK. The 15 reversed lines now start at 15 m. Their picks, if any, sit on them. The profile and the slices show no stagger. Separately: shortening a grid in **Edit grid…** moves its reversed lines with the far edge, so this never happens again.

---

## 2. Starting state (main at `8fcc37d`, #67 merged)

- **Placement** (`nsgeo-core`, `geometry/placement.py`): `GridPlacement(grid_id, axis, offset, start_along, direction, label)`, frozen. `distance_along = start_along + direction · i / traces_per_metre`. `start_along` is stored as an absolute number in the grid frame.
- **Import** (`ui/import_dialog.py`, `lookup.py`): `ImportRow` carries `offset_edited`, `label_edited`, `direction_edited`. `recompute_offsets` re-derives every un-edited row on each edit. A reversed row's `start_along` is `options.start_along + grid_size_along`. The Start cell is read-only because a typed value would go stale on the next recompute.
- **Session** (`session.py`):
  - `add_lines`, `remove_lines` and `remove_grid(with_lines=)` each make one change: one dirty mark, one `lines_changed`.
  - `set_line_velocity` is the one-line edit pattern.
  - `replace_grid` emits `grids_changed` then `lines_changed`. `set_grid_velocity` goes through it.
  - `keys_on_grid` returns keys in survey order (`site.lines` order), and the Survey panel shows them in that order.
  - `slice_sources[grid_id]` remembers `preset`, `lines` (`None` = every line) and `gain`.
- **Picks** (`layers.py`, `session.Pick`):
  - Fields: `line_key`, `trace`, `time_ns`, `distance_m`, `depth_m`, `velocity_m_ns`, `stack_json`, `note`, `created`, `feature_id`, `seq`.
  - `distance_m` comes from `line.distance_along()`, so it depends on Start and Dir.
  - `_pick_point` places a pick once, at write time. Nothing re-derives it, except a CRS change through `_rebuild_picks`.
  - `_warn_if_a_placed_grid_moved` (M8 Ruling 20, a stopgap) warns when a grid with picks moves. It never fires for remove-and-re-import, or for a line that moves without its grid moving.
  - The README tells the user to edit picks "with the ordinary tools" but not to drag them. The guide's *4. Where your data lives* explains the warning.
  - `picks` is the one table the survey JSON cannot regenerate. It has had its storage repaired twice, and #22 (buffered edits lost in a picks rebuild) is still open.
- **Slices:**
  - `SliceEngine._grid_fingerprint` is `(origin, azimuth, size_x, size_y, crs)`. `_on_grids_changed` re-prepares only when that changes.
  - `SlicesDock.rebuild_source` leaves a prepared source alone on `lines_changed`.
  - `SiteEngine` holds one engine per grid and re-queues a grid on `on_grid_moved`.
  - So a line whose placement changes keeps being binned at its old coordinates until the source is chosen again. #64 and #29 both flag this.
- **Survey panel** (`ui/survey_dock.py`):
  - One reused `QMenu`, cleared on each right-click. The code relies on there being no submenus for `clear()` to leave nothing behind (#64 flags this).
  - Grid menu: Edit grid…, Import DZT files…, Set velocity…, Remove grid.
  - Line menu: Open, Set velocity override…, Remove line from site.
  - A multi-selection offers only Remove.
- **Profile (#67):**
  - Reversed lines are mirrored.
  - Each grid and axis has one ruler, `[0, grid size along]`, widened by any line past the edge.
  - A Start that is wrong shows directly as a line that overruns or falls short.
- **M15 (designed, unbuilt):** picks on a cut go in the same `picks` table, keyed by a cut key that cannot collide with a line key. They are written once. A redrawn cut is a new cut.

---

## 3. Decisions

### Taken by the user

1. **A pick is a trace and a time on its line, and it follows the line** through every change that moves the line: a grid edit, a line edit, a move to another grid, and remove-and-re-import (#35).
2. **Edit lines… is a sibling of the import dialog,** not the import dialog itself. It opens from a grid's right-click and shows every line on that grid in a table. It doesn't change Import DZT files.
3. **Bulk editing is a panel under the table** (mock-up option A; the user chose it over type-to-fill and a right-click menu). With rows selected, the panel changes those lines together.
4. **A reversed line's Start counts from the grid's far edge,** the way a forward line's counts from the near edge. In practice:
   - **The grid's length changes:** its reversed lines move with the far edge. Grid 5 going from 16 to 15 m should have moved its reversed lines to 15 m.
   - **A line moves to a grid of a different length:** a reversed line lands at the new grid's far edge.
   - **Dir flips:** Start goes to the other edge (0 ↔ grid length).
5. **The grid's width changing moves no lines.** A line that ends up outside the grid gets a warning, not a refusal (#64).
6. **Existing bad placements are fixed by hand,** in Edit lines. There is no one-off repair. Nothing can tell a stale 16 m from a deliberate one.
7. **A pick's depth and velocity follow the line's current velocity.** In the user's words: *"the pick is on the reflection in the profile, depth and velocity should be updated to whatever is considered an accurate description of where that reflection is."* So whenever a line's resolved velocity changes, its picks' `depth_m` and `velocity_m_ns` are worked out again from their time. That covers a grid velocity edit, a line override set or cleared, an applied fit, and a move to a grid with a different velocity. A pick does not keep the velocity it was made with.

### Calls made by Claude (check these)

1. **One rule behind decision 4, the edge inset.** A line's inset `d` is its distance in from the edge it starts at. For a forward line, `start = d`. For a reversed line, `start = L − d`, where `L` is the grid's size along the line's axis (`size_y` for lines along y, `size_x` for lines along x). Each change in decision 4 keeps `d` and recomputes Start:
   - **Length change:** a reversed line moves by ΔL; a forward line doesn't move.
   - **Flip:** a forward line at 0.2 becomes a reversed line at `L − 0.2`.
   - **Move to another grid:** `L` is the new grid's.

   **Snap to grid edge** sets `d = 0`. For the ordinary case `d = 0`, so every rule above gives exactly what the user agreed to. Import's own rule (`start_along + L` for reversed rows) is left alone (non-goal 1).
2. **A dragged pick goes back to its line.** Pick attributes (a note, say) stay editable in QGIS. The geometry does not stay where it was dragged. How it is enforced is left to the builder (§9).
3. **A pick whose line is not in the site is left exactly where it is.** That covers a removed line, and a future M15 cut pick, whose key is not a line key.
4. **Every derived field is worked out again on the same path.** The map position and `distance_m` follow the line's placement, since `distance_m` depends on Start and Dir. `depth_m` and `velocity_m_ns` follow its resolved velocity (decision 7). All of them use the computations `add_pick` already uses: `_pick_distance`, and `resolved_velocity(key).depth_at` / `.velocity_at` at the pick's time. That way a re-derived pick is identical to one made fresh at the same trace and time.
5. **Picks the next refresh updates are reported once.** After an upgrade, or on a site whose grids or velocities changed since its picks were made, the first refresh puts every pick back on its line, with its depth at the current velocity. The message bar says how many picks were updated, so it is not silent. A move caused by an edit the user just made needs no message beyond the dialog's own count.
6. **A changed grid length says what it moved.** After an Edit grid that moves reversed lines, the message bar says e.g. "Grid 5 is now 15.00 m long; its 15 reversed lines moved with the far edge."
7. **Survey-panel entries:**
   - Grid: **Edit lines…**, greyed when the grid has no lines.
   - One line: **Edit line…**, which opens the grid's table with that row selected.
   - A selection on one grid: **Edit N lines…**, opening with those rows selected.
   - Any line selection, one or several, on any grids: **Move to grid ▸**, listing every grid. Lines already on the chosen grid are left as they are.
   - A selection spanning grids gets no Edit entry, because the table shows one grid.
8. **The table's columns.**
   - Editable: **Label, Offset, Dir, Start, Grid.**
   - Read-only: **Along** (the axis), **Traces**, **Length**, **Picks** (how many picks the line has), **Note**.
   - **Note** flags a line whose Start is off its own edge (inset `d` beyond a few centimetres either way), and a line whose offset is outside the grid's width. It never judges the far end. Where a line ends depends only on how far it was walked.
   - Measured on Sunnyside's 210 lines (builder check, then re-checked from `survey.nsgeo.json`): correctly placed lines run up to 1.12 m past the far edge (Grid 8). The only Starts off their edge are Grid 5's 15 reversed lines, each by exactly 1.00 m. So this rule flags those 15 and nothing else. A rule on the far end could not do that.
   - Example Note text: "starts 1.00 m past the far edge".
9. **Row order is survey order.** ↑/↓ in the table reorders the grid's lines, and the Survey panel follows on OK. This is #29 part 2, fixed after the fact rather than at import.
10. **Nothing changes until OK, and OK is one change:** one dirty mark and one `lines_changed`, however many lines changed. Cancel discards everything. Changed cells are highlighted until then. A status line reads "N lines changed · M picks will move with them".
11. **No live map preview** while the table is open. You see the result after OK.
12. **A line moved to another grid joins it the way an imported line would** for the remembered slice lines. It leaves the old grid's `slice_sources[…].lines` list if it was in one.
13. **This branch is cut from main at `8fcc37d`.** The slices cleaning round (`nsgeo-slices-cleanup`, planned, not built) also touches the Slices panel. Whichever merges second resolves the overlap.
14. **The table holds edits, not a copy of the lines.** Lines can change elsewhere while it is open: Edit grid, Move to grid ▸, another grid's Edit lines table, or remove-and-re-import. So OK works like this:
    - **Only the fields the user changed are written,** on top of each line's placement as it is at OK.
    - **Starts that come from the inset rule** (Flip, Snap, a Grid change) are worked out again at OK, against the grid's length as it is then.
    - **A line changed both here and elsewhere** since the table opened is skipped, and the dialog names it.
    - **Lines that arrived on the grid** while the table was open go after the reordered ones.

    This way OK never undoes a concurrent length edit's move of the reversed lines, and never rewrites a line the user didn't touch.
15. **A restored cube that names a line now on another grid** drops that line, and the restore says so. Restoring prepares from today's placements, as it already does after an Edit grid.

---

## 4. Behaviour

### 4.1 The Edit lines table

The mock-up is `.lavish/edit-lines.html` in the main checkout. The layout follows it.

- **Title and header:** the title is "Edit lines · ‹grid›". A header line gives the grid's size and its number of lines.
- **Rows:** every line on the grid, in survey order. ↑/↓ move the selected rows.
- **Cells:**
  - **Label:** free text.
  - **Offset:** metres across.
  - **Dir:** ±1. Flipping it also moves Start, by call 1.
  - **Start:** metres along, editable here, unlike in Import.
  - **Grid:** any grid in the site. Choosing another grid recomputes Start by call 1 and keeps offset, axis and label. The row stays in the table, showing its new grid, until OK.
- **Bulk panel** under the table, titled "Change the N selected lines" and greyed when nothing is selected:
  - **Start:** a value and **Set**, plus **Snap to grid edge**.
  - **Offset:** a value and **Shift**. Lines move by that much. Setting several lines to one offset would stack them, so that isn't offered.
  - **Dir:** **Flip**.
  - **Grid:** a grid and **Move**.
  - Labels have no bulk control.
- **OK:** applies the edits; see 4.2. **Cancel** applies nothing.
- **The dialog stays usable while open**, like Import DZT files. The site can close, the grid or some of its lines can be removed, and its lines can change elsewhere, all while it is open. OK re-checks before writing and follows call 14. It applies only to lines still present and says what it skipped. It never raises out of a slot.

### 4.2 What applying an edit does

All of these happen as one change, through a new session method in the same one-change style as `remove_lines`:
1. Each line gets its new placement: a different label, offset, direction, Start or grid.
2. The grid's lines take the new order.
3. Moved lines leave the old grid's remembered slice lines (call 12).
4. Lines are redrawn and their picks follow (4.4).
5. Slice sources that use any changed line prepare again (4.5).
6. The open profile reflects the change if its line was edited.

A line's key is its file path. Its processing stack, velocity override, picks and open state stay attached through every edit.

**Move to grid ▸** from the Survey panel is the same operation, with only the Grid field changed.

### 4.3 A grid whose length changes

When `replace_grid` changes a grid's size along an axis, every reversed line along that axis on that grid moves by the change (call 1). This happens in the same change as the grid edit, before the signals are emitted, so the map, picks and slices only ever see the consistent result. A velocity-only edit, or one that changes only the width, moves no lines. The message bar reports the move (call 6).

### 4.4 Picks follow their line

- On every refresh that follows `grids_changed` or `lines_changed`, and when a site opens, each pick on a line in the site gets its derived fields worked out again (call 4).
  - Its map position and `distance_m` come from `line_key` and `trace`. The position uses the same `_line_points` path the lines layer is drawn from, so the pick sits exactly on the line's vertex.
  - Its `depth_m` and `velocity_m_ns` come from `time_ns` and the line's resolved velocity now.
  - Every velocity change already reaches a refresh. `set_line_velocity` emits `lines_changed`, and `set_grid_velocity` goes through `replace_grid`, which emits both signals. The builder confirms this holds for an applied fit.
- A pick's `trace`, `time_ns`, `stack_json`, `note`, `created`, `feature_id` and `seq` are never changed by this.
- Only rows whose values actually change are written. They are updated in place through the loaded layer's provider. The table is never truncated or rebuilt for this.
- Picks on keys that are not site lines are untouched (call 3). So are picks on a line that cannot be placed (no grid frame, or a time-triggered file with no distance axis).
- A pick dragged on the map goes back to its line (call 2).
- Attribute edits are never lost. That includes edits buffered while the picks layer is in editing mode, the #22 hazard.
- **Removed:** M8's moved-grid warning (`_warn_if_a_placed_grid_moved` and the cached placements that drive it), the README's "do not drag a pick" paragraph, and the guide's "A pick's map position is fixed" bullet. #55's third bullet goes with the warning.

### 4.5 Slices see the new positions

A prepared slice source must not keep binning a line at its old position. A source prepares again when:
- a line in it changes placement;
- a line in it moves to another grid;
- a line moves onto its grid, and the source takes every line (`lines = None`).

This applies to the This grid engine and to each of Whole site's per-grid engines (M12). It is the "re-prepare on a placement change" step #64 and #29 both asked for, built once. A change that touches no line in a source leaves it alone, so editing one grid's lines doesn't re-prepare every grid's engine.

**A line moved off a grid has to leave that grid's source choice, not just trigger a re-prepare.** Found by the builder check:
- `SlicesDock._sync_included` checks a chosen line list against every key in the site, not the grid's own lines (`ui/slices_dock.py:839-840`).
- `SliceEngine.set_source` places each key on that line's *current* grid (`slices_engine.py:584-587`).

So re-preparing A's unchanged choice would bin a line now on B into A's slices, at its position on B. The This grid choice, and the remembered `slice_sources[A].lines` (call 12), both drop it. Whole site is already safe: `site_scope.source_keys` keeps only the grid's own lines. Restoring a saved cube follows call 15.

---

## 5. Goals, non-goals, anti-goals

**Goals:** everything in §3 and §4. When done, this closes #35, #64 and #29 (parts 1–3 and both cases from its third comment). It covers the placement part of #58.

**Non-goals:**
1. **Import DZT files is unchanged.** Its Start stays derived, and its reversed-row rule stays `start_along + L`.
2. Bulk presets and bulk velocity overrides. Those are the rest of #58.
3. Dragging lines between grids in the Survey panel, editing a line's axis, and undo.
4. **Re-processing never moves a pick.** A pick's trace and time stay as they were made, even if the line's processing changes later, such as migration (M14) moving the reflection it was made on. `stack_json` records what the pick was made on.
5. A repair pass over old sites (decision 6). Re-placing M15 cut picks (call 3).

**Anti-goals** (failures, even if everything else works):
- A pick that ends up anywhere but on its line's trace, or a pick row or note that is lost.
- A placement edit that leaves the slices, the map or the profile showing the old position.
- A bulk change that touches a line the user didn't select, or any change that lands before OK.
- A grid length edit that leaves reversed lines overrunning, or falling short of, the edge they were placed at.

---

## 6. Documentation

- **Getting-started guide:**
  - The Survey panel section gains **Edit lines…** and **Move to grid ▸**.
  - *4. Where your data lives* replaces the fixed-position bullet with one line: a pick follows its line, so editing a grid or a line moves its picks too, and dragging a pick on the map does not move it.
- **README:** the Picking paragraph says the same. It also says that a pick's depth and velocity follow the line's current velocity (decision 7).
- **Issues:** close #35, #64 and #29 with the PR. Tick #55's third bullet as moot. Comment on #58 that its placement part is done.

---

## 7. Testing and the walkthrough

- **Real data is the main check.**
  - The test fixtures are `nsgeo-core/tests/data/local/FILE__001`–`010`.
  - The walkthrough runs on the user's Sunnyside site (`~/nsgeo-m4-check/Sunnyside/`): Grid 5's 15 reversed lines at 16 m on a 15 m grid, fixed with one Snap to grid edge. Keep a copy of the site folder first.
  - It runs on a new QGIS profile, `ns_geo_lines` (a copy of `ns_geo`, symlinked to this worktree).
- **Pure tests** for the edge-inset rules (call 1): flip, snap, move to another grid, length change. Both axes, and lines that start outside the grid.
- **A real-data check of the Note rule** (call 8): on Sunnyside's placements it flags exactly Grid 5's 15 reversed lines, and none of the other 195 lines.
- **QGIS-tier tests:**
  - Picks follow a grid edit, a line edit, a move, and remove-and-re-import.
  - Picks on unknown keys stay put.
  - A pick's depth and velocity follow a grid velocity edit, a line override, an applied fit, and a move to a grid with another velocity. Each matches a pick made fresh at the same trace and time.
  - A note typed in editing mode survives a refresh that moves its pick.
  - The slices re-prepare on a placement change, and only for sources that hold the line.
  - The Survey panel's submenu leaves nothing behind after `clear()`.
- **Hazards to test head-on:**
  - Both axes on one grid, and a reversed line on a grid whose other axis changes.
  - A line moved while it is the open line, and while it is in a prepared source on each grid.
  - The dialog open while its grid is removed.

---

## 8. Size

L: this document, then a plan of about 5–6 tasks plus the walkthrough. The plan sets the split. One possible order:
1. Picks follow their line (#35's core, with its own careful review).
2. The session operation and the pure rules, plus a grid length change taking its reversed lines with it.
3. Slices re-prepare.
4. The Edit lines table.
5. The bulk panel and Survey-panel entries.
6. Docs, deploy and the walkthrough.

---

## 9. Left to the builder

- **How a dragged pick is sent back** (call 2). Options include reverting the geometry change when the edit is made, refusing geometry edits at commit, or re-deriving on the next refresh. Any of these works, so long as attributes stay editable and #22's buffered-edit hazard is not made worse.
- **The session API's shape,** within call 14 (it takes edits, not whole placements). For example, one `edit_lines(edits, order)` that both the table and **Move to grid ▸** call. Also where the pure rules live (`lookup.py` is the precedent).
- **How slices notice a placement change** (4.5). For example, a fingerprint over the source's lines' placements next to the grid's.
- **The Start tolerance** for Note (call 8). A few centimetres; Sunnyside's correct Starts are exact.
- **How the table is built:** reusing pieces of the import table's code or not, and how changed cells are highlighted.
