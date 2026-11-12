# Task 2 report: per-line values in nsgeo-core

**Status: DONE_WITH_CONCERNS.** Commit `edc6691` on `nsgeo-auto-destagger`, pushed (bc80ffb..edc6691).
Four spec tolerances are strict xfails with measured numbers (ruling 2). Three come from one cause found in
the data (FILE__031's own hidden residual), and one from evidence that contradicts the FILE__027 pin. Details
are under *Concerns* below.

## Method (and why)

Code: `packages/nsgeo-core/src/nsgeo/destagger/per_line.py` (new); `profiles.py` and `measure.py` (changed).

**1. Pair curves, not per-line curves** (`profiles.pair_curves`, `PairCurves`).
- Each pair of neighbouring opposite-direction lines is compared once by FFT, and the curve is kept per time
  bin and per half of the axis (first and second), over ±3× the search range.
- A line's curve against the mean of its neighbours is the mean of its two pair curves (correlation is linear).
- Correcting a line just shifts its pair curves, so a re-measure costs microseconds.
- Checked against recomputing profiles with the corrected placement: they agree exactly at whole 2 cm steps.
  At half a step, recomputing itself moves residuals by up to 1.6 cm (resampling phase), so shifting is as
  accurate as recomputing.
- Lines are visited in offset order, and only the previous line's FFTs are held. Peak traced memory on Grid 1
  is 19.8 MB, against 110 MB in Task 1. Pinned by a test at < 40 MB.

**2. The grid value is unchanged.**
- It is the raw mean of the line curves, as in Task 1. Values and spreads are identical to Task 1 to within
  1e-15 on all four cases.
- Its clear test now uses the normalised mean (see 3).

**3. Strength is a correlation coefficient** (`PairCurves.normalised`): the curve divided by sqrt(E_a·E_b),
each line's energy over its own valid part (or half).
- A real line paired with itself reads exactly 1.0 over the whole record and over either half (new test).
  Under the old 1/axis-length scaling a half read about 0.5.
- `MIN_CORRELATION` is now 0.10 in these units. The real grids' normalised grid curves peak at 0.27–0.43;
  unrelated lines (G1/G2 alternating) peak at 0.036–0.05.
- `is_clear(curve, min_correlation=, ratio=)` takes the normalised curve.

**4. Per-line classification** (`_Solver.classify`). Each line is read against its neighbours, with their
current own corrections applied and its own removed. It is read from five parts: the whole record, shallow,
deep, first half along and second half along.
- **NO_MATCH** if the whole-record peak is not clear.
- **CHANGES** if both along halves are *decisive* and differ by more than `CHANGE_M`. Decisive means
  `is_clear` with rival ratio 0.6.
- **Candidate** if |u| ≥ `MIN_OWN_M`, a pair of halves is clear and agrees within
  tol = max(`AGREE_M`, `AGREE_FRACTION`·|u|), and no decisive half differs from u by more than tol.
  The C13 reading: a half without a clear peak neither confirms nor counts against; a decisive half counts
  against.
- **GRID** otherwise.

**5. Joint solve** (`_Solver.solve_run`). Each run of adjacent candidates is solved by an exact Viterbi search
along the run.
- Each line's correction is either 0 or at least `MIN_OWN_M` (2 cm states).
- The score is the sum of the normalised pair matches at zero lag after correction, minus `OWN_GAIN` per own
  value. The lines either side of the run are held.
- Each own value is then refined to the parabola peak of its own corrected curve.
- Holding the run's ends means no net trend across the run can be absorbed, so a skew or an angled feature is
  not "straightened".

**6. Passes** (`_Solver.run`), up to `MAX_PASSES` = 8; the Nashville grids settle in 1–3.
- Start from the strict candidates at zero correction.
- Each pass: solve, re-read every line, then:
  - drop for good any own line that no longer qualifies (or fell under `MIN_OWN_M`);
  - add any line that now qualifies, for example one that read as two-peaked while its neighbour was
    uncorrected.

**7. Shallow/deep split** (`_depth_split`). Split where each half holds half the grid's evidence: per-bin
correlation between neighbours at the grid value, averaged over pairs. It falls at 36.4 ns on Grid 1, 24.3 ns
on Grid 2 unfitted and 27.8 ns on Grid 2 fitted. It adapts to the antenna and record, as constraint §11 asks.
The prototype's fixed 25 ns and 20 ns also pass; the bin-count median (31 ns) and 30 ns lose FILE__059 fitted.

### Why the prototype read −0.43 for a −0.50 move

It was not end trims, filters or the loop stopping early.
- FILE__031 already sits **+0.052 m** ahead of its neighbours before any move. Its halves agree: shallow
  +0.04, deep +0.09, first +0.04, second +0.13.
- That is below any sane own-value threshold, so its base value is the grid value.
- A moved line's own curve shifts exactly with the move, so its value is grid − (d + 0.052).
- The rest of the prototype's error came from its linear block solve on peak positions. When neighbours are
  two-peaked, that solve lets them absorb part of the move ("dragging").

The built solve recovers the move itself to 0.004 m: the +0.30 and −0.50 results differ by −0.796. Against the
spec target (base − d) it misses by the hidden 0.052, plus 0.001–0.003 because the grid value moves.

### Tried and dropped (all in the scratchpad)

- **Linear block solve (prototype style) and the exact solve on raw pair curves with greedy one-at-a-time
  pruning.** Same results as each other. Pruning order decided which alternate lines in a block kept values,
  and a 0.02 m/line skew flipped Grid 1 012/014 ↔ 013/015 (P9 fail).
- **A soft solve where small corrections are free** (to let regional blocks dissolve). It smears a single off
  line into two sub-threshold halves: FILE__051 0.24 → 0.14 + 0.08, FILE__059 −0.22 → −0.10 − 0.14. That loses
  pinned lines.
- **Adding non-candidate neighbours to the free set, with a higher penalty.** Messy stretches then got
  three-line explanations that flipped on borderline verification (fitted 008/010/011). The pass loop finds
  hidden lines without it.
- **Run-level identifiability checks (leave-one-out, leave-all-out score gaps).** Too narrow a margin between
  blocks (0.10) and the real pinned lines (0.13).
- **Tying `CHANGE_M` to 0.20.** It names 9–10 lines CHANGES on Grid 2.
- **Fixing the skew flips structurally.** The remaining flips sat on binary thresholds:
  - Grid 1 015's first half was only just clear, so CHANGES flipped. Fixed by a decisive ratio for CHANGES.
  - 047's and fitted 009's half agreement sat at 0.10–0.12, against a tolerance of 0.10. Fixed by
    `AGREE_M` 0.15 and a decisive-half veto.

## Thresholds (module constants, comments say what they were tuned on)

Tuned on Grids 1 and 2, unfitted and fitted, with the injected moves and the skew. A one-at-a-time sweep found
the range where *every* real-data test still passes.

| Constant | Value | Passing range |
|---|---|---|
| `per_line.MIN_OWN_M` | 0.15 | 0.12–0.18 (0.20 fails P9 on G1u FILE__060) |
| `per_line.AGREE_M` | 0.15 | 0.10–0.18 as veto limit (0.20 fails P9 on G1f FILE__009), 0.12–0.25 to confirm |
| `per_line.AGREE_FRACTION` | 0.3 | 0.3–0.4 (0.2 loses FILE__045) |
| `per_line.CHANGE_M` | 0.30 | 0.25–0.40 |
| `per_line.DECISIVE_RATIO` | 0.6 | 0.5–0.7 |
| `per_line.OWN_GAIN` | 0.02 | 0–0.05 (0.10 fails P9) |
| `per_line.MAX_PASSES` | 8 | settles in 1–3 |
| `profiles.MIN_CORRELATION` | 0.10 (normalised) | per-line 0.06–0.12 (0.14 loses FILE__051) |
| `profiles.CLEAR_RATIO` / `SHOULDER_M` | 0.8 / 0.12 (unchanged) | ratio 0.7–0.9 |
| `profiles.PAIR_LAG_FACTOR` | 3 | the shift budget: grid + two own values |

## TDD evidence

**RED, test file** (`test_destagger_lines.py`):
```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests/test_destagger_lines.py packages/nsgeo-core/tests/test_destagger_grid.py -q -p no:cacheprovider
E   ImportError: cannot import name 'pair_curves' from 'nsgeo.destagger.profiles'
1 error in 0.49s
```

**RED, behaviour** (a scratchpad copy without the new import, run against Task 1 code):
```
16 failed, 9 passed, 4 xfailed
```
- The failures are the own-value and status tests (`GRID is OWN`, `GRID in (CHANGES, NO_MATCH)`), the memory
  test, and the `is_clear` tests (TypeError: new signature).
- The 9 that pass are the shares, skew, neighbour and determinism tests, which hold trivially when there are
  no own values.

**RED, grid file:**
```
test_should_stop_is_honoured_in_the_per_line_passes
E  assert 361 >= (360 + 60)
1 failed, 22 passed
```

**GREEN, both files:**
```
49 passed, 4 xfailed in 42.05s
```
Since then the stage-boundary test was added (1 more pass). With `--runxfail`, each xfail fails on exactly its
stated assertion: −0.1998 vs −0.1483 ±0.05; +0.5961 vs +0.6517; −0.2184 vs −0.1483; FILE__027 NO_MATCH.

**Full core+pure:**
```
1280 passed, 5 skipped, 4 xfailed in 92.83s
```
The baseline was 1253 passed and 5 skipped; skips are unchanged.

Lint and format: `All checks passed!` / `190 files already formatted`. Types: `Success: no issues found in 49
source files`, using CI's list. `destagger_job.py` (in the constraints' command) does not exist until Task 3.

