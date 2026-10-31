# Walkthrough rounds — slices cleaning round (#74, #70, #72, #71)

Page: https://claude.ai/artifact/PKBWF5xrSNJXhjun6zcCXZ (db collection `results`, 21 checks).
Build: `nsgeo-slices-cleanup` at 8b7dc43 (origin/main merged in), QGIS profile `ns_geo_slices`, the user's real data.

## Round 1 — 2026-10-31: 17 pass, 0 fail, 1 skip

- Passed: A1 (open and scope switches stay clean), B1–B3 (#74), C1–C2 (#70), D1–D4 (#72), E1, E3, E4 (#71 This grid), F1–F4 (#71 Whole site).
- Skipped: E2 (This grid's save, close and reopen). Its site twin F3 passed, and the reopen paths are covered by `test_reopening_a_survey_restores_a_remembered_resolution_without_dirtying_it` and the site reopen test.
- Not marked (both optional): C3 (remove the selected last grid while Whole site shows) and E5 (the time-cutoff fallback, "your call").
- No notes. The user: "walk done. looks good", and asked for the PR, the merge, the 0.2 release number and a new zip.
