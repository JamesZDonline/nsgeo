# Task 2 — C14 follow-up (FIX_BASE cc5635b)

The author looked at the C14 pictures and decided (spec amended in cc5635b — read §10 "An injected single-line
error is recovered", the Grid 2 own-value list and "Not pinned either way", and the "C14 outcome" paragraph):

- The per-line values make the big sharp features look better; the alternate-line blocks look right.
- **Injected-error target counts the line's own residual.** A moved line's value must come out within 0.05 m of
  (the grid value of that run) − (d + r0), where r0 is the line's own residual in the UNMOVED run, read the same
  way the solver reads a line (whole-record peak of its curve against its neighbours, after the grid value). The
  tolerance stays 0.05; neighbours still within 0.02; the companion "two moves differ by −0.80 ± 0.01" test stays.
  Rewrite the three FILE__031 strict xfails (single +0.30, single −0.50, adjacent pair — each line of the pair
  against its own r0 from the unmoved run) as ordinary passing tests with this target. Read r0 through the
  solver's own reading (no copy of its maths in the test). If any case still misses 0.05, do NOT loosen: report
  the numbers and leave it a strict xfail with raises=AssertionError.
- **FILE__027 is no longer pinned** (Grid 2 unfitted). Remove its xfail test. FILE__045 and FILE__028 stay pinned
  as they are.
- **CHANGE_M stays 0.30.** No change.

Also, in test_destagger_lines.py (re-review minors deferred from fix round 1):
- the module docstring's xfail count must match what is left (probably none now);
- the "did not settle" test builds `own` in result order and assumes it matches the solver's numbering: add
  `assert own.size == solver.dirs.size` (or equivalent) so a NOT_MEASURED line cannot silently shift it.

Spike note: in "Per-line results (built)", one or two sentences recording the C14 outcome (pointer to the spec's
"C14 outcome" paragraph); file names and metres only.

Append a "## C14 follow-up" section to task-2-report.md (what changed, file:line, the r0 values and the new
misses for each case). Verification as before: core+pure suite (expect 0 xfailed if all pass, 5 skipped, no
noise), ruff check + format --check, mypy with CI's list. Commit (message ends with
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`) and push.