## Results (also in the spike note, "Per-line results (built)")

| Grid | Lines | Grid value (± spread) | OWN | CHANGES | NO_MATCH | NOT_MEASURED |
|---|---|---|---|---|---|---|
| 1 | unfitted | +0.152 (±0.013) | 4 | 7 | 4 | 0 |
| 1 | fitted | −0.066 (±0.008) | 0 | 1 | 4 | 0 |
| 2 | unfitted | +0.162 (±0.019) | 9 | 2 | 7 | 0 |
| 2 | fitted | −0.061 (±0.010) | 5 | 4 | 1 | 0 |

Own values (offset from the grid value in brackets):
- **G1 unfitted:** FILE__013 +0.351 (+0.200), FILE__015 +0.405 (+0.253), FILE__047 +0.364 (+0.213) and
  FILE__060 −0.065 (−0.217).
  - CHANGES: FILE__002, 008, 009, 024, 027, 036 and 048.
  - NO_MATCH: FILE__001, 011, 026 and 028.
- **G1 fitted:** none.
  - CHANGES: FILE__024.
  - NO_MATCH: FILE__001, 002, 028 and 029.
- **G2 unfitted:**
  - FILE__015 −0.011 (−0.173) and FILE__022 +0.332 (+0.170);
  - FILE__028 +0.687 (+0.525) and FILE__032 +0.489 (+0.327);
  - FILE__034 +0.612 (+0.450) and FILE__042 +0.448 (+0.286);
  - FILE__045 +0.884 (+0.722), FILE__052 +0.329 (+0.166) and FILE__056 +0.505 (+0.343).

  CHANGES: FILE__046 and 060. NO_MATCH: FILE__026, 027, 043, 047, 048, 049 and 050.
