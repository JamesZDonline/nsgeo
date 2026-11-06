# Final review — #67 grid-aligned profiles

Whole-branch review (opus) of 7069959..fb62978, then one fix wave (2ddd7f4) and one scoped re-review (opus).

## Whole-branch review: "With fixes"

- **Important (plan defect).** On a ruled line the held time window was applied unchanged when the
  same line's record changed size. Clamping only handled a shrinking record. Re-selecting a
  `time_cutoff` row showed the bypassed record still cropped at the cut, so there was nothing below
  the line to drag it over. Removing the cutoff or disabling `time_zero` left the view cropped.
  Main refit on any `n_samples` change.
- Minor: rule 3's `n_traces` half untested; a zero-spacing distance (a `traces_per_metre = +inf`
  header) made `bounds_on` infinite, so `set_axes` raised and the previous line's picture stayed under
  the new title; `trace_index_at` no longer used in production (left as is).
- Deferred-minor triage: only "file the window in `_clear_view_only`" and "pin the `_held` lifetime"
  were recommended for the fix wave; everything else was left for later (see progress.md).

## Fix wave (2ddd7f4)

- A departing view showing the whole record (within dt/2) or the whole ruler (within half a trace)
  is remembered as "whole", not as numbers; a genuine zoom on either axis is still held exactly.
- Rule 3 trace-count test; the ruler is dropped when its bounds aren't finite and ordered;
  `_clear_view_only` files the window through the same helper; `_clear` resets `_held` after it;
  site-close test; docstrings.

## Scoped re-review: all items addressed, one test gap parked

- Mutants killed: whole-time and whole-ruler sentinels forced either way; rule 3 comparing only
  `n_samples`; no filing in `_clear_view_only`; no `_held` reset in `_clear`.
- Survives: resetting `_held` *before* `_clear_view_only()` in `_clear`. Only a preview-only site
  close shows the order. The code is correct; the reviewer's drop-in test
  (`test_p1_preview_only_site_close_forgets_the_hold`) goes into the first walkthrough fix round.
- New minors (deferred): a deep time zoom is lost after visiting a shorter record; a zoom touching
  the end of a cut record stays at the cut; a constant-distance line gets a ruler from the dock but
  not from the view (harmless re-show); small nits.

Verification at 2ddd7f4: core+pure 827 passed / 3 skipped; QGIS tier 1208 passed, 0 skipped
(real-data zigzag test included); ruff and mypy clean.
