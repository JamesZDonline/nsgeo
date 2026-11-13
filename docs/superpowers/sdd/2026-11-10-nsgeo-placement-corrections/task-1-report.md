# Task 1 report: scale and travel shift in core and survey file

Commit a012644 `feat(core): a placement's scale and travel shift (#3, #47)`, pushed.

## Implemented
- `GridPlacement` gains `scale=1.0`, `travel_shift=0.0` after `label`; `__post_init__` raises ValueError unless scale finite and >0 and shift finite; `distance_along` = start + direction*(scale*i/spm + shift); class docstring explains both, citing calls 1, 4.
- `project.py`: keys written only when != defaults (exact compare, call 13); read with `float(doc.get(...))`; `load_site` wraps `_placement_from_dict` (KeyError/TypeError/ValueError -> ProjectError naming the line); unknown-type ProjectError passes through.

## Tests
- Brief's tests added verbatim, except one fix: `trace_count(path)` in the brief is wrong, the real signature is `trace_count(path, header)`; I used `trace_count(path, h)`.
- RED: 16 failed (placement: TypeError unexpected kwarg 'scale' / real-data TypeError from trace_count signature; project: round trip fails, "DID NOT RAISE ProjectError").
- GREEN: core+pure 1168 passed, 5 skipped (baseline 1150/5; +18 new). Real-data test ran and PASSED (-v), not skipped.
- ruff check/format clean (one import-order autofix for `import math`); mypy clean.

## Self-review
Diff matches brief; no extra API. No concerns beyond the brief's trace_count typo (plan text for later tasks may repeat it).
