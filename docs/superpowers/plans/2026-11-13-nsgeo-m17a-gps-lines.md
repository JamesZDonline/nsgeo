# M17a: GPS Lines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** Read the RTK GPS log (`.DZG`) beside each GSSI `.DZT`, place the line along its walked track, and import, draw, list and destagger such lines without any grid.

**Architecture:**
- **Core (numpy only).**
  - `nsgeo.io.dzg` reads a DZG into fixes, each tied to an exact trace.
  - `nsgeo.geometry.track.TrackPlacement` is the second `Placement`. It places traces between RTK-fixed fixes by trace number, bridges dropouts, runs the ends on by wheel, and carries the same `travel_shift` as `GridPlacement`.
  - Projection from lat/long is *injected* as a function, so the core never needs a CRS library.
  - `Site` gains its own CRS, and the survey file saves GPS lines as schema 4.
- **Plugin.**
  - A shared CRS rule (`crs_rule.py`, moved out of `GridDialog`).
  - A Qt-free import planner (`gps_import.py`) and an **Import GPS lines…** dialog.
  - Gridless lines drawn on the map, with a new `rtk_gaps` table.
  - GPS rows in the Survey panel, with **Set destagger…**.

**Tech Stack:** Python ≥ 3.9 and numpy (core); PyQt via `qgis.PyQt` and `qgis.core` (plugin); pytest on two tiers (core+pure, QGIS).

**Spec:** `docs/superpowers/specs/2026-11-06-nsgeo-gps-lines-design.md`, approved 2026-11-13. Read §2, §3, §4, §5, §6.1, §6.2, §9 (M17a), §10 and **§15 first** (what main changed since the design). The spec's author decisions are cited as decision 1–12 and its calls as C1–C13. This plan's own calls are P1–P15, cited as `(M17a plan, P<n>)`.

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

## Review Focus

These are the inputs a person will meet that the spec implies but does not spell out. Each is pinned by a test in its owning task.

