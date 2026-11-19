# M17a — binding constraints for every task (extracted from the plan)

## Plan calls (Claude's; check while reading)

- **P1 — M17 is three plans.** This is M17a: GPS lines without grids. M17b (true-distance profiles) and M17c (GPS areas) are planned after this plan's walkthrough, against what it really built.
- **P2 — The DZG model.** One `DzgFix` per GGA sentence, paired with the `$GSSIS` just before it. Every fix is kept, whatever its quality, because a non-RTK fix between two RTK fixes is what marks a dropout (P4). A GGA with no position (quality 0, empty fields) is kept with `lat`/`lon` NaN.
  - Any talker counts (`$GNGGA`, `$GPGGA`, …). Other sentences are ignored.
  - A sentence whose `*hh` checksum is wrong is dropped and counted. A sentence with no checksum is accepted.
  - A GGA with no `$GSSIS` before it, and a `$GSSIS` followed by another `$GSSIS` or by a dropped GGA, are counted as unpaired.
  - Trace numbers must rise strictly, and must name traces inside the DZT. Both are errors naming the file, because a wrong pairing misplaces every trace after it (spec §5.1). The real files never repeat a trace: wheel-triggered logging only writes when the scan count has advanced.
- **P3 — Anchors are quality-4 fixes only** (decision 7). A track needs at least two anchors at different places.
- **P4 — A bridge** is a pair of consecutive anchors with at least one non-anchor fix between them. Its `metres` is the straight distance between the two anchors. The traces between are placed on that straight segment, exactly as between ordinary fixes. Both real dropouts (§15) are bridges under this rule.
- **P5 — Ends run on by wheel.**
  - Before the first anchor and after the last, traces continue in a straight line at the line's heading at that end.
  - The heading points from the end anchor towards the first anchor at least `HEADING_BASE_M = 1.0` m away (else the farthest anchor). This keeps 1 Hz jitter out of it.
  - Metres per trace are `1 / traces_per_metre` when that is positive. A time-triggered line (C11) uses the end segment's own metres per trace instead.
  - A run longer than `END_LIMIT_M = 2.0` m is flagged. The real runs are 0–0.67 m at the start and 0 m at the end.
- **P6 — `travel_shift` moves along the walked path.** With `s = travel_shift`, trace `i` sits at arc length `c[i] + s` along the unshifted polyline, which is extended straight past both ends. `distance_along` is `c + s`. The name, units and sign are `GridPlacement`'s: positive moves every trace forward along the way it was walked (§15). The spike measured about +0.24 m on the first survey; that number is never built in.
- **P7 — Projection is injected.** The core takes `to_xy(lon, lat) -> (x, y)`, numpy arrays in degrees in and metres out. The plugin passes a `QgsCoordinateTransform` from EPSG:4326 to the site CRS. Core tests use a local equirectangular helper. Fixes keep their lat/long as read (C10).
- **P8 — The survey file.**
  - A GPS line's placement saves as `{"type": "track", "crs", "label", "fixes": [[trace, x, y, lat, lon, alt_m, geoid_m, quality], …]}`.
  - `grid_id` is written only when set, and `travel_shift` only when non-zero, as `GridPlacement`'s corrections are. Missing values are `null`.
  - `TRACK_SCHEMA_VERSION = VELOCITY_SOURCE_SCHEMA_VERSION + 1` (4). A site with any GPS line saves as 4, and only then gains the top-level `"crs"`.
  - **A site without GPS lines saves exactly as before** (schema 1–3, no `"crs"`).
- **P9 — The site's CRS** (C12).
  - `Site.crs` is read from the file's `"crs"`, else the first grid's, else None.
  - `SiteSession.site_crs()` answers the same way for a live site. `SiteLayers.crs()`, `SiteEngine._site_crs()` and `GridDialog`'s site CRS all read it.
  - `set_site_crs` sets it only when the site has none. The first GPS import into a grid-free site is the only caller.
  - `Site.validate` refuses a GPS line placed in any other CRS.
- **P10 — One CRS rule for both dialogs.** `GridDialog._choose_crs` and its helpers move into `nsgeo_qgis/crs_rule.py`, and `GridDialog` delegates with no change in behaviour.
  - The import uses `choose_crs` when the site has no CRS. The first RTK-fixed fix of the first readable file is the location.
  - When the site has a CRS, each file must be usable in it at its own first RTK-fixed fix, or that row is refused. A site's CRS is never changed by an import.
