# nsgeo measure the destagger automatically — design

A **Measure** button in Edit lines works out the destagger each line needs from the grid's own
data. It uses the lines as they are placed now, fitted or not, and assumes no sign. One value
comes for the whole grid, and lines that are clearly off on their own get their own value. The
results fill the Destagger box and the table's Destagger column as a starting point the author
can adjust. Nothing changes until OK.

Closes #159. It is the "suggested shift" half of #47's stagger design. #47 stays open for
direction balancing. The typed destagger it fills in was built with #3 (PR #160).

Evidence: `docs/superpowers/notes/2026-11-11-destagger-measure-spike.md` (this branch), which
builds on `docs/superpowers/notes/2026-11-06-stagger-spike.md` (branch `nsgeo-m17-gps`).

---

## 1. What this is for

When lines are walked in alternate directions, a feature seen by lines walked one way sits a
little along from the same feature seen by lines walked the other way. In a slice, the edges of
anything sharp zig-zag from line to line. The typed destagger (#47, PR #160) corrects this by
moving every trace of a line forward along its own direction of travel. Finding the value is the
hard part.

How the author judges it, in their words: **"how much wiggle there was in big sharp features."**

In the placement-corrections walkthrough (2026-11-11), the right value could not be guessed. On
Nashville City Cemetery Grid 1, unfitted, +0.15 m was much better, 0.10 too little and 0.25 a
little too much. Once the lines were fitted to the grid's edges, +0.15 made it worse, and −0.15
"looks fantastic". The fit removes a wheel's length error, and that error had been looking like
stagger (§4).

The author also expects lines to differ from each other:

> I'd expect it might change line to line. If a person just doesn't line up exactly on the
> baseline to start, or the grid wasn't well squared. All of these problems may be helped by this.
> It's also one of the reasons I want an automated version. Manually setting every line custom
> would be too much

And how they will use it:

> I'm imagining measure as a starting point that I can tweak if something doesn't look right.

## 2. What stagger is (the author's model, which this design follows)

> Well stagger is a shift in the position of the gpr from one line to another. So different values
> at different depths doesn't make sense. A notch that exists at one level and not at another may
> be real, not the result of stagger.

Therefore:
- **A line's destagger is one number, the same at every depth.** That is already the model
  `GridPlacement.travel_shift` implements.
- **Measure looks at every depth and every line together.** It does not tune itself to the depth
  being viewed or to one feature, because a shape at one depth may be real. Comparing many lines
  over the whole record lets real shapes average out, and only the consistent shift survives.

## 3. Starting state (main at d8acb01)

- `GridPlacement` (`nsgeo/geometry/placement.py`) places trace `i` at
  `start_along + direction * (scale * i / traces_per_metre + travel_shift)`. `travel_shift` is
  "Destagger (m)" in the UI. It is metres forward along the line's own direction of travel, and it
  is not scaled.
- Edit lines (`nsgeo_qgis/ui/edit_lines_dialog.py`) is a modeless table of one grid's lines. Its
  columns include Dir, Start, Scale and Destagger, and pending edits are shaded before OK. Below
  the table is a bulk panel, "Change the N selected lines", disabled when nothing is selected. It
  has a Destagger (m) row (spin box + Set) and a Scale row with Fit to grid edges. OK re-checks
  every line against the placement the table saw.
- Nothing measures a destagger today.

## 4. Evidence from the spike (summary)

Real data, spike method (§7), destagger in metres:

| Grid | Lines | Measured, whole grid | By eye (walkthrough) |
|---|---|---|---|
| Nashville 2023 Grid 1 | unfitted | **+0.152** (95% +0.140…+0.165) | +0.15 |
| Nashville 2023 Grid 1 | fitted | **−0.065** (95% −0.057…−0.073) | −0.15 |
| Nashville 2023 Grid 2 | unfitted | **+0.165** | – |
| Nashville 2023 Grid 2 | fitted | **−0.059** | – |

- **Nashville 2023 Grid 1 is the same survey as `tests/data/local/with-dzg/`** (the 60-line RTK
  survey; identical files). The two acceptance cases #159 listed are one survey, unfitted and
  fitted.
- **Measure recovers the sign on its own.** Unfitted, a wheel reading about 1.4% short, with
  every line started at its edge, pushes opposite neighbours apart by about
  (scale − 1) × length ≈ 0.4 m, the same all along the line. That looks exactly like stagger.
  Fitting removes it, and the remainder goes the other way.
- **Fitted Grid 1: the eye's −0.15 is right on the grid's most compact strong feature, far along
  the lines.** There the fitted lines want about −0.12 to −0.13. Over the whole grid they want
  −0.065. The difference is leftover wheel error that a single stretch per line cannot follow.
  That is not stagger, and no shift fixes it everywhere.
- **Deeper reflectors consistently want 3–8 cm more forward shift** on both grids, both
  placements and every third of the lines. That is not stagger (§2). It may be the antenna
  looking slightly ahead rather than straight down. It is out of scope (§12).
- **Per line:** most lines' own leftover (±5 cm) is noise. Independent halves of the data disagree
  by as much. A handful of lines are clearly off by 0.15–0.7 m and agree across halves. Some lines
  change partway along (Grid 1 `FILE__011`, the known 4 m wheel slip).

## 5. Goals, non-goals, anti-goals

**Goals**
1. A Measure button in Edit lines. It fills the Destagger box with the grid's value and the
   selected rows' Destagger cells with each line's value, as pending edits. The author adjusts
   them and presses OK, or Cancel.
2. Per-line values for lines that are clearly and consistently off. Every other line takes the
   grid value.
3. Lines Measure cannot place are named on the status line with a reason, not guessed at.
4. It runs in the background. The dialog stays usable and can cancel it.
5. The estimator lives in nsgeo-core and is tested on real data.

**Non-goals**
- **A grid that is not squared.** Comparing each line with the average of its two neighbours
  cannot see a shift that grows steadily across the grid, so it cannot tell a skewed baseline from
  features that really run at an angle (§7.3). That needs surveyed corners, or GPS (M17).
- **Wheel error that changes along a line** (a slip partway). A shift cannot fix it. Measure names
  such lines.
- **The depth trend** in §4.
- **Direction balancing** (the rest of #47).
- **GPS lines.** M17 will reuse the estimator. Nothing about GPS placement is built here.
- **Measuring at import**, or applying anything automatically.

**Anti-goals** (would make it a failure even if it "works")
- **Straightening a real feature that runs at an angle** across the lines.
- **Writing per-line noise.** A per-line value that is not real adds wiggle.
- **Changing anything before OK,** or leaving the author unable to see what Measure changed.
- **Assuming a sign,** or giving an answer that depends on the depth being viewed.
- **A number that changes when Measure is pressed twice** on the same table.

## 6. Decided by the author

- Measure is a starting point to adjust, not a final answer. Nothing changes until OK.
- Stagger is one shift per line, the same at every depth. Measure uses all depths and all lines,
  not the viewed depth or one feature (§2).
- Lines may each need their own value. Automating per-line values is a main reason for Measure.
- It measures the lines as they are placed now, and the data decides the sign (#159, and the
  author agreed with the playback of §4).
- Nashville 2023 Grid 2 joins the local test data as links, so the per-line rules are tuned and
  tested on its real off lines (§10).

Claude's calls are marked **C1–C14** in §7–§10. The author has not separately confirmed them.

## 7. The estimator (nsgeo-core)

### 7.1 Inputs and outputs

A pure numpy function, or a small set of them, with no Qt. Module name and signature are left to
the builder (§11).

- **Per line:** a processed, binned envelope array (time bins × traces), along positions for every
  trace at the line's current placement, its offset (cross position), and its direction (+1/−1).
- **Out:**
  - the grid value: the destagger every line shares, in metres;
  - per line: the value to put in its Destagger cell, and a status. The status is one of:
    - *grid value*;
    - *own value*;
    - *changes partway along* (left at the grid value);
    - *no clear match* (left at the grid value);
    - *not measured* (no opposite-direction neighbour, or too short), left as it was.
  - some measure of how sure the grid value is, for the status line (the spike used a bootstrap
    over lines).

**C10 — the grid value can fail too.** If the grid value's peak is not clear, Measure changes
nothing and says why on the status line. "Not clear" covers a peak at the edge of the search
range, a peak that does not stand clear of the next-highest one, or too few lines with an
opposite neighbour to measure. A clear peak with a wide bootstrap interval still fills, and the
status line says how sure it is. This follows "named, not guessed at" (§5) at the grid level.

**C11 — lines on both axes.** A grid can hold lines along x and along y (cross-hatched;
`keys_on_grid` returns both). Measure treats each axis's lines as a separate set, with its own
neighbours by offset and its own grid value. Each selected row gets its own set's values. The
Destagger box gets the value of the axis with more lines, and the status line gives both values.
The two sets can genuinely differ: unfitted wheel error scales with each axis's length.

**C1 — the current destagger is ignored.** Positions are computed with `travel_shift = 0` and every
other field as the table now shows it (pending Start, Scale, Dir, Offset edits included). Measure
returns full values, not increments, so pressing it twice gives the same numbers.

### 7.2 The grid value (the spike's method)

1. **Processing, fixed, not the author's stack (C2).** Dewow 4 ns, background mean removal, analytic
   envelope (`nsgeo.processing`), then average 8 samples into each time bin. The author's stack
   (migration, gains) is for viewing. Migration in particular would move energy around, and the
   measurement must not depend on display choices.
2. **Time window.** Skip the direct wave and use the rest of the record. The spike used 4–70 ns on
   the DZT header's clock for a 350 MHz antenna and a 99 ns record. The builder should not
   hard-code 70 ns for other antennas (§11).
3. **Profiles.** For each line and time bin, resample onto a common along axis at 2 cm. Divide by
   that bin's median over all lines (a time gain), low-pass at 0.15 m and high-pass at 3 m. Zero
   the 2 m at each line's own ends (the ends are bright in every window), then normalise each line
   jointly over all bins.
4. **Neighbours (C3).** Order the lines by offset. A line's neighbours are the lines either side of
   it that run the other way. It is compared with **the mean of its two neighbours**, or with its
   one neighbour at the edge of the grid.
5. **Correlate** over a range of lags. Express the lag as a shift in the line's own direction of
   travel, so both directions add up instead of cancelling. Sum the curves over bins, average over
   lines, and take the peak with a parabola. **C12 — the search range grows with the lines.**
   The spike searched ±1 m, which is enough for 30 m lines. Unfitted neighbours disagree by about
   (scale − 1) × length plus the stagger: about 0.4 m at 30 m with a 1.4% short wheel, but about
   1 m at 60 m. The range is therefore ±max(1 m, about 3% of the longest line). The peak must
   stand clear of the next-highest one (C10), which guards against locking onto repeating
   features such as rows of graves. The exact factor and margin are the builder's (§11).
6. **Grid value = −(peak lag) / 2.** Opposite lines each move half their disagreement.

### 7.3 Why the mean of both neighbours (C3)

A feature crossing the lines at an angle sits a little further along on each successive line, and
so does every feature on a skewed grid. The mean of a line's two neighbours then lands exactly
where the line itself sees the feature. The comparison sees nothing, so a real angled wall is never
"straightened". The cost is the non-goal in §5: a skewed baseline is invisible too. Stagger,
which alternates from line to line, and a single line that is off on its own both show up clearly.

### 7.4 Per-line values (C4)

After the grid value is applied, measure each line's leftover against its neighbours. Required
behaviour (the method is the builder's):

- **A single line moved by d** (in its direction of travel) gets the grid value + its own
  correction of about −d. Its neighbours keep the grid value. A bad line must not drag its
  neighbours: comparing with the mean of both neighbours shows a single moved line as about −d/2
  on each neighbour, so a naive per-line reading would wrongly move them.
- **Two adjacent lines moved** are both recovered.
- **A shift that grows steadily across the lines** (a skew or an angled feature) produces no
  per-line values.
- **Pure stagger** produces the grid value only.
- **A line gets its own value only when it is clear and repeatable.** The two answers from
  independent halves of the data must agree, and the correlation peak must be clear (not at the
  edge of the search range). The spike's halves were shallow/deep bins and first/second half along the line.
  **A half without a clear peak of its own neither confirms nor counts against the line (C13).**
  It has nothing to match: Grid 1's first half has few compact features, which is why lines 8
  and 9 read about 0 there. A line needs at least two independent halves with clear peaks that
  agree. The thresholds are tuned by the builder on the real grids (§10). Whether Grid 1 lines 8
  and 9 end up with their own values is left to those thresholds and the walkthrough, not pinned
  here.
- **Changes partway along:** the along-line halves disagree by much more than noise, and both have
  a clear peak. The line is named and left at the grid value.
- **No clear match:** the peak is at the search edge, or there is no peak worth the name. The line
  is named and left at the grid value.
- **Not measured:** no opposite-direction neighbour, a recorded length too short to leave anything
  after the 2 m end trims, or no distance axis (`traces_per_metre <= 0`). The line keeps the
  Destagger it had.

If **no line has an opposite-direction neighbour** (every line walked the same way), Measure says
there is no stagger to measure and changes nothing.

## 8. Measure in Edit lines

**C5 — scope.** Measure always measures **every line on this grid**, with its pending edits (C1).
Lines whose Grid cell now names another grid are left out. It writes results into **the selected
rows**, matching the bulk panel, which acts on the selection (Ctrl+A for the whole grid). The
neighbours always come from the whole grid, so a single selected line still gets a value measured
against its real neighbours. (#159 said "the selected lines, or the whole grid". This reading
keeps the panel's rule and never measures a line without its neighbours.) **Confirmed by the
author at the walkthrough (2026-11-12),** after asking why ten selected lines read the whole
grid: the tooltip and the guide now say the selection only chooses which rows get filled. A
"measure the selection on its own" option, for a grid walked in two sessions, would be its own
follow-up.

**C6 — what it shows.**
- **The Destagger (m) spin box** gets the grid value, so Set can apply it to any selection
  afterwards.
- **Each selected row's Destagger cell** gets its value. The cell is shaded like any pending edit.
- **The status line** says what happened in a sentence or two. It gives the grid value with how
  sure it is, names the lines with their own values, and names the lines left at the grid value or
  not measured, with the reason. An illustration of the shape, not of the expected results: "Measured
  +0.152 m from 60 lines (±0.012). FILE__045 and FILE__028 have their own values. FILE__011
  changes partway along and is left at +0.152." The exact words are the builder's.

The author then edits any cell, presses Set, or presses Cancel. Measure adds no new column. The
button sits in the Destagger (m) row, after Set.

**C7 — while it runs.**
- Measure reads and processes every line on the grid, about 10 s for 60 lines plus a few seconds
  of correlation (spike note, Cost). That work runs off the main thread.
- The button becomes a way to cancel, and the status line shows progress.
- The rest of the dialog stays usable.
- **Results land only if the table still matches.** If any measured line's placement changed in
  the table while Measure ran (other than its Destagger), the results are discarded and the
  status line says to press Measure again.
- Closing or cancelling the dialog cancels Measure.

**C8 — keep the processed lines while the dialog is open.** Re-measuring after Fit, Flip or a
typed Start should only redo the placement and correlation, not reread every file.

## 9. Running in the background

The plugin's traps apply and are recorded in `nsgeo_qgis/loader.py` and the project memory:
- `QgsTask.fromFunction` tasks need a Python keep-alive.
- `on_finished` exceptions are swallowed, so the callback guards its own body.
- Slots must not raise.
- The session is touched only on the main thread.
- The dialog is modeless (`show()`, never `exec()`), and the site can close while it is open.

**C9 — the worker gets copies, not the session.** It receives each line's path, header and
placement, read on the main thread, and reads samples itself. The builder chooses between a
`QgsTask`, as in `LineLoader`, and the refine worker's `ThreadPoolExecutor`. The finished callback
checks that the dialog, the site and the table snapshot are all still current.

## 10. Acceptance

**Real-data tests (nsgeo-core),** using `GPS_LINES` from `tests/real_data.py` (= Nashville 2023
Grid 1). Skip when the data is absent. Place the lines as the spike did: zigzag at 0.5 m with
line 1 forward, on a 30 m grid.
- **Unfitted** (scale 1, each line starting at its edge): grid value +0.15 ± 0.02.
- **Fitted** (scale = 30 / recorded span, both ends on the edges): grid value −0.065 ± 0.02.
- **The current destagger is ignored:** the same lines with any destagger already set give the
  same values.
- **Mirror symmetry:** placing every line mirrored along the grid (start → length − start,
  direction flipped) gives the same values.
- **An injected single-line error is recovered.** Move one mid-grid line by +0.30 m along its
  direction of travel and, in a second case, by −0.50 m. That line's value comes out within
  0.05 m of (the grid value) − (d + r), where r is the line's own residual before the injection,
  and its neighbours keep their values. A line's own value corrects everything that is off on the
  line, not only the injection: a line already a few centimetres off (below the own-value
  threshold, so left at the grid value) is corrected by that much as well once it is moved
  (decided by the author at C14, 2026-11-11; FILE__031 of Grid 1 sits about +0.05 m ahead of its
  neighbours). The +0.30 and −0.50 results differ by −0.80 ± 0.01.
- **Two adjacent injected errors** are both recovered.
- **An injected skew is ignored.** Add k × 0.02 m to line k's start: no line gets an own value, and
  the grid value moves by less than 0.01 m.
- **Most lines keep the grid value** on the real survey. The exact share is the builder's to pin
  from the data; the spike suggests ≥ 80%.
- **Unfitted `FILE__011`** is reported as changing partway along, or as no clear match. It must not
  get an own value.

**Real-data tests on Grid 2** (decided by the author, 2026-11-11). Grid 1 has almost no lines that
need their own value, and Grid 2 has several. The per-line thresholds (§11) are tuned on these
lines, not only on injected errors.
- **The data.** `tests/data/local/grid2/` holds links to Nashville 2023 Grid 2's raw files
  (DZT, DZX and DZG, 60 lines) on `/mnt/DataStorage`, so these tests skip when the drive is not
  mounted. The links were made on 2026-11-11 in the main checkout. Add a `GRID2_LINES` list to
  `tests/real_data.py` and the folder to the layout in `tests/data/local/README.md`. Place the
  lines like Grid 1's: zigzag at 0.5 m, line 1 forward, on a 29.96 m grid. This matches the
  saved survey.
- **Grid value:** unfitted +0.165 ± 0.02, fitted −0.059 ± 0.02.
- **The lines the spike found clearly off get their own values.** Each value corrects in the
  direction that cancels the line's residual. Residuals are measured in the line's own direction
  of travel against its neighbours, after the grid value; the spike's figures are in the note.
  - Unfitted: `FILE__045` (about −0.72 m) and `FILE__028` (about −0.52 m).
  - Fitted: `FILE__051` (about −0.23 m) and `FILE__059` (about +0.23 m).
  The test pins the sign. The builder pins the size tolerance once the per-line solve exists, and
  shows it to the author at the C14 checkpoint.
- **Fitted `FILE__050`** (its halves read −0.18 and +0.96 m, and one hits the search limit) is
  reported as changing partway along, or as no clear match. It must not get an own value.
- **Not pinned either way:** the lines whose halves only partly agreed in the spike. Unfitted
  these are `FILE__044`, `048` and `049`; fitted, `FILE__044`, `045` and `049`. Unfitted
  `FILE__027` too: it was pinned with 028 until C14, but the built solve found only 028 off
  (moving 028 alone lines up the strong reflection on 027–030; moving 027 as well puts it 0.35 m
  out), and the author dropped the pin (2026-11-11).
- **Most lines keep the grid value**, as on Grid 1.

Synthetic data only where it mirrors the real records (project rule): the injected-error cases
above use the real lines.

**C14 — the author sees the estimator's results before the dialog is built.** After the core
task, the plan stops at a checkpoint. It shows the author the grid and per-line values for Grids
1 and 2, unfitted and fitted, beside line-strip pictures at the depth they judge by (the spike's
`destagger_panels.py`, with the per-line values applied). Threshold choices get the author's eye
before the dialog work. Preferring −0.15 on fitted Grid 1 while looking at one feature is the
author adjusting a starting point, which Measure is for (§1). It is not a failure of the whole-grid
value, which follows the author's own model in §2. A preference that the per-line results look
worse overall than the grid value alone would send the plan back to the estimator at that
checkpoint.

**C14 outcome (author, 2026-11-11).** The per-line values make the big sharp features look better.
The blocks of neighbouring lines that are all off the same way (Grid 2 unfitted 032–034 and
040–042, Grid 1 unfitted 012–015), where the method moves every other line, look right. The
FILE__027 pin is dropped and the injected-error target counts the line's own residual (both
above). "Changes partway along" stays at a 0.30 m difference between a line's halves: 0.40 m would
name 3 lines on Grid 1 unfitted instead of 7, but would drop lines 8 and 9, which are known to
change partway along.

**Walkthrough (author, QGIS, deployed profile).**
- Grid 1, unfitted and fitted: Measure, look at the slice at 14.9–19.7 ns, and judge the wiggle on
  big sharp features against the values found by eye.
- Grid 2, unfitted and fitted: expect about +0.165 and −0.06, plus the lines with their own values
  (spike note).
- Cancel mid-measure; edit during measure (the results are discarded); press Measure twice (same
  numbers); a one-direction grid (nothing to measure).

## 11. Left to the builder

- Module and function names in nsgeo-core, and the per-line solve that meets §7.4's behaviour.
- The thresholds for "clear", "repeatable" and "changes partway", tuned on the real grids (§10).
- The search range's factor and the peak-clearance margin (C10, C12).
- The time window's end for records and antennas unlike the spike's. For example, stop where the
  bin median falls to the noise floor.
- How "how sure" is computed and worded.
- `QgsTask` or the executor; progress granularity; cancel button styling.
- Speed-ups (vectorised correlation, a coarser along step for the grid value), as long as the
  acceptance values hold.

## 12. Findings for later (not built here)

- **The depth trend.** Deeper reflectors consistently want 3–8 cm more forward shift. Possibly
  antenna tilt or pattern. It could become a per-survey "depth lean" correction, but only with
  evidence of the cause. A candidate issue, not filed.
- **Wheel error along a line.** One stretch per line leaves 3 cm or more of error in places
  (fitted Grid 1, far third). User marks in the DZX or GPS (M17) could pin a line at more than its
  two ends. A candidate issue, not filed.
- **#159's fitted acceptance value** (−0.15) was the eye on one feature. The whole-grid value is
  −0.065 (§4). The walkthrough will show which the author prefers once per-line values are in.