- **G2 fitted:**
  - FILE__001 −0.214 (−0.152) and FILE__004 +0.132 (+0.193);
  - FILE__045 +0.406 (+0.467) and FILE__051 +0.173 (+0.234);
  - FILE__059 −0.288 (−0.227).

  CHANGES: FILE__022, 027, 049 and 060. NO_MATCH: FILE__050.

Against the prototype:
- FILE__045 +0.884 (+0.881) and FILE__028 +0.687 (+0.687);
- FILE__051 +0.173 (+0.147) and FILE__059 −0.288 (−0.287).

On Grid 2 unfitted, 9 of 60 lines are OWN (15%; the prototype had 15, 25%).

## Spec tolerances

| Test | Met? | Numbers |
|---|---|---|
| Single +0.30 within 0.05 of base − 0.30 | **No (xfail)** | −0.200 vs −0.148: 0.052 (the hidden residual) |
| Single −0.50 within 0.05 of base + 0.50 | **No (xfail)** | +0.596 vs +0.652: 0.056 (0.052 + grid moves 0.003) |
| Neighbours keep status, values within 0.02 | Yes | 030, 032 (and 033) stay GRID; move 0.001 / 0.003 |
| Move recovered relative to the line's own residual (added) | Yes | +0.30 and −0.50 results differ by −0.796 (target −0.80 ±0.01) |
| Two adjacent +0.30, each within 0.05 | **FILE__031 no (xfail), FILE__032 yes** | 031 −0.218 vs −0.148 (0.070); 032 −0.114 vs −0.148 (0.034) |
| Skew (P9), unfitted and fitted | Yes | The grid moves +0.0005 / +0.0008. Unfitted: the same 4 own lines, within 0.020. Fitted: none. Nothing created or removed. |
| Grid 1 not-OWN share (≥80%, pinned ≥85%) | Yes | 93% unfitted, 100% fitted |
| Unfitted FILE__011 not OWN | Yes | NO_MATCH |
| Grid 2 045/028 OWN > grid + 0.25; sizes pinned ±0.03 | Yes | +0.884, +0.687 |
| Grid 2 027 OWN > grid + 0.25 | **No (xfail)** | NO_MATCH (evidence below) |
| Grid 2 051 > grid + 0.10, 059 < grid − 0.10; ±0.03 | Yes | +0.173 (grid −0.061), −0.288 |
| Fitted FILE__050 not OWN | Yes | NO_MATCH |
| Grid 2 not-OWN share (≥70%, pinned ≥80%) | Yes | 85% unfitted, 92% fitted |
| Deterministic | Yes | Grid 2 fitted, twice, `==` |

