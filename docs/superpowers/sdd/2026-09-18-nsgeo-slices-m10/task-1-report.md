# Task 1 Report: CubeFrame and ZAxis

## What I implemented

- `packages/nsgeo-core/src/nsgeo/slices/__init__.py` — package docstring and
  re-export of `CubeFrame`, `ZAxis`, verbatim from the brief.
- `packages/nsgeo-core/src/nsgeo/slices/frame.py` — `CubeFrame` (frozen
  dataclass: `origin`, `azimuth`, `cell`, `nx`, `ny`, `crs`) with `n_cells`,
  `axes()`, `to_local()`, `cell_index()`, `for_grid()`, `for_points()`; and
  `ZAxis` (frozen dataclass: `t0_ns`, `dz_ns`, `nz`) with `t_end_ns`,
  `times_ns()`, `depths_m()`, `from_range()`, `level_range()`. Implementation
  follows the brief's code verbatim except for two deviations, both
  documented below.
- `packages/nsgeo-core/tests/test_slices_frame.py` — the 16 tests specified
  in the brief, verbatim.

## Deviations from the brief's verbatim code (both authorized by the task's
"fix it and say so" clause; neither is the annotation ruling)

1. **`Tuple`/`Dict` → `tuple`/`dict`** (the ruling given in the task prompt).
   Dropped `from typing import TYPE_CHECKING, Tuple` in favor of
   `from typing import TYPE_CHECKING`, and every `Tuple[...]` annotation
   became `tuple[...]`. No `Dict` usage existed in this file. Confirmed this
   was necessary, not optional: before the change, `ruff check` raised
   UP006/UP035 on every `Tuple[...]` occurrence.

2. **A real bug in `cell_index`, found by TDD, not an annotation issue.**
   `test_for_points_contains_every_point_it_was_built_from` (verbatim from
   the brief) failed on first run with one point of 200 landing at
   `cell_index == -1` despite `CubeFrame.for_points` having been sized
   around that exact point set. Root cause: `for_points` builds `origin` by
   re-projecting the local minimum back through the rotation
   (`lo_x * x_hat + lo_y * y_hat`); `cell_index` (via `to_local`) reaches
   the same point by a *different* chain of floating-point operations
   (`world - origin`, then `@ x_hat`/`@ y_hat`). At a non-axis-aligned
   azimuth (17.0 in the test) these two paths don't cancel to the last bit,
   so the point that defined the frame's own lower-left corner landed at
   local x = -8.88e-16 instead of 0.0, and `floor(-8.88e-16 / 0.5) == -1`.
   Fix: `cell_index` now adds `eps = 1e-9 * self.cell` before flooring, i.e.
   tolerates floating-point round-off at the exact boundary without
   softening the "never clipped" contract for genuine misses (the existing
   `test_cell_index_marks_points_outside_as_minus_one` test uses offsets of
   0.1-2.0 cell units, four to five orders of magnitude past the
   tolerance). Verified the fix generalizes: swept 50 seeds x 6 azimuths
   (300 combinations) through the same `for_points` -> `cell_index`
   round-trip with zero -1s.

   I left the brief's own stray comment above the `for_points` return
   ("nextafter keeps a point exactly on the far edge inside the frame...")
   untouched even though no `nextafter` call exists anywhere in the
   function — it doesn't cause a test/lint/mypy failure, so it falls
   outside the scope the task authorized me to diverge on. Flagging it here
   as a documentation inconsistency worth a look, not something I fixed
   silently.

3. **Formatting only:** the brief's own test file (copied verbatim) is not
   `ruff format` clean — three multi-line `Grid(...)` calls each pack two
   keyword arguments per line, which `ruff format` insists on breaking one
   per line. Since the brief's own Step 5 requires
   `ruff format --check .` to pass, I ran `ruff format` on just that one
   file. Purely whitespace; no semantic change, confirmed by the diff
   ruff itself printed (visible in the RED/GREEN section below).

