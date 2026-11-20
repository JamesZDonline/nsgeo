# Task 17 report — Schema-driven parameter form and the add-step dialog

## Fix report — review round 2

Re-review verdict: all round-1 findings addressed, no new Critical/Important breakage. Round 2 was
six small items (item 1 touches `nsgeo-core`), closing the task with no further review round.

The re-reviewer verified two things I hadn't independently checked, and corrected one claim before I
acted on it:

- **Verified the identity proxy against core, not on faith**: `StepStack.set_enabled` and `move` both
  carry the *same* step object forward (`self._entries[index] = (step, bool(flag))` re-uses `step`;
  `move` only repositions the `(step, enabled)` tuple, never rebuilds it) — so an enable-toggle or a
  reorder can never be misread by `_show_form`'s identity check as "a different step arrived here".
  Only append/insert/remove/replace put a genuinely different object at an index. That's what makes
  "identity means content changed" a sound invariant rather than one that merely happened to hold in
  the cases I'd traced by hand.
- **Verified the allowlist widening is safe**: `Step` is a `typing.Protocol` with no implementation to
  leak across the boundary, and it could not have been hidden behind `TYPE_CHECKING` instead, because
  `test_plugin_boundary.py`'s `ast.walk` descends into a `TYPE_CHECKING` block's body the same as any
  other — so that option was never actually available, not merely undesirable.
- **Corrected a claim**: the re-reviewer's own first pass said a NaN `low_mhz` makes `Bandpass` "produce
  all-NaN data". Re-run directly, that's wrong — `low_mhz=nan, high_mhz=600` raises nothing and
  produces *different, finite, arbitrary* output, not all-NaN. I did not re-derive this myself (the
  correction arrived already verified); I used the corrected framing in item 3's comments and test
  docstrings below rather than the original, wrong one.

### Item 1 — pin `nyquist_mhz`'s constant

Added `test_nyquist_mhz_pins_the_constant` to `packages/nsgeo-core/tests/test_processing_base.py`:
`assert nyquist_mhz(0.2) == 2500.0`. Confirmed by direct experiment (not the re-reviewer's word alone)
that this is a real gap, not a nitpick: substituting `550.0` for `500.0` in `nyquist_mhz` leaves every
*other* core test passing (288 passed, 2 skipped) and only the new test catches it — see RED evidence
below. `nyquist_mhz` is imported into the test module from `nsgeo.processing.base`, matching the
existing import style in that file.

### Item 2 — test m7 with a cheaper method than I judged possible in round 1

Round 1, I judged that testing two independent curve-kind params would mean registering a fake step
in the global `_REGISTRY`, and skipped it to avoid polluting `available_steps()` for the rest of the
test session. The re-reviewer found the cheaper path I'd missed: `param_form.py` does
`from nsgeo.processing import ... get_step`, binding `get_step` into its own module namespace — so
`monkeypatch.setattr(nsgeo_qgis.ui.param_form, "get_step", lambda name: FakeTwoCurveStep)` redirects
only `set_step()`'s own lookup, never touching `_REGISTRY` at all. Added
`test_curve_values_are_kept_independent_per_parameter`: a fake two-curve schema, `set_step()` with
both curve values supplied, and `values()` (no `build()` needed) asserting both keys keep their own
value. Ran the reversion (`_curve_values` back to a single shared `_curve_value`) — see RED evidence
below — confirming `curve_a`'s expected value gets silently overwritten by `curve_b`'s, exactly the
failure mode this was meant to catch.

### Item 3 — reject non-finite numbers, for the corrected reason

`_parse_number` now checks `math.isfinite(...)` on both the float path and the int-kind's
whole-number probe (`float("nan")`/`float("inf")` both succeed in Python but are not valid values for
a physical parameter), raising `"{label} must be a finite number, got {text!r}"`. Comments and the two
new tests (`test_non_finite_float_is_rejected_not_silently_accepted`,
`test_non_finite_int_is_rejected_not_silently_accepted`) use the *corrected* justification the
re-reviewer supplied — NaN slips past a step's own validation and produces different, finite,
arbitrary output, not all-NaN data — rather than the original, wrong claim. Ran both reversions (see
RED evidence below).

### Item 4 — `ParamForm._updating` becomes a depth counter

Changed `self._updating = False`/`True` to `= 0`/`+= 1`/`-= 1` in both `clear()` and `set_step()`,
matching `ProcessingDock._updating`'s existing pattern and rationale: `set_step()` already calls
`clear()` before taking its own guard, so the two are nested within a single call today, and only
happen to be harmless because of that specific ordering. Added
`test_updating_guard_survives_a_nested_clear`, mirroring Task 16's
`test_updating_guard_survives_a_nested_rebuild` for `ProcessingDock`: mark the guard up, run a real
`set_step()` through it, assert it's still up afterward. Ran the reversion (bool instead of counter in
`clear()`) — see RED evidence below.

