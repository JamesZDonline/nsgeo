# Task 1 report: migration real-data test (#125)
Commit b2001f1, pushed to origin nsgeo-step-edges. Status DONE_WITH_CONCERNS.

Implemented: `real_radargram(path)` in tests/real_data.py (skips if missing; dt_ns, t0_ns=position_ns, dx_m=1/tpm or None);
REAL_DIFFRACTIONS, `_real_focus`, and `test_a_real_diffraction_collapses_at_its_measured_velocity` (2 cases) in test_steps_migration.py.

Measured (d_trace, d_row rows / ns, focus unmigrated / 0.6v / v / 1.6v):
- FILE__033: +1, 5 rows = 1.083 ns, 0.0243 / 0.0471 / 0.0794 / 0.0377
- FILE__032: -1, 6 rows = 1.299 ns, 0.0203 / 0.0354 / 0.0472 / 0.0168
Differences from the brief: FILE__033 focus(v) 0.0794 vs 0.075; FILE__032 focus(v) 0.0472 vs 0.050 (about 5%). All thresholds still pass with margin; unmigrated, 0.6v, 1.6v, d_row and d_trace match.

Tests: both new cases pass; full core suite 1261 passed, 4 skipped (395 s); ruff check and format clean.
Sabotage (velocity v*0.6 for the main focus): both cases FAIL. FILE__033 on `focus >= 2*before` (0.0471 vs 0.0485); FILE__032 on `abs(d_trace) <= 2` (4). Reverted before commit.
Files: packages/nsgeo-core/tests/real_data.py, packages/nsgeo-core/tests/test_steps_migration.py.
