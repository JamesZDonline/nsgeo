# nsgeo a grid velocity from its fits — design

A grid's **Set velocity…** opens a velocity dialog for the grid. It lists every saved hyperbola
fit on the grid's lines, averages the ones you tick, and sets the grid's velocity from that
average. The grid remembers which fits made its velocity. A line's own velocity dialog gets the
same tick boxes and average. Slices and their exports, like cuts, take their depths from the
grid's velocity, never from one line's override.

Closes #127 and #86 (the averaging; Dix conversion stays where the velocity spec put it, §11).
Fixes a slice-depth defect found while designing this (§10), not yet filed.

Comes after two other branches, which both touch files this one changes:
- **Piece 1** (`nsgeo-fit-marks`: #126 fit counts in the Survey panel, #128 Save fit clears the
  points). Its Apply-after-Save behaviour is what §7.4 extends.
- **Fine-cell export** (`nsgeo-fine-cells-export`), which moves the export's velocity call in
  `plugin.py`.

Build from main after both have merged.

---

## 1. What this is for

The author measures velocities by fitting hyperbolas on several lines of a grid. What they need
at the end is **one velocity for the whole grid**, because slices are built per grid. In their
words:

> I measured velocities on several lines, but I couldn't see what I'd measured without going
> into each line I measured and opening the velocity override dialog. and I couldn't find which
> lines I'd done easily because there was no mark of them. And even if I did find them, I had to
> keep track myself of what the numbers were if I was wanting to find a number that could work
> reasonably well for the whole grid which is important because slice takes a preset that is
> per-grid, not per-line

How they get from several numbers to one: **"I was going to average them."**

Piece 1 answers the first half (which lines have fits). This design answers the rest: see every
fit on the grid together, average them, and set the grid's velocity from the average.

