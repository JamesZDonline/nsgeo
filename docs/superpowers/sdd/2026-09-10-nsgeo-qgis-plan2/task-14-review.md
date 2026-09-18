# Task 14 review: `RadargramImage`, `ProfileView`, and the QImage wrapper

Reviewed: `a650ecb..e8773f7` (2 commits: `31b5f73` implementation, `e8773f7` fixture teardown fix).

## Verdicts

- **Spec compliance: PASS.** Every file, symbol, margin, colour, signal and method named in the
  brief's Interfaces line is present and matches; Qt discipline is clean; the boundary test holds.
  All four deviations from the brief's reference code are correct and I would keep the
  implementation's side in every case.
- **Task quality: CHANGES REQUESTED.** One Critical (a reproducible hard segfault from three states
  reachable through the public `set_axes` signature — the same unterminated-`QPainter` mechanism the
  implementer themselves identified for defect (a), still open on three other paths), and 9
  Important, almost all coverage: of 35 mutations I applied, **11 were killed and 24 survived**,
  including "wheel zoom does nothing", "middle-drag pan does nothing", "resize no longer updates the
  transform", and the entire `_paint_axes` body neutered.

All work below was run with `PYTHONDONTWRITEBYTECODE=1` and with every `__pycache__` under
`packages/` removed between mutations. Working tree verified clean (`git status --porcelain` empty)
and `packages/nsgeo-qgis/tests/qgis` re-run green (**169 passed**) after the sweep.

---

## The two dispatched brief defects

### (a) `paintEvent`'s division before `source_rect()` — FIXED, but only half the surface

The brief computed `self._image.width() / t.n_traces` unconditionally. The implementation moved the
division inside `if self._image is not None and t.n_traces > 0 and t.n_samples > 0:` and falls
through to the existing message branch. That is the right shape: it leaves Task 13's "an empty axis
is legal" contract untouched and does not invent a new visual state.

Confirmed load-bearing: reverting the guard to `if self._image is not None:` **core-dumps the test
process** (`timeout: the monitored command dumped core`), not merely fails a test. The implementer's
escalation of the brief's framing ("not just a swallowed `ZeroDivisionError` — a hard crash") is
accurate and I reproduced it.

**But the fix guards the image branch only.** `_paint_axes` runs unconditionally afterwards, outside
any guard, and `painter.end()` is not in a `finally`. See Critical C1 — the empty-trace-axis state
the fix was written to make safe still crashes the process when `distance_along` is supplied.

Verdict: keep the implementation's side. The brief is wrong. Extend the fix.

### (b) `wheelEvent` / `mouseMoveEvent` guards — FIXED, and the breadth is right

Both handlers now wrap their bodies in `except Exception` and log through the same
`_log`/`QgsMessageLog` helper `survey_dock` uses (byte-identical definition). I verified the
implementer's justification for `except Exception` rather than `except ValueError` rather than
taking it on trust:

```
1.25 ** (-100_000_000 / 120.0)  ->  0.0            (underflow; then ZeroDivisionError in zoomed())
1.25 ** (+100_000_000 / 120.0)  ->  OverflowError: (34, 'Numerical result out of range')
```

Three distinct exception types are reachable from one bad `angleDelta`, and only one of them is the
`ValueError` the brief's framing implies. `except Exception` is correct, not lazy.

`resizeEvent`/`mousePressEvent`/`mouseReleaseEvent` were deliberately left unguarded, and the stated
reasoning checks out: `resized()` only `replace()`s width/height (already-finite fields), and
press/release only call the clamping `trace_index_at`/`time_of_y`.

**The omission is `paintEvent`.** It is the one Qt-invoked override where an escaping exception is
invisible *and* continuous *and* leaves a live `QPainter` bound to the widget — the exact mechanism
the implementer proved can abort the process. Guarding `wheelEvent` while leaving `paintEvent`
unguarded is the wrong side of that trade. See C1.

Verdict: keep the implementation's side. The brief is wrong. Extend the guard to `paintEvent`.

---

## The segfault fix (`make_view`) — correct and complete, documented for the wrong reason

Measured, 5 runs of `test_cursor_is_drawn_at_the_trace` individually per variant:

| fixture teardown | exit codes |
|---|---|
| none (the original bug) | `139 139 139 139 139` |
| `hide()` only | `0 0 0 0 0` |
| `deleteLater()` only | `0 0 0 0 0` |
| `hide()` + `deleteLater()` (as shipped) | `0 0 0 0 0` |
| `hide()` + `deleteLater()` + `sendPostedEvents(None, DeferredDelete)` | `0 0 0 0 0` |

