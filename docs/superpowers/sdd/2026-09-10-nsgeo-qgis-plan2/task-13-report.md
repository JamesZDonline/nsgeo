# Task 13: `ViewTransform` -- report

## What was implemented

- `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` (new): `ViewTransform`, a frozen dataclass
  with fields `n_traces, n_samples, t0_ns, dt_ns, width, height, trace_lo, trace_hi, time_lo, time_hi`.
  `fit(n_traces, n_samples, t0_ns, dt_ns, width, height)` classmethod; `t_end` property;
  `x_of_trace`/`trace_of_x`, `y_of_time`/`time_of_y` forward-inverse pairs; `trace_index_at`,
  `sample_index_at` (clamped, integer); `source_rect() -> (x, y, w, h)` in image-pixel units;
  `with_window`, `zoomed`, `panned`, `resized` (all return new instances via `dataclasses.replace`,
  never mutate). Module-level `nice_ticks(vmin, vmax, target=6) -> np.ndarray` and constants
  `MIN_TRACE_SPAN = 4.0`, `MIN_SAMPLE_SPAN = 4.0`. Imports only `math`, `dataclasses`, and `numpy` --
  no Qt, no `nsgeo` core.
- `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py` (new): the brief's 9 tests, verbatim
  in substance (ruff auto-wrapped 3 lines that exceeded the 100-column limit and sorted the import
  block; no assertion or test-case value was changed -- see diff note below).
- `.github/workflows/ci.yml`: appended `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` to the
  lint job's mypy invocation, after `nsgeo_qgis/lookup.py`. Nothing else in the plugin package was
  added, per the brief's explicit instruction.

I implemented the brief's reference code as given (Step 3), after independently checking it against
every test case by hand and by running it in an isolated scratch copy before touching the worktree --
see "Reference-code check" below. Unlike Tasks 10-12, this brief's reference implementation had no
defects against its own test cases.

## Test results

- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q` -> **39 passed** (was 30; +9 new).
- `.venv/bin/python -m pytest packages/nsgeo-core/tests -q` -> **285 passed, 2 skipped** (unchanged;
  ran as a sanity check that nothing in core was touched).
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **76 files already formatted.**
- `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` -> **Success: no issues found in 24 source
  files** (up from 23).
- `test_plugin_boundary.py` (the AST boundary test) passes with the new module present: no forbidden
  import, and `nsgeo_qgis/__init__.py` still imports no qgis at module level.

This module is pure-tier only; `.venv-qgis`/`tests/qgis` were not touched and do not need to run for
this task (Task 13 introduces no Qt code).

## Reference-code check

Given this branch's pattern of every prior task's brief reference code containing at least one real
defect, I verified the brief's Step 3 implementation independently before committing to it:

- Hand-traced every assertion in the brief's 9 tests against the reference formulas, including the
  two that use exact (non-`approx`) float equality: `FIT.x_of_trace(0) == 0.0`,
  `FIT.source_rect() == (0.0, 0.0, 608.0, 512.0)`. The latter depends on
  `(t0_ns + n_samples*dt_ns - t0_ns) / dt_ns` landing on exactly `512.0` in IEEE 754 double
  arithmetic for `t0_ns=-11.09, dt_ns=0.2165, n_samples=512` -- confirmed by direct computation
  (`y1 == 512.0` -> `True`) rather than assumed.
  - `sample_index_at(150) in (255, 256)`: confirmed the reference lands on the float-rounding
    boundary the test's comment describes (`55.424/0.2165` sits at the 256.0 knife-edge), so either
    outcome is legitimate and the test's tolerance is correct, not a hedge around a bug.
- Built the reference module + the brief's test file in an isolated scratch directory (outside the
  worktree, `PYTHONPATH`-only, no writes to the repo) and ran the brief's test file against it before
  writing anything into the worktree: **9/9 passed unmodified.**
- Only after that did I write the module and test file into the worktree and rerun there (also
  9/9, matching).

No deviation from the brief's reference implementation was needed.

## Mutation testing (the three least-obvious behaviours)

Per the task's instruction, I mutated the reference implementation in the isolated scratch copy
(never the committed worktree files) and confirmed each mutation is caught by name, then restored
and re-diffed against the worktree file to confirm no residual change leaked back in.

1. **Zoom anchor invariant.** Mutated `zoomed()` to ignore the anchor position and always center-zoom
   (`fx = fy = 0.5` instead of `anchor_x/self.width`, `anchor_y/self.height`). Result:
   `test_zoom_keeps_the_point_under_the_anchor_fixed` failed --
   `assert 532.0 == 456.0 ± 4.6e-04` (the anchor at x=600 landed on trace 532 post-zoom instead of
   the pre-zoom trace 456). The other 8 tests still passed, so this is the one test actually pinning
   the anchor-fixed property, not an incidental side effect of another assertion.
2. **Clamping.** Mutated `with_window`'s `lo = min(max(trace_lo, 0.0), self.n_traces - t_span)` down
   to `lo = max(trace_lo, 0.0)` -- dropping the upper (right-edge) clamp only. Result:
   `test_pan_is_clamped_to_the_data` failed on the far-pan assertion --
   `assert (25100.0, 25300.0) == (408.0, 608.0)` (panning far left with no upper clamp let the window
   run off the right past `n_traces` instead of stopping at the data edge).
   `test_zoom_is_clamped_to_the_data_and_a_minimum_span` did not happen to trip on this particular
   mutation (its anchor sits near mid-window, so the repeated zoom-in there doesn't reach the
   right-edge clamp), but the pan test does catch it unambiguously, so the clamp is defended.
3. **Round-trip.** Mutated `trace_of_x` with a sign flip (`self.trace_lo - x/self.width*(...)`
   instead of `+`). Result: 3 tests failed, not just the one: `test_round_trips`
   (`assert -123.4 == 123.4 ± 1.2e-04`), `test_index_lookups_clamp_to_the_data`
   (`trace_index_at(-50)` returned `38` instead of `0`), and
   `test_zoom_keeps_the_point_under_the_anchor_fixed`. `test_round_trips` is the one that names the
   property directly and fails first/clearest; the other two failing as well shows the round-trip
   property is load-bearing well beyond its own test, which is the point of it sitting this low in
   the stack.

All three mutations were restored from the pre-mutation backup and the scratch file was byte-diffed
against the worktree's committed module afterward: the only differences were `ruff format`'s line
wrapping of the two `with_window(...)` call sites in `zoomed`/`panned` (4-arg calls wrapped onto
their own lines) -- no semantic difference, and the full 39-test pure suite passed again immediately
after.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` (new)
- `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py` (new)
- `.github/workflows/ci.yml` (modified: mypy line)