1. **A real dropout:** float fixes in the middle of a line, or at its very end. The line is placed across them on a straight bridge. The bridge is listed with its traces and metres, and drawn in `rtk_gaps`. Pinned by Task 2, `test_the_second_surveys_dropouts_are_bridged` (grid2 `FILE__039` and `FILE__042`), and Task 5, `test_a_bridge_is_drawn_in_rtk_gaps`.
2. **A DZT with no DZG, or a DZG that belongs to another file** (trace numbers past the DZT's end). The row is refused with its reason and nothing is added. Pinned by Task 1, `test_a_trace_beyond_the_dzt_is_refused`, and Task 4, `test_rows_that_cannot_be_placed_are_refused_with_their_reason`.
3. **The site's coordinates cannot place the lines:** an existing site whose CRS is a UTM zone far away, or a project in degrees with no site CRS yet. The site's CRS is never changed silently. The far file is refused, and a grid-free site gets the location's UTM zone with a note. Pinned by Task 4, `test_a_file_outside_the_site_crs_is_refused` and `test_a_geographic_project_gets_the_utm_zone_with_a_note`.
4. **A saved site reopened after its DZG was moved or deleted.** It reopens with identical positions (C10). Pinned by Task 3, `test_a_gps_line_round_trips_with_identical_positions_without_its_dzg`.
5. **A file imported twice, or already in the site as a tape line.** It is refused and told how to switch (C9). Pinned by Task 4, `test_a_file_already_in_the_site_is_refused_with_how_to_switch`.

---

## Pre-flight (coordinator, before Task 1)

- [ ] Commit the roadmap's *In progress* entry straight to main from a throwaway worktree: "**M17a: GPS lines** — reading DZG files and placing lines along their RTK track, without a grid. Building." Move the M17 item in *Next* to say part one is in progress. Push it. Keep site names out.
- [ ] Create `.venv-tools`: `../../.venv/bin/python -m venv .venv-tools && .venv-tools/bin/pip install ruff==0.17.1 mypy==2.4.0 numpy`.
- [ ] Link the real files.
  - The two GPS surveys, as directories: `ln -s /home/jameszd/Documents/Github/archaeo_geophysics/packages/nsgeo-core/tests/data/local/with-dzg packages/nsgeo-core/tests/data/local/with-dzg`, and the same for `grid2`.
  - The ten campus files, file by file, into `packages/nsgeo-core/tests/data/local/`.
  - Then check that `git status --short` shows nothing new.
  - `grid2`'s files are themselves links to the author's data disk. If that disk is not mounted, its tests skip, and the coordinator must say so in the ledger rather than record the skips as a baseline.
- [ ] Run the four verification commands and record the pass and skip counts in the ledger (`.superpowers/sdd/`) as baselines.

---

### Task 1: Read DZG files (nsgeo-core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/io/dzg.py`
- Modify: `packages/nsgeo-core/src/nsgeo/io/__init__.py` (export the five names below, sorted)
- Create: `packages/nsgeo-core/tests/dzg_data.py`, `test_dzg.py`, `test_dzg_real_files.py`
- Modify: `packages/nsgeo-core/README.md` (a short DZG paragraph under the io section, naming each public name in backticks)

**Interfaces (produced):**

```python
# nsgeo/io/dzg.py
RTK_FIXED: int = 4
class DzgError(ValueError): ...

@dataclass(frozen=True)
class DzgFix:
    trace: int                # 0-based DZT trace index, from the $GSSIS before the GGA
    utc_s: float | None       # GGA time, seconds of the UTC day
    lat: float                # degrees, S negative; NaN when the GGA has no position
    lon: float                # degrees, W negative; NaN likewise
    quality: int              # GGA fix quality: 4 RTK fixed, 5 float, 1 GPS, 2 DGPS, 0 none
    n_sats: int | None
    hdop: float | None
    alt_m: float | None       # antenna altitude above mean sea level (GGA field 9)
    geoid_m: float | None     # geoid separation (GGA field 11)

@dataclass(frozen=True)
class DzgLog:
    fixes: tuple[DzgFix, ...]    # in file order; traces strictly rising
    bad_checksum: int
    unpaired: int
    @property
    def n_fixed(self) -> int: ...   # fixes with quality == RTK_FIXED

def dzg_for(path: str | Path) -> Path | None: ...   # the .DZG beside a .DZT, either case; dzx.sidecar_for's directory-listing rule
def read_dzg(path: str | Path, n_traces: int | None = None) -> DzgLog: ...   # P2; checks the trace range only when n_traces is given
```

- [ ] **Step 1: Write the failing tests.**
  - `tests/dzg_data.py` is a helper.
    - `write_dzg(path: Path, fixes: Sequence[tuple[int, float, float, int]], *, talker: str = "GN", alt_m: float = 120.0, geoid_m: float = 47.5) -> Path` writes, for each `(trace, lat, lon, quality)`:
      - `$GSSIS,{trace},-1`;
      - then a `${talker}GGA` with the real files' field layout. For a made-up fix that is `$GNGGA,163915.40,4512.3456789,N,01030.1234567,E,4,22,0.6,120.000,M,47.500,M,1.4,0000*hh`, where `hh` is the computed checksum: 7 decimals of minutes, satellites, HDOP, altitude and geoid separation each followed by `M`, correction age, station id. The time steps 1.0 s per fix from 163915.40. Never copy a sentence from a real file into a test or a doc.
      - CRLF line ends, as the real files have.
    - It also has `local_xy(lat0: float, lon0: float)`, which returns a `(lon, lat) -> (x, y)` function: a local equirectangular projection in metres about that point. Real-data tests use it so that they assert relative distances only. It is Task 2's `ToXY` shape; Task 1 only defines it.
  - `test_dzg.py`:
    - `test_reads_gssis_and_gga_pairs_in_order`: fixes at traces 13, 26, 47 round-trip with their quality, `alt_m`, `geoid_m`, `n_sats` and `hdop`. `lat` and `lon` decode ddmm.mmmmmmm with the hemisphere: `4512.3456789,N` gives `45 + 12.3456789/60`, `01030.1234567,E` gives `10 + 30.1234567/60`, and an `S` or `W` hemisphere is negative. `utc_s` of `163915.40` is `16*3600 + 39*60 + 15.4`.
    - `test_any_talker_reads_as_gga`: `talker="GP"` reads the same fixes.
    - `test_other_sentences_are_ignored`: a `$GNRMC,…` line between two pairs changes nothing.
    - `test_a_bad_checksum_drops_the_sentence_and_counts_it`: one GGA's checksum is altered. That fix is missing, `bad_checksum == 1`, and `unpaired == 1` (its `$GSSIS`).
    - `test_a_gga_with_no_preceding_gssis_is_unpaired`.
    - `test_a_gga_with_no_position_reads_as_nan_with_its_quality`: `$GNGGA,163916.40,,,,,0,0,,,M,,M,,*hh` gives `quality == 0` with NaN lat/lon and `None` for the rest.
    - `test_trace_numbers_that_do_not_rise_are_refused`: traces 40 then 12 raise `DzgError` matching `r"x\.DZG: trace numbers must rise, but 40 is followed by 12"`. 40 then 40 is refused the same way.
    - `test_a_trace_beyond_the_dzt_is_refused`: `read_dzg(p, n_traces=50)` on a fix at trace 50 matches `r"names trace 50, but the DZT has 50 traces"`. With `n_traces=None` it reads.
    - `test_dzg_for_finds_either_case_and_none_when_absent`: `a.DZT` with `a.dzg` beside it gives `…/a.dzg`. With nothing beside it, None.
  - `test_dzg_real_files.py`, using `GPS_LINES` and `GRID2_LINES` from `tests/real_data.py`, each test skipping on an empty list:
    - `test_every_gps_line_has_a_dzg_that_reads_cleanly`: for every DZT in both lists, `dzg_for` finds the DZG, `read_dzg(dzg, trace_count(...))` succeeds, and `bad_checksum == unpaired == 0`.
    - `test_the_first_survey_is_rtk_fixed_throughout`: 2,999 fixes over the 60 lines, all quality 4.
    - `test_the_second_survey_has_float_fixes_on_two_lines`: 2,523 fixes. The non-4 fixes, keyed by file name within `GRID2_LINES`, are exactly `{"FILE__039.DZG": [190, 212, 239], "FILE__042.DZG": [1753, 1754]}`, all quality 5.
- [ ] **Step 2: Run them and see each fail** (import error first).
- [ ] **Step 3: Implement `nsgeo/io/dzg.py`** to P2. The checksum is the XOR of every character between `$` and `*`.
- [ ] **Step 4: Run core + pure, lint and types.** All pass, and the skip count is unchanged.
- [ ] **Step 5: Commit** (`feat(core): read GSSI DZG GPS logs (#134)`) and push.

---

### Task 2: `TrackPlacement` (nsgeo-core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/track.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/__init__.py` (export `Bridge`, `TrackFix`, `TrackPlacement`, `track_from_log`, sorted)
- Create: `packages/nsgeo-core/tests/test_track.py`, `test_track_real_files.py`
- Modify: `packages/nsgeo-core/README.md` (a short `TrackPlacement` paragraph)

**Interfaces:**
- Consumes: Task 1's `DzgLog`, `DzgFix` and `RTK_FIXED`.
- Produces:

```python
# nsgeo/geometry/track.py
ToXY = Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]   # (lon, lat) degrees -> (x, y) metres
END_LIMIT_M: float = 2.0
HEADING_BASE_M: float = 1.0

@dataclass(frozen=True)
class TrackFix:
    trace: int
    x: float                  # metres in the placement's crs; NaN for a fix with no position
    y: float
    lat: float
    lon: float
    alt_m: float | None = None
    geoid_m: float | None = None
    quality: int = 4

@dataclass(frozen=True)
class Bridge:
    first_trace: int          # the anchor before the dropout
    last_trace: int           # the anchor after it
    metres: float             # straight distance between the two anchors

@dataclass(frozen=True)
class TrackPlacement:
    fixes: tuple[TrackFix, ...]
    crs: str
    grid_id: str | None = None
    label: str | None = None
    travel_shift: float = 0.0
    # __post_init__: P3 + the Copy's ValueErrors (traces strictly rising, >= 2 anchors, not all at one point, finite shift)
    def anchors(self) -> tuple[TrackFix, ...]: ...
    def bridges(self) -> tuple[Bridge, ...]: ...                                 # P4, in trace order
    def positions(self, n_traces: int, header: DztHeader) -> np.ndarray: ...     # (n, 2) unshifted, P4/P5
    def end_runs(self, n_traces: int, header: DztHeader) -> tuple[float, float]: ...  # metres placed before the first / after the last anchor
    def distance_along(self, n_traces: int, header: DztHeader) -> np.ndarray: ...     # P6: c + s
    def trace_coords(self, n_traces: int, header: DztHeader, frames: Mapping[str, Grid]) -> np.ndarray: ...  # P6; frames ignored

def track_from_log(log: DzgLog, to_xy: ToXY, crs: str, *, label: str | None = None) -> TrackPlacement: ...
# Projects every fix with a position. Raises ValueError("no RTK-fixed position") or ValueError("only one RTK-fixed position")
# before building, so the import can show those words as they are.
```

**The shift** (P6). Let `P` be `positions(...)` and `c` its cumulative path length, with `c[0] = 0`. Trace `i` goes to the point at arc length `c[i] + s` along `P`. Beyond `c[-1]` it continues along `P[-1] − P[-2]`, and before 0 along `P[0] − P[1]`, both normalised. Repeated arc lengths, from coincident positions, must not divide by zero.

- [ ] **Step 1: Write the failing tests** (`test_track.py`). Headers come from `tests.synthetic.write_dzt` + `read_header`, at `traces_per_metre=10.0` unless stated.
  - `test_traces_between_fixes_are_spaced_evenly_by_trace`: anchors `(trace, x, y)` = (10, 0, 0), (40, 3, 0), (70, 3, 4). Trace 25 is at (1.5, 0) and trace 55 at (3, 2).
  - `test_distance_along_is_the_walked_path`: with the same anchors and 81 traces, `d[70] − d[10] == 7.0` (3 + 4 m), and `d` never falls.
  - `test_the_start_runs_on_by_wheel_along_the_heading`: anchors at (5, 0, 0) and (25, 2, 0). Trace 0 is at (−0.5, 0), five traces of 0.1 m back along +x.
  - `test_the_heading_uses_an_anchor_at_least_a_metre_away`: anchors (5, 0, 0), (7, 0.1, 0.15) and (25, 2, 0). Trace 0's y is 0 to 1e-9, because the jittery near anchor is skipped.
  - `test_a_time_triggered_line_runs_on_at_its_end_segments_spacing`: at `traces_per_metre=0.0`, with anchors (5, 0, 0) and (25, 2, 0), trace 0 is at (−0.5, 0), because the segment's 0.1 m per trace is used.
  - `test_float_and_plain_fixes_are_bridged_not_used`: anchors at traces 10 (0, 0) and 50 (4, 0), with a quality-5 fix at trace 30 placed at (2, 0.5). Trace 30 is at (2, 0), and `bridges() == (Bridge(10, 50, 4.0),)`.
  - `test_a_fix_with_no_position_still_marks_a_bridge`: the same, with a quality-0 fix (NaN x/y) at trace 30.
  - `test_travel_shift_moves_every_trace_forward_along_the_path`:
    - On a straight track along +x with `travel_shift=0.24`, every x grows by 0.24 and y is unchanged.
    - On the L-shaped track of the first test, the trace 0.24 m before the corner lands 0.24 m past it, on the +y leg.
    - `distance_along` grows by exactly 0.24 everywhere.
  - `test_a_negative_shift_runs_back_past_the_start_in_a_straight_line`.
  - `test_fewer_than_two_anchors_or_one_point_is_refused`: each of the Copy's `ValueError` messages, by `pytest.raises(match=…)`.
  - `test_end_runs_are_the_metres_beyond_the_first_and_last_anchor`: anchors at traces 5 and 25 on a 31-trace line give `(0.5, 0.5)`.
  - `test_track_from_log_projects_with_the_given_function_and_keeps_lat_lon`: `to_xy = lambda lon, lat: (lon * 100.0, lat * 100.0)`. Each `TrackFix` has those x/y and the lat/lon as read. A log with one quality-4 fix raises `ValueError("only one RTK-fixed position")`.
  - `test_frames_are_not_needed`: `trace_coords(n, header, {})` works.
- [ ] **Step 2: Write the failing real-data tests** (`test_track_real_files.py`), building each line with `track_from_log(read_dzg(...), local_xy(first fix), "LOCAL")`:
  - `test_file_011_is_placed_along_its_whole_walk`: `GPS_LINES`' `FILE__011.DZT` has 1,560 traces (26.0 m by wheel). Its walked length, `d[-1] − d[0]`, lies between 29.5 and 30.6 m.
  - `test_the_second_surveys_dropouts_are_bridged`:
    - in `GRID2_LINES`, `FILE__039` has exactly one bridge, traces 149 to 246, with `metres` 1.83 ± 0.02;
    - `FILE__042` has exactly one, 1739 to 1755, 0.39 ± 0.02;
    - every other `GRID2_LINES` line has none.
  - `test_every_first_survey_line_starts_close_to_its_first_fix_and_ends_at_its_last`: over `GPS_LINES`, every start run is ≤ 0.70 m and every end run ≤ 0.05 m.
- [ ] **Step 3: Run them and see each fail.**
- [ ] **Step 4: Implement `nsgeo/geometry/track.py`** to P3–P7.
- [ ] **Step 5: Run core + pure, lint and types.** All pass, and the skip count is unchanged.
- [ ] **Step 6: Commit** (`feat(core): TrackPlacement — place traces along an RTK track (#134)`) and push.

---

### Task 3: The site's CRS, and GPS lines in the survey file (core + session)

**Files:**
- Modify:
  - `packages/nsgeo-core/src/nsgeo/model/survey.py`: `Site.crs` and `Site.validate`.
  - `packages/nsgeo-core/src/nsgeo/project.py`: the track dict, the `"crs"` key, `TRACK_SCHEMA_VERSION` and `READABLE_SCHEMA_VERSIONS`.
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `site_crs`, `set_site_crs`.
  - `packages/nsgeo-qgis/nsgeo_qgis/layers.py`: `crs()` reads `session.site_crs()`.
  - `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`: `_site_crs` likewise.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`: `_site_crs` likewise.
- Test:
  - `packages/nsgeo-core/tests/test_project.py`, `test_schema.py` and `test_survey.py`, which gain the tests below.
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` likewise.

**Interfaces:**
- Consumes: Task 2's `TrackPlacement` and `TrackFix`.
- Produces:

```python
# nsgeo/model/survey.py — Site gains
crs: str | None = None        # P9; GPS lines are placed in it

# nsgeo/project.py
TRACK_SCHEMA_VERSION = VELOCITY_SOURCE_SCHEMA_VERSION + 1        # 4 (P8, P15)
READABLE_SCHEMA_VERSIONS = (..., TRACK_SCHEMA_VERSION)

# nsgeo_qgis/session.py — SiteSession gains
def site_crs(self) -> str | None: ...          # site.crs, else the first grid's crs, else None
def set_site_crs(self, crs: str) -> None: ...  # ValueError(f"the site already uses {old}") when site_crs() is set; marks dirty
```

- [ ] **Step 1: Write the failing core tests.**
  - `test_a_gps_line_round_trips_with_identical_positions_without_its_dzg`:
    - Save a site with one GPS line: synthetic DZT + DZG, `track_from_log`, `travel_shift=0.24`, one fix with `alt_m=None`.
    - Delete the DZG, then load the site.
    - The loaded placement equals the saved one (dataclass equality, NaN fields compared with `math.isnan`). `trace_coords` matches to 1e-9.
  - `test_a_site_with_a_gps_line_saves_as_schema_4_and_names_its_crs`: `doc["schema_version"] == 4` and `doc["crs"] == "EPSG:32632"`.
  - `test_a_site_without_gps_lines_saves_exactly_as_before`: a grid-and-tape-line site saves with no `"crs"` key, as schema 1. With a cut it saves as 2, and with a velocity source as 3, as on `origin/main`. Loading and saving again gives the same JSON text.
  - `test_an_older_site_takes_its_crs_from_its_first_grid` (load, then `site.crs == grids[0].crs`).
  - `test_a_grid_free_site_keeps_its_crs` (GPS lines and no grids round-trip `crs`).
  - `test_travel_shift_and_grid_id_are_written_only_when_set`.
  - `test_a_gps_line_in_another_crs_is_refused_by_validate` (the Copy's message).
  - `test_schema_4_is_readable_and_5_is_not`.
- [ ] **Step 2: Write the failing QGIS tests** (`test_plugin_session.py`):
  - `test_site_crs_is_the_first_grids_until_the_site_has_its_own`;
  - `test_set_site_crs_refuses_to_change_a_set_crs`;
  - `test_layers_crs_follows_the_site_crs_on_a_grid_free_site`.
- [ ] **Step 3: Run them and see each fail.**
- [ ] **Step 4: Implement** to P8/P9. The version is the highest that applies: track, then velocity source, then cuts, then 1.
- [ ] **Step 5: Run core + pure, the touched QGIS files (`test_plugin_session.py`, `test_plugin_grid_dialog.py`, `test_plugin_layers.py`, `test_plugin_site_engine.py`), lint and types.**
- [ ] **Step 6: Commit** (`feat: a site has its own CRS; GPS lines save as schema 4 (#134)`) and push.

---

### Checkpoint C1 (coordinator, before Task 4)

- [ ] Mock up the **Import GPS lines** dialog and the GPS rows of the Survey panel in lavish. Use the Copy above, made-up file names and made-up numbers. The author approves, changes or waives it. Record the answer in the ledger, and fold any copy change into Tasks 4 and 6 before they start.

---

### Task 4: Import GPS lines… (plugin)

**Files:**
- Create:
  - `packages/nsgeo-qgis/nsgeo_qgis/crs_rule.py`;
  - `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py`, which has no Qt;
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/gps_import_dialog.py`.
- Modify:
  - `ui/grid_dialog.py`: delegate to `crs_rule`, and import `CRS_SCALE_WARN`/`CRS_SCALE_REFUSE` from it;
  - `plugin.py`: the toolbar action, `open_gps_import_dialog` and the messages;
  - `.github/workflows/ci.yml`: add `gps_import.py` to the mypy list;
  - `packages/nsgeo-qgis/tests/plugin_testing.py`: `synthetic_gps_dzt`.
- Test:
  - `packages/nsgeo-qgis/tests/pure/test_pure_gps_import.py`;
  - `tests/qgis/test_plugin_crs_rule.py`;
  - `tests/qgis/test_plugin_gps_import_dialog.py`.
  - `test_plugin_grid_dialog.py` must stay green, unchanged.

**Interfaces:**
- Consumes: Tasks 1–3 (`read_dzg`, `dzg_for`, `track_from_log`, `ToXY`, `Bridge`, `END_LIMIT_M`, `site_crs`, `set_site_crs`).
- Produces:

```python
# nsgeo_qgis/crs_rule.py  (qgis.core)
CRS_SCALE_WARN = 0.001
CRS_SCALE_REFUSE = 0.02
def crs_scale_error(crs: QgsCoordinateReferenceSystem, point: QgsPointXY) -> float | None: ...
def crs_check(crs: QgsCoordinateReferenceSystem, point: QgsPointXY | None) -> tuple[str | None, float | None]: ...  # None point: no scale check
def usable_at(crs: QgsCoordinateReferenceSystem, lonlat: QgsPointXY) -> tuple[str | None, float | None]: ...
def project_reason(crs: QgsCoordinateReferenceSystem, kind: str | None, scale_error: float | None) -> str: ...
def choose_crs(site: QgsCoordinateReferenceSystem | None, project: QgsCoordinateReferenceSystem,
               lonlat: QgsPointXY) -> tuple[QgsCoordinateReferenceSystem, str]: ...   # GridDialog._choose_crs's rule and notes, unchanged

# nsgeo_qgis/gps_import.py  (no Qt, no qgis)
@dataclass(frozen=True)
class GpsRow:
    path: Path
    line: Line | None              # placed at travel_shift 0; None when refused
    n_traces: int | None
    n_fixes: int
    n_fixed: int
    bridges: tuple[Bridge, ...]
    end_runs: tuple[float, float]
    refusal: str | None            # the Copy's refusal words, or None when ready
    @property
    def without_rtk_m(self) -> float: ...          # sum of bridge metres

def first_fixed_lonlat(path: Path) -> tuple[float, float] | None: ...   # (lon, lat) of the DZG's first RTK fix; None if unreadable or none
def plan_gps_rows(paths: Sequence[Path], to_xy: ToXY, crs: str,
                  taken: Callable[[Path], bool],
                  usable: Callable[[float, float], bool]) -> list[GpsRow]: ...
def shifted_lines(rows: Sequence[GpsRow], metres: float) -> list[Line]: ...   # ready rows only, travel_shift set
def import_messages(rows: Sequence[GpsRow], imported: int) -> list[str]: ...  # the Copy's after-import messages, in order

# tests/plugin_testing.py
def synthetic_gps_dzt(folder: Path, name: str, track: Sequence[tuple[int, float, float, int]],
                      n_traces: int = 200, **kw) -> Path: ...   # DZT via synthetic_dzt + DZG via tests.dzg_data.write_dzg; (trace, lat, lon, quality)
```

- **The plugin's `to_xy`:** a `QgsCoordinateTransform` from EPSG:4326 to the chosen CRS over `QgsProject.instance()`. It is applied point by point (about 100 fixes a line), and NaN stays NaN.
- **`usable`** is `crs_rule.usable_at(crs, lonlat)[0] is None`, at each row's own first RTK fix.
- **`taken`** is `lambda p: nsgeo.project.line_key(p, session.root, allow_absolute=True) in set(session.keys())`, the key `SiteSession.line_key` computes.

- [ ] **Step 1: Write the failing pure tests** (`test_pure_gps_import.py`, with a fake `to_xy` and synthetic files from `tests.synthetic` and `tests.dzg_data`):
  - `test_a_ready_row_carries_its_line_counts_bridges_and_ends`.
  - `test_rows_that_cannot_be_placed_are_refused_with_their_reason`. One row each gives `no DZG beside it`, `no RTK-fixed position`, `only one RTK-fixed position`, and `could not read it: …` for a DZG with a falling trace. Its `line` is None.
  - `test_a_file_already_in_the_site_is_refused_with_how_to_switch`.
  - `test_a_file_outside_the_site_crs_is_refused` (`usable` returns False; the refusal names the CRS).
  - `test_shifted_lines_sets_the_shift_on_ready_rows_only`.
  - `test_import_messages_follow_the_copy_in_order`: one bridge, one start run of 2.5 m, one refusal. The exact strings, in the Copy's order.
- [ ] **Step 2: Write the failing QGIS tests.**
  - `test_plugin_crs_rule.py`:
    - `test_a_metre_project_crs_usable_here_is_kept`: project EPSG:32632 at lon 10.5, lat 45.2 gives EPSG:32632 with note `""`.
    - `test_a_geographic_project_gets_the_utm_zone_with_a_note`: project EPSG:4326 at the same point gives EPSG:32632, with a note starting `"picked for you:"`.
    - `test_the_site_crs_wins_when_usable`.
  - `test_plugin_gps_import_dialog.py`:
    - `test_adding_files_plans_rows_and_shows_the_coordinates` (cells per the Copy).
    - `test_import_adds_gps_lines_sets_the_site_crs_and_applies_the_shift`: a grid-free site, two synthetic GPS files, spin 0.24. The result is two `TrackPlacement` lines with `travel_shift == 0.24`, `session.site_crs() == "EPSG:32632"`, and the messages are shown.
    - `test_an_import_into_a_site_with_grids_uses_their_crs`.
    - `test_import_after_the_site_was_replaced_adds_nothing` (`"The site changed; nothing was imported."`).
    - `test_the_tape_import_still_places_by_the_tapes_beside_a_dzg`: `ImportDialog` on a DZT with a DZG beside it gives a `GridPlacement`.
    - `test_the_toolbar_action_needs_an_open_site_but_no_grid`.
    - `test_importing_the_first_gps_survey` (real data, skips without `GPS_LINES`): all 60 import. `FILE__011`'s walked length is 29.5–30.6 m, and no message names a bridge.
- [ ] **Step 3: Run them and see each fail.**
- [ ] **Step 4: Implement `crs_rule.py`.** Move the methods' bodies out of `GridDialog` unchanged. `GridDialog._crs_check(crs, None)` keeps substituting the form's origin before delegating. Run `test_plugin_grid_dialog.py`: green and unchanged.
- [ ] **Step 5: Implement `gps_import.py`, the dialog and the plugin wiring** to P10/P11 and the Copy. Accept re-checks `session.json_path` against the one the dialog opened with. Then, in this order:
  1. `set_site_crs` if the site has none;
  2. `add_lines(shifted_lines(rows, spin))` in one call;
  3. `plugin.message` for each `import_messages` line.
- [ ] **Step 6: Run core + pure, the three new QGIS files plus `test_plugin_grid_dialog.py` and `test_plugin_import_dialog.py`, lint, and types (now with `gps_import.py`).**
- [ ] **Step 7: Commit** (`feat(plugin): Import GPS lines… — place DZTs along their RTK track (#134)`) and push.

---

### Task 5: GPS lines on the map (plugin)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers_gps.py`
- `test_plugin_layers.py` must stay green, unchanged.

**Interfaces:**
- Consumes: Task 2 (`TrackPlacement.bridges`, `end_runs`, `END_LIMIT_M`) and Task 3 (`session.site_crs`).
- Produces:

```python
# layers.py
TABLES["lines"]   # gains ("placed_by", "str") and ("without_rtk_m", "float"), after "file_name"
TABLES["rtk_gaps"] = (QgsWkbTypes.Type.LineString,
    [("line_key", "str"), ("kind", "str"), ("first_trace", "int"), ("last_trace", "int"), ("metres", "float")])
DERIVED = ("grids", "lines", "marks", "cuts", "rtk_gaps")
LEGEND_ORDER = ("picks", "marks", "cuts", "rtk_gaps", "lines", "grids")
NO_GRID_COLOUR = "#636363"
RTK_GAP_COLOUR = "#e377c2"     # in no grid colour and not the cut colour
def _line_crs(self, line: Line) -> str | None: ...          # a grid line's grid crs; a GPS line's placement crs
def _line_points(self, line: Line, frames: dict[str, Grid]) -> list[QgsPointXY] | None: ...   # was (line, grid, frames); every caller updated
def refill_rtk_gaps(self) -> None: ...
```

- **`refresh()`** clears the derived tables only when the site has neither grids nor lines.
- **`refill_lines`, `refill_marks`, `follow_lines` and the pick placement** treat a line with no grid like any other, through `_line_points`.
- **`_style_lines`** adds the `""` category, labelled `No grid`, in `NO_GRID_COLOUR`, with the same width and dashes as the grid categories.
- **`rtk_gaps` features:**
  - one `bridge` per `Bridge`, along the line's trace positions `first_trace..last_trace`;
  - a `start` feature for a start run over `END_LIMIT_M`, from trace 0 to the first anchor; `end` likewise.
  - It is styled `RTK_GAP_COLOUR`, 0.8 mm, dotted (custom dash 0.5/1.0 mm), and is not selectable.

- [ ] **Step 1: Write the failing tests** (`test_plugin_layers_gps.py`), on synthetic GPS lines built with `synthetic_gps_dzt`, `read_dzg`, `track_from_log` and `session.add_lines`:
  - `test_a_gps_line_with_no_grid_is_drawn_along_its_track`: the vertices equal `trace_coords` in the site CRS. `placed_by == "gps"`, `grid_id == ""`, the tape-only fields are NULL, and `length_m` equals the walked length.
  - `test_a_grid_free_site_draws_its_gps_lines`.
  - `test_a_bridge_is_drawn_in_rtk_gaps`: one `bridge` feature with that bridge's traces and metres.
  - `test_only_long_end_runs_are_drawn`: a 3 m start run gives a `start` feature, and a 0.5 m one none.
  - `test_marks_on_a_gps_line_sit_on_its_track`: a DZX with a mark at scan 50 gives the point `trace_coords[50]`.
  - `test_a_pick_on_a_gps_line_sits_on_its_track`.
  - `test_tape_lines_are_drawn_as_before_with_placed_by_tape`.
  - `test_an_older_package_gains_the_new_fields_and_table`: a package written with the old `lines` fields is rebuilt, and `rtk_gaps` is created.
  - `test_the_second_surveys_dropout_is_drawn` (real data, skips without `GRID2_LINES`): `FILE__039` gives one `bridge`, traces 149 to 246.
- [ ] **Step 2: Run them and see each fail.**
- [ ] **Step 3: Implement** to P12.
- [ ] **Step 4: Run `test_plugin_layers_gps.py`, `test_plugin_layers.py`, `test_plugin_map_link.py` and `test_plugin_pick_tool.py`, then lint and types.**
- [ ] **Step 5: Commit** (`feat(plugin): GPS lines, their gaps, marks and picks on the map (#134)`) and push.

---

### Task 6: GPS lines in the Survey panel, destagger and profiles (plugin + guide)

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `is_gps_line`, `set_travel_shift`;
  - `ui/survey_dock.py`: the row text, the menus and `destagger_requested`;
  - `plugin.py`: the destagger dialog;
  - `docs/guide/getting-started.md`: a new step after Step 3, *Import GPS lines*;
  - `packages/nsgeo-qgis/README.md`: one line naming the feature.
- Test: `tests/qgis/test_plugin_survey_dock.py`, `test_plugin_session.py` and `test_plugin_profile_dock.py` gain the tests below.

**Interfaces:**
- Consumes: Task 2's `TrackPlacement` and Task 4's `synthetic_gps_dzt`.
- Produces:

```python
# session.py
def is_gps_line(self, key: str) -> bool: ...          # isinstance(placement, TrackPlacement)
def set_travel_shift(self, keys: Iterable[str], metres: float) -> None: ...
# All or nothing: KeyError for an unknown key; ValueError(f"{name} is not a GPS line") for a tape line; ValueError for a non-finite value.
# One dirty mark and one lines_changed; a no-op when nothing would change.

# survey_dock.py
destagger_requested = pyqtSignal(list)                 # GPS line keys
```

- **The guide step** says:
  - what a DZG is;
  - that lines are placed along the walk with no grid;
  - what `Without RTK` and the `rtk_gaps` layer mean;
  - that the destagger can be measured later (M17c);
  - that a tape-placed line is switched by removing it and importing it again.

  It has no screenshots from real data.

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_session.py`:
    - `test_set_travel_shift_is_one_change`;
    - `test_set_travel_shift_refuses_a_tape_line_and_changes_nothing`;
    - `test_a_pick_on_a_gps_line_follows_its_destagger`: after `set_travel_shift(…, 0.5)`, the pick's map point moves 0.5 m along the track.
  - `test_plugin_survey_dock.py`:
    - `test_a_gps_line_row_reads_gps_length_and_gaps`: for a synthetic line with a 1.8 m bridge and a 29.8 m walk, the text is exactly `"… · GPS · 29.8 m · 1.8 m without RTK"`.
    - `test_a_destaggered_gps_line_row_names_it` (`" · destagger +0.24 m"`).
    - `test_a_gps_line_menu_offers_destagger_not_edit_or_move`.
    - `test_a_gps_only_selection_offers_destagger_for_all`.
    - `test_a_mixed_selection_offers_only_removal`.
    - `test_set_destagger_starts_at_the_shared_value_and_applies_to_all`: drive the dialog with a monkeypatched `QInputDialog.getDouble`, then check the message.
  - `test_plugin_profile_dock.py`:
    - `test_a_gps_line_opens_with_walked_distance_and_no_ruler`: the bottom axis runs from `travel_shift` to walked length plus `travel_shift`, and `_ruler_for` is None.
    - `test_the_velocity_fit_on_a_gps_line_uses_the_wheel_spacing` (P14).
- [ ] **Step 2: Run them and see each fail.**
- [ ] **Step 3: Implement** to P13/P14 and the Copy.
- [ ] **Step 4: Run core + pure, the three QGIS files, lint and types.** Then the coordinator runs the full QGIS tier.
- [ ] **Step 5: Commit** (`feat(plugin): GPS lines in the Survey panel, Set destagger…, guide (#134)`) and push.

---

### Checkpoint C2 (coordinator): build and walkthrough

- [ ] Deploy to a **new** QGIS profile, `ns_geo_gps` (a copy of `ns_geo`, symlinked to this worktree, via `dev_link.py --profile ns_geo_gps`). Check that it loads headless.
- [ ] Publish a walkthrough Artifact with a `db` collection, `checks`. The author runs it on their own copy of the real data:
  - **G1** Import all 60 lines of the first survey into a new site with no grid. Every line is drawn along its walk. The zigzag's turn-arounds are visible, and the coordinates note says which CRS was picked.
  - **G2** `FILE__011` is drawn at about 30 m, where the wheel says 26 m.
  - **G3** `FILE__016` and `FILE__028` stretch across their obstacle lifts, at the user marks.
  - **G4** Import the second survey's `FILE__039` and `FILE__042`. The messages name their stretches without RTK, and `rtk_gaps` draws them.
  - **G5** Open a GPS line. Its profile reads in distance walked. Hover follows the map, and a pick sits on the track.
  - **G6** Set destagger 0.24 on the first survey's lines. The rows say so, the map moves, and picks follow.
  - **G7** Save, close and reopen. Everything is where it was. Repeat with one DZG renamed away.
  - **G8** Add a grid to the GPS-only site. Its CRS is the site's.
  - **G9** The tape import on a file with a DZG still places by the tapes.
  - **G10** The Survey panel rows and menus read well. This settles C1's open points.
- [ ] Fold the results in. Fix rounds follow the usual review loop. Merging asks the author first ([[build-and-walkthrough-before-merge]]).
- [ ] At the PR: comment on #134 with what M17a delivered. Move the README roadmap row (M17a to Done, "next release"). Then write the M17b plan.