### Item 5 — `match=` on the bare `pytest.raises(ValueError)`

`test_set_value_reports_an_unknown_combo_choice_instead_of_guessing` now asserts
`match="is not one of this field's choices"`, so an unrelated `ValueError` (e.g. a typo introduced
elsewhere in `set_value`) can no longer satisfy it.

### Item 6 — strengthen the C1 backstop to identity

`_on_form_committed`'s second line of defence was `current.name != self.form.step_name`, which cannot
catch a same-name desync (`[dewow_a, dewow_b]`, remove row 0 — both share the name `"dewow"`).
Replaced it with `current is not self._shown_step` — strictly stronger, since `_show_form` keeps
`self.form.step_name == self._shown_step.name` as an invariant, so anything the name check would have
caught, the identity check also catches, plus the same-name case it couldn't. No new test: as the
review noted, nothing reaches this path today (`_show_form`'s own identity check already prevents the
desync from being visible), so there's no live scenario to reproduce without contriving one — this is
pure defence-in-depth for Task 18's external `replace_step` caller, same as m11's `clear()` guard in
round 1 had no live trigger either.

### TDD evidence — every reversion actually run this round

All applied to the real file, run, and restored from a scratch copy (verified byte-identical with
`diff` before moving to the next); never `git checkout --`.

**Item 1** — `nyquist_mhz` returning `550.0 / dt_ns` instead of `500.0 / dt_ns`:
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests -q
```
```
FAILED packages/nsgeo-core/tests/test_processing_base.py::test_nyquist_mhz_pins_the_constant
assert 2750.0 == 2500.0
1 failed, 287 passed, 2 skipped in 0.71s
```
(confirms the re-reviewer's "degenerate probe" point directly: every *other* test, including every
`Bandpass` Nyquist-guard test, still passes under the wrong constant)

**Item 2** — `_curve_values` reverted to a single shared `_curve_value` at every call site:
```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py::test_curve_values_are_kept_independent_per_parameter -q -p no:xonsh
```
```
AssertionError: assert {'curve_a': [..., [1.0, 5.0]]} == {'curve_a': [..., [1.0, 5.0]]}
Differing items:
{'curve_a': [[0.0, 5.0], [1.0, 5.0]]} != {'curve_a': [[0.0, 0.0], [1.0, 0.0]]}
```

**Item 3 (float)** — removed the `math.isfinite(value)` check on the float path:
```
FAILED ...::test_non_finite_float_is_rejected_not_silently_accepted
assert ([])
```

**Item 3 (int)** — removed the `math.isfinite(probe)` check on the int-kind whole-number probe:
```
FAILED ...::test_non_finite_int_is_rejected_not_silently_accepted
assert (["Sample must be a whole number, got 'inf'"] and 'finite' in "sample must be a whole number, got 'inf'")
```

**Item 4** — `clear()`'s guard reverted to `= True`/`= False`:
```
FAILED ...::test_updating_guard_survives_a_nested_clear
assert 0
 +  where 0 = <ParamForm object>._updating
```

### Full verification, final state

Per-tier counts, exactly as printed:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
257 passed in 57.95s
```
(253 baseline + 4 new: non-finite float, non-finite int, curve independence, nested-clear guard)

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
334 passed, 2 skipped in 0.96s
```
(333 baseline + 1 new: `test_nyquist_mhz_pins_the_constant`)

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed in 0.18s
```
(unchanged — item 1 adds no new import to either plugin file, only a core test)

```
.venv/bin/python -m ruff check .
All checks passed!
.venv/bin/python -m ruff format --check .
88 files already formatted
```

