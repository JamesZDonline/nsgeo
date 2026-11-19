# nsgeo Processing panel: gain strip, Difference view and refusals — design

Session E of the issue-sessions plan (https://claude.ai/artifact/A1w1dKGNENHd2S2GbmqECj).
Settled in chat on 2026-11-18. Size M: a 4–5 task plan and one walkthrough on the Processing and
Profile panels.

Branch `nsgeo-processing-panel`, from origin/main 9691c7b (after M16 Plan C, PR #217).

- **Closes:** #49 (the gain strip passes ±120 dB, and keeps a refused or unreachable point), #8
  (clipped caption), #9 (reset), #13 (Difference after a drag-reorder), #48 (Difference after
  selecting Time zero: already fixed on main, pinned here), #197 (a refusal stays in the panel).
- **Comments, issue stays open:** #15 (the three gain slots are guarded; the sweep of the rest of
  `plugin.py` waits for the milestone branches), #20 item 4 and #25 items 3 and 4 (done here; both
  issues stay open for session N).
- **Decided after the fixes:** #21 (split `processing_dock.py` or not), §9.
- **#33:** explained, given a cue (§7). Closed only if the walkthrough reproduces it and the cue
  answers it.
- **Follow-up, not built:** the open-project summary (#194) in the same Warnings box. Recorded as
  a comment on #197 (user, 2026-11-18: "leave it as a follow-up").

The Processing panel is 433 px wide in the user's `ns_geo` profile (its minimum; tabbed with
Slices in the right dock area). The Profile panel floats at 1361 × 448; the gain strip is a fixed
96 px at its right.

## 1. What this is for

The Processing panel is where a line's steps are set, and three things there mislead:

- **A refused step is told in a toast and then forgotten.** A Dewow window of 0.2 ns on FILE__007
  (Δt 0.2165 ns) is refused with "Dewow window 0.2 ns is one sample at this line's 0.217 ns
  sampling; use 0.33 ns or more." The text reaches only the message bar, for six seconds, and
  wraps out of sight. The profile quietly keeps the old picture. Nothing in either panel says why.
- **The gain strip can show a curve the step doesn't have.** A drag can go past the core's
  ±120 dB, and the strip keeps the refused point. A point that falls outside the record can be
  neither reached nor removed, yet it still shapes the curve. The only way back to flat is to
  remove the step and add it again.
