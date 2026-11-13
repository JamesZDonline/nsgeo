# Task 3 — fix round 1 (FIX_BASE 0214fd3)

The opus task review confirmed the behaviour is correct and well built (Refiner use, land order, P5/P6/P8,
thread safety, copy verbatim, done()). Fix the following, append a "## Fix round 1" section to task-3-report.md
(each item: change, file:line, covering test, command, output), commit and push.

## Important
1. Review Focus 1, second half, is untested (`test_plugin_edit_lines_measure.py:245`). The plan says this focus
   pins "results land in the rows selected at the start (P6, P8)". Add a gated test: select rows 0–3, press
   Measure, `spin_until(canned.seen)`; change the selection (clear it, then select rows 4–5); release and finish;
   assert rows 0–3 hold their canned values and rows 4–5 are untouched. Show (scratch copy outside the worktree,
   or a temporary local edit you revert before committing — never committed) that changing `_land` to use
   `self.selected_keys()` makes it fail.

## Spec
2. `docs/guide/getting-started.md`: the Measure paragraph must come AFTER the destagger paragraphs, i.e. after
   "Fit a grid's lines before you destagger them…", not between "Stagger shows…" and it.

## Minor (all included)
1. `edit_lines_dialog.py:535`: `JobLine.label` is always "" (built from the snapshot placement whose label is
   None). Fill it from `self._label_of(key)`.
2. P5 rounding untested: a canned value such as 0.12345 must land as 0.123 in the row and in the box.
3. Untested copy paths: the Error copy (canned function raises `RuntimeError("boom")` → status
   `Could not measure: RuntimeError: boom. Nothing was changed.` or whatever exact form the constraints give for
   {message} — check `_describe` in refine.py); the No-targets copy (`measure()` with nothing selected); the
   progress strings (a gated run shows the "comparing lines" progress copy once `canned.seen` is set).
4. Review Focus 2 covers "closed" but not "replaced": add close + reopen of the same site mid-run → Site-changed
   copy, nothing written.
5. `test_plugin_edit_lines_measure.py:60`: the noise seed uses `hash(name)` (varies with PYTHONHASHSEED). Use a
   stable seed (the line index). Also inject a known stagger into the shared-field synthetic lines so the
   real-measure tests do not depend on the accidental 1/60 m placement offset (+0.010) to see "filled" rows;
   assert the measured grid value is near the injected one.
6. Ruling 9: when no line could be read (axes empty because every file is unreadable), the summary starts with
   `Could not measure: no line could be read. Nothing was changed.` followed by the not-measured group. Add it to
   `measure_summary` and a pure test.
7. The close test (`:229`) releases the gate before `reject()`, so it can't tell "close stopped the run" from
   "close waited for it". Use a canned function that loops until `should_stop()` (as
   `tests/qgis/test_plugin_refine.py::test_shutdown_joins_the_worker` does) so reject() must cancel it, and keep
   the Ruling 3 thread-count check.
8. `test_two_axes_fill_each_row_from_its_own_axis` (`:335`): drop the unused `make` fixture, reuse `_open`'s site
   building instead of duplicating it, move the stray pure `box_value` assertion (`:372`) into the pure file.
   Replace the local `spin_until` wrapper with a plain import.
9. P12 cap is tested only for the Own values group; add a case for a "; "-joined group (more than 6 lines that
   change partway or have no clear match).
10. `_label_of` repeats the label expression that `_drop_note` and `fit_to_edges` inline; make those two call it.

Not for this round (Ruling 10): Stop dropping the run's reads — noted for the walkthrough.

## Verification
- the two QGIS files + `test_plugin_edit_lines_dialog.py` (command as before), then the combined core+pure run
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
  (you did not re-run it after the boundary-import fix last time — do it this time and paste the tail);
- ruff check + format --check; mypy with the CI list.
- Commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; push; confirm with
  `git ls-remote origin refs/heads/nsgeo-auto-destagger`.