## TDD evidence

### RED

Command:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -v
```
Relevant output (before `nsgeo/slices` existed):
```
ImportError while importing test module '.../tests/test_slices_frame.py'.
packages/nsgeo-core/tests/test_slices_frame.py:8: in <module>
    from nsgeo.slices.frame import CubeFrame, ZAxis
E   ModuleNotFoundError: No module named 'nsgeo.slices'
=========================== short test summary info ============================
ERROR packages/nsgeo-core/tests/test_slices_frame.py
```
This is exactly the failure the brief's Step 2 predicts — expected, since
neither `nsgeo/slices/__init__.py` nor `nsgeo/slices/frame.py` existed yet.

Second RED, after creating the package and implementing `frame.py` verbatim
(before the `eps` fix):
```
FAILED packages/nsgeo-core/tests/test_slices_frame.py::test_for_points_contains_every_point_it_was_built_from
AssertionError: assert np.False_
```
15/16 passed; the one failure was the floating-point boundary bug described
above (point index 46 landed at `cell_index == -1`). This was an unexpected
RED relative to the brief's Step 4 ("Expected: all PASS"), so I treated it as
a bug to diagnose and fix rather than a red I could implement past.

### GREEN

Command:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -v
```
Output (after the `eps` fix in `cell_index`):
```
collected 16 items
... (16 lines, all PASSED) ...
============================== 16 passed in 0.12s ==============================
```

Full core suite:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
```
```
333 passed, 2 skipped in 0.97s
```
(baseline was 317 passed, 2 skipped; +16 new tests, 0 regressions, 2 skips
unchanged.)

Linters:
```
./.venv/bin/ruff check .
```
```
All checks passed!
```
```
./.venv/bin/ruff format --check .
```
```
95 files already formatted
```
(after reformatting the one test file as described above; before that fix it
reported "1 file would be reformatted, 94 files already formatted")

Mypy:
```
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
```
```
Success: no issues found in 24 source files
```
(baseline: 22 files; +2 for the new `slices` package)

`test_boundary.py` specifically, since the brief calls it out:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py -v
```
```
test_no_forbidden_module_level_imports PASSED
test_src_tree_is_actually_being_scanned PASSED
```

## Files changed

