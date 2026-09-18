# Task 14: `RadargramImage`, `ProfileView`, and the QImage wrapper -- report

## What was implemented

- `packages/nsgeo-qgis/nsgeo_qgis/render/__init__.py` (new): docstring only, per the brief.
- `packages/nsgeo-qgis/nsgeo_qgis/render/qimage.py` (new): `rgb_to_qimage(rgb) -> QImage` and
  `RadargramImage(rg, percentile=99.0, colormap_name=DEFAULT_COLORMAP, max_width=8192)` with `.rg`,
  `.percentile`, `.colormap_name`, `.limit`, `.max_width`, lazy cached `.image`, `.with_display(...)`,
  `.with_radargram(rg)`. Implemented as the brief's Step 3 gives it -- no defect found in this file's
  logic itself (see "Reference-code check" below for what was independently verified and what was
  found to actually need strengthening, which turned out to be the *test*, not the implementation).
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (new): `ProfileView(QWidget)` with the full
  interface from the brief -- margins `MARGIN_LEFT=56, MARGIN_RIGHT=48, MARGIN_TOP=8,
  MARGIN_BOTTOM=28`, colours `CURSOR_COLOUR`/`SELECTION_COLOUR`/`PICK_COLOUR`, signals
  `trace_hovered`/`range_selected`/`pick_requested`/`view_changed`, `set_axes`/`set_image`/
  `set_velocity`/`set_cursor`/`set_selection`/`clear_selection`/`set_picks`/`set_pick_mode`/
  `set_direction`/`fit`/`one_to_one`/`zoom_at`/`image_rect`/`grab_image`/`transform`. Two deliberate
  departures from the brief's reference code, both required by the task brief itself -- see below.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` (new): the brief's 13 tests, plus 5 of
  my own (empty-axis paint guard x2 parametrised cases, the two defect-(b) guard tests, a
  decimation-scaling test, and a `with_radargram` interface test), with 3 of the brief's own tests
  corrected where they were unsound as given (see below). 18 tests total.

## The two brief defects, as fixed

### (a) `paintEvent` dividing by zero on an empty trace/sample axis

Restructured so the division is inside the same condition that gates using it at all:

```python
if self._image is not None and t.n_traces > 0 and t.n_samples > 0:
    sx = self._image.width() / t.n_traces
    sy = self._image.height() / t.n_samples
    x, y, w, h = t.source_rect()
    painter.drawImage(QRectF(r), self._image, QRectF(x * sx, y * sy, w * sx, h * sy))
else:
    painter.setPen(AXIS_COLOUR)
    painter.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self._message)
```

An empty axis with a real (non-null) image falls back to the same "message" branch as no-image-yet,
which was the only existing defined behaviour to fall back to -- Task 13's contract (`n_traces == 0`
/ `n_samples == 0` is legal, constructible, never rejected) is left untouched; nothing about the
*axis* is treated as invalid, only "there is nothing meaningful to draw as an image right now."

**This is not merely a swallowed exception -- it can be a hard process crash.** Mutating the guard
back out and running the empty-sample-axis test produced a **segmentation fault inside
`pytest_runtest_call`** (not at process teardown -- see the mutation log below), not a Python
traceback. `QPainter(self)` never reached `painter.end()` before the `ZeroDivisionError`, and an
unterminated `QPainter` against a live paint device is a documented Qt hard-failure mode, not a
graceful one. This is a stronger finding than the brief's framing ("a live `ZeroDivisionError` inside
a paint event") suggests: in this environment it is not just silently eaten by Qt's exception
reporting, it can bring the whole process down.

### (b) Exceptions in `wheelEvent`/`mouseMoveEvent` vanish

Both handlers now wrap their body in `try/except Exception`, logging through the same
`_log()`-via-`QgsMessageLog` helper `nsgeo_qgis.ui.survey_dock` already establishes, and leaving
`self.transform` at its last good value:

```python
def wheelEvent(self, event: Any) -> None:
    if self.transform is None:
        return
    try:
        x, y = self._local(event)
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_at(1.25**steps, x, y)
    except Exception as exc:  # noqa: BLE001
        _log(f"could not zoom: {exc}", Qgis.MessageLevel.Warning)
```

`mouseMoveEvent` delegates its whole body to a private `_handle_mouse_move` and wraps just that call,
for the same reason `survey_dock.rebuild()` separates `_rebuild()` from the guarded outer method.

**Caught `except Exception`, not `except ValueError`, deliberately -- verified directly, not
assumed.** I constructed the exact failure and ran it: `event.angleDelta().y() = -100_000_000` makes
`steps ~= -833_333`; `1.25 ** steps` **underflows to exactly `0.0`** in IEEE 754 double arithmetic
(confirmed: `1.25**(-833333) == 0.0`), and `ViewTransform.zoomed` then divides a span by that `0.0`,
raising **`ZeroDivisionError`** -- not the `ValueError` `ViewTransform`'s own finiteness guard raises,
because the division itself blows up before that guard is ever reached. A large *positive* delta is
worse: `1.25 ** steps` for `steps ~= +833_333` raises **`OverflowError`** directly (`(34, 'Numerical
result out of range')`) inside `wheelEvent` itself, before `zoom_at`/`ViewTransform` are even called.
Three different exception types are reachable from one bad wheel delta (`OverflowError`,
`ZeroDivisionError`, and `ValueError` for inputs that don't hit either extreme but still land
non-finite), which is exactly why the guard has to be `except Exception`, not the narrower
`ValueError` the brief's framing of this defect implies.

**Also verified directly (not assumed) that PyQt5 really does swallow an exception raised inside a
Qt-invoked virtual method, and that this environment does not abort the process for it.** A small
scratch reproduction (`QWidget` subclass overriding `wheelEvent` to raise, dispatched with
`QApplication.sendEvent`) confirmed: the raise reaches `sys.excepthook` and `sendEvent` still returns
normally -- the module docstring's claim ("PyQt prints the traceback to stderr and execution continues
as if it succeeded") holds in this specific environment. That scratch check is also why the tests for
this defect install a capturing `sys.excepthook` rather than asserting "no exception reached the
test": going through the real event dispatch, an unguarded handler's exception genuinely does not
propagate to the test process, so "the test didn't crash" is not evidence the guard exists.

## Other issues found (beyond the two named defects)

Per the instruction to treat the rest of the brief as suspect: three more problems were found, all in
the brief's own *test* code, none in its reference implementation.

