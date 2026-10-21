# nsgeo display gain: a fixed scale for the gain curve, and a strip that shows headroom (#6, #10)

Two issues, one idea. #6 stops the profile's brightness scale from chasing the gain curve. #10
then draws, under the curve, how close the line is to burning out. #10 only works once #6 is in,
because "the edge of what can be displayed" is meaningless while that edge moves with every drag.

---

## 1. What this is for

The user's words, from the brainstorm: *"I wanted to balance the visualization of the data, but
I'd raise one area and the visual would lower the other, making it hard to see what I was doing."*

Today the display limit is recalculated from the final, already-gained data
(`nsgeo_qgis/render/qimage.py:52`, `PercentileClip(percentile).limit(rg.data)`). Any band the gain
curve lifts becomes part of the 99th percentile, raises the limit, and dims everything else. The
two symptoms filed in #6 follow from that:

1. `gain_curve` appears to do nothing unless `gain_agc` comes first. AGC flattens trace energy, so
   the curve's shaping survives the renormalisation.
2. Dragging a control point right brightens the profile near it up to a point. Past that point the
   rest of the image darkens instead.

What success looks like: lifting the deep part of a profile brightens the deep part and leaves the
shallow part as it was. Pushing too far burns that band out to solid black and white. While
dragging, the strip shows how close each depth is to that point.

---

## 2. Starting state, measured on `main` at `c4701e8`

| What | Where | State |
|---|---|---|
| Display limit | `nsgeo_qgis/render/qimage.py:52` | `RadargramImage.__init__` takes `PercentileClip(percentile).limit(rg.data)` from the radargram it renders. `with_display` and `with_radargram` both rebuild it. |
| Percentile slider | `ui/profile_dock.py:132-154`, `:262` | 50.0–100.0 %, inverted appearance, default 99.0. `_display_changed` rebuilds the image with the new percentile. Never saved. |
| Render path | `ui/profile_dock.py:648` `current_radargram`, `:699` `_render` | `stack.result()`, or `stack.difference(i)` while Difference is on. A preview of another line renders that line's stack through the same path. |
| Cached intermediates | `nsgeo-core/.../processing/stack.py:98` `_ensure`, `:115` `intermediate` | The output of every step is cached. Editing step *i* invalidates *i* onward. The input to step *i* is `intermediate(i - 1)`, or `source` when *i* = 0. |
| Gain strip | `ui/gain_strip.py` | 96 px fixed width (`:105`). Paints a grey dashed 0 dB line (`ZERO_COLOUR`, `:97`, `:221`), the blue curve and its handles, and the dB range at the top. Shown only while a step with a curve-kind parameter is selected. |
| Which step is "the gain curve" | `plugin.py:508` `_curve_param_name` | Decided by the schema's `kind == "curve"`, never by the step's name. |
| Cursor line | `ui/profile_dock.py:223`, `session.py:176` | `session.trace_changed` moves the orange cursor. It stays where it was last put. `current_trace` is `-1` until there is one. |
| Unused alternative | `nsgeo-core/.../render.py:80` `FixedRange` | A drop-in fixed limit already exists in core. Nothing uses it. |
| Render budget | `render.py:50` | ~120 ms normalise + LUT on a 512 × 6301 radargram for the whole render. Dragging a curve point re-renders on every move. |

---

## 3. Decisions

### Taken by the user

| Decision | Choice |
|---|---|
| What the scale does | It holds still while the gain curve is edited. Raising a band brightens only that band. Moving every point right overgains the whole profile until it burns out. |
| The percentile slider | Keeps its job of setting the overall brightness. |
| Where the scale is measured | On the data as it enters the gain curve, not after it. (Refined in §4.1. See the first call below.) |
| AGC and the parametric gain | Unchanged. Only the manual gain curve gets the fixed scale. |
| No jump on leaving the curve | The profile looks the same after the gain curve step is deselected as it did while dragging. |
| What goes under the curve | **Option E** from the mock-up: the line's envelope as a grey band, plus the trace under the orange cursor line as a thin black line. |
| How the envelope is measured | At each depth, the slider's percentile of the magnitudes across the line's traces. |
| Display limits | Two dotted lines. Anything past them is drawn red, in both the band and the trace. |
| Strip width | Stays 96 px. |

### Calls made by Claude (check these)

1. **The scale is measured on the profile as it would look with every gain curve switched off**,
   not literally on the gain curve's input. These are the same thing whenever the gain curve is
   the last enabled step, which is the normal case. They differ only when a step follows the
   curve. Measuring the literal input would blank the profile in an ordinary situation: add a
   `gain_agc` after an existing gain curve, and AGC's output (RMS ≈ 1) is drawn against a limit
   taken from raw amplitudes in the millions. With this rule, any later step is part of the scale
   and only the gain curves are not.