- `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (new)
- `packages/nsgeo-core/src/nsgeo/slices/frame.py` (new)
- `packages/nsgeo-core/tests/test_slices_frame.py` (new)

## Self-review findings

- **Completeness:** every interface in the brief's spec is present —
  `CubeFrame(origin, azimuth, cell, nx, ny, crs)`, `n_cells`, `axes()`,
  `to_local()`, `cell_index()`, `for_grid()`, `for_points()`, and
  `ZAxis(t0_ns, dz_ns, nz)`, `times_ns()`, `t_end_ns`, `depths_m()`,
  `from_range()`, `level_range()`. All 16 specified tests pass; no test was
  altered in substance (only the eps fix in source, and reformatting in the
  test file's whitespace).
- **Quality:** docstrings explain "why," matching the surrounding codebase's
  style (`grid.py`, `velocity.py`). Added one docstring paragraph to
  `cell_index` explaining the new `eps` tolerance and why it's safe — this
  is the one place I extended the brief's own documentation, and only
  because I added behavior the brief's text didn't describe.
- **Discipline:** no scope creep — did not touch `Grid`, `VelocityModel`, or
  any file the brief didn't name. Did not "fix" the stray `nextafter`
  comment since it doesn't break anything (see deviation #2 above);
  reported it instead of acting unilaterally on a purely cosmetic call.
- **Testing:** TDD was followed in the sense the brief specifies (tests
  written first, failure confirmed, implementation added, failure
  re-confirmed to be the *right* kind, then fixed). The one place this task
  departed from a clean "implement then green" is the numerical bug in
  step 4, which surfaced as a real, reproducible test failure rather than
  something guessed at — I verified root cause with a small ad hoc debug
  script (not committed) before choosing the fix, and stress-tested the fix
  across 300 seed/azimuth combinations before trusting it. Test output is
  pristine: no warnings in any of the runs above.

## Concerns

- The `eps = 1e-9 * self.cell` tolerance in `cell_index` is a deviation from
  the brief's literal code, made necessary by a genuine floating-point bug
  the brief's own test caught. I'm confident in the fix (verified against
  300 seed/azimuth sweeps, and it doesn't touch the semantics of the
  existing "never clipped" boundary test), but flagging it explicitly since
  it changes behavior the brief didn't describe in prose, only in test
  form.
- The brief's stray `nextafter` comment in `for_points` (see deviation #2)
  references code that isn't there. Harmless, but a reviewer may want it
  cleaned up in a later pass.

**Both concerns above were addressed in the fix round below — the eps
mechanism was wrong and has been replaced, and the stale comment has been
rewritten.**

---

## Fix report (review round 1)

Review came back "Needs fixes" with three findings. All three are fixed,
verified, and committed. Commit `60e6e2d`.

### CRITICAL 1 — `cell_index`'s tolerance was scaled wrong and introduced a new bug

**What was wrong**, confirmed by the reviewer's independent numerical
checks (which I re-ran and reproduced exactly, see below): `eps = 1e-9 *
self.cell`, added unconditionally to both coordinates before flooring, was
wrong in two ways —

1. It scales with **cell size**, but the round-off it needs to absorb
   scales with **coordinate magnitude** (the `world - origin` cancellation
   in `to_local`). At toy coordinates (~10) the two happen to be close
   enough that the original test passed; at UTM magnitudes (~1e6) the
   round-off (~1e-9 m) is orders of magnitude larger than a realistic
   cell-relative epsilon (e.g. 5e-10 for a 0.5 m cell, worse for smaller
   cells), so points were still dropped.
2. Adding it unconditionally, to every point, nudges points near *any*
   boundary — including a point genuinely inside, a hair below the frame's
   far edge — up across that boundary, turning a correctly-inside point
   into a false negative. `f.cell_index([[4.0 - 1e-12, 0.5]])` on a
   `nx=4, cell=1.0` frame returned `-1` instead of `3`.

**Mechanism chosen**: no field added to `CubeFrame` (per the ruling — that
would ripple into Task 4's binner and Task 6's `.npz` writer). Instead,
`cell_index` floors exactly as before with no upfront nudge, then applies a
correction only to points that already floor to `-1` or to `nx`/`ny` — i.e.
only the frame's own outer edges, never an interior cell boundary, and
never a point that already floors to a valid interior index. The
correction tolerance is `tol = 8.0 * np.finfo(float).eps *
np.maximum(1.0, np.abs(world).max(axis=1))` — proportional to each point's
own **world**-coordinate magnitude (not cell size), computed per-point so
a batch mixing toy and UTM-scale points is handled correctly for each. The
multiplier 8 gives headroom over the reviewer's own measured round-off
(~1x machine epsilon at that magnitude) to absorb a few compounded
operations (subtraction, dot product, trig) without approaching any
realistic cell size (0.05 m is ~7 orders of magnitude larger than the
resulting tolerance at UTM scale).

This satisfies all five properties in the ruling:
1. No unconditional shift — only `-1`/`nx`/`ny` results are touched.
2. Tolerance is `np.abs(world)`-based, not cell-based.
3. `4.0 - 1e-12` case: floors to `3` already (never hits the `ix == nx`
   branch), so it's untouched and stays inside — verified directly.
4. `test_cell_index_marks_points_outside_as_minus_one` passes unchanged
   (offsets there are 0.1-2.0, five-plus orders of magnitude past any
   tolerance this produces at toy coordinate scale).
5. `for_points` contains every point it was built from at UTM magnitudes —
   verified by direct re-run of the reviewer's exact sweep design.

**Independent re-verification of the reviewer's exact repro** (script run,
not just the new pytest tests):

Command (ad hoc verification script, not committed):
```python
offset = np.array([500000.0, 4500000.0])
for cell in (0.5, 0.1, 0.05):
    drops = combos = 0
    for seed in range(50):
        rng = np.random.default_rng(seed)
        pts = rng.uniform(-5.0, 15.0, size=(200, 2)) + offset
        for az in (0.0, 17.0, 33.3, 90.0, 123.4, -45.0):
            combos += 1
            f = CubeFrame.for_points(pts, cell=cell, crs="EPSG:32633", azimuth=az)
            if (f.cell_index(pts) < 0).any():
                drops += 1
    print(f"cell {cell:<5} -> {drops}/{combos} combinations drop >=1 defining point")