### The hard case, −0.50 beside +0.30 (measured, not pinned)

| Case | FILE__031 | FILE__032 | Neighbours |
|---|---|---|---|
| 031 −0.50, 032 +0.30 | +0.578 OWN (target +0.652, off −0.074) | −0.114 OWN (target −0.148, off +0.034) | 030 and 033 stay GRID, +0.002 |
| 031 +0.30, 032 −0.50 | −0.224 OWN (target −0.148, off −0.076) | +0.686 OWN (target +0.652, off +0.035) | stay GRID, +0.003 |

Both are recovered as well as the single moves. FILE__031's error is again its +0.052 residual plus about
0.02. The prototype gave −0.42 / +0.25 in the first ordering.

## Test runtimes

- `test_destagger_lines.py` with `test_destagger_grid.py`: 42 s for 53 tests. That includes reading 120 DZT
  files the first time (about 20 s), shared through the session cache.
- Each full 60-line measurement takes about 0.6–0.9 s, of which the per-line step is 0.03–0.04 s.
- Module-scoped fixtures measure each base and injected case once.
- The slowest tests are the fixture set-ups that first read the files (12.8 s and 11.4 s) and the
  per-line-passes stop test (2.0 s).

## Files changed

- `packages/nsgeo-core/src/nsgeo/destagger/per_line.py`: new, the per-line solve.
- `packages/nsgeo-core/src/nsgeo/destagger/profiles.py`:
  - `pair_curves`, `PairCurves`, `line_curves` and `PAIR_LAG_FACTOR`, replacing `lag_curves`;
  - normalised `MIN_CORRELATION`;
  - `is_clear(curve, min_correlation, ratio)`;
  - `grid_peak(curves, normalised, boot)`;
  - the unused `along_range` dropped from `line_profiles`.
- `packages/nsgeo-core/src/nsgeo/destagger/measure.py`: streams pair curves, then calls `per_line_values`; OWN,
  CHANGES, NO_MATCH and GRID results. The extra check after the lag curves is gone.
