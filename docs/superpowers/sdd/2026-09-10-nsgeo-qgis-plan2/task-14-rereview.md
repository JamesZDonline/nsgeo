# Task 14 re-review: fix round 1 (scoped)

Scope: did the named findings close, and did the fixes break anything? **Not** a re-review of the
original implementation. Reviewed `e8773f7..8f296e6` (1 commit, `8f296e6`).

In scope: C1, I1–I9, m1–m5, m7–m10. Parked, not re-raised: m6.

Every mutation below was run with `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`,
every `__pycache__` under `packages/` removed **between** runs, the mutation applied to the committed
worktree file and restored byte-for-byte (md5 compared) afterwards. Working tree verified clean and
`packages/nsgeo-qgis/tests/qgis` re-run green (**195 passed**) after the whole sweep.

---

## Verdicts at a glance

| finding | verdict |
|---|---|
| C1 | **CLOSED** — and complete, not half-applied this time (evidence below) |
| I1 I2 I3 I4 I5 I6 I7 I8 I9 | **CLOSED** (all nine) |
| m1 m2 m3 m4 m5 m7 m8 m9 m10 | **CLOSED** (m4 as a quantified hazard, per its own framing; m8 with a residue note) |
| m6 | parked, untouched |

New findings: **0 Critical, 0 Important, 6 Minor.** All six are test-side.

**Recommendation: Task 14 can close.**

---

## 1. C1's completeness

The original defect pattern was a guard applied on one path and missed on another. Applying the same
suspicion:

### Every path `paintEvent` can take

`QPainter(self)` (line 226) is the **only** statement outside the `try`. Everything else is inside it:

```
try:
  painter.fillRect ─ self.image_rect() ─ self.transform read
  ├─ t is None  → setPen, drawText, **return**            (finally still runs)
  ├─ image branch → self._image.width()/height(), t.source_rect(), painter.drawImage
  └─ else branch  → setPen, drawText
  painter.setClipRect
  _paint_selection → _selection_bounds → t.x_of_trace
  _paint_picks     → _pick_positions   → t.x_of_trace, t.y_of_time
  _paint_cursor    → t.x_of_trace
  painter.setClipping(False)
  _paint_axes → _time_ticks → nice_ticks, t.y_of_time
              → _depth_ticks → VelocityModel.depth_at, np.interp, nice_ticks
              → _distance_ticks → np.interp, np.argsort, nice_ticks
              → _distance_unit_label, _direction_arrow
except Exception → _log
finally → painter.end()
```

The early `return` in the `t is None` branch is inside the `try`, so `finally` still ends the painter
— that was the one structural way to reproduce the original half-fix, and it is covered.

### Measured, not reasoned

Forced a raise at each site and ran four consecutive `grab()` repaints in one process
(`scratchpad/probe_paint.py`). Exit code and survival:

| forced failure | result |
|---|---|
| none (control) | 4 repaints, exit 0 |
| `_paint_selection` raises `RuntimeError` | 4 repaints, exit 0 |
| `_paint_picks` raises | 4 repaints, exit 0 |
| `_paint_cursor` raises | 4 repaints, exit 0 |
| `image_rect()` raises (before `r` is even bound) | 4 repaints, exit 0 |
| `_paint_axes` raises on the no-image message branch | 4 repaints, exit 0 |
| `_paint_axes` raises **`KeyboardInterrupt`** (escapes `except Exception`) | 4 repaints, exit 0 |
| `_paint_axes` raises **`SystemExit`** | 4 repaints, exit 0 |

The last two matter: they are the cases `except Exception` cannot catch, and they survive purely
because of `finally: painter.end()`. No path leaves the painter active.

`QPainter(self)` sitting outside the `try` is correct, not a residual gap: it must be, so `finally`
can reference a bound name, and it cannot raise in practice — a `begin()` that fails prints a warning
and yields an *inactive* painter, and `end()` on an inactive painter warns harmlessly (this is also
what happens in the nested-repaint case, e.g. if logging ever re-entered paint).

### Is the "either alone is sufficient" reasoning concealing a gap?