```
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

### Files changed (this round)

- `packages/nsgeo-core/tests/test_processing_base.py` (item 1)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py` (items 3, 4)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (item 6)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py` (items 2, 3, 4, 5 — new/changed tests)

### Concerns

None. All six items addressed within round-2 scope. `import_dialog.py`'s own
`float(item.text().replace(",", "."))` (the same comma-ambiguity this task's `ParamForm` no longer
does) was explicitly parked to the final review by the coordinator and left untouched.

---

## Fix report — review round 1

Review verdict: 1 Critical, 2 Important, 8 Minor. All fixed this round.

### CRITICAL 1 — `_shown` never invalidated on a same-row, different-step change

**The bug.** `_shown` keyed only on `(key, row)`. Removing the row above the current selection (or
inserting one at/above it) leaves `row` unchanged while a genuinely different step now sits there —
`_show_form` saw an unchanged `(key, row)` and skipped rebuilding, leaving the form showing a step
that had just been replaced or destroyed underneath it. The next edit through that stale form wrote
its params onto the *new* step at that index, silently destroying it and resurrecting the old one.

**The fix**, exactly as specified: `ProcessingDock` now also tracks `self._shown_step`, the step
*object* last shown (not just its row). `_show_form` skips rebuilding only when both the `(key, row)`
and the step's identity match what's already on screen; this works precisely because the project
never mutates a step in place (`build_step(...)` always produces a new instance), so identity is a
sound proxy for "is this the exact content already displayed." `_on_form_committed` sets
`self._shown_step = new` *before* calling `session.replace_step`, so the `stack_changed` echo this
triggers reports that same object back and is correctly recognised as a no-op. Added the second line
of defence too: `_on_form_committed` now bails if `entries[row][0].name != self.form.step_name`,
turning any residual desync into a no-op rather than a corruption.

I traced the two sibling paths the reviewer named without a new test each, per the review's own
guidance (they're the same fix, just different triggers):
- `insert_step` at/above the selected row: same mechanism as `remove_selected` — the object at
  `entries[row]` changes identity, the identity check catches it, the form is correctly refreshed.
- External `replace_step` on the current key+row (Task 18's gain-strip path): same mechanism — a
  different object appears at the same row, the identity check refreshes the form to show it instead
  of reverting it.

Also confirmed the three paths the review said were *not* siblings really aren't, by re-reading each:
`move_selected` calls `session.move_step` then its own trailing `setCurrentRow(dst)`, which always
fires a real, final `_show_form(dst)` after the transient mid-move one; drag reorder likewise ends
with Qt's own current-index-follows-the-moved-row behavior; `set_channel` only replaces
`stack.source`, never `entries`; site close routes through `_show_form`'s `key is None` branch, which
was already unconditionally correct.

**m9 alongside this**: `add_step_with_dialog`'s dialog is now wrapped in `try/finally: dialog.deleteLater()`
regardless of accept/reject/exception, since `parent=self` keeps Qt from segfaulting on a parentless
widget but also means the dialog would otherwise live on, hidden, for the dock's whole lifetime.

### IMPORTANT 2 — `test_add_step_with_dialog_cancel_adds_nothing` didn't test what it claimed

Fixed the driver to fill both required fields *before* rejecting
(`lambda d: (d.form.set_value(...), d.form.set_value(...), d.reject())`, written as a named function
for clarity), so `result_step()` would return a real, buildable `bandpass` step and only the
`Accepted` gate in `add_step_with_dialog` is what keeps the stack empty. Ran the reviewer's own
reversion (dropping the `if dialog.exec() == Accepted:` gate) directly — see RED evidence below — and
confirmed the *old* test text passed against it (proving the reviewer's finding) and the *new* test
text fails against it (proving the fix pins the right thing).

### IMPORTANT 3 — added the positive complement

`test_removing_the_selected_row_shows_the_step_that_slides_into_it`: adds `dewow` (row 0) and
`gain_agc` (row 1), selects row 0 (form shows `dewow`), calls `remove_selected()` (deletes the
selected row, so `gain_agc` slides up to fill row 0 while `currentRow` stays a valid 0), and asserts
`dock.form.step_name == "gain_agc"` and `set(dock.form.editors) == {"window_ns", "target", "eps"}`.
Ran directly against the pre-fix guard (`(key, row)` comparison only) — see RED evidence below —
confirming it fails exactly as the review predicted (`'dewow' == 'gain_agc'`).

### Minors — all addressed

- **m4**: added `nyquist_mhz(dt_ns) -> float` to `nsgeo.processing.base` (pure arithmetic, `500.0 /
  dt_ns`), exported it from `nsgeo.processing.__init__`, and pointed both `Bandpass.apply` and
  `add_step_dialog.header_facts` at it instead of each computing it separately. Had to also add
  `"Step"` and `"nyquist_mhz"` to `ALLOWED_FROM_PROCESSING` in
  `tests/pure/test_plugin_boundary.py` — this repo has a *second*, hand-maintained allowlist of names
  the plugin may import from `nsgeo.processing`, separate from what core chooses to export, and the
  boundary test caught both new imports immediately (see RED evidence below). Confirmed boundary
  still passes at 6.
- **m6**: `AddStepDialog._validate`'s `step.apply(probe)` now catches `Exception`, not just
  `ValueError` — added a comment explaining why (a slot; `apply` is arbitrary step code with no
  promise of only raising `ValueError`) and a new test that forces a `RuntimeError` via
  `monkeypatch.setattr(Bandpass, "apply", boom)` and confirms `message`/`ok_button` are updated instead
  of the exception being silently swallowed by Qt.
- **m7**: `ParamForm._curve_value` (one shared slot) became `self._curve_values: dict[str, Any]`, keyed
  by `spec.name`, everywhere it's read or written (`_make_editor`, `is_complete`, `values`). No step in
  the current registry has two curve params, so I didn't invent a fake registered step to exercise
  this directly (that would pollute the global step registry for the rest of the test session); fixed
  and re-verified by reading through every call site, matching how the review itself flagged this as
  latent rather than reproducible today.
- **m8**: `ParamForm.build()` and `AddStepDialog.result_step()` now return `Step | None` instead of
  `Any` (`Step` imported from `nsgeo.processing`, already exported there).
- **m9**: see CRITICAL 1 section above.
- **m10**: three separate fixes in `ParamForm`, each with its own new test:
  - Dropped `.replace(",", ".")` entirely — `"1,000"` and a European `"1,5"` can't be told apart from
    the text alone, so silently converting every comma to a dot was a guess the rest of this form
    never makes elsewhere; a comma is now reported as bad input like any other unparseable text.
  - Split parsing into `_parse_number`: an `int`-kind field that fails `int(text)` now tries
    `float(text)` before giving up, and if *that* succeeds, reports "must be a whole number" instead of
    the misleading "is not a number".
  - `set_value` on a `QComboBox` now raises `ValueError` when the requested choice isn't found,
    instead of `max(0, findData(...))` silently landing on index 0.
- **m11**: `clear()`'s body now runs inside its own `self._updating = True/False` guard (matching
  `set_step()`'s existing pattern), so a widget destroyed mid-`removeRow()` firing a stray
  `currentIndexChanged` can't reach `_on_edited`/`commit` against a half-cleared `self.editors`/
  `self._specs`. No live trigger found (matching the reviewer's own note), so this is a defensive fix,
  verified by reading rather than a dedicated new test — the two curve-column tests above already
  cover the visible behaviour of `clear()`/`set_step()`, so this only guards against an event ordering
  I couldn't get Qt to actually produce.

### TDD evidence — every named reversion actually run this round

All of these were applied to the real file, run, and reverted from a scratch copy (never
`git checkout --`); each shows the exact assertion failure, not a guess.

**CRITICAL 1** — dropped the `step is self._shown_step` half of `_show_form`'s guard:
```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q -p no:xonsh
```
```
1 failed, 13 passed in 0.81s
FAILED ...::test_removing_the_selected_row_shows_the_step_that_slides_into_it
AssertionError: assert 'dewow' == 'gain_agc'
```

**IMPORTANT 2** — dropped the `Accepted` gate in `add_step_with_dialog` (`dialog.exec()` called but
never checked, `append_from_dialog` called unconditionally), run against the *fixed* test (the one
that fills the form before rejecting):
```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py::test_add_step_with_dialog_cancel_adds_nothing -q -p no:xonsh
```
```
FAILED ...::test_add_step_with_dialog_cancel_adds_nothing
AssertionError: assert 1 == 0
```

**m10 comma** — restored `.replace(",", ".")`:
```
FAILED ...::test_a_comma_is_reported_not_silently_read_as_a_decimal_point
assert ([])
```

**m10 int/float message** — removed the int-specific `float(text)` probe:
```
FAILED ...::test_int_field_reports_a_clearer_message_for_a_non_integer_number
assert (["Sample: '3.5' is not a number"] and 'whole number' in "sample: '3.5' is not a number")
```

**m10 combo fallback** — restored `max(0, editor.findData(text))`:
```
FAILED ...::test_set_value_reports_an_unknown_combo_choice_instead_of_guessing
Failed: DID NOT RAISE ValueError
```

**m6 broad except** — narrowed back to `except ValueError`:
```
FAILED ...::test_validate_disables_ok_on_any_exception_not_just_valueerror
AssertionError: assert 'synthetic failure' in ''
```
(stderr for this run showed the unhandled `RuntimeError` traceback from inside `_validate`, printed by
PyQt rather than raised to the test — the exact swallowing behaviour m6 exists to stop.)

**m4 boundary allowlist** — before adding `Step`/`nyquist_mhz` to `ALLOWED_FROM_PROCESSING`:
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
```
```
FAILED packages/nsgeo-core/test_plugin_boundary.py::test_processing_is_used_only_through_its_public_surface
AssertionError: processing internals imported by the plugin:
ui/add_step_dialog.py:13: ['Step', 'nyquist_mhz']
ui/param_form.py:23: ['Step']
```