- `packages/nsgeo-core/tests/test_destagger_lines.py`: new, 30 tests including the 4 strict xfails.
- `packages/nsgeo-core/tests/test_destagger_grid.py`:
  - `test_every_measured_line_gets_the_grid_value` removed;
  - the stop test reworked into named fixed stages plus a per-line-passes test;
  - a test that pins the stage boundaries (calls 240/300 and the per-line start), closing Task 1's
    "placement assumed, not enforced" minor.
- `packages/nsgeo-core/README.md`: the `measure_destagger` row says what a line's result is.
- `docs/superpowers/notes/2026-11-11-destagger-measure-spike.md`: new section "Per-line results (built)", with
  file names and metres only.

## Task 1 findings carried here

- **`MIN_CORRELATION` depended on length:** fixed by normalising; tested by a line paired with itself (1.0
  over the record and each half).
- **Memory:** lines are streamed. 110 MB → 19.8 MB on Grid 1, and the test bounds it at 40 MB.
- **`is_clear` branch tests:** six hand-made-curve tests cover the edges, strength, rival, shoulder and the
  `ratio` parameter.

## Self-review

- **Brief coverage:** every test in Step 1 exists.
  - The single-move tests are split: the recovery assertion (xfail) and the neighbour assertion (passes), so
    the part that holds stays asserted.
  - The adjacent test is parametrised per line, so FILE__032 passes while FILE__031 is xfailed.
  - One companion test was added (the difference of two moves), without loosening anything.
  - Step 5 (spike note) and Step 6 (commit, push) are done.
- **Names:** British spelling and plain words, matching Task 1.
- **No new public names.** `per_line` is internal; `LineVerdicts` is returned to `measure` only.
- **YAGNI:** removed the dead `along_range` and the unused `self.max_lag`; no neighbour-expansion or ambiguity
  machinery left in. `OWN_GAIN` is kept, as a stated tie-break towards fewer own values.
- **Determinism:** no randomness in the per-line step; ties prefer "no own value" (state 0 is first);
  iteration is over sorted indices.
- **`should_stop`:** called once per line in every per-line loop: the first reading, each re-read, the Viterbi
  steps and assignment, and the refinement.
- **Status semantics as ruled:**
  - OWN = grid + own correction;
  - CHANGES and NO_MATCH = the grid value;
  - NOT_MEASURED = None, unchanged;
  - sign = grid − r. Checked: FILE__031 moved +0.30 gets grid − 0.35.
- **Pristine output:** the test run prints nothing besides pytest's summary.

## Concerns (for C14)

1. **Three injected-error tolerances are unmeetable as written** (strict xfails). FILE__031's own +0.052 m
   residual sits below the threshold in the base run, so its base value is the grid value. Once moved, its own
   value rightly corrects that 0.052 too.
   - The move itself is recovered to 0.004 m.
   - Question for the author: should the tests compare against the line's own residual (the companion test),
     or should the target stay "base − d" with these xfails?
2. **FILE__027 (Grid 2 unfitted) gets no own value; the spec pinned it** (strict xfail).
   - The 027–028 pair reads −0.52 m (searched to ±2 m), so 027 and 028 are not both 0.5 m off.
   - On the strong reflector at about 8.8 m, moving only 028 (+0.525) lines up 027–030 within about 0.15 m.
   - The prototype's 027 +0.50 puts it 0.35 m out of line.
   - My stacked-profile plot: `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/0cbbd721-3d42-4127-ad2b-7732618f3426/scratchpad/t2/w_g2u_27.png`.
     It is a picture of the site, so scratchpad only; the coordinator may show it to the author.
   - 027 may deserve a small own value of about +0.15 (its residual after 028 is corrected), but its other
     neighbour 026 matches nothing clearly.
3. **Blocks of adjacent lines that are all off the same way are ambiguous.** "Alternate lines off by d" fits
   the pair data as well as "every line off by d/2".
   - The solve picks alternate lines. Examples: Grid 2 unfitted FILE__032/034 (with 033 left) and 042; Grid 1
     unfitted 013/015 (012/014 left).
   - These are stable under the skew but not identifiable in principle.
   - The author should judge 032–034 and 040–042 (Grid 2 unfitted) and 012–015 (Grid 1 unfitted) on the C14
     pictures. On fitted Grid 1 these residuals mostly vanish: they are wheel error, which fitting removes.
