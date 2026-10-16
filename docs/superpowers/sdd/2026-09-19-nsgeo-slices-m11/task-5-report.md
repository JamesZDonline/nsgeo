# Task 5 report: Reading the slice — the band on the radargram, and shift + scroll

## Summary

Implemented spec 9.3's one new profile-view overlay (the active slice's time window, drawn as a
translucent dashed band on whichever radargram is on screen) and spec 9.2's shift+scroll depth
gesture, exactly as the brief specified, with one deliberate addition beyond its literal text
(documented below) and one place where the brief's own predicted mutant outcome did not hold
(also documented below, per Step 6's own instruction to report that honestly rather than force a
test green).

Files touched, matching the brief's list exactly:
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` — `SLICE_BAND_COLOUR`/`SLICE_BAND_EDGE`/
  `MIN_BAND_PX`, `_slice_band` state, `set_slice_band`/`clear_slice_band`/`_slice_band_bounds`/
  `_paint_slice_band`, wired into `paintEvent` (before `_paint_selection`) and `clear()`.
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` — two one-line relays.
- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` — `window_changed`/`window_cleared` signals,
  emitted from `refresh_slice()`; `CanvasDepthScroll`.
- `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` — `depth_scroll_delta`.
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` — wiring in `initGui`/`unload`.
- Tests appended verbatim from the brief to `tests/pure/test_pure_slices_plan.py`,
  `tests/qgis/test_plugin_profile_view.py`, `tests/qgis/test_plugin_slices_dock.py`, and
  `tests/qgis/test_plugin_loads.py`.

## Test counts

| Tier | Command | Before | After |
|---|---|---|---|
| core + pure (`./.venv`) | `pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -q -p no:xonsh` | 541 passed, 2 skipped | 542 passed, 2 skipped (+1 `depth_scroll_delta`) |
| QGIS (`./.venv-qgis`) | `QT_QPA_PLATFORM=offscreen pytest packages/nsgeo-qgis/tests -q -p no:xonsh -W error::DeprecationWarning -W error::FutureWarning` | 558 passed, 0 warnings | 566 passed, **0 warnings** (+4 band tests, +2 dock wiring tests, +1 end-to-end plugin-wiring test) |

