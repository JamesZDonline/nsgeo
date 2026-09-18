# Round-2 chunk 1 — C2 report

Base `5cc5a12`, branch `nsgeo-qgis`, worktree
`/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-qgis`.
Every test run below had `PYTHONDONTWRITEBYTECODE=1` exported.

## 1. The failing test, before the fix

Written first, against unmodified `5cc5a12`. It drives the brief's reproduction through the real
plugin: two `gain_curve` steps in one stack, a drag started on row 0's handle, a real
`Qt.Key_Down` delivered to the processing list (which keeps the keyboard, because the strip sets
no focus policy), then the rest of the gesture.

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py -q -p no:xonsh \
    -k "row_change_mid_drag"
F                                                                        [100%]
=================================== FAILURES ===================================
_____ test_a_row_change_mid_drag_never_writes_onto_the_newly_selected_step _____
>       assert after == b_before, f"step B's authored curve was overwritten with step A's: {after}"
E       AssertionError: step B's authored curve was overwritten with step A's: [[0.0, 0.0], [54.9044748033796, 9.789473684210526]]
E       assert [[0.0, 0.0], ...473684210526]] == [[0.0, 0.0], [40.0, -12.0]]
E
E         At index 1 diff: [54.9044748033796, 9.789473684210526] != [40.0, -12.0]
1 failed, 19 deselected in 0.83s
```

That is the brief's finding exactly: step B's authored `[[0.0, 0.0], [40.0, -12.0]]` came back as
the dragged A curve, with no error, no log and no undo.

The second-barrier test failed too, for its own reason:

```
$ ... -k "no_longer_holds"
>       assert s.stack_for(key).entries[1][0] is before  # unchanged object: no replace_step ran
E       assert <nsgeo.processing.gain.GainCurve object at 0x7677d27d5700> is <nsgeo.processing.gain.GainCurve object at 0x7677d27d56a0>
1 failed
```

## 2. The design, and what I rejected

**`GainStrip.set_points(points, owner)` — barrier 1.** An opaque token, compared only for
equality. A payload whose owner differs from the one on screen *ends* the gesture (`_drag =
_drag_db_range = None`) and is then accepted; a payload with the same owner keeps the existing
mid-drag refusal. The strip deliberately does not decide what makes two curves "the same" — that
is `plugin.py`'s business.

`owner` is **required**, not defaulted. `ProfileDock.show_gain_strip` is its only production
caller, and the two payload kinds this widget must tell apart are distinguished by nothing else,
so a caller that forgets has no safe answer to fall back on. On `show_gain_strip` the owner *is*
defaulted to `None`, because its three `show_gain_strip(None)` hide calls return before reaching
`set_points` at all and would otherwise have to invent a token for a payload that is never
delivered.

**The owner is `(key, row, generation)` — a deviation from the WIP, see §5.** It cannot be the
step object: every move of a drag replaces the step, so an owner keyed on identity would differ
on the very first move and the gesture would end itself. It cannot be `(key, row)` alone either
— see §5.

**`NsgeoPlugin._on_gain_points` re-checks step identity — barrier 2.** Before writing, the
selected row must still hold the very step object `_sync_gain_strip` built the strip from
(`if step is not self._gain_step: return`). Identity, not name: two `gain_curve` steps in one
stack share a name. This mirrors `ProcessingDock._on_form_committed`'s check against
`_shown_step`, and it is the only barrier that covers `points_changed` being a public signal on a
public widget — an emit that never came from a gesture never passes through the strip's owner
check at all.

**`self._gain_step = new` is set before `session.replace_step(...)`, not after.** This is
load-bearing, not cosmetic: `replace_step` emits `stack_changed` synchronously, which rebuilds
the dock, which re-emits `step_selected`, which re-enters `_sync_gain_strip` with the *new* step
object. Recorded after the call, that echo would read as "a different step" and end the drag on
its first move. Mutation M4 below proves it.

**Rejected: resetting the strip's `_owner` on the hide paths** (the WIP gap the chunk brief asked
me to decide on). It buys nothing observable. `hideEvent` already ends the gesture, so a stale
`_owner` on a hidden strip cannot cause a refusal — `set_points`'s mid-drag branch is
unreachable with `_drag is None`. And every hide path is one where the step at the selected row
is *not* the strip's step (no curve param) or there is no row at all, so barrier 2 refuses any
stray write regardless. I left the hide paths as plain `show_gain_strip(None)`.

**Rejected: the WIP's `_forget_gain_owner()`.** Same reasoning. It would have added a third piece
of plugin state mutated on three branches with no test able to kill it — a mutation survivor by
construction, which is the defect class this whole fix round exists to remove.

**Rejected: an `owner()` accessor on `GainStrip`** (also in the WIP). Nothing in production or in
the tests reads it; the plugin keeps its own `_gain_owner`.

**Rejected: a third `_gain_owner != (key, row)` check inside `_on_gain_points`** (the WIP had
one). With the generation in the token, `_gain_step` can only be the step at the recorded
`(key, row)`, so the extra comparison is unreachable and untestable.

## 3. Mutation results

Each barrier disabled in turn, the file restored afterwards and the restore asserted byte-exact.
Run against `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py` (M5 against the whole
qgis tier).

| # | Mutation | Killed by |
|---|---|---|
| M1 | `gain_strip.set_points`: `if owner != self._owner:` → `if False:` (the strip can no longer tell one curve from another) | `test_a_row_change_mid_drag_never_writes_onto_the_newly_selected_step` |
| M2 | `plugin._on_gain_points`: `if step is not self._gain_step:` → `if False:` (no second barrier) | `test_a_gain_write_is_refused_when_the_row_no_longer_holds_the_strips_step` |
| M3 | `plugin._sync_gain_strip`: `self._gain_generation += 1` → `pass` (owner degenerates to `(key, row)`) | `test_a_stack_reorder_mid_drag_never_writes_onto_the_step_that_took_the_row` |
| M4 | `plugin._on_gain_points`: `self._gain_step = new` moved to *after* `replace_step` | `test_dragging_a_point_past_its_neighbour_does_not_corrupt_it` (pre-existing) |
| M5 | `plugin._sync_gain_strip`: `if name is None: show_gain_strip(None); return` → `pass` (the restructured non-curve branch) | `test_plugin_routes_strip_edits_through_replace_step`, `test_reselecting_a_curve_row_after_an_edit_still_shows_the_strip`, `test_applying_a_preset_updates_the_form_and_gain_strip_for_the_selected_row` (3 failed, 13 errors) |

Raw output:

```
=== M1-strip-owner-check ===
..........F
FAILED ...::test_a_row_change_mid_drag_never_writes_onto_the_newly_selected_step
1 failed, 10 passed in 2.28s

