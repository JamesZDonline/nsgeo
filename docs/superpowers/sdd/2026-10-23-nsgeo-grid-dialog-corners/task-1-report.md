# Task 1 report: pure corner rules in lookup.py

Implemented CORNER_ROLES, utm_epsg, CornerFrame, corner_frame, roles_from_ring, rotate_roles, compass_label exactly per brief (messages verbatim, checks in the briefed order). corners_from_polygon untouched.

TDD: RED: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -q` -> ImportError: cannot import name 'CORNER_ROLES' (expected: not yet implemented). GREEN: same command -> 69 passed.
Full: core+pure 746 passed, 3 skipped (baseline 698/3). ruff check + format clean; mypy clean.

Files: packages/nsgeo-qgis/nsgeo_qgis/lookup.py, packages/nsgeo-qgis/tests/pure/test_pure_lookup.py.

Notes/concerns:
- Brief's "reversed ring" test: literal reversal of W+[W0] gives idx [0,3,2,1]; the expected [3,2,1,0] matches reversing as [W3,W2,W1,W0,W3], which I used.
- Added two small extra tests (wrong slot count, Y-unfixed message with rows (2,3)).
- Origin tie tolerance is 1e-9 degrees so float noise at 45 degree squares still goes to the lower index.

## Fix round 1
- roles_from_ring: tie now keeps the lower cleaned-ring vertex index on either winding (compares order[k]); tolerance named _BEARING_TIE; docstring updated. Test: 45-degree square, anticlockwise -> idx[0]==0, clockwise (reversed) -> 2.
- corner_frame: with four rows, mixed signs among the consecutive-triple cross products raise "these corners are out of order: check which row each corner is in", after the unfixed-axis check and before in-a-line. Docstring names the rule. Tests: four adjacent swaps, plus a noisy 2<->3 swap; mirrored (1<->3) and collinear tests unchanged and pass.
- Results: test_pure_lookup.py 75 passed; core+pure full suite run, ruff and mypy clean (see commit).