1. **A tautological assertion that can never fail.** `test_radargram_image_caches_and_rebuilds_on_display_change`'s
   last line was:
   ```python
   assert ri3.image.pixel(0, 0) != img.pixel(0, 0) or ri3.colormap_name != DEFAULT_COLORMAP
   ```
   The right-hand disjunct (`"grey_white_high" != "grey_black_high"`) is always `True`, so the whole
   assertion is always `True` regardless of what `with_display`/`colormap`/`to_rgb8` actually do. Fixed
   by asserting the pixel comparison directly, verified safe (not just less flaky) by checking `_grey()`'s
   construction: `grey_black_high[i] = 255 - i` and `grey_white_high[i] = i` for every index `i` in
   0..255 exactly (both ramps are whole-integer `linspace` steps over 256 entries), so the two tables
   disagree at *every* index -- there is no amplitude value at which they could coincide.

2. **A short-circuit bug that raises `IndexError` instead of failing cleanly.**
   `test_depth_axis_uses_the_velocity_model`'s probe was:
   ```python
   assert labels and labels[0].startswith("-") or labels[0] == "0"
   ```
   `and`/`or` precedence makes this `(labels and labels[0].startswith("-")) or (labels[0] == "0")`; if
   `depth_tick_labels()` ever returned an empty list, the left disjunct is `[]` (falsy), evaluation
   falls to `labels[0] == "0"`, and that indexes an empty list -- `IndexError`, not a clean assertion
   failure. Split into `assert labels` followed by the intended check.

3. **`QTest.mouseMove` does not reliably deliver a move while a button is held, in this environment.**
   Confirmed directly (scratch reproduction with tracing on `mouseMoveEvent`): the brief's own
   `test_drag_selects_a_trace_range` (`QTest.mousePress` -> `QTest.mouseMove` -> `QTest.mouseRelease`)
   never invokes `mouseMoveEvent` at all for the middle step -- the exact same `QTest.mouseMove` call
   with *no* button held (as in `test_mouse_move_emits_the_trace_under_the_cursor`) works every time.
   This is a limitation of `QTest`'s cursor-warp-based simulation under `QT_QPA_PLATFORM=offscreen`,
   not a bug in `ProfileView`: directly constructing and sending a real `QMouseEvent(MouseMove, ...)`
   via `QApplication.sendEvent` reaches `mouseMoveEvent` every time and produces the exact expected
   selection `(28, 86)`. Added a `_send_move_while_pressed()` helper used by both
   `test_drag_selects_a_trace_range` and my own pan-guard test, in place of the mid-drag
   `QTest.mouseMove` call. As given, the brief's drag-select test would have passed or failed
   independent of whether drag-selection worked at all -- its middle step was a no-op.

## Decimation vs. `source_rect()`: how the reconciliation works

`ViewTransform.source_rect()` returns `(x, y, w, h)` in **unbinned** trace/sample index units (Task
13's contract). `RadargramImage.image` can be **narrower** than `n_traces` pixels when
`decimate_columns` fires (real lines here are 606-666 traces, well under the default
`max_width=8192`, so this path is unreachable with real data -- confirmed and treated as a hazard per
the brief, not assumed safe). `paintEvent` reconciles the two by scaling the source rect into the
cached image's own pixel space before using it:

```python
sx = self._image.width() / t.n_traces
sy = self._image.height() / t.n_samples
x, y, w, h = t.source_rect()
painter.drawImage(QRectF(r), self._image, QRectF(x * sx, y * sy, w * sx, h * sy))
```

This is the brief's own approach (unchanged); what I added is a test that actually exercises it rather
than merely trusting it. `test_decimated_image_paints_the_correctly_scaled_source_rect` builds a
20,000-trace, 8-sample line where every column's value equals its own trace index (so the decimated
image is a smooth, still-monotonic gradient), decimates it to exactly 2000 pixels wide
(`20_000 / 10` traces per column, no ragged tail), zooms into two disjoint trace windows near the
start and near the end of the *original* 20,000-trace axis, and asserts the rendered grey levels
differ in the correct direction by a wide margin. Mutating `sx`/`sy` to `1.0` (i.e. treating the
source rect as if it were already in decimated-image pixels) was caught: the far window's source rect
then falls outside the 2000px-wide image entirely, and the two windows render at existing pixel values
124.3 and 250.0 respectively rather than the expected `low > high + 50` -- an inversion, not just a
smaller gap, confirming the mutation breaks the read, not merely blurs it. Also confirmed the
decimation-only test (`ri.image.width() <= 4096`, from the brief) does **not** by itself catch this:
it only checks the cached image's own size, never that a widget actually reads the right part of it.

## Memory ownership (`rgb_to_qimage`'s `.copy()`): the brief's own probe does not catch the mutation

The brief's test deleted `rgb` after construction (`del rgb`) and then asserted on pixel values.
**Mutated `rgb_to_qimage` to drop `.copy()` and reran: the test still passed.** Investigated why:
PyQt5's raw-buffer `QImage(rgb.data, ...)` constructor evidently keeps its own reference to the buffer
object passed in (`rgb.data`, a memoryview), which keeps the ndarray's memory alive as long as the
(uncopied) `QImage` exists -- `del rgb` only removes the local name binding, and does not free memory
still referenced elsewhere. This means the brief's own test, as literally given, does not actually
exercise the hazard it is named for in this PyQt5/environment combination.

Fixed by overwriting the array's bytes **in place** instead of relying on `del` + garbage collection:
```python
rgb[:] = 99
del rgb
assert QColor(img.pixel(1, 0)).red() == 255 and QColor(img.pixel(0, 0)).red() == 0
```
An in-place overwrite doesn't rebind `rgb` -- if `img` were a view onto the same bytes (no `.copy()`),
this corrupts `img`'s pixels too; if `img` owns independent storage (`.copy()` present), it does not.
Verified both ways directly: without `.copy()`, `img.pixel(1, 0)` reads back as `(99, 99, 99)` (the
overwrite value) after the in-place write; with `.copy()` restored, it stays `(255, 0, 0)`
unaffected. This is now the assertion that actually distinguishes the two cases, kept alongside the
brief's original `del rgb` (harmless, just not decisive on its own).

## `QImage.Format_RGB888` row alignment

`rgb_to_qimage` passes the buffer's true row stride (`3 * w`, from `np.ascontiguousarray`) explicitly
to the `QImage` constructor rather than letting Qt assume one -- there is no default stride for Qt to
get wrong when the real one is always given. The brief's own memory-ownership test already exercises
a non-4-aligned width (`w=3`, i.e. 9 bytes/row) and passed correctly once memory ownership was fixed
(above), which is a reasonable proxy for this: a wrong stride would have sheared that 3x2 image's
pixel colours, and it did not.

## `except Exception`/`_log` guard placement: why only `wheelEvent`/`mouseMoveEvent`

