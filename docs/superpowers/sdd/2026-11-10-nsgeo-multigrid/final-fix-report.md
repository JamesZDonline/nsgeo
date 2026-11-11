# Final fix report (commit 83a7459, pushed to origin nsgeo-multigrid)
Items 1-6, 15: curvature.py module docstring (41/3.5x; accuracy figures; 0.2 m slower + Whole-site budget note; plan column one run per case, 0.582 s starred with re-measure footnote; neutral load wording; frame-cap plan/solve figures) and plan call 10 comment in `solve`.
Item 7, 8: multigrid.py module docstring (492 / 540; `spare` exception) and `precondition` docstring.
Item 9: comment corrected (up to four plane temporaries); no code change, so no bit-identity check needed.
Item 10: test_slices_multigrid.py symmetry comment. Item 11: `tight_solve` asserts its < 20000. Item 12: test_pure_slices_plan.py docstring (95-100 B plan, 138 B with a solve).
Item 14: two-threads test now 400x400, rows every 10 (6 levels, ~12 its, 2.8 s total); the earlier 300x300/20-row try was partial coverage and took 16 s.
Item 13: `_solve_into` asks should_stop once after the initial residual, before the first precondition; solve docstring updated. New test test_a_solve_asked_to_stop_at_once_runs_no_v_cycle (patches Hierarchy.precondition, asserts 0 calls). test_a_solve_stops_when_asked unchanged: still stops on the 4th call (now before iteration 3 rather than 4), len(calls)==4 holds.
Verify: focused files 100 passed; core+pure 1094 passed, 5 skipped; ruff check/format clean; mypy "Success: no issues found in 43 source files".