=== M2-plugin-step-identity ===
............F
FAILED ...::test_a_gain_write_is_refused_when_the_row_no_longer_holds_the_strips_step
1 failed, 12 passed in 6.22s

=== M3-owner-generation ===
...........F
FAILED ...::test_a_stack_reorder_mid_drag_never_writes_onto_the_step_that_took_the_row
1 failed, 11 passed in 5.53s

=== M4-gain-step-before-replace ===
........F
FAILED ...::test_dragging_a_point_past_its_neighbour_does_not_corrupt_it
1 failed, 8 passed in 3.53s

=== M5-hide-on-non-curve-row ===   (whole qgis tier)
3 failed, 290 passed, 13 errors in 71.46s
```

Every line of production code added by this change is killable, and each barrier is killed by a
different test — removing either one goes red on its own.

## 4. Verification

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
339 passed in 70.49s (0:01:10)

$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
363 passed, 3 skipped in 1.59s

$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py -q -p no:xonsh
2 passed in 0.03s

$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

qgis tier **336 → 339** (+3, the three tests added here). Pure+core **363 passed, 3 skipped**,
unchanged — all three new tests live in the qgis tier, which that venv skips wholesale.

## 5. Deviations from the brief

**(a) The owner token is `(key, row, generation)`, not `(key, row)`.** The WIP's reasoning for
why the owner cannot be the step object is right and I kept it; its choice of `(key, row)` as the
replacement is not sufficient, and I can show it.

A stack mutation that swaps a *different* step into the *same* row leaves `(key, row)` unchanged.
The strip would then compare the incoming payload's owner equal to its own, take it for an echo,
and refuse it mid-drag — while `_sync_gain_strip` had already, correctly, recorded the new step
as the one at that row, so barrier 2's identity check passes and the write lands on it. That is
C2 again, one row along, with both of the brief's barriers open. Reproduced: with the generation
bump removed (mutation M3), `test_a_stack_reorder_mid_drag_never_writes_onto_the_step_that_took_
the_row` fails with the dragged curve written onto the reordered step.

The fix is two lines — bump a counter whenever a genuinely different step object arrives — and it
keeps the token stable across the strip's own edits, which is the property the WIP correctly
identified as essential. It is not reachable by a human today (reordering needs the pointer the
strip has grabbed), so the new test is a barrier against a future path, the same kind
`test_a_shrunk_point_list_mid_drag_does_not_raise` already exists for in this file. It is driven
through the real, public `session.move_step`, exactly as the dock's own ↑/↓ buttons drive it.

**(b) `show_gain_strip`'s `owner` is defaulted, `set_points`'s is required.** The chunk brief
asked me to confirm `Any` is imported in `profile_dock.py` — it is (`profile_dock.py:42`) — and
to decide between a defaulted and a required owner. Split, for the reason in §2.

**(c) The boundary command reports 2 passed, not the brief's baseline of 6.**
`packages/nsgeo-core/tests/test_boundary.py` contains exactly two test functions and has not been
touched since `d26b32a` ("feat: scaffold nsgeo core package with boundary test and CI").
Confirmed against BASE: `git show 5cc5a12:packages/nsgeo-core/tests/test_boundary.py |
grep -c '^def test_'` → `2`. The baseline figure in the chunk brief is wrong; nothing regressed.

**(d) `ruff` and `mypy` are not on `PATH` on this machine.** Run as `.venv/bin/ruff` and
`.venv/bin/mypy`. Same tools, same arguments.

**(e) I restructured `_sync_gain_strip`'s non-curve branch** from
`show_gain_strip(step.params[name] if name else None)` into an explicit
`if name is None: show_gain_strip(None); return`. Necessary — the show path now needs a
`name`-dependent owner computed only when there is a curve — and behaviour-preserving; M5 pins it.

## 6. Out of scope — found, not fixed

1. **`_on_gain_points` indexes `entries[row]` with no bounds check**
   (`plugin.py:340`, `self.session.stack_for(key).entries[row][0]`). `_sync_gain_strip` guards
   the same access with `if row >= len(entries)`; this one does not, so a `points_changed` that
   arrives between a stack shrink and the dock's rebuild would raise `IndexError` inside a slot.
   Pre-existing, unreachable through today's synchronous rebuild path, and adding the guard would
   have added a branch no test can kill. Not touched.

2. **`_on_gain_points` writes whether or not the strip is visible.** `show_gain_strip` hides the
   strip when `self.view.transform is None`, and that path still records `_gain_owner`/
   `_gain_step`, so a `points_changed` emitted while the strip is hidden for want of an axis
   passes both barriers. Pre-existing and unchanged by this fix; no route emits it today, since
   `hideEvent` ends the gesture and `mouseMoveEvent` needs a live `_drag`.

3. **`GainStrip`'s module docstring opened with "Two invariants"** while already documenting
   three. I corrected it to "Four" in the same docstring I extended, since leaving it would have
   made the count visibly wrong at the point of my own edit. Documentation only.