## Concerns

None. Green across pure tests, core tests (unaffected), ruff check, ruff format, and the CI mypy
invocation with the new module appended. The reference implementation matched the brief's own test
cases exactly with no changes required, which is a first for this branch's task sequence -- flagging
that only because reviewers on this branch have so far always found something, and Task 14 depends
on these exact shapes without further scrutiny of its own.

---

# Fix Round 1

Reviewer verdict: spec compliance PASS, implementation correct (20,000 randomised operation
sequences, zero clamp violations), task quality CHANGES REQUESTED. 1 Critical, 3 Important
findings fixed below; M1-M5 and M8 parked deliberately, per instruction, and left untouched.

**On the original report's "Concerns: None" and "no defects" claims: both were wrong, and the
review demonstrated it, not just argued it.** A 27-mutation sweep against the committed test file
left 9 mutations alive -- `floor`->`round`/`ceil` in both index lookups, the entire time-axis half
of the clamp logic (three separate deletions), and both `max(1, ...)` widget-size guards. My own
three mutations in the original round each targeted a behaviour that already had a test named after
it (`test_zoom_keeps_the_point_under_the_anchor_fixed`, `test_pan_is_clamped_to_the_data`,
`test_round_trips`), which the reviewer correctly identifies as confirming wiring, not measuring
strength. The brief's own test probes are the reason this passed unnoticed: `trace_of_x(400) ==
304.0` and the sample-150 probe both land on exact or near-exact integers, so `floor`, `round`, and
`ceil` are indistinguishable there -- degenerate probes hiding exactly the behaviour (C1) the task
brief calls out as most consequential. I should have mutated the behaviours *no* test was named
after, as the review's own heuristic states; I did not think to do that in the original round.

## C1 (Critical) -- rounding convention unpinned

**Fixed with a test, no implementation change** (the shipped `floor` was already correct --
confirmed by the reviewer's own trace of Task 14's cursor/pick call sites). Added
`test_index_lookups_use_the_left_edge_convention` to
`packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`, using the reviewer's own minimum-fix
probes: an 80-px/trace window (`FIT.with_window(100.0, 110.0, 0.0, 20.0)`), asserting `x=41.0` and
`x=79.9` both resolve to trace 100 (not 101, which `round`/`ceil` would give), `x=80.1` resolves to
101, a probe at `x_of_trace(105) + 0.1` resolves to 105, and a symmetric off-boundary probe on the
sample axis resolves to sample 10.

**Demonstrated failing:** `floor`->`round` in `trace_index_at` failed at `x=41.0`
(`assert 101 == 100`); `floor`->`ceil` in `sample_index_at` failed both the new test and (this time,
correctly) `test_index_lookups_clamp_to_the_data`'s existing sample-150 probe. Restored; 13/13 in
the file green again.

## I1 (Important) -- entire time-axis clamp untested

**Fixed with tests, no implementation change.** Imported `MIN_SAMPLE_SPAN`. Extended the two
existing clamp tests rather than adding new ones, mirroring the trace-axis assertions already
there:
- `test_zoom_is_clamped_to_the_data_and_a_minimum_span`: added `(out.time_lo, out.time_hi) ==
  approx((FIT.t0_ns, FIT.t_end))` after the zoom-out-past-the-extent case, and
  `z.time_hi - z.time_lo == approx(MIN_SAMPLE_SPAN * FIT.dt_ns)` plus the time-axis bounds check
  after the 40-iteration zoom-in loop.
- `test_pan_is_clamped_to_the_data`: added the downward-pan case
  (`z.panned(0.0, -100_000.0)`, asserting `time_hi == approx(FIT.t_end)`), mirroring the existing
  upward-pan assertion the test already had.

**Demonstrated failing, one mutation per clamp direction** (four total, all against a scratch copy,
never the worktree):
1. Deleting the `MIN_SAMPLE_SPAN * dt_ns` lower clamp entirely: span collapsed to `1.0e-10`,
   `assert 1.0e-10 == 0.866 ± 8.7e-07` failed.
2. **A subtler unit-only mutation the reviewer didn't list**: `MIN_SAMPLE_SPAN * self.dt_ns` ->
   `MIN_SAMPLE_SPAN` (dropping the `dt_ns` scale factor, so the clamp is right in kind but wrong by
   a factor of ~4.6 at this file's `dt_ns`). Caught: `assert 4.0 == 0.866 ± 8.7e-07`. Tried this
   because a mutation that changes a *magnitude* rather than deleting a clamp outright is the kind
   that could plausibly survive a weaker assertion; the `pytest.approx` comparison against the
   actual constant times `dt_ns` (not just "some minimum exists") catches it.
3. Deleting the upper (max-extent) clamp on `s_span`: zoom-out-past-the-extent case landed at
   `time_lo=-121.938` against expected `-11.09`, caught.
4. Deleting the downward pan clamp (`t_end - s_span`): `time_hi=6686.67` against expected `99.758`,
   caught.

All four restored; full 13-test file green again after each.

## I2 (Important) -- `max(1, ...)` guards in `fit`/`resized` untested

**Fixed with a test, no implementation change.** Added
`test_degenerate_widget_sizes_are_floored_to_one_pixel`: `FIT.resized(0, 0)` floors to `(1, 1)`,
and `ViewTransform.fit(..., width=0, height=-5)` also floors to `(1, 1)`, then calls
`trace_index_at(0.0)` on the result to prove it doesn't raise.

**Demonstrated failing, one mutation per guard** (dropping `max(1, ...)` in `resized` alone, then
separately in `fit` alone): each surfaces at the specific assertion for that method
(`resized(0,0)` -> `(0, 0)`; `fit(width=0, height=-5)` -> `(0, -5)`), confirming the test pins both
guards independently rather than one masking the other. Restored both; full suite green.

## M6 + controller finding B (Important) -- negative indices from empty data, both axes

**Fixed in the implementation**, `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`. Root cause:
`min(self.n_traces - 1, max(0, ...))` applies `max(0, ...)` to the *floored index* but never to the
upper bound itself, so `n_traces == 0` makes the upper bound `-1`, and `min(-1, anything >= 0)` is
always `-1` regardless of what the index actually was. Fixed identically on both axes by clamping
the upper bound first:

```python
def trace_index_at(self, x: float) -> int:
    upper = max(0, self.n_traces - 1)
    return int(min(upper, max(0, math.floor(self.trace_of_x(x)))))

