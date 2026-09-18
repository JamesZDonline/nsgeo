# Task 15 report: profile dock bound to the session

## Status: DONE_WITH_CONCERNS

Implemented the M5 profile dock exactly as specified in the brief, with the
context-note deviations required, and stopped before the manual M5
checkpoint as instructed.

## Files

- Created `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modified `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (import, attribute,
  construction in `initGui`, teardown in `unload` -- matches the brief's
  Step 4 verbatim, plus the `self.profile_dock` lifecycle)
- Created `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py` (16
  tests: the brief's 8, plus 8 I added -- see "Additional tests" below)

## Deviations from the brief's literal code, per the "context the brief
cannot know" section

1. **`velocity_source` derives its answer from `resolve_velocity`'s own
   return value, instead of duplicating its precedence.** Rather than
   re-implementing "line override, then grid, then header" as a second
   `if/elif/else` cascade, `velocity_source` calls `resolve_velocity(line,
   grid)` once and compares the *object it returned* against
   `line.velocity`/`grid.velocity` by identity (`is`, not `==`).
   `resolve_velocity` returns `line.velocity`/`grid.velocity` directly (no
   copy) when one of those tiers applies, and only constructs a fresh
   `VelocityModel` for the header-fallback tier -- so identity is exactly
   the signal that tells you which tier actually ran, and it cannot drift
   from `resolve_velocity`'s actual behaviour no matter how its precedence
   changes later (GitHub issue #4). I chose "derive" over "pin with a
   test" because a derivation can't silently drift by construction, where
   a pinning test only catches drift if someone remembers to run it (per
   the brief's own note, two prior implementers on this branch reported
   clean sweeps a review then disproved).

2. **`ProfileView` is parented.** `self.view = ProfileView(body)`, and
   `body` is the dock's own central widget (`self.setWidget(body)`), so
   Qt's parent/child chain controls destruction order in production,
   mirroring `SurveyDock`. The new test file's own `ProfileDock` instances
   are still parentless top-level widgets (same as `SurveyDock`'s test
   fixture), so both fixtures (`opened`, `bare`) tear their dock down with
   `hide()` then `deleteLater()` on exit, the same pattern
   `test_plugin_profile_view.py`'s `make_view` fixture uses.

3. **Reused `nsgeo_qgis.log.log` as `_log`** -- no new logging code.
   Every session-signal slot and Qt-signal slot that does real work
   guards its own body with a broad `except Exception` and reports through
   `_log`, matching `survey_dock.py`/`profile_view.py`'s established
   pattern (their module docstrings' hazard note is copied into
   `profile_dock.py`'s own docstring, extended for this file's own new
   hazard: `Line.distance_along()` raising `ValueError` for a
   time-triggered line -- see `_safe_distance`).

4. **Did not wire `loader.loading_changed`** -- `profile_dock.py` never
   references `LineLoader` at all; the dock only reacts to
   `SiteSession`'s own `line_opened`/`line_loaded`/`stack_changed`/
   `trace_changed`/`selection_changed`, exactly as specified.

## A hazard I found and fixed beyond the brief's literal code

The brief's own `_render`/`_on_line_opened` pass `line.distance_along()`
straight to `ProfileView.set_axes` as the bottom-axis distance array.
`distance_along()` raises `ValueError` for a time-triggered acquisition
(`traces_per_metre <= 0`) -- exactly the case `SurveyDock`'s tree already
handles by marking such a line "unplaced" rather than omitting it or
crashing. Left as the brief wrote it, opening a time-triggered line would
raise inside `_on_line_opened` (a slot on `session.line_opened`), which is
swallowed by PyQt with no visible axes at all -- not a crash, but a
silent failure to satisfy "shows header-derived axes immediately," which
is the M5 requirement itself. Added `_safe_distance()` (catches
`ValueError`, returns `None`) and used it at both call sites; the
resulting fallback is a trace-index axis instead of a distance one --
mirroring `ProfileView`'s own no-distance-along behaviour. Covered by
`test_time_triggered_line_shows_a_trace_axis_instead_of_raising`.

## Additional tests beyond the brief's 8

The brief's 8 tests all passed on first implementation. Manual mutation
testing (below) turned up real, currently-untested branches, so I added:

- `test_velocity_label_falls_back_to_the_header_dielectric` -- the
  brief's own tests never exercise `resolve_velocity`'s third tier.
- `test_rerender_with_the_same_shape_keeps_the_current_zoom` /
  `test_switching_lines_does_not_inherit_the_previous_lines_window` --
  `_render`'s "keep the current pan/zoom across a re-render" logic ANDs
  two independent shape checks (`n_traces` match, `n_samples` match); the
  brief's own `time_zero` test only varies `n_samples`, leaving the
  `n_traces` half completely unexercised.
- `test_stack_change_on_a_different_line_is_ignored` /
  `test_line_loaded_for_a_different_line_is_ignored` -- `stack_changed`/
  `line_loaded` are emitted for whichever line changed, not only the one
  currently open (unlike `trace_changed`/`selection_changed`, which
  `SiteSession` itself already gates on the current key before emitting
  at all); nothing in the brief's suite ever mutates a *second* line.
- `test_hover_with_no_line_open_is_a_silent_no_op` (+ a local
  `message_log` fixture, copied from `test_plugin_profile_view.py`'s
  fixture of the same name, per that file's own precedent of duplicating
  it rather than centralising it in `conftest.py`).
- `test_set_difference_index_shows_what_a_step_actually_removed` --
  `set_difference_index`/the difference branch of `current_radargram`
  ships in this task (for Task 19 to wire a UI onto later) but had zero
  test coverage otherwise. Asserts the actual pixel data
  (`stack.source.data - stack.intermediate(0).data`), not just the label
  text, since the label is set independently of which radargram was
  actually returned.
- Strengthened the brief's first test to also check the trace count in
  the window title (`f"{line.n_traces} traces" in dock.windowTitle()`),
  which the original assertion never touched.

## Mutation testing

No mutation-testing tool is installed in this environment (checked:
neither `mutmut` nor `cosmic-ray` present, and per the "ask to install
tools" policy I did not install one silently). Followed this branch's own
established practice instead (visible in `profile_view.py`'s "m1".."m10"/
"I1".."I9" test comments from Task 14): manual, targeted mutations of
`profile_dock.py`, applied one at a time to a throwaway copy, with
`__pycache__` cleared and `PYTHONDONTWRITEBYTECODE=1` set before every run,
restoring the original file after each. 21 mutants total.

**15 killed** (by the final test suite, after the additions above):

| Mutation | Killed by |
|---|---|
| `velocity_source`: line-override check forced False | `test_velocity_label_names_its_source` |
| `velocity_source`: grid check forced False | `test_velocity_label_names_its_source` |
| `velocity_source`: grid label drops the id | `test_velocity_label_names_its_source` |
| `velocity_source`: header label drops epsr | `test_velocity_label_falls_back_to_the_header_dielectric` |
| `_render`: `keep_window`'s n_traces half forced True | `test_switching_lines_does_not_inherit_the_previous_lines_window` |
| `_render`: keep_window restore removed | `test_rerender_with_the_same_shape_keeps_the_current_zoom` |
| `_safe_distance`: catches `KeyError` instead of `ValueError` | `test_time_triggered_line_shows_a_trace_axis_instead_of_raising` |
| `_display_changed`: percentile label pinned to a constant | `test_display_gain_rerenders_without_touching_the_stack` |
| `_display_changed`: `with_display`/`set_image` calls dropped | `test_display_gain_rerenders_without_touching_the_stack` |
| `current_radargram`: difference branch disabled | `test_set_difference_index_shows_what_a_step_actually_removed` |
| `_configure_channels`: `setVisible(n > 1)` → `n >= 1` | `test_channel_combo_hidden_for_single_channel_files` |
| `_on_stack_changed`: key guard removed | `test_stack_change_on_a_different_line_is_ignored` |
| `_on_line_loaded`: key guard removed | `test_line_loaded_for_a_different_line_is_ignored` |
| `_hovered`: key-is-None guard removed | `test_hover_with_no_line_open_is_a_silent_no_op` |
| `_on_line_opened`: window title drops trace count | `test_opening_shows_axes_and_loading_before_samples_arrive` |

**6 honest survivors** (reported, not hidden):

1. `_render`: the `rg.n_traces == line.n_traces` guard before computing
   `distance` -- removing it (always compute) survives. No processing
   step in this codebase today changes trace count (only `time_zero`
   crops *samples*), so this branch is currently unreachable from any
   real stack, the same character as `ProfileView`'s own documented C1c
   guard ("not reachable from real data today... but is a public entry
   point... so it enforces its own contract rather than trust every
   future caller to"). I judged a contrived test forcing a mismatched-
   shape radargram through private state not worth writing for a branch
   with no live path to it; flagging it here instead.
2. `_on_trace_changed`: key guard removed -- survives. `SiteSession.
   set_trace` itself already gates `trace_changed` to `key ==
   self._current_key` before ever emitting, and the dock's own `_key`
   tracks that same value via `line_opened`, so this signal can only ever
   arrive already matching. Defense-in-depth against SiteSession's own
   invariant, not a currently reachable path.
3. `_on_selection_changed`: key guard removed -- survives, same reasoning
   as #2 (`SiteSession.set_selection` gates identically).
4. `_channel_changed`: guard removed -- survives. The channel combo is
   only visible/interactive while a multi-channel line is open, so a
   `currentIndexChanged` with `self._key is None` has no live path today.
5. `_range_selected`: guard removed -- survives, same reasoning as #4
   (`ProfileView.range_selected` only fires from a completed drag on an
   image, which requires an open line).
6. `_refresh_velocity`: the `not self.session.is_open` half of its guard
   removed -- survives. The method's own `except KeyError: return`
   already produces the identical outcome whenever `self._key` doesn't
   resolve, so this half is provably redundant with the exception
   handler immediately below it, not a distinguishable behaviour.

After every mutation, the file was restored and diffed byte-for-byte
against the pre-mutation copy (`diff` reported no differences) before
continuing.

## Test results

**Pure tier** (`.venv`, numpy-only):
`.venv/bin/python -m pytest packages/nsgeo-core packages/nsgeo-qgis/tests/pure -p no:xonsh -q`
→ **333 passed, 2 skipped** (the 2 skips are pre-existing, unrelated:
`test_schema.py`'s `bandpass`/`gain_curve` "required parameters by
design" cases).

**QGIS tier** (`.venv-qgis`, `QT_QPA_PLATFORM=offscreen`):
`.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -p no:xonsh -q`
→ **212 passed** (207 pre-existing + 5 net new files' worth from this
task's 16 new tests replacing nothing).

**Individual-test sweep** over the new file (`test_plugin_profile_dock.py`,
each test run alone, `QT_QPA_PLATFORM=offscreen`, `-p no:xonsh`): **all 16
exit 0 individually.**

**Boundary test** (`packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`,
run under `.venv`): **4 passed** -- `profile_dock.py` imports only
`Radargram`/`StepStack` from `nsgeo.processing` (both allow-listed), uses
`qgis.PyQt` exclusively, and the package `__init__` still imports no
`qgis` at module level.

**Ruff**: `ruff check .` → all checks passed. `ruff format --check .` →
83 files already formatted (no diffs).

**CI mypy line** (exact invocation from `.github/workflows/ci.yml`):
`mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
→ **Success: no issues found in 24 source files** (`profile_dock.py` is
not in this file set -- it imports `qgis.*`, same as every other dock,
and CI's own mypy line does not type-check any Qt-importing module).

## Concerns (why DONE_WITH_CONCERNS, not DONE)

- The 6 honest mutation survivors above are all, by my own analysis,
  currently-unreachable defense-in-depth given today's call graph -- but
  that analysis is mine alone, and a reviewer may judge one of them
  reachable by a path I didn't consider (particularly `_on_trace_changed`/
  `_on_selection_changed`'s reliance on `SiteSession`'s own gating: if a
  future change ever lets two `ProfileDock`s share one `SiteSession`, or
  lets the dock's `_key` and the session's `_current_key` diverge even
  briefly, these guards would start mattering for real).
  `set_difference_index`/the difference-view feature is genuinely inert
  in this task (no UI calls it yet) beyond the one test I added for it;
  Task 19 is where it gets real exercise.
- I added 8 tests beyond the brief's 8 based on my own mutation-testing
  findings, not on additional instructions. I judged each one against a
  real, demonstrable gap (see the mutation table), not just to inflate
  coverage, but that judgment call is mine to defend in review.
- The M5 manual checkpoint (real QGIS, mouse-driven) was deliberately not
  attempted, per instructions.

---

## Fix Round 1

Reviewed commit `2849534` against `task-15-review.md` (2 Critical, 6
Important, 8 Minor -- the 8 Minors parked to the final whole-branch
review per the coordinator's instruction). Fixed C1, C2, I1, I2, I3, I4,
I5, I6. Did not touch any of the 8 Minors.

### C1 -- cursor and selection surviving a line switch

Fixed by resetting both in `ProfileDock._open`, right after `self.image =
None` and before either branch (profiles loaded or not): `self.view.
set_cursor(-1)` and `self.view.clear_selection()`. This runs on every line
open, unconditionally, so it can't be skipped by which branch `_open`
takes. Added `test_switching_lines_clears_the_cursor_and_selection`,
reproducing the review's own concrete input (`set_trace(key, 120)`,
`range_selected.emit(5, 9)`, then opening a second line) almost verbatim.

### C2 -- the three central M5 observables were unpinned

Added the five assertions the review wrote out verbatim to
`test_opening_shows_axes_and_loading_before_samples_arrive`: `dock.view.
transform.n_samples`/`t0_ns` against the header directly (not a value
the dock computed), `dock.view._velocity is not None and
dock.view.depth_tick_labels()` (using Task 14's `depth_tick_labels()` test
hook, previously unused anywhere), `dock.view._distance is not None`, and
`dock.view._image is not None` after `set_profiles`. No production code
changed here -- the behaviour was already correct; only the test was
silent about it.

### I1 -- plugin.py's Step-4 block was untested

No production change (the review verified the code itself is correct).
Added two assertions to `test_plugin_survey_dock.py`'s existing
`test_plugin_wires_the_dock_and_file_actions`: `plugin.profile_dock in
fake_iface.docks` after `initGui()`, and `fake_iface.docks == [] and
plugin.profile_dock is None` after `unload()`.

### I2 -- Fit, 1:1, and the pick relay were wired but unproven

Added three tests: `test_fit_button_restores_the_full_extent_after_a_zoom`,
`test_one_to_one_button_sets_a_trace_per_pixel_window` (needed a second,
much wider synthetic line -- the `opened` fixture's 240-trace line is
narrower than the view, so 1:1 clamps back to fit and the two buttons
would be indistinguishable, exactly the "1:1 looks like a no-op" behaviour
the review measured on the real M5 data), and
`test_pick_requested_relays_key_trace_and_time`.

### I3 -- the identity trick was weaker than `==`, and the docstring overclaimed

Changed `velocity_source`'s two comparisons from `is` to `==`, and turned
the header-tier fallback from an unconditional `return` into an explicit
check (`if resolved == VelocityModel.from_dielectric(...): return ...
return "unknown source"`). Rewrote the docstring to state the actual
guarantee: reordering the three known tiers is still always named
correctly; an *added* tier now reports "unknown source" instead of
mislabelling itself as the header tier.

Added two tests. `test_velocity_label_reports_unknown_source_when_no_known_tier_matches`
monkeypatches `resolve_velocity` to return a model matching none of the
three candidates (issue #4's "added a fourth tier" scenario), pinning the
new fallback. `test_velocity_label_recognises_an_equal_but_different_velocity_object`
monkeypatches `resolve_velocity` to return `dataclasses.replace(grid.
velocity)` -- an equal-value, different-object copy -- and asserts the
label is still "Grid A"; this is the one that actually discriminates `is`
from `==` (the review's own reconciliation notes this can only be shown by
making `resolve_velocity` return a copy, since it never does so today).
Monkeypatching the name as imported into `profile_dock.py` reproduces
this without mutating `nsgeo/velocity.py` itself, which is out of this
task's scope.

### I4 -- survivor #6's justification was wrong

Corrected the claim (no source comment previously existed for this
guard; the wrong "provably redundant" claim was only in the previous
report, not the code) by adding a comment on `_refresh_velocity` stating
the real reason: `ProjectError` is not a `KeyError`, so the `not self.
session.is_open` half is behaviourally distinguishable from the exception
handler (silent return vs. a logged Critical), even though nothing in
today's call graph reaches that state. Also added a test,
`test_refresh_velocity_returns_silently_once_the_site_is_closed`, which
forces the otherwise-unreachable state directly (`session.close_site()`
then `dock._key = key`) and asserts nothing is logged.

### I5 -- two brief-written tests passed vacuously

`test_closing_the_site_clears_the_view` now calls `session.set_profiles`
before `close_site()`, with a sanity assertion (`dock.image is not None`)
that there is something to clear. `test_cursor_and_selection_follow_the_
session_and_vice_versa` gained the missing session -> view direction for
the selection (`session.set_selection(key, 40, 45)`), using *different*
bounds than the view -> session step earlier in the same test: reusing
`(5, 9)` would hit `SiteSession.set_selection`'s own no-op-on-unchanged-
value guard and never re-emit, making the added assertion pass vacuously
for exactly the reason this fix exists to close.

### I6 -- `_pick` was the one unguarded slot; `_refresh_velocity`'s tail sat outside its try

`_pick` now guards its body the same way every other slot in this file
does. One honest caveat, verified directly rather than assumed: a plain
script (`signal.emit()` with a raising connected slot, both plain
`QObject`s, direct connection) confirms PyQt swallows a downstream
subscriber's exception at the point that subscriber is invoked -- it
never reaches back into `_pick`'s own `try`. So this guard cannot catch a
future picking dock's own bug escaping through `pick_requested`; it only
protects logic inside `_pick` itself (there is none today beyond the
`emit()` call). Documented this precisely in a comment rather than
implying the guard does something it empirically does not. No test claims
otherwise -- `test_pick_requested_relays_key_trace_and_time` only proves
the wiring, not exception containment.

`_refresh_velocity`'s two view-mutating statements moved inside the `try`.
Checked whether this is an observable behaviour change: it is not --
both `except` clauses already had their own explicit `return`, so the
tail could never previously run after either exception path regardless of
its indentation. This is a structural fix for the stated "guards its own
body" rule, not a live bug; no mutation distinguishes the two forms, and
none is claimed.

### Mutation verification (round 1)

Same method as before: `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared
before/after each mutant, file restored and diffed byte-identical after
every run.

`profile_dock.py`, run against `test_plugin_profile_dock.py` -- **8/8
killed**:

| Mutation | Killed by |
|---|---|
| C1: drop `self.view.set_cursor(-1)` | `test_switching_lines_clears_the_cursor_and_selection` |
| C1: drop `self.view.clear_selection()` | `test_switching_lines_clears_the_cursor_and_selection` |
| C2 (reviewer's #1): drop `view.set_image(...)` in `_render` | `test_opening_shows_axes_and_loading_before_samples_arrive` |
| C2 (reviewer's #2): drop `view.set_velocity(...)` in `_refresh_velocity` | `test_opening_shows_axes_and_loading_before_samples_arrive` |
| C2 (reviewer's #3): `header.position_ns` -> `0.0` | `test_opening_shows_axes_and_loading_before_samples_arrive` |
| I3: header fallback reverts to a blind `return` | `test_velocity_label_reports_unknown_source_when_no_known_tier_matches` |
| I3: `==` reverted to `is` (line/grid checks) | `test_velocity_label_recognises_an_equal_but_different_velocity_object` |
| I4: drop the `is_open` half of the guard | `test_refresh_velocity_returns_silently_once_the_site_is_closed` |

`plugin.py`, run against `test_plugin_survey_dock.py` -- **4/4 killed**:

| Mutation | Killed by |
|---|---|
| Delete the whole `ProfileDock` construction block in `initGui` | `test_plugin_wires_the_dock_and_file_actions` |
| Drop `self.docks.append(self.profile_dock)` | `test_plugin_wires_the_dock_and_file_actions` |
| Drop `self.profile_dock = None` in `unload` | `test_plugin_wires_the_dock_and_file_actions` |
| Delete the whole dock teardown loop in `unload` | `test_plugin_wires_the_dock_and_file_actions` |

For C2, verified with the reviewer's own three mutations specifically
(rows 3-5 of the table above), not variants of my own, per the
coordinator's instruction.

No honest survivors from this round's own mutants. The 6 survivors from
round 0 (defense-in-depth guards) were left untouched, since the review
agreed with 5 of the 6 conclusions (disagreeing only with #6's reasoning,
fixed above as I4) and explicitly said not to write tests that would have
to forge the divergence through private state.

### Test results (post-fix)

**Pure tier** (`.venv`): `.venv/bin/python -m pytest packages/nsgeo-core
packages/nsgeo-qgis/tests/pure -p no:xonsh -q` -> **333 passed, 2 skipped**
(same 2 pre-existing, unrelated skips as before).

**QGIS tier** (`.venv-qgis`, offscreen): `.venv-qgis/bin/python -m pytest
packages/nsgeo-qgis/tests/qgis -p no:xonsh -q` -> **219 passed** (212
baseline before this round + 7 net new: 6 new tests in
`test_plugin_profile_dock.py`, 0 net-new in `test_plugin_survey_dock.py`
since that file's test count didn't change, only its assertions did --
212 + 7 = 219; `test_plugin_profile_dock.py` alone now has 23 tests, up
from 16).

**Individual-test sweep** over `test_plugin_profile_dock.py` (all 23,
each run alone, `QT_QPA_PLATFORM=offscreen`, `-p no:xonsh`): **all exit 0
individually.**

**Boundary test**: 4 passed, unchanged.

**Ruff**: `ruff check .` -> all checks passed. `ruff format --check .` ->
83 files already formatted.

**CI mypy line** (unchanged invocation): **Success: no issues found in 24
source files** (neither `profile_dock.py` nor the test files are in this
set, same as before).

### Concerns carried into this round

- The `_pick` guard (I6) is applied exactly as instructed but is, by my
  own direct verification, unable to catch what the review's own
  motivating scenario describes (a future picking dock's exception
  escaping through `pick_requested`) -- PyQt swallows that before it ever
  reaches `_pick`'s `try`. I kept the guard (it costs nothing and matches
  the file's stated rule) and documented the limitation rather than claim
  it does more than it does. Flagging this explicitly in case my empirical
  read of PyQt's exception semantics here is itself wrong.
- The `_refresh_velocity` tail-inside-try change (also I6) has no
  behavioural effect today (both exception branches already returned
  early) -- it is a pure structural/style fix, not a bug fix, and I did
  not manufacture a test to pretend otherwise.
- The 6 round-0 survivors (defense-in-depth guards `_on_trace_changed`/
  `_on_selection_changed`/`_channel_changed`/`_range_selected`, plus the
  `_render` n_traces-vs-line.n_traces guard) are unchanged from round 0;
  the review's slot-ordering argument (Tasks 16/18 appending new
  `line_opened` subscribers after `ProfileDock`) is the correct reason to
  keep two of them, and I have not added tests for any, per the review's
  explicit instruction not to forge the divergence through private state.