**Is `deleteLater()` without flushing `DeferredDelete` sufficient here? Yes — but not because the
widget gets deleted.** Measured directly with `sip`:

```
after deleteLater,                       isdeleted = False
after QApplication.processEvents(),      isdeleted = False
after sendPostedEvents(None, DeferredDelete), isdeleted = True
```

which reconfirms this codebase's standing fact. What actually removes the hazard is a side effect
PyQt applies at the same moment: `deleteLater()` **transfers sip ownership to C++**
(`sip.ispyowned(v)`: `True` before, `False` after), so Python's GC no longer destroys a C++-owned
top-level widget at interpreter shutdown. `hide()` removes the same hazard independently, by never
leaving a *shown* top-level window for GC. The shipped fix applies both; the explicit flush is
genuinely unnecessary, so the implementer's judgement call was right.

Their *explanation* is not. The `make_view` docstring says `deleteLater()` is there "so the QObject
is deleted through Qt's own object-deletion path rather than Python's `__del__`". No `ProfileView` in
this file is ever deleted — all 13 leak for the life of the process. Harmless in a test process, but
the next author who copies this fixture into code that needs actual destruction will be misled. See
Minor m1.

**Does any widget or QObject still escape ownership?** In the tests, no: `ProfileView(` appears
exactly once in the file, inside `_make`. `QMouseEvent`/`QWheelEvent`/`QImage` are value types, not
QObjects, and `QApplication.sendEvent` takes no ownership. In the new source, one object does escape
— the `QPainter` in `paintEvent`, on every path that raises. That is C1.

---

## Critical

### C1. `paintEvent` still has three unguarded raise paths and no `finally: painter.end()`; the second repaint is a hard segfault

`painter.end()` sits at the bottom of `paintEvent` with no `try/finally`. Any exception below
`QPainter(self)` leaves a live painter bound to the widget. Repaint 0 prints
`QPaintDevice: Cannot destroy paint device that is being painted`; **repaint 1 segfaults the
process.** Measured for two separate inputs, both times crashing on iteration 1 of a `grab_image()`
loop. In QGIS that is the whole application, not one widget.

Three concrete inputs, all reachable through the public `set_axes` signature, none caught by any of
the 18 tests:

**C1a — `distance_along` length ≠ `n_traces`.**
```python
v.set_axes(200, 128, -4.0, 0.5, distance_along=np.arange(100) / 60.0)
v.set_image(RadargramImage(rg).image)
v.grab_image()   # repaint 0: warning.  v.grab_image() again: SIGSEGV
```
```
File ".../ui/profile_view.py", line 281, in _paint_axes
    for label, x in self._distance_ticks(t):
File ".../ui/profile_view.py", line 316, in _distance_ticks
    d_lo, d_hi = np.interp([lo, min(hi, t.n_traces - 1)], idx, d)
ValueError: fp and xp are not of the same length.
```
`set_axes` accepts the array with no length check. Task 15's brief already knows this is a hazard —
its `_render` writes `distance = line.distance_along() if rg.n_traces == line.n_traces else None` —
which means the invariant is currently enforced only by every caller remembering to. `set_axes`
should enforce it, or `_distance_ticks` should degrade to trace ticks.

**C1b — the empty-trace-axis state defect (a) was fixed to make safe.**
```python
v.set_axes(0, 50, 0.0, 0.5, distance_along=np.array([]))
v.grab_image()
```
```
ValueError: array of sample points is empty
```
Same site. `n_traces == 0` is the exact state Task 13 deliberately permits and the brief dispatched
as defect (a); the fix makes the *image* branch safe and then walks straight into `_paint_axes`.
This one is the most pointed: the task's own named defect is only half closed.

**C1c — `dt_ns == 0`.**
```python
v.set_axes(200, 128, 0.0, 0.0)
v.set_image(img)
v.grab_image()
```
```
File ".../ui/view_transform.py", line 111, in source_rect
    y0 = (self.time_lo - self.t0_ns) / self.dt_ns
ZeroDivisionError: float division by zero
```
This one is *not* reachable from real data — `parse_header` rejects `range_ns <= 0` and
`Radargram.__post_init__` rejects `dt_ns <= 0` — so it is a contract gap rather than a live bug. But
`ViewTransform.__post_init__` checks finiteness only, so `dt_ns = 0.0` constructs fine and only
explodes inside the paint event, and Task 15's first `set_axes` call site passes
`line.header.dt_ns` straight through. Note the empty-axis guard (`n_traces > 0 and n_samples > 0`)
does **not** cover it: `source_rect()` divides by `dt_ns`, not by a count.