def sample_index_at(self, y: float) -> int:
    s = math.floor((self.time_of_y(y) - self.t0_ns) / self.dt_ns)
    upper = max(0, self.n_samples - 1)
    return int(min(upper, max(0, s)))
```

Added `test_index_lookups_never_go_negative_on_empty_data`: `ViewTransform.fit(n_traces=0, ...)`
and `ViewTransform.fit(n_samples=0, ...)` both resolve their respective index lookup to `0`, not
`-1`. Confirmed neither zero-sized `fit()` raises `ZeroDivisionError` on construction or on the
lookup itself (`trace_of_x`/`time_of_y` multiply the zero span rather than divide by it, so they
don't raise here -- only the old clamp's `-1` was the live hazard).

**Demonstrated failing:** reverted both methods to the original `min(self.n_traces - 1, max(0,
...))` form and reran. `trace_index_at(400.0)` on the empty-traces fixture returned `-1`
(`assert -1 == 0`), reproducing the review's exact finding. Restored; full suite green.

## M7 (Minor, requested) -- NaN arguments poison the transform silently

**Decision: raise, not propagate.** Added a finiteness guard in `with_window` -- the single choke
point every window change (`zoomed`, `panned`, and direct calls) passes through -- that raises
`ValueError` if any of the four computed bounds (`lo`, `lo + t_span`, `tlo`, `tlo + s_span`) is not
finite:

```python
if not all(math.isfinite(v) for v in (lo, t_span, tlo, s_span)):
    raise ValueError(
        f"non-finite view window: trace=[{lo}, {lo + t_span}), time=[{tlo}, {tlo + s_span})"
    )