4. **Grid 1 unfitted names 7 lines CHANGES** (002, 008, 009, 024, 027, 036, 048).
   - Their two along halves read decisively different values; often the first half has few features, as the
     spike predicted for 8 and 9.
   - The summary will list them, capped at 6 plus "and 1 more" (P12). Raising `CHANGE_M` to 0.40 still passes
     every test, if the author finds this too chatty.
5. **Fitted Grid 1 lines 8 and 9 get no own value** (+0.25 in the second half, about 0 in the first). A single
   shift would move the first half the wrong way. The spec left this open.
6. **The shallow/deep split is a new data-driven rule,** not in the spec: half the grid's evidence on each
   side. A fixed 30 ns would lose FILE__059.
7. **The constraints' types command names `nsgeo_qgis/destagger_job.py`, which Task 3 creates.** I ran CI's
   current list.
8. **Re-reading by shifting is approximate for the along halves.** Their masks are fixed on the axis, so
   features within a correction's length of the midpoint move between halves. The effect is negligible next
   to the 0.15 m threshold, but it is not exact.

## Fix round 1

Commit `770c7e0` (FIX_BASE `edc6691`), pushed. No tolerance was changed. Per-line results are unchanged on all
four cases: the same own lines and values, and the same grid values.

The scratch proofs were run against copies, never the worktree. They live under
`/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/0cbbd721-3d42-4127-ad2b-7732618f3426/scratchpad/t2/fix1/`:
`a/` holds the edited test copies; `viterbi/`, `refine/` and `oldbranch/` hold mutated source copies.

### Important 1: the FILE__027 strict xfail could never XPASS

- **Change:** `tests/test_destagger_lines.py:219` pins FILE__027 at the prototype's +0.665, not `None`. The
  `SIZE_TOL` comment says why.
- **Proof** (`fix1/a/`): the grid2_unfitted fixture was patched to force FILE__027 to OWN at +0.665.
  - New pin: `[XPASS(strict)] … 1 failed`, so strict now fires.
  - Old pin (`None`), same forced result: `XFAIL … 1 xfailed`, i.e. stuck as "expected" before.
- Per the controller ruling, the xfail stays; the author decides at C14.

### Minor 1: `raises=AssertionError` on all four xfails

- **Change:** `tests/test_destagger_lines.py:102, 116, 154, 222`.
- **Proof** (`fix1/a/test_typeerror*.py`): an unrelated `moved.destagger + None` was inserted into
  `test_a_line_moved_forward_is_recovered`.
  - With `raises=`: `FAILED … TypeError: unsupported operand type(s) for +: 'float' and 'NoneType'`.
  - Without it: `XFAIL`, so the bug was swallowed.

### Minor 2: should_stop once per line in every per-line loop, and checks pinned in the solve

Checks were added:
- `profiles.py:257`: `line_curves`. It now returns raw and normalised curves in one loop, one check per line;
  `measure.py:241` calls it once.
- `per_line.py:137`: `_depth_split`, now a loop over the lines in offset order.
- `per_line.py:156`: the pair-curve cache, moved to its own method `_cache_curves`, a loop over the lines.
- `per_line.py:263`: `runs()`.

Inside the solve:
- `solve_run` is one loop with one check per run line (`per_line.py:233`), replacing the two partial checks.
- Refinement is now its own method `refine` (`per_line.py:279`, check at `:284`).

Tests (`tests/test_destagger_grid.py:188–265`):
- `_loop_of_caller` names the function that called `check`.
- A module-scoped `check_calls` records one whole Grid 1 run.
- `test_should_stop_is_honoured_in_every_exclusion_stage` covers the four exclusion stages, 60 calls each, from
  `_measure_axis`.
- `test_every_loop_checks_once_per_line_in_order` pins calls 241–540 as 60 each of `pair_curves`,
  `line_curves`, `_depth_split`, `_cache_curves` and `classify_all`. In the passes it pins `runs` ==
  `classify_all` (a multiple of 60), plus `solve_run` and at least 4 `refine`.