**Fix:** wrap the whole `paintEvent` body in `try/except Exception` + `finally: painter.end()`,
logging through the existing `_log` (the same pattern already applied to `wheelEvent`), and
additionally validate in `set_axes` (`dt_ns > 0`; `distance_along` length `== n_traces`, else
ignore it and log). The `finally` is the part that turns a crash into a blank widget.

---

## Important

### I1. `wheelEvent` has no positive test — zoom-on-wheel is entirely unverified

Mutation `if steps:` → `if False:` in `wheelEvent`: **18 passed.** The user scrolls the wheel over
the profile, nothing zooms, and the suite is green.

This is the first of the two traps the dispatch names (see also I6, I7, m2). `test_wheel_zooms_about_the_cursor_and_emits_view_changed`
does not touch `wheelEvent` at all — it calls `v.zoom_at(2.0, ...)` directly. The only test that
dispatches a real `QWheelEvent` is
`test_wheel_event_survives_a_degenerate_zoom_factor_instead_of_leaking_to_qt`, and its assertions are
`not excepthook_calls` and `v.transform == before` — **both of which are exactly what a do-nothing
`wheelEvent` produces.** The test cannot distinguish "the guard caught a degenerate factor" from
"the feature was never implemented". It does kill the removal of the `try/except` (the report's
mutation 7), so it tests the guard; nothing tests the thing being guarded.

Fix: add a positive wheel test — dispatch a `QWheelEvent` with `angleDelta = QPoint(0, 120)` at a
known anchor and assert the resulting `trace_lo`/`trace_hi` against hard-coded numbers.

### I2. Middle-button pan has no positive test

Mutation: delete `self.transform = self.transform.panned(d.x(), d.y())` from `_handle_mouse_move`:
**18 passed.** Same tautology as I1 —
`test_mouse_move_survives_a_broken_pan_transform_instead_of_leaking_to_qt` monkeypatches `panned` to
raise and then asserts `v.transform == before`, which also holds if `panned` is never called. No test
anywhere asserts that a middle-drag actually moves the window.

### I3. `_pan_last` is never cleared except by a middle-button release — a real stuck pan

`mousePressEvent` sets `_pan_last` on a middle press and returns; `mouseReleaseEvent` clears it only
when `event.button() == MiddleButton`. Any other release path leaves panning armed, and
`_handle_mouse_move` checks `_pan_last is not None` *before* it checks whether a button is held.

Measured, on a view zoomed to `trace=[75.0, 125.0)`:
```
middle-press at (156, 58); left-press at (156, 58); left-release at (156, 58)
_pan_last after the left release: QPointF(156.0, 58.0)
then one mouse move to (356, 58) with NO button held:
  before: (75.0, 125.0)
  after : (60.63, 110.63)     <- the view panned 14.4 traces on a button-less move
```
The profile then scrolls under the pointer on every subsequent mouse movement until the user presses
and releases the middle button again. Fix: clear `_pan_last` on any release (and on `leaveEvent` /
`focusOutEvent`), or check `event.buttons() & MiddleButton` in the move handler.

### I4. A right-button release ends and commits a left-button drag-selection

Same root cause — `mouseReleaseEvent` keys off `event.button()` with no symmetry to the press.
Measured: left-press at x=100, drag to x=300, then press *and release the right button*:
```
range_selected emitted by a RIGHT-button release: [(28, 86)]
_press after right release: None
```
The selection is committed to whatever Task 15 connects to `range_selected` by a button the user
never used to start it.

### I5. `resizeEvent`'s transform update is untested

Mutation: replace `self.transform = self.transform.resized(r.width(), r.height())` with `pass`:
**18 passed.** The fixture's only `resize()` happens *before* `set_axes`, so the
`if self.transform is not None` branch never runs in the whole suite.

This is the silent-wrong-trace failure the dispatch warns about, not a cosmetic one. Dock the view
and widen the QGIS window by 200 px: `image_rect().width()` becomes 896 while `transform.width`
stays 696, so `trace_of_x` scales every pointer x by the wrong factor. A hover at x=800 reports
`trace_of_x(800) = 800/696*200 = 229.9` → clamped to trace 199 instead of the correct
`800/896*200 = 178`. That wrong index is what `trace_hovered`, `pick_requested` and
`range_selected` carry downstream.