f = CubeFrame(origin=(0.0,0.0), azimuth=0.0, cell=1.0, nx=4, ny=3, crs="EPSG:32633")
print("far-edge case:", f.cell_index(np.array([[4.0 - 1e-12, 0.5]])))
```
Output:
```
cell 0.5   -> 0/300 combinations drop >=1 defining point
cell 0.1   -> 0/300 combinations drop >=1 defining point
cell 0.05  -> 0/300 combinations drop >=1 defining point
far-edge case: [3]
genuine miss ids (expect -1,-1): [-1 -1]
toy outside ids (expect all -1): [-1, -1, -1, -1]
```
(Was 25/300, 133/300, 142/300 and `[-1]` respectively before the fix, per
the reviewer's numbers, which I reproduced against the pre-fix code before
changing it.)

**New regression tests** added to `test_slices_frame.py`:
- `test_for_points_contains_every_point_at_utm_magnitudes` — the UTM sweep
  above (50 seeds x 6 azimuths x 3 cell sizes including 0.05), as an
  actual pytest test.
- `test_cell_index_keeps_a_point_a_hair_below_the_far_edge` — pins the
  `4.0 - 1e-12` case returning a valid index (`3`), not `-1`.

### IMPORTANT 2 — `ZAxis.from_range`'s division fragility

**Fix**: `from_range` now computes `span = (t1_ns - t0_ns) / dz_ns`, then
uses `nearest = round(span)` and snaps to it via `math.isclose(span,
nearest, rel_tol=1e-9)` before falling back to `math.floor(span)`. A
relative tolerance (not absolute) means it does the right thing regardless
of the input magnitude, and `rel_tol=1e-9` is far tighter than any
realistic user-intended fractional difference (the smallest gap the brief
or task ever uses is on the order of 0.05-0.5 ns) while comfortably
covering IEEE-754 double division error (~1e-16 relative).

**Verification**: re-ran the reviewer's own falsification method — exact
rational arithmetic as ground truth — over a larger sweep than the
reviewer used (t1 in 0.01..10.00, dz in 0.01..1.00, both in hundredths, so
denominators of 100 rather than the reviewer's presumably coarser grid):

Command (ad hoc verification script):
```python
from fractions import Fraction
bad, total_exact = [], 0
for t1h in range(1, 1001):
    for dzh in range(1, 101):
        t1, dz = t1h / 100.0, dzh / 100.0
        frac = Fraction(t1h, 100) / Fraction(dzh, 100)
        if frac.denominator != 1:
            continue
        total_exact += 1
        expected_nz = int(frac) + 1
        z = ZAxis.from_range(0.0, t1, dz)
        if z.nz != expected_nz:
            bad.append((t1, dz, z.nz, expected_nz))
print(f"{len(bad)} of {total_exact} exactly-divisible pairs mismatch")
for t1, dz in [(0.3, 0.1), (0.3, 0.05), (0.6, 0.05)]:
    z = ZAxis.from_range(0.0, t1, dz)
    print(t1, dz, "-> nz=", z.nz, "t_end=", z.t_end_ns)