**No gap in the shipped code, but the claim is narrower than the report states.** The report says
`except Exception` and `finally: painter.end()` are "each independently" sufficient. That holds only
for `Exception` subclasses. It is false for (a) `BaseException` — `KeyboardInterrupt`/`SystemExit`
skip the `except` entirely, and (b) an exception raised *inside* the `except` handler, e.g. `_log`
itself failing. In both, only `finally` ends the painter, as the table above demonstrates. So the
shipped both-guards code is strictly stronger than the report's framing implies; keeping both was
right, and the report's mutation #4 ("survived" with `finally` retained) is honest evidence for
`finally` alone, not for `except` alone. The complementary direction was measured by the implementer
narratively but never entered the ledger.

### The generic guard is load-bearing and pinned

I removed *only* the `try/except/finally` scaffolding from `paintEvent` (de-indented body,
`painter.end()` restored at the bottom — the exact pre-C1 shape), keeping every new `set_axes` and
`_distance_ticks` guard:

```
C1R try/except/finally removed from paintEvent (set_axes guards kept)
    → rc = -11 (SIGSEGV), suite dies after 14 tests
```

So `test_paint_event_survives_an_unexpected_exception_across_two_repaints` genuinely pins the generic
guard, independently of the three specific input guards.

### C1a / C1b / C1c at source

- **C1a** `set_axes` rejects a `distance_along` whose `ndim != 1` or whose length disagrees with
  `n_traces`, stores `None`, logs, and applies the rest of the axes. Mutation "relax the length check
  to a truthiness check" → **killed** by `test_set_axes_rejects_a_mismatched_distance_along_and_logs_it`.
- **C1b** `_distance_ticks` guards `t.n_traces == 0` before `np.interp`. Killed by the direct
  `_distance_ticks` call the implementer added after finding `grab_image()` alone could not
  distinguish it from the outer catch-all — that was the right correction, honestly reported.
- **C1c** `set_axes` rejects `not dt_ns > 0` (which correctly also rejects NaN). Guard removal →
  **killed**. See new finding N4 for the one weakness in its *test*.

There is no remaining stale-length hazard: `self._distance` is reassigned on every successful
`set_axes`, and nothing else can change `transform.n_traces`.

**C1: CLOSED.**

---

## 2. Survivor reconciliation — the crux

The two ledgers are not comparable, so I re-ran **my own** 24, mapped onto the refactored file
(`_time_ticks`, `_selection_bounds`, `_pick_positions`, `_distance_unit_label`, `_direction_arrow`
are new homes for code that used to be inline in `_paint_axes`/`_paint_selection`/`_paint_picks`).

### Result: 23 of my 24 survivors are now killed; 1 still survives.