### I6. `test_paints_the_image_inside_the_margins` does not test that the image stays inside the margins

Mutation: `painter.drawImage(QRectF(r), ...)` → `painter.drawImage(QRectF(self.rect()), ...)` —
i.e. paint the radargram straight over both axis gutters and the time labels: **18 passed.**

The test's two probes are `np.std(inside) > 5` (measured 14.2 — comfortable, and it does catch "no
image drawn") and `margin.red() == margin.green() == margin.blue()`, commented "axis gutter is
neutral". The second is vacuous: `DEFAULT_COLORMAP` is `grey_black_high`, so **every** radargram
pixel already satisfies `r == g == b`. Fix: assert the margin pixel equals `BACKGROUND` exactly
(measured `(250, 250, 250, 255)`), or render the probe image with `seismic`.

### I7. `test_depth_axis_uses_the_velocity_model` passes with the velocity model bypassed entirely

Mutation: `depths = self._velocity.depth_at(times)` → `depths = np.asarray(times, dtype=float)`:
**18 passed.** The right-hand axis would then be labelled in nanoseconds while claiming metres.

This is the dispatch's tautology trap in its second form. With `t0_ns = -4.0`, `n_samples = 128`,
`dt_ns = 0.5` and `VelocityModel.constant(0.1)`, the real depths run `[-0.2, 3.0]` →
`nice_ticks` step 1.0 → `labels[0] == "0"`. With the model bypassed the times run `[-4, 60]` →
step 10.0 → `labels[0] == "0"` as well. The surviving assertion after the implementer's (correct)
precedence fix is effectively `labels[0] == "0"`, which both branches satisfy; the `startswith("-")`
branch never fires. The test proves only that setting a velocity produces *some* labels.

The tick *positions* are untested too: `out.append((f"{d:g}", t.y_of_time(time_ns)))` →
`out.append((f"{d:g}", 0.0))` also survives.

### I8. The whole of `_paint_axes` is untested beyond "does not raise"

Every one of these survives all 18 tests:

| mutation | what ships |
|---|---|
| `y = r.top() + t.y_of_time(float(tick))` → `y = r.top()` | every time tick and label stacked on the top edge |
| `nice_ticks(t.time_lo, t.time_hi)` → `nice_ticks(0.0, 1.0)` | time axis labelled 0…1 regardless of the record |
| `_distance_ticks`'s no-distance branch → `return []` | no trace ticks at all |
| `for label, x in self._distance_ticks(t)` → `for label, x in []` | no bottom-axis ticks at all |
| `unit = "m" if self._distance is not None else "trace"` → `"trace"` | metres axis labelled "trace along line" |
| `arrow = "→" if self._direction == 1 else "←"` → `"→"` | reversed lines drawn with a forward arrow |
| `self._direction = direction` → `= 1` | `set_direction()` is a no-op |

The last two matter for Task 15, which wires `set_direction(int(line.placement.direction))`: a
reversed line would render with the wrong arrow and nothing would notice.

### I9. Selection and pick painting are never rendered by any test

`set_picks()` is **never called anywhere in the suite**, so `_paint_picks` never runs with a
non-empty list. Both of these survive: `x = r.left() + t.x_of_trace(trace + 0.5)` → `x = r.left()`,
and `y = r.top() + t.y_of_time(time_ns)` → `y = r.top()` — i.e. every pick marker drawn in the
top-left corner of the image area.

For the selection band, `x1 = r.left() + t.x_of_trace(b + 1)` → `x_of_trace(b)` survives (the band's
right edge one trace short), and so does removing `set_selection`'s `min/max` normalisation:
`self._selection = (min(a, b), max(a, b))` → `(a, b)`. That last one is a live behaviour gap, not
just a coverage one — **a right-to-left drag is untested end to end.** With the normalisation gone,
dragging from trace 86 back to trace 28 stores `(86, 28)`, `_paint_selection` calls
`fillRect` with a negative width (draws nothing), and `range_selected.emit(86, 28)` hands Task 15 a
reversed range. `test_drag_selects_a_trace_range` only ever drags left-to-right.

*(For balance: `range_selected.emit(a, b)` → `emit(b, a)` **is** killed, by that same test.)*

---

## Minor