Earlier requests for the same thing:
- M13 walkthrough (#86): *"It'd be great to let you select the ones you want to use (check box)
  and then do something like take the average of the selected ones."*
- 2026-11-06 (#86): *"See the average of all velocity estimates for a context (in a line if
  velocity override for line, in a grid if velocity set in grid)"*
- 2026-11-06 (#127): *"The ability to see all velocity estimates in a grid (in survey panel right
  click grid and click velocity takes me to a dialog like the velocity override, not the edit grid
  dialog)"*

Why the grid remembers its fits: **"for reproducibility sake"**. Months later, the project
should still say where a grid's velocity came from.

## 2. Starting state (main 15dea4c, plus piece 1)

- **Fits.** `Line.velocity_fits` maps a fit id (`fit-1`, `fit-2`, …) to a `StoredFit`
  (`nsgeo/velocity_fit.py`): `t0_ns`, `v_m_ns`, `v_stderr_m_ns`, `rms_ns`, `apex_trace`,
  `points`, `fitted_at`, `zero_ns`. Fits are never edited, only added and deleted.
- **Fit ids are reused.** `SiteSession.add_velocity_fit` numbers from the count: delete `fit-2`
  of two, and the next save is `fit-2` again.
- **A line remembers one fit.** `Line.velocity_from_fit` names the fit behind the line's
  override, or `None`. `remove_velocity_fit` clears it when that fit is deleted, and the
  velocity stays ("it was applied deliberately, and only the claim that this fit produced it
  goes"). `load_site` drops a pointer naming a fit that is not there.
- **A grid remembers nothing.** `Grid.velocity` is a bare `VelocityModel | None` (optional since
  #4).
- **The line's dialog** (`ui/velocity_dialog.py`, modal): a velocity box, a table of the line's
  fits (t0, v ± σ, rms, points, a "disagrees with another fit" flag at 2σ), Delete fit
  (immediate, confirmed), Apply / Clear override / Cancel. Picking a row puts that fit's
  velocity in the box. `selected_fit_id()` is the picked fit unless the box has moved off its
  velocity (compared to 4 dp).
- **A grid's Set velocity…** (Survey panel) emits `grid_velocity_requested`, which `plugin.py`
  connects to `open_grid_dialog`: the whole Edit grid dialog. Its velocity box keeps the stored
  model when the value is unchanged to 4 dp (`GridDialog._result_velocity`).
- **The profile's velocity source label** (`velocity_source` in `ui/profile_dock.py`) reads
  `line override (fit at 15.6 ns)`, `line override`, `Grid G2` or `header ε 9`.
- **Cuts** take their velocity from `SiteSession.cut_velocity(grid_id)`: the grid's velocity,
  else the header dielectric of the grid's first line. A line override is ignored on purpose
  (cut spec call 16).
- **Slices do not** (§10).
- **Project file versions** (`nsgeo/project.py`): a site saves as version 1, or 2 when it has
  cuts, so a build older than cuts refuses the file instead of dropping the cuts. The current
  build reads 1 and 2.

## 3. What the author decided

1. A grid's **Set velocity…** opens a grid velocity dialog: the line dialog's layout plus a Line
   column, tick boxes and an average (§4).
2. A line's velocity dialog gets the same tick boxes and average (§5).
3. Fits are averaged whatever their depths. The author needs one number for the grid. This
   overrides the velocity spec's §7 ("No averaging"). The depth range and a disagreement warning
   are shown beside the average (§6), so a layered site is visible, not blocked.
4. **The grid remembers which fits made its velocity, for reproducibility** (§7). This changes
   the project file (§9).
5. Fit ids are never reused (§8).
6. Slices and their exports use the grid's velocity (§10).

Calls I made, shown to the author with no objection ("nope" to "anything wrong or missing"):
- **The average is weighted** by each fit's σ (§6).
- **Lines with their own velocity are starred** in the grid dialog and never changed by the
  grid's Apply.
- **Edit grid keeps its velocity box.** An unchanged value keeps the remembered fits. A changed
  value drops them.
- **Apply to grid on the profile strip** records the fit it applied, when that fit is saved
  (§7.4).
- **GeoTIFF and cube exports** record the velocity number, as now, not the fits behind it.

Mockup the author reviewed: `.lavish/grid-velocity.html` in the main checkout. It is
gitignored, so this document describes everything that matters in it.

## 4. The grid velocity dialog

Opened from the Survey panel, grid row › **Set velocity…**. It replaces Edit grid on that menu
item only. Edit grid stays on its own menu item. The dialog is modal, like the line dialog.

Title `Velocity · <grid id>`. Top to bottom:

1. **Velocity (m/ns)** box, as in the line dialog, holding the grid's velocity, or 0 ("required")
   when the grid has none. Beside it, a hint: *Slices and cuts on this grid use this velocity.*
2. A label: *Saved hyperbola fits on this grid's lines. Tick fits to average them; pick one to use
   its velocity.*
3. **The table.** One row per fit on every line currently on this grid. Columns: tick box,
   **Line** (the line's label, as the Survey panel shows it), t0 (ns), v ± σ (m/ns), rms (ns),
   points, flag.
   - Sorted by line, in survey order, then by t0. Clicking a column header sorts by that column.
     Sorting by t0 shows a depth trend if there is one.
   - A header tick box ticks or unticks every row.
   - A line with its own velocity override shows `*` after its name. A note under the table names
     those lines and their velocities: *\* FILE__008 has its own velocity (0.0889). Apply doesn't
     change it.* The note appears only when such lines exist.
   - The flag column is the 2σ "disagrees with another fit" flag, across all the grid's fits.
     `disagreeing_fit_ids` already takes any mapping. Its keys here must be (line key, fit id)
     pairs, because every line has a `fit-1`.
   - Clicking a row selects it and puts that fit's velocity in the box, as the line dialog does.
     If the selected fit's line is the one open in the Profile panel, its curve is highlighted
     there, as the line dialog does.
4. **Delete fit**, for the selected row. It acts at once and asks for confirmation, as in the line
   dialog. When the fit is a member of this grid's remembered velocity, or of any line's, the
   confirmation says so and adds that the velocity stays as it is.
5. **Average of the ticked fits** group (§6): the average and its ±, a **Use average** button that
   puts the average in the box, the count and the depth range, a disagreement warning when it
   applies, and a short note that the average is weighted.
6. **Remembered-velocity note** (§7.3), when the grid's velocity came from fits.
7. Buttons: **Clear grid velocity** (sets the grid's velocity to none, and forgets the fits),
   **Cancel**, **Apply** (default).

Nothing but Delete fit changes the project before Apply, as in the line dialog.

**When it opens**, every fit is ticked, unless the grid remembers fits (§7.3).

**A grid with no fits** shows an empty table and an empty average group (*No fits on this grid's
lines yet*), and still works for typing a velocity, so the menu item never loses what Edit grid
gave it.

## 5. The line velocity dialog

It gains the tick boxes, the header tick box, the average group with **Use average**, and the
remembered-velocity note, exactly as in §4 but over that line's fits. It has no Line column and no
starred-lines note. Its Apply and Clear override work as now, plus §7.

## 6. The average

- **Weighted mean.** Each ticked fit counts by `w = 1/σ²` (σ = `v_stderr_m_ns`). The average is
  `Σ w·v / Σ w` and its ± is `1/√(Σ w)`. One ticked fit averages to itself.
- **Shown as** `0.0896 ± 0.0014 m/ns`, and under it `6 fits on 4 lines · t0 from 9.8 to 22.4 ns`
  (the line dialog says `3 fits · t0 from …`). Same digits as the table.
- **A fit with σ that is zero, negative or not finite** cannot be weighted. If one is ticked,
  the average is not shown, and the group says which fit and why. Such fits should not exist; this
  only makes sure a bad one is never silently weighted as infinitely precise.
- **Nothing ticked:** *No fits ticked*, and Use average is disabled.
- **Disagreement warning.** When any two ticked fits disagree by the 2σ rule:
  *Some ticked fits disagree with each other. The ground may be layered, and one number may not
  suit every depth.* It is a warning only. It never blocks the average.
- The arithmetic lives in the core (numpy-only, next to `velocity_fit.py`). The dialogs only call
  it.

## 7. Remembering where a velocity came from

### 7.1 What is remembered

A **velocity source** record says where a line's or a grid's velocity came from. It holds:
- **The member fits**, each as (line key, fit id).
- **A copy of each member's numbers as they were** when applied: t0, v, σ and `zero_ns`, plus the
  line's label at the time. This is what makes the record reproducible after a member fit is
  deleted, or its line is removed or moved.
- **How the velocity was made:** `weighted mean` (Use average, one or more fits) or `fit`
  (a single picked fit).
- **The result:** v and σ.
- **When**, as ISO-8601 UTC.

A grid has one optional record. A line has one too. The record replaces `velocity_from_fit`:
a single picked fit is a record of one member made by `fit`. Old files' `velocity_from_fit` loads
as that one-member record.

This departs from the comment on #86 ("a combined velocity will be stored as its own fit record"
in the line's fit list). A grid's average spans lines, so it cannot sit in one line's list. And a
combination stored among a line's fits would be counted as a fit by piece 1's marks and could be
averaged into another combination.

### 7.2 What Apply records

At Apply, the box's value (to 4 dp) decides, in this order:
1. It equals the **average of the ticked fits**: record those fits, made by `weighted mean`. The
   velocity applied is the unrounded average, not the box's 4-dp rounding. This mirrors how
   `VelocityDialog.velocity()` applies a fit's own velocity.
2. It equals the **selected fit's** velocity: record that fit, made by `fit`, as today.
3. It equals the velocity already in force, untouched: keep the existing record as it is.
4. Anything else is a typed number: the velocity is set, and any record is dropped.

Clear grid velocity, and Clear override on a line, drop the record with the velocity.

Edit grid: an unchanged velocity keeps the record, and a changed one drops it (rule 3 and 4).

### 7.3 When a member changes

Fits are never edited, so a member can only go away. That can happen in three ways:
- the fit is **deleted**;
- its line is **removed** from the survey;
- for a grid's record, its line is **moved to another grid**.

In all three cases the velocity and the record stay as they are, with the copied numbers. This
follows `remove_velocity_fit`'s rule for a single fit: the velocity was applied deliberately.
What changes is how the dialog describes the record.

**The note in the dialog** says where the velocity came from, under the average group:
- All members present: *This velocity is the average of 6 fits (applied 2026-11-12).*
  For a single fit: *This velocity is FILE__003's fit at 15.6 ns.*
- Some gone: *This velocity is the average of 6 fits (applied 2026-11-12). 1 of them is no longer
  on this grid: FILE__003's fit at 31.0 ns (deleted).* The reason is one of deleted, line
  removed, or moved to grid X. The average group still shows the average of whatever is ticked
  now, so the old and new numbers sit side by side.

**Reopening the dialog** ticks the record's members that are still present, and unticks the
rest. With no record, every fit is ticked.

**Deleting a member** keeps the record, unlike today, where `remove_velocity_fit` clears
`velocity_from_fit`. The copied numbers are what the author asked to keep.

### 7.4 The profile strip

**Apply to line** and **Apply to grid** on the profile strip act on the working fit, or, after
piece 1, on the fit just saved.
- Applying a **saved** fit records it, made by `fit`.
- Applying an **unsaved** working fit records nothing (a typed-equivalent bare number). This is
  today's rule for lines, extended to grids.

### 7.5 Where the record shows

- **Survey panel, grid row:** `v 0.090 (average of 6 fits)`, or `v 0.090 (fit on FILE__003)`, or
  `v 0.090` alone.
- **Survey panel, line row:** the existing `v 0.089*` marker, unchanged.
- **Profile velocity source label:** `Grid G2, average of 6 fits`, `Grid G2, fit on FILE__003`,
  `line override, average of 3 fits`, `line override (fit at 15.6 ns)` as now.
- **Slices panel velocity label:** it reads `velocity_source`, so it follows (§10).
- **Exports:** the velocity number only, as now.

## 8. Fit ids are never reused

A fit id, once used on a line, is never given to another fit on that line, across deletes, saves
and loads. A record copies the member's numbers anyway, but an id that came back would make a
record name a different hyperbola than the one it copied.

How is the builder's call. A per-line counter saved with the line is the obvious way. Files
without one start from one past the highest existing number.

## 9. The project file

- A site **with any velocity source record** saves as **version 3**, and this build reads 1, 2
  and 3.
- A site **without one** saves as it does today, 1 or 2, so 0.4.0 can still open it. This is how
  M15 bumped the version for cuts.
- A version 3 file may or may not have cuts. The version only says "this file needs a build that
  knows velocity sources and cuts".
- An old file's `velocity_from_fit` loads as a one-member record (§7.1). The site then saves as
  version 3 the next time it is saved. That is intended: an older build would drop the record.
- If the fit-id counter (§8) needs saving, it follows the same rule. It is harmless to an older
  build only while no record names an id.
- A record that names a line or fit the file does not have still loads. Its copied numbers are
  what it is for. This is unlike `velocity_from_fit` today, which is dropped.
- Round trip: save then load gives back equal records, including the copied numbers bit for bit.

## 10. Slices use the grid's velocity

**The defect.** A slice's depths come from the first line of the grid, through
`SiteSession.resolved_velocity(first_key)`. That resolves the line's override first. With
overrides set on lines from their fits, a slice's depth labels and its export follow whichever
line happens to be first in survey order, not the grid's velocity. Three places:
- `SliceEngine.provenance()` (`slices_engine.py`, the `for line in self._lines` loop): the
  velocity recorded in cubes and exports.
- `SlicesDock._resolved_velocity` (`ui/slices_dock.py`): the readout and the velocity label.
- `site_scope.grid_velocity` (`ui/site_scope.py`): each grid in Whole site.

**The fix.** All three use the rule cuts already use (`cut_velocity`): the grid's velocity, else
the header dielectric of the grid's first line. A line's override never reaches a slice. Rename
or generalise `cut_velocity`, so slices and cuts share one rule and one name. The Slices panel's
label names the grid as its source, e.g. `v = 0.090 m/ns (Grid G2, average of 6 fits)`, or
`(header ε 9, FILE__001)` when the grid has no velocity.

**Why it belongs here.** It is what makes the grid dialog's hint true, and it is the reason the
author wants a grid number at all.

The fix keeps the existing guards: a removed first line must not blank a valid slice (the
KeyError handling in both places stays).

## 11. Non-goals and anti-goals

**Non-goals**
- Dix conversion, layered velocity models, or velocity varying with depth. A grid gets one
  constant velocity.
- A site-wide average across grids.
- Changing line overrides from the grid dialog. The grid's Apply leaves them alone, and the
  dialog says so.
- Listing the fits in GeoTIFF or cube metadata.
- Marking hyperbolas more precisely (#88, #140). Those come later.

**Anti-goals** (would make this a failure even if it works):
- **A record that claims more than it knows.** If the remembered fits are not what made the
  number, the record is worse than none. Rule 4 in §7.2 exists for this, as M13 kept Save from
  setting provenance.
- **A ± that looks better than it is.** The weighted ± assumes independent fits. Hand fits are.
  #140's automatic tracing must keep that true (its own issue says so).
- **A file an older build silently damages.** That is why the version rule in §9 exists.

## 12. Testing

- **Real data first** (memory: real files are the primary validation). Real lines are linked at
  `packages/nsgeo-core/tests/data/local/` (`grid2/`, and FILE__001–010 at the root, whose
  diffractions #125 lists: FILE__003 trace 283 at about 15.6 ns, FILE__006 trace 544, FILE__008
  trace 370). Use them where they add something:
  - a project of real lines with fits and records saved and loaded;
  - the slice fix on a real grid **with an override on the grid's first line**.
- **The slice fix must test the hazard input.** A grid whose first line in survey order has its
  own override, different from the grid's velocity. Assert the slice label, the readout's
  metres, the provenance velocity and Whole site all use the grid's. A test that avoids the
  override on the first line proves nothing (memory: tests that dodge the hazard).
- **Core:**
  - the weighted mean and ± against hand-computed values;
  - one member;
  - the invalid-σ refusal;
  - records: save/load round trip, version 1/2/3 choice, old `velocity_from_fit` → record,
    a record naming a missing line or fit still loads;
  - fit ids not reused across delete → save → load → add.
- **QGIS tier:**
  - grid dialog: rows across lines, the star and note, ticks and the header tick, Use average,
    each §7.2 Apply rule, Clear, Delete fit with the member warning, reopening ticks the
    record's members, the §7.3 note for each of the three reasons;
  - line dialog: the same, over one line;
  - Survey panel grid row text;
  - profile source label;
  - the strip's Apply after Save records the fit, and Apply of an unsaved fit records none;
  - Edit grid keeps the record on an unchanged value and drops it on a changed one.
- Assert `message_log == []` in slot-driven tests, as the suite does elsewhere.

## 13. Walkthrough

On a new QGIS profile, `ns_geo_grid_velocity`, deployed with `scripts/dev_link.py`. It needs
its own profile because the project file changes. The walkthrough is an Artifact with the `db`
capability. It should cover at least:
- measure fits on three or four lines of a real grid, then read them all in Grid › Set velocity…;
- tick a subset, Use average, Apply;
- reopen the dialog: the same ticks;
- delete one member, and read the note;
- the Slices panel label and depth read-out, with a different override on the grid's first line;
- save, close QGIS, reopen: the record is still there;
- open the saved file in 0.4.0, and check it is refused with a message naming version 3. Mark
  this check data-loss relevant.

## 14. Left to the builder

- Names and the exact shape of the record type, and where it lives in the core.
- How the fit-id counter is stored (§8).
- Whether the grid dialog subclasses, shares code with, or generalises `VelocityDialog`.
- Exact wording, within the meaning given here.
- Whether `cut_velocity` is renamed or wrapped (§10).
- Column widths, sizing and the dialog's minimum size. Keep it usable at QGIS's default window
  size.

## 15. Size and order

**M**: a written plan of about four tasks, then the walkthrough.
1. Core: the average, the velocity source record, ids never reused, the file version rule, and
   loading old files.
2. The slice fix (§10), with its hazard test.
3. The grid velocity dialog, the menu wiring, the Survey panel and profile labels.
4. The line dialog's ticks and average, the strip's Apply records, and Edit grid's rule.

README roadmap: list the branch under In progress when the build starts. Move it to Done when it
merges.

## 16. Follow-ups to file when this merges

- Exports could carry the velocity source (a summary of the record) in their metadata, if the
  author wants reproducibility to reach the GeoTIFF too.
- Dix conversion from fits at several depths (velocity spec §11), if a layered site needs it.