| # | my original survivor | now | killed by |
|---|---|---|---|
| 1 | wheel zoom disabled (`if steps:` → `if False:`) | KILLED | `test_wheel_event_zooms_about_the_cursor` |
| 2 | `panned()` call dropped | KILLED | `test_middle_drag_pans_the_view` |
| 3 | image drawn over the margins | KILLED | `test_paints_the_image_inside_the_margins` (+ time-tick render test) |
| 4 | `sy` → 1.0 alone | KILLED | `test_vertical_scaling_reconciles_an_image_shorter_than_n_samples` |
| 5 | `set_selection` min/max normalisation removed | KILLED | `test_set_selection_normalises_reversed_bounds` |
| 6 | selection right edge `b + 1` → `b` | KILLED | `test_selection_bounds_use_the_trace_after_b_for_the_right_edge` |
| 7 | pick marker x pinned | KILLED | `test_set_picks_renders_a_marker_at_the_correct_position` |
| 8 | pick marker y pinned | KILLED | same |
| 9 | `set_picks` dropped | KILLED | same |
| **10** | **hover bounds check removed (`0 <= x < width` → `True`)** | **SURVIVED** | — (see N1) |
| 11 | `resizeEvent` transform update → `pass` | KILLED | `test_resize_after_axes_are_set_updates_the_transform` |
| 12 | depth ticks ignore the velocity model | KILLED | `test_depth_axis_uses_the_velocity_model` |
| 13 | depth tick y pinned | KILLED | same |
| 14 | time tick y pinned | KILLED | `test_time_ticks_are_actually_rendered_in_the_left_margin` (+ value test) |
| 15 | time ticks over the wrong range | KILLED | same |
| 16 | `_distance_ticks` no-distance branch → `return []` | KILLED | `test_distance_ticks_fall_back_to_trace_ticks_without_distance_along` |
| 17 | `_paint_axes` distance-tick loop → `[]` | KILLED | `test_distance_ticks_are_actually_rendered_at_the_bottom` |
| 18 | unit label pinned to `"trace"` | KILLED | `test_distance_unit_label_reflects_whether_distance_is_set` |
| 19 | direction arrow pinned | KILLED | `test_direction_arrow_reflects_set_direction` |
| 20 | `set_direction` no-op | KILLED | same |
| 21 | `zoom_at` anchor ignored | KILLED | `test_wheel_zooms_about_the_cursor_and_emits_view_changed` (m10's new assertion — confirmed by running this mutation alone: that test is among the three that fail) |
| 22 | `set_axes` `view_changed` dropped | KILLED | `test_set_axes_and_fit_emit_view_changed` |
| 23 | `fit` `view_changed` dropped | KILLED | same |
| 24 | `one_to_one` no-op | KILLED | `test_one_to_one_sets_a_trace_per_pixel_column_and_emits_view_changed` |

**Against my original 35: now 34 killed, 1 survived** (was 11/24).

### Why the two ledgers disagreed

The implementer's 27 is not a superset of my 24. Their ledger covers **20** of my 24. The four of mine
absent from it are #9 (`set_picks` dropped), #17 (distance-tick loop), #21 (`zoom_at` anchor — asserted
"confirmed" in the m10 prose but never entered as a ledger row), and #10 (hover bounds). Three of those
four are killed anyway by tests written for neighbouring findings. The fourth is the one real gap, and
it is precisely the one their ledger never tested. "26 of 27 caught" was therefore never evidence that
my 24 had closed; it happens to be 23/24 on the merits, which the re-run establishes.

Their ledger's remaining 7 rows (#1–#5 for C1, #13 depth-y, #27 `clear()`) are mutations I had not
applied; I re-ran the C1 ones independently above.

---

## 3. Are I1/I2/I6/I7/I8/I9's replacements genuinely positive tests?

Yes for all six, with one residual (N2).

- **I1 `test_wheel_event_zooms_about_the_cursor`** — dispatches a real `QWheelEvent` with
  `angleDelta=(0,120)` and asserts `trace=[20.0, 180.0)`, `time=[2.4, 53.6)` as hard literals. I
  re-derived these by hand from `ViewTransform.zoomed`: anchor local `(348, 132)`, `fx = fy = 0.5`,
  `factor = 1.25`, trace span `200/1.25 = 160` → `100 ± 80`; time span `64/1.25 = 51.2`, anchor time
  `28` → `2.4 … 53.6`. Independent of the code under test. Not a "something changed" test.
- **I2 `test_middle_drag_pans_the_view`** — zooms in first (correct: at fit zoom `with_window` clamps
  a pan to nothing), then asserts `trace_lo = 42.81609195402299` etc. Re-derived: `dt = -50/696*100`,
  `ds = -20/264*32` on a `[50,150) × [12,44)` window. Matches exactly. Independent.
- **I6** — `margin == BACKGROUND` exactly. The vacuous `r==g==b` is gone; mutation #3 is killed.
- **I7** — the exact list `["0","1","2","3"]` plus y-positions `[16.5, 99.0, 181.5, 264.0]`. Re-derived:
  `depth = 0.05·t` over `t ∈ [-4, 60]` gives depths `[-0.2, 3.0]`, `nice_ticks` step 1.0; `y_of_time`
  with height 264 over a 64 ns span gives 16.5/99/181.5/264. Both the model-bypass and the y-pinning
  mutations die. The bypassed variant would give `["0","20","40","60"]` — a different list, not a
  different first element, so the distinction is complete, not incidental.
- **I8** — `_time_ticks`/`_distance_unit_label`/`_direction_arrow` now return plain values asserted
  against literals, each paired with a rendering-consumption check. `test_time_ticks_are_actually_
  rendered_in_the_left_margin` has a **negative control** (a probe 20 px below the tick asserted
  light), so it is not a bare change-detector. Mutation "tick mark not drawn, labels kept" → killed.
