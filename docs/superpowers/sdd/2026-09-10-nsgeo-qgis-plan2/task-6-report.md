# Task 6 report: `SiteSession`

## What I implemented

- `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `SiteSession(QObject)`, the single
  owner of plugin survey state, exactly per the brief's interface list — 11
  signals, 10 properties, 33 public methods, `SURVEY_FILE` constant.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`: the brief's 12 tests
  verbatim, plus one supplementary test I added, `test_further_mutators_emit_only_on_real_change`
  (see Deviation below).

Behaviour, traced against every given test case:
- `new_site`/`open_site`/`close_site`/`save` manage the `Site` + `survey.nsgeo.json`
  lifecycle; `save(allow_absolute=None)` remembers an explicit opt-in for the
  rest of the session (matches `_line_key`'s absolute-path escape hatch).
- `line_key`/`keys`/`line_for_key` compute keys via `nsgeo.project._line_key`
  with `allow_absolute=True` always (the save-time restriction is a separate,
  later concern owned by `save()`), so in-memory identity works for out-of-tree
  lines before the user has opted into persisting them that way.
- Grid/line CRUD (`add_grid`, `replace_grid`, `remove_grid`, `set_grid_velocity`,
  `add_lines`, `remove_line`, `set_line_velocity`) validate before mutating
  (duplicate ids, lines still referencing a grid) and mark dirty + emit the
  matching `*_changed` signal only on success.
- `stack_for`/`append_step`/`insert_step`/`replace_step`/`remove_step`/
  `move_step`/`set_step_enabled` are the only legal path to `StepStack`
  mutation, all funnelling through `_touch_stack` (dirty + `stack_changed`).
  `replace_step` is the fast, correct edit path per the core's no-mutation
  rule; nothing here ever edits a step object in place.
- `apply_stack_to_grid` copies a stack via `StepStack.to_dicts()` /
  `from_dicts()` onto every other line in the same grid — independent
  `StepStack` objects, not shared references (verified by identity and by
  re-editing the source afterwards without affecting the copy).
- `set_profiles`/`profiles_for`/`channel`/`set_channel` hold per-line
  `Profile` lists and the active channel; `_attach_source` is the one place
  that builds `Radargram.from_profile(...)` (never the raw constructor) and
  feeds it into the stack, invalidating the stack's cache.
- `open_line`/`set_trace`/`set_selection`/`clear_selection` are the cursor
  state, each gated so a call for a non-current line is ignored and a value
  equal to the current one does not re-emit.
- `resolved_velocity` delegates entirely to `nsgeo.velocity.resolve_velocity`,
  no re-implementation of the line-over-grid precedence.

## Deviation from the brief's reference code

The brief's reference `session.py` guards no-op calls for `set_trace`,
`set_selection`, and `set_channel` (skip if the value is unchanged), and the
module's own docstring promises this for *every* signal: "Every signal fires
only when a value actually changed." But the reference `set_step_enabled` and
`move_step` did not follow their own rule:

- `set_step_enabled(key, index, flag)` called `stack.set_enabled(...)` and
  emitted `stack_changed` unconditionally, even when `flag` already matched
  the entry's current enabled state.
- `move_step(key, src, dst)` called `stack.move(...)` and emitted
  unconditionally, even when `src == dst` (a step dropped back where it
  started — the natural drag-and-drop-cancelled case).

Both are exactly the failure mode the task's own Context section calls out:
"a signal that fires when nothing changed causes redundant re-renders of a
512x6301 radargram." `stack_changed` is precisely the signal a profile dock
would use to trigger a full re-render of the processed radargram, so this
was a real, load-bearing defect, not a style nit.

I fixed both:
```python
def move_step(self, key: str, src: int, dst: int) -> None:
    stack = self.stack_for(key)
    if src == dst and 0 <= src < len(stack):
        return  # moving a step onto itself changes nothing
    stack.move(src, dst)
    self._touch_stack(key)

def set_step_enabled(self, key: str, index: int, flag: bool) -> None:
    stack = self.stack_for(key)
    if stack.entries[index][1] == flag:
        return  # already in the requested state
    stack.set_enabled(index, flag)
    self._touch_stack(key)
```
`move_step`'s guard is careful to only short-circuit when `src` is in range,
so an out-of-range `move_step(key, 99, 99)` still raises `IndexError` via the
underlying `StepStack.move`, matching the original error behaviour for bad
input — only the genuine no-op case is skipped.

I added one supplementary test, `test_further_mutators_emit_only_on_real_change`,
that pins this (and also exercises the no-op paths of `open_line` and
`clear_selection`, which the given tests exercise only indirectly). I did
**not** weaken any of the brief's 12 given tests — all pass unmodified except
for a `ruff format`/import-sort autofix (see below).

I deliberately did **not** add equivalent no-op guards to `replace_step`,
`replace_grid`, `set_grid_velocity`, `set_line_velocity`, `add_grid`,
`remove_grid`, `add_lines`, or `remove_line`. Those are structural collection
changes gated by explicit-exception invariants (duplicate ids, dangling
references) rather than value-redundancy checks, and `Step` objects (unlike
`bool` flags or list indices) have no `__eq__` — comparing them for a no-op
would mean inventing a new `(name, params)` equality convention not
established anywhere else in the core or plugin. That felt like scope creep
past a discovered defect and into speculative redesign, so I left those as
the brief specifies.

I also found the brief's verbatim test file failed `ruff check`/`ruff format`
as given (an import-sort grouping and one line over 100 chars in `_lines()`).
This is a formatting-only issue, not a behavioural one, so I ran
`ruff check --fix` and `ruff format` on just that file rather than hand-editing
around it — the test bodies are untouched, only import order and line-wrapping
changed.

## TDD Evidence

**RED** (before `session.py` existed):
```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:xonsh
...
packages/nsgeo-qgis/tests/qgis/test_plugin_session.py:13: in <module>
    from nsgeo_qgis.session import SURVEY_FILE, SiteSession
E   ModuleNotFoundError: No module named 'nsgeo_qgis.session'
1 error in 0.17s
```
Expected and matches the brief's Step 2 exactly.

**RED for my own added test**, confirmed by temporarily reverting the two
no-op guards back to the brief's unmodified `set_step_enabled`/`move_step`:
```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_session.py::test_further_mutators_emit_only_on_real_change -q -p no:xonsh
...
>       assert stack_changed.calls == []
E       AssertionError: assert [('raw/FILE__...E__001.DZT',)] == []
E         Left contains 2 more items, first extra item: ('raw/FILE__001.DZT',)
1 failed in 0.68s
```
This proves the added test actually exercises the defect (fails against the
brief's original code, passes against my fix) rather than being vacuous.
Guards were restored immediately after this check.

**GREEN** (final state, both tiers + lint + mypy):
```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
294 passed, 2 skipped in 0.73s

$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
23 passed in 1.31s   # 10 pre-existing + 13 in test_plugin_session.py

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
59 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
Success: no issues found in 22 source files
```
(mypy's configured target is `packages/nsgeo-core/src/nsgeo` only, per the
Environment section's exact command — `nsgeo_qgis` is not in its scope for
this task, consistent with there being no qgis-specific mypy config in the
repo.)

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/session.py` (new, 379 lines)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` (new, 241 lines)

Commit: `bbe9cd5` — "feat: SiteSession, the single owner of plugin survey state"

## Self-review findings

- Traced every one of the brief's 12 tests line-by-line against the reference
  implementation before writing it, to distinguish "brief is right" from
  "brief is the thing to fix" — see Deviation section for the one place I
  changed behaviour.
- Confirmed `line_key`'s deliberate `allow_absolute=True` (always, regardless
  of the session's save-time `_allow_absolute` flag) is correct design, not a
  bug: it is the in-memory identity computation, distinct from the
  persistence-time restriction `save()` enforces. Traced this against
  `test_save_out_of_tree_line_needs_allow_absolute`, which depends on exactly
  this split (adding the out-of-tree line succeeds immediately; only `save()`
  without the opt-in raises).
- Checked the boundary guard (`tests/pure/test_plugin_boundary.py`) by hand
  against every import in `session.py`: `Radargram`, `StepStack` from
  `nsgeo.processing` are both allowed; `Step` is deliberately never imported
  (mutator signatures use `step: Any` instead, which is exactly why the
  reference code does this — confirmed it's intentional, not an oversight).
  `nsgeo.project`, `nsgeo.model.survey`, `nsgeo.geometry.grid`, `nsgeo.velocity`
  are all outside the guard's restricted surface.
- Checked `Site.stacks`/`Line`/`Grid` equality semantics (frozen dataclasses,
  default `eq=True`) line up with the reference's use of `list.remove(line)`,
  `list.index(line)`, `list.remove(grid)` — no risk of removing/finding the
  wrong element in these tests since each fixture produces distinct paths.
- Confirmed `Radargram.from_profile` (never the raw constructor) is the only
  route `_attach_source` uses to build a radargram, and that the resulting
  array is `float` (`dtype.kind == "f"`), per the sharp edge about
  `Profile.data` being `int32`.
- No YAGNI concerns: every public method/property/signal in the file is
  required by the brief's interface list and exercised by at least one test.
  `picks_changed` is declared but never emitted — that is per the brief
  (a later task's concern), not unused scope I added.
- Test output is pristine: no warnings, no skips introduced, no stray prints.

## Concerns

- None that block. One thing worth flagging for a reviewer's attention rather
  than a concern of mine: `stack_for(key)` trusts an already-present
  `site.stacks[key]` entry without re-validating it against `line_for_key`
  (the `KeyError` guard only runs on the "create a fresh stack" branch). A
  hand-corrupted or externally-produced `survey.nsgeo.json` with an orphaned
  stack key that doesn't match any current line could reach `stack_for`
  without raising. This is not reachable through any method this task
  exposes (every path that populates `site.stacks` goes through a validated
  key), it is not exercised by any given test, and `Site.validate()` itself
  does not check stack/line key consistency either — so I left it as-is
  rather than inventing new validation the brief didn't ask for. Flagging it
  in case a later task (import/loader) needs to reason about malformed
  project files.

---

# Fix report: review round 1

Commit: `d5aba2f` — "fix: SiteSession review round 1 -- selection clamp,
profile-load race, line-index perf, and four signal/state-ordering defects"
(on top of `bbe9cd5`, not amended).

All nine findings fixed. One per finding below: what changed, the `set_selection`
sentinel decision, the Finding 4 measurement, the covering test(s), and the RED
evidence (each new test run against the pre-fix `bbe9cd5` code, proving it's
not vacuous).

## Finding 1 — `set_selection` asymmetric clamp

**Change** (`session.py`, `set_selection`): clamp `lo` and `hi` independently
into `[0, n-1]` instead of flooring only `lo` and capping only `hi`:
```python
sel = (max(0, min(lo, n - 1)), max(0, min(hi, n - 1)))
```

**Sentinel decision, stated explicitly:** `set_selection` can never express
"cleared." With symmetric clamping, both ends always land in `[0, n-1]`
(a `Line` always has `n_traces >= 1`, since the DZT reader rejects a
zero-trace file), so the result can never equal `(-1, -1)`. Clearing the
selection remains exclusively `clear_selection()`'s job — I did not add a
`raise` for negative input, because the clamp already makes the sentinel
unreachable without rejecting otherwise-ordinary off-edge drags (dragging
past either end of the line is a normal gesture, not an error). This is
recorded in a comment at the call site.

**Test:** `test_set_selection_clamps_both_ends_independently_into_range` —
reproduces the review's own three probe rows (`(-5,-3)`, `(5000,6000)`,
`(-1,-1)`) and asserts the resulting selection and the exact `selection_changed`
call sequence.

**RED against `bbe9cd5`:**
```
AssertionError (selection == (0, 0) failed; old code produced (0, -3))
```
(full trace below, this test was one of seven that failed in the batch run)

## Findings 2 & 3 — `set_profiles` leaks state on error, builds the radargram twice

**Change:** `stack_for(key)` is now called *first* in `set_profiles`, before
`self._profiles`/`self._channel` are touched — it both validates the key
(raising `KeyError` before anything is cached) and returns the stack, which
`_attach_source` then builds against exactly once (its creation branch inside
`stack_for` sees no profiles yet, since `self._profiles[key]` isn't set until
after `stack_for` returns).

**Tests:**
- `test_set_profiles_leaves_no_residue_when_the_key_is_unknown` — asserts
  `profiles_for("nope") is None` after the `KeyError`.
- `test_set_profiles_builds_the_radargram_exactly_once` — monkeypatches
  `Radargram.from_profile` with a counting wrapper (via
  `nsgeo_qgis.session.Radargram`, the same class object session.py imported)
  and asserts exactly one call on first load.

**RED against `bbe9cd5`:**
```
test_set_profiles_leaves_no_residue_when_the_key_is_unknown:
  AssertionError: assert [Profile(data=array(...))] is None
  (profiles_for('nope') still returned the leaked list)

test_set_profiles_builds_the_radargram_exactly_once:
  AssertionError: assert 2 == 1
```

## Finding 4 — `line_for_key`/`keys()` cost

**Change:** `self._root` (the resolved project directory) and
`self._lines_by_key: dict[str, Line]` are now computed once in `_install`
(one `resolve()` per line, at open time) and kept in sync incrementally:
`add_lines` extends the map, `remove_line` deletes from it, `set_line_velocity`
overwrites the entry at the same key (the key is stable — it depends only on
`line.path`, never on `velocity`), `close_site` clears it.
`keys()`/`line_for_key()` now read the map directly (no `resolve()` calls at
all on that path); `apply_stack_to_grid` iterates the map instead of
recomputing every line's key from `site.lines`.

**Measurement** (100 lines, one grid, 300 calls each — script run standalone,
not part of the committed test suite):

| | before (`bbe9cd5`) | after (`d5aba2f`) | speedup |
|---|---|---|---|
| `line_for_key` | 4.5530 ms/call | 0.0004 ms/call | ~11,000x |
| `keys()` | 8.9767 ms/call | 0.0011 ms/call | ~8,000x |

Commands:
```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python bench_line_for_key.py   # before
line_for_key: 4.5530 ms/call  (300 calls, 100 lines)
keys():       8.9767 ms/call  (300 calls, 100 lines)

$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python bench_line_for_key.py   # after
line_for_key: 0.0004 ms/call  (300 calls, 100 lines)
keys():       0.0011 ms/call  (300 calls, 100 lines)
```

**Test:** `test_line_index_stays_correct_across_every_list_changing_operation`
— exercises `set_line_velocity` (object swapped, key stable), `remove_line`
(key gone, `line_for_key` now raises `KeyError`), `open_site` on a fresh
session (index rebuilt from what was actually saved), and `close_site`
(`keys()`/`line_for_key()` both require an open site again).

This test is functional, not a timing test, so — as expected — it **passes
against `bbe9cd5` too**: the pre-fix code was correct, just slow, and the
whole point of Finding 4 is that correctness alone doesn't catch it. The
benchmark above is the actual evidence for this one; the test's job is to
pin that the new caching layer didn't trade correctness for speed.

## Finding 5 — `close_site` signal/state gaps

**Change:** `close_site` now emits `line_opened("")` when a line was current
(mirroring `remove_line`'s guard, `had_current_line = self._current_key is
not None` captured before the reset), and resets `self._allow_absolute = False`
the way `_install` does.

**Tests:**
- `test_close_site_does_not_emit_line_opened_when_nothing_was_current` — no
  spurious emit when nothing was open.
- `test_close_site_emits_line_opened_empty_and_resets_allow_absolute_when_a_line_was_current`
  — asserts the emit, and directly reads `session._allow_absolute` (there is
  no public way to observe it once the site is closed and no new site has
  been installed over it, since `_install` would reset it anyway — noted in
  the test).

**RED against `bbe9cd5`:** the "nothing was current" test passed unchanged
(old code never emitted at all, so the "no emit" half was trivially true);
the "a line was current" test failed:
```
AssertionError: assert [] == [('',)]
```

## Finding 6 — `_attach_source` silently keeps a stale source

**Change:** when `profiles` is falsy, `_attach_source` now sets
`stack.source = None` instead of doing nothing, so a reload with no profiles
clears whatever radargram was previously attached rather than leaving it in
place.

**Test:** `test_set_profiles_with_an_empty_list_clears_a_previously_attached_source`
— loads real profiles, confirms a source is attached, then calls
`set_profiles(key, [])` and asserts `stack_for(key).source is None`.

**RED against `bbe9cd5`:**
```
AssertionError: assert Radargram(data=array([[ -53067., ...]]), ...) is None
```
(the previous line's Radargram was still attached)

## Finding 7 — `new_site` installs before it writes

**Change:** `new_site` now builds `site = Site()` and calls `save_site(site,
json_path)` *before* `self._install(...)`, matching `open_site`'s existing
write/load-then-install order. A failed initial write leaves the session
exactly as it was — not `is_open`, no `site_opened`.

**Test:** `test_new_site_does_not_install_when_the_initial_save_fails` —
monkeypatches `nsgeo_qgis.session.save_site` to raise `OSError` (standing in
for a read-only folder) and asserts `not s.is_open` and no `site_opened` emit.

**RED against `bbe9cd5`:**
```
AssertionError: assert not True   (s.is_open was True after the failed save)
```

## Finding 8 — `apply_stack_to_grid` dirty-after-emit ordering

**Change:** `self._set_dirty(True)` now runs immediately before each
`stack_changed.emit(other)` inside the loop, instead of once after the whole
loop finishes. `_set_dirty` is idempotent (guarded internally), so this costs
nothing extra when there are multiple targets — it just guarantees dirty is
already `True` by the time *any* `stack_changed` handler runs.

**Test:** `test_apply_stack_to_grid_marks_dirty_before_any_stack_changed_slot_runs`
— connects a synchronous lambda to `stack_changed` that records
`session.dirty`, calls `apply_stack_to_grid`, and asserts the recorded value
is `True`.

**RED against `bbe9cd5`:**
```
AssertionError: assert [False] == [True]
```

## Finding 9 — no thread-safety statement

**Change:** added one paragraph to the module docstring stating the session
is main-thread-only and that a background loader (`QgsTask`) must marshal its
result back to the main thread before calling in. Documentation-only; no test
applies.

## Not touched (per the "not in scope" list)

`stack_for` still doesn't mark dirty when it creates an empty stack;
`apply_stack_to_grid` still returns `[]` silently for an unknown `grid_id`;
`set_channel`'s `IndexError` message is unchanged; and I did not add the
deferred coverage (`close_site` idle-path beyond what Finding 5 needed,
`open_site` over an already-open site, `grid_for_line`, `profiles_for`'s
happy path, or a multi-channel `set_channel` success path).

## A side effect of the Finding 4 cache worth flagging

Caching `key -> Line` in a `dict` changes behaviour for one degenerate case
that was never in scope or tested: if a hand-edited `survey.nsgeo.json` listed
the same path twice, the old `keys()` (a list comprehension over `site.lines`)
would surface the duplicate key twice and `line_for_key` would return the
first match; the new cache silently collapses the dict to one entry, and
`line_for_key` returns whichever line was inserted last. Neither `Site.validate()`
nor `load_site()` checks for duplicate line paths today, so this was already an
unvalidated state, not one the old code handled gracefully either — it just
failed differently. Not fixed here (out of round scope, not one of the nine
findings, not raised by the reviewer), flagging for whoever eventually adds
duplicate-path validation to `load_site`/`Site.validate()`.

## Commands run and output

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
294 passed, 2 skipped in 0.73s

$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
32 passed in 1.29s
  # test_plugin_session.py: 13 pre-existing + 9 new = 22
  # test_plugin_loads.py: 1 (unaffected)
  # tests/pure (boundary + shim, also collected under .venv-qgis): 9 (unaffected)

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
59 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
Success: no issues found in 22 source files
```

Batch RED check (full file, all new tests, against the unmodified `bbe9cd5`
`session.py`, before restoring the fixed version):
```
7 failed, 15 passed in 0.84s
```
The 7 failures are Findings 1, 2, 3, 6, 5 (current-line half), 7, 8 — exactly
the ones with a behavioural difference to catch. The 15 passes are the 13
pre-existing tests (unaffected) plus the two tests whose assertions hold
under both the old and new code by construction (Finding 4's correctness test,
and Finding 5's "nothing was current" half) — reasoned through above.

Files changed this round:
- `packages/nsgeo-qgis/nsgeo_qgis/session.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`
