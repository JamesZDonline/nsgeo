## Plan calls (Claude's; check while reading)

- **P1 — module and names.** The core code lives in the package `nsgeo/destagger/`. `__init__.py` re-exports the public names, and the code is in `prepare.py`, `profiles.py`, `measure.py` and `per_line.py`. `destagger` joins `EXPECTED_PUBLIC` in `test_public_api.py`, and the core README names every public name.
- **P2 — time settings.** Every line on an axis must share the most common bin `dt_ns` and `t0_ns` (within 1e-6). A line that differs is *not measured*, with the reason `recorded with different time settings from the rest of the grid`. Lines with different record lengths are cut to the shortest common bin count.
- **P3 — too short.** A line whose placed length, less the two 2 m end trims, is under 2 m is *not measured*, with the reason `too short to measure`.
- **P4 — multi-channel files** are measured on their first channel (`read_samples(...)[0]`), as the spike did.
- **P5 — per-line values round to 0.001 m** when they land in the table, the precision of the Destagger box.
- **P6 — the rows filled** are the rows selected when Measure was pressed. They exclude rows whose Grid cell now names another grid. The status line describes only those rows, plus the grid value.
- **P7 — the worker** is the existing `nsgeo_qgis.refine.Refiner` (one thread, generation-checked, results drained on the GUI thread), one per dialog. It is not a `QgsTask`. The job does no Qt and no session work, and the Refiner already handles its traps (C9).
- **P8 — the panel stays reachable.** While a measure runs, the bulk panel stays enabled even with no selection, so **Stop** can always be pressed. With no selection, the other bulk buttons do nothing.
- **P9 — the skew test** (spec §10, "an injected skew is ignored") cannot hold literally: real Grid 1 already has a few own values without any skew. It is tested as "the skew creates and removes no own value 0.20 m or more from the grid value, own values present in both runs differ by at most 0.03 m, and the grid value moves by less than 0.01 m".
- **P10 — two adjacent injected errors** use +0.30 m on two neighbouring lines, as when two lines were both started off the baseline. Each must be within 0.05 m. Large opposite moves on neighbours (−0.50 beside +0.30) are a known weak case of the prototype. They are reported at the C14 checkpoint, not pinned.
- **P11 — tolerances the spec did not give** are pinned by the Task 2 builder from the data:
  - the Grid 2 own values' size;
  - the share of lines keeping the grid value (spec: about 80% or more on Grid 1; at least 70% on Grid 2);
  - the thresholds.

  A spec tolerance that cannot be met (the −0.50 single-line case is the likeliest) is never loosened in a test. The task reports `DONE_WITH_CONCERNS`, and the coordinator takes it to the author at C14.
- **P12 — the summary names at most 6 lines per group**, then `and {n} more`.

## Global Constraints

- **Core:** numpy only (no scipy), runtime Python 3.9: no `zip(strict=)`, no `match`, no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new file.
- **Plugin:**
  - `nsgeo_qgis/destagger_job.py` and `nsgeo_qgis/line_edit.py` import no Qt and no `qgis`. Add `destagger_job.py` to the mypy list in `.github/workflows/ci.yml` and in the types command below.
  - Qt only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green.
  - Every Qt slot guards its own body and ends in `except Exception as exc: self._failed(exc)`, the pattern `EditLinesDialog` already uses.
- **Determinism:** the same lines and placements give identical results. The bootstrap uses `np.random.default_rng(0)`. Pressing Measure twice on an unchanged table gives the same numbers (spec anti-goal).
- **Stopping:** `measure_destagger` calls `should_stop()` at least once per line in every per-line loop, and raises `MeasureStopped` when it returns True. A stop then takes effect within about half a second.
- **Numbers (core, exact):**
  - `DEWOW_NS = 4.0` and `BIN_SAMPLES = 8`.
  - `STEP_M = 0.02`, `LOWPASS_M = 0.15`, `HIGHPASS_M = 3.0` and `END_TRIM_M = 2.0`.
  - `T_START_NS = 4.0` (header clock; bins whose centre is at or before it are skipped).
  - The search range is ±max(`MIN_SEARCH_M = 1.0`, `SEARCH_FRACTION = 0.03` × the longest placed line on the axis) of neighbour lag.
  - `BOOTSTRAP = 300`; `MIN_USABLE_M = 2.0` (P3).
  - The time window's end is not hard-coded. The builder chooses a rule (spec §11) that keeps the §10 values.