`resizeEvent`, `mousePressEvent`, and `mouseReleaseEvent` were deliberately left unguarded.
`resizeEvent` only calls `ViewTransform.resized(w, h)`, which floors `width`/`height` to `>= 1` and
touches no other field -- `t0_ns`/`trace_lo`/etc. are already valid from a prior successful
construction, so there is no reachable non-finite path there. `mousePressEvent`/`mouseReleaseEvent`
only call `trace_index_at`/`time_of_y` (which clamp/never raise) or emit signals with already-computed
values. `set_axes`/`fit`/`one_to_one`/`zoom_at` are ordinary public methods, not Qt-invoked virtual
overrides -- a caller (a future `ProfileDock`, per the established `plugin.py` pattern) can and should
catch their own call sites, the same way `plugin.py`'s dialog-opening methods aren't guarded internally
either. Guarding indiscriminately would also risk masking real implementation bugs during development
behind a warning log instead of a stack trace -- confirmed this is a real risk, not hypothetical: while
developing `_handle_mouse_move`, I ran the full guard-wrapped version first and it worked, but I
independently verified the *un*-guarded logic against every test first, specifically to avoid the guard
silently hiding a bug of my own.

## Test results

**Correction (see "Pre-review fix" below): the QGIS and pure tiers were originally reported as one
combined number.** `packages/nsgeo-qgis/tests` contains both `tests/qgis` and `tests/pure`, so running
it as one path (as below) reports their sum, not either tier alone. Reporting each tier separately,
by its own directory:

- `.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q` (offscreen) -> **169 passed**
  (up from 151 before this task: 18 new tests in `test_plugin_profile_view.py`; confirmed by
  `--collect-only` on both the qgis-only path, not the combined one).
- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q` -> **46 passed** (unchanged; this
  task adds nothing to the pure tier).
- `.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q` (offscreen, both tiers together) ->
  **215 passed** (169 + 46 -- the number originally reported alone, without noting it was the sum).
- `.venv/bin/python -m pytest packages/nsgeo-core/tests -q` -> **287 passed, 2 skipped** (unchanged;
  sanity check that core was untouched).
- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q` -> **4
  passed**: no forbidden `PyQt5`/`PyQt6`/`matplotlib`/`scipy` import, `nsgeo.processing` used only for
  the allowed `Radargram` symbol, `nsgeo_qgis/__init__.py` still imports no `qgis` at module level.
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **80 files already formatted.**
- CI's existing mypy line (unmodified, verbatim from `.github/workflows/ci.yml`) -> **Success: no
  issues found in 24 source files.**
- `test_real_file_renders_at_full_resolution` confirmed running against real data, not skipped
  (`1 passed` when selected alone; the ten real DZT files are reachable via the existing symlinks).

**`packages/nsgeo-qgis/nsgeo_qgis/render/qimage.py` and `.../ui/profile_view.py` were deliberately
*not* added to the CI mypy line.** Tried it directly: both fail with `Cannot find implementation or
library stub for module named "qgis.*"` -- the `lint` CI job installs only `ruff mypy numpy`, no QGIS,
so `qgis.PyQt`/`qgis.core` are unresolvable there regardless of this task's code. Task 13's
`view_transform.py` could be added because it imports no Qt at all; these two files are exactly the
Qt-dependent half of this task, so they stay out of that line, unlike Task 13. Ran mypy against them
anyway (locally, filtering the expected `qgis.*` import errors) to catch any *other* type error: found
one (a `ViewTransform | None` narrowing gap in `_handle_mouse_move`, since the null-check lives in the
caller `mouseMoveEvent`, not in this method itself) and added `assert self.transform is not None` at
the top of `_handle_mouse_move`, matching the existing `assert self._velocity is not None` style
already used in `_depth_ticks`. Zero non-import-related errors remain.

## Mutation testing

All mutations applied directly to the committed worktree files (never a scratch copy this time, since
the point was to prove the *actual* shipped guard/logic), one at a time, confirmed failing, then
restored from a pre-mutation backup and diffed byte-for-byte (`md5sum`) to confirm no residual change
before moving to the next. Every sweep ran with `PYTHONDONTWRITEBYTECODE=1`.

| # | Target | Mutation | Result |
|---|---|---|---|
| 1 | Memory ownership | drop `.copy()` in `rgb_to_qimage` | **survived** against the brief's own `del rgb` probe; **caught** after strengthening the test with an in-place overwrite (see above) |
| 2a | Decimation | skip `decimate_columns` entirely (`data = self.rg.data`) | caught (both `test_radargram_image_decimates_very_wide_lines` and my scaling test) |
| 2b | Decimation/paint reconciliation | `sx = sy = 1.0` in `paintEvent` | caught (my `test_decimated_image_paints_the_correctly_scaled_source_rect`; low/high grey levels inverted: 124.3 vs 250.0 against an expected `low > high + 50`) |
| 3 | Cursor coordinate mapping | drop the `+ 0.5` trace-centring offset in `_paint_cursor` | caught (`test_cursor_is_drawn_at_the_trace`) |
| 4 | Pick coordinate mapping | swap `x`/`y` arguments into `pick_requested.emit(...)` | caught (`test_shift_click_and_pick_mode_request_picks`) |
| 5 | Selection coordinate mapping | drop the `- image_rect().left()` margin offset in the drag-select `a =` computation | caught (`test_drag_selects_a_trace_range`) |
| 6 | Defect (a) | drop the `t.n_traces > 0 and t.n_samples > 0` guard in `paintEvent` | caught -- **as a segmentation fault inside `pytest_runtest_call`**, not a Python exception (see "defect (a)" above) |
| 7 | Defect (b), wheel | remove the `try/except` around `wheelEvent`'s body | caught (`test_wheel_event_survives_a_degenerate_zoom_factor_instead_of_leaking_to_qt`) |
| 8 | Defect (b), pan | remove the `try/except` around `mouseMoveEvent`'s body | caught (`test_mouse_move_survives_a_broken_pan_transform_instead_of_leaking_to_qt`) |

