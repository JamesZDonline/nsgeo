# Profile view: axes, zoom and time zero by eye (session F)

Status: designed with the user in chat and on lavish pages, 2026-11-20. Branch `nsgeo-profile-view`,
worktree `.worktrees/nsgeo-profile-view`, from origin/main 86f4016.

Issues: #131, #5, #11, #14, #158, and #163 item 2. #211 was in the session too, but the user
closed it as not planned on 2026-11-20.

Paths below are under `packages/nsgeo-qgis/nsgeo_qgis/` unless they start with `packages/`.

## 1. Why

The Profile panel is where the user reads every line. It floats at about **1361 × 448**, which
leaves an image of about 1249 × 354 px. Five rough edges have collected around it:

- The slice band can't be hidden (#131). The user wants to look at a profile without it.
- **1:1 doesn't mean what it says (#5).** It sets one trace per pixel column. On a short line
  that clamps to the whole line, so it really acts as "fit the width, keep the time zoom". The
  user found that useful at M5, but the name misled them.
- The vertical axes are fixed to ns and m, and there is no cursor read-out (#11).
- A failed velocity refresh leaves the previous line's depth axis up (#14).
- Adding or editing Time zero throws away a time zoom (#163 item 2).
- Time zero can only be typed as a row number. The user wants to set it by eye, dragging a line
  on the profile (#158).

What success looks like to the user:

- They can follow a depth range along the whole line (Fit width), and see a feature at true
  scale (1:1).
- They can read the profile in rows when setting processing windows.
- They can set Time zero by dragging, without the profile jumping in ways that look like a
  glitch.

## 2. Decisions taken with the user (2026-11-20)

| # | Question | Decision |
|---|---|---|
| Q1 | #211: the velocity strip makes the profile jump | Not worth fixing. #211 is closed as not planned. |
| Q2 | #5: Fit width, Fit height and 1:1 | **Fit is a split button.** Clicking it repeats the last pick; the arrow opens Fit, Fit width and Fit height. It starts as Fit when QGIS starts, and the pick is not remembered across restarts. **1:1 becomes true scale** (§4.4), on its own button beside Fit. Fit height stays in the menu, though the user had no use in mind for it. |
| Q3 | #131: does a closed Slices panel hide the band? | **No, only the button does.** The slice stays on the map when the panel is closed, so the band still means something. |
| Q4 | #11: where the units are chosen, and where the read-out goes | **Click an axis to choose its units.** Its unit name shows "ns ▾" and right-click works too. The **read-out goes at the top right**, in the row above the image. |
| Q5a | #158: a new by-eye mode, or a drag on `sample` | **A drag on `sample`.** There is one hand mode: type the row or drag the line, and both change the same number. |
| Q5b | #158: what selecting the Time zero row shows | **The cropped rows come into view, and the line reads 0.** The profile stays on the line's own clock (§4.11). |
| Q6 | #158, raised by the design review: which record is drawn while Time zero is selected | **What Time zero receives (its input),** not every step except Time zero, which migration refuses (§4.11). |
| Build 1 | How a step says "drag me" | **The step's schema.** Each parameter names the modes it belongs to, and there is a new `row` kind (§4.9). |
| Build 2 | How the selected view reads on the line's clock | **Relabel the drawn record** onto the line's zero before it reaches the view (§4.11). |

The user also agreed to these, which were offered as my calls:

- The velocity label elides.
- Every value in the read-out is for the one sample under the pointer.
- "Samples" counts the rows on screen.
- Depth is greyed out in the units menu when there is no velocity.
- The unit choices and the band button are remembered across restarts.
- The read-out has no off switch.
- Switching into `sample` mode seeds the row at the first-break pick.
- Each mode shows only its own settings.

## 3. Goals, non-goals, anti-goals

**Goals**

- Every behaviour in §4, pinned by a test that fails before its fix.
- A walkthrough on a floating Profile panel at about the user's size.

**Non-goals**

- **The bottom axis's units.** It stays metres along the line, or trace numbers where there are
  no metres.
- **True distance along a GPS track.** That is M17c, next after F; see the constraint in §3.1.
- **Drawing with smoothing at Fit,** where traces are skipped on long lines. It came up while
  discussing 1:1. Offer it as an issue; don't file it unasked.
- **A cue showing which part of the line is in view.** It came up while discussing Fit height.
  It was offered and not taken.
- **#210 itself,** the tracer's-edge mode. F only builds the plumbing that mode will slot into.

**Anti-goals** (what would make this a failure even if it worked)

- The profile jumps or relabels when the user only selected a row and changed nothing.
- The drag line and the form's `sample` disagree.
- E's Difference rule (processing panel spec §6.2) stops holding.
- `plugin.py` grows beyond the slice band wiring. H, M19a and the #227 branch all edit it.

### 3.1 Constraints

- **M17c redraws the profile at true distance next.** The bottom axis, the read-out, Fit width
  and 1:1 must all read position along the line from **one helper**, so M17c can swap traces for
  distance in one place.
- **Time zero spec, 2026-11-10 design, §4.3 and §5.3.** Every value written from the profile
  reaches the step on its input axis, through the radar clock. A `row` value is a row of the
  step's input record, so no clock conversion applies. While the row is selected the profile
  draws exactly that input (§4.11, §4.12).
- **Processing panel spec, 2026-11-18 design, §6.2.** With Difference on, selecting Time zero
  turns Difference off:
  - one toast;
  - the button unchecks and the label clears;
  - the profile shows the ordinary view: the result, the cutoff's bypass while a cutoff row is
    selected, or Time zero's input while its row is selected.
- **Turns with G and Q.** G and Q take turns with F, so don't start Q while F is open.
- **CI and tests.**
  - CI runs QGIS 3.44 and 4.2.
  - Locally, run core and pure tests in full, plus the touched QGIS test files and the
    `-m real_data` tests (see the test-suite-speed recipe).
- **Open branches that overlap,** checked against origin/main on 2026-11-20:
  - `nsgeo-site-never-stuck` (H) and `nsgeo-m19-mag` (M19a) edit `plugin.py`, and the #227
    branch is planned to.
  - H, M19a and `nsgeo-3d-menu` all edit `ui/slices_dock.py`. H edits just above
    `ElidedLabel` (about line 153). So F imports `ElidedLabel` from `slices_dock` and does not
    move it.
  - None of them edits the other files F touches.
  - `nsgeo-help-pages` (stale since 2026-10-22) edits `ui/processing_dock.py`. Its
    `docs/guide/getting-started.md` describes 1:1 as "one trace per screen pixel". Whichever of
    the two merges second fixes that line. F does not touch that branch.

## 4. The design

### 4.1 The toolbar

Today the row reads:

```
Display gain [slider] 99.0 % [colormap] [Difference label] [Fit] [1:1] [channel] ...stretch... v = 0.100 m/ns (Grid A)
```

It becomes:

```
Display gain [slider] 99.0 % [colormap] [Difference label] [Fit|▾] [1:1] [Slice band] [channel] v = … (elided, takes the rest)
```

- **Fit** is a `QToolButton` in `MenuButtonPopup` mode (§4.3).
- **1:1** is a `QToolButton` (§4.4).
- **Slice band** is a checkable `QToolButton` (§4.2). *Superseded by §4.14 W1: a "Show slice band" `QCheckBox` after the colormap.*
- The velocity label becomes a `slices_dock.ElidedLabel`, imported, not moved (see §3.1). It takes the remaining width with stretch 1, elides on the right, and
  keeps its full text in its tooltip. The spacer before it goes.

Measured at 1361 px in the worst case (a long Difference label, plus a velocity label that names
its fits), today's row has 77 px spare. With this layout nothing overflows: only the velocity
label elides.

### 4.2 #131: the Slice band button

- **Placement and default.** A checkable "Slice band" button after 1:1, on by default. *Placement and widget superseded by §4.14 W1; the behaviour below stands.*
- **Turning it off** hides the band in the view. The dock keeps `_slice_band` (the cube-clock
  window from `SlicesDock.window_changed`), so nothing is forgotten.
- **Turning it back on** draws the band at the current window, even if the window changed while
  the band was hidden. That means `_push_slice_band` must keep storing while the band is hidden.
- **Greyed out while there is no window** (`_slice_band is None`, nothing to show yet).
  - Its tooltip says why.
  - It becomes enabled on `set_slice_band` and greys again on `clear_slice_band`.
  - Its checked state survives being greyed.
- **Remembered across restarts** in `QSettings`. Read the key at dock construction and write it
  on toggle; use the key style the other nsgeo settings use.
- **The Slices panel being closed or hidden has no effect.** Only the button decides.
- **`plugin.py`.** No change is expected: lines 540–541 already deliver the window. If wiring is
  needed, it stays within those lines.

### 4.3 #5: Fit, Fit width, Fit height

- **Fit** is today's `ProfileView.fit()`: the whole ruler or line across, and the whole record
  down.
- **Fit width** shows the whole ruler or line across (`trace_bounds`) and keeps
  `time_lo`/`time_hi`.
- **Fit height** keeps `trace_lo`/`trace_hi` and shows the whole record down
  (`t0_ns` … `t_end`).

Both new operations are `ViewTransform` methods, applied through `with_window` (so it clamps)
and exposed on `ProfileView` like `fit()`.

**The split button.**

- Clicking the button runs its current action. The arrow menu holds Fit, Fit width and Fit
  height.
- Picking from the menu runs that action and makes it the button's action. The button's text
  becomes the action's name, as with Qt's `setDefaultAction`.
- It starts as Fit each time the dock is built. The pick isn't persisted.
- Tooltips say what each one keeps.

Fit width is what 1:1 did on campus lines that are shorter in traces than the image is wide. The
user's own M5 description was "it kept the vertical zoom and respaced the horizontal zoom".

### 4.4 #5: 1:1 means true scale

**What it does.** A metre of depth spans as many pixels as a metre along the line.

- **The along-line scale** is px per metre in the current window: image width ÷ metres across
  the window. Read the metres through the one position helper (§3.1, §4.7).
- **The down-the-line scale** is image height ÷ the depth span of the time window, using the
  velocity the depth axis uses (the view's `_velocity`).
- **Keep the window's middle time and the scale along the line.** Set the time span so the two
  scales match: Δt = (height ÷ px_per_m) converted to time at the window's middle depth.
  - For a constant velocity that is Δt = 2·Δz/v.
  - For a layered model, use the local slope dz/dt at the middle time. True scale is then exact
    only at that depth, which is acceptable and was shown to the user.
- **If the time span would exceed the whole record,** keep the whole record down instead (Fit
  height). Then narrow the window along the line about its middle until the scales match.
  - Example: a 30 m GPS line at Fit, where depth is stretched 1.7×, ends up showing about
    17.6 m.
- **The wheel keeps true scale afterwards,** because `zoomed` scales both spans by one factor.
  Fit, Fit width, Fit height and resizing the panel all leave it. Nothing tracks "being at 1:1";
  it's a one-shot action.
- **Greyed out, with a tooltip saying why, when either is missing:**
  - **no metres along the line,** i.e. a time-triggered line with no distance;
  - **no velocity,** i.e. no depth axis.
- Today's `one_to_one()` (one trace per pixel column) is removed. Tests that pin it are rewritten
  for the new meaning, not deleted silently.

Numbers at the user's size, for the walkthrough:

| Line | Across | Down (0.1 m/ns) | Vertical scale at Fit |
|---|---|---|---|
| `FILE__007` (11 m) | 113 px/m | 0–100 ns over 354 px = 71 px/m | depth squeezed to 0.6× |
| A 30 m GPS line | 42 px/m | — | depth stretched 1.7× |

### 4.5 #14: a failed velocity refresh clears the depth axis

`ProfileDock._refresh_velocity` (about line 2186) catches `KeyError` for cuts, but its generic
`except Exception` only logs. That leaves the previous line's model on the view and its label
on the toolbar.

**Fix:** in that branch, also call `view.set_velocity(None)` and clear `velocity_label`, then
log as now.

**Follow-on effects:**

- The depth axis goes blank.
- An axis set to m (§4.6) goes blank.
- 1:1 greys out.

### 4.6 #11: what each vertical axis shows

**The choices.** Each vertical axis, left and right, is set on its own to one of:

- **Time (ns):** today's left axis (`_time_ticks`).
- **Samples:** row indices of the radargram on screen.
  - **Ticks** sit on row centres (`t0 + (s + ½)·dt`), the same rule as the distance ticks'
    column centres. Labels are integers, from `nice_ticks` over the visible row range.
  - **What the count means:**
    - After Time zero, row 0 is the zero row.
    - While the Time zero row is selected (§4.11), row 0 is the first row of the step's input,
      so the number equals the step's `sample` field.
    - In a difference view, the rows are the difference's rows.
- **Depth (m):** today's right axis (`_depth_ticks`).
  - Blank when there is no velocity.
  - No ticks for negative times, so none above the line in §4.11.

**Defaults** are left ns and right m, as today.

**The caption** in the top row reads "ns ▾", "sample ▾" or "m ▾".

- "sample ▾" measures 46 px at the 8 pt axis font (Qt offscreen, Noto Sans).
- The left caption's rect is `MARGIN_LEFT − 6` = 50 px, so it fits there.
- The right one is `MARGIN_RIGHT − 8` = 40 px, so it doesn't, and drawText clips it. **Make
  `MARGIN_RIGHT` equal to `MARGIN_LEFT` (56).**
  - At the user's size the image becomes 1241 px wide, not 1249. §4.4's numbers barely move.
  - Re-pin any test that hard-codes the right margin or the image width.

**Choosing:**

- A **left or right click** anywhere on an axis strip opens a menu with three checkable items
  (Time (ns), Samples, Depth (m)). The strip is the margin beside the image, from the caption
  row to the bottom of the image.
- **Depth is disabled** with no velocity, with a tooltip saying why.
- **The view opens the menu** at the pointer (a `QMenu`) and emits a signal with the side and
  the unit. The dock stores the choice and persists it in `QSettings`, one key per side.

**Clicks on the strips change meaning.**

- Today a press anywhere, the margins included, arms `_press`: a click clears the trace
  selection, and a drag selects a range.
- After this, a press on a vertical axis strip opens the menu instead, and arms nothing.
- Presses on the image and on the bottom axis behave as today.
- In velocity mode, right-click inside the image still discards a point, and the strips' menu
  still opens.

### 4.7 #11: the cursor read-out

**Where it goes.** In the strip above the image, right-aligned to the image's right edge, with a
gap before the right axis's caption.

- It is painted by `ProfileView`, at 9 pt in the axis colour.
- Its rect is the whole `MARGIN_TOP` height (22 px), not `CAPTION_ROW` (14): 9 pt text is
  18 px tall. Over the image's width that strip holds nothing else. The topmost tick labels
  overhang only into the side margins.
- The bottom-right placement was mocked up and rejected. There, a distance tick label ran into
  it, and its descenders were clipped by the panel's edge.

**Format** (shown to the user):

```
4.23 m along (trace 254) · 22.95 ns · 1.15 m deep
```

- **First:** the position along the line, with the trace index in brackets. With no metres it is
  `trace 254` alone.
- **Then the left axis's value, then the right's,** each in its own unit:
  - ns: `22.95 ns`, the time of the sample under the pointer, `t0 + s·dt`;
  - samples: `sample 106`;
  - depth: `1.15 m deep`, which is left out with no velocity and above 0 ns.
- **When both axes use the same unit,** the value appears once.

Every value is for the one sample and trace under the pointer (`trace_at`, `sample_index_at`), so
they agree with each other and with the axes.

**Behaviour:**

- It shows while the pointer is over the image.
- It clears when the pointer leaves the image, including onto the margins.
- It has no switch.

**One place for position along the line, both ways.**

- Add one pair of `ProfileView` helpers:
  - trace coordinate → metres along (None with no metres);
  - metres along → trace coordinate.
  They are built on today's `metres_at` and `trace_units_at` over `self._distance`.
- **Every** conversion between traces and metres in the view goes through the pair:
  - `_distance_ticks` (both directions);
  - `window_m` and `set_window_m` (the held windows);
  - the read-out;
  - Fit width;
  - 1:1, including its narrowing along the line.
- The pair is where M17c swaps traces for distance. Its docstring says so.
- **Test:** monkeypatch the pair and see the ticks, the read-out and `window_m` all follow.

### 4.8 #163 item 2: a time zoom survives a clock change on the same line

**Today.** Adding or editing Time zero changes the line's zero and its record length (the crop).

- `_set_axes_holding`'s rule 1 fails, because `t0_ns`/`n_samples` changed.
- **On a ruler,** rule 2 re-applies the filed window as the same ns numbers, so the picture
  slides by the zero change.
- **With no ruler,** rule 3 needs equal axes, so the view goes back to Fit and the zoom is lost.

**When it applies.** The key is the same, `n_traces` and `dt_ns` are equal, and any of `t0_ns`,
`n_samples` or the shown `zero_ns` changed.

This is deliberately broad, and it is my call. It also applies to:
- adding, editing, selecting or deselecting a time cutoff;
- turning a step on or off;
- turning Difference on or off on a step that crops.

On a line with no ruler, these now keep the zoom where today they go back to Fit. That's the
point of #163, and nothing the user asked for needs the reset. Today's tests that pin a reset to
Fit there get re-pinned, and the plan names each one.

**The rule.**

- Shift the held time window by the zero change, `t' = retime_ns(t, old_zero, new_zero)`. The
  shift is 0 when only `t0`/`n_samples` changed. The features on screen then stay where they
  were, and the tick labels move by the change.
- **Top stays top.** If the old window started at the old record's top (`time_lo <= t0 + dt/2`),
  the new window starts at the new record's top with the same span.
- **A whole-record window** (filed as None) stays whole.
- **Both paths:** this applies with a ruler (the filed window) and without (rule 3 relaxed to
  the same key with `n_samples`/`t0_ns`/zero changed). `n_traces` and `dt_ns` must still be
  equal.
- **The trace window** is kept as today.
- **Clamping** is left to `with_window`.

`old_zero` is the zero of the radargram that was showing. **Trap:** capture it before
`_shown_radargram` is reassigned.

- `_render` sets `_shown_radargram = rg` (about line 1924) before it calls
  `_set_axes_holding` (about line 1925).
- `_take_down_picture` sets it to None (about line 849) before its own call.

How the zeros reach `_set_axes_holding` is the builder's choice.

§4.11 and §4.12 reuse this rule for selecting and deselecting the Time zero row and for releasing
a drag. It is the only mechanism for "what stays put".

### 4.9 #158: per-mode parameters and the `row` kind (nsgeo-core)

In `packages/nsgeo-core/src/nsgeo/processing/base.py`:

**Per-mode parameters.**

- `ParamSpec` gains an optional field saying which values of a sibling choice parameter it
  belongs to, e.g. `when=("mode", ("sample",))`. The field's exact name and shape are the
  builder's call.
- A spec without it belongs to every mode.
- `__post_init__` validates what it can. A schema-level check validates the rest: the named
  sibling exists, is a choice, and holds the listed values.

**The `row` kind.**

- `KINDS` gains `"row"`: an int row of the step's **input** record, counted from its first row.
  A front end may let the user drag it on the profile.
- It is validated like `int` (`base.py` around lines 343 and 352).
- Saved params stay plain ints, so saved sites load unchanged.

**Using it.**

- **Time zero.** `sample` becomes `kind="row"` with `when` `mode == "sample"`. `threshold`
  belongs to `mode == "first_break"`. Its help text drops "Used when mode is 'sample'"; the
  form now makes that true by itself.
- **Gain.** `gain.py`'s exponential and power parameters (the "used when mode is …" ones at
  lines 111 and 120) declare their modes too. This is my call: it follows from "each mode shows
  only its own settings".

**#210.** Its future mode on the tracer's edge declares no row parameter, so it gets no line.
Nothing else is needed for it now.

### 4.10 #158: the form

`ui/param_form.py`:

- **Hide fields outside the current mode.** A field whose `when` doesn't match the current value
  of its mode's combo is hidden, together with its label. It is shown again when the combo
  changes; choice combos already commit on change.
- **Bound the row field.** It is an int spin box bounded by `[0, n − 1]` from
  `step_inputs.input_axis` (`n_samples` of the step's input). Today `sample` has no upper bound.
- **Switching into `sample` mode seeds the row** at the first-break pick of the step's input,
  using the step's current threshold. The zero therefore doesn't move until the user drags or
  types.
  - It seeds on every switch into `sample`. That's my call: "switching modes never moves the
    zero" is the simple rule.
  - The input record is `stack.intermediate(row − 1)`, or the source for row 0. Where the seed
    lives is the builder's call; `step_inputs` is the natural home. Today `seed_params` only
    covers `migrate_fk`.
- **When no seed can be found,** the switch still commits, keeps the stored `sample`, and shows
  one toast naming the row it kept. Do not snap the mode back: the hand mode is the way out when
  the automatic pick fails. That's my call. The cases:
  - the samples haven't loaded;
  - the input has no arrival (`_first_break_or_none` is None);
  - the stack above the step doesn't run.
- **Re-show on `line_loaded`.** Today `ProcessingDock._on_line_loaded` re-shows only forms
  flagged `_form_axis_unknown`. That flag is set only for steps with a `time`-kind field
  (`processing_dock.py` about lines 594–614), so a Time zero form is never re-shown. Extend
  the flag to forms with a `row`-kind field, so that once the samples arrive, the row's upper
  bound and the profile line appear.
- `clock_unknown` is no help here. It looks only for Time zero steps above the row, so it is
  False for the first Time zero itself. What's missing before the load is the source.

### 4.11 #158: the profile handle, and the selected view on the line's clock

**The handle generalises today's cutoff line.**

- **Which steps get a line.** `profile_dock.time_param_name` becomes "the step's draggable
  parameter": the first parameter of kind `time` or `row` that is visible in the current mode.
  `_cutoff_row` and the identity check in `_on_cutoff_dragged` follow it. A step in
  `first_break` mode has no visible `row` parameter, so it gets no line.
- **Which side is dimmed** comes from the kind:
  - `time` (the cutoff's end) keeps what is above and dims below, as today;
  - `row` (Time zero's first kept row) keeps what is below and dims above.
- **Snap and range:**
  - `time` keeps `snap_cutoff`: `[t0 + dt, t0 + n·dt]`, end boundaries.
  - `row` snaps to row tops, `[t0, t0 + (n − 1)·dt]` on the shown axis, and maps to the row
    index `round((t − t0)/dt)` of the shown record. No ns value is stored.
- **Tag text:**
  - `time` keeps `cutoff_label` as today;
  - `row` reads `Time zero · sample 44` when still, and `sample 41 · −0.65 ns` while dragging
    (the row, and the offset from the line's current zero).
  The tag stays white on magenta, as now.
- **Colour.** The line and dimming use today's `CUTOFF_COLOUR` and `CUTOFF_DIM`.

**Which record is drawn while the row is selected (Q6, the user's pick after the review).**

- **`time` handle (the cutoff):** unchanged. The profile draws `stack.result_bypassing(row)`,
  i.e. every step except the cutoff.
- **`row` handle (Time zero):** *superseded by §4.14 Q3 (the bypass, with this as its fallback).* The profile draws **what the step receives**,
  `stack.intermediate(row − 1)`, or the source for row 0.
  - On the user's lines Time zero is first, so that is the record as recorded. The direct wave,
    which the zero is judged by, is drawn plainly.
  - Nothing after Time zero runs, so nothing can refuse it.
  - Its rows are exactly the step's rows.
- **Why not the bypass.** *Now the reason the fallback exists (§4.14 Q3).* `migrate_fk` refuses a record that starts more than 2 ns from zero
  (`MAX_T0_NS`, `nsgeo/processing/migration.py`). With Time zero skipped, the record starts at
  −11.09 ns, so the bypass fails on every line that is migrated. That was found in the design
  review and shown to the user, side by side, on a GPS line.
- **The display limit** for this view is taken from the drawn record itself, as for a
  difference view. `_scale_reference` must not run the stack below it. *Since §4.14 Q3 this
  holds for the fallback only; the bypass view takes the ordinary view's limit with Time zero
  also bypassed.*

**The selected view is on the line's clock (Build 2).**

- The input's `zero_ns` is the input's, not the line's. Before it reaches `_render`,
  **relabel** it onto the line's zero:
  - `t0' = t0 + (rg.zero_ns − line_zero)`;
  - `zero_ns' = line_zero`;
  - the data and row count are unchanged.
  - The line's zero is the result's `zero_ns`, i.e. `stack.zero_ns()` or `session.line_zero`.
- So the line reads 0 ns, the cropped rows read below zero, and everything under the line keeps
  its numbers.
- The cutoff's bypass doesn't change the clock, so the same relabel, applied there, is a no-op.
- `shown_zero_ns()` then returns the line's zero. Picks, the slice band, velocity fits and the
  gain strip's points already convert through it (`profile_dock.py` and `plugin.py`, 10 call
  sites), so they need no change.

**Selecting and deselecting use §4.8.**

- **Select:** the zero is unchanged, but `t0` and `n_samples` grow by the cropped rows.
  - At the top of the record, top stays top: the cropped rows slide in above the line, dimmed,
    at the same scale.
  - Elsewhere, nothing moves.
  - At Fit, the whole record now includes the strip, so it is about 10% shorter per ns on these
    lines.
- **Deselect** reverses it.

Real numbers, for the tests and the walkthrough:

| Line | Line's zero on the record clock | Record top | Rows cropped |
|---|---|---|---|
| `FILE__007` (campus) | −0.48 ns | −11.09 ns | 49 (10.6 ns) |
| `with-dzg/FILE__010` (GPS) | −1.56 ns | −11.09 ns | 44 (9.5 ns) |

`dt` is 0.2165 ns on both. The first-break pick is at the default threshold.

### 4.12 #158: drag, release, and the form

**While dragging:**

- The line snaps to rows and stays inside the record.
- The dimming follows it.
- The tag reads the row and the offset from the current zero.
- Nothing is written until release, the same as the cutoff (`DRAG_THRESHOLD_PX` and the grab
  rules unchanged).

**On release:**

- The dock writes the row as `sample` with `build_step` and `session.replace_step`, keeping the
  identity check against the step the line was drawn from. An unmoved handle writes nothing.
- The stack re-runs and the line's zero changes. The selected view is relabelled onto the new
  zero, so the line reads 0 again.
- By §4.8 the picture stays still and the tick labels shift by the change. That is the only
  label change the user causes.
- The Processing panel's form shows the new `sample`, because the stack change re-shows it as
  today.

**Typing a row in the form** goes through the same stack change, so the line moves to it.

**Rows count from the top of the drawn record,** which is Time zero's input (§4.11). So the row
under the line is exactly the step's `sample`, with nothing in between.

### 4.13 E's Difference rule holds

Selecting Time zero with Difference on:

1. `stack.difference(row)` raises `ValueError`, because the sample count changes.
2. `_decline_difference` runs: one toast, the button unchecks, the label clears.
3. `current_radargram` falls through to the step's input, relabelled (§4.11).

So the user sees the toast, then the line view.

- The input lies upstream of the difference, so a failure there would already have failed the
  difference with the same text. `declined` suppresses the repeat, so there is never a second
  toast.
- Nothing in F may return early before that fall-through.
- The plugin-level pin from session E stays green.
- One new pin covers `sample` mode on a line with migration after Time zero: exactly one toast,
  the button off, and the line up.

### 4.14 After the walkthrough (2026-11-21)

All 13 walkthrough checks passed. Q1, Q2 and Q4 are kept as built. Three changes follow from the user's notes and answers.

**Q3. Time zero's selected view keeps the processed look.** This supersedes Q6's "what Time zero receives" as the first choice.

- **What it draws.** While a `row` handle's step is selected, the profile draws `stack.result_bypassing(row)`, relabelled onto the line's zero. That is every step except Time zero, run on the uncropped record (picture 4 on the follow-up page). Its display limit is the ordinary view's, taken with Time zero also bypassed, so selecting the row doesn't change the look.
- **When it falls back.** It draws today's view instead (the step's input on its own scale, §4.11) when either:
  - the bypass raises, because a later step refuses the uncropped record; `migrate_fk` does, with `MAX_T0_NS`. That fallback emits no error; or
  - the bypass's rows don't start where the input's do: its first row is at a different radar-clock time (`t0_ns + zero_ns`), or its `dt_ns` differs. Then the line's row would mean something else; a second Time zero further down does this.
- **A shorter record is fine (task review ruling, 2026-11-21).** A time cutoff after Time zero cuts the bottom off the bypass. The top rows still line up, so the bypass is drawn, not the fallback. A guard on `n_samples` would make the usual stack (Time zero, then a cutoff) always fall back. In the bypass, the cutoff reads its `end_ns` on the clock Time zero would have changed, so its cut lands `zero_ns` earlier on the radar clock than in the ordinary view (later when `zero_ns` is negative). On the user's GSSI lines the header already puts zero near the first break, so `zero_ns` is about −0.5 ns: two rows. That is what leaving Time zero out means. The line's drag stops at the drawn record's last row.
- **Why.** Taken literally, "the processed scale" saturates the raw record: its limit is about 9.7 million against about 2.3. The user picked the processed record with this fallback.
- **E's rule is unchanged.** With migration after Time zero, there is still exactly one toast, and the profile shows the fallback view.

**W1. The band toggle is a checkbox.**

- It becomes a `QCheckBox` labelled **Show slice band**, placed after the colormap combo with the other display settings, away from Fit and 1:1, which it isn't part of.
- Its behaviour is §4.2's: it remembers its state, is greyed out with no window, and keeps the window while hidden.
- The attribute stays `slice_band_button`, so the tests keep their names.

**W5. Distance while dragging a selection.**

- While a range selection is being dragged on the profile (the drag that colours the map), the read-out shows the selection instead of the pointer:
  - `f"{d:.2f} m selected (trace {a}–{b})"`, where `d` is `abs(m(b + 0.5) − m(a + 0.5))` through the helper pair;
  - `f"{b − a + 1} traces selected (trace {a}–{b})"` when the line has no metres.
- It goes back to the cursor read-out on release.
- The distance comes through the helper pair, so M17c's true distance reaches it too.

## 5. Tests to pin

Each test must fail before its fix; the plan records the failing run. **Real-data tests** are
marked `real_data`, read lines through `tests/real_data.py`, and skip cleanly without the
lines:

- `FILE__007` for campus lines;
- the `with-dzg` lines for GPS.

- **#131**
  - Hiding and showing the band keeps the window.
  - A window change while hidden is drawn on re-show.
  - The choice survives a new dock, through `QSettings`.
  - The button is greyed with no window.
  - A closed Slices panel changes nothing.
- **#5**
  - Fit width keeps the time window and shows the whole ruler.
  - Fit height keeps the trace window and shows the whole record.
  - The split button repeats the last pick, and a new dock starts as Fit.
  - 1:1 matches px/m across and down, within one pixel, at constant velocity. Test it on a
    zoomed window, and at Fit on a long line, where the record-height fallback narrows the
    window along the line.
  - 1:1 is greyed with no velocity or no metres.
- **#14:** a refresh that raises clears the depth axis and the label (fake the resolver).
- **#11**
  - Each axis shows ticks in samples, ns and m.
  - The read-out matches the cursor in each unit. At a known pixel, assert the trace, the
    sample, `t0 + s·dt` and the depth.
  - Depth is greyed with no velocity.
  - The choices persist.
  - A press on a vertical strip opens the menu and leaves the selection alone.
  - The read-out and `_distance_ticks` use the one helper. A test monkeypatches the helper and
    sees both change.
- **#163 item 2.** A held time zoom survives:
  - adding Time zero, and moving its `sample`;
  - on a campus line (`FILE__007`, on a ruler) and a GPS line (with-dzg), `real_data`;
  - and on a line with no ruler, which today resets to Fit.
  Top stays top.
- **#158**
  - The `row` kind and `when` validate, including bad declarations.
  - Saved `time_zero` dicts load unchanged.
  - The form hides fields outside the mode (Time zero and gain), and bounds `sample` to
    `[0, n − 1]`.
  - Switching to `sample` seeds the first-break row.
  - The line shows only in `sample` mode, while the row is selected.
  - Selecting shows the line at 0 ns on the line's clock, with the dimming above it.
  - Selecting draws Time zero's input, not the bypass. On a line with `migrate_fk` after Time
    zero this shows the input, where the bypass would have refused. *Superseded by §4.14 Q3:
    the bypass is drawn, and this input view is its fallback.*
  - The drag snaps to rows and stays in range.
  - A released drag writes `sample`, and the form shows it.
  - A typed `sample` moves the line.
  - The selected view relabels so the line reads 0 again, and the picture holds still.
  - Real data: `FILE__007` and a with-dzg GPS line, with the row seed at 49 and 44.
  - E's rule still holds (§4.13).
  - The time cutoff's drag is unchanged. Today's cutoff tests stay green untouched.

## 6. Plans

One branch, one PR, one walkthrough. The work is split into two plans of 3–6 tasks each.

- **Plan A** covers #131, #5, #14, #11 and #163 item 2. A sensible order:
  1. #14 and #131 (small);
  2. the toolbar and Fit width/Fit height;
  3. 1:1 true scale;
  4. axis units;
  5. the read-out and the position helper;
  6. #163 item 2.
- **Plan B** covers #158 and comes after Plan A, because §4.11 reuses §4.8:
  1. core `when` + `row`;
  2. the form;
  3. the handle and drag;
  4. the line's-clock relabel and select/deselect;
  5. real-data pins.

Then:

- the local test recipe, and a check of branch CI;
- a deploy to its own QGIS profile;
- a walkthrough artifact, on a floating Profile panel at about 1361 × 448, covering:
  - the band hidden and shown;
  - Fit width and Fit height;
  - 1:1;
  - each axis unit and the read-out;
  - a time zoom held across a Time zero edit;
  - dragging Time zero by eye, with Difference on and off.

Merging asks the user first. On merge, close #131, #5, #11, #14, #158 and #163. #163 items 1 and
3–6 were done by sessions A and B.

## 7. Left to the builder

- Names: the `when` field, the position helper, the signals, and the `QSettings` keys.
- Where the seed for switching into `sample` lives (§4.10).
- How the dock gives `_set_axes_holding` the old and new zeros (§4.8).
- Tooltip wording, within the plain-language style of the plugin's other tooltips.
- Whether the handle draws for a disabled Time zero step. Match what the cutoff does today.
