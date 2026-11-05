# Task 2 report

Implemented: smooth.py (shifted-sum separable Gaussian, truncated at 4 sigma, mask-normalised, NaN stays NaN, sigma 0 skips the axis, negative sigma ValueError), finish.py (FinishSettings with validation, finish_slice), to_north_up half-pitch rule via lattice_pixel(snap_azimuth(...)), docstring edits (display.py, frame.py, slice_export.py Ruling AE bullet replaced with a short history note), __init__ exports, README rows (smooth, FinishSettings, finish_slice).

TDD: RED = collection ImportError "cannot import name 'FinishSettings' from 'nsgeo.slices'" (modules missing; display tests were written in the same file and would fail on gt[1]==cell). GREEN = 46 passed for the three focused files.

Full core + pure: 910 passed, 3 skipped. Four QGIS files: 171 passed. ruff check/format clean, mypy clean.

QGIS expectations changed: none were needed (all passed unchanged).

Deviation from brief: test_a_spike_spreads_as_a_gaussian_of_the_given_sigma uses a 41x41 field with the spike at (20,20), not 21x21 at (10,10). On 21x21 the 4-sigma kernel (12 cells) reaches the edge, the mask divide sees a truncated kernel, and the ratio differs from the Gaussian by about 1%, so rtol=1e-6 cannot hold. The brief's design (value*mask over mask) is unchanged.

Self-review: no issues. Note frame/world extent for snap_azimuth uses hypot(nx, ny)*cell as the brief says.