- **I9** — `_selection_bounds` and `_pick_positions` asserted as values; the pick rendering test has a
  negative control (nothing pick-coloured in the top-left corner, which is where the pinning mutations
  would draw). The one exception is `test_selection_is_actually_rendered` — see **N2**.

### The extraction is genuinely behaviour-preserving

I did not take "same rendered output" on trust. I loaded the pre-fix `profile_view.py` (from `e8773f7`)
and the shipped one side by side in one process and compared every pixel of the rendered widget across
8 configurations (`direction ±1` × `distance on/off` × `velocity on/off`), with a cursor, a selection
band and two picks set:

```
direction=+1 distance=True  velocity=True  -> differing pixels: 0
direction=+1 distance=True  velocity=False -> differing pixels: 0
direction=+1 distance=False velocity=True  -> differing pixels: 0
direction=+1 distance=False velocity=False -> differing pixels: 0
direction=-1 distance=True  velocity=True  -> differing pixels: 0
direction=-1 distance=True  velocity=False -> differing pixels: 0
direction=-1 distance=False velocity=True  -> differing pixels: 0
direction=-1 distance=False velocity=False -> differing pixels: 0
```

---

## 4. The 26 new tests' own strength

Checked for the two traps this branch keeps paying for.

**Expected value computed from the code under test.** Four new tests compare against
`v.transform.x_of_trace(...)` / `y_of_time(...)` rather than a literal
(`test_selection_bounds_...`, `test_pick_positions_...`, `test_set_picks_renders_...`, and the
m3-revised `test_cursor_is_drawn_at_the_trace`). This is acceptable, not the trap: `ViewTransform` is a
different module with its own suite, and in every case the *distinguishing* argument is a literal
(`x_of_trace(41)` vs `x_of_trace(40)`; `x_of_trace(100.5)` vs the untested `100`), so the property under
test is pinned even though the pixel coordinate is not. Every genuinely load-bearing number in the new
tests — the wheel window, the pan window, the depth/time tick lists and y-positions, `4000`, `1819`,
`block=11`, `0.7272…`, `696 → 896`, `trace 178`, `trace 66` — is a hard literal, and I re-derived each
independently above or against `decimate_columns`' own `ceil(n/max_width)` / `ceil(n/block)`.

**Rounding ties.** m2's own probe moved from `348` (`348/696` exactly `0.5`, one ULP from flipping
`trace_index_at` to 99) to `232` (`232/696 = 1/3` → trace 66.67, 2.3 px from either integer boundary) —
genuinely fixed. The two new wheel/pan tests still anchor at `(348, 132)`, i.e. exactly the same 0.5
fractions, but that is harmless here: nothing floors, and the assertions are `pytest.approx` on
continuous values. The one new probe that *is* convention-coupled is
`test_distance_ticks_are_actually_rendered_at_the_bottom` — see **N6**.

**m3's own revision did not weaken the test.** The ±1 window still kills the mutation it was written
for: `_paint_cursor`'s `self._cursor + 0.5` → `self._cursor` is **killed**.

---

## 5. Did the m8 extraction change `survey_dock.py`'s behaviour?

**No.** The diff is exactly: drop the inline `_log`, drop `QgsMessageLog` from the `qgis.core` import
(`Qgis` stays, still used at all five call sites), add `from nsgeo_qgis.log import log as _log`. The
moved function is byte-identical in signature, default (`Qgis.MessageLevel.Warning`), body and `"nsgeo"`
tag. All five guarded slots (`rebuild`, the status-label update, line-open, the second line handler,
the context-menu builder) call `_log(...)` with the same arguments and are otherwise untouched.

I checked the one way an extraction like this can silently change behaviour — a test patching the name
in the *old* module's namespace. `grep` over the whole package: nothing monkeypatches
`survey_dock._log` or `survey_dock.QgsMessageLog`; the only log-capturing fixtures
(`test_plugin_layers.py`, and the new one in `test_plugin_profile_view.py`) connect to the
`QgsApplication.messageLog()` singleton, which is unaffected by where the helper lives. No import cycle
(`nsgeo_qgis/log.py` imports only `qgis.core`), and the boundary test's `FORBIDDEN_ROOTS` does not
include `qgis`.