- `test_should_stop_is_honoured_in_every_per_line_loop[loop]` covers all 8 loops, including `solve_run` (the
  Viterbi search) and `refine`. It stops at the loop's first check and asserts MeasureStopped, the exact call
  count, and that the last call came from that loop.

Proof, each check deleted in a scratch copy:
- `fix1/viterbi/`, the `solve_run` check deleted:
  `FAILED test_every_loop_checks_once_per_line_in_order` and
  `FAILED test_should_stop_is_honoured_in_every_per_line_loop[solve_run]`
  (`ValueError: 'solve_run' is not in list`).
- `fix1/refine/`, the `refine` check deleted: the same two tests fail for `refine`.

### Minor 3: the "did not settle" branch

- **Change** (`per_line.py:312–319`): drop the failing own values, `refine` the rest without them (they were
  solved together), and re-read every line. Repeat until every own value left qualifies. Each round drops at
  least one line, so it ends. `_failing` (`:288`) is shared with the main loop.
- **Test:** `tests/test_destagger_lines.py:292`. Grid 2 unfitted needs 2 passes (FILE__027 and 041 fail the
  first), and `MAX_PASSES` is monkeypatched to 1. It asserts every returned OWN still classifies as a
  candidate, and that each own value sits at its own peak against the returned others (±0.005).
- **Proof** (`fix1/oldbranch/`, the old branch restored): `FAILED`, because FILE__028 comes back at +0.5395
  (solved beside 027, which was then dropped), while its peak against the lines returned is +0.5248.
- **Note:** the "still a candidate" half alone does not discriminate on real data. Probed on Grid 2 unfitted,
  skewed and moved, and the hard case at 1 and 2 passes, the old branch's own values all still classified.
  The refit half is what catches it.

### Minor 4: `PairCurves.normalised` with both `bins` and `half`

- **Change** (`profiles.py:172–178`): `bins` defaults to None, and asking for both raises
  `ValueError("give bins or a half along the axis, not both")`.
- **Test:** `tests/test_destagger_profiles.py:95`, on a minimal hand-built `PairCurves`; it checks the
  arguments only, not the data.

### Minor 5: memory wording

- **Change** (`profiles.py:12–19`): what is kept grows with the grid, but slowly. It is
  n_bins × (6 × search range + 1) values per pair: about 5 MB for Grid 1 and about 30 MB for 200 lines of 50 m,
  against every line's whole transform before.

### Minor 7: synthetic tests out of the real-data file

- **Change:** the six `is_clear` hand-made-curve tests moved to a new `tests/test_destagger_profiles.py`
  (`:60–94`). So did the real-line strength test (`:30`), which tests a profiles helper, and the new
  `normalised` test.
- `test_destagger_lines.py` is real data only now. Its docstring and imports were trimmed accordingly.

### Minor 8: stop-test comment

- **Change:** the comment and stage lists were rewritten (`tests/test_destagger_grid.py:186–200`). The four
  exclusion stages in `_measure_axis` are named apart from the per-line loops, and each loop is named by its
  function. The old "loops before the per-line solve … first per-line reading" wording is gone.

### Verification

- Destagger files (lines, grid, profiles): `57 passed, 4 xfailed in 44.25s`.
- Full core+pure: `1287 passed, 5 skipped, 4 xfailed in 99.47s`. That is 7 more tests: the eight-loop and
  four-stage stop tests replace the old stage tests, plus the two new tests. Skips are unchanged; no warnings.
- Lint and format: `All checks passed!` / `191 files already formatted`. Types (CI list): `Success: no issues
  found in 49 source files`.

Concerns: none new. Reviewer Minor 6 (CHANGES uses decisive halves) goes to the author at C14, as the
controller said.

## C14 follow-up

Commit `5c29322` (FIX_BASE `cc5635b`), pushed. No tolerance was loosened, `CHANGE_M` stays at 0.30, and per-line
results are unchanged.

### What changed