- **m1. The `make_view` docstring's stated mechanism is wrong.** See the segfault section above:
  `deleteLater()` never deletes these widgets (`sip.isdeleted` stays `False` through
  `processEvents()`); what fixes the crash is the sip ownership transfer it performs
  (`ispyowned` `True` → `False`), and `hide()` fixes it independently. The fix is right; the comment
  will mislead whoever copies it. Also worth recording in the docstring that the flush was measured
  as unnecessary *because* of the ownership transfer, not because the object is gone.

- **m2. `test_mouse_move_emits_the_trace_under_the_cursor` probes exactly on a rounding tie.** This
  is the dispatch's second named trap. `r.width() = 800 - 56 - 48 = 696`; the probe is
  `r.width() // 2 = 348`; measured `trace_of_x(348) == 100.0` **exactly**, and
  `trace_index_at(nextafter(348, 0)) == 99`. It is deterministic only because `348/696` is exactly
  `0.5` in IEEE 754 — it is one ULP from flipping. The hard-coded `== 100` is also coupled to the
  fixture's 800-px width: change it to `v.resize(801, 300)` and `trace_index_at(348)` becomes 99, so
  the test fails for no behavioural reason. Probe at `r.width() // 3` (232 → trace 66.66…) instead.

- **m3. `test_cursor_is_drawn_at_the_trace` probes a single pixel column with zero tolerance.**
  Measured: the cursor renders as exactly one orange column at x=405 (`(255,159,26)`), with 404 and
  406 both background. Mutation sensitivity is excellent (the `+ 0.5` removal is killed), but a pen
  width or device-pixel-ratio change would break it for no reason. A ±1 px window would be as
  sensitive and less brittle.

- **m4. The decimation test steps around the ragged-tail case, which is misaligned.** The test picks
  `20_000 / 2_000 = 10` traces per column and comments "no ragged tail". With `n = 20_001,
  max_width = 2000`, `decimate_columns` uses `block = 11`, `n_blocks = 1819`, so image column *j*
  covers traces `[11j, 11j+11)` and the correct factor is `1/block = 0.0909091`; `paintEvent` uses
  `image.width() / n_traces = 1819/20001 = 0.0909455`. The error reaches 0.73 px at the tail.
  Irrelevant at fit zoom; at a 4-trace zoom near the tail (source width 0.36 px) it shifts the
  visible content by two whole image columns, ~22 traces. Only reachable on lines wider than
  `max_width = 8192`; real lines are 606–666, so this is correctly filed as a hazard, not a bug.

- **m5. The scaling is verified in one direction only, contrary to the test's docstring.** Mutating
  `sy = self._image.height() / t.n_samples` → `sy = 1.0` alone survives all 18 tests (mutating
  *both* `sx` and `sy` is killed). That is structurally expected — `decimate_columns` only bins
  columns, so `image.height() == n_samples` whenever image and axes come from the same radargram,
  making `sy` identically 1.0 on every reachable path. If `sy` exists to cover "image from radargram
  A, axes from radargram B", nothing tests that combination either.

- **m6. `image_rect()` is a `QRect`, so the right and bottom axis lines land one pixel inside the
  image.** `r.right() == left + width - 1 == 751` and `r.bottom() == 271`, while
  `drawImage(QRectF(r), ...)` paints `[56, 752) × [8, 272)`. Cosmetic, except that
  `setClipRect(r)` also ends at 751, so a cursor at the very last trace edge
  (`r.left() + x_of_trace(n_traces) == 752`) is clipped away entirely.

- **m7. `test_radargram_image_decimates_very_wide_lines` asserts only `width() <= 4096`** — an
  implementation returning a 1-px-wide image passes. The companion test already uses an exact
  `== 2000`; this one could too. (It does kill the "skip `decimate_columns`" mutation, so it is not
  useless.)

- **m8. `_log` is duplicated verbatim from `survey_dock.py`** (same signature, same body, same
  `"nsgeo"` tag). Two copies now; a third will make it worth hoisting.

- **m9. `set_axes`/`fit` emitting `view_changed` is untested** (both removals survive); only
  `zoom_at`'s emission is covered, via `test_wheel_zooms_about_the_cursor_and_emits_view_changed`.
  `one_to_one()` and `clear()` are never called by any test at all.

- **m10. `test_wheel_zooms_about_the_cursor_and_emits_view_changed` does not test "about the
  cursor".** `self.transform.zoomed(factor, x, y)` → `zoomed(factor, 0.0, 0.0)` survives: the test
  checks only that the span halves, never that the anchor point stays put.

