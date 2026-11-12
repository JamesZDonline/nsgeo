# Boundary fix: plugin imports clock helpers through nsgeo.processing (#97)

Commit 93fedfa on nsgeo-time-zero, pushed to origin (b599a6d..93fedfa).

## Files changed
- packages/nsgeo-core/src/nsgeo/processing/__init__.py: re-exports retime_ns (from base), and TIME_BASE_RADAR, TIME_BASE_TIME_ZERO, first_break_ns, sets_time_zero, time_base_of (from timezero); added to __all__ in sorted order.
- packages/nsgeo-core/README.md: six new rows in the nsgeo.processing table.
- packages/nsgeo-qgis/nsgeo_qgis/plugin.py: `from nsgeo.processing import build_step, retime_ns`.
- packages/nsgeo-qgis/nsgeo_qgis/session.py: retime_ns merged into the existing `from nsgeo.processing import` line.
- packages/nsgeo-qgis/nsgeo_qgis/layers.py: `from nsgeo.processing import retime_ns`.
- packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py: `from nsgeo.processing import Radargram, StepStack, build_step, first_break_ns, retime_ns`.

## Verify
1. `pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure`:
   `1278 passed, 5 skipped in 42.93s` (0 failed). The brief's pre-fix baseline was 1 failed, 1277 passed; I did not re-run the baseline.
2. `pytest packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` (QT_QPA_PLATFORM=offscreen, .venv-qgis):
   `14 passed in 11.45s`
3. `ruff check .`: `All checks passed!`
   `ruff format --check .`: `182 files already formatted`
   `mypy` on the listed targets: `Success: no issues found in 43 source files`

## Notes
- The commit uses the Co-Authored-By trailer from the brief (Claude Opus 5.5). The session's attribution reminder names Claude Haiku 5.5; the brief's explicit text was followed.