Every file was restored from a scratch copy after each check (verified byte-identical with `diff`
before moving to the next), matching this branch's standing caution about `git checkout --`.

### Full verification, final state (after every fix and every reversion-check restore)

Per-tier counts, exactly as printed:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
253 passed in 54.29s
```
(248 baseline + 5 new: the Important-3 complement, plus 4 minor-fix tests — comma, int/float message,
combo fallback, broad except)

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
333 passed, 2 skipped in 0.95s
```
(unchanged from baseline)

```
.venv/bin/python -m ruff check .
All checks passed!
.venv/bin/python -m ruff format --check .
88 files already formatted
```
(unchanged file count from the original submission — no new files this round, only edits)

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed in 0.17s
```
(matches baseline; confirms `nyquist_mhz`'s move into core didn't change the count, only the
allowlist contents)

```
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

### Files changed (this round)

- `packages/nsgeo-core/src/nsgeo/processing/base.py` (new `nyquist_mhz`)
- `packages/nsgeo-core/src/nsgeo/processing/__init__.py` (export it)
- `packages/nsgeo-core/src/nsgeo/processing/bandpass.py` (use it instead of recomputing)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (CRITICAL 1 fix, m9)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py` (m7, m8, m10, m11)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py` (m4, m6, m8)
- `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` (allowlist for m4)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py` (IMPORTANT 2 fix, IMPORTANT 3 test, m6/m10
  regression tests)

### Concerns

None. Every Critical/Important/Minor item from the review was addressed within this round's scope.
The two items the review explicitly parked (the dialog-validates-against-`source`-not-`result()`
design question, and not chasing `insert_step`/external-`replace_step` with dedicated new tests) were
left alone, per instruction — both are already covered by the identity-based mechanism this round's
fix installs, not by anything still open.

---

## What I implemented

- `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py` (new): `ParamForm(parent=None)`, one generic
  form built from a step's `schema()`. `kind` picks the editor: `float`/`int` are `QLineEdit`s (so a
  `REQUIRED` field can start blank), `choice` is a `QComboBox`, `curve` is a placeholder `QLabel`
  ("edited in the profile viewer's gain strip" — the actual curve editor is a later task).
  `set_step(name, params=None)` rebuilds the editors; `set_value`/`values`/`is_complete`/`build`/
  `commit` round-trip through the core's own `build_step`, so the core is the only validation.
  Signals: `committed(dict)` (a step was built and its params differ — see below), `error(str)`,
  `edited()`.
- `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py` (new): `AddStepDialog(step_name,
  header=None, radargram=None, parent=None)`. Blank `REQUIRED` fields, `header_facts()` shows antenna/
  sample interval/Nyquist/sample count as read-only reference, and `ok_button` stays disabled until
  the core builds the step **and** applies it to a one-trace slice of `radargram` without error —
  Nyquist/window errors surface in the dialog, never after the step is already in the stack.
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (modified): wired `self.form = ParamForm`
  into `form_area`; `add_step_requested` now routes to `add_step_with_dialog`, which seeds curve-kind
  REQUIRED steps (`gain_curve`) with the identity curve directly, or opens a real `AddStepDialog` via
  `exec()` for anything else (`bandpass`). Added `time_axis()`, `build_add_dialog()`,
  `append_from_dialog()`, `_show_form()`, `_on_form_committed()`, and a `self._shown` cache — see the
  named-risk section below for what that guards and why.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py` (new): the brief's 9 given tests,
  verbatim, plus 5 I added (one regression pin for a defect I found in the brief's draft code, two
  pinning the named risk, and two exercising the real `AddStepDialog.exec()` modal path that none of
  the given tests reach).