---

## Where the brief itself is wrong, and which side I would keep

The brief has six defects in this task. The implementer found and fixed all six; I reproduced each
one independently and would keep the implementation's side in every case.

1. **`paintEvent` divides before `source_rect()`** (dispatched defect a) — real; reverting the fix
   core-dumps. Keep the implementation.
2. **`wheelEvent`/`mouseMoveEvent` unguarded** (dispatched defect b) — real; `except Exception` is
   the correct breadth, verified via `OverflowError` and the `1.25 ** -833333 == 0.0` underflow.
   Keep the implementation.
3. **`assert ri3.image.pixel(0,0) != img.pixel(0,0) or ri3.colormap_name != DEFAULT_COLORMAP`** —
   the right disjunct is a constant `True`; the assertion could never fail. The implementer's split
   is correct and safe: `_grey()` builds `grey_black_high[i] = 255 - i` and `grey_white_high[i] = i`
   over an integer `linspace` of 256 entries, so the tables differ at every index. Keep the
   implementation.
4. **`assert labels and labels[0].startswith("-") or labels[0] == "0"`** — precedence makes an empty
   `labels` raise `IndexError` instead of failing cleanly. Keep the implementation's split (though
   see I7: the corrected assertion is still too weak).
5. **`test_rgb_to_qimage_owns_its_memory_and_matches_pixels`'s `del rgb` probe does not catch a
   missing `.copy()`.** Confirmed: dropping `.copy()` and running the brief's version passes; the
   implementer's in-place `rgb[:] = 99` overwrite kills it (I re-ran the mutation: **1 failed**).
   Keep the implementation.
6. **`QTest.mouseMove` between a `mousePress` and its `mouseRelease` is not delivered under offscreen
   QPA**, making the brief's drag-select middle step a silent no-op. The `_send_move_while_pressed`
   substitution is the right call, and it is load-bearing: `range_selected.emit(a, b)` → `emit(b, a)`
   is killed by that test, which it could not be if the move never arrived. Keep the implementation.

---

## Mutation ledger

35 valid mutations, all with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` cleared between runs.
**11 killed, 24 survived.**

**Killed (11):** `_paint_cursor` `+ 0.5` dropped · `_local` top-margin dropped · `sx` *and* `sy` → 1.0
· source rect x/y swapped · `image_rect` top `+1` · empty-axis guard removed (core dump) ·
`rgb_to_qimage` `.copy()` dropped · `decimate_columns` skipped · `with_radargram` percentile dropped ·
`_pick_mode` default flipped · `range_selected.emit(a, b)` → `emit(b, a)`.

**Survived (24):** wheel zoom disabled · pan disabled · image drawn over the margins · `sy` → 1.0
alone · `set_selection` normalisation removed · selection right edge `b + 1` → `b` · pick marker x
pinned · pick marker y pinned · `set_picks` dropped · hover bounds check removed · `resizeEvent`
no-op · depth ticks ignore the velocity model · depth tick y pinned · time tick y pinned · time ticks
over the wrong range · trace ticks removed · distance ticks removed · unit label pinned to "trace" ·
direction arrow pinned · `set_direction` no-op · `zoom_at` anchor ignored · `set_axes`
`view_changed` removed · `fit` `view_changed` removed · `one_to_one` no-op.

## Verification performed

- Baseline `test_plugin_profile_view.py`: 18 passed.
- Full `packages/nsgeo-qgis/tests/qgis` after the sweep: **169 passed**, `git status --porcelain`
  empty.
- Qt discipline: no `PyQt5`/`PyQt6`/`PySide` import in any of the three new source/test files (only
  the two prose mentions in comments); no short-form enum anywhere in the new code (one prose mention
  of `QImage.Format_RGB888` in a docstring). `tests/pure/test_plugin_boundary.py` permits the
  `qgis.core` import added for `Qgis`/`QgsMessageLog`.
- Probe-tightness measurements: margin-test `np.std(inside) = 14.2` (threshold 5); cursor column
  isolated to exactly x=405; `trace_of_x(348) == 100.0` exactly, 99 at one ULP below.
- Ownership: `sip.ispyowned` / `sip.isdeleted` before and after `hide()`, `deleteLater()`,
  `processEvents()` and `sendPostedEvents(None, DeferredDelete)`; five-run exit-code sweeps across
  five fixture-teardown variants.