```
Output:
```
0 of 5142 exactly-divisible pairs mismatch
0.3 0.1 -> nz= 4 t_end= 0.30000000000000004
0.3 0.05 -> nz= 7 t_end= 0.30000000000000004
0.6 0.05 -> nz= 13 t_end= 0.6000000000000001
```
(Before the fix these were `nz=3`, `nz=6`, `nz=12` per the reviewer's
report — all now correct, `t_end_ns` matching `t1_ns` to float precision.)

**New regression test**: `test_z_axis_from_range_includes_the_end_when_the_division_is_not_exact_in_float`
— `ZAxis.from_range(0.0, 0.3, 0.1)` asserts `nz == 4` and
`t_end_ns == pytest.approx(0.3)`, exactly the case the reviewer specified.

### IMPORTANT 3 — stale `nextafter` comment

Replaced. The comment above `for_points`' `return cls(...)` (frame.py, at
the `nx=max(1, int(math.floor((hi_x - lo_x) / cell)) + 1)` lines) now
reads:

```
# `+ 1`: nx/ny counts cells inclusively across lo..hi, not just the
# (possibly fractional) number of whole cells floor() gives back.
```

This attributes the `+1` to what it actually does, as the reviewer
specified, rather than to a `nextafter` call that was never present.

### Commands run and full output (post-fix)

Focused test file:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -v
```
```
collected 19 items
test_n_cells_is_nx_times_ny PASSED
test_cell_index_is_row_major_iy_times_nx_plus_ix PASSED
test_cell_index_marks_points_outside_as_minus_one PASSED
test_to_local_inverts_the_rotation PASSED
test_for_grid_covers_the_whole_grid PASSED
test_for_grid_rounds_a_ragged_extent_up_rather_than_dropping_it PASSED
test_for_points_contains_every_point_it_was_built_from PASSED
test_for_points_contains_every_point_at_utm_magnitudes PASSED
test_cell_index_keeps_a_point_a_hair_below_the_far_edge PASSED
test_for_points_rejects_an_empty_array PASSED
test_frame_rejects_a_non_positive_cell PASSED
test_z_axis_times_start_at_t0_and_step_by_dz PASSED
test_z_axis_from_range_includes_the_end PASSED
test_z_axis_from_range_includes_the_end_when_the_division_is_not_exact_in_float PASSED
test_z_axis_depths_use_the_velocity_model PASSED
test_level_range_is_half_open_and_covers_the_window PASSED
test_level_range_clamps_to_the_axis_and_never_empties PASSED
test_z_axis_rejects_a_non_positive_dz PASSED
test_azimuth_convention_matches_grid PASSED
============================== 19 passed in 0.22s ==============================
```

Full core suite:
```
./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
```
```
336 passed, 2 skipped in 1.13s
```
(336 = 333 pre-fix-round total + 3 new regression tests; 0 regressions, 2
skips unchanged from baseline.)

Linters:
```
./.venv/bin/ruff check .
```
```
All checks passed!
```
```
./.venv/bin/ruff format --check .
```
```
95 files already formatted
```

Mypy:
```
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
```
```
Success: no issues found in 24 source files
```

### Files changed (this fix round)

- `packages/nsgeo-core/src/nsgeo/slices/frame.py` — `cell_index` boundary
  tolerance mechanism replaced; `for_points` comment fixed; `from_range`
  division-fragility fixed.
- `packages/nsgeo-core/tests/test_slices_frame.py` — three new regression
  tests added (UTM-magnitude sweep, far-edge pin, non-exact-division pin).

### Remaining concerns

None on the three findings above — all verified against the reviewer's own
exact numbers, not just against my own tests. The three Minor findings
(untested `margin` parameter, untested error branches, `level_range`'s two
clip directions meaning different things) were explicitly marked out of
scope for this round and are not addressed here.