## A third defect found in the brief's draft code

The brief's `ParamForm.set_step()` ends its per-spec loop with `self._layout.addRow(self.message)`,
putting the status label inside the same `QFormLayout` that `clear()` empties via
`while self._layout.rowCount(): self._layout.removeRow(0)`. I checked directly (not assumed) whether
`QFormLayout.removeRow()` deletes the row's widgets or only detaches them:

```python
layout.addRow("A label", edit); layout.addRow(msg)
while layout.rowCount(): layout.removeRow(0)
msg.text()   # -> RuntimeError: wrapped C/C++ object of type QLabel has been deleted
edit.text()  # -> RuntimeError: wrapped C/C++ object of type QLineEdit has been deleted
```

It deletes them. So on the **second** `set_step()` call on one `ParamForm` instance — ordinary use for
`ProcessingDock.form`, a single instance reused across every row selection for the dock's lifetime —
`clear()`'s `removeRow` loop destroys `self.message` (added as a row by the *first* call), and the
very next line, `self.message.setText("")`, raises. Because this happens inside a slot connected to a
`pyqtSignal` (`step_selected` → `_show_form` → `set_step` → `clear`), the exception never reaches the
caller — PyQt prints it to stderr and the emitting signal returns normally — so it doesn't look like
a crash; it looks like the form silently staying blank (`step_name` stuck at `None`) the next time a
different row is selected. I confirmed this precisely with a mutation (see RED evidence below):
`dock.add_step("dewow")` then `dock.add_step("gain_agc")` then `setCurrentRow(1)` left
`dock.form.step_name` as `None`, with a swallowed `RuntimeError` printed to stderr from inside
`_show_form`.