Residue, not a finding to act on here: `nsgeo_qgis/layers.py:131` still defines the same two-line
`_log` verbatim. The hoist unified two of the three copies; the third is Task 8's file and outside this
task's diff. Worth one line in a future cleanup, not a reopen of m8.

---

## 6. New defects from the I3/I4 interaction-handler changes

The state machine gained two branches. I drove seven combinations through real `QMouseEvent`s with
explicit `button`/`buttons` (`scratchpad/probe_mouse.py`), on a view zoomed to a 100-trace window:

| scenario | result |
|---|---|
| A. middle+left held together, move, left release, middle release | pans; left drag does **not** accumulate (`_selection` stays `(-1,-1)`); left release emits **nothing**; middle release clears `_pan_last` |
| B. left drag in progress, then middle press **and** release mid-drag | no emission on the middle release; `_press` survives; the later left release commits `(28, 86)` correctly |
| C. middle-press, left-press, move with only LEFT held (the I3 sequence) | **no pan**; `_pan_last` cleared by the move itself; falls through to drag-select `(64, 93)`, committed on the left release |
| D. left drag started in the left / right / bottom margin | selection clamps to `(0, 86)` / `(86, 199)` / normal — pre-existing clamping, unchanged by this round |
| E. middle drag started in the top-left margin corner | pans normally — pre-existing, unchanged |
| F. hover at widget x = 5, 30, 55, 56, 751, 752, 795 | emits only for local x ∈ [0, 696) — the bounds guard is correct (but untested: N1) |
| G. shift-click in the margins | `pick_requested` fires with out-of-range times — **pre-existing**, `mousePressEvent` untouched this round; noted only because my original review mis-stated `time_of_y` as clamping |

No combination produces a spurious `range_selected`, a lost drag, or a stuck pan. Directed mutations
confirm both new branches are pinned: inverting the `buttons() & MiddleButton` check → **killed**;
widening `mouseReleaseEvent`'s Left check to also accept Right → **killed**.

**No new Critical or Important defect from I3/I4.** One minor test-side consequence: N5.

---

## New findings

All six are test-side. None blocks the task.

### N1 (Minor). The hover bounds guard is still untested — the last of my original 24 survivors

```
if 0 <= x < self.transform.width:          →  if True:
    self.trace_hovered.emit(...)
```
**44 passed.** Concrete input: on the `view` fixture, a mouse move to widget `x = 5` (local `x = -51`,
in the left axis gutter) emits nothing today; with the guard removed it emits `trace_hovered(0)`, and
`x = 795` (right gutter) emits `trace_hovered(199)`. Task 15 wires `trace_hovered` to the map cursor,
so the marker would jump to trace 0 / the last trace whenever the pointer crossed a gutter. Fix: one
assertion that a move into the margin emits nothing.

### N2 (Minor). `test_selection_is_actually_rendered` is a bare "something changed" probe

This is the exact trap the dispatch named, and it is the only one of the six replacements that has it.
The test asserts `cleared.pixel(x0, y) != selected.pixel(x0, y)` with no negative control:

