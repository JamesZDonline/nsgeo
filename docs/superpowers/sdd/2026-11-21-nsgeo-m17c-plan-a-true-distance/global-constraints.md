## Global Constraints

- **Privacy:** "I'm fine with it as long as there are no coordinates and the site name isn't added." No real coordinate (from a DZG or a DZT header) and no site name in any committed file, test, docstring, commit message or report. Synthetic GPS data uses the existing made-up place (lat 45.2, lon 10.5, EPSG:32632). Real-data tests read `tests/data/local/` (gitignored, symlinked) and assert only on trace indices, steps, counts and metres along a line.
- **Tape lines and cuts are unchanged by construction:** they never get a `TraceAxis`; `ViewTransform` with `axis=None` runs exactly today's code. Existing tests pass unmodified; any change to an existing test is named and justified in the report.
- **Exact values:** `GAP_FACTOR = 6.0`. A step is a gap when it is **longer than** the threshold (`>`, not `>=`). A trace is left out when the steps on **both** sides are gaps; the first and last traces never are. A drawn trace reaches at most **half a usual step** into a gap.
- **Copy, verbatim:** column header `Gap over (m)`; automatic cell `auto {v:.2f}` (e.g. `auto 0.10`); typed cell `{v:.2f}`; read-out over a gap `{m:.2f} m along (gap)`; bulk buttons `Set` and `Automatic`; `GAP_TIP` = "On a GPS line, a step between two traces longer than this is drawn as a gap, and traces with a gap on both sides (lifted over an obstacle) are left out of the profile. Empty means automatic: 6× the line's usual step."; `TAPE_SKIP` = "Left {n} tape line(s) alone: Gap over applies to GPS lines only."; a bad typed value: `{text!r} is not a length above 0; unchanged`.
- **Platforms:** the plugin runs on QGIS 3.44 (PyQt5) and 4.2 (PyQt6); use `nsgeo_qgis.qtcompat` and the enum spellings already used in the touched files. Core stays numpy-only.
- **Tools:** lint with the worktree's `.venv-tools/bin/ruff` (0.17.1) only, never the main `.venv` ruff (it reformats `docs/superpowers`). Commands from the worktree root:
  - core + pure: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider -p no:xonsh`
  - QGIS files: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q -p no:cacheprovider` (add `-m real_data` for the real-data tier)
  - lint: `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`; types: `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo`
- **Schema:** `gap_m` is an optional key on the saved track placement, written only when typed. Schema 4 is unreleased; no new schema number.


## Spec §17 calls that bind every task (from docs/superpowers/specs/2026-11-06-nsgeo-gps-lines-design.md)
- Only GPS lines (TrackPlacement) get a trace axis. Tape lines and cuts keep today's code path exactly, so they look as before by construction, not by tolerance.
- The horizontal map stays the one road through trace centres (`ruler.metres_at` / `trace_units_at`); picks, cursor, selection and ticks keep trace-unit coordinates. Screen x is linear in metres along the line whenever the line has a trace axis.
- Each trace's column runs halfway to its neighbours, but no more than half a usual step into a gap; the rest of a gap is the profile's no-data hatch. Hovering a gap shows no trace and the read-out says "(gap)"; a click there picks nothing.
- Migration re-samples a GPS line onto an even grid at the usual step from the drawn traces only, with nothing (zeros) inside gaps; migrates; reads each trace back at its own distance. A tape line migrates exactly as before. A Gap over change re-prepares what depends on it.
- Slices are NOT changed: they still bin every trace where the GPS put it.
