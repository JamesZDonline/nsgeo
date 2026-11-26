# 3-D follow-ups (session S): design

Issues: #204, #203, #219, #218, #228. Branch `nsgeo-3d-follow-ups`, from origin/main ac1766e.
Background: the M16 spec (`2026-11-11-nsgeo-m16-3d-design.md`) and the decision records
`docs/superpowers/sdd/2026-11-13-nsgeo-m16-b-surfaces-from-picks` (R11, R15),
`2026-11-16-nsgeo-m16-c-qgis-3d-view` (R6) and `2026-11-16-nsgeo-m16-d-cuts`.

## Intent

These are the leftovers from the M16 Plan B, C and D reviews. A surface should read stale only
when a rebuild would change its numbers. Today two things mark surfaces stale when nothing has
changed: an untouched ParaView export, and a reopen without Save site. Separately, the 3-D view
should read each line's file once at most: today it re-reads a line that failed on every
refresh, and it reads time zero from a different channel than the volume is built from. Plan D
also left five small tidy-ups.

**Goals.**
- A surface stays fresh through an untouched export and through a reopen without Save site.
- The 3-D view reads a failing line once.
- The 3-D view, the export's record window and the surfaces all use one channel.
- #228's five items are done.

**Non-goals.**
- Building the 3-D work from the channel the user chose. That needs the choice saved per line,
  a schema change, so it is filed as #237.
- Saving the grid's 3-D settings without Save site.
- Moving the export's fill into the background (#236, session R).

**Anti-goals.**
- A fix that makes a surface read fresh while a rebuild would still change its numbers.
- Writing `survey.nsgeo.json` behind Save site's back.

## Decisions

### #204: one rounding for the 3-D cell