```
p.fillRect(QRectF(x0, r.top(), x1 - x0, r.height()), SELECTION_COLOUR)
  → p.fillRect(QRectF(r), SELECTION_COLOUR)        # band painted over the ENTIRE image area
```
**44 passed.** The wrong change passes because it also changes the probed pixel. (Shifting the band by
40 px *is* killed, so the failure mode is narrow — the band's position is pinned, its extent is not.)
Fix: one more probe at a pixel outside the band (e.g. trace 100) asserted unchanged. Note the sibling
tests written in the same round (`test_time_ticks_are_actually_rendered_in_the_left_margin`,
`test_set_picks_renders_a_marker_at_the_correct_position`) both *do* carry negative controls — this one
is the outlier.

### N3 (Minor). A paint failure can go entirely unlogged and nothing notices

```
_log(f"could not paint the profile view: {exc}")   →   pass
```
**44 passed.** `test_paint_event_survives_an_unexpected_exception_across_two_repaints` asserts only
that the process lives. In QGIS a silent swallow means a blank or half-drawn profile with nothing in
the message log — the failure mode the guard is supposed to convert *into* a log line. The
`message_log` fixture this round introduced is right there in the same file.

### N4 (Minor). The `dt_ns` guard's test pins only `dt_ns == 0.0`

```
if not dt_ns > 0:   →   if dt_ns == 0:
```
**44 passed.** The shipped guard is correct (`not dt_ns > 0` rejects negatives *and* NaN, which is why
it is written that way rather than `dt_ns <= 0`), but the test passes only `0.0`, so the property the
odd-looking expression exists for is unverified. Fix: parametrise with `-0.5` and `float("nan")`.

### N5 (Minor). `test_stuck_pan_is_not_armed_by_a_later_non_middle_release` rejects a safer implementation

Its mid-test `assert v._pan_last is not None` (after the left release) pins the *absence* of defensive
clearing. I applied both defensive variants the original I3 suggested — clear `_pan_last` on a left
release, and clear it on any release — and this test **fails on both**, despite each being strictly
safer than what ships. The test should assert the outcome (no pan, `_pan_last is None` afterwards) and
drop the mid-sequence assertion about how the state got there.

### N6 (Minor). `test_distance_ticks_are_actually_rendered_at_the_bottom` hard-codes Qt's truncation convention

`tick_x = int(r.left() + x)` where `x = 208.8`, i.e. pixel column 264 rather than `round(264.8) = 265`,
with a single-pixel probe and no negative control. This is the inverse of the m3 fix applied three
tests earlier in the same round: a rasteriser or device-pixel-ratio change flips it for no behavioural
reason. A ±1 window would be just as sensitive (ticks are 208.8 px apart here). Adding a negative
control between ticks would also strengthen it, matching its time-axis sibling.

---

## Verification performed

- Baseline `test_plugin_profile_view.py`: **44 passed**; full `tests/qgis` after the whole sweep:
  **195 passed**; `git status --porcelain` empty; `profile_view.py` md5 identical to HEAD after every
  mutation.
- **My original 24 survivors re-run** against the fixed tree: 23 killed, 1 survived (N1).
- **11 extra mutations** probing the new code and the new tests' strength: `_paint_selection` full-rect
  fill (survived → N2), band shifted 40 px (killed), distance tick x pinned (killed), time tick mark
  not drawn (killed), `except`-branch log dropped (survived → N3), `set_axes` length check relaxed
  (killed), `dt_ns` guard narrowed to `== 0` (survived → N4), pan `buttons()` check inverted (killed),
  release widened to Right (killed), `_distance_ticks` guard widened to `<= 1` (survived; behaviourally
  inert — `nice_ticks` returns `[]` for a 1-trace axis either way, so not reported as a finding).
- **2 defensive mutations** (clear `_pan_last` on left / on any release): both killed → N5.
- **C1 regression:** `try/except/finally` removed from `paintEvent` only, every other new guard kept →
  **rc −11 (SIGSEGV)** after 14 tests.
- **C1 completeness:** 8 forced-failure variants × 4 consecutive repaints per process, including
  `KeyboardInterrupt` and `SystemExit` (which `except Exception` cannot catch) — all exit 0.
- **Refactor equivalence:** pre-fix vs shipped module, pixel-by-pixel, 8 configurations — 0 differing
  pixels each.
- **I3/I4 combinations:** 7 scenarios driven with explicit `button`/`buttons` `QMouseEvent`s.
- **m8:** `survey_dock.py` diff read in full; `grep` confirms no test patches `_log`/`QgsMessageLog` in
  that module's namespace; `Qgis` still imported and used; no import cycle.
- **m4/m7 literals** re-derived against `decimate_columns`' own `block = ceil(n/max_width)`,
  `n_blocks = ceil(n/block)`: `(20_000, 4096) → 4000`; `(20_001, 2000) → block 11, width 1819`,
  error `8/11 = 0.72727…` px.

## Recommendation

**Close Task 14.** C1 is complete rather than half-applied — I enumerated `paintEvent`'s callees,
forced a raise at every one including two exception classes the `except` cannot catch, and the guard
holds on all of them; removing only the scaffolding still segfaults. All nine Importants and all nine
in-scope Minors are closed, 23 of my 24 surviving mutants are dead, and the I8/I9 extraction is
pixel-identical to what it replaced. The one survivor (N1) and the five other new Minors are all
test-side, each a few lines, and none of them changes shipped behaviour. Fold N1–N3 into the next
round if one happens; do not hold the task for them.