**Fix**: `message` now lives in its own outer `QVBoxLayout`, never as a row of the `QFormLayout` that
`clear()` tears down — created once in `__init__`, never touched by `clear()`/`set_step()` again.
`clear()` still calls `self.message.setText("")` (clearing any stale error text), but that widget is
never deleted underneath it. This required restructuring `ParamForm.__init__` (an outer `QVBoxLayout`
holding a nested `QFormLayout` for the per-step rows, plus `self.message` as a sibling widget) — the
only deviation from the brief's draft beyond the named-risk work below. None of the brief's given
tests needed to change for this; they only observe `.text()`/`isinstance` results, never the layout
structure.

## The named risk: double `step_selected` emission and form-reset-mid-edit

`rebuild()` emits `step_selected` unconditionally every time it runs — including the echo that comes
back from this very form's own commit (`_on_form_committed` → `session.replace_step` →
`stack_changed` → `rebuild()`) and the second of `add_step()`'s two emissions (once from `rebuild()`,
once from its own following `setCurrentRow(count - 1)`). Naively reconnecting `step_selected` straight
to a slot that calls `form.set_step(...)` (i.e. `form.clear()` + rebuild every editor) would tear down
the very `QLineEdit` whose `editingFinished` just fired the commit, and discard whatever the user has
typed into any *other* field that hasn't been committed yet.

**Decision**: I traced every place a step's identity at a fixed `(key, row)` can change in this class,
and there is exactly one: the commit round-trip through `_on_form_committed` (nothing else — remove,
insert, reorder — replaces a step at a fixed index; every other mutation changes `row`, `key`, or
both). So `ProcessingDock` now tracks `self._shown: tuple[str | None, int]`, the `(key, row)` that
`_show_form` last actually displayed, and skips rebuilding whenever a new `step_selected(row)` reports
the same pair — an echo, by construction, never new information. This fixes both halves of the named
risk with one guard: it collapses `add_step()`'s duplicate emission into (at most) one real rebuild
(the transient first emission is either a genuine no-op skip, or a harmless `clear()` on a row nothing
was focused in yet), and it stops the commit round-trip from rebuilding the row it just wrote to.

I deliberately did **not** touch `add_step()`, `rebuild()`, or `_on_current_row()` to suppress the
duplicate emission at the source. `step_selected` is a public signal with no other documented
consumer today, but nothing rules one out, and a future consumer might legitimately want every
emission (e.g. a status log). Absorbing the redundancy at the one place that actually needs
deduplication — the form, the only consumer today that rebuilds expensive/stateful UI on it — keeps
the fix minimal and scoped to the actual problem, rather than changing Task 16's already-reviewed
`rebuild()`/`add_step()` mechanics for a consumer-side concern.

I did **not** change how `committed` fires (the brief's draft already commits on `editingFinished`/
`currentIndexChanged`, not on every keystroke — `textChanged` only feeds `edited`, which drives live
`is_complete()`/Nyquist feedback in `AddStepDialog`, and never touches the session). That part of the
brief's design was already correct; the risk was specifically in what happens *after* a legitimate
commit, not in when a commit fires.

## Tests written for the named risk

1. **`test_committing_one_field_does_not_rebuild_the_others`** — adds a `bandpass` step via the
   dialog, selects it, captures the `high_mhz` editor widget, edits and commits `low_mhz` through the
   real `committed` signal, and asserts (a) the session's step actually changed and (b)
   `dock.form.editors["high_mhz"] is high_editor` — the untouched field's widget survived the
   round-trip identically, not just its text.
