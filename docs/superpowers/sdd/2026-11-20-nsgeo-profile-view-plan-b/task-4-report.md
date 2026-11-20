# Task 4 report: Time zero's line, drawn, dragged, written

Commit 0217a72 on nsgeo-profile-view (pushed).

## Implemented
- view_transform.py: `ViewTransform.snap_row` (row tops, clamp 0..n-1).
- profile_view.py: `set_cutoff(t, kind="end"|"start")`, `_cutoff_kind` (reset on clear), `_cutoff_text` (end: unchanged `cutoff_label`; start: "Time zero · sample k" at rest, "sample k · t ns" while dragging), start dims image top down to the line, drag snaps with `snap_row` for start. End path unchanged.
- profile_dock.py: `_show_cutoff` draws the row handle at `shown.t0 + sample*dt` (shown = `_shown_radargram`, the relabelled input); `_on_cutoff_dragged` dispatches a `row` handle to new `_write_row_handle` (row = round((t - t0)/dt); no write when equal; build_step + replace_step; identity check shared with the cutoff). With a valid Difference view up, a row handle draws no line (that record's rows are not the step's).

## Tests
New: pure snap_row x2; view x3 (dim/tag, snap+drag tag, default-kind guard); dock x5 (sample-mode-only line, not-first step, dock drag, clamp both ends, disabled, difference-on no line); new file test_plugin_time_zero_drag.py x6 (drag writes + form shows + unmoved no write, typed row, picture holds + line at 0 ns, Difference stays off + writes, campus FILE__007 seed 49, GPS FILE__010 seed 44). Neither real-data test skipped.

RED (source reverted, tests kept): pure `AttributeError: 'ViewTransform' object has no attribute 'snap_row'`; view `TypeError: ProfileView.set_cutoff() got an unexpected keyword argument 'kind'`; plugin/dock drags `AssertionError: assert 20 == 26`; dock line tests `comparison failed` (cutoff_ns None). The default-kind test is a guard (fails only on the kwarg).
GREEN: pure 434 passed; profile_view+time_zero_drag 140 passed; profile_dock 174 passed (180 with drag file); time_cutoff 13 passed unedited; difference_presets 20 passed; real_data 57 passed; ruff check and format clean.

## Disabled Time zero (Review Focus 2)
`_handle_row` ignores `enabled`, so a disabled time cutoff still shows its line; the row handle does the same. With the step disabled `zero_ns()` skips it, so the relabel is a no-op: the user sees the step's input on the source's own clock, uncropped, the line at the step's row on it (tag "Time zero · sample k"), and dragging writes the row while the step stays disabled. Drawn line and written row agree; nothing claims a crop. Pinned by test_a_disabled_time_zero_draws_its_line_as_the_cutoff_does.

## Self-review
Implemented before the tests were written (order slip); RED was then shown by reverting source. Test order not strictly test-first. Concern: while a drag is in progress the tag's time is on the shown clock (the old clock until release), as the brief specified.

## Fix round 1
Changes: item 1 view test `test_a_start_handle_dragged_off_either_edge_lands_on_row_0_and_the_last_row`; item 2 tag uses `round(t, 2) or 0.0` and `test_the_drag_tag_never_reads_minus_zero` (t0=-11.4745, dt=0.2165, k=53; the brief's -11.086/12 leaves no residue); item 3 private-state dock test replaced by plugin-level `test_a_valid_difference_view_on_time_zero_draws_no_row_line` (sample=0); item 4 exact drag-tag text; item 5 typed-row test asserts window held and line y moved 10 rows; item 6 `set_cutoff` rejects unknown kind (logs, hides), `cutoff_ns` docstring, `_cutoff_step` set after the Difference check; item 7 seed test (threshold 0.25: source row 40, dewowed row 33) and `cutoff_ns is not None` in the §4.13 migration pin.
RED: -0.00 test `'sample 53 · -0.00 ns' == 'sample 53 · 0.00 ns'`; unknown kind `assert 40.0 is None`. Mutants (reverted): drag always snap_cutoff -> `[0.5] == [0.0]`; drop the Difference check -> `assert 0.0 is None`; seed from source -> `assert 40 == 33`. Item 5's added assertions fail alongside the existing ones under any stale-line mutant; no separate mutant run.
GREEN: covering set (view, dock, time_zero_drag, time_cutoff, difference_presets, processing_dock) 426 passed; pure 434 passed; real data 57 passed; ruff clean.

## Fix round 2
Corrections to the round 1 notes above: (a) my claim that item 5's assertions fail under any stale-line mutant was false and was not run; on the line's own clock a stale and a moved line both read 0 ns, and the held window makes the y check follow from the window check. (b) The bottom-clamp is guarded: under the always-snap_cutoff mutant the top case fails first, which only made the bottom look unguarded.
Change: the typed-row test now asserts `dock._cutoff_step is` the stack's step after the commit, then emits `cutoff_dragged(rg.t0_ns + 33*rg.dt_ns)` and asserts `sample == 33`.
Mutant S2 (row branch skips the redraw when the step changed under the line): the test fails at the identity assertion (`_cutoff_step` is still the old TimeZero), before reaching `30 == 33`; reverted. Without the identity line it fails on `30 == 33`, as the re-reviewer showed.
GREEN: test_plugin_time_zero_drag.py + test_plugin_profile_dock.py 181 passed; ruff check and format clean.