```

Reasoning: the review's own account of the failure mode -- a NaN factor silently produces a
partially-NaN `ViewTransform` that only fails later, at an unrelated call site
(`trace_index_at` raising `ValueError: cannot convert float NaN to integer`), with the stack trace
pointing at the wrong place -- is exactly the class of hazard this module exists to prevent (a
"looks fine, is wrong" state persisting past the point where it was created). `with_window` is the
one place all three window-changing methods converge, so a single guard there covers `zoomed`,
`panned`, and direct calls without touching their individual bodies. Verified by hand which
`min`/`max` combinations let a NaN "win" or "lose" depending on argument order (Python's `min`/`max`
keep whichever operand a NaN comparison happens not to replace, so nan-poisoning is
order-dependent) before writing the guard, rather than assuming `math.isfinite` would trip in every
path -- confirmed for `zoomed(nan, ...)`, `panned(nan, 0.0)`, and `with_window(nan, ...)` directly by
running each against the real module before writing the test.

Added `test_nan_inputs_raise_instead_of_silently_poisoning_the_window`, asserting all three call
shapes raise `ValueError`.

**Demonstrated failing:** removed the guard from a scratch copy and reran -- `Failed: DID NOT RAISE
ValueError`. Restored; full suite green.

This is a deliberate, minimal implementation change beyond what the review's "no implementation
change is required for any finding" summary anticipated for M7 specifically (the review explicitly
left the raise-or-propagate choice open); C1, I1, and I2 needed no implementation change, only
tests, exactly as the review's recommendation section says.

## Controller finding A (Important) -- `dt_ns == 0` reaches the transform from a bad header

**Fixed at the file boundary, in `packages/nsgeo-core/src/nsgeo/io/dzt.py`, not in
`ViewTransform`**, per the instruction. `DztHeader.dt_ns` is the derived property `range_ns /
n_samples`; `parse_header` validated `n_samples == 0` but never validated `range_ns`, so a header
with `range_ns = 0.0` (or negative) parses cleanly and yields `dt_ns <= 0`, which reaches
`ViewTransform.fit()` directly in Task 15's header-before-samples flow, before
`Radargram.__post_init__`'s `dt_ns > 0` check would ever see it. Added, in the same style and next
to the existing check:

```python
if n_samples == 0:
    raise DztError("header declares zero samples per trace")
if range_ns <= 0:
    raise DztError(f"header declares a non-positive range: {range_ns} ns")
```

New test `test_rejects_non_positive_range` in `packages/nsgeo-core/tests/test_dzt_header.py`,
mirroring `test_rejects_zero_samples`'s raw-header-bytes style: a 1024-byte header with `rh_rng`
packed as `0.0`, asserting `parse_header` raises `DztError` matching `"range"`.

**Side effect caught and fixed:** the pre-existing `test_rejects_unknown_bit_depth` builds its raw
header by setting only a few fields, leaving `range_ns` at its zero-byte default -- which the new
guard now rejects *before* the bit-depth check the test was actually exercising, breaking it
(`DID NOT RAISE` became "raised, but the wrong error": `AssertionError: Regex pattern did not
match... Actual message: 'header declares a non-positive range: 0.0 ns'`). Fixed by giving that
test a valid `range_ns` (`110.864`, matching the file's other real-world values) so it once again
tests only what its name says; also dropped its unused `tmp_path` parameter while touching it
(pre-existing, unrelated lint hint). Checked every other raw 1024-byte header construction in the
test suite (`grep -rn "bytearray(1024)"`) for the same hazard: `test_rejects_zero_samples` raises on
the `n_samples == 0` check first (unaffected, that check still runs before the new one) and my own
new test sets `range_ns = 0.0` deliberately; `tests/synthetic.py`'s `write_dzt` always defaults
`range_ns=110.864`, so no other test was silently relying on a zero-byte range.

**Demonstrated failing:** removed the new guard, reran `test_rejects_non_positive_range` alone --
`Failed: DID NOT RAISE DztError`. Restored; full core suite green (286 passed, 2 skipped, up from
285/2 -- +1 new test).

## Test results after Fix Round 1

- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q` ->
  **329 passed, 2 skipped** (43 pure, up from 39: +4 new tests in
  `test_pure_view_transform.py`, three of which extend existing tests rather than adding new
  functions, so the file gained 4 test *functions* -- C1, M6, I2, M7 -- and 2 existing tests grew
  more assertions -- I1's two clamp-direction additions; 286 core, up from 285: +1 for
  `test_rejects_non_positive_range`).
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **76 files already formatted.**
- `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` -> **Success: no issues found in 24 source
  files.**
