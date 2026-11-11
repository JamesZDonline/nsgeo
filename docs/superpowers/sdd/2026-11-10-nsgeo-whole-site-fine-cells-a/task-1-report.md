# Task 1 report: bilinear rule in the core
Commit 305b824 feat(slices): bilinear taps and samplers for north-up pictures (pushed).
Files: slices/resample.py (new), slices/__init__.py (exports), tests/test_slices_resample.py (brief's tests verbatim, ruff-formatted), packages/nsgeo-core/README.md (4 rows; test_public_api requires every public name in the README).
RED: with resample.py moved aside, pytest test_slices_resample.py -> collection ERROR (ImportError on bilinear_taps). GREEN: 11 passed.
Full core tier: 784 passed, 28 skipped. ruff check/format clean; mypy (CI command) no issues.
Notes: exact path leaves outside points NaN; outside points get ix0=iy0=0,t=0; tx clamped below 1 after float32 cast. No brief test altered.

## Fix round 1
Changed: sample_counts now takes the min over in-frame corners with positive bilinear weight only (ok &= w > 0 in its loop). Brief's counts test now defines `hits` by the same rule. New test_axis_aligned_counts_are_each_cells_own_count. Cell-centre test parametrized over azimuth 0/17/30 with cell=0.05 at UTM origin.
Command: PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_resample.py -q -p no:xonsh -p no:cacheprovider -> 14 passed. ruff check/format and mypy clean.
Mutant (snap line deleted, scratch copy in scratchpad): 3 failed (the three azimuth cases of the cell-centre test), 11 passed.