- **`per_line.py`: one reading method for the solver.**
  - `_Solver.residual(k, own, part="full")` (`:189`) returns how far a line sits ahead of its corrected
    neighbours, in metres: the peak of its curve.
  - It uses a shared `_metres` (`:100`). `classify` (`:198`) and `refine` (`:295`) now use it too, so the
    tests read r0 exactly as the solver reads a line, with no copy of its maths.
- **`test_destagger_lines.py`, helpers and fixtures:**
  - Module docstring (`:1–13`): no xfails are left; it states the C14 target.
  - `SIZE_TOL` comment (`:32–35`): the FILE__027 sentence is gone.
  - `measure_with_solver` (`:53`) spies on the solver through `pytest.MonkeyPatch.context`, so it also works
    in module-scoped fixtures.
  - `own_corrections` (`:69`) asserts `len(result.lines) == solver.dirs.size` (`:73`) before relying on the
    result order matching the solver's numbering.
  - `own_residual` (`:83`) reads a line's residual.
  - Fixtures `grid1_unfitted_solved` / `grid1_unfitted` (`:90`, `:95`) measure Grid 1 unfitted once.
    `unmoved_residual` (`:100`) gives r0 from that unmoved run.
- **`test_destagger_lines.py`, tests:**
  - The three FILE__031 strict xfails are now ordinary tests with target (grid value of that run) − (d + r0),
    tolerance 0.05: `test_a_line_moved_forward_is_recovered` (`:144`) and
    `test_a_line_moved_back_is_recovered` (`:152`).
  - `test_two_adjacent_moved_lines_are_both_recovered` (`:180`) checks FILE__031 and FILE__032, each against
    its own r0.
  - The neighbour test (within 0.02) and the companion test (−0.80 ± 0.01) are unchanged.
  - The FILE__027 case is removed from `test_grid2_clearly_off_lines_get_own_values` (`:237`); FILE__045 and
    FILE__028 stay pinned as they were.
  - The "did not settle" test (`:296`) uses the same helpers, so it gets the size assertion, and reads the
    refit through `solver.residual`.
- **Spike note:** a short "C14 outcome" paragraph under "Per-line results (built)" (`:301`), pointing to the
  spec's paragraph and giving the new misses. File names and metres only.

### r0 and the new misses (Grid 1 unfitted)

r0 in the unmoved run is FILE__031 +0.0524 and FILE__032 +0.0053; the grid value is +0.1517.

| Case | Line | Gets | Target: grid − (d + r0) | Miss (tol 0.05) |
|---|---|---|---|---|
| 031 +0.30 (grid +0.1509) | FILE__031 | −0.1998 | −0.2015 | +0.0017 |
| 031 −0.50 (grid +0.1550) | FILE__031 | +0.5961 | +0.6026 | −0.0065 |
| both +0.30 (grid +0.1492) | FILE__031 | −0.2184 | −0.2032 | −0.0152 |
| | FILE__032 | −0.1145 | −0.1561 | +0.0416 |
| 031 −0.50, 032 +0.30 (not pinned) | FILE__031 / FILE__032 | +0.5775 / −0.1138 | +0.6009 / −0.1520 | −0.0234 / +0.0382 |
| 031 +0.30, 032 −0.50 (not pinned) | FILE__031 / FILE__032 | −0.2239 / +0.6864 | −0.1977 / +0.6494 | −0.0261 / +0.0370 |

Every pinned case passes, so none is left a strict xfail.

### Verification

- `test_destagger_lines.py`: `23 passed in 46.82s`.
- Full core+pure: `1290 passed, 5 skipped in 111.14s`, with 0 xfailed and no warnings. That is 1287 + 4
  former xfails, less the dropped FILE__027 case.
- Lint and format: `All checks passed!` / `191 files already formatted`. Types (CI list): `Success: no issues
  found in 49 source files`.

### Concern

- **FILE__032 in the adjacent pair passes with 8 mm of margin** (+0.0416 against 0.05). Against the old target
  it was +0.034.
- The pair together lines up within 0.026 m of its combined target. The solve splits the pair's shared lag
  unevenly: FILE__031 gets 0.015 m too much and FILE__032 0.042 m too little, a split the pair curves cannot
  separate well.
- It is honest at today's numbers, but a small change to the solve or thresholds could tip it.