2. **`test_typing_in_a_field_survives_an_unrelated_stack_change`** — the more realistic manifestation:
   no commit at all. Selects `gain_agc`, types into `window_ns` (`textChanged` only — genuinely
   mid-keystroke, nothing committed), then triggers `session.set_step_enabled(key, 0, False)` on a
   *different* row (a real, unrelated `stack_changed`). Asserts the in-progress editor is the same
   object and still reads `"12"` afterward.

Both fail under the same one-line reversion (deleting the `if shown == self._shown: return` guard in
`_show_form`) — verified directly, not assumed (see RED evidence below): with the guard removed, both
fail on a plain identity comparison (`<QLineEdit at 0x...> is <QLineEdit at 0x...>` — different
objects), no crash, no swallowed exception, a clean pinpoint of exactly the behaviour the fix
restores.

## TDD evidence

**RED — Step 2 of the brief**, before either new module existed (files moved aside, then restored;
never left absent):

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q -p no:xonsh
```
```
ImportError while importing test module '.../test_plugin_param_form.py'.
...
E   ModuleNotFoundError: No module named 'nsgeo_qgis.ui.add_step_dialog'
1 error in 0.16s
```
Matches the brief's expected failure exactly.

**RED — the third defect** (`test_message_label_survives_being_set_twice`), applying the one-line
reversion the test's own docstring names (re-adding `self._layout.addRow(self.message)` at the end of
`set_step()`, restored from a scratch copy afterward, never via `git checkout --`):

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q -p no:xonsh
```
```
2 failed, 11 passed in 0.88s
FAILED ...::test_message_label_survives_being_set_twice
  RuntimeError: wrapped C/C++ object of type QLabel has been deleted
FAILED ...::test_typing_in_a_field_survives_an_unrelated_stack_change
  AssertionError: assert None == 'gain_agc'
```
The second failure is not a bug in that test — it is the *same* underlying defect cascading: the
dock's own persistent `dock.form` hits its second real `set_step()` call inside this test too (adding
`dewow` then `gain_agc` and switching rows), and the swallowed `RuntimeError` (printed to stderr, not
raised to the caller — the exact hazard the task brief calls out) leaves `dock.form.step_name` stuck
at `None`. This is strong, unplanned corroboration that the fix is load-bearing, not cosmetic.

**RED — the named risk** (`test_committing_one_field_does_not_rebuild_the_others` and
`test_typing_in_a_field_survives_an_unrelated_stack_change`), applying the one-line reversion
(removing the `if shown == self._shown: return` guard in `_show_form`, restored from a scratch copy
afterward):

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q -p no:xonsh
```
```
2 failed, 11 passed in 0.78s
FAILED ...::test_committing_one_field_does_not_rebuild_the_others
  assert <PyQt5.QtWidgets.QLineEdit object at 0x...a0f0> is <PyQt5.QtWidgets.QLineEdit object at 0x...a180>
FAILED ...::test_typing_in_a_field_survives_an_unrelated_stack_change
  assert <PyQt5.QtWidgets.QLineEdit object at 0x...b140> is <PyQt5.QtWidgets.QLineEdit object at 0x...af90>
```
Exactly the two intended tests fail, cleanly (no crash, no stderr noise) — a plain identity mismatch,
precisely the "rebuilt instead of preserved" symptom the fix addresses. All other 11 tests unaffected
by either reversion, confirming each test pins its own, distinct behaviour.

**GREEN — after every fix**, focused file:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q -p no:xonsh
```
```
.............                                                            [100%]
13 passed in 0.71s
```

## What each new test's one-line reversion is (as required)

- `test_form_builds_editors_from_the_schema`, `test_form_shows_current_values_and_commits_new_ones`,
  `test_form_reports_bad_input_instead_of_raising`, `test_required_fields_start_blank_and_block_completion`,
  `test_add_step_dialog_shows_header_facts_and_validates_against_nyquist`,
  `test_dock_form_edits_the_selected_step_through_replace_step`,
  `test_dock_adds_required_steps_through_the_dialog`, `test_dock_seeds_a_curve_step_with_the_identity`
  — the brief's own given tests; not re-verified against a reversion individually beyond the RED/GREEN
  runs above, since they are specified verbatim.
- `test_message_label_survives_being_set_twice` — fails if `self._layout.addRow(self.message)` is
  restored at the end of `set_step()` (message back inside the destructible layout). Shown above.
