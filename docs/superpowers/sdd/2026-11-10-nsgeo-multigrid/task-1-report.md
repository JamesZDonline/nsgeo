# Task 1 report: multigrid hierarchy

Implemented `nsgeo/slices/multigrid.py` (port of mg2.py: coarsening reads COARSEST_UNKNOWNS at call time, `scale` replaces inverse_diagonal, no `upper`, read-only arrays via Hierarchy.__post_init__, `nbytes`, active copied, coefficients kept uncopied) and `tests/test_slices_multigrid.py` (13 tests: the brief's 12 plus a COARSE_OFFSETS shape test).

RED: pytest on the new test file before the module existed -> collection error (ImportError: cannot import name 'multigrid' from 'nsgeo.slices'), expected.
GREEN: focused 13 passed; core + pure 1085 passed, 5 skipped (baseline 1072 + 13); ruff and mypy clean.

Deviation: the brief's symmetry tolerance (1e-5 * |vdot(M r1, r2)|) fails for random r (rel 2e-4) because the dot cancels to ~0.3 against norm products ~1e5. mg2.py gives the identical number, so it is float32 rounding, not a port bug. The test uses 1e-5 * the norm product (observed 4e-10), with float64 dots.
Files: the two new files only.

## Fix report (review round)
Changed: (1) Chebyshev breaks after the last `x += d`; (2) l1 sum accumulated per offset plane, coarse symmetrisation in place per (k, k') pair with plane-sized temporaries; (3) docstring reworded; (4) test comment figures corrected; (5) `levels[0].coefficients is coef` asserted in the nbytes test; (6) COARSE_OFFSETS test exact via itertools.product.
Equivalence scratch check (old module = git show 1ae9731 loaded separately): on 120x160 and 800x800 frames, all level coefficients/scales np.array_equal and precondition of 3 random r np.array_equal. 800x800 (7 levels) V-cycle median of 5: 0.132 s before, 0.098 s after.
Tests: focused multigrid + test_slices_curvature pass; ruff and mypy clean.
Follow-up: ruff SIM300 on the offsets assert fixed in a second commit; ruff check and format now clean.
