# nsgeo QGIS plugin (Plans 2 and 3, M4–M9) — design

**Date:** 2026-09-10
**Status:** Approved design, pending implementation plans
**Extends:** `2026-09-10-nsgeo-gpr-qgis-design.md` (the v1 design). That document stays
binding. This one refines §7–§13 for the plugin now that the core's API exists, and records
every place it deviates (see §12).

## 1. What this covers

Plan 1 delivered the core: a numpy-only library that reads DZT files, models a
georeferenced survey, and applies user-ordered processing steps. Nothing has a screen yet.

This design covers everything with a screen, plus the core additions the screen needs:

- a parameter-schema declaration per processing step, resolving the recorded spec §7 deviation;
- three numpy-only core modules the plugin consumes (`render`, `velocity`, `io.dzx`);
- the plugin package `packages/nsgeo-qgis/` with its docks, dialogs, viewer, map tools,
  GeoPackage layers, and headless test harness;
- the map↔profile link and anomaly picking;
- distribution as a dev symlink and a release zip.

It is implemented as two plans from this one spec: **Plan 2 (M4–M6)** ends with real data on
screen and processable; **Plan 3 (M7–M9)** ends with the map link, picking, and a release zip.

## 2. Decisions made in brainstorming

Each of these was a question with alternatives; the chosen answer and the reason are recorded so
nobody reopens them by accident.

| Decision | Chosen | Why |
|---|---|---|
| Plugin verification | Headless offscreen QGIS tests plus manual click-through at each milestone boundary | Offscreen `QgsApplication` starts in ~1 s from the system Python; subagents can verify their own widgets; the user is the tester at milestones, not for every task |
| `bandpass` initial values | Required fields, blank, header facts (antenna, Nyquist) shown as read-only reference | A default passband silently filters real data; a suggestion parsed from the antenna name is still an invented number |
| Qt compatibility | Qt5 and Qt6 compatible source; `qgisMinimumVersion=3.40`; `supportsQt6=True` | Costs a habit (`qgis.PyQt` imports, scoped enums), saves a whole-tree port later |
| Where vector outputs live | One GeoPackage per site with several tables | One file travels with the site; QGIS-native; a colleague without the plugin still sees lines and picks |
| Velocity | A layered `VelocityModel`, stored per grid with an optional per-line override; v1 UI exposes the constant case | Grids are the unit of completed fieldwork and conditions change between them; the list shape means adding layers later needs no schema migration |
| Display logic location | Thick core, thin plugin: normalisers, colormaps, decimation, and velocity live in the MIT core | Numpy math with no Qt in it; a future standalone GUI needs it verbatim; in the GPL plugin it could not be lifted into an MIT front end |
| Profile viewer widget | Custom `QWidget` with `paintEvent` and a pure `ViewTransform`, not `QGraphicsView` | Measured: pan/zoom frames 3.1 ms at any zoom on a 512 × 6301 radargram; one pure transform is what the map link and picking test against |
| Import direction default | Alternate (zigzag), first line +1 | Cart surveys are zigzag by default; the table fixes exceptions |
| Line label default | File stem (`FILE__001`) | Provenance, not geometry; equals the DZX name in real data |
| Gain-curve editor | Vertical strip beside the profile image sharing its time axis, shown while a `gain_curve` step is selected | Control points are in absolute two-way time; sharing the drawn axis is the safest alignment |
| Display-gain controls | Profile viewer toolbar, away from the processing dock | They change colour mapping, not data, and are never recorded in the stack; the placement makes the distinction visible |
| Picking interaction | Pick tool toggle on the toolbar, plus Shift+click when the tool is off | A visible mode for deliberate picking sessions; a shortcut so a single pick never needs a mode change |
| "Site" vocabulary | The unit is a *site*; "project" means the QGIS project file only | Two meanings of one word in one UI is how people lose files |

## 3. Core additions

All four modules are numpy-only and covered by the existing boundary test. All run on the
existing CI matrix with no QGIS present.

### 3.1 Parameter schema

`nsgeo/processing/base.py` gains:

```python
REQUIRED: Final = _Required()          # sentinel with repr "REQUIRED"

@dataclass(frozen=True)
class ParamSpec:
    name: str                          # keyword accepted by the step's __init__
    kind: str                          # "float" | "int" | "choice" | "curve"
    label: str                         # human label for the widget
    default: Any                       # a value, or REQUIRED
    unit: str | None = None            # "ns", "MHz", "traces", "dB"
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()      # kind == "choice" only
    help: str = ""

class Step(Protocol):
    name: str
    @property
    def params(self) -> dict[str, Any]: ...
    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]: ...
    def apply(self, rg: Radargram) -> Radargram: ...
```