8 mutations tried, 1 initially survived (memory ownership, against the brief's own probe) and was
fixed by strengthening the test rather than left unreported; the other 7 were caught on first try. No
mutation was left unresolved or reported as "probably fine" -- each was restored and the full 18-test
file rerun green (or, in mutations 6-8's case where the process itself crashed, restored and rerun
green as a separate confirming step) before moving to the next.

**A reproducible environment quirk found during this sweep, unrelated to correctness:** the offscreen
QGIS test process segfaults intermittently at interpreter/`QgsApplication` teardown (after all tests
in the file have already reported pass/fail) roughly one run in three, regardless of any mutation --
confirmed by re-running the clean, restored file multiple times and seeing it both with and without a
crash. This is distinct from the defect-(a) crash above (which happened *during* test execution, at a
specific test, every time that mutation was applied) and did not affect any test's reported pass/fail
result in any of the runs above -- the dot-per-test output always completed fully before any such
crash, and the full-suite run (`tests/qgis` in one process, 215 tests) never showed this. Flagging it
here since it's a real, observed environment fact and not something to quietly work around.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/render/__init__.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/render/qimage.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (new)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` (new)

## Concerns

None blocking. One thing worth a reviewer's attention because it is a judgement call, not just a fact:

1. **The empty-axis paint fallback (defect a) draws the "no line open"/"loading..." message rather
   than, say, a blank rect.** This reuses the one existing fallback path rather than inventing a new
   visual state; a reviewer might reasonably want a distinct empty-axis message, but nothing in the
   brief or Task 13 specifies one, and inventing one felt like scope creep for a defect fix.

**(Former item 2, the "intermittent offscreen-teardown segfault", was wrong and is withdrawn -- see
"Pre-review fix" below.** It was not pre-existing to the environment and not independent of this
task's code; it was this file's own `view` fixture leaking a shown, parentless widget for Python's GC
to destroy in an order Qt doesn't expect, and it is now fixed.)

---

## Pre-review fix

The coordinator's pre-review found the "intermittent offscreen-teardown segfault" reported above as a
pre-existing environment fact was neither pre-existing nor environmental: it was a real bug in this
task's own test file, conclusively identified by running each test individually rather than as a
whole suite, and by the kernel fault site (`libQt5Widgets.so.5.15.13`, widget destruction, not a pixel
buffer).

**Verified the diagnosis independently before changing anything**, per the review-reception
discipline, rather than taking it on trust:
- Ran each of the 18 tests in `test_plugin_profile_view.py` individually (`pytest path::test_name`,
  one process per test). Result matched exactly: the 9 tests taking the `view` fixture each exited
  **139** (segfault); the other 9 each exited **0**. No test outside those 9 crashed, in either
  direction.
- Confirmed the mechanism: the `view` fixture built a `ProfileView()` with no parent, called
  `.show()`, and `return`ed it -- no `yield`, no teardown at all. A shown, parentless, top-level
  widget destroyed by Python's GC (rather than by Qt, which normally controls destruction order
  through parent-child ownership) at interpreter/`QgsApplication` shutdown is exactly the class of
  hazard the kernel fault site points to. It only surfaces when the process exits shortly after that
  widget's own lifetime ends, which a narrow or single-test run does and a 169-test full-tier run
  usually does not (the `QgsApplication` object, constructed once per test *session*, outlives the
  leaked widget there).

**Root cause, once seen, also explains a claim in my own original report that I now know was wrong.**
I had reported an "intermittent offscreen-teardown segfault... regardless of mutation" during the
mutation-testing sweep, seen only in some full-`test_plugin_profile_view.py`-file runs, and called it
a pre-existing environment fact I could not root-cause. It was not: it was this same leaked-widget bug,
manifesting probabilistically in a full-file run too (GC timing is not deterministic), not only in the
single-test runs that exposed it reliably. I did not test narrowly enough in the original round to
catch it -- I only ran the *whole* file repeatedly, which is exactly the configuration the coordinator
noted "lets it through the first time."

**Fix:** replaced the `view` fixture's direct `ProfileView()` construction with a `make_view` fixture
(`packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`) that tracks every widget it builds and,
on teardown, calls `hide()` then `deleteLater()` on each -- `hide()` so a *shown* top-level window is
never left for GC to tear down, `deleteLater()` so the `QObject` itself is deleted through Qt's own
deferred-deletion path rather than Python's `__del__` reaching into a C++-owned object directly. Did
**not** add an explicit `QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)` flush: judged
it unnecessary here, and verified that judgement rather than assumed it --see "Verification" below,
all sweeps came back clean without one. Also converted the four tests that built a `ProfileView`
directly via the `qgis_app` fixture (`test_decimated_image_paints_the_correctly_scaled_source_rect`,
`test_loading_state_when_there_is_no_image`, both parametrised cases of
`test_paint_event_handles_an_empty_axis_without_dividing_by_zero`, and
`test_real_file_renders_at_full_resolution`) to `make_view` as well, per the coordinator's instruction
-- none of these four crashed in either sweep, but the fix makes the whole file consistently correct
about widget lifetime instead of safe in nine places by construction and safe in four more by luck.

**Verification, in the exact configuration that exposed the bug:**
- All 18 tests run individually, one process per test -- **every one exits 0**. Repeated this full
  18-test individual sweep **three times** (54 individual invocations total): all 0, no exceptions.
- The full file run together, five times in a row: **exit 0 every time** (previously this also
  occasionally segfaulted at teardown, per the mutation-testing log in the original report -- now
  gone across all five runs).
- Re-ran the defect-(a) mutation (dropping `paintEvent`'s empty-axis guard) against this new fixture
  shape to confirm it still reproduces the *original*, unrelated crash -- **it does**, at the exact
  same test (`test_paint_event_handles_an_empty_axis_without_dividing_by_zero[empty_sample_axis]`),
  confirming the widget-lifetime fix did not paper over or change the behaviour of the real defect-(a)
  bug it sits alongside.
- Full regression battery re-run after the fix: qgis tier 169 passed, pure tier 46 passed, core 287
  passed/2 skipped, boundary 4 passed, `ruff check` clean, `ruff format --check` clean, CI mypy line
  (unmodified) clean.

**Report correction (numbers):** the original report's "**215 passed**, up from 197" conflated the
qgis and pure tiers by running `packages/nsgeo-qgis/tests` (which contains both) as one path. Fixed
above, under "Test results", to report each tier from its own directory: qgis tier 169 (151 before
this task), pure tier 46 (unchanged), 215 only as their explicitly-labelled sum.

## Commit

`e8773f7` -- "fix: tear down every ProfileView this test file constructs", on top of `31b5f73` (the
original Task 14 implementation commit).

---

# Fix Round 1

Review verdict: spec compliance PASS (all six brief defects the implementer found unaided confirmed
correct, best catch rate on this branch). Task quality CHANGES REQUESTED: one Critical (a reproducible
hard segfault, three reachable inputs) and nine Important findings, almost all coverage -- 35
mutations applied, 11 killed, 24 survived. Ten Minors, fix all except m6 (parked, cosmetic).

## C1 (Critical) -- paintEvent had three unguarded raise paths and no try/finally at all

Fixed exactly as instructed: wrapped the whole `paintEvent` body in `try: ... except Exception as exc:
_log(...) finally: painter.end()`, and additionally validated the three specific inputs at their own
source rather than relying only on the outer catch-all:

- **C1a** (`distance_along` length != `n_traces`): `set_axes` now checks
  `distance_along.ndim != 1 or distance_along.shape[0] != n_traces`, logs, and stores `None` instead of
  the mismatched array.
- **C1c** (`dt_ns <= 0`): `set_axes` now checks `not dt_ns > 0` first and rejects the whole call
  (leaving `self.transform` at whatever it was), logging why. Not reachable from real data today
  (`parse_header`/`Radargram.__post_init__` already reject it), but `set_axes` is a public entry point
  with no caller in between, so it enforces its own contract.
- **C1b** (empty-trace-axis + a *matching* empty `distance_along`): C1a's length check passes (`0 ==
  0`), and the array still reached `np.interp` with an empty `xp` inside `_distance_ticks`. Added
  `self._distance is None or t.n_traces == 0` there directly -- the same "this axis has nothing to
  tick" fallback as the no-distance branch.

**Verified each specific guard is independently load-bearing, not just covered by the outer
catch-all** -- this mattered concretely for C1b: `grab_image()` alone did not distinguish "the
`_distance_ticks` guard exists" from "paintEvent's own catch-all covered for it" (both make
`grab_image()` not raise). Added a direct call to `_distance_ticks()` in that test, which does raise
without its own guard, confirmed by mutation (see the ledger).

**Investigated, and corrected my own initial claim, on the exact contribution of `except` vs.
`finally`.** My first pass reused the brief's framing ("`except Exception` alone is not enough here,
because it does not guarantee `painter.end()` runs") without independently re-deriving it. Measured
directly instead:
- `except Exception` present, `painter.end()` skipped entirely (no `finally`, no call after): survives
  three consecutive repaints, no crash, no warning. A purely-local `painter` with no other reference is
  destroyed the instant `paintEvent` returns, and (confirmed via a from-scratch reproduction) this
  destruction implicitly ends the painter.
- `except ValueError` (does not match a raised `RuntimeError`), `finally: painter.end()` still present:
  also survives. `finally` runs regardless of which exception type escaped the `except`, so
  `painter.end()` still executes before the exception continues propagating.
- Both removed entirely (the original, pre-C1 shape): reliably segfaults on the second `grab_image()`
  call, reproduced directly, including the exact diagnostic Qt prints first ("QPaintDevice: Cannot
  destroy paint device that is being painted").

So the accurate statement is: `except Exception` and `finally: painter.end()` **each independently**
prevent this specific crash; only removing **both** reproduces it. The code comment and the new
`test_paint_event_survives_an_unexpected_exception_across_two_repaints`'s docstring were both written
to say this precisely, not the initially-assumed (and, on direct measurement, wrong in the "either
alone" case) version.

## I1 -- positive wheel-zoom test

Added `test_wheel_event_zooms_about_the_cursor`: dispatches a real `QWheelEvent` (`angleDelta =
(0, 120)`, one standard notch) at a known anchor and asserts the resulting window against hard-coded
numbers (`trace_lo/trace_hi = 20.0/180.0`, `time_lo/time_hi = 2.4/53.6`), independently derived from
`ViewTransform.zoomed`'s documented formula by hand, not by calling `zoom_at`/`wheelEvent` to produce
the expected value.

## I2 -- positive middle-drag-pan test

Added `test_middle_drag_pans_the_view`: zooms in first (fit zoom clamps any pan to nothing, since the
window already spans the full data extent), then drags the middle button by a known pixel delta and
asserts the resulting window against hard-coded numbers, independently derived from
`ViewTransform.panned`'s documented formula.

## I3 -- fixed: `_pan_last` is no longer stuck armed by a non-middle release

`_handle_mouse_move`'s pan branch now checks `event.buttons() & Qt.MouseButton.MiddleButton` before
treating `_pan_last is not None` as an active pan; if the middle button is no longer actually held, it
clears `_pan_last` and falls through to the ordinary hover/drag-select logic instead. This is
authoritative regardless of which release path (or lack of one -- e.g. losing focus mid-drag) got
there, rather than trying to clear `_pan_last` from every place that might need to.

Added `test_stuck_pan_is_not_armed_by_a_later_non_middle_release`, reproducing the reviewer's exact
sequence (middle-press, left-press, left-release, one button-less move) and asserting no pan happened
and `_pan_last` is `None` afterward. One test-construction issue found and fixed along the way: `QTest`
tracks button state globally, so a plain `QTest.mouseMove` after a middle-press with no matching
middle-release still reports the middle button held (Qt's own bookkeeping, not this widget's) --
`QTest.mouseMove` would then silently not be delivered at all for the same reason
`_send_move_while_pressed` already exists, making the test pass for the wrong reason. Used that same
direct-`QMouseEvent` helper (with `buttons=NoButton` explicitly) for the final move instead.

## I4 -- fixed: a right-button release no longer ends or commits a left-button drag

`mouseReleaseEvent`'s generic branch now requires `event.button() == Qt.MouseButton.LeftButton` before
touching `_press`/`_dragging`/emitting `range_selected` -- Left is the only button `mousePressEvent`
ever arms those for.

Added `test_right_button_release_does_not_end_or_commit_a_left_drag`: starts a left-button drag,
presses and releases the right button mid-drag, asserts nothing was emitted and the left-button drag is
still completable afterward by its own release.

## I5 -- resize-after-set_axes: implementation was already correct, only untested

Confirmed `resizeEvent`'s `self.transform = self.transform.resized(...)` was not itself buggy --
mutating it to `pass` is what the review measured, and every existing fixture called `resize()` before
`set_axes`, so `self.transform` was `None` at the only resize in the whole suite and the branch never
ran. No production change; added `test_resize_after_axes_are_set_updates_the_transform`, reproducing
the reviewer's own numbers (`image_rect().width()` 696 -> 896 after widening 800px -> 1000px; hover at
local x=800 gives trace 178, not the stale-width 199).

## I6 -- fixed: `test_paints_the_image_inside_the_margins` now proves the margin stayed background

Replaced the vacuous `margin.red() == margin.green() == margin.blue()` probe (true of every pixel under
the grey colormap regardless of what was painted where) with `margin == BACKGROUND` (exact). Real
radargram data landing on precisely `(250, 250, 250)` is not a realistic tie.

## I7 -- fixed: `test_depth_axis_uses_the_velocity_model` now proves the velocity model is actually used

Replaced the `labels[0] == "0"` check (satisfied by both the real computation and the reviewer's
velocity-bypassed mutation, since both axes happen to include a "0" tick with this fixture's numbers)
with the exact label list (`["0", "1", "2", "3"]`, independently derived from the fixture's known
`t0_ns=-4.0, n_samples=128, dt_ns=0.5` and `VelocityModel.constant(0.1)`) plus the tick *y-positions*
(`[16.5, 99.0, 181.5, 264.0]`), closing the "y pinned to a constant" survivor too.

## I8 -- `_paint_axes`'s value computations factored out and directly tested

Extracted `_time_ticks(t)` (mirroring the already-separate `_depth_ticks`/`_distance_ticks`),
`_distance_unit_label()`, and `_direction_arrow()` out of `_paint_axes`'s body -- a behaviour-preserving
refactor (same rendered output) that makes each piece assertable as a plain value instead of only
provable by reading rendered pixels. Added:
- `test_time_ticks_use_the_actual_time_range_and_positions` (exact labels + y-positions, hard-coded)
  and `test_time_ticks_are_actually_rendered_in_the_left_margin` (a lightweight rendering check that
  `_paint_axes` actually consumes the loop, not just that the values are right).
- `test_distance_ticks_are_actually_rendered_at_the_bottom` and
  `test_distance_ticks_fall_back_to_trace_ticks_without_distance_along` (the no-distance branch was
  never exercised at all -- the `view` fixture always supplies `distance_along`).
- `test_distance_unit_label_reflects_whether_distance_is_set` and
  `test_direction_arrow_reflects_set_direction` (the latter also independently pins `set_direction()`
  itself, not just the arrow computation, against becoming a no-op).

## I9 -- selection and pick painting: extracted, tested, and one live behaviour gap fixed

Extracted `_selection_bounds(t)` and `_pick_positions(t)` out of `_paint_selection`/`_paint_picks` (same
reasoning as I8). Added:
- `test_selection_bounds_use_the_trace_after_b_for_the_right_edge` (`b + 1`, not `b`, as a plain value)
  and `test_selection_is_actually_rendered` (lightweight consumption check).
- `test_pick_positions_use_the_trace_centre_and_the_time` and
  `test_set_picks_renders_a_marker_at_the_correct_position` (`set_picks()` was never called by any
  test in the suite at all).
- `test_set_selection_normalises_reversed_bounds` (direct, cheap) and
  `test_drag_right_to_left_still_emits_a_normalised_range` (end to end: the live gap the review named --
  a right-to-left drag was untested end to end and, without the `min`/`max` normalisation, would emit a
  reversed range to whatever Task 15 connects to `range_selected`). No implementation change needed for
  the normalisation itself -- it was already correct, only untested.

## Minor

- **m1 (fixed).** Corrected the `make_view` docstring: neither `deleteLater()` here ever actually
  deletes a widget (confirmed with `sip`: `isdeleted` stays `False` through `deleteLater()` and
  `processEvents()`, only becoming `True` after an explicit `sendPostedEvents(None, DeferredDelete)`
  flush this fixture never calls -- every widget it builds leaks for the rest of the process,
  harmlessly). What removes the segfault hazard is the *ownership transfer* `deleteLater()` performs
  (`sip.ispyowned`: `True` -> `False`), independently confirmed against `sip` directly rather than
  taken on trust; `hide()` removes the same hazard by a different route (never leaving a *shown*
  top-level window for GC to race Qt's own teardown over).
- **m2 (fixed).** Moved `test_mouse_move_emits_the_trace_under_the_cursor`'s probe from
  `r.width() // 2` (348 -- `348/696` is exactly `0.5`, a coincidental tie one ULP from flipping, and
  coupled to this fixture's specific 800px width) to `r.width() // 3` (232 -- `232/696` is exactly
  `1/3`, landing on `66.666...`, nowhere near an integer boundary).
- **m3 (fixed).** `test_cursor_is_drawn_at_the_trace` now searches a +-1px window around the expected
  column instead of asserting on a single exact pixel -- same mutation sensitivity (the `+ 0.5` removal
  is still killed), not brittle to a 1px rendering shift.
- **m4 (fixed, as a quantified/tested-but-not-eliminated hazard, per the review's own framing).** Added
  a code comment in `paintEvent` at the `sx`/`sy` computation documenting the ragged-tail imprecision
  explicitly, and `test_decimation_ragged_tail_scaling_error_is_bounded_at_fit_zoom`, which pins the
  reviewer's own measured numbers (`block=11`, `image.width()=1819` for `n=20_001, max_width=2000`,
  error `0.727...` px across the whole width at fit zoom) so a future change that makes the error worse
  would be caught. Not eliminated: doing so needs `decimate_columns`'s own block size inside
  `paintEvent`, a larger change than this finding asked for, and it is unreachable with real data today
  regardless (max_width=8192; real lines are 606-666 traces).
- **m5 (fixed).** Added `test_vertical_scaling_reconciles_an_image_shorter_than_n_samples`: builds a
  2-row image directly (bypassing `RadargramImage`, which can never produce `image.height() !=
  n_samples` since `decimate_columns` only ever bins columns) against axes declaring 8 samples, and
  confirms two different time sub-windows read the two different image rows in the correct direction --
  mirrors the existing horizontal (`sx`) test for the vertical (`sy`) axis.
- **m6.** Parked, per instruction (cosmetic, no correctness consequence).
- **m7 (fixed).** `test_radargram_image_decimates_very_wide_lines` now asserts the exact width (`4000`,
  independently computed: `block = ceil(20_000/4096) = 5`, `n_blocks = ceil(20_000/5) = 4000`, no
  ragged tail) instead of `<= 4096`, which a 1-px-wide image would also satisfy.
- **m8 (fixed).** Extracted the byte-identical `_log`/`QgsMessageLog` helper (`survey_dock.py` and
  `profile_view.py` both had it inline) into `nsgeo_qgis/log.py`. `survey_dock.py`'s own call sites are
  unchanged -- `from nsgeo_qgis.log import log as _log` keeps the same local name, same signature, same
  behaviour; confirmed by re-running its own test suite (18 passed, unchanged) after the change.
- **m9 (fixed).** Added `test_set_axes_and_fit_emit_view_changed` (both were untested; `set_axes`'s
  emission is easy to miss since every existing test already connects and checks something else first),
  `test_one_to_one_sets_a_trace_per_pixel_column_and_emits_view_changed` (never called by any test;
  needed a >696-trace axis so the requested one-trace-per-pixel window isn't itself clamped by
  `n_traces` to something smaller, which would have made the assertion pass by clamp coincidence rather
  than because `one_to_one` did what it claims), and `test_clear_resets_state_and_paints_safely` (never
  called by any test).
- **m10 (fixed).** Added an anchor-invariant assertion to
  `test_wheel_zooms_about_the_cursor_and_emits_view_changed`:
  `v.transform.trace_of_x(anchor_x) == pytest.approx(anchor_trace_before)`, which the
  `zoomed(factor, 0.0, 0.0)` anchor-ignoring mutation breaks (confirmed) while the span-halving
  assertion alone did not.

## Mutation ledger (Fix Round 1) -- every mutation and its honest outcome

All mutations applied directly to the committed worktree file (never a scratch copy, since the point
was to prove the actual shipped fix), one at a time via a saved pre-mutation checkpoint, confirmed
failing, then restored and diffed byte-for-byte (`md5sum`) before the next. Every run used
`PYTHONDONTWRITEBYTECODE=1`.

| # | Finding | Mutation | Result |
|---|---|---|---|
| 1 | C1c | `set_axes`'s `dt_ns > 0` guard removed | caught |
| 2 | C1a | `set_axes`'s length-mismatch guard removed | caught (and confirmed paintEvent's own outer catch-all also engaged gracefully, logging the same `ValueError` -- defence in depth working as designed) |
| 3 | C1b | `_distance_ticks`'s `n_traces == 0` guard removed | **survived against the original test** (paintEvent's own outer catch-all covered for it, since `grab_image()` alone can't tell which guard caught it) -- strengthened the test to call `_distance_ticks` directly; **caught** on re-test |
| 4 | C1, generic | `except Exception` narrowed to `except ValueError` (doesn't match the raised `RuntimeError`), `finally` kept | **survived** -- `finally` still runs `painter.end()` before the exception continues propagating; this is the "either alone is sufficient" finding, not a gap |
| 5 | C1, generic | `except`+`finally` both removed entirely (the full pre-C1 shape) | caught -- reliable segfault on the second `grab_image()`, reproduced with a full traceback and the exact Qt diagnostic |
| 6 | I1 | `wheelEvent`'s `if steps:` -> `if False:` | caught (new positive test; the two existing wheel tests, which call `zoom_at` directly, were unaffected as expected) |
| 7 | I2 | `_handle_mouse_move`'s `panned()` call dropped | caught |
| 8 | I3 | buttons-check in the pan branch replaced with `if False:` (always treat as panning) | caught |
| 9 | I4 | left-button check in `mouseReleaseEvent` removed | caught (the two drag-completion tests, left-to-right and reversed, were unaffected as expected) |
| 10 | I5 | `resizeEvent`'s transform update replaced with `pass` | caught |
| 11 | I6 | `drawImage(QRectF(r), ...)` -> `drawImage(QRectF(self.rect()), ...)` | caught |
| 12 | I7 | `depths = self._velocity.depth_at(times)` -> `depths = np.asarray(times)` | caught |
| 13 | I7 | depth tick `y` -> pinned `0.0` | caught |
| 14 | I8 | `_time_ticks`' range `nice_ticks(t.time_lo, t.time_hi)` -> `nice_ticks(0.0, 1.0)` | caught (both the value test and the rendering test) |
| 15 | I8 | `_time_ticks`' `y` -> pinned `0.0` | caught (both) |
| 16 | I8 | `_distance_ticks`'s no-distance branch -> `return []` | caught |
| 17 | I8 | `_distance_unit_label()` -> pinned `"trace"` | caught |
| 18 | I8 | `_direction_arrow()` -> pinned `"→"` | caught |
| 19 | I8 | `set_direction()` -> no-op (`self._direction = 1` always) | caught |
| 20 | I9 | `set_selection`'s `min`/`max` normalisation removed | caught (both the direct test and the end-to-end reversed-drag test) |
| 21 | I9 | `_selection_bounds`'s `b + 1` -> `b` | caught |
| 22 | I9 | `_pick_positions` -> pinned `(0.0, 0.0)` | caught (both the value test and the rendering test) |
| 23 | m5 | `sy = self._image.height() / t.n_samples` -> `sy = 1.0` | caught |
| 24 | m9 | `set_axes`'s `view_changed.emit()` dropped | caught |
| 25 | m9 | `fit`'s `view_changed.emit()` dropped | caught |
| 26 | m9 | `one_to_one()` -> no-op (keeps `view_changed.emit()`) | caught |
| 27 | m9 | `clear()` -> no-op (keeps `self.update()`) | caught |

27 mutations tried, **26 caught, 1 survived on first try** (#3, C1b) and was closed by strengthening the
test to call the guarded method directly rather than only through `grab_image()`; re-tested and caught.
Mutation #4 is reported as "survived" deliberately -- it is not a gap, it is the direct evidence for the
"either `except` or `finally` alone is sufficient" finding above, and reporting it as caught would have
been the same kind of overclaim Fix Round 2 of Task 13 had to walk back once already on this branch.

## Test results after Fix Round 1

- `.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q` (offscreen) -> **195 passed** (up
  from 169: 26 new tests in `test_plugin_profile_view.py`, taking that file from 18 to 44).
- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q` -> **46 passed** (unchanged).
- `.venv/bin/python -m pytest packages/nsgeo-core/tests -q` -> **287 passed, 2 skipped** (unchanged).
- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q` -> **4 passed**
  (the new `nsgeo_qgis/log.py` imports only `qgis.core`, already an established, allowed import
  elsewhere in the plugin).
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **81 files already formatted** (up from 80: the new `log.py`).
- CI's mypy line (unmodified) -> **Success: no issues found in 24 source files.**
- **Individual-test sweep, all 44 tests in `test_plugin_profile_view.py`, one process each: all 44 exit
  0.** Confirms the widget-lifetime fix from the previous round was not regressed by any of this
  round's new tests (every new test that constructs a `ProfileView` does so through `make_view`,
  uniformly).
- `survey_dock.py`'s own test suite re-run explicitly after the `_log` extraction: **18 passed,
  unchanged.**

## Files changed in this round

- `packages/nsgeo-qgis/nsgeo_qgis/log.py` (new): the shared `log()` helper (m8).
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`: `paintEvent` wrapped in `try/except/finally`
  (C1); `set_axes` validates `dt_ns` and `distance_along` (C1a/C1c); `_distance_ticks` guards
  `n_traces == 0` (C1b); `_handle_mouse_move`'s pan branch checks `event.buttons()` (I3);
  `mouseReleaseEvent` checks the released button is Left (I4); `_time_ticks`, `_distance_unit_label`,
  `_direction_arrow`, `_selection_bounds`, `_pick_positions` extracted from `_paint_axes`/
  `_paint_selection`/`_paint_picks` (I8/I9); `_log` now imported from `nsgeo_qgis.log` (m8).
- `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`: `_log` now imported from `nsgeo_qgis.log` instead
  of defined inline; no call site or behaviour changed (m8).
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`: 26 new tests, `make_view`'s docstring
  corrected (m1), two probes moved off coincidental exactness (m2, m3), two assertions tightened to
  exact values (m7, I6/I7).

## Concerns

None blocking. Two things worth a reviewer's attention because they are judgement calls or limits of
what a test can prove, not just facts:

1. **C1's outer `except Exception`/`finally: painter.end()` are each independently sufficient against
   the specific segfault mechanism measured here** (see the mutation ledger, #4 vs #5) -- both are kept
   regardless, since they serve different purposes (the `except` also stops the exception from ever
   reaching `sys.excepthook` at all, consistent with `wheelEvent`/`mouseMoveEvent`'s established
   convention; `finally` is explicit resource-lifecycle clarity rather than leaning on CPython's
   immediate-refcounting destructor timing for something this consequential). Flagging this because my
   own first-pass reasoning about *why* got it wrong before I measured it directly, and I would rather
   a reviewer know that was corrected than have it read as settled from the start.
2. **m4 is fixed as "quantified and tested, not eliminated,"** per the review's own framing of it as a
   hazard rather than a live bug. If a future task widens what "wide enough to decimate" means in
   practice (e.g. lines close to `max_width`), this quantification test would need re-deriving its
   literal numbers for the new scenario, not just re-running.

---

# Fix Round 2

Re-review verdict: C1, all nine Importants, and all nine in-scope Minors CLOSED. C1 confirmed complete
this time -- a forced raise at 8 sites x 4 consecutive repaints all exit 0, including
`KeyboardInterrupt`/`SystemExit`, which `except Exception` cannot catch and only `finally` saves. Six
new Minor findings, all test-side. Three carried into this round; three parked for the whole-branch
review (a bare "something changed" selection-render probe, the `dt_ns` test pinning only `== 0`, and a
distance-tick probe hard-coding Qt's truncation convention without a +-1 window).

**The lesson this round exists to teach, taken at face value:** my Fix Round 1 ledger (26/27 caught)
and the reviewer's original sweep (24 survivors) never actually spoke to each other -- my 27 covered
only 20 of their 24, and the four it omitted included the one gap that was still real (the hover bounds
guard). Before writing any of the three items below, re-ran the reviewer's *own* mutations against the
current tree rather than inventing my own variants, specifically so this round's evidence is checked
against the sweep that actually found the gap, not a fresh one of my own that might miss it the same
way again.

## N1 -- the hover bounds guard, the one real survivor, now pinned

`if 0 <= x < self.transform.width: self.trace_hovered.emit(...)` had no test at all. Decided behaviour
(matching the reviewer's own reproduction exactly, not invented independently): a pointer in the axis
margins is not "over" any trace, so hovering there emits nothing. Added
`test_hover_outside_the_image_rect_emits_nothing`: moves to widget `x=5` (inside the left margin for
this fixture's geometry) and asserts `trace_hovered` never fired.

**Mutation-verified with the reviewer's own exact mutation, not a variant of my own** (`if 0 <= x <
self.transform.width:` -> `if True:`): caught, and the failure reproduces their own predicted output
exactly (`trace_hovered(0)` fires).

## N3 -- a paint failure can no longer go silently unlogged

`test_paint_event_survives_an_unexpected_exception_across_two_repaints` asserted only that the process
survived; dropping the `_log(...)` call inside `paintEvent`'s `except` handler also passed 44/44 -- the
`finally: painter.end()` guard stops the segfault either way, but a regression there would make a paint
failure completely invisible (no crash, no traceback, no log line -- just a widget that silently stops
painting, forever). Added the `message_log` fixture (already used elsewhere in this file, connecting to
`QgsApplication.messageLog()`) to this test and asserted `"could not paint the profile view"` appears in
it.

**Mutation-verified:** replaced the `_log(...)` call with `pass` -- caught.

## N5 -- de-brittled the stuck-pan regression test

The mid-sequence assertion `assert v._pan_last is not None` (right after the left release, before the
final button-less move) pinned the *absence* of any defensive clearing at that specific point. The
reviewer applied two strictly *safer* implementations -- clearing `_pan_last` on a left release too,
and clearing it on any release -- and both correctly fix the same bug while failing that one
assertion. A test that rejects a better implementation of the thing it is testing is a liability: it
would block a legitimate future fix and read as a regression while doing so.

Dropped that one assertion. What remains asserts only the property that actually matters: after the
button-less move, the view did not pan (`v.transform == before`) and `_pan_last` is `None` afterwards,
regardless of which code path got it there.

**Verified all three ways, not just that it still passes on the shipped code:**
- Shipped implementation: passes (unchanged).
- Variant A (also clear `_pan_last` on a left release): applied directly to the committed file --
  **now passes** (previously would have failed the dropped mid-sequence assertion). Ran the *whole*
  `test_plugin_profile_view.py` file under this variant too, not just the one test: **45 passed**,
  confirming it doesn't regress anything else either.
- Variant B (clear `_pan_last` on *any* release, unconditionally at the top of `mouseReleaseEvent`):
  same -- passes, and the whole file still passes (45/45) under it.
- **The real regression is still caught**: restored the shipped code, then disabled the actual I3 fix
  (the `event.buttons() & MiddleButton` check, mutated to never trigger) -- the loosened test still
  fails, and for the right reason (`v.transform` differs from `before`, i.e. a real stuck pan).

No production code changed for N5 -- it is a test-only fix, per the finding.

## Test results after Fix Round 2

- `.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q` (offscreen) -> **196 passed** (up
  from 195: +1, `test_plugin_profile_view.py` now has 45 tests).
- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q` -> **46 passed** (unchanged).
- `.venv/bin/python -m pytest packages/nsgeo-core/tests -q` -> **287 passed, 2 skipped** (unchanged).
- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q` -> **4
  passed**.
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **81 files already formatted.**
- CI's mypy line (unmodified) -> **Success: no issues found in 24 source files.**
- **Individual-test sweep, all 45 tests in `test_plugin_profile_view.py`, one process each: all 45
  exit 0.**

## Files changed in this round

- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` only -- no production code changed this
  round. One new test (N1), one existing test strengthened with an additional assertion and fixture
  dependency (N3), one existing test's over-constrained assertion removed (N5).

## Commit

`fc9237c` -- "fix: pin the hover bounds guard, paint-failure logging, and de-brittle the stuck-pan
test", on top of `8f296e6` (fix round 1).

## Concerns

None. All three items mutation-verified against the reviewer's own reproductions where one was given
(N1), and N5 was verified against both of the reviewer's specific "strictly safer" variants, not merely
re-passed on the shipped code. The three parked findings (bare selection-render probe, `dt_ns == 0`-only
pinning, distance-tick truncation convention) are left for the whole-branch review, as instructed.
