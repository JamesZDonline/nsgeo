# Task 1 report: A refusal that stays (#197)

Status: DONE (one concern, below).

## Implemented
- Core: `StepRefused(ValueError)` (message, index, title; pickles via `__reduce__`) in stack.py; `_ensure` and `result_bypassing` wrap `step.apply` through `_apply` (a StepRefused re-raises, another ValueError becomes StepRefused `from exc`). `difference()`'s own check and "no source" stay plain ValueError. Exported from `nsgeo.processing` (in sorted position) and added to the core README table, both pinned by test_public_api.py (found by the full core run).
- Processing panel: `REFUSAL_TEXT`, `REFUSAL_COLOUR`, `dock.warnings` (WarningsPanel between list and form), `refusal()`, `_check_refusal()` at the end of `rebuild()` and in `_on_line_loaded`; marks the row with the stop sign, red foreground, tooltip `name\n\nnote`; item edits under `_updating`. Reason gets exactly one final full stop.
- Profile panel: `STEPS_REFUSED_TEXT`, `PREVIEW_STEPS_REFUSED_TEXT`; `_take_down_picture` (extracted from the no-profiles branch, now shared) and `_show_steps_refused` (message set after the axes, uses `line_label`); called after `_render()` when `self.image is None` in `_show_line`'s profiles branch and in `_on_line_loaded`; never from `_on_stack_changed`.
- Guide paragraph updated.

## Tests and results
- Core: test_stack.py 46 passed (4 new); test_public_api.py 63 with test_stack passed after the export/README fix.
- Full core+pure: 1960 passed, 9 skipped, 19 xfailed, 2 failed (test_public_api: `__all__` order, README name). Fixed afterwards and re-ran those two files green; I did not repeat the 36-minute full run (nothing else changed in core).
- QGIS: test_plugin_processing_dock.py 47 passed (incl. the real FILE__007 test, run with `-m real_data`: passed, not skipped); test_plugin_profile_dock.py 123 passed; test_plugin_gain_strip.py 44 passed; test_plugin_difference_presets.py 12 passed; test_plugin_slices_width.py 11 passed.
- Lint: ruff check and format --check clean.

## TDD evidence
- Core RED: `pytest packages/nsgeo-core/tests/test_stack.py -k "refus or pickles or plain_value"` with the src reverted: `ImportError: cannot import name 'StepRefused' from 'nsgeo.processing.stack'`, as the brief expects. GREEN: 46 passed.
- Panel RED: src reverted, `qgis_tests.sh .../test_plugin_processing_dock.py -k refus`: `ImportError: cannot import name 'REFUSAL_COLOUR'`, as expected. GREEN: 13 passed (`-k "refus or note or real_one"`), then the whole file.
- Profile RED (behavioural, with only the two `_show_steps_refused` calls neutralised): test_opening_a_line..., test_a_preview..., and test_back_from_a_preview... each fail `assert <QImage> is None` (old picture still set). GREEN: 7 passed. 
- Guard test: mutation (call `_show_steps_refused` from `_on_stack_changed` whenever the stack refuses) makes `test_a_bad_edit_on_the_open_line_keeps_its_last_picture` fail; mutation reverted by hand. Note: the naive mutation "same `self.image is None` condition in `_on_stack_changed`" does NOT fail it (image is not None after a bad edit), so the docstring's mutation is the unconditional call.

## Files changed
- packages/nsgeo-core/src/nsgeo/processing/stack.py, __init__.py; packages/nsgeo-core/README.md; packages/nsgeo-core/tests/test_stack.py
- packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py, profile_dock.py
- packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py, test_plugin_profile_dock.py
- docs/guide/getting-started.md

Commits: a2bab7b, f8521ea, 362bb5d, 1677829.

## Self-review
- Existing test changed: `test_a_line_whose_velocity_cannot_be_resolved_still_lists_its_steps` used a migrate_fk on a synthetic line starting at -11 ns, which migration genuinely refuses (time zero not corrected), so the row now carries the stop sign. I put a `time_zero` step ahead and assert on row 1; the test's purpose (row survives an unresolvable velocity) is unchanged.
- Accidentally ran `ruff format` over docs/; reverted with `git checkout -- docs/superpowers`; the diff holds only intended changes.
- `_check_refusal` re-runs `stack.result()` (cached after the profile's own render) so no extra computation in steady state.

## Concerns
- Full core+pure not re-run after the two-line export/README fix (the 2 failing files re-run green).
- `rebuild()` is still not wrapped in try/except (as before); `_check_refusal` handles its own exceptions around `result()` only.

## Fix round 1
1. Width test: now shows the dock and processes events before both measurements, with a docstring naming the mutation. Mutant run (WarningsPanel labels with setWordWrap(False) and Preferred policy, reverted by `git checkout`): FAILED `assert 3609 == 458`. Real code passes.
2. `_check_refusal` is now a thin try/except (logs via `_log`) around the new `_paint_refusal`, which holds the previous body, so `rebuild` always reaches its `step_selected` emit.
3. Guide reworded: opening or hovering a line whose steps can't run shows the Profile message instead of the previous line's picture.
Tests: test_plugin_processing_dock.py 47 passed; test_plugin_slices_width.py 11 passed; ruff clean.
Commits: bbf562c, 61231e2, 2a4ad48.

## Fix round 2
1. Width test now runs in try/finally (hide, deleteLater, events). Focused run `-k test_the_note_never_widens_the_panel`: 1 passed, exit 0 (was segfault 139); `-k "never_widens or preset_that_refuses"` also exit 0; whole file 47 passed, exit 0.
2. Token widened to 120 x's. Mutations (each reverted with `git checkout`): Ignored policy lost alone: FAILED `assert 1111 == 458`; word wrap AND Ignored lost: FAILED `assert 3617 == 458`; word wrap lost alone: still passes (Ignored keeps the minimum small), so the docstring claims only the first two.
3. Guide paragraph re-wrapped at ~80 columns.
Commits: see git log (test(processing) and docs(guide)). ruff clean.