- **The Difference view can name the wrong step** after a drag-reorder, and the panel never says
  which line its steps belong to (#33's "vanishing" steps).

**Success:** while a step can't run on the open line, the panel says so, next to the step, until
it is fixed. The strip only ever shows the curve the step has, every point on it can be grabbed,
and Reset gets back to flat. The Difference view always shows the selected step. The panel names
its line.

**Anti-goals:**
- A note for something that is no longer true. A note is for what is still so; a toast is for
  what just happened (the Slices panel's rule, `ui/warnings_panel.py`).
- Anything that widens the Processing panel. `test_plugin_slices_width.py` pins the Slices panel
  to the Processing panel's minimum width, so every new label wraps and must not raise
  `ProcessingDock.minimumSizeHint().width()`.
- Edits in `profile_dock.py` beyond the Difference view, the gain strip and the error/refusal
  wiring. Session Q may add to the velocity strip there.

## 2. Decisions taken with the user

1. **The refusal goes in a Warnings box under the step list** (mock-up option A). It sits between
   the row it names and the settings that fix it, and it shows whichever row is selected.
2. **Reset sits at the foot of the gain strip** (option R1), and asks first, because there is no
   undo.
3. **A curve the core refuses snaps back, with a toast.** The strip shows the step's real curve
   again, and the message bar says why. Not a note: after the snap-back nothing is still wrong.
4. **The open-project summary stays out** (follow-up on #197).
5. **The Processing panel checks its own line's steps** to decide whether a step can't run
   (approach A, §8), and **the core says which step refused** (§3.2).
6. My calls the user saw in the mock-up and let stand: the caption measured by the font (§4.3),
   off-record points as edge handles (§4.2), the line named at the top of the panel (§7), and #48
   pinned rather than re-fixed (§6.2).
7. My calls after the builder check, for the user to check while reading: a hover preview of a
   refusing line gets its own message (§3.6); the gain strip waits for its clock before it is
   shown (§4.4); #20 item 4 is pinned on `_clear` directly, since no real path reaches it (§6.3).

## 3. A refusal that stays (#197)

### 3.1 What is a refusal, and what stays a toast

**A refusal** is a step that can't run on the open line: evaluating the working line's steps
raises the core's `StepRefused` (§3.2). Examples: the one-sample Dewow window, a bandpass whose
band can't hold a frequency, a high cut past Nyquist.

**These stay toasts only:**
- A Difference view being declined: the step changes the sample count (selecting Time zero), or
  the differenced step no longer exists. The view switches off and the ordinary view shows;
  nothing stays wrong.
- A refusal met while a map hover previews another line. The panel belongs to the working line.
- A gain curve the core refuses (decision 3).
- Anything that is not a step refusing: "stack has no source radargram", an `IndexError`, a
  non-`ValueError` exception. These keep today's handling.

The toast is unchanged: `ProfileDock.error` → `plugin.message` still announces every refusal the
profile meets. The note is additional.

### 3.2 The core says which step refused

`nsgeo.processing.stack` gains `StepRefused(ValueError)` with `index` (0-based position in the
stack) and `title` (the step's title). `StepStack._ensure` and `result_bypassing` catch a
`ValueError` from `step.apply` and raise `StepRefused(index, title, str(exc)) from exc`.

- `str(exc)` is exactly the step's own message, so every existing `except ValueError` and every
  message assertion keeps working.
- `difference()`'s own sample-count `ValueError` and "stack has no source radargram" stay plain
  `ValueError`: neither is a step refusing.
- Exported from `nsgeo.processing` beside `StepStack`.

### 3.3 The Processing panel's check

`ProcessingDock` re-checks the working line whenever it rebuilds (`line_opened`, its own line's
`stack_changed`, `site_closed`) and when its line's samples arrive (`line_loaded`):

- No line, a cut, or no samples loaded yet: no note.
- Otherwise it calls `stack.result()` on the working line's stack. The Profile panel has usually
  just computed it on the same signal, so the cache makes this nearly free.
- `StepRefused`: the note shows for that step. Any other exception: no note, logged (the check is
  inside a slot and must never raise).

**Known gap, accepted:** the profile shows a time cutoff's bypass while a cutoff row is selected.
A step that fails only on the uncropped record (after a cutoff, breaking only when the cutoff is
bypassed) is a toast without a note. Not reachable by hand that anyone has found.

### 3.4 What the note shows

- **The row:** its text starts with "⛔ " and is dark red (#a3122c on the light palette; the
  selected row keeps the selection colours). Its tooltip is the note's text.
- **The box:** `WarningsPanel` from `ui/warnings_panel.py`, reused as it is, placed between the
  step list and the parameter form, hidden when empty. One `REFUSAL` entry:

  > ⛔ Dewow (step 2) can't run on this line: Dewow window 0.2 ns is one sample at this line's
  > 0.217 ns sampling; use 0.33 ns or more. The profile won't update until this is fixed.

  The step number is 1-based, as the user counts rows. Only the first refusal is shown: the
  steps after it never run, so nothing is known about them.
- Every new label wraps and keeps an Ignored horizontal size policy (§1 anti-goals).

### 3.5 When it clears

On every re-check that finds the steps run: the setting is fixed, the step is removed or turned
off, a preset replaces the steps. It also goes when another line opens (that line is checked
afresh) and when the site closes. An edit to some other step while the refusing one still
refuses leaves the note, because it is still true. A new refusal replaces the old note.

### 3.6 A line that opens with a refusal

Found while writing this (verified offscreen): open a line whose steps refuse, and the Profile
panel's title names the new line while the view still shows the **previous line's** picture
(`dock.image` is None, `view._image` is not). Within the same line, keeping the last picture after
a bad edit is deliberate (module docstring). Across a line change it is wrong.

When `_render` has nothing to draw because a line was just put on screen or loaded
(`_show_line` or `_on_line_loaded`, not a stack edit), the view is cleared and says so through
`view.set_message`:

- **The working line:** "This line's steps can't run. See the Processing panel."
- **A hover preview** (the same bug today: the title says "PREVIEW: FILE__003" over the previous
  picture): "FILE__003's steps can't run. Select it to see why in the Processing panel." The
  panel has no note for a previewed line (§3.1), so the message doesn't point at one that isn't
  there. This comes up often: after Apply to grid copies a refusing setting, every hover over the
  grid meets it.
- **Back from a preview** (`_exit_preview` goes through `_show_line`) to a working line that
  refuses: the cleared view and the working line's message. The last good picture is not brought
  back; the note in the panel says why.

My call, since it is the profile half of the same complaint; say if it should be filed instead.

## 4. The gain strip (#49, #8, #9)

### 4.1 Limits (#49 part 1)

- `_db_range` never extends past ±120 dB: `lo = max(-120, min(-6, min(dbs) - 6))`,
  `hi = min(120, max(24, max(dbs) + 6))`. The strip's edges are the core's limits, so a drag to the
  edge lands on 120, never past it. The frozen-range rule during a drag is unchanged.
- Every value the strip writes (move, double-click) is clamped to ±120 as well, in case a range
  was frozen from points that were somehow already outside.

### 4.2 Points outside the record (#49 part 2)

The strip learns the shown record's time extent (first and last sample time of what the profile
draws, on the shown clock) from `ProfileDock` alongside the time mapping. A point earlier than the
first sample draws as a ▲ handle on the record's top edge, at its own dB; a point later than the
last sample draws as a ▼ on the bottom edge. The curve itself is drawn as it applies, crossing the
edge at the value the record actually gets, so the ▲ and the line need not touch.

- `handle_at` finds an edge handle at its drawn position, so it can be dragged (its time becomes
  the time under the cursor, inside the record) or right-clicked away (never below two points).
- Points outside the zoomed window but inside the record are left as they are: zooming out
  reaches them.
- Nothing changes until the user touches the handle.

### 4.3 The caption (#8)

Placed with `QFontMetrics`: the low value left-aligned at the strip's left edge, the high value
right-aligned at its right edge, "dB" centred between them. If the three don't fit, "dB" is
dropped first. Digits are never cut. Number formatting stays `:g`.

### 4.4 Reset (#9)

- A small "Reset" button, a child of `GainStrip`, in the strip's bottom margin (the 28 px under
  the time axis, level with the profile's distance axis). It shows and hides with the strip.
- It emits `reset_requested`; `ProfileDock` relays it as `gain_reset_requested`, as it relays
  `points_changed`.
- `plugin.py` handles it (§5): if every point is already 0 dB there is nothing to lose, so it
  writes the flat curve without asking. Otherwise it asks: "Reset the gain curve to a flat 0 dB?
  Its N points will be lost." (Yes / No.)
- The flat curve is `identity_curve(t0, dt, n)` on the input the step receives
  (`ProcessingDock.input_axis(row)`), the same curve a new Gain curve step starts with, written
  through `replace_step` with the same identity check a drag uses.
- **The strip waits for its clock.** Today the strip is shown before a line's samples load: the
  view's axes come from the header, so with an enabled Time zero above the curve the stored
  points (on the Time zero clock) are drawn against the radar's clock, offset by the line's zero.
  `_sync_gain_strip` hides the strip whenever `input_axis(row)` is None (no samples, a Time zero
  above), and `_resync_gain_strip` (already on `line_loaded`) shows it once they arrive. So the
  strip only ever draws the curve on the right clock, the edge handles of §4.2 land where they
  belong, and Reset is never reachable without an input axis.

### 4.5 A refused curve snaps back (#49, decision 3)

When `build_step` refuses the strip's points, `_on_gain_points` gives the strip the step's real
curve again (through `show_gain_strip` with the current owner and the step's input clock) and
toasts the reason. Mid-drag the strip refuses that payload (its first invariant); the release
emits again, is refused again, and the snap-back then lands. With §4.1 in place no gesture
reaches this; it is a backstop.

## 5. The gain slots (#15, #25 items 3 and 4)

- `_sync_gain_strip`, `_resync_gain_strip`, `_on_gain_points` and the new reset slot each guard
  their whole body with `try/except Exception` and report through `self.message(...)`, as the
  module docstring requires. The docstring's policy is right and stays as written.
- **The sweep of the rest of `plugin.py` waits.** M17a, M19a and M16 Plan D all have open
  branches that add slots there. Said on #15.
- **#25 item 3:** `show_gain_strip`'s docstring is corrected, not the signature (no call-site
  churn in a file three open branches edit). The sentence says a `None` owner with real points is
  honoured as a different owner only when the strip shows a real one, and that callers always
  pass a real token.
- **#25 item 4:** `unload()` clears `_gain_owner` and `_gain_step` beside the docks.

## 6. The Difference view

### 6.1 After a drag-reorder (#13)

Verified on main: Difference on Background removal (row 1), drag it below AGC: the selection
follows it to row 2, but the view stays on index 1 and the label says "Difference: Automatic gain
control".

**Rule: the Difference view always shows the selected step.** `_on_rows_moved`, after
`move_step`, re-aims the view at the current row when the button is checked, as ↑ and ↓ already
do through `setCurrentRow`. If the moved step can't be differenced (it changes the sample count),
the decline of §3.1 applies.

### 6.2 Selecting Time zero (#48), and the rule session F builds on

Already fixed on main by the time-cutoff work (ruling R7, b5dca3e, 2026-10-21): a declined
Difference view falls through to the ordinary view. The issue's own repro now shows the result.
Pinned here at plugin level with the issue's exact steps (the existing test is dock-level). The
test passes on main; it must fail when `current_radargram`'s fall-through is removed.

**The rule, for session F (#158, set Time zero by dragging):** with Difference on, selecting a
step that changes the sample count (Time zero) turns the Difference view off: one toast, the
button unchecks, the label clears, and the profile shows the ordinary view (the result, or the
cutoff's bypass while a cutoff row is selected). It is a toast, not a note (§3.1). F must keep
this when it changes what the profile shows while the Time zero row is selected.

### 6.3 `_clear` resets the Difference view (#20 item 4)

No real path reaches `_clear` with a Difference view showing: `close_site` emits
`line_opened("")` before `site_closed`, and `_open("")` resets the view first (#20's "no
reachable precondition today"). So the pin is two parts:
- **the method:** with a Difference view showing, `ProfileDock._clear()` called directly leaves
  `_difference_index == -1`, the label empty and `difference_cleared` emitted. This part must fail
  without the reset in `_clear`; its docstring says no real path reaches it today and that it
  guards the day one does;
- **the outcome:** closing the site for real with Difference on leaves the button unchecked and
  the label empty.

## 7. Which line the steps belong to (#33)

The user's comment on #33: several lines were selected on the map, so none was promoted, yet
steps could be added; they "disappeared" once one line was selected. `MapLink._on_selection` does
nothing for a multi-selection, so the steps went onto the line already open, and selecting another
line showed that line's steps. Nothing was lost. A cue, not a guard.

A label at the top of the Processing panel names the working line:
- "**FILE__007** · grid A" (the Survey panel's name, `velocity_records.line_label`; the grid id
  when the line is in one).
- While a map hover previews another line: "**FILE__007** · grid A · the profile is previewing
  FILE__003" (`session.preview_changed`).
- No line open, or a cut: empty (the cut already says "Processing does not apply to a cut.").
- Wraps; Ignored horizontal size policy.

A test pins the multi-select path: two features selected on the lines layer, a step added, then
one line selected: the step is on the line that was open, and the label named it throughout.

## 8. Approaches considered

**Who decides that a step can't run (#197).**
- **A. The Processing panel checks its own line's steps** (chosen). One place, no new wiring out
  of `profile_dock.py`, works with the Profile panel closed, and covers a step failing upstream of
  a Difference view. Blind to a refusal met only in a cutoff's bypass (§3.3).
- B. The Profile panel reports what it failed to draw, over new signals through `plugin.py`.
  Exact to the screen, but more wiring near session Q's area, a preview filter, and silent with
  the Profile panel closed.

**How the panel knows which row (#197).**
- **The core raises `StepRefused` with the index** (chosen). Exact for both chains, a few lines.
- The plugin walks `intermediate(i)` until one raises. No core change, but repeats the stack's
  work and doesn't cover the bypass chain.

**Where the note goes:** under the list (chosen), with the step's settings (out of sight on any
other row), or at the panel's foot (far from the row). **Where Reset goes:** foot of the strip
(chosen), on the Gain curve's settings in Processing (away from the curve), or right-click (hidden,
and one slip from removing a point). Mock-ups in the chat's lavish page, 2026-11-18.

## 9. #21: split `processing_dock.py`?

Decided after the fixes, with a recommendation to the user. If a split is recommended it is the
last task, with no behaviour change; otherwise #21 gets a comment or a follow-up. No open branch
edits that file today.

## 10. Tests to pin

Each must fail before its fix (the #48 test: fail when the fall-through is removed, §6.2).

- A drag past the strip's edge lands at 120 dB, not above; `_db_range` never exceeds ±120.
- A curve the core refuses is replaced on the strip by the step's real curve, with a toast.
- An off-record point draws on the edge, is found by `handle_at`, can be dragged in and
  right-clicked away.
- The caption's three parts fit inside 96 px at the test font and at a large one.
- Reset: asks when points are lost, writes `identity_curve` on the input clock on Yes, nothing on
  No, no question when already flat.
- With Difference on, selecting Time zero puts the result back on screen (#48's repro, plugin
  level).
- A drag-reorder re-aims the Difference view at the moved, selected step.
- `_clear` resets the Difference view (#20 item 4).
- A refusal stays visible until it is fixed, and clears on an edit, a removal, turning the step
  off, opening another line and closing the site; an edit to another step leaves it.
- A line opened with a refusal shows the profile's message, not the previous line's picture; a
  hover preview of one shows the preview wording.
- With an enabled Time zero above a gain curve and no samples loaded, the strip is hidden; it
  appears on `line_loaded`, with the points on the Time zero clock.
- An exception in each gain slot (three existing, plus reset) is reported through `message`, not
  swallowed.
- The new labels never raise the Processing panel's minimum width (with a long line name and a
  long refusal).
- **Real line:** FILE__007 for the strip and for the one-sample Dewow refusal (the exact text
  above), marked `real_data`.

## 11. Constraints and other sessions

- **Files:** `processing_dock.py`, `gain_strip.py`, the gain-slot and unload parts of `plugin.py`,
  the Difference/strip/error parts of `profile_dock.py`, `nsgeo/processing/stack.py` (+
  `__init__`), the guide's processing section (§12), tests.
- **Session F** comes after E and builds on §6.2's rule.
- **Sessions H, K, N, Q and R** may run alongside. None edits `processing_dock.py` or
  `gain_strip.py`; Q may add to the velocity strip in `profile_dock.py`.
- **Open branches touching `plugin.py`** (M17a, M19a, M16 Plan D): keep this branch's edits there
  to the gain slots and `unload()`, to keep merges small.
- The guide's known-issues section is untouched: none of these issues is listed there.

## 12. The guide

`docs/guide/getting-started.md`, the Processing section:
- the "refused with a message" paragraph says the reason stays under the step list, with the
  step marked, until the setting is fixed;
- the gain strip paragraph mentions Reset, that the strip stops at ±120 dB, and the edge handles;
- one line that the panel names the line its steps belong to.

## 13. Walkthrough

On its own QGIS profile, with FILE__007:
- drag the gain strip to both edges (stops at ±120), then Reset (asks; flat);
- read the caption with a narrow panel and large values;
- seed a curve, insert Time zero above it, reach the ▲ handle;
- reorder steps by drag with Difference on, then select Time zero;
- set Dewow to 0.2 ns: the note and the row mark stay until fixed; clear it by each route;
- open another line with a refusing step: the profile says so instead of the old picture; hover
  over one too;
- an attempt at #33: several lines selected on the map, add a step, then select one line.

## 14. Left to the builder

The exact pixel geometry of the Reset button and the edge-handle shape; how the strip receives the
record's extent (an argument to `set_time_mapping` or its own setter); the dark-red colour in a
dark palette; test structure and fixtures; whether the `StepRefused` message prefix or the note's
wording needs a helper.