2. More than one gain curve: all of them are switched off for the scale.
3. A disabled gain curve counts as absent. With no enabled gain curve, the scale is today's.
4. **The Difference view keeps today's scale** (measured on what is shown). With Difference on,
   the strip draws the curve only, with no band, trace or limits.
5. A preview of another line follows the same rule, applied to that line's own stack. (The strip
   is already hidden during a preview.)
6. The band and trace show the data as displayed, at the end of the stack.
7. The band and trace are centred in the strip, on their own axis, separate from the curve's dB
   axis.
8. The 0 dB line becomes a light blue dashed line, so it belongs visibly to the blue curve and can't
   be mistaken for the dotted limits (they can sit within a few pixels of each other at the
   default dB range). The limits are dark grey dotted.
9. With no cursor (`current_trace == -1`, as right after a line opens), the strip shows the band
   alone.
10. The percentile slider gains a tooltip saying that, with a gain curve in the stack, the
    percentile is measured as if the gain curve were switched off.
11. **Selecting a row never changes the brightness.** The time cutoff (§9) shows the record with
    the cutoff skipped while its row is selected. The limit still comes from the real stack, with
    the cutoff applied and only the gain curves skipped. So selecting or deselecting the cutoff
    row moves the line's dimmed tail in and out of view without shifting the profile's brightness.
12. For unipolar output (`stack.output_unipolar`, an `amp_*` step after the curve) the band is
    one-sided, from the centre towards the positive limit, matching how the profile draws it.

---

## 4. Behaviour

### 4.1 The scale (#6)

For the stack being displayed, let **reference** be the radargram that stack would produce with
every enabled gain curve bypassed.

- **Display limit** = `PercentileClip(percentile).limit(reference.data)`.
- The rendered data is still `stack.result()`. Only the limit's source changes.
- With no enabled gain curve, reference is the result itself, so nothing changes for any stack
  without one. This must hold exactly. Every existing profile without a gain curve must look
  identical before and after.

| Stack (enabled steps, in order) | Reference | Display |
|---|---|---|
| … → background → **gain_curve** | output of background (the curve's input) | gained data against a fixed limit |
| … → **gain_curve** → bandpass | bandpass applied to the curve's input | follows the bandpass, fixed against the curve |
| … → **gain_curve** → gain_agc | AGC of the curve's input | not blank. AGC undoes most of the curve's shaping, which is the honest result. |
| … → **gain_curve** (disabled) | the result | today's behaviour |
| … → **gain_curve** → … → **gain_curve** | both bypassed | fixed against both |
| any stack, Difference on | n/a | today's behaviour |

Moving the slider changes the percentile taken on the reference. Changing a gain curve's points
never changes the limit. Changing any other step, or switching a gain curve on or off, changes the
reference and therefore the limit.

### 4.2 The strip (#10)

Drawn while the strip is shown, every time the curve, the stack, the percentile, the view's time
mapping or the cursor changes. Bottom to top:

1. **Envelope band.** For each displayed sample row *i*, `e_i` = the slider's percentile of `|d_ij|`
   over the traces *j* of the displayed data. Filled symmetrically about the strip's centre,
   light grey (≈ 12 % black). Past a limit, red.
2. **Cursor trace.** The displayed data's column at `current_trace`, drawn as a 1 px black line,
   red where it is past a limit. Omitted when there is no cursor.
3. **Limits.** Two dark grey dotted vertical lines at ±limit. Because the limit no longer moves
   with the curve, these stay put during a drag.
4. **Today's strip, unchanged except for call 8:** the 0 dB line (now light blue dashed), the blue
   curve, its handles, and the dB range labels.

Geometry, as in the mock-up (the builder may tune these after seeing them in Qt):

- Amplitude 0 sits at the strip's horizontal centre.
- ±limit sits at 80 % of the half-width inside `PAD_X`.
- Values beyond ±1.25 × limit are clamped to the strip's edge. The room between the limit and
  the edge is what shows how far over a depth has gone.
- Rows map to y through the same `ViewTransform` the curve already uses, so the band and trace line
  up with the profile at any zoom.

Red is `rgb(179, 38, 62)` in the mock-up. It must stay distinguishable from the profile's pick
colour (red-orange) and the planned time-cutoff line (magenta), although those are drawn in the
profile, not the strip.

Unipolar output (an `amp_*` step after the gain curve): the trace is one-sided on its own; the band
is drawn one-sided by call 12, because `e_i` is taken over magnitudes and would otherwise be
mirrored.

---

## 5. Performance

A drag must stay interactive within the existing render budget (~120 ms for a 512 × 6301 radargram,
`render.py:50`). The new work must not add a full re-evaluation per move:

- The reference does not depend on any gain curve's points, so it and its limit are computed once
  and reused until something other than a curve's points changes. When the curve is the last
  enabled step, the reference is already in the stack's cache (`intermediate(i - 1)`).
- The envelope must not cost a full per-row percentile on every move. Two acceptable routes, the
  builder's choice: take it over a deterministic strided subset of traces (the way `PercentileClip`
  subsamples), or, when the gain curve is the last enabled step, scale a precomputed reference
  envelope by the curve's per-row multiplier, since a per-row positive scale commutes with both
  `|·|` and the percentile.