`ruff check .` and `ruff format --check .` are both clean. The mypy command CI actually runs —
`mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent
packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
— reports `Success: no issues found in 33 source files`, both before and after (`slices_plan.py`
is in this list; `depth_scroll_delta` type-checks cleanly).

## Decisions where the brief was ambiguous or (in one place) wrong

1. **Test fixture: `make_view`, not raw `ProfileView()`.** The brief's own Step 2 preamble says
   to append the tests "matching its existing fixtures for building a view with axes," but the
   code block it gives constructs `ProfileView()` directly with no teardown. This file's own
   `make_view` fixture docstring documents a measured (not theoretical) segfault hazard for a
   parentless, undisposed `ProfileView` at interpreter shutdown. I followed the preamble's
   instruction over the literal snippet and built all four new tests through `make_view`, which
   is what every other test in the file except one already does.

2. **`window_cleared` also emitted on `refresh_slice()`'s exception path.** The brief only names
   the early-return ("no window") branch for `window_cleared.emit()`. The exception branch right
   below it already resets `_values`/`_window` to `None` and rewrites the readout for exactly the
   reason its own comment gives ("state reset here too, not just reported... otherwise readout
   keeps describing the tick before this one"). Leaving the profile band out of that reset would
   recreate precisely the bug that comment describes, one layer up: an out-of-range `z1` (the
   existing `test_an_error_during_refresh_clears_the_stale_slice_and_readout` scenario) would
   leave the band pointing at a time window the message bar has just said is no longer valid —
   which is the exact confusion spec 9.3's band exists to prevent. I added
   `self.window_cleared.emit()` there too, with a comment explaining why, and reran
   `test_an_error_during_refresh_clears_the_stale_slice_and_readout` to confirm nothing existing
   broke (it didn't — that test doesn't touch `window_changed`/`window_cleared` at all, so this is
   a pure addition, not a change in existing behaviour).

3. **`git push` at the end of Step 7**: per this task's own instructions from the calling agent
   ("Do not push. Commit as the brief says."), I committed but did not run `git push origin
   nsgeo-m11`, overriding the brief's own Step 7 command. This is an explicit instruction from
   this session, not a brief defect.

## The four mutation checks (Step 6)

All four were built, run against the named test (or the full suite where the brief specified no
single test), confirmed, and reverted; the pure and QGIS tiers were re-run clean after each
revert.

**1. `_paint_slice_band` called after `_paint_picks` (and `_paint_selection`), instead of
before.**
Applied the swap in `paintEvent`. Ran the full QGIS suite (566 tests) rather than a single test,
since the brief states plainly that no test catches paint ordering. Result: **all 566 tests still
passed** with the mutant in place — confirming the brief's own claim. This is a real gap: nothing
in the automated suite pins that the band must be visually *under* the selection/picks rather than
over them. Per the brief's explicit instruction, I have not invented a pixel-colour test to force
this into the automated suite; it is a visual judgement call, correctly deferred to the manual
walkthrough this milestone's other tasks also defer such calls to. Reverted; confirmed the profile
view test file (53 tests) passes again.

**2. `depth_scroll_delta` inverted (`return 1 if angle_delta_y > 0 else -1`).**
Ran `test_shift_scroll_steps_deeper_downward_and_is_inert_without_shift`. Result: **FAILED**, as
expected —
```
assert depth_scroll_delta(-120, shift_held=True) == 1  # down: deeper
AssertionError: assert -1 == 1
```
Reverted; test passes again.

**3. `_slice_band_bounds` with the `MIN_BAND_PX` floor removed.**
Ran `test_a_single_level_window_still_draws_a_visible_band`. Result: **FAILED**, as expected —
```
assert y1 - y0 >= 2.0
AssertionError: assert (52.800000000000004 - 52.800000000000004) >= 2.0
```
Reverted; test passes again.

**4. `set_slice_band` without the finiteness guard, fed `float("nan")`.**
This is the one place the brief's predicted outcome did not hold, and I am reporting that plainly
rather than writing a test to match the prediction. The brief expects: "confirm `grab_image()`
then logs rather than raising." What I actually found, using a scratch pytest module built on the
same `qgis_app`/`message_log` fixtures the rest of this tier uses (not committed — deleted after
the check):

- `view.set_slice_band(float("nan"), 30.0)` does not raise (`min`/`max` on a NaN operand return
  NaN rather than raising in Python).
- `_slice_band_bounds` then computes `y0 = y1 = nan` (`ViewTransform.y_of_time` is ordinary float
  arithmetic on the NaN input, which propagates NaN without raising), and `nan - nan < MIN_BAND_PX`
  is `False` (every comparison against NaN is `False`), so the floor never engages.
- `_paint_slice_band` builds a `QRectF`/two `QLineF`s with NaN coordinates and hands them to
  `QPainter`. **Nothing raises.** Qt silently declines to draw the malformed primitives.
  `grab_image()` returns a valid, non-null `QImage`.
- `message_log` (subscribed to `QgsApplication.messageLog()` for the duration of the check)
  received **zero messages** — `_log` is never called, because nothing ever threw.

So without the guard, feeding NaN is neither a crash nor a logged warning: it is a silent no-op
that happens to look harmless in this Qt/PyQt5 build. That is worse to rely on than the brief's
assumed "still safe because it logs" outcome, not better — a future Qt version's handling of NaN
geometry is not a contract this codebase controls, and silently drawing nothing is itself a
regression of the band's whole purpose (the band vanishing with no diagnostic is exactly the kind
of failure spec 9.3 exists to make legible, not invisible).

Separately, per the brief's own fallback instruction, I checked reachability from the dock: it is
genuinely unreachable today. `SlicesDock.refresh_slice()` only ever calls
`window_times_ns(self.engine.z, window)`, whose inputs are `z.t0_ns + k * z.dz_ns` for integer
`k` — and `Resolution.__post_init__` already rejects a non-finite `dz_ns` (`not self.dz_ns > 0.0`
is `True` for NaN, raising `ValueError`) and a non-finite `t0_ns`/`t1_ns` (`t1_ns > t0_ns` is
`False` against NaN, same raise) before a `ZAxis` is ever built. A `QDoubleSpinBox` also cannot
itself emit NaN. So no real caller can reach this path with non-finite values today.

**Conclusion: kept the guard**, for both reasons together — it is unreachable today but the
codebase's own established pattern (`set_axes`'s C1a/C1c defects, explicitly "not reachable from
real data today... but enforces its own contract rather than trust every future caller to") is to
guard the public entry point anyway, and the actual behaviour without it (silent, unlogged,
non-crashing data corruption) is a worse outcome than the brief anticipated, not a merely
theoretical one.

## Verification

- `./.venv/bin/python -m pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -q -p no:xonsh`
  → 542 passed, 2 skipped.
- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q
  -p no:xonsh -W error::DeprecationWarning -W error::FutureWarning` → 566 passed, 0 warnings.
- `ruff check .` / `ruff format --check .` → clean.
- CI's exact mypy invocation → `Success: no issues found in 33 source files`.
- `test_every_declared_signal_has_a_connect` (orphan-signal check) passes with no changes needed:
  `window_changed`/`window_cleared` are each declared once and each connected once in
  `plugin.py`, so neither needed an entry in `KNOWN_UNCONSUMED` or `SHADOWED`.
- `PYTHONDONTWRITEBYTECODE=1` was set and `__pycache__` cleared before every mutation run, per
  this milestone's own documented pyc-staleness trap.

## Commit