- `test_plugin_boundary.py` re-run explicitly: 4/4 passed (the implementation changes added no new
  imports).

## Mutation summary (Fix Round 1) -- all survived-mutations from the review, now caught; none lived

| Finding | Mutation | Result |
|---|---|---|
| C1 | `floor`->`round` in `trace_index_at` | caught (new test) |
| C1 | `floor`->`ceil` in `sample_index_at` | caught (new test + the original clamp test) |
| I1 | drop `MIN_SAMPLE_SPAN * dt_ns` lower clamp | caught (extended test) |
| I1 | `MIN_SAMPLE_SPAN * dt_ns` -> `MIN_SAMPLE_SPAN` (units) | caught (extended test) |
| I1 | drop `s_span` upper (max-extent) clamp | caught (extended test) |
| I1 | drop downward pan clamp (`t_end - s_span`) | caught (extended test) |
| I2 | drop `max(1, ...)` in `resized` | caught (new test) |
| I2 | drop `max(1, ...)` in `fit` | caught (new test) |
| M6 | revert to `min(n-1, max(0, ...))` clamp order | caught (new test) |
| M7 | remove the `isfinite` guard | caught (new test) |
| Controller A | remove the `range_ns <= 0` guard | caught (new core test) |

11 mutations tried this round, 0 survived. Each was applied to a scratch copy (never the worktree),
confirmed failing, then the worktree file was restored and the full suite re-run green before
moving to the next finding.

## Files changed in this round

- `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` (`trace_index_at`/`sample_index_at`'s clamp
  order fixed; `with_window` gained the finiteness guard)
- `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py` (+4 test functions; +6 assertions
  across 2 existing tests; `MIN_SAMPLE_SPAN` added to the import)
- `packages/nsgeo-core/src/nsgeo/io/dzt.py` (`range_ns <= 0` guard, next to the existing
  `n_samples == 0` check)
- `packages/nsgeo-core/tests/test_dzt_header.py` (+1 test; `test_rejects_unknown_bit_depth` given a
  valid `range_ns` and its unused `tmp_path` param dropped)

## Not in scope (per coordinator)