- Add `remembered_cell(cell, floor)` to `surface_plan.py`, beside `remembered_step` and
  `remembered_end`.
  - It rounds the cell to 3 decimals, the export dialog's precision, so a float tail such as
    `0.05000000000000002` or `0.04999999999999999` lands on `0.05`.
  - If the rounded value is finer than `floor` (the grid's `smallest_safe_cell`), it rounds up
    to 3 decimals instead.
  - It never goes below the dialog's minimum, 0.001.
- `ParaViewExport.defaults()` returns its cell through `remembered_cell`, so the dialog shows,
  and writes back, exactly the cell a build uses.
- The build (`Surfaces._compute`) and the `resolution` staleness input also apply it, as R11
  does for the depth step.
- *My call:* a surface built before this change at a float-tail cell reads stale once
  ("resolution"), because its stored hash has the unrounded cell. One Rebuild clears it. We
  accept that and say so in the PR and the release notes, rather than compare cells loosely.

### #203: an empty record falls back to the newest built surface (user, 2026-11-20)

- Each surface's json gains `"choice": choice.to_record()`: cell, depth step, depth end,
  transform, stretch, wave period and depth balance.
- When the grid's volume record is empty, `defaults()` reads its fields in this order:
  1. the grid's record (unchanged);
  2. the `"choice"` of the newest built surface on that grid that has one: the newest by
     `built_utc`, among the surfaces that still exist;
  3. the Slices panel's values, then the built-in defaults, as today.
- What follows from this:
  - The export dialog also opens on the last build's values on a grid like this. A saved
    record already behaves the same way (R10).
  - An export changed after the last build, then closed without saving, is forgotten.
  - Surfaces built before this change have no `"choice"`. They are skipped, and when none has
    one, the panel is used as today.
- The lookup lives on `Surfaces`, which lives as long as the plugin. `Surfaces._export()` makes
  a new `ParaViewExport` for every state check, so the lookup can't be kept there. The newest
  choice is kept per grid and cleared when a build writes, a surface is deleted, or the site
  changes. `defaults()` runs on every 3-D refresh and every state check, so it must not scan
  the folder on each call.
- *Rejected:*
  - writing the record to the site file at build time (behind Save site's back);
  - comparing each surface with its own build while the record is empty (the panel would call
    it fresh while a rebuild would still change its numbers).
- The guide's note under "Where your data lives" ("If you close without saving … the surfaces
  reopen marked stale") is reworded to match.

### #219: a failed time-zero read is remembered

- `_zero_of` remembers a failure under the same key as a success: the line plus the preset's
  steps.
- A later call raises the same error without reading the file.
- `pick_depths` logs a line only when the read actually happened, so it logs once per key.
- A changed preset gives a new key, and so does a new `ParaViewExport`, which is what a reopened
  site or a reopened 3-D view uses. Either one tries again.

### #218: channel 0 everywhere (user, 2026-11-20)

- `_zero_of` reads `profiles[0]`, as the line preparation does (`slices_engine.py`).
  `pick_depths` and `_record_range` follow from that.
- The guide gains one sentence: 3-D work (slices, surfaces, the 3-D view and the ParaView
  export) reads each line's first channel.
- *Rejected:* the chosen channel everywhere. The choice is kept in memory only, and opening a
  site clears it, so every surface would go stale at each reopen. That option is #237.

### #228 items 1, 3 and 5

- **Item 1.** In `Surfaces._compute`, a cut pick with no `distance_m` gets `WHY_NO_DEPTH`. It
  must be checked before the other-clock check, because `cut_pick_on_clock` already refuses a
  pick with no distance.
- **Item 3.** Put back the two assertions in `tests/qgis/test_plugin_surfaces_membership.py`:
  - a create that raises leaves nothing behind;
  - the mixed cut-and-line `grid_id` case.
- **Item 5.** `selection_refusal`'s docstring lists the deleted-cut refusal in its place in the
  order.

### #228 items 2 and 4: after session F merges

Both are in the Profile panel, which F rebuilds. Do them last, after merging main once F is in.
If F hasn't merged when the other work is done, ask the user whether to wait or to hand these
two to G.

- **Item 2.** One reader for a time base, in `surface_plan.py`. An empty, missing or unreadable
  time base reads as radar. `cut_pick_base` and the Profile panel's
  `_time_base_of_provenance` both call it.
- **Item 4: move the cursor once the section loads (user, 2026-11-20).**
  - Clicking a cut pick in the outlier list opens its cut, and the Profile panel holds the
    pick's distance along the cut.
  - When that cut's section arrives, the cursor goes to the column nearest that distance.
  - It uses the distance, not the stored column, because the column is wrong if the section was
    rebuilt at another cell size.
  - Opening anything else first drops the target.
  - The guide's "at that pick" then holds for cut picks too.

## Tests to pin (each fails on main before its fix)

- **#204.**
  - A surface built at `0.15 - 0.1` and at `0.1234` stays fresh after
    `remember_volume(grid, cell=round(cell, 3))`.
  - An untouched export of a float-tail cell leaves the record's cell alone, or moves it only
    to the value the build uses.
- **#203.** After a reopen in a new `SiteSession` without Save site:
  - changing the panel's transform, the wave period or the panel's cell leaves the surface
    fresh;
  - a rebuild uses the built choice.
- **#219.**
  - `_zero_of` reads and logs a failing line once over two `pick_depths` calls.
  - It reads it again after the preset's steps change.
- **#218.**
  - On a two-channel line set to channel 1, `pick_depths` puts a pick at the depth the surface
    builder gives it.
  - `_record_range` agrees with the prepared lines' window.
  - The test is synthetic, because every real file is single-channel, and it says so.
- **#228.**
  - Item 1's reason.
  - Item 3's two assertions.
  - Item 2: one reader, with the empty-base case.
  - Item 4: the cursor lands on the pick after the section loads.
- **Real data.** Everything except #218 also runs on the M16 walkthrough site, whose Grid1
  Slices cell is the float tail `0.05000000000000002`.

## Left to the builder

- Names and where small helpers live, beyond what is fixed above.
- How the 3-D view's refreshes are counted in the #219 test.
- How the Profile panel holds and drops item 4's target. This is fitted to F's code once it has
  merged.
