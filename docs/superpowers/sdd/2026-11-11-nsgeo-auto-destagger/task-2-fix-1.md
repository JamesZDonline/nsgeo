# Task 2 — fix round 1 (FIX_BASE edc6691)

The opus task review found the per-line solve correct (shift and normalisation maths checked; status semantics,
determinism, Viterbi solve all confirmed). Fix these, then append a "## Fix round 1" section to task-2-report.md
and push. Do not change any spec tolerance; do not touch the four xfails' tolerances.

## Important
1. `test_destagger_lines.py:225` with `:248` — the FILE__027 strict xfail can never XPASS: `measured` is None, so
   the last assertion is `found.destagger == pytest.approx(None, abs=0.03)`, which is False for any number. If
   027 ever became OWN above grid + 0.25 the test would still fail and stay "xfailed". Pin the size to the
   prototype's +0.665 (the brief's anchor) so strict=True can fire. Prove it: in a scratch copy (not the
   worktree), force 027 to OWN at ~+0.665 and show the test XPASSes (strict → fails). Report the evidence.

## Minor (all included by the controller)
1. All four xfails (`:109, :122, :159, :226`): add `raises=AssertionError`, so an unrelated KeyError/TypeError
   is not swallowed as "expected".
2. Global constraint "should_stop at least once per line in every per-line loop":
   - add a check to the loops that lack one: `per_line.py:122` (curve cache), `per_line.py:143` (`_depth_split`),
     `profiles.py:246` (`line_curves`), and `runs()` if it iterates per line;
   - pin the checks inside the solve: today `test_should_stop_is_honoured_in_the_per_line_passes`
     (`test_destagger_grid.py:246`) stops only at the first and last call, and its `>= 420` bound is met by the
     re-reads alone, so deleting the Viterbi/refinement checks (`per_line.py:223,240,262`) leaves every test
     green. Parametrise it over at least one call that lands inside a Viterbi solve and one inside refinement,
     and show (scratch copy) that deleting one of those checks now fails a test.
3. `per_line.py:285-290` — the "did not settle" branch zeroes the bad lines but keeps own values solved jointly
   with them that may no longer classify. Re-verify the run's remaining own values (or drop them), and add a
   test that forces it (e.g. monkeypatch `MAX_PASSES=1` on a real grid that needs >1 pass) and asserts every
   returned OWN still classifies as a candidate.
4. `profiles.py:169-176` — `PairCurves.normalised(a, b, bins=..., half=h)` silently ignores `bins` when `half` is
   given. Raise ValueError when both are passed (and test it).
5. `profiles.py:16` — the docstring says memory "does not grow with the grid"; `by_bin` holds
   n_bins × (6·max_lag+1) floats per pair, which grows with line count and length (far more slowly than the old
   FFT cache). Reword it truthfully.
7. `test_destagger_lines.py:318-358` — the synthetic `is_clear` tests sit in a file the brief calls "real data
   only". Move them to `test_destagger_grid.py` (or a new `test_destagger_profiles.py`).
8. `test_destagger_grid.py:184` — the comment says "loops before the per-line solve" and then lists "the first
   per-line reading", which is part of the solve. Make it consistent.

Not for this round: reviewer Minor 6 (CHANGES uses decisive halves) goes to the author at C14.

## Verification (from the worktree)
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
  — expect 1280+ passed, 5 skipped, 4 xfailed, and no new noise.
- `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .` and mypy with CI's list.
- Commit (message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`) and push; if the push
  fails on the network, say so and the controller pushes.