- Cursor moves arrive on every mouse move over the profile. Repainting the strip for one may read
  one column and must not recompute the envelope.

---

## 6. Goals, non-goals, anti-goals

**Goals:** §4.1 and §4.2 as written, on both QGIS 3.40+ and QGIS 4.

**Non-goals:**

- No manual or typed limit, and no "lock scale" button. The slider stays the only control.
- No change to AGC, the parametric gain, the processing itself, or anything saved in a project.
  Display gain is still never recorded in a stack.
- No change to the Slices panel. It has its own stretch.
- No clipping readout ("x % burnt out"). The mock-up had one, labelled mock-up only.
- No change to the strip's width or to how points are dragged, added or removed.

**Anti-goals** (failures even if everything above technically works):

- Any profile **without** a gain curve looking different from today.
- A profile going blank or solid because of where a step sits relative to a gain curve.
- The image's brightness visibly jumping when any step, the gain curve or the time cutoff, is
  selected or deselected.
- A drag that lags behind the pointer on a long real line.

---

## 7. Documentation

- `docs/guide/getting-started.md:229`: the `gain_curve` bullet says what the band, the black
  trace, the dotted limits and the red mean, and that the curve now works without AGC.
- The `gain_curve` help-page draft (help-pages branch, git-ignored SDD workspace) describes the
  old renormalisation ("the top still sets the colour range"). That page is not on this branch.
  Note it in the help-pages ledger so the integration plan rechecks it. Don't edit it here.

---

## 8. Testing and the walkthrough

Real files first (`nsgeo-core/tests/data/local/`, gitignored). The input classes most likely to
hurt a user, each of which needs a test that actually feeds it:

1. A stack with no gain curve: the limit is bit-identical to today's.
2. Gain curve last, deep point raised on a real line: the limit does not change and the shallow
   rows' pixels do not change.
3. `gain_agc` after a gain curve: the profile is not blank (the scenario behind call 1).
4. Two gain curves, and one disabled curve.
5. Difference on while the gain curve is selected: today's scale, and the strip draws the curve
   only.
6. A preview of another line while a gain curve is selected on the working line.
7. Envelope by the strided or scaled route against a full `np.percentile(..., axis=1)` on a real
   line: same answer within a stated tolerance.
8. Cursor at `-1`, at trace 0 and at the last trace.

Then the standing build-and-walkthrough: deploy to a QGIS profile, publish a walkthrough page with
results recorded, and have the user balance a real line by hand on Windows QGIS 3 and QGIS 4
before any merge decision. The mock-up the user chose from is
`.lavish/gain-strip-overlay.html` in the main checkout. It is local only and is not committed,
because it embeds a real line.

---

## 9. Left to the builder

- Where "bypass every gain curve" lives. A core `StepStack` method is the natural home. **The time
  cutoff is being built in parallel** (`nsgeo-time-cutoff`; its Task 1 landed at `d5b1f70` on
  2026-10-21). It adds `StepStack.result_bypassing(index)` for a single index, which deliberately
  caches nothing and re-runs every step after the bypassed one on each call. That is fine for the
  cutoff but not for a drag (§5). Generalise it to a set of indices rather than add a second
  mechanism, and give the reference a cache that survives `replace_step` on a gain curve but not
  on any other change. The cutoff's Task 3 also rewrites `ProfileDock.current_radargram()` and
  `_render()`, the two functions §4.1 changes, so call 11 has to be honoured there.
- How `RadargramImage` receives the reference or its limit (an extra argument, or a `Normalizer`
  passed in).
- How the strip receives the envelope, the cursor trace and the limit from `ProfileDock`.
- Exact colours and line widths, within §4.2's constraints.

Both issues close on merge: #6 and #10.
