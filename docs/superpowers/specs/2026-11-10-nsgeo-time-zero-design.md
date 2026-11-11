# nsgeo time zero — design (#97)

After this change, the Time zero step sets the clock as well as cropping. The row it lands on
reads 0 ns, and every time below it is measured from there. Depths, velocity fits, slices and
migration all measure from that 0. Today the step crops the rows above the first break and leaves
every sample on the radar's own clock. That clock is set by the header's position, which is −11.09
ns on every real file we have.

This resolves the decision #97 left open: "will nsgeo ever shift the time axis so the first break
is at 0 ns?" The user said yes on 2026-11-10. The fix to the fit strip's warning, #97's first
option, is folded in (§7).

---

## 1. Why

**What users expect.** The user has used tools that detect time zero automatically, and one that
asked them to set it by eye. In both, the chosen point became 0 ns. Asked whether nsgeo's Time zero
step should work that way, they said *"yes, that's what I would expect."* Today it does not. After
the step, the top row of the campus lines reads −0.5 ns, and the fit strip still tells the user to
add the step they just added (#97).

**Why the radar's clock is not good enough.** The header puts the radar's zero at −11.09 ns on
both real surveys, yet the first break lands in a different place on each (§2). Between surveys,
with identical settings, the radar's zero moves by about a nanosecond. At a 20 ns apex that is a
2–3% velocity bias (the table in #97). That is within one fit's own σ, but it is a consistent bias
rather than noise, and with grids side by side in a site it is a misalignment.

**Why now.** M15 stores cut picks, and M16 stores depth surfaces. Both are times on the cube's
clock. If the clock moves after they exist, every one of them needs converting. Today, every stored
time is still on the radar's clock, because nothing has ever moved it. That is what makes the
change cheap now (§5). The README roadmap has this as item 5, before the placement corrections and
M15.

---

## 2. Starting state, measured

Read from `main` at `b55b2f0` on 2026-11-10.

| What | Where | State |
|---|---|---|
| `Radargram` | `processing/base.py:19` | `data`, `dt_ns`, `t0_ns`, `dx_m`. Row *i* is at `t0_ns + i·dt_ns`. Every step builds its output with `rg.replace(...)`. `from_profile` is the only constructor, and it sets `t0_ns = header.position_ns`. |
| `time_zero` | `processing/timezero.py` | Modes `first_break` (threshold on the mean absolute amplitude across traces, default 0.2) and `sample` (a row index). Crops at row *k* and sets `t0_ns += k·dt`, so the survivors keep their times. **`k <= 0` returns the input unchanged.** |
| Step ordering | `processing/stack.py`, `session.py`, presets | No constraint. A cutoff or gain curve can sit before or after `time_zero`, and `time_zero` can be disabled or appear twice. |
| Time-valued step parameters | `timecutoff.py` `end_ns` (kind `time`), `gain.py` `gain_curve.points` (kind `curve`) | On the step's **input** axis. The profile drag (`profile_dock._on_cutoff_dragged`) and the gain strip (`plugin._on_gain_points`) write values read off the **displayed** axis. |
| Picks | `layers.py` `picks` table; `session.add_pick` | Stores `time_ns` (the displayed axis, clamped to the header window) plus conveniences `depth_m` and `velocity_m_ns`. `follow_lines` rewrites the conveniences, never `time_ns`, and loads no samples. `picks` is the one authored table. It has a migrate-and-verify rebuild (`_rebuild_picks`) and a backup. |
| Saved fits | `velocity_fit.StoredFit`; `Line.velocity_fits`, `velocity_from_fit` | Points `(trace, t_ns)` as clicked; fitted `t0_ns`, `v`, `σ`, rms. Curves are redrawn from the stored `t0`/`v` and **never refitted**. Apply's provenance match compares point tuples for exact equality (`profile_dock.py:1127`). The velocity dialog applies the stored `v`. |
| Velocity model | `velocity.py` | Layer tops in two-way time, the first at 0.0. `depth_at` measures depth from 0 on whatever clock it is given. The UI only makes constant models. |
| Cube recipes | `Site.cubes[id]` via `slice_export.cube_record` / `recipe_from_record` | `z = {t0_ns, t1_ns, dz_ns}` on the prepared lines' clock. Restoring re-bins from the lines. `recipe_from_record` treats "a different cube under the same name" as the one unacceptable failure. |
| Remembered z ranges | `slice_sources[grid].resolution`, `site_view.resolution` | `t0_ns`/`t1_ns` on the cube clock. Silently clamped into the prepared bounds on restore. |
| Slice axis | `slices_engine.prepared_z_bounds`, `binning.plan_line` | The intersection of the lines' time spans. Every line is sampled at the same absolute times. |
| Site view | `slices/site.py`, `site_engine.py` | Grids line up by time (site-view spec §3). One ns window maps onto every grid. |
| GeoTIFFs | `site_export.py`, `slice_export.py` | Times in band descriptions and `NSGEO_*` items. Nothing says which clock. Nothing reads them back. |
| Migration guard | `migration.py` `MAX_T0_NS = 2.0` | Refuses a record that starts more than 2 ns from 0. The rationale cites the −0.69..+0.82 ns residual `time_zero` leaves today. |
| Fit strip note | `profile_dock._velocity_time_zero_note` | Warns when the view's `t0` is more than half a sample from 0. After the step it still fires on the real files (#97). |
| Pinned "the step moves no time" | `test_plugin_velocity_fit.py:539-565` (PR #96) and the docstrings in `timecutoff.py`, `base.py`, `velocity.py`, `profile_dock.py:1119-1131` | The pin makes a relabelling step fail on purpose. This design removes it deliberately. |

### Where the first break sits, on both real surveys

The `first_break` pick, measured on the radar's clock (header position −11.09 ns, dt 0.2165 ns, on
every file of both surveys):

| Survey | Threshold 0.1 | **0.2 (default)** | 0.4 |
|---|---|---|---|
| Campus, ten lines (`CAMPUS_LINES`) | −1.13 .. −0.91 ns | **−0.48 ns** (all ten) | +0.82 ns |
| GPS survey, 60 lines (`GPS_LINES`) | −1.99 .. −1.78 ns | **−1.56 .. −1.34 ns** | −0.26 .. −0.04 ns |

These are the relabel offsets this design applies. They show three things:
- On each survey, every line's pick falls within one sample of the others.
- The two surveys differ by about a nanosecond.
- The threshold moves the pick by about 2 ns.

The GPS survey's offset is three times the campus one, which makes it the better real-data test.

---

## 3. Decisions

From the brainstorm on 2026-11-10. Marked **user** where the user decided, **Claude's call** where I
did. The user said "sounds good" to the calls in the play-back, and was not asked about the rest.

1. **The step sets the clock (user).** The row Time zero lands on reads 0 ns, whether the step
   found it (`first_break`) or was given it (`sample`). Every time below is measured from there.
   Rows above are still cropped, as now.
2. **Each line gets its own zero (Claude's call, in the play-back).** The step already runs line by
   line. A line whose first break is a sample later gets its own 0. No grid-wide or survey-wide
   shared zero.
3. **Picks and fits stay on their reflections (Claude's call, in the play-back).** If the time zero
   moves (a new threshold, a by-eye setting, the step added or removed), a pick stays on the sample
   it was made on, and its time and depth change. A saved fit's velocity is recomputed from its
   points.
4. **Every stored time says which zero it is measured from (Claude's call).** This is the mechanism
   behind decision 3. Absent means the radar's own zero, which is true of every time stored today,
   so **no stored value is converted**. §5 has the per-store detail.
5. **Times typed into later steps are left alone (Claude's call, in the play-back).** A cutoff or
   gain curve saved after `time_zero` is read on the new clock. Its values land 0.5–1.5 ns
   differently on the real data. They are not converted.
6. **Velocities already applied stay put (Claude's call).** A velocity applied to a line or grid is
   a value, and it does not change unless the user acts. When the fit it came from now measures
   differently, the velocity dialog says so, and Apply takes the new value (§5.2).
7. **Without the step, nothing moves (Claude's call).** Times stay on the radar's clock and depths
   are measured from its zero, as today. The fit strip's note says that plainly instead of
   repeating advice (§7).
8. **Cubes and everything built on them use the time-zero clock (Claude's call).** A cube has no
   single radar clock, because each line has its own offset. Its natural clock is "time below each
   line's own zero", and M15's cuts and M16's surfaces inherit that.

---

## 4. The clock

### 4.1 A radargram knows where its zero is

`Radargram` gains a field (name the builder's call; `zero_ns` below). It holds the radar-clock
time that this radargram's axis calls 0. Row *i* then sits at radar-clock time
`zero_ns + t0_ns + i·dt_ns`.

- `from_profile` sets `zero_ns = 0.0`. The radar's own clock is the starting point.
- The radargram must also say **whether a Time zero step has set its clock**. A radar zero that
  happens to land exactly on the first break is not the same as having run the step. The fit
  strip's note (§7) and the site view's mixed-clock warning (§6.2) need this. Builder's call
  whether it is a flag or an optional `zero_ns`.
- Every other step passes both through via `rg.replace`, as it passes `dx_m` today. No step but
  `time_zero` changes them.

### 4.2 `time_zero` relabels

At pick row *k*, the output's `t0_ns` is exactly `0.0`. Its `zero_ns` is the input's radar-clock
time of row *k*: `zero_ns + t0_ns + k·dt_ns`. The step marks the clock as set.

- **`k = 0` relabels too.** "Zero is at row 0" still means row 0 reads 0. Today's early return for
  `k <= 0` goes. So does today's no-op for a `sample` of 0, which a test pins (§9).
- A second `time_zero` in a stack relabels again at its own pick. That is normally row 0 of an
  already-zeroed record, which changes nothing.
- A disabled `time_zero` does nothing, as now.
- What the step picks is unchanged: the first-break threshold rule and the row index.

### 4.3 Conversions go through the radar's clock

Any time moved from one axis to another goes through the radar's clock:
- a stored time to the axis on screen;
- the axis on screen to a step's input;
- the cube to a line;
- a pick's old zero to its new one.

The rule is `radar = zero + t`, then `t' = radar − zero'`. This is the only conversion rule. Every
place in the inventory that reads `header.position_ns` instead of the processed axis is a place
where it is easy to forget:
- `session.add_pick`'s clamp;
- the profile's header-only axes before samples load;
- `processing_dock.input_axis`'s fallback and the seeds that come from it;
- `slices_dock._seed_dz_z_defaults`;
- `site_scope.header_z_seed`.

Each has to either convert or be shown harmless (a seed that is clamped afterwards).

### 4.4 What the profile shows

The profile's time axis, depth axis, picks and fit curves are all on the clock of the radargram on
screen. A line whose stack has an active Time zero step reads 0 at its top row, and depths are
measured from it. The rest follows from that.

One trap the inventory found: `_set_axes_holding`'s "Rule 1" reuses the previous transform without
comparing `t0_ns`. With a relabel that crops nothing, that would leave a stale axis on screen.

---

## 5. Stored times

The principle (decision 4): **each stored time carries the zero it is measured from, and a missing
zero means the radar's own.** Old files therefore need no value conversion. Readers convert to
whatever clock they need via §4.3.

### 5.1 Picks

- **What the picks table shows (Claude's call).** `time_ns` and `depth_m` stay the user-facing
  values, measured from the zero the line's own stack sets. So the table matches the profile.
  M15's cut picks will write `time_ns` on the cube's clock, which is also time from zero
  (decision 8), so the column means one thing for both kinds of pick.
- **Recording the zero.** A new column records the radar-clock time of that zero (`zero_ns`;
  name the builder's call). NULL means 0, which is right for every row written before this change.
  Adding the column goes through the existing migrate-and-verify path; no time value is rewritten
  by it.
- **The radar-clock time of a pick** is `time_ns + zero_ns`. It never changes unless the user
  edits the row. That keeps the pick on its reflection.
- **When a line's zero changes,** its pick rows are rewritten: new `time_ns`, `zero_ns` and
  `depth_m`, with the same radar-clock time. The requirement is that **once any action that
  changes a line's stack completes** (an edit in the Processing panel, applying a stack to a
  grid, a preset), that line's rows show times and depths from its new zero. Applying a stack to
  a grid may therefore have to load the lines that carry picks to find their zeros. That cost is
  acceptable on an explicit user action.
- `follow_lines` keeps its job (position, distance, depth from the current velocity), and computes
  depth from `time_ns`, which is already time from zero.
- Drawing picks on the profile converts through §4.3. This covers the header-only axis shown
  before samples load, where the zero is the radar's, and the bypass and difference views.
- A row edited by hand keeps whatever the user typed, relative to its `zero_ns`.
- `stack_json` stays write-only provenance, as now.

### 5.2 Saved fits

- `StoredFit` gains the radar-clock zero its points were clicked against (absent = 0). The points
  stay as clicked.
- **Everything that shows or uses a fit refits it at the line's current zero** first: the curve on
  the profile, the dialog's list (velocity, σ, apex time, sort order), the "fit at X ns" label,
  Apply to line and Apply to grid. Refitting means:
  1. Convert the points to the current clock.
  2. Run `fit_hyperbola` with the stored apex trace as the guess.

  It is a handful of points, so it is cheap. Before this change, the result equals the stored
  values whenever the zero has not moved, and a test pins that.
- **The stored record is not rewritten on open.** Its `v`, `t0`, σ and rms remain what was
  measured at its own zero, which is the evidence. Recording a new zero happens only when the user
  re-saves the fit. Opening a site never dirties it.
- **The Apply provenance match** compares points on the radar clock, not as raw tuples.
- **Applied velocities (decision 6).** When a line's applied velocity came from a fit
  (`velocity_from_fit`) whose velocity at the current zero is now different, by more than a
  display rounding, the velocity dialog says so beside that fit, e.g. *"applied 0.0712; measured
  from the current time zero 0.0705"*. Apply then updates it. `velocity_source` keeps naming the
  fit. A grid velocity is a plain value with no link to a fit, so it gets no flag.
- If refitting fails at the new zero (for example, a point now at t ≤ 0), the fit is shown as
  unusable at this time zero with the reason, and it is not deleted.

### 5.3 Step parameters

Time-valued parameters stay on their step's **input** axis, as the schema already says. What
changes is that the profile drag and the gain strip read the displayed axis, which may now be on a
different clock from the step's input. A step placed before `time_zero` is one example; the bypass
view of `time_zero` itself is another. **Every value written from the profile is converted to the
step's input axis by §4.3.**

- The form's range already comes from `input_axis`, so it needs no change beyond the header
  fallback (§4.3).
- Saved values are not converted (decision 5).

### 5.4 Cubes, recipes and remembered ranges

- **A cube's z axis is on the time-zero clock** of the preset's stack (decision 8). Each
  `PreparedLine` carries its line's zero under the preset. That lets cube times be taken back to a
  line, for the profile's slice band (§6.3) and for M15.
- **Cube recipes gain a time-base marker.** A recipe without one was written on the radar's clock.
  Restoring such a recipe:
  - **Preset has an enabled `time_zero`:** the stored z range moves by the median of its lines'
    zeros, so the slices come back at the depths they showed. The message bar says once that the
    cube was rebuilt with times measured from each line's first break.
  - **Otherwise:** the record means what it always meant, so nothing changes.

  `recipe_from_record`'s rule against a different cube under the same name is why this is not
  silent.
- **The `.npz` store** records the same marker in its metadata.
- **Remembered z ranges are not converted** (the spirit of decision 5). They are already clamped
  into the prepared bounds on restore, and on the time-zero clock the lower bound is 0.

### 5.5 GeoTIFFs

Each exported slice and site file records which clock its times are on:
- the time-zero clock;
- the radar's clock;
- for a site whose grids differ, which grid is on which.

This uses a new `NSGEO_*` metadata item, the same way it records normalisation today. Band
descriptions are unchanged.

---

## 6. Lines and grids side by side

### 6.1 Within a grid

The grid's preset is applied to every line, so the lines share a clock. After the step, every line
starts at 0. So `prepared_z_bounds`' lower bound is 0, and the lines line up on their own first
breaks rather than on the radar's clock. The ends still differ by the cropped rows.

`plan_line`'s coverage check is unchanged.

### 6.2 Across a site

The site view still lines grids up by time, which is now time from each line's zero when the grids'
presets set one. **When the grids in a site view are on different clocks** (some presets set a
time zero and others don't), the panel warns and names the grids on the radar's clock. Their times
are about 11 ns apart on the real files, so slices would not line up. It does not refuse.

### 6.3 The slice band on the profile

The band is on the cube's clock. The profile may be showing the line's own stack, which can differ
from the preset. The band is converted cube → radar → profile using the line's zero under the
preset (§5.4) and its zero on screen, so it marks the same samples the slice was binned from.

---

## 7. The fit strip's note (#97's first option)

- **The radargram on screen had its clock set by a Time zero step:** no note.
- **Otherwise** (no step, or a disabled one), the note says:
  - that times are measured from the radar's own zero;
  - where the first break sits on that clock. The default `first_break` pick (threshold 0.2) is
    run on the displayed data, read-only, and its time is reported.
  - once there is a fit, the velocity it would measure from the first break.

  For example: *"Times are from the radar's own zero; the first break is at −0.5 ns. Measured from
  the first break, this fit would be 0.0712 m/ns (+1.2%). Add a Time zero step to measure from
  it."*
- **When the first break is within half a sample of the radar's zero,** the note stays quiet: the
  step would make no measurable difference (Claude's call).

The advice can no longer repeat itself. Following it silences it.

---

## 8. Migration

The guard stays at `MAX_T0_NS = 2.0`, and the refusal message is unchanged.
- **After a Time zero step,** `t0_ns` is exactly 0 and the guard passes.
- **Without one,** a real file starts at −11.09 ns and is refused, as now.

Only the rationale comment changes: the −0.69..+0.82 ns residual it cites no longer exists.

---

## 9. Testing

Real data comes first. Synthetic tests are used where real data cannot show the effect. The real
offsets are small, so clock bugs need synthetic records with a large, known zero, as well as the
GPS survey's −1.3 to −1.6 ns.

**Pins to remove or turn round (deliberately):**
- `test_plugin_velocity_fit.py:539-565`, "a fit is unchanged by the step". It becomes: the step
  changes the fit exactly as shifting the points does.
- `test_plugin_velocity_fit.py:342-370`: the half-sample warning rows.
- `test_steps_timezero_dewow.py:22-26` and `:48-52`: `t0` is advanced, and a sample of 0 keeps the
  old `t0`.
- `test_plugin_param_form.py:346-372`.
- `test_plugin_slices_dock.py:1785-1860`: three distinct starts become one.
- The stale numbers and comments listed in the inventory: `test_plugin_slices_dock.py:1723-1780`,
  `test_steps_migration.py:245-253`, `test_plugin_slices_engine.py:1694-1700`, `test_velocity.py:1-5`.

**New invariants worth pinning:**
- After `time_zero`, row *k* reads 0 and `zero_ns` is the input's radar time of row *k*, for both
  modes, for `k = 0`, and for a stack with the step twice.
- **A pick stays on its sample** through:
  - adding the step;
  - changing the threshold;
  - disabling the step;
  - applying a stack to a grid.

  Its `time_ns + zero_ns` never changes, and its table time and depth match the profile.
- **A saved fit:**
  - refitted at an unchanged zero, it equals the stored values;
  - refitted at a moved zero, it equals a fresh fit of the shifted points;
  - an old fit with no zero reads as the radar's clock.
- A survey file and picks table written before this change open with every value unchanged and
  nothing dirty.
- Dragging a cutoff that sits before `time_zero` writes the value on the step's input clock.
- A cube built with the step starts at 0. An old recipe restores within one sample of its old
  slices.
- The site view warns on mixed clocks.

**On real data:**
- Campus lines: after the default step, every line's `zero_ns` is −0.48 ns.
- GPS lines: offsets fall in −1.56 .. −1.34 ns.
- A fit measured on real ground matches the shifted-points fit.

---

## 10. Manual checkpoints

The build is deployed to its own QGIS profile, then walked through on real data before any merge
decision.

The walkthrough covers:
1. Adding Time zero on a line makes the top read 0, and depths start there.
2. Picks made before the step stay on their reflection, and the table's times and depths change
   to match the profile.
3. Changing the threshold keeps picks on their reflections.
4. A saved fit's velocity follows the time zero, and the dialog flags an applied velocity that no
   longer matches.
5. Without the step, the fit strip's note names the first break and the corrected velocity.
6. A grid cube built with the step starts at 0.
7. A site with one grid without the step warns.
8. An existing project from before the change opens with picks, fits and cubes where they were.

---

## 11. Out of scope

**Non-goals:**
- **Antenna-offset correction.** Zero is the first break, not first break minus the transmitter–
  receiver separation over c. It could be a later parameter.
- **Per-trace time zero.** Aligning each trace's first break to correct drift within a line is a
  different step.
- **A shared zero for a grid or survey.**
- **Converting times already saved in stacks, presets or remembered ranges.**
- **Editing a header's `position_ns`.** Relabelling here happens through the step. The user's
  older open question about header edits (Plan 2 KICKOFF) is not answered by this design.

**Anti-goals** (failures even if everything else works):
- a pick or fit that silently lands on a different reflection;
- a stored file whose values change meaning without a marker;
- a velocity that changes without the user acting;
- any loss in the picks table.

---

## 12. Left to the builder

- Names: `zero_ns`, the clock-set flag, the picks column, the recipe and GeoTIFF markers.
- How the session learns a line's zero after a stack change for lines that are not open (§5.1),
  and where that work runs.
- The exact wording of the note, the dialog flag and the warnings, within what §§5–7 say they
  must contain.
- The order of tasks. This may be one plan of about six tasks, or two: the line-level clock (§4,
  §5.1–5.3, §7, §8), then the cube level (§5.4–5.5, §6).

---

## 13. Hand-offs

- **M15** (spec approved, plan on `nsgeo-m15-cut-anywhere`): cut picks write `time_ns` on the
  cube's time-zero clock and leave the picks table's zero column empty. Its plan needs a check
  after this merges, because it was written against today's clock.
- **README roadmap:** item 5 changes from "decide" to this work.