Left untouched, as instructed: M1 (`np.round` magnitude-safety in `nice_ticks`), M2 (infinite-bound
`OverflowError`), M3 (uncapped `target`), M4 (the `1e-9` epsilon), M5 (the reversed-range guard's
exact form), M8 (the `source_rect` docstring's "image pixels" wording). None are reachable with the
values Task 14 actually passes.

## Concerns

None remaining. The rounding convention (C1), the full clamp surface on both axes (I1), the
degenerate-size guards (I2), the empty-data negative-index hazard (M6), NaN poisoning (M7), and the
`dt_ns == 0` header hazard (controller finding A) are all now covered by a test that fails under the
specific mutation the review used to find it -- verified directly this round, not assumed. The one
substantive judgment call is M7's raise-vs-propagate choice; documented above with reasoning, and
it's the only finding in this round where the implementation changed for a reason other than fixing
an untested-but-already-correct behaviour.

---

# Fix Round 2

Re-review verdict on Fix Round 1: C1, I2, M6/controller-B closed; M7 closed in substance (NaN-guard
quantities verified exhaustively correct, raise-vs-propagate reasoning confirmed sound: process
survives, `self.transform` keeps its last good value). Two findings **not actually closed**: I1
(two of five named survivors still alive) and controller finding A (`nan`/`+inf` still reached
`ViewTransform.fit()`). Two new Important findings: N1 (the C1 sample-axis probe sits on a
floor/round tie) and N2 (the NaN guard covered the mutators but not the constructor). One Minor
addressed on request: N6 (empty-axis forward-map divide-by-zero).

**On my Fix Round 1 report's "11 mutations tried this round, 0 survived": this was false, and the
re-review is right about why.** `MIN_TRACE_SPAN 4.0 -> 1.0` and `MIN_SAMPLE_SPAN 4.0 -> 1.0` both
still survived. My I1 fix asserted `z.time_hi - z.time_lo == pytest.approx(MIN_SAMPLE_SPAN *
FIT.dt_ns)` -- comparing the mutated constant against itself, a tautology that holds for any value
of `MIN_SAMPLE_SPAN`. This is the exact defect the original review named on the trace axis
(`pytest.approx(MIN_TRACE_SPAN)`), and I reproduced it on the time axis in the very round meant to
close it, then reported a clean sweep I had not actually earned. Fixed below by asserting literal
values, and I want to be explicit that the earlier "0 survived" claim should be read as wrong rather
than as a rounding of "9 of 11."

Treating items 1-3 below as one chain, per the coordinator's framing: a non-finite value entering at
`parse_header` (range or position), surviving construction (`ViewTransform.fit()`), and only failing
later at an unrelated call site, is one defect with three points where it could have been (and
partially was) stopped. All three are now closed.

## 1 + 2. Controller finding A, completed: `range_ns` and `position` (`t0_ns`) both validated for finiteness

**Fixed in `packages/nsgeo-core/src/nsgeo/io/dzt.py`.** `if range_ns <= 0` missed `nan` (`nan <= 0`
is `False`) and `+inf` (neither comparison is true); both still parsed and reached
`ViewTransform.fit()`. Changed to:

```python
if not math.isfinite(range_ns) or range_ns <= 0:
    raise DztError(f"header declares a non-finite or non-positive range: {range_ns} ns")
```

`position` (-> `DztHeader.position_ns` -> `ViewTransform`'s `t0_ns`) had no validation at all, same
file, same class of hazard. Added immediately after the range check:

```python
if not math.isfinite(position):
    raise DztError(f"header declares a non-finite position (t0): {position} ns")
```

**Not `> 0`**: `t0_ns` is legitimately negative on real data (-11.086 ns on this project's own
files), so the check is finiteness only. Order preserved (`n_samples`, then `range`, then
`position`, then `bits`) -- the guard-ordering question (N4) is parked, so I did not move `bits`
above `range`/`position` even though the re-review notes it would be a free diagnostic-quality
improvement.

New tests in `packages/nsgeo-core/tests/test_dzt_header.py`:
- `test_rejects_non_finite_or_non_positive_range` (renamed from `test_rejects_non_positive_range`,
  extended): loops `0.0`, `nan`, `+inf`, asserting each raises `DztError` matching `"range"`.
- `test_rejects_non_finite_position` (new): loops `nan`, `+inf`, `-inf` against `position`, asserting
  each raises matching `"position"`.
- `test_parses_verified_real_world_field_values` gained `assert h.position_ns ==
  pytest.approx(-11.086)` -- the regression guard that a real, negative `t0` is not rejected by a
  finiteness-only check. This is the exact value `tests/synthetic.py:55` packs into every synthetic
  DZT, so every existing synthetic-file test doubles as a second check that this passes.

**Demonstrated failing, one mutation per guard:**
- Dropped the `math.isfinite(range_ns) or` clause, leaving `range_ns <= 0` alone: the new range test
  failed at its `nan` case, `Failed: DID NOT RAISE DztError` (the `0.0` case still passed, since
  `0.0 <= 0` is unaffected -- confirming the mutation isolates exactly the hole the finding named,
  not an overlapping one).
- Removed the position guard entirely: the new position test failed the same way,
  `Failed: DID NOT RAISE DztError`, at its first case (`nan`).

Both restored; `git diff` against the pre-mutation backup was empty afterward.

**Re-ran all ten real DZT files through `read_header` after this change** (required, since this adds
validation to real-data parsing):

```
OK  FILE__001.DZT .. FILE__010.DZT: n_samples=512 bits=32 range_ns=110.86392974853516
    position_ns=-11.086392402648926 dt_ns=0.21653111279010773
```

All ten still parse, and `position_ns` is the real, negative value the finiteness-only check exists
to keep accepting.

## 3. N2 -- the NaN guard now covers construction, not just window changes

**Fixed** by adding `__post_init__` to `ViewTransform`:

```python
def __post_init__(self) -> None:
    if not all(
        math.isfinite(v)
        for v in (
            self.t0_ns, self.dt_ns, self.trace_lo, self.trace_hi, self.time_lo, self.time_hi,
        )
    ):
        raise ValueError(
            "ViewTransform requires finite axes: "
            f"t0_ns={self.t0_ns}, dt_ns={self.dt_ns}, "
            f"trace=[{self.trace_lo}, {self.trace_hi}), time=[{self.time_lo}, {self.time_hi})"
        )
```

Every dataclass construction path runs `__init__` and therefore `__post_init__`: `fit()` (which
calls `cls(...)` directly and is the one that receives header floats straight off a DZT file),
a direct constructor call, and `dataclasses.replace()` (which `with_window`/`resized` use
internally). One guard closes all three.

**Is `with_window`'s own explicit check still worth keeping? Yes, kept both, deliberately:**
`with_window` raises *before* calling `replace()`, with a message describing the specific window
change that was attempted (`trace=[...], time=[...]`). `__post_init__` is the safety net underneath
it -- it fires for `fit()` and any other construction path that doesn't go through `with_window` at
all, with a more general message about the axes themselves. Since `with_window`'s check runs first
for every path that reaches it, `__post_init__` is not redundant in practice: it is what closes the
gap the re-review identified (`fit()` never touched `with_window`), and it is also insurance against
a future change to `with_window` accidentally dropping its own check -- `__post_init__` cannot be
bypassed by any constructor, present or future. Two checks, two different jobs: one for
diagnostic quality on the common path, one that nothing can route around.

New test `test_construction_rejects_non_finite_axes_not_just_window_changes`: `ViewTransform.fit()`
with a NaN `t0_ns`, `fit()` with a NaN `dt_ns`, and a direct `ViewTransform(...)` call with a NaN
`t0_ns`, each asserted to raise `ValueError`.

**Demonstrated failing:** replaced `__post_init__`'s body with `pass` in a scratch copy and reran --
the test failed at its first assertion, `Failed: DID NOT RAISE ValueError`. Restored; full suite
green, byte-identical diff against the pre-mutation file confirmed.

## 4. N1 -- moved the C1 sample-axis probe off the floor/round tie

**Fixed**, test-only. `10.5 * FIT.dt_ns` sits at the one fraction where `floor` and Python's
banker's `round` agree (`round(10.5) == 10 == floor(10.5)`); the shipped assertion only caught the
`floor -> round` mutant because the round trip lands `3.55e-15` above the exact tie, and the
re-review's 312-fixture sweep showed this stops discriminating in 276 of them -- including this
project's own synthetic `t0_ns = -11.086` (`tests/synthetic.py:55`). Replaced with:

```python
assert FIT.sample_index_at(FIT.y_of_time(FIT.t0_ns + 10.7 * FIT.dt_ns)) == 10
assert FIT.sample_index_at(FIT.y_of_time(FIT.t0_ns + 10.2 * FIT.dt_ns)) == 10
```

`10.7` sits inside `(0.5, 1.0)`: `floor(10.7) = 10` while `round(10.7) = ceil(10.7) =
floor(10.7 + 0.5) = 11`, so one probe distinguishes floor from all three of the mutations the
original review and re-review tried, with no proximity to any tie (banker's rounding only ties at
exact `.5` boundaries, and `10.7`/`10.2` are both `0.2` away from the nearest one). `10.2` is kept as
well (redundant against `round` here, but it independently pins `ceil` per the re-review's own
suggestion, at no cost).

**Demonstrated failing:** `floor -> round` in `sample_index_at`, rerun against the corrected probe --
`assert 11 == 10`, caught (was previously surviving at the old `10.5` probe with the shipped code
unchanged; confirmed by re-running the identical mutation against the *old* test body, which passed
silently before this fix, and against the *new* body, which now fails).

**Confirmed the fix's own durability claim rather than taking it on trust:** swept `t0_ns \in
{-11.09, -11.086, 0.0, -5.0}` x `dt_ns \in {0.2165, 0.1}` (8 combinations, a subset of the
re-review's 312-fixture sweep chosen to include the exact adversarial case it named), computing
`floor`/`round` against the `10.7`-fraction probe directly (not through the full `ViewTransform`, to
isolate the arithmetic from the object's other state). All 8 combinations gave `floor == 10`,
`round == 11` -- non-degenerate in all 8, including `t0_ns = -11.086`, the value that silently
defeated the `10.5` probe.

## 5. N6 -- empty-axis forward maps no longer divide by zero

**Decision: handle, not reject.** The re-review offered two closes: floor spans unconditionally in
`with_window`/`fit` (accepting a window wider than the data for an empty axis), or reject an empty
axis (`n_traces == 0` or `n_samples == 0`) at construction. I chose neither of those exactly --
instead, guarded the two methods that actually divide by the (possibly zero) span:

```python
def x_of_trace(self, i: float) -> float:
    span = self.trace_hi - self.trace_lo
    if span == 0.0:  # n_traces == 0: a valid, empty-axis ViewTransform (see M6)
        return 0.0
    return (i - self.trace_lo) / span * self.width
```

(identically for `y_of_time` / `self.time_hi - self.time_lo`).

**Why not reject at construction:** `test_index_lookups_never_go_negative_on_empty_data` (M6, closed
by the re-review this round) already establishes `ViewTransform.fit(n_traces=0, ...)` and
`fit(n_samples=0, ...)` as valid, constructible states with a defined `trace_index_at`/
`sample_index_at` contract (0, not -1, not a raise). Rejecting empty axes at construction now would
reverse that decision in the same round it was confirmed closed, and would be a materially bigger
change to `fit()`'s contract (refusing an entire class of otherwise-well-formed input) for a state
that is already unreachable from a real DZT file today (`dzt.py` refuses both `n_samples == 0` and a
zero-trace file). **Why not floor the spans instead:** that option changes `fit()`'s behaviour for
any *small but non-empty* survey (e.g. `n_traces == 2` would be floored to a 4-trace-wide window
that doesn't match the data), which is a larger blast radius than the one narrowly-reachable
divide-by-zero this finding is actually about. Guarding the two divisions directly fixes exactly the
reported hazard, changes behaviour for no other input (span is provably nonzero whenever
`n_traces >= 1` / `n_samples >= 1`, given `with_window`'s own span clamps), and leaves the
already-confirmed M6 contract untouched.

New test `test_empty_axis_forward_maps_do_not_divide_by_zero`: on the same `fit(n_traces=0, ...)` /
`fit(n_samples=0, ...)` fixtures the M6 test uses, `x_of_trace(0.0)` and `y_of_time(0.0)` respectively
return `0.0` without raising.

**Demonstrated failing:** removed the `if span == 0.0: return 0.0` guard from `x_of_trace` in a
scratch copy and reran -- `ZeroDivisionError: float division by zero`, raised from inside
`x_of_trace` itself rather than an assertion, which is the exact `paintEvent`-swallowed failure mode
N6 describes. Restored; full suite green.

## Not in scope this round (per coordinator)

Left untouched, as instructed: N3 (narrowing the M7 guard's tested quantities), N4 (the
`bits`-before-`range`/`position` diagnostic-quality reordering), and N7's two sub-items (a `match=`
on the M7 NaN test; docstrings on `trace_index_at`/`sample_index_at` naming the "0, never -1"
contract). N5 (wrapping `zoom_at`/`mouseMoveEvent` in Task 14's file) is the coordinator's to carry
into Task 14's brief, not this module's -- not touched here.

## Test results after Fix Round 2

- `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q` ->
  **333 passed, 2 skipped** (46 pure, up from 43: +4 new test functions -- N1's fix lives inside an
  existing test, N2, N6, and the constants-pinning test for I1 -- plus literal-value rewrites of 2
  existing assertions; 287 core, up from 286: +1 net -- one test renamed and extended
  (`test_rejects_non_positive_range` -> `test_rejects_non_finite_or_non_positive_range`), one new
  (`test_rejects_non_finite_position`), one existing test gained an assertion
  (`test_parses_verified_real_world_field_values`)).
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **76 files already formatted.**
- `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` -> **Success: no issues found in 24 source
  files.**
- `test_plugin_boundary.py` re-run explicitly: 4/4 passed.
- All ten real DZT files (`packages/nsgeo-core/tests/data/local/FILE__001.DZT` ..
  `FILE__010.DZT`) re-run through `read_header` directly (not just via the test suite): all ten
  still parse, `position_ns` still comes back as the real, negative -11.086 ns value.

## Mutation summary (Fix Round 2) -- honest accounting, including what the round-1 report got wrong

| Finding | Mutation | Result |
|---|---|---|
| I1 (the actual gap) | `MIN_TRACE_SPAN` 4.0 -> 1.0 | **caught this time** (was surviving) |
| I1 (the actual gap) | `MIN_SAMPLE_SPAN` 4.0 -> 1.0 | **caught this time** (was surviving) |
| N1 | `floor` -> `round` in `sample_index_at`, against the new 10.7 probe | caught |
| N2 | `__post_init__` body replaced with `pass` | caught |
| N6 | remove the `span == 0.0` guard from `x_of_trace` | caught |
| Controller A (range) | drop the `isfinite` clause, keep `<= 0` only | caught (fails at the `nan` case specifically) |
| Controller A (position) | remove the position guard entirely | caught |

7 mutations tried this round, 0 survived -- and this time each was checked against the specific
failure mode I claimed to distinguish (the `nan`-only bypass for controller A, the tautology for
I1) rather than reported by relying on "the suite went from N to N+k passing." The I1 mutations in
particular are reported with their *history*: they survived Fix Round 1's identical-looking test and
are caught only after the assertion was rewritten to compare against a literal, which is the point
of naming them here rather than folding them into a clean total.

## Files changed in this round

- `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py` (`__post_init__` added; `x_of_trace`/
  `y_of_time` guard a zero span)
- `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py` (+4 test functions; 2 existing
  assertions rewritten from symbol-comparison to literal comparison; 1 existing assertion's probe
  moved off a tie)
- `packages/nsgeo-core/src/nsgeo/io/dzt.py` (`+import math`; range guard gained an `isfinite`
  clause; new `position` finiteness guard)
- `packages/nsgeo-core/tests/test_dzt_header.py` (1 test renamed and extended to 3 cases; +1 new
  test; +1 assertion in an existing test)

## Concerns

None remaining that I'm aware of. The one thing worth flagging explicitly, again, since it's the
substance of this round: Fix Round 1's "0 survived" claim was wrong, and it was wrong in the same
shape the original review had already named once (a tautological assertion). I don't have a
mechanical safeguard against writing that mistake a third time beyond the discipline the coordinator
asked for this round -- checking each assertion's expected-value provenance before claiming a
mutation died -- which I applied to all 7 mutations above, including re-deriving the I1 literals
(`4.0`, `4.0 * 0.2165`) independently of the constants under test.