Committed as the brief's Step 7 specifies (message body unchanged; attribution line per this
session's own instructions). **Not pushed** — the calling agent's instructions for this task said
explicitly not to push, overriding the brief's own `git push` step.

## Fix round 1 (review follow-ups, no review cycle after)

Three review findings addressed, none Critical/Important. Both requested mutation checks were
built, run, confirmed against a failing assertion, and reverted, matching Step 6's own discipline.

**Minor 1 — the two `ProfileDock` relays were unguarded slots.** `set_slice_band`/
`clear_slice_band` are connected directly to `SlicesDock.window_changed`/`window_cleared` in
`plugin.py`, and this file's own docstring requires every slot doing real work to guard its body
and report through `_log` (the comparable cross-dock slot, `set_difference_index`, already does).
Wrapped both in `try/except Exception` reporting through `_log(..., Qgis.MessageLevel.Critical)`,
matching every other guarded slot in `profile_dock.py` (all fourteen existing ones use `Critical`,
not `Warning`).

**Minor 2 — the band's painting had no pixel coverage.** Added
`test_the_band_is_actually_painted_under_the_picks` to `test_plugin_profile_view.py`: renders a
pick inside the band's own y-range, and asserts (a) a pixel away from the pick changes once the
band is set (catches the band painting nothing) and (b) the pick's own interior pixel reads
*exactly* `PICK_COLOUR` whether or not the band is set (catches the paint order itself).

- **`_paint_slice_band` mutated to `return` on its first line** (the coordinator's named mutant):
  ran `test_the_band_is_actually_painted_under_the_picks` → **FAILED**, caught by assertion (a):
  `assert QColor(before.pixel(...)) != QColor(after.pixel(...))`, `"the band must actually change
  pixels, not paint nothing"` — the probe pixel was `(122,122,122,255)` in both grabs.
- I also re-verified the *original* Step 6 Mutant 1 (paint order swapped to after `_paint_picks`)
  against this same new test, since the coordinator's stated goal was pinning that ordering "for
  free": ran the same test with the order swapped → **FAILED**, caught by assertion (b):
  `assert pick_after == pick_before` — measured `(197, 92, 70, 255)` vs. the true
  `(224, 66, 27, 255)` (`PICK_COLOUR`), i.e. the band's translucent fill alpha-blended onto the
  pick from above. This value matters: the *existing* pick-detection helper
  (`is_pick_coloured`, `red() > 180 and green() < 120 and blue() < 80`) still classifies
  `(197, 92, 70)` as "pick-coloured" — `197 > 180`, `92 < 120`, `70 < 80` all hold — which is
  exactly why that existing loose threshold check (line ~924) does *not* catch this mutation and
  an exact-colour comparison was needed instead, not a re-use of the existing helper as originally
  suggested.
  Both mutations reverted; `test_plugin_profile_view.py` (54 tests) passes clean again.

**Minor 3 — `CanvasDepthScroll.eventFilter` had no test.** Added
`test_canvas_depth_scroll_consumes_shift_wheel_and_leaves_plain_scroll_alone` to
`test_plugin_slices_dock.py`, calling `eventFilter` directly against a minimal stub exposing only
`.type()`/`.modifiers()`/`.angleDelta().y()` (not a real `QWheelEvent`, for the same Qt5/Qt6
constructor-divergence reason `depth_scroll_delta` itself avoids one) built on `fake_iface`'s real
`QgsMapCanvas` and a prepared `docked` dock:

- **`return True` inserted before the `delta == 0` check** (the coordinator's named mutant, at
  the line then numbered `slices_dock.py:1117`): ran the new test → **FAILED**, caught by
  `assert dock.slice_slider.value() > start, "shift+wheel must actually step the slice"` —
  `step_slice` is never reached once `eventFilter` returns unconditionally, so the slider stayed
  at its start value (`assert 0 > 0`). (The mutant also breaks the plain-scroll assertion the same
  way, since it would return `True` there too; this run happened to fail on the first assertion.)
  Reverted; `test_plugin_slices_dock.py` (37 tests) passes clean again.

### Verification after the fix round

- `./.venv/bin/python -m pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -q -p no:xonsh`
  → 542 passed, 2 skipped (unchanged from before this round — no pure-tier files touched).
- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q
  -p no:xonsh -W error::DeprecationWarning -W error::FutureWarning` → **568 passed, 0 warnings**
  (566 → 568: the two new tests).
- `ruff check .` → clean. `ruff format --check .` → one file needed reformatting
  (`test_plugin_slices_dock.py`, a wrapped function signature over the line-length limit);
  reformatted with `ruff format`, then reconfirmed clean, and the affected tests re-run to confirm
  nothing changed behaviourally.
- CI's exact mypy invocation → `Success: no issues found in 33 source files` (unaffected; none of
  this round's files are in CI's mypy list).

No changes to Minors 4/5 (deferred to the whole-branch review, per the coordinator's message).
