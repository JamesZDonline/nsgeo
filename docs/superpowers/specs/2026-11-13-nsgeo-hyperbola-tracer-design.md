# nsgeo trace a hyperbola from a box — design

In velocity mode, dragging a box around a diffraction hyperbola makes the plugin trace it. It
marks about ten dots on the outer edge of the hyperbola's top band and draws the fitted curve,
exactly as if the author had clicked them. The author then removes or adds dots and saves the
fit as today. Ctrl+click (Cmd+click on a Mac) places velocity dots, or draws a box, without first
switching velocity mode on.

Closes #140 (option 1; option 2, snapping hand clicks, was declined, and option 3 is a
follow-up) and #88.

Built from main cc9e51d. This is the third piece of the velocity bundle: pieces 1 (#126, #128)
and 2 (#127, #86) have merged.

---

## 1. What this is for

The author measures velocity by clicking a diffraction hyperbola, apex first, then down both
legs. In their words, it is hard "because it can be difficult to get the exact apex, and the
precise boundaries of the 'legs' are somewhat blurred in the pixelated edges".

They mark the **outer edge of the top reflection band**, because "by hand I can't tell where in
the mass of black or white is the maximum (or middle) of the amplitude change. So the edge was
where I felt I could be as precise as possible."

The goal is marks that can be repeated. Boxing the same hyperbola a little differently should
give the same velocity, within its σ. The author trusts the result when **the displayed curve
lines up with where they see the hyperbola in the profile**.

**The edge is the right place to mark.** Booth, Clarke & Murray (2010, *Near Surface
Geophysics* 8:235, doi 10.3997/1873-0604.2010008) found that only the first break of a GPR
wavelet carries the true travel time and velocity. Later half-cycles give slower velocities.
Booth & Pringle (2016, *J. Applied Geophysics* 125:37) say the same for diffraction hyperbolas.
The edge also matches the plugin's own clock: the Time zero step puts 0 ns at the direct wave's
first break (§2). Marking edge against edge cancels the offset. A fixed shift is something a
hyperbola cannot absorb, so marking the bright middle against a first-break zero would bias
every fit.

## 2. Starting state (main cc9e51d)

- **Toolbar.** The `Velocity` and `Pick` toolbar actions (`plugin.py`, `act_velocity` and
  `act_pick`) exclude each other.
  - Shift+click authors a pick in any mode.
  - `VELOCITY_TIP` reads: "Velocity mode: click a diffraction hyperbola on the profile, apex
    first. Right-click a point to remove it."
- **The press chain.** `ProfileView._handle_mouse_press` resolves a press in this order:
  1. middle button pans;
  2. a right-click in velocity mode discards the nearest dot (within `VELOCITY_DISCARD_PX`);
  3. a left press with Shift, or in pick mode, authors a pick;
  4. a left press in velocity mode emits `velocity_point_requested(trace, time)` **on press**;
  5. otherwise the press grabs the time cutoff or starts a selection drag.

  A left drag in velocity mode does nothing today.
- **A velocity click in the panel.** `ProfileDock._on_velocity_point_requested`:
  - refuses on a preview;
  - clears the after-Save state (`_just_saved`);
  - appends `(trace, radar-clock time)` via `retime_ns`;
  - refits.

  Cuts are refused ("a cut has no velocity fit").
- **The fit.** It is `fit_hyperbola(x_m, t_ns, x_m[0])`, so **the first dot is the apex guess**.
  The apex is searched within ±0.25 m of the guess in 101 steps. A fit needs at least 3 points,
  or 4 while searching. A saved fit's `refit` also takes its first point as the guess.
- **The drawing.** The profile draws the working fit as an orange 2 px curve with blue dots.
  Saved fits are drawn as faint curves.
- **Time zero.** The `first_break` mode (`processing/timezero.py`) puts 0 ns at the first sample
  where the trace-mean |amplitude| reaches **0.2** of its peak, to a whole sample.
- **Step names.** Migration is `migrate_fk`. The amplitude transforms are `amp_abs`, `amp_square`
  and `amp_envelope`.
- **What is drawn.** The panel draws `_shown_radargram`. That is the stack's result, the result
  with the time cutoff bypassed while its row is selected, or a difference view.
- **Saved fits** (`StoredFit`) keep the dots as `(trace, radar-clock ns)` with float times, plus
  the fit numbers and when the fit was made.

## 3. What the author decided (2026-11-13)

1. **The tracer follows the outer edge** of the top band, the same spot they mark by hand.
2. **About 10 dots**, not one per trace.
3. **Refuse after migration or an amplitude transform (Absolute, Square, Envelope), and say why.**
   Migration has collapsed the hyperbolas. An amplitude transform removes the edge the tracer
   follows.
4. **The gesture.**
   - In velocity mode a **click places a dot and a drag draws a box**, as QGIS's Select Features
     tool does. There is no separate box mode.
   - A right-click still removes a dot.
   - A box replaces the working dots.
   - Hand dots never snap.
   - A box with no clear hyperbola draws nothing and says why.
   - Half a hyperbola (apex and one leg) works.
5. **The result arrives as ordinary working dots and the orange curve.** The author removes or
   adds dots, then uses Save fit or Apply, all as today.
6. **Ctrl+click on Windows and Linux, Cmd+click on a Mac** places a dot (Ctrl+drag or Cmd+drag
   draws a box). It **switches Velocity on and leaves it on**. The author wants to try how this
   feels in the walkthrough.
7. **A saved fit keeps only its dots, as before.** It records nothing about being traced, the
   box or the edge rule.

## 4. The tracer (core)

A new module, `nsgeo/hyperbola_trace.py` (the name is the builder's call). It is numpy only and
runs on Python 3.9, like the rest of the core.

**Inputs:**
- the drawn radargram's amplitudes;
- its time axis, on the clock the fit uses (the line's own clock, the one its stack calls 0);
- the line's distance at each trace, in metres;
- the box: first and last trace, earliest and latest time.

**Never assume even trace spacing.** Read the distance at each trace. M17's later "profiles at
true distance" plan makes spacing uneven.

### 4.1 Find the hyperbola

Scan these candidate curves, t(x) = √(t0² + 4(x − x0)²/v²):
- **Apex position:** inside the box. The apex must lie inside the box (decision 4).
- **Apex time:** inside the box.
- **Velocity:** 0.03–0.30 m/ns. The fit's own bound is c ≈ 0.3. Soils at this site measure about
  0.07. *(My call.)*

Score each curve by the energy along it, using the box's traces where the curve lies inside the
box. Normalise the score so that short and long curves compare fairly. Search coarse to fine.
Keep the best. When a box holds two hyperbolas, or a hyperbola crossing a reflector, the
stronger one wins, and the drawn curve shows which it took.

The exact score (mean envelope, or a semblance like #125's sweep) is the builder's call. Tests
pin the outcomes (§10).

### 4.2 Mark the edge on each trace

On each trace in the box, look at the reflection band near the chosen curve, within about one
wavelet period. The edge is where the signal first reaches **0.2** of that trace's peak in the
band. It is read between samples by linear interpolation. 0.2 is the Time zero step's fraction,
so the two offsets cancel *(my call)*.

Two traps the rule must avoid:
- **a zero crossing inside the band**, which would put the edge on a later lobe and bias the
  velocity slow;
- **noise just before the band.**

Measuring on the amplitude envelope, or stepping back from the band's peak, avoids both. How is
the builder's call.

**Required:** for the same wavelet, this rule and the Time zero step's `first_break` rule land
within one sample of each other. A test pins this.

A trace whose band peak is too weak to stand above the noise gives no edge. This is where a
fading leg ends.

### 4.3 Clean up, then thin to about 10 dots

1. Fit every trace's edge with `fit_hyperbola`, taking the apex guess from the scan.
2. Drop the edges that disagree, such as a leg crossing another reflection or a noise spike.
   Refit. The robust rule is the builder's, for example a residual over 3× the median absolute
   residual.
3. Keep **about 10** of the survivors, spread evenly along the traced extent.
   - Always keep the edge nearest the apex, and put it **first**: the fit, and a saved fit's
     refit, take the first dot as the apex guess.
   - Fewer survivors give fewer dots.
   - Fewer than 4 dots gives no result.

Why thin: neighbouring traces are not independent readings. Sixty dots would make σ look several
times better than it is, and that would mislead the grid average and its 2σ flag.

### 4.4 Output

The tracer returns the dots as `(trace, time)` on the clock it was given, apex-nearest first. It
does not return a fit: the panel fits the dots exactly as it fits clicked ones. A traced fit is
therefore saved, refit and averaged the same way as a hand fit.

On failure it raises `ValueError` with a plain reason, as `fit_hyperbola` does. The reasons:
- the box is too small;
- there is no hyperbola in the box;
- the hyperbola is too faint to trace;
- too few dots are left after cleaning;
- any reason `fit_hyperbola` itself gives.

### 4.5 Speed

Search coarse to fine. Target: dots appear within about a second for the largest box measured on
the real lines. It runs on the UI thread with a wait cursor *(my call)*. If the measurements show
a box size that cannot meet the target, refuse boxes above that size with a reason; never freeze
QGIS. Record the measured times in the ledger.

## 5. The gesture (profile view)

**A left press starts the velocity gesture** when it is inside the radargram and either velocity
mode is on or Ctrl is held.
- If the pointer moves beyond Qt's start-drag distance, a box is drawn while dragging: a dashed
  rectangle in the selection colour.
- **On release after a drag,** the view emits a new signal, `velocity_box_drawn(first_trace,
  last_trace, top_time, bottom_time)`, clipped to the radargram. The name is the builder's call.
- **On release without a drag,** it emits `velocity_point_requested` at the press position.
  Today this is emitted on press. Emitting it on release makes no visible difference, and it is
  how a click is told from a drag *(my call)*.

**Right-click** is unchanged.

**Ctrl (Cmd on a Mac).** Qt reports Cmd as `ControlModifier` on macOS, so one check covers all
three platforms. On a Mac a physical Control+click arrives as a right-click, which in velocity
mode removes the nearest dot, as any right-click does. The builder confirms that QGIS does not
set `AA_MacDontSwapCtrlAndMeta`.

**The new press order** for a left press:
1. **Shift without Ctrl**, or pick mode without Ctrl: a pick.
2. **Ctrl without Shift**: the velocity gesture. If velocity mode is off, the view asks for it to
   be switched on (§7).
3. **Ctrl+Shift**: neither a pick nor a velocity dot. It falls through to the cutoff grab and the
   selection, as #88 proposed ("Ctl+shift leaves both unpressed").
4. **Velocity mode**: the velocity gesture.
5. The cutoff grab and the selection, as today.

## 6. The panel (profile dock)

When a box arrives, the panel first checks for a refusal. It refuses:
- on a preview, with the existing message;
- on a cut, with the existing message;
- when the working stack has an enabled `migrate_fk` step;
- when it has an enabled `amp_abs`, `amp_square` or `amp_envelope` step;
- while a difference view is drawn.

Each refusal names the step by its title and says why (decision 3). It shows in the velocity
strip's note, where the fit's own notes appear *(my call)*.

**After a successful trace:**
- the traced dots **replace** the working dots;
- the after-Save state clears, as it does after a new click;
- the panel refits through the same path as a click.

Times convert to the radar clock with `retime_ns`, exactly as a clicked dot's do.

**A refusal or a failed trace leaves the working dots as they were** *(my call: a box never
destroys dots without giving new ones)*. The reason shows in the note.

## 7. The Ctrl/Cmd shortcut (plugin)

When the view asks for velocity mode, the plugin checks `act_velocity`. Its existing toggle turns
Pick off and shows the strip. The dot or box is then handled as usual.

A Ctrl+click does only what the Velocity button could do. Where that button is unavailable (on a
cut), the click is refused the same way.

**Tooltips:**
- `VELOCITY_TIP` gains the box: drag a box around a hyperbola to trace it.
- `VELOCITY_TIP` gains the shortcut: Ctrl+click (Cmd+click on a Mac) works with velocity mode
  off.
- Pick's tooltip keeps its Shift sentence.
- The Velocity row of the toolbar table in `docs/guide/getting-started.md` says the same.

The held-key button feedback from #88 (buttons that look pressed while a key is held) is **not**
built *(my call)*. The author accepted "switch on and stay on" for now. Revisit it after the
walkthrough.

## 8. What stays the same

- A saved fit's format, and the project file. There is no schema change.
- Save fit, Apply to line, Apply to grid and Clear.
- The velocity dialogs.
- `fit_hyperbola`.
- Hand clicks: they land where clicked.

## 9. Non-goals and anti-goals

**Not in this piece:**
- snapping hand clicks;
- #140's option 3, the migration check;
- recording how a fit was made;
- tracing on cuts;
- the held-key button feedback;
- finding hyperbolas across a whole line without a box.

**Failures even if it "works":**
- a σ that looks more precise than the data allows;
- a curve that rides a later lobe, so the velocity comes out slow;
- a trace when there is no hyperbola, instead of saying so;
- QGIS freezing on a big box;
- a box silently wiping the author's dots.

## 10. Testing

**Core tests on CI, with synthetic data built to mirror the real lines.**
- Measure dt, trace spacing, dominant wavelet period and noise level once from FILE__003. Write
  them into the test as literals, with a note of where they came from. Plant hyperbolas with that
  wavelet and noise:
  - **Known velocity:** the traced v (after the panel-equivalent fit) is within 2σ of the truth.
  - **Edge consistency:** the edge rule and the `first_break` rule agree within one sample on
    the same wavelet (§4.2).
  - **Two hyperbolas** in one box: the stronger is traced.
  - **A fading leg:** the dropped traces are the faded ones.
  - **Apex and one leg:** traced.
  - **Noise only:** "no hyperbola". A box too small gives its own reason.
  - **Uneven trace spacing:** still traced correctly.
  - **At most about 10 dots**, apex-nearest first.

**Core tests on real data, local only** (the DZTs are gitignored, so CI skips these).
- Process with #125's recipe: `time_zero`, `dewow`, `background_mean`.
- Use #125's candidates: FILE__003 near trace 283 at about 15.6 ns, FILE__006 near trace 544,
  and FILE__008 near trace 370.
- **Repeatability:** three boxes about 20% different in size and position give velocities that
  agree pairwise within their combined σ.
- **Plausibility:** the velocities fall within 0.04–0.15 m/ns.
- **Speed:** the largest box is timed (§4.5).

**Plugin tests (QGIS tier).** Use real `QTest` mouse events, not calls to the handlers.
- A drag in velocity mode emits the box. A wobble shorter than the drag distance places a dot.
- With velocity off, Ctrl+click turns Velocity on, turns Pick off and places a dot.
- Ctrl+drag draws a box.
- Ctrl+Shift+click does neither.
- Shift+click still picks.
- A box replaces the dots, and a failed box leaves them.
- Each refusal in §6 shows its reason.
- Save fit after a trace, then refit, reproduces the velocity shown.

## 11. Walkthrough (the author, on ns_geo or a new profile)

1. Box a hyperbola on a line you know. The curve sits on the outer edge where you see it.
2. Mark the same hyperbola by hand and save it, then box it and save that. The two velocities in
   the line's velocity dialog agree within σ.
3. Box it three slightly different ways. You get the same velocity each time.
4. Try these boxes, each with the result shown:

   | Box | Result |
   |---|---|
   | A fading leg | traced on the visible part |
   | Two hyperbolas | the stronger one, shown by its curve |
   | Half a hyperbola at a line's end | traced |
   | Empty ground | a reason |
   | Migration on | a refusal naming Migration |

5. After a trace, remove a dot, add a dot, Save fit, and reopen the dialog.
6. **How Ctrl+click feels** (the author asked to try it). Also try Ctrl+drag and Ctrl+Shift.
7. **On a Mac, if one is available:** Cmd+click and Cmd+drag. If none is available, the
   walkthrough and the PR record that it was not checked.
8. A big box: how long it takes.
9. Optional, for #125: look at its four candidates and say which are real diffractions.

## 12. Left to the builder

- The module and signal names.
- The scan's score and its coarse-to-fine steps.
- How §4.2 avoids lobes and noise.
- The rule for dropping outliers.
- The exact thinning.
- The dashed box's look.
- How the panel finds the stack's enabled steps.

## 13. Size and order

Three tasks, then the walkthrough:
1. **The tracer in the core**, test-first, against the real lines and the planted hyperbolas.
2. **The box:** the gesture in the view, the panel's wiring and refusals, and the plugin tests.
3. **The Ctrl/Cmd shortcut:** the press order, the plugin's mode switch, the tooltips and the
   guide row.

**Other branches.**
- `plugin.py` is also edited by M16 (A, B) and M19, and `getting-started.md` by M16 and M19.
  Here those edits are a tooltip, the mode switch and one table row.
- No branch touches `profile_view.py`, `profile_dock.py` or the velocity core.
- There is no project-file change, so M19's file-version change is unaffected.

## 14. Follow-ups to file when this merges

- The held-key button feedback (#88's second half), if the author wants it after trying the
  shortcut.
- #140's option 3: migrate the box at a range of velocities as a check on the trace.