- **Copy (exact). Core reasons, as module constants in `nsgeo.destagger.measure`:**
  - `NO_DISTANCE = "no distance axis (recorded on a timer)"`
  - `TOO_SHORT = "too short to measure"`
  - `TIME_SETTINGS = "recorded with different time settings from the rest of the grid"`
  - `NO_NEIGHBOUR = "no line walked the other way beside it"`
  - `ONE_WAY = "every line was walked the same way, so there is no stagger to measure"`
  - `TOO_FEW = "too few lines walked in opposite directions to measure"` (fewer than `MIN_LINES = 4` lines with a neighbour)
  - `UNCLEAR = "no clear match between lines walked in opposite directions"`
  - `AXIS_FAILED = "its grid's value could not be measured"`
  - `NO_LINES = "none of the grid's lines could be measured"` (no line survives the exclusions; Ruling 12)
- **Copy (exact), plugin:**
  - Button: `Measure`; while running, `Stop`.
  - `MEASURE_TIP = "Works out the destagger from the grid's own data: each line is compared with its neighbours walked the other way, over the whole record. Fills the Destagger box with the grid's value and each selected row with its line's value. Nothing changes until OK."`
  - Progress: `Measuring… read {i} of {n} lines`, then `Measuring… comparing lines`.
  - Stopped: `Measure stopped. Nothing was changed.`
  - Discarded: `The table changed while measuring, so the results were not used. Press Measure again.`
  - Site gone or replaced: `The site changed while measuring, so the results were not used.`
  - Error: `Could not measure: {message}. Nothing was changed.`
  - Nothing selected to fill: `Select the lines to fill, then press Measure.`
  - Summary (built by `measure_summary`, parts joined with one space, empty parts left out):
    - One axis: `Measured {g:+.3f} m from {n} lines (±{s:.3f} m).`
    - Two axes: `Along {axis}: measured {g:+.3f} m from {n} lines (±{s:.3f} m).` per axis, then the groups below.
    - One axis that failed: `Could not measure: {reason}. Nothing was changed.`; with two axes, `Along {axis}: could not measure ({reason}); nothing changed there.`
    - `Own values: {label} {v:+.3f}, {label} {v:+.3f}.`
    - `Left at the grid value: {label} changes partway along; {label} has no clear match.`
    - `Not measured, left as they were: {label} ({reason}); {label} ({reason}).`
    - An unreadable file's reason: `could not be read: {error}`.
    - When every axis failed, the summary is the failure sentence or sentences, then the not-measured group without NO_NEIGHBOUR or AXIS_FAILED lines (Ruling 12); if nothing is left, the failure sentence alone. The groups describe only the `filled` rows (P6).
- **Never commit site data:** never commit pictures of the site or coordinates. `tests/data/local/` is git-ignored; never `git add -f` from it.
- **Shared-worktree safety:** reviewers and any mutation probes work on a scratch copy, never this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every run.
- **Commits:** end each message with a `Co-Authored-By:` line naming the model that wrote it. Push each commit to `origin nsgeo-auto-destagger` as it is made. Touch no other worktree.

## Verification commands (exactly these, from the worktree root)

The worktree uses the main checkout's virtualenvs, with the worktree's core on `PYTHONPATH`, plus a local `.venv-tools` (git-excluded) holding the CI-pinned ruff 0.17.1 and mypy 2.4.0. Real data is linked under `packages/nsgeo-core/tests/data/local/`:
- the campus lines at the top level;
- `with-dzg/` (Nashville 2023 Grid 1);
- `grid2/` (Nashville 2023 Grid 2).

A real-data test that skips has validated nothing, so the skip count must not rise.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`
  - This takes 10+ minutes. Run single files while iterating; the coordinator runs the full tier.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py packages/nsgeo-qgis/nsgeo_qgis/destagger_job.py` (check `ci.yml` for any file added since; this list must match it).

The baselines are recorded in the ledger at pre-flight.