- **P11 — The import dialog** is modeless and single-instance, shaped like `ImportDialog` (the plugin module docstring's pattern).
  - Rows are planned when files are added. The shift spin box applies to every ready row at Import.
  - The site is re-checked at Import, as `ImportDialog.accept` does.
  - Before Task 4 its layout is shown to the author as a lavish mockup (Checkpoint C1).
- **P12 — The map.**
  - Gridless GPS lines go in the existing `lines` table with `grid_id = ""`, drawn in `NO_GRID_COLOUR` with the same thin dashes as grid lines (#66). `placed_by` is `"tape"` or `"gps"`. The tape-only fields (`axis`, `offset_m`, `start_along_m`, `direction`) are NULL for GPS lines, and `length_m` is the walked length.
  - A new derived table `rtk_gaps` holds one feature per bridge, plus one per end run over `END_LIMIT_M`. It is drawn above the lines in `RTK_GAP_COLOUR`, 0.8 mm, dotted.
  - Marks and picks sit on GPS lines as on any line.
- **P13 — The Survey panel.**
  - GPS lines say so, with their walked length and any metres without RTK.
  - Their menu offers **Set destagger…** in place of **Edit line…** and **Move to grid ▸**. Both of those are tape-only until M17c; `move_lines` silently skips GPS lines today.
  - A selection holding both kinds offers only removal.
- **P14 — Profiles need no new code** (spec §9, M17a: one column per trace).
  - A GPS line's distance axis is `distance_along()`, the walked distance.
  - A line with no grid has no shared ruler (`_ruler_for` already answers None).
  - The velocity fit's metres per trace is `distance[1] − distance[0]`, the wheel's spacing at the start run (P5). That is decision 11's interim, until M17b.
  - Task 6 pins all three with tests.
- **P15 — Merge order with M19a** (spec §15). If M19a merges first, rebase `TRACK_SCHEMA_VERSION` to the next free number, add it to `READABLE_SCHEMA_VERSIONS`, and expect conflicts in `project.py`, `session.py` and `ui/survey_dock.py`. GPS lines are GPR. Nothing here touches mag grids.

## Global Constraints

- **Core:** numpy only (no scipy, no pyproj). The runtime is Python 3.9, so: no `zip(strict=)`, no `match`, and no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new file.
- **Plugin:**
  - `nsgeo_qgis/gps_import.py` imports no Qt and no `qgis`. Add it to the mypy list in `.github/workflows/ci.yml` and to the types command below.
  - Qt is used only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green.
  - Every Qt slot guards its own body: `except Exception as exc:  # noqa: BLE001 -- a slot …`, reporting through `plugin.message` or the dialog's status line, never by raising (the plugin module docstring's rule).
- **Tape lines and grids are unchanged.** A site without GPS lines saves byte-for-byte as before (P8). `ImportDialog` keeps placing by the tapes even when a DZG sits beside a DZT (decision 9).
- **Raw files are never written.**
- **Never commit site data.**
  - `tests/data/local/` is gitignored, and nothing from it is ever added with `git add -f`.
  - Real files reach the worktree only by symlink.
  - No coordinate from a real DZG or DZT header appears in a test assertion, a fixture, a doc or a figure. Real-data tests assert relative quantities only: lengths, counts, trace numbers and bridge metres.
  - Synthetic DZGs use made-up positions near lat 45.2, lon 10.5.
- **Shared-worktree safety:** reviewers and any mutation probes work on a scratch copy, never on this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every run.
- **Commits:** end each message with a `Co-Authored-By:` line naming the model that wrote it. Push each commit to `origin nsgeo-m17-gps` as it is made. Touch no other worktree.

### Copy (exact)

**Core, `DzgError`** (from `read_dzg`; `{name}` is the DZG's file name):
- `"{name}: trace numbers must rise, but {a} is followed by {b}"`
- `"{name}: the GPS log names trace {t}, but the DZT has {n} traces"`

**Core, `TrackPlacement` / `track_from_log`** (`ValueError`; the first two are also import refusals):
- `"no RTK-fixed position"` (none at all)
- `"only one RTK-fixed position"`
- `"the RTK-fixed positions all lie at one point"`
- `"trace numbers must rise along a GPS track"`
- `"travel_shift must be finite, got {value!r}"`

**Core, `Site.validate`:** `"line {name} is placed in {a}, but the site is in {b}"`.

**Plugin, toolbar.** `Import GPS lines…`, placed after `Import DZT…`, with the tip `"Imports DZT files with a DZG beside them, each placed along its RTK GPS track."` It is greyed out until a site is open. It needs no grid.

**Plugin, Import GPS lines dialog.**
- The title is `Import GPS lines`.
- The buttons are `Add files…`, `Remove`, `Import` and `Cancel`.
- The file filter is `"GSSI radar files (*.dzt *.DZT)"`.
- The table columns are:
  - `File`;
  - `Traces`;
  - `RTK fixes` (`"{fixed} of {total}"`);
  - `Without RTK` (`"{m:.1f} m"`, or `—` when there is no bridge);
  - `Ends` (`"{start:.2f} / {end:.2f} m"`);
  - `Status` (`ready`, or the refusal).
- `Destagger (m)` is a spin box from −2.00 to 2.00, step 0.01, starting at 0.00. Its tooltip is `"Moves every trace forward along the way its line was walked, for every line in this import. Change it per line later from the Survey panel."`
- `Coordinates: {authid}`, with the rule's note after it in grey when the note is not empty.
- Refusals, in the `Status` cell:
  - `no DZG beside it`
  - `could not read it: {message}`
  - `no RTK-fixed position`
  - `only one RTK-fixed position`
  - `already in the site (remove it first to place it by GPS)`
  - `outside what {authid} can place`
- Status line:
  - `"Add DZT files that have a DZG beside them."`
  - `"{n} of {m} file(s) ready to import."`
  - `"Nothing to import: no file is ready."`
  - `"The site changed; nothing was imported."`
- After an import, the plugin shows these messages, in this order:
  - `"imported {n} GPS line(s)"`;
  - one `"{file}: {m:.1f} m without an RTK fix, traces {a}–{b}"` per bridge;
  - `"{file}: its start runs {m:.1f} m before the first RTK fix"` and `"{file}: its end runs {m:.1f} m past the last RTK fix"` when over `END_LIMIT_M`;
  - one `"not imported: {file} ({refusal})"` per refused row.

**Plugin, Survey panel.**
- A GPS line row is `"{label} · GPS · {walked:.1f} m"`, plus `" · {gap:.1f} m without RTK"` when its bridges sum above zero. Then come the existing suffixes, unchanged: `" · destagger {s:+.2f} m"`, velocity and fits.
- A GPS line's menu is `Open`, `Set velocity override…`, `Set destagger…`, a separator, then `Remove line from site`.
- A selection of only GPS lines offers `Set destagger for {n} GPS lines…`, a separator, then `Remove {phrase} from site`. A selection holding both kinds offers only the removal.
- **Set destagger** is a `QInputDialog.getDouble` titled `Destagger`. Its label is `"Move every trace forward along the way its line was walked, for {n} GPS line(s), by (m):"`. It runs from −2.0 to 2.0 with 2 decimals, and starts at the lines' shared value, or at 0.0 when they differ.
- After a change, the message `"destagger set to {m:+.2f} m on {n} GPS line(s)"`.

**Plugin, map.** The table is `rtk_gaps`, with fields `line_key`, `kind` (`bridge`, `start`, `end`), `first_trace`, `last_trace` and `metres`.

## Verification commands (exactly these, from the worktree root)

The worktree uses the main checkout's virtualenvs, with the worktree's core on `PYTHONPATH`. A local `.venv-tools` (git-excluded) holds the CI-pinned ruff 0.17.1 and mypy 2.4.0. A real-data test that skips has validated nothing, so the skip count must not rise.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`. This takes 10+ minutes. Run single files while iterating; the coordinator runs the full tier.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py packages/nsgeo-qgis/nsgeo_qgis/export_pipeline.py packages/nsgeo-qgis/nsgeo_qgis/destagger_job.py packages/nsgeo-qgis/nsgeo_qgis/gps_import.py`. From Task 4 on, this list must match `ci.yml`. Before Task 4, leave out the last file.