- `test_committing_one_field_does_not_rebuild_the_others` and
  `test_typing_in_a_field_survives_an_unrelated_stack_change` — both fail if the
  `if shown == self._shown: return` guard is removed from `_show_form`. Shown above.
- `test_add_step_with_dialog_opens_a_real_modal_and_accepts` — fails if `add_step_with_dialog`'s
  `if dialog.exec() == QDialog.DialogCode.Accepted:` is inverted or if `append_from_dialog` is not
  called on acceptance (the assertion is on `session.stack_for(key).entries`, driven through the real
  `drive_dialog`-simulated `exec()`, not a fabricated call).
- `test_add_step_with_dialog_cancel_adds_nothing` — fails if `add_step_with_dialog` appended the step
  unconditionally instead of gating on the dialog's result (e.g. dropping the `if` around
  `append_from_dialog`).

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (modified: imports, `self._shown` init,
  `ParamForm` wiring in `__init__`, `_show_form`/`_on_form_committed`, `time_axis`/`build_add_dialog`/
  `append_from_dialog`/`add_step_with_dialog`)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py` (new)

## Full verification (final run)

Per-tier counts, exactly as printed:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
248 passed in 57.82s
```
(235 baseline + 13 new, all in `test_plugin_param_form.py`; no other qgis-tier test file touched)

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
333 passed, 2 skipped in 0.95s
```
(unchanged from baseline — this task never touches `nsgeo-core` or the pure tier)

```
.venv/bin/python -m ruff check .
All checks passed!
.venv/bin/python -m ruff format --check .
88 files already formatted
```
(one intermediate `ruff check --fix` was needed on the new test file: its import block did not match
this repo's isort grouping — `nsgeo_qgis.*` sorts alongside `nsgeo.*`/`plugin_testing`/`qgis.*` in one
block here, not as a separate "local" group, matching the existing `test_plugin_processing_dock.py`.
Applied, re-checked clean. 85 → 88 files: the two new implementation modules plus the new test file.)

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed in 0.17s
```
(unchanged from baseline)

```
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```
(this task's diff touches neither `lookup.py` nor `view_transform.py`, so this is unaffected either
way — confirmed by running it, not assumed)

## Self-review findings

- Confirmed no signal-processing code appears anywhere in the diff: the plugin only calls
  `get_step`, `build_step`, `available_steps`/`default_params`/`required_params` (via
  `processing_dock.py`, unchanged from Task 16) and each step's own `schema()`/`apply()` — the
  Nyquist check in `AddStepDialog._validate` runs the *real* `Bandpass.apply()` against a one-trace
  probe, never a reimplementation of what it does.
- Confirmed steps are never mutated in place: every edit goes through `build_step(...)` producing a
  new instance, passed to `session.replace_step`/`append_step`.
- Confirmed every Qt import goes through `qgis.PyQt`, and every enum reference is scoped
  (`QDialogButtonBox.StandardButton.*`, `QDialog.DialogCode.Accepted`).
- Confirmed every new widget is parented: `ParamForm(body)` in the dock, `ParamForm(self)` in
  `AddStepDialog`, and every editor/label/button reaches a parent transitively through
  `addRow`/`addWidget` on a layout installed on a parented widget (verified the parenting chain by
  hand, not merely by pattern-matching the brief).
- Confirmed the `_no_unhandled_modals` autouse guard in `conftest.py` already covers
  `AddStepDialog.exec()` without any change needed — it patches `QDialog.exec` on the base class, and
  `AddStepDialog` does not override `exec()`, so every subclass instance is caught the same way. Added
  two tests (`test_add_step_with_dialog_opens_a_real_modal_and_accepts`,
  `test_add_step_with_dialog_cancel_adds_nothing`) using the existing `drive_dialog` fixture to
  actually exercise `add_step_with_dialog`'s real `exec()` branch — none of the brief's given tests
  reach it (they all call `build_add_dialog`/`append_from_dialog` directly, bypassing the modal loop).
- Ran the focused file after every change while iterating, then both full tiers, ruff, boundary, and
  mypy, in that order, before committing.
- Output is pristine: no stderr noise, no Qt warnings, in the final (fixed) state — confirmed by
  re-reading the full `-q` output of every run above, not just the pass/fail counts.

## Concerns

None. The task's own environment/command guidance was followed exactly as given (no discrepancies
found this time, unlike Task 16's mypy-scope and boundary-file-name notes). The one structural
deviation from the brief's draft code (`ParamForm.__init__`'s outer/nested layout split) is described
above with the reasoning and the direct experiment that motivated it, and does not change any of the
brief's own test expectations.