Rules, each pinned by a registry-wide test:

- Every registered step implements `schema()`; the spec names equal the keys of `params` on a
  constructed instance, in order.
- Every parameter whose default is not `REQUIRED` builds a step from defaults alone via
  `build_step(name, **{s.name: s.default ...})`.
- `REQUIRED` appears only where a default would be an invented number: `bandpass.low_mhz`,
  `bandpass.high_mhz`, and `gain_curve.points`. For `kind == "curve"` the front end seeds an
  identity curve (two points at 0 dB spanning the current radargram's time axis); that is the
  identity, so it is not a guess.
- Bounds and choices are declared where the step already validates them: `time_zero.mode`
  ∈ {first_break, sample}, `time_zero.threshold` ∈ [0, 1], `gain_parametric.mode`
  ∈ {exponential, power}, `dewow.window_ns` > 0, `background_sliding.window_traces` ≥ 1,
  `background_svd.n_components` ≥ 0, `bandpass.taper_frac` ≥ 0. Nyquist is not a schema bound
  because it depends on the radargram; `apply()` keeps checking it and the form shows it.
- Constructors are unchanged, so existing stacks and JSON keep loading.
- `GainCurve.__init__` now raises `ValueError` for fewer than two points or non-finite values,
  so an invalid curve can no longer be serialised. `load_site` wraps a step `ValueError` from
  `StepStack.from_dicts` into a `ProjectError` naming the line.

No plugin code names a step. The parameter form is one generic widget driven by `schema()`;
the only special case is on `kind`.

### 3.2 `nsgeo.render`

```python
class Normalizer(Protocol):
    def limit(self, data: np.ndarray) -> float      # symmetric ±limit about zero

@dataclass(frozen=True)
class PercentileClip:                                # v1 implementation
    percentile: float = 99.0
    max_samples: int = 200_000                       # strided subsample above this

def colormap(name: str) -> np.ndarray               # (256, 3) uint8 LUT
def colormap_names() -> list[str]                    # "grey_black_high" (default), "grey_white_high", "seismic"
def to_index8(data, limit) -> np.ndarray             # uint8 (H, W): clip((data/limit + 1) * 127.5)
def to_rgb8(data, limit, lut) -> np.ndarray          # uint8 (H, W, 3), C-contiguous
def decimate_columns(data, max_width) -> np.ndarray  # block-mean along traces when n_traces > max_width
```

Zero maps to index 127/128 (mid-grey), strong negative to white, strong positive to black in
the default map, following GPR convention and spec §8. Decimation happens after processing and
only when a line is wider than the cache budget (§5.4); the spike showed that scaling a cached
full-resolution image is the fast path for lines of ordinary length.

Measured on the ten real files stitched into one 512 × 6301 radargram: full normalise plus LUT
120 ms with a full percentile, 1.2 ms to build the `QImage`, 3.1 ms per pan/zoom frame at any
zoom, 15.9 ms with smooth interpolation. A single real line (≈650 traces) normalises in
≈12 ms. The strided-subsample percentile is what keeps display-gain dragging interactive on
long lines, and the plan pins it with a test.

### 3.3 `nsgeo.velocity`

```python
@dataclass(frozen=True)
class VelocityModel:
    layers: tuple[tuple[float, float], ...]      # (top_ns, v_m_per_ns), sorted, first top_ns == 0.0

    @classmethod
    def constant(cls, v_m_per_ns: float) -> VelocityModel
    @classmethod
    def from_dielectric(cls, epsr: float) -> VelocityModel     # 0.299792458 / sqrt(epsr)
    def depth_at(self, times_ns: np.ndarray) -> np.ndarray     # cumulative ∫ v/2 dt; negative above t = 0
    def velocity_at(self, times_ns: np.ndarray) -> np.ndarray
    def to_dict(self) / from_dict(doc)

def resolve_velocity(line: Line, grid: Grid | None) -> VelocityModel
```

Boundaries are in two-way time because that is what is visible on a radargram; depth is the
derived quantity. Depth is measured from time zero, so before a `time_zero` step a real
SIR-4000 file (position −11.09 ns) shows a negative depth at the top. That is correct and is
pinned by a test.

Resolution order: `line.velocity`, then `grid.velocity`, then
`VelocityModel.from_dielectric(line.header.epsr)`. The header-derived value is a suggestion the
UI displays; it is never written into the JSON silently.

Model changes: `Grid.velocity: VelocityModel | None = None` and
`Line.velocity: VelocityModel | None = None` (`Line.open` gains a `velocity=None` kwarg). `None`
means "unset", not a default number, which is why the core needs no invented constant. The JSON
gains `"velocity": {"layers": [{"top_ns": 0.0, "v_m_ns": 0.080}]}` on grids and optionally on
lines. Schema version stays 1: a file without velocities loads, resolves to header
suggestions, and is upgraded on the next save. The grid dialog always stores a value, so sites
made through the plugin never rely on the fallback.

### 3.4 `nsgeo.io.dzx`

```python
@dataclass(frozen=True)
class DzxMark:  scan: int; kind: str; name: str
@dataclass(frozen=True)
class DzxInfo:  name: str | None; scan_range: tuple[int, int] | None; dielectric: float | None
                system: str | None; marks: tuple[DzxMark, ...]

def read_dzx(path: Path) -> DzxInfo | None     # path may be the .DZT or the .DZX; sibling lookup is case-insensitive
```

Parsed namespace-agnostically (the real files declare `www.geophysical.com/DZX/1.02`). The
`Macro/Process` binary blobs are ignored. Import uses the result for the label default, the
dielectric suggestion, the sidecar column, and the marks layer. Nothing from a DZX is
geometric truth. Verified on the nine real sidecars: `FILE__007.DZX` carries one user mark at
scan 634 of 635 traces.

### 3.5 Exports

`nsgeo/__init__.py` continues to export only `__version__`. Plan 3's final task promotes the
names the plugin actually imported, once the list is known rather than guessed.

## 4. Plugin architecture

```
packages/nsgeo-qgis/
├── nsgeo_qgis/
│   ├── __init__.py          # classFactory + core path shim
│   ├── metadata.txt         # name, version (single source), qgisMinimumVersion=3.40, supportsQt6=True
│   ├── plugin.py            # Plugin: builds docks, toolbar, map tools; tears down cleanly
│   ├── session.py           # SiteSession: the one place survey state lives
│   ├── layers.py            # GeoPackage tables via the loaded layer's provider
│   ├── lookup.py            # Qt-free: nearest trace, import planning, polygon corners
│   ├── render/qimage.py     # RGB byte array -> QImage, and nothing else
│   ├── ui/
│   │   ├── survey_dock.py   # tree
│   │   ├── processing_dock.py, param_form.py, gain_strip.py
│   │   ├── profile_dock.py, profile_view.py, view_transform.py (Qt-free)
│   │   ├── import_dialog.py, grid_dialog.py, add_step_dialog.py
│   └── maptools/
│       ├── trace_tool.py    # hover-to-trace, click-to-open
│       └── digitise_tool.py # two clicks: origin, then a point along +Y
├── tests/
│   ├── pure/                # no qgis import; runs on the normal CI matrix
│   └── qgis/                # needs qgis; offscreen QgsApplication fixture; skips elsewhere
└── scripts/
    ├── build_zip.py
    └── dev_link.py          # symlink nsgeo_qgis/ into the QGIS profile plugins dir
```

### 4.1 Core path shim

`__init__.py` looks for `_vendor/nsgeo` first (the release zip provides it). When absent, it
resolves its own real path through the dev symlink and adds the sibling
`packages/nsgeo-core/src` to `sys.path`. If neither location holds a `nsgeo` package the plugin
refuses to load with a message naming both places it looked. No `pip install` into the QGIS
interpreter is required in either mode.

### 4.2 `SiteSession`

A `QObject` owning: the `Site`, its JSON path, its GeoPackage path, the per-line `StepStack`
(seeded from `Site.stacks` by the relative POSIX key from `project._line_key`), the current
line key, the current trace index, the current selection, and a dirty flag.

Signals: `site_opened`, `site_closed`, `dirty_changed`, `grids_changed`, `lines_changed`,
`line_opened(key)`, `line_loaded(key)`, `trace_changed(key, index)`,
`selection_changed(key, start, end)` (or cleared), `stack_changed(key)`, `picks_changed`.
Every signal fires only when a value actually changed, which is the loop guard for the map
link.

Widgets read from the session and never hold survey state. Display settings (clip percentile,
colormap, zoom) belong to the viewer, not the session, because they are not survey state.

**Stack mutation rule.** The only stack-editing methods are on the session:
`append_step`, `insert_step`, `replace_step(i, build_step(name, **params))`, `remove_step`,
`move_step`, `set_step_enabled`, `apply_stack_to_grid(grid_id)`. Each emits `stack_changed`.
Nothing else touches a `StepStack`, which keeps the core's no-in-place-mutation rule true.

Save is explicit (`save_site`), with a dirty flag and a prompt on plugin unload or QGIS project
close. Importing a file outside the site folder offers "reference by absolute path" with a
warning, mapping to `allow_absolute=True`, or cancel.

### 4.3 `layers.py` and the site GeoPackage

`<name>.nsgeo.gpkg` sits beside `survey.nsgeo.json`. Tables:

| table | geometry | kind | fields |
|---|---|---|---|
| `grids` | polygon | derived, read-only | grid_id, azimuth, size_x, size_y, default_spacing, velocity_json |
| `lines` | linestring | derived, read-only | line_key, grid_id, label, axis, offset_m, start_along_m, direction, n_traces, length_m, antenna, file_name |
| `marks` | point | derived, read-only | line_key, scan, kind, name |
| `picks` | point | **authored, editable** | line_key, trace, distance_m, time_ns, depth_m, velocity_m_ns, stack_json, note, created |

Three rules keep a file that mixes derived and authored tables safe:

1. **Regenerate per table, never per file.** Rebuilding `lines` truncates and refills that
   table. The file is never deleted or replaced, so picks survive and Windows file locks never
   bite.
2. **All writes go through the loaded QGIS layer's data provider.** Never a second OGR handle
   on a GeoPackage QGIS already has open.
3. **Derived layers are read-only in QGIS** (`setReadOnly(True)`). The JSON is the source of
   truth for geometry.

Layers are added to the project in a group named for the site, styled with a categorised
renderer on `grid_id` for lines and a dashed outline for grids. The current line is shown with
a highlight rubber band, never by editing the renderer.

The GeoPackage CRS is the CRS of the first grid in the site. Other grids are transformed into
it on write. Canvas display goes through QGIS's normal transform.

GeoPackage rasters are 8-bit tiles, so future float timeslices will be GeoTIFFs beside the
package rather than inside it. Vector layers all fit.

### 4.4 `lookup.py` (Qt-free)

- `nearest_trace(coords_by_key, xy, tolerance) -> (key, index, distance) | None`: numpy over
  per-line coordinate arrays in the canvas CRS, precomputed once per line when the layer is
  built or the canvas CRS changes. Ten lines are ≈6300 points; no spatial index.
- `plan_import(files, options) -> list[ImportRow]` and `recompute_offsets(rows)`: the
  vendor-neutral placement guess. Sort by the trailing integer in the file stem (GSSI
  `FILE__001`, MALA `DAT_0001`, Sensors & Software `LINE01` all number this way), fall back to
  name order; offsets are index × spacing over *included* rows, skipping rows whose offset was
  hand-edited; direction alternates, or is all +1 / all −1.
- `corners_from_polygon(vertices, origin_index, plus_y_index) -> (local, world)`: turns a
  selected rectangle feature into the four control points the corner fit consumes.

### 4.5 Plugin boundary test

An AST test over `nsgeo_qgis` fails the build on any direct `PyQt5`/`PyQt6` import (everything
goes through `qgis.PyQt`) and on any import from `nsgeo.processing` other than `StepStack`,
`build_step`, `available_steps`, `get_step`, `Radargram`, `ParamSpec`, and `REQUIRED`. That is
what "no signal processing in the plugin" means mechanically.

### 4.6 Threading

`LoadLineTask(QgsTask)`: `run()` calls `Line.load()`; `finished()` hands the profiles to the
session on the main thread, which sets `StepStack.source = Radargram.from_profile(...)`. The
viewer draws header-derived axes and a loading state immediately. Header reads stay on the main
thread (1 KB each).

Processing runs on the main thread in v1. Every step is milliseconds on a single line except
SVD, about a second on a long line. This is a documented limit: `StepStack`'s cache is not
thread-safe, and a background stack needs its own design.

Multi-channel files get a channel selector in the viewer toolbar, visible only when the header
reports more than one channel. Channel 0 is the default. Stacks apply per line, matching how
the core keys them.

### 4.7 Errors

Core exceptions (`DztError`, `ProjectError`, step `ValueError`s) surface in the QGIS message
bar with the core's message text, never as a traceback dialog. Parameter forms validate at
commit by building the step and catching `ValueError`; the message appears beside the field
and the value never enters the stack. A site with missing referenced files fails to open with
the list of missing paths; relocation is a later feature. A line whose header reports
`traces_per_metre <= 0` is shown in the import table as "time-triggered: cannot be
grid-placed" and unchecked, not raised.

## 5. UI

The approved mock lives in the brainstorming artifact (`.lavish/plan2-section3-ui.html`,
untracked) and was built from the real FILE__001 radargram and the real file list. This
section is its normative summary.

### 5.1 Arrangement

Three `QDockWidget`s around the QGIS canvas plus a fourth along the bottom. All are movable,
floatable, and closable; the arrangement is a default. The plugin toolbar sits with QGIS's:
New site, Open, Save · Add grid…, Import DZT… · Trace tool, Pick · Panels.

```
┌──────────────┬────────────────────────────────┬──────────────┐
│ nsgeo Survey │        QGIS map canvas         │ nsgeo        │
│  Site        │   grids, lines, marks, picks   │ Processing   │
│   └ Grid A   │   over the project's layers    │  stack       │
│      ├ FILE… │   ▲ trace cursor               │  param form  │
├──────────────┴────────────────────────────────┴──────────────┤
│ nsgeo Profile · FILE__001 · line 0 · Grid A                  │
│ [display gain][colormap][difference][fit][1:1][v = …]        │
│  time ns │ radargram image  │ gain strip (when selected) │ depth m │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 Survey dock

A tree: site → grids → lines, plus lines with no grid at the site level (future GPS
transects). Line rows show label, offset, direction glyph, a loading spinner while a
`LoadLineTask` runs, and a velocity override marker when set. Status bar: JSON file name and
the dirty flag.

Context menus. Grid: Edit grid…, Import DZT…, Apply current stack to grid…, Set velocity…,
Remove grid (only when empty). Line: Open, Edit placement…, Set velocity override…, Remove
line from site. Removing a line deletes its stack entry and its `lines` feature and leaves its
picks in place; they keep their `line_key` and are not silently deleted.

### 5.3 Processing dock

Add step ▾ (menu built from `available_steps()`, alphabetical, "needs values" tag on steps
with `REQUIRED` parameters), Remove, ↑, ↓; the stack list with an enable checkbox, name, a
difference-view eye toggle (disabled with a tooltip for steps that change the sample count),
and a drag handle; a hint on a `gain_curve` that is not last ("drag is slower"); the
parameter form for the selected step; Apply to grid…; Presets ▾ (named stacks saved in the
JSON).

The parameter form is generated from `schema()`: `float` → double spin box with bounds and
unit, `int` → spin box, `choice` → combo box, `curve` → the gain strip in the profile dock.
Edits commit on Enter or focus-out and go through `session.replace_step`.

**Adding a step with `REQUIRED` parameters** opens the same form as a modal before anything
enters the stack. Required fields are blank and highlighted; a read-only panel shows the current
file's header facts (antenna, sample interval, Nyquist, sample count); OK is disabled until the
core's own validation passes. Steps whose schema has defaults for every parameter append
directly.

### 5.4 Profile dock

Toolbar: display gain (clip percentile slider), colormap combo, difference-view indicator
naming the step, Fit, 1:1, channel selector when relevant, and the resolved velocity with its
source ("v = 0.080 m/ns (Grid A)").

Viewer: `ProfileView(QWidget)` with `paintEvent`. Left axis two-way time in ns, bottom axis
distance along the line in m with the direction glyph, right axis depth in m sampled from the
resolved `VelocityModel` at each tick (so a layered model bends the axis with no viewer
change). Vertical cursor with a readout (trace, distance, time, depth). Drag-selection band.
Pick markers. Wheel zooms about the cursor, middle-drag pans, Fit and 1:1 reset.

`ViewTransform` (Qt-free) maps trace index and two-way time to widget pixels and back given
the visible trace range, time range, and widget size. Axes, cursor, selection, picking, and
the gain strip all go through it.

Gain strip: a vertical panel beside the image sharing the time mapping, visible while a
`gain_curve` step is selected; drag points, the image updates; Enter commits through
`replace_step`.

Cache: one full-resolution RGB `QImage` per (stack result, display settings), rebuilt on
`stack_changed` or a display change; pan and zoom draw a sub-rectangle of it. Lines wider than
8192 traces are decimated to that width at fit zoom and re-rendered at full resolution when
zoomed past 1:1.

### 5.5 Import dialog

Fields: target grid, axis the lines run along, spacing across the other axis (seeded from the
grid's `default_spacing`), first offset, start along, direction mode (alternate / all +1 /
all −1), label source (file stem / line number).

Table columns: Include ☐, File, Label, Offset, Dir, Start, Traces, Length, Sidecar, Note.
Editable: Include, Label, Offset, Dir, Start. Read-only: Traces and Length from the header;
Sidecar from the DZX (dielectric, mark count). Rows drag to reorder; Remove selected. Excluding
a redone line (6, 6a, 6b) pulls following files into its offset slot unless their offsets were
hand-edited. A line longer than the grid gets a warning note, not an error: the outline comes
from `size_x`/`size_y`, the line from its trace count. Time-triggered files are unchecked with a
note.

### 5.6 Grid dialog

Three tabs feed the same fields: **GNSS corners** (table of local x/y and world E/N, "From
point layer…", Fit → `fit_grid_from_corners`, residual RMS shown as a QC number),
**Digitise on map** (two-click tool: origin, then a point along +Y; then enter sizes),
**From polygon** (layer and feature pickers, which corner is the origin, which neighbour is
+Y → `corners_from_polygon`). Common fields: id, CRS, origin E/N, azimuth, size X/Y, default
spacing, velocity (constant case; seeded from the header dielectric, shown as "from ε 14.0").

## 6. Map ↔ profile link and picking

- **`MapLink`** (a `QObject`) owns a `QgsVertexMarker` for the trace cursor and a
  `QgsRubberBand` for the selected segment. It listens to `trace_changed` and
  `selection_changed`. The world coordinate of a trace is `Line.trace_coords(frames)[index]`
  transformed to the canvas CRS.
- **Trace tool** (`QgsMapTool`): on move, `nearest_trace` within tolerance; if it is the current
  line, `session.set_trace`; if another line, highlight it. On click, open that line and set the
  trace. Clicking a pick feature jumps to its line and trace.
- **From the profile:** mouse move → `session.set_trace`; drag → `session.set_selection`; the
  marker and band follow.
- **Picking:** with the Pick tool on, or Shift+click otherwise, a click in the profile becomes
  `session.add_pick(key, trace, time_ns)`. The feature carries line key, trace index, distance
  along, two-way time, depth from the resolved velocity, the velocity used, the stack as JSON,
  an empty note, and a timestamp. Time is the truth; depth and velocity are conveniences that can
  be recomputed.
- **Loop guard:** the session emits only on real change, so a marker update that round-trips to
  the same trace is a no-op.

## 7. Persistence

`survey.nsgeo.json` remains the source of truth (schema version 1, extended compatibly):

```json
{
  "schema_version": 1,
  "grids": [{ "id": "A", "origin": [...], "azimuth": 12.4, "size_x": 5.0, "size_y": 11.0,
              "crs": "EPSG:32616", "default_spacing": 0.5,
              "velocity": { "layers": [ { "top_ns": 0.0, "v_m_ns": 0.080 } ] } }],
  "lines": [{ "path": "raw/FILE__001.DZT", "placement": { ... },
              "velocity": { ... },              // optional override
              "stack": [ { "step": "dewow", "params": { "window_ns": 4.0 }, "enabled": true } ] }],
  "presets": { "campus-default": [ ...stack dicts... ] }
}
```

`presets` is new and optional. The GeoPackage is derived except for `picks` (§4.3).

## 8. Testing and CI

Three tiers:

| tier | where it runs | what it proves |
|---|---|---|
| Core | full OS × Python matrix, as now, plus the schema, render, velocity, DZX suites | numpy behaviour, registry rules, JSON compatibility |
| Plugin pure (`tests/pure`) | same matrix job; plugin dir on the path; no `qgis` import | `lookup`, `ViewTransform`, import planning, polygon corners, feature dicts |
| Plugin QGIS (`tests/qgis`) | locally via `.venv-qgis`; in CI one ubuntu job on the `qgis/qgis` image with `QT_QPA_PLATFORM=offscreen`; skips where `qgis` is unimportable | plugin loads through `classFactory` against a fake `iface`; every dock constructs; a real DZT renders to a `QImage` of the expected size; a site round-trips through the GeoPackage; a synthetic map hover moves the profile cursor to the trace the pure lookup predicts |

`.venv-qgis` is created with `python3 -m venv --system-site-packages .venv-qgis` from
`/usr/bin/python3` (the interpreter QGIS uses) and gets `pytest` installed. Real DZT files are
symlinked from the main checkout's local data directory and tests skip when absent, as the core
does.

Each milestone ends with a manual click-through script in the plan: what to open, what to
click, what should be visible. That is the "by hand" part of spec §11, and it belongs to the
user, not a subagent.

Ruff covers both packages. Mypy covers the core and the plugin's Qt-free modules; widget
modules are excluded because the `qgis.PyQt` shim defeats stubs. Real-data validation is
primary: any plugin test that can run on a real file does, and synthetic fixtures only prove
self-consistency.

## 9. Distribution

**Development:** `scripts/dev_link.py` creates the symlink into the active QGIS profile's
`python/plugins/` and prints where it went. The shim (§4.1) finds the sibling core source. Edit
core or plugin, use Plugin Reloader, see the change.

**Release:** `scripts/build_zip.py` copies `nsgeo_qgis/` (excluding tests and caches), vendors
`packages/nsgeo-core/src/nsgeo` into `nsgeo_qgis/_vendor/nsgeo`, records the core version and
git SHA in `_vendor/VERSION`, reads the plugin version from `metadata.txt` (the single source),
and writes `dist/nsgeo_qgis-<version>.zip`. It refuses to run on a dirty tree or with failing
core tests unless told otherwise with explicit flags for CI, where those have already been
checked. CI builds the zip on every push and attaches it to tagged releases.

## 10. Milestones and plan split

| | Milestone | Plan | Ends with |
|---|---|---|---|
| M4 | Schema fix; `render`, `velocity`, `io.dzx`; plugin skeleton and shim; survey dock with new/open/save; grid dialog; import dialog; GeoPackage layers on the map | 2 | Lines on the map from real files |
| M5 | Profile dock: render, pan/zoom, axes, display gain, loading state, channel selector | 2 | First sight of real data |
| M6 | Processing dock: stack list, generated forms, add-step modal, gain strip, difference view, apply-to-grid, presets | 2 | Real data processable |
| M7 | Trace tool, `MapLink`, selection band, click-to-open | 3 | The differentiator |
| M8 | Pick tool, picks layer, marks layer | 3 | An interpretation tool |
| M9 | `build_zip.py`, `dev_link.py`, CI zip job, docs, first release; promote core exports | 3 | Usable by other people |

Plan 2 is written first and executed before Plan 3 is written, so Plan 3 reflects what the
viewer and session actually became.

## 11. Out of scope for these plans

Timeslices, migration, velocity analysis, the layered-velocity editor (the model supports it;
the UI exposes the constant case), `TrackPlacement` and the DZG reader, the `.gpr` reader,
background processing of stacks, relocating missing files, a target-layer picker for picks,
writing processed data to disk, and any instrument other than GPR.

## 12. Deviations from the v1 spec, recorded

- **§8 rendering widget.** Custom `QWidget` with `paintEvent` instead of `QGraphicsView`.
  Justified by measurement (§3.2) and by the pure `ViewTransform` the map link tests against.
- **§3 core layers.** `render`, `velocity`, and `io.dzx` join `io`, `model`, `geometry`,
  `processing`. All numpy-only; the boundary test covers them.
- **§10 line layer.** One GeoPackage per site with derived and authored tables, under the three
  rules in §4.3, rather than a GeoPackage of line geometries alone.
- **§6 model.** `Grid.velocity` and `Line.velocity` added as optional `VelocityModel`s.
- **§11 plugin testing.** Headless offscreen QGIS tests added; "widget behaviour tested by
  hand" kept for milestone click-throughs. Still no `pytest-qt`.
- **§7 `Step.params`.** Resolved by `schema()` per step, with `REQUIRED` for the two
  non-default-constructible steps, exactly as the follow-ups asked.
- **§12 dev install.** Path shim in `__init__.py` instead of `pip install -e` into the QGIS
  interpreter, which is PEP 668 externally managed on Ubuntu.
