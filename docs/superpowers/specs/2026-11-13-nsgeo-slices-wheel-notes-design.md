# nsgeo Slices panel: scroll wheel, typing, width and notes — design

Session A of the issue-sessions plan (https://claude.ai/artifact/A1w1dKGNENHd2S2GbmqECj). Seven
issues that all live in the Slices panel's boxes and note lines, plus one in Edit lines, so that
one plan, one review and one walkthrough cover them.

- **Closes:** #177 (dz wheel and freeze), #176 (Edit lines Grid column takes the wheel), #105
  (a Whole site refresh rewrites a box you are typing in), #121 (panel width).
- **Takes items from, without closing:** #157 items 4, 5 and 6; #163 item 1; #50's first half
  (the Qt 6 width test). #50's Windows QGIS 4 hand check belongs to session O. The other items of
  #157 and #163 belong to sessions B, F, H and P.

Branch `nsgeo-slices-wheel-notes`, from origin/main 513867a. Decided in chat on 2026-11-13; the
notes layout was chosen on a mockup (`.lavish/session-a-notes.html`, local only).

---

## 1. What this is for

The author, on using the plugin (2026-11-12):

> There are so many parameters and the scroll wheel is becoming a liability in some cases. The
> two that keep biting me are accidentally scrolling dz to a tiny number in the slices panel
> (which freezes and sometimes crashes QGIS) [...] and accidentally scrolling the grid number in
> the edit lines dialog an moving a line to a different grid by mistake.

Scrolling the panel past a box should never change a value. A background refresh should never
rewrite a number being typed. A refusal should stay on screen until it is dealt with, not fade as
a toast. And the warnings the panel already gives (the site's clock warning, the preview note)
should be readable without hovering.

**Success looks like:** the author scrolls the whole Slices panel and the Edit lines table
without changing anything, types during a Whole site refresh without losing digits, and reads
every warning in full at the width they work at.

**Anti-goals:**
- Taking the wheel away from places the author likes it. The depth slider steps with the wheel on
  purpose (#109), and the other boxes keep today's behaviour.
- A message shown in two places. A refusal moves from the toast to the panel; it does not appear
  in both.

## 2. The wheel rule (#177, #176)

**The rule:** a box ignores the wheel until you click into it (it has keyboard focus). An ignored
wheel event goes to the panel, which scrolls. This is the rule the Processing panel's
`TimeSpinBox.wheelEvent` already uses (`ui/param_form.py`, from #109).

**Which boxes (the author's call):** only these, for now.
- Slices: **dz, z0, z1 and Cell size** (`dz_spin`, `z0_spin`, `z1_spin`, `cell_spin`). These are
  the dock's own spins, shared by This grid and Whole site, so the rule holds in both scopes.
- Edit lines: **each row's Grid combo** (§4).

Everything else keeps today's wheel behaviour: Thickness, Step, the Source and Display combos, the
Interpolation boxes, the sliders. The author will flag other boxes as they bite. So the rule is
written once, as a small shared helper, and adding a box later is one line.

**Approaches considered:** these boxes only, or every spin box and combo box in a scrolling panel
or dialog, plugin-wide. The author chose these boxes only: there are places they like the wheel,
and none of the others has grabbed it by accident. Plugin-wide would have covered the Processing
panel's choice combos, where a wheel notch commits and re-processes the line. That hazard is
known; it is left until it bites.

**After you use a box, scrolling the panel lets go of it** (the author's call, from the builder
check). A box you typed in or clicked the arrows of keeps focus, so without this the panel could
slide it under the pointer and the next notch would change it. So:
- **As soon as you scroll the panel** (the wheel over the panel, the scroll bar, or its keys),
  the guarded box that has focus lets go of it. From then on it ignores the wheel like the others.
- **Click then wheel still works.** With the pointer on the focused box, the wheel goes to the
  box, and the panel doesn't move.
- **Letting go is the same as clicking elsewhere:** what you typed is kept and applied, as it is
  today when you click away.
- **Only a scroll you make counts.** The panel moving on its own must not take focus away: a
  Warnings entry appearing or going (§6.1), a section folding, or the panel scrolling a box into
  view when you Tab to it.
- **The same holds in Edit lines.** Scrolling the table lets go of a focused Grid combo. It rarely
  matters there, because a pick already hands focus back (§4).

The other options were: pressing Enter lets go (but after clicking the arrows the box would keep
the wheel until you clicked elsewhere), or leave it as the Processing panel's time boxes work
today (a box keeps the wheel until you click something else).

## 3. dz: a floor at the sample interval, and a level limit (#177)

### 3.1 What "native interval" means here

The radar takes a reading every so often in each trace. Every real DZT in the repo's local data
(130 files) has 512 readings over 110.86 ns: one every **0.2165 ns**, about 1 cm of depth at
0.1 m/ns. Each cube level is a blend of the two readings either side of its time
(`resample_window`, `nsgeo/slices/binning.py`). A dz finer than the interval makes levels between
the same two readings: no new information, only a deeper cube. 0.001 ns is 216 levels per
reading, which is the freeze.

### 3.2 The floor

- **dz can't go below the sample interval**, and its arrows step in whole samples. The box's
  minimum is the interval; its step already is (`_seed_dz_z_defaults`, `SiteScope.seed_z`).
- **This grid:** the interval of the grid's first included line, as `_seed_dz_z_defaults` reads it
  today.
- **Whole site:** the finest interval among the included grids. All of the author's grids share
  one.
- **Before any line exists** there is no interval to read. The box keeps a small generic minimum
  then, and the level limit (§3.3) is what protects. *(My call.)*
- **A remembered dz, or a saved cube's dz, below the floor** is raised to the floor in the box,
  without comment *(my call)*.
  The record is not rewritten. This is how the cell size's floor already treats a remembered cell.
  A saved cube is re-prepared from its recipe anyway (`restore_cube`), so it comes back at the
  floor.
- The floor travels with the spins when the scope switches (`capture_spins` / `restore_spins`),
  as the time step already does.

**Approaches considered:** a floor at the native interval (the issue's suggestion), or sub-sample
dz kept with smaller wheel and arrow steps. The author chose the floor: a finer dz adds nothing
(slices spec §7.2), and with the wheel rule in place, smaller steps would only matter for arrows
and typing.

### 3.3 The level limit

A backstop for any route that skips the floor: a typed z range, a saved record, a remembered
value, or a value from before the lines loaded.

- **The limit:** a cube may have at most **twice as many levels as the deepest included line has
  samples**. That is 1,024 levels on the author's lines. A deeper radar record (1,024 or 2,048
  samples) is never refused at native dz. A fixed number would refuse it.
- **Checked before any preparation, however the value arrived,** in both scopes: This grid's
  `_apply_resolution` (beside the frame-cap check) and `SiteScope.apply_resolution`.
- **It counts the levels each cube would actually have** *(my call, from the builder check)*.
  This grid counts the range as it would be applied, the count `ZAxis.from_range` makes. Whole
  site counts each grid's own axis after the site clips z0–z1 to that grid's data (`site_axis`,
  `grid_axis`), against twice that grid's deepest line. So a typed z1 of 100,000 ns is refused in
  This grid. Whole site already clips it to the data, so it does no harm there and is not
  refused. Checking each grid alone means a site mixing radars can't have its own seeded default
  refused.
- **The message**, shown in the Warnings section (§6), not as a toast:

  > Too many levels: dz 0.2165 ns from 0 to 100,000 ns makes 461,894 levels; this cube allows
  > 1,024 (twice the 512 samples in each line). Narrow z0–z1 or raise dz.

- With the floor in place, a cube can't exceed its lines' own readings by itself. A z range past a
  line's recording is already refused at planning (`plan_line` raises `CoverageError`: "does not
  cover … shrink the z range"). So the limit should rarely fire. Its job is to make sure nothing
  ever starts building a cube 200 times too deep.

## 4. Edit lines: the Grid column (#176)

- **Each row's Grid combo takes the wheel rule** (§2). Scrolling the table over the Grid column
  changes nothing.
- **After you pick a grid, focus goes back to the table.** Otherwise the combo you just used keeps
  focus, and the first wheel notch with the pointer still over it would change it again. That is
  the very gesture of picking one line's grid and then scrolling on to the next.
- The bulk **Move to grid** combo is left alone. Nothing moves until **Move** is clicked.

**Approaches considered:** an item delegate (the grid as plain text, with a combo that opens only
when the cell is clicked), or the same focus rule as dz. The author chose the focus rule: it is
the smaller change, it reuses the helper, and it merges cleanly with M19a Plan B (§10).

## 5. Typing during a Whole site refresh (#105)

`site_scope.set_spins_quietly` sets every spin it is given on every Whole site ready tick
(`SiteScope.seed_z`). It changes in two ways:
- it **skips a spin whose value already equals the target**;
- it **skips a spin that has keyboard focus and whose text you have changed**. Your half-typed
  number stays as typed, and the tick's value is not forced over it.

The seed is not lost. The next tick, or your own finished edit, settles the value, as it does
today.

## 6. Warnings, and sections that fold (#163 item 1, #157 items 4 and 5)

Chosen on the mockup: option B, revised by the author, "as drawn".

### 6.1 A Warnings section

- **Its own section, titled Warnings, right under Position.** It is hidden when there is nothing
  to say. It replaces the one-line elided `site_note` under the readout, which goes away.
- **The same section appears in This grid and Whole site.**
- **One entry per message, in full, wrapped, with an icon:** ⛔ refusals first, then ⚠ warnings,
  then ⓘ notes *(the order is my call)*. No hover is needed. A tooltip may repeat the text but carries nothing extra.
- **What goes in it:**
  - **⚠ the site clock warning** (#163 item 1): `mixed_clock_note`, as its own entry, no longer
    joined onto the end of another message.
  - **ⓘ the preview note** (#157 item 5), tightened to about two sentences. For example: *"Preview
    at 0.4 m pixels: the site (120 × 95 m) is too big to draw at 0.05 m. It draws in full at a
    0.2 m cell or coarser, or without grid C."* Same facts as today's `preview_note`, fewer words.
  - **⛔ This grid's frame-cap refusal** (#157 item 4). It names the refused value, why, what is
    still on the map, and the way out. For example: *"Cell 0.01 m refused: grid A would be
    9,000,000 cells, too many to draw. Still showing 0.05 m. Use 0.02 m or coarser."*
  - **⛔ Whole site geometry failures** (#157 item 4): `_rebuild_geometry_reporting` failures on
    engine-callback paths (a grid becoming ready, moving or being dropped). The engine keeps the
    failure as state the scope reads, as it keeps `preview_note`, and they show as today's
    "Not drawn: …". A geometry failure refuses no value, so it clears on the next rebuild that
    succeeds.
  - **⛔ the level limit's refusal** (§3.3).
- **A restored cube's cell** *(my call, from the builder check)*. Today `restore_cube` never sets
  the cell floor for the cube's grid. Its frame-cap check runs against the grid shown before the
  restore, so the cube's own grid is never checked. Fixed: the restore sets the cube's grid's
  floor first, as a grid change does (`_seed_resolution_defaults`). A saved cell below the floor is
  then raised to it without comment, the same rule as a saved dz (§3.2) and a remembered cell. The
  record is not rewritten. The frame-cap check stays as a backstop and reports in Warnings if it is
  ever reached. With the floor in place, neither typing nor a restore can reach it. #157 item 4
  already said "the cell spin's floor guards each grid's frame".
- **A refusal stays until the value it refused changes**, or the scope or grid changes.
- **Which toasts go** *(my call, from the builder check)*. Every refusal shown in Warnings loses
  its toast, so each message is in one place: the frame cap, the level limit, and Whole site's
  "Not drawn" problems, which already show in the panel and toast too today. `Resolution`'s own
  checks ("t1_ns must exceed t0_ns", "dz_ns must be positive") stay as toasts. The boxes apply
  while you type, so those fire mid-number, and a panel that jumps while you type is worse than a
  toast.
- **The cost the author accepted with this option:** when a message comes or goes, everything below
  the section moves. A refusal appearing while you type in Resolution moves that box down by the
  message's height. Typing and focus stay put: the panel moving on its own is not a scroll you
  made, so the box keeps focus (§2).

### 6.2 Sections that fold

- **Resolution, Interpolation, Normalisation (Whole site only) and Display fold** open and closed
  from their headers. Source, Position and Warnings stay open.
- **Built on QGIS's own folding group box** (`QgsCollapsibleGroupBox`, the one in Layer
  Properties), so they look and click like the rest of QGIS. It exists on QGIS 3.44 and 4.2.
- **Folding is remembered across QGIS restarts.** This grid and Whole site fold together.
  Resolution and Display are already shared widgets. The two Interpolation panels (`grid_finish`,
  `site_finish`) share one fold state. QGIS's own sync group only syncs on a modifier-click, so
  the two are wired through the fold signal (`collapsedStateChanged`).
- **Every section starts unfolded** the first time *(my call)*.

**Approaches considered (from the mockup):**
- A: today's single line, shortened, with the rest on hover;
- B: full notes under the readout;
- C: a short line under the readout, with the full notes at the bottom of the panel.

I recommended C. The author chose B and revised it: the notes get their own Warnings section
rather than sitting between the slice count and the depths, and the settings sections fold away
once they are set.

## 7. Explaining the coverage view (#157 item 6)

The guide already says what the counts are. Two pieces are missing:
- **The Show coverage tooltip** says what it is for and how a preview draws it *(the wording is my
  call)*:

  > Shows how many traces fell in each cell, instead of the amplitude.
  > Use it to see where your lines ran and where there is no data: blank cells had no line
  > through them.
  > In a Whole site preview each pixel shows the largest count among the cells under it, so
  > lines look wider than they are.

- **The guide** (`docs/guide/getting-started.md`, under **Show coverage**) gains the same last
  sentence.

## 8. Panel width (#121, #50's first half)

### 8.1 What was measured

- In the author's QGIS 3.44 (`ns_geo` profile, Ubuntu 11 font, Fusion style), the Slices panel is
  tabbed with Processing and sits at **449 px**. 449 is the Processing panel's own minimum. The
  Slices contents need **401 px**.
- Offscreen, with an empty panel (origin/main 513867a):

  | Font | Processing minimum | Slices contents | widest Slices row |
  |---|---|---|---|
  | Noto Sans 9 | 418 px | 328 px | Interpolation 320 |
  | Ubuntu 11 | 433 px | 358 px | Interpolation 362, Display 329 |
  | Ubuntu 14 | 472 px | 430 px | Interpolation 422 |

- The Qt 6 xfail on `test_the_dock_minimum_does_not_force_the_main_window_to_grow` was already
  dropped on 2026-11-05 (4e39772). The wide Interpolation row had lifted the Qt 6 opening width
  past the test's 280 px. So that test passes on Qt 6 by accident.

### 8.2 The rule (the author's call)

**The Slices contents are never wider than the Processing panel's minimum, at the same font.**
The two share a tab stack, so Slices can never be narrower than Processing anyway. Both grow and
shrink with the font, so the rule holds on a laptop or a TV without picking a pixel count. The
author works on several screens and asked not to fit two numbers.

- **It holds today,** at every font measured and in the author's QGIS. The Interpolation row stays
  as it is.
- **Text that comes from the data counts.** That includes the slice readout, cube names in the
  Cube combo, the memory label and the Warnings entries. None of it may widen the panel past the
  rule: it wraps or is cut off with "…".
- **A guard test** compares the two panels at a small and a large font, with every section
  unfolded and a real site loaded where the local data exists. It replaces the fixed thresholds
  where they guard the same thing.
- **#50: the panel opens at least as wide as its own contents** on both Qt versions, so it never
  opens scrolling sideways. That replaces the fixed `sizeHint().width() >= 280`, which only
  passes on Qt 6 because of the Interpolation row.
- **The catch, accepted:** docked on its own, Slices stays about 400 px wide at the author's font.
  If Processing gets narrower later, the guard says Slices must follow.
- **Measure before changing anything** *(my call, from the builder check)*. §8.1's offscreen
  figures are for an empty panel. With a site loaded, the repo's own layout probe gives 475 px
  locally and 520 px in the QGIS 3.44 CI image (`layout_width`, `tests/plugin_testing.py`). Those
  numbers are at the test font, so they can't be compared directly with the Processing figures
  above. The plan's first width step measures both panels at the same font, loaded. Today
  `velocity_label` and `included_label` (with its over-budget suffix) don't wrap. Any row over the
  guard gives way by wrapping, eliding, or stacking its label above its box. That includes the
  Interpolation row if the measurement says so; "the Interpolation row stays" holds only if it
  fits.

**Approaches considered:** a pixel target of about 300 px (the issue's), a rule in characters of
the panel's own font (about 35, my proposal), or pinning to Processing's minimum (the author's).
Pinning won: it is the width the author actually gets, it scales with the font, and it already
holds.

**Not in this session:** making the Processing panel itself narrower, which is the only way the
tab stack gets below 449 px. That would be its own issue if the author wants it.

## 9. Tests to pin

- A wheel event over an **unfocused** dz, z0, z1 or Cell size box changes nothing, and nothing
  re-prepares. A **focused** box still takes the wheel.
- A wheel event over an unfocused Edit lines **Grid** combo changes no line's grid. After a pick,
  focus is back on the table.
- The ignored wheel event **scrolls the panel**: the scroll area's position moves. This is what the
  author is after, and it is the easy thing to get wrong (an event filter that swallows the event
  leaves the panel still).
- **Scrolling the panel lets go:** with dz focused, a wheel notch over another part of the panel
  scrolls it, dz no longer has focus, and its value is what was typed. A wheel over the focused box
  itself still changes it. The panel moving on its own (a Warnings entry appearing or going, a fold,
  Tab scrolling a box into view) leaves focus where it was.
- **dz can't go below the sample interval**, in both scopes. The arrows step in whole samples.
  A remembered dz below the floor is raised and its record left as it was.
- **The level limit refuses** a z range or dz past twice the samples, before any preparation, in
  both scopes. Its message is in the Warnings section, and no toast is shown.
- **A half-typed value survives a Whole site ready tick** (#105's own test), and an unchanged value
  is not re-set.
- **Warnings:** the clock warning and the preview note show as separate full entries, in order. The
  frame-cap refusal from `restore_cube` shows there, as does a geometry failure on an engine
  callback. A refusal clears when its value changes.
- **Folding:** each named section folds and unfolds, and the two Interpolation panels fold
  together. Tests must neither read nor write the author's saved fold state.
- **Width:** the guard in §8.2, and the dock minimum-width tests stay green
  (`test_the_dock_minimum_does_not_force_the_main_window_to_grow`, the indicator's content-width
  test, the layout-probe tests).
- **Real lines, not only synthetic ones:** the dz floor and the level limit are checked on the
  local real DZTs (0.2165 ns, 512 samples → floor 0.2165, limit 1,024). The width guard runs with a
  real site where the local data exists, and skips cleanly in CI where it does not.

## 10. Constraints and clashes

- **M19a Plan B Task 1** adds a mag mode to `edit_lines_dialog.py`, on a stacked branch
  `nsgeo-m19-mag-b` that does not exist yet (checked 2026-11-13). The M19 branch changes one line
  of that file today. Keep the #176 change to the combo setup and one focus hand-back, so the two
  merge cleanly. Plan B's expectation that a GPR grid "still shows the Grid combo" stays true.
- **M16 Plan A (PR #190, open)** adds a third button, ParaView…, beside Save cube… and Export
  GeoTIFF…. Whichever branch merges second makes that row pass the width guard (§8.2). It may
  need two rows.
- **QGIS 3.44 (Qt 5) and 4.2 (Qt 6)** must both pass. CI runs both.
- **Every Qt override and slot guards its own body**, as the codebase does throughout. A wheel
  handler or event filter that raises must never escape into Qt.
- The site's clock-warning comment on #163 (grid velocity fits measured on another clock, PR #186)
  is not in this session (§12).

## 11. The walkthrough

Built and deployed to its own QGIS profile, as usual. It covers:
- **a narrow panel:** Slices tabbed with Processing at its minimum, and docked alone. Nothing
  scrolls sideways, and every warning reads in full;
- **scrolling past every box:** dz, z0, z1 and Cell size don't change. A click then the wheel does
  change them. The other boxes behave as before;
- **type a dz, then scroll the panel:** dz keeps what you typed, lets go, and the panel scrolls
  past it without changing it;
- **dz:** the arrows step 0.2165, 0.433, …; dz can't go below 0.2165. In This grid, a typed z1 of
  100,000 ns is refused in the Warnings section, with the old picture still on the map. In Whole
  site the same z1 is clipped to the data;
- **a restored cube** comes back at its saved settings, or at the floor where its grid no longer
  allows them. Tests cover the frame-cap backstop, which a person can no longer reach by hand;
- **typing in dz, z0 or z1 during a Whole site refresh;**
- **the clock warning and the preview note** in full, on a site with a grid without Time zero and
  at a fine cell;
- **folding:** fold sections, switch scopes, restart QGIS; the folds are remembered;
- **Edit lines:** scroll over the Grid column, pick a grid, keep scrolling;
- **the coverage tooltip.**

The Windows QGIS 4 look (#50) stays in session O.

## 12. Non-goals

- The wheel rule anywhere else (Processing choice combos, Thickness/Step, Display combos,
  Interpolation boxes, sliders). Add boxes one line at a time as they bite.
- Letting go on scroll for the Processing panel's time boxes. They keep today's rule.
- Making the Processing panel narrower.
- #157 items 1, 2 and 3 and #163 items 2–6: sessions B, F, H and P.
- The grid-velocity clock comment on #163: it concerns velocity fits, not the panel's placement.
  It belongs with the velocity follow-ups.
- Changing what the Interpolation row shows (it fits under the rule).

## 13. Left to the builder

- The helper's form: a subclass, an event filter or a function that installs one. It must let the
  ignored event reach the scroll area (see §9).
- How a scroll you make is told apart from the panel moving on its own (§2). For example, the
  scroll bar's `actionTriggered` fires for the wheel, a drag, its arrows and keys, but not for a
  value set in code or a range that shrinks.
- How "text you have changed" is detected for #105 (for example, the line edit's modified flag or
  text that differs from the value's own display).
- Exact wording of each Warnings entry within §6.1's rule: it names the value, the reason, what is
  still drawn, and the way out.
- The Warnings section's widget and icons. It must not raise the panel's minimum width.
- How the level count is computed. It must match `ZAxis.from_range`.
- How the width guard measures "a real site loaded", and its two fonts.

## 14. When it merges

- The PR closes #177, #176, #105 and #121.
- Comment on #157 (items 4, 5 and 6 done), #163 (item 1 done) and #50 (the Qt 6 width test
  settled; the Windows hand check stays with session O), each naming the items closed. Don't close
  those three.
- #121's comment says why the target changed from about 300 px to the Processing panel's minimum.
