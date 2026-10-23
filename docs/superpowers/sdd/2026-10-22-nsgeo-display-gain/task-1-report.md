# Task 1 report
Implemented `StepStack.result_bypassing(*indices)` with a 2-entry LRU memo (`_bypassed`, `_drop_bypassed(keep)`), wired into all mutators and the source setter; `nsgeo.render.row_envelope` (plain np.percentile when all finite, nanpercentile route otherwise, all-NaN rows -> 0.0 silently); README row for the public-API test.
RED: test_stack.py: 5 failed (several-index TypeError, memo `is` failures); test_render.py: ImportError row_envelope. (The recompute-after-change tests already passed pre-change since nothing was memoised; they guard the new memo.)
GREEN: core+pure: 634 passed, 3 skipped (pre-existing schema skips); real-file tests ran. ruff, format, mypy clean.
Files: stack.py, render.py, README.md (core), test_stack.py, test_render.py, test_real_files.py.
