# nsgeo — GPR core library and QGIS plugin (v1 design)

**Date:** 2026-09-10
**Status:** Approved design, pending implementation plan

## 1. Context and goals

The long-term goal is a cross-platform toolstack for near-surface geophysical
survey processing, analysis, and visualisation, covering GPR, magnetometry,
conductivity, and resistivity, usable by anyone.

The stack is a mostly-independent set of tools with thin front-end layers: a
QGIS plugin first, possibly a standalone GUI later.

v1 is deliberately narrow: load GSSI DZT files, organise them into sites and
grids, view profiles, and apply user-controlled processing including background
removal. The primary user is an archaeologist working on gridded survey blocks,
but nothing in the design is archaeology-specific.

### The differentiator

Map-driven navigation. The user reports it is missing from most GPR software:
the ability to click a line on a map, see its profile, move the cursor in the
profile and watch a marker track along the line on the map, and see it all
against the other spatial data already in a QGIS project (excavation plans,
imagery, GNSS-recorded surface features, other geophysics).

## 2. Scope

### In scope for v1

- GSSI DZT reader, single- and multi-channel
- Site / Grid / Line / Profile data model with pluggable placement
- Grid georeferencing from GNSS corners, on-map digitising, or existing polygons
- User-ordered processing step stack: time-zero, dewow, three gain steps,
  bandpass, and three background-removal methods
- Profile viewer with pan/zoom, axes, and real-time display gain
- Bidirectional map to profile cursor synchronisation
- Anomaly picking from the profile into a QGIS point layer
- Human-readable survey definition file
- Plugin zip build and first public release

### Out of scope for v1

- Timeslices and amplitude maps (designed for, not built)
- Migration and velocity analysis
- Instruments other than GPR
- Writing processed data back to disk
- GPS-tracked transects (the model accommodates them; the DZG reader is not
  built in v1)
- Standalone GUI

## 3. Architecture

Two packages in one repository, with a hard boundary between them.

`nsgeo` (core) contains no `qgis` or `PyQt` import anywhere. `nsgeo_qgis`
(plugin) contains no signal processing anywhere. The boundary is what makes the
core testable headless, reusable by other front ends, and extensible to other
instruments without touching UI code.

Rejected alternatives:

- **Plugin-first, extract a library later.** Faster to first light, but QGIS
  types leak into geometry and I/O code, every test needs a QGIS runtime, and
  the extraction cost lands exactly when the second instrument is added.
- **Core library plus standalone viewer first.** Cleanest core, but defers the
  one feature that motivates the project.
- **Two separate repositories.** Rejected for now, not on principle. The core's
  API does not exist yet and will churn through M4 to M7; every discovery that
  the plugin needs something the core does not expose would become two pull
  requests and a version bump, at exactly the stage with the most such
  discoveries. The plugin also vendors the core's *source tree* into its zip,
  which is trivial in one repo and needs a submodule or a CI download step
  across two. Neither distribution target cares: plugins.qgis.org takes an
  uploaded zip, and PyPI publishes fine from a subdirectory.

  The genuine argument for splitting is that separate repositories make
  cross-boundary imports physically impossible rather than merely disciplined.
  That is better served by a boundary test (see section 11), which additionally
  catches scipy becoming a hard dependency and matplotlib appearing at all —
  neither of which a repository split would catch.

  Split when one of these becomes true, not before: outside contributors arrive
  for one side and the other's CI noise obstructs them; release cadences
  genuinely diverge; or a second front end makes the plugin one consumer among
  several. Extraction stays cheap because `git subtree split` preserves history
  and the core has no dependency on the plugin, so it only has to go one way.

### Dependencies

The core requires **numpy and nothing else**. scipy is an optional accelerator:
detected at import, used when present, with a numpy fallback and tests
asserting both paths agree within tolerance. matplotlib is not used at all.

This constraint exists because QGIS ships its own Python interpreter, and users
on Windows and macOS generally cannot pip-install into it. A numpy-only core can
be vendored into the plugin zip safely. numpy is always present in QGIS because
QGIS's own raster code uses it; scipy and matplotlib vary by installer
(OSGeo4W vs standalone vs distribution packages vs flatpak) and across releases.

Everything v1 needs is achievable in numpy:

| Step | numpy implementation |
|---|---|
| Time-zero | slice plus first-break pick (threshold or argmax on abs amplitude) |
| Dewow | running-mean subtraction along the time axis via `cumsum` |
| Gain (AGC) | `cumsum`-based running RMS |
| Background removal, mean | `arr - arr.mean(axis=1, keepdims=True)` |
| Background removal, sliding | `cumsum` running mean |
| Background removal, SVD | `numpy.linalg.svd`, drop leading eigenimages |
| Bandpass | `numpy.fft.rfft`, cosine-tapered passband, `irfft` |

Bandpass requires care: the passband edges must be cosine-tapered rather than
applied as a brick wall, because brick-wall filtering causes ringing that can be
mistaken for stratigraphy.

Known future costs of excluding scipy: 2-D median despiking (workable with
`sliding_window_view` plus `np.median`, slower), and scattered-data
interpolation for timeslices (mitigated by GDAL, always present in QGIS, whose
`gdal_grid` provides IDW/nearest/linear/average; and by the fact that 0.5 m line
spacing is near-gridded, making binned averaging in numpy defensible).

## 4. Repository layout

```
nsgeo/
├── packages/
│   ├── nsgeo-core/                  # MIT
│   │   ├── pyproject.toml
│   │   ├── src/nsgeo/
│   │   │   ├── io/dzt.py
│   │   │   ├── model/
│   │   │   ├── geometry/grid.py
│   │   │   ├── processing/
│   │   │   └── project.py
│   │   └── tests/
│   │       └── data/
│   │           ├── local/           # gitignored: real survey files
│   │           └── fixtures/        # committed: synthetic and scrubbed
│   └── nsgeo-qgis/                  # GPL-2.0-or-later
│       ├── nsgeo_qgis/
│       │   ├── __init__.py          # classFactory
│       │   ├── metadata.txt
│       │   ├── ui/
│       │   ├── render/
│       │   └── maptools/
│       └── scripts/build_zip.py
├── docs/
└── .github/workflows/ci.yml
```

## 5. Licensing

Core is **MIT**. Plugin is **GPL-2.0-or-later**, as QGIS requires.

Apache-2.0 was considered and rejected for the core: it is regarded as
incompatible with GPL-2 due to its patent-termination clause, which would force
the plugin to GPL-3-or-later and remove QGIS's GPL-2 option. MIT is compatible
with both and imposes no friction on reuse, including commercial reuse.

The DZT reader is written from the format specification rather than adapted from
readgssi (GPL-3.0), which would make the core copyleft. GPRPy (MIT) may be
consulted freely as a reference. RGPR declares no licence and must not be used
as a source.

## 6. Core data model

```python
Profile   # one channel of one radargram
  data: np.ndarray          # (n_samples, n_traces), raw, never mutated
  header: DztHeader         # ns/sample, samples, traces/m, antenna freq, bits

Line      # one collected survey line
  path: Path
  channels: list[Profile]
  placement: Placement

Grid      # a coordinate frame, not a container
  id: str
  origin: tuple[float, float]  # world coords of grid-local (0, 0)
  azimuth: float               # degrees clockwise from CRS north to the
                               #   grid-local +Y axis
  size_x, size_y: float        # metres
  crs: str                     # authority string, e.g. "EPSG:32616"
  default_spacing: float       # import convenience ONLY, not geometric truth

Site
  grids: list[Grid]
  lines: list[Line]          # flat; GPS transects have no grid
```

### Placement

```python
class Placement(Protocol):
    def trace_coords(self, n_traces, header) -> np.ndarray:   # (n_traces, 2|3) world
    def distance_along(self, n_traces, header) -> np.ndarray: # (n_traces,) metres

GridPlacement(
    grid_id: str,
    axis: Literal["x", "y"],   # grid-local axis this line runs ALONG
    offset: float,             # metres along the OTHER axis. Geometric truth.
    start_along: float,        # along-axis coordinate of trace 0
    direction: int,            # +1 or -1
    label: str | None,         # e.g. "line 12" — provenance, never geometry
)
TrackPlacement(coords, trace_marks)   # v1.1, from DZG/NMEA
```

For a grid line:

```
distance_along[i] = start_along + direction * (i / traces_per_metre)
```

All consumers use only `trace_coords()` and `distance_along()` and never learn
which placement they received. Adding GPS support later is a new `Placement`
implementation plus a DZG parser, touching nothing else.

`distance_along` for a track is cumulative path length, not
`trace_index / traces_per_metre`: GPS lines curve, and time-triggered
acquisition makes the header's trace spacing meaningless.

### Key decisions

**Trace index is the join.** `Profile.data[:, i]` and
`placement.trace_coords(...)[i]` describe the same trace. This single shared
index is what makes bidirectional map to profile navigation work. Every channel
in a Line must have identical `n_traces`; a file violating this is corrupt and
must fail loudly at load.

**Ownership runs one way.** `Line` owns its `Profile` channels; `Profile` holds
no back-reference, keeping it a pure, picklable, trivially testable data object.

**Zigzag is handled in geometry, never by flipping arrays.** A line collected
against the axis keeps its traces in raw file order and carries `direction = -1`,
so `distance_along()` returns a decreasing coordinate. Flipping at read time
would silently desynchronise the data from the file.

**Line position is stored in metres, not as an index times a spacing.** The
grid does not own a single line direction or a single spacing, because real
acquisition does not work that way:

- **Cross-hatched grids.** Lines are run in one direction and then again
  perpendicular across the same block, for better coverage where noise is high
  or features are subtle. `axis` therefore belongs to the *placement*, not the
  grid: one grid holds lines along x and lines along y simultaneously. This also
  pays off later for timeslices, where two directions allow directional striping
  to be cancelled rather than merely tolerated.
- **Infill and irregular spacing.** Half-spacing infill lines over an anomaly
  are just another offset in metres; as an index they would need a fractional
  index or a second spacing.

`label` retains the field name ("line 12") for display and provenance, while
`offset` carries the geometry. Import computes `offset` from index times
`default_spacing` as a convenience, then discards the coupling.

**Lines need not span the grid.** `start_along` is the along-axis coordinate of
trace 0, which covers a line that starts inside the grid rather than at its
edge. A line that *stops* early — an obstruction, a parked car, a tree — needs
no field at all: it simply has fewer traces, and its drawn extent follows from
the trace count. A line interrupted and resumed past the obstruction is two
`Line` objects sharing an axis and offset with different `start_along` values,
which the model already expresses.

No `known_length` field is included. Correcting odometer drift against a known
line length is a real need, but it is a processing concern rather than a model
one, and adding the field before the correction exists would leave it unused
and unvalidated.

**Three georeferencing methods, one representation.** GNSS corners,
on-map digitising, and reading an existing polygon are three UI paths producing
the same four numbers: origin, azimuth, size_x, size_y. Corners are
least-squares fitted, which also yields a residual reported as a QC measure of
grid squareness.

**Lazy headers, on-demand samples.** A DZT header is a 1024-byte read, so
opening a site with 60 lines reads ~60 KB and populates the tree and map layer
immediately. Sample arrays load on demand into a bounded LRU cache.

## 6a. DZT format notes, verified against real files

Verified against ten SIR-4000 files (antenna `HS350US`, campus training run,
2024). These are empirical findings from real data, not readings of the spec,
and each one is a place a naive reader goes wrong:

- **`rh_tag` is 2047 (0x07FF), not the 255 (0x00FF) that most format
  descriptions cite.** The reader must accept the known tag values rather than
  asserting one.
- **Header size is `1024 * rh_data` when `rh_data < 1024`.** Here `rh_data` is
  128, giving a 131,072-byte header — far larger than the 1024-byte minimum
  header that a naive reader assumes. Assuming 1024 produced a non-integer trace
  count (671.5) in all ten files; the correct rule produces exact integers in all
  ten. **A non-integer trace count is the diagnostic**, and the reader should
  treat it as a hard error rather than truncating, because truncation would turn
  a wrong header size into plausible-looking but misaligned data.
- **`rh_bits` is 32, and samples are signed `int32` centred near zero**
  (means around -300 against a range of roughly +/-1.5e7). No zero-offset
  correction applies for this variant, despite `rh_zero` being 105, which is
  neither of the documented 0x80 / 0x8000 sentinels. `rh_zero` must not be
  trusted blindly.
- **Leading all-zero traces are normal** — recording starts before the cart
  moves. These are data, not corruption, and must not be silently trimmed.
- `rhf_spm` is 60 traces/m, giving line lengths of 10.1 to 11.1 m, consistent
  with the recorded survey.
- `.DZX` sidecars accompany the files and are not yet parsed. They are XML
  metadata and may carry marks and line information worth reading in v1.1.

### Other formats seen

`.gpr` files from a second instrument are present in the local data directory
for future reference. Structure so far: magic `GPR\x01`, a 16-byte file header,
then fixed 195-byte records, 8-bit samples; `(filesize - 16) % 195 == 0` holds
across all four samples. The originating instrument is not yet identified and no
reader is planned for v1.

## 7. Processing

Nothing runs automatically. Opening a profile shows raw data. The stack starts
empty. Every step is added by explicit user action.

```python
@dataclass(frozen=True)
class Radargram:
    data: np.ndarray
    dt_ns: float
    t0_ns: float

class Step(Protocol):
    name: str
    params: dict              # declared schema; the UI builds widgets from it
    def apply(self, rg: Radargram) -> Radargram: ...
```

Axis metadata travels with the data because time-zero correction crops rows. A
step that fails to update `t0_ns` desynchronises the depth axis, and returning a
whole `Radargram` makes that an obvious test failure rather than a silent bug.

### Stack semantics

Ordered, toggleable, with cached intermediates. Editing or reordering step *i*
invalidates cache entries *i* onward. Because steps are pure functions, that is
the entire invalidation rule.

Steps are registered, not hardcoded. The UI enumerates the registry and builds
parameter widgets from declared schemas, so new instruments contribute steps
without UI changes.

### v1 registry

`time_zero` (manual sample or first-break threshold), `dewow` (window in ns),
`gain_agc` (window in ns), `gain_parametric` (exponential or t^n),
`gain_curve` (draggable `(t_ns, gain_dB)` control points, linearly interpolated,
applied as `10^(dB/20)`), `bandpass` (low/high MHz plus taper fraction),
`background_mean`, `background_sliding` (window in traces),
`background_svd` (number of components removed).

Three separate gain steps rather than one with modes: different parameter
schemas, and more than one may legitimately be used at once.

### Interactivity

`gain_curve` dragging recomputes one broadcast multiply over a roughly
(512, 3000) array — well under a millisecond — plus a repaint, provided gain is
near the end of the stack. Placing gain earlier is permitted and correct, just
slower; the panel indicates this.

### Persistence and provenance

The stack serialises as `[{step, params, enabled}, ...]` into the survey file,
giving an inspectable, diffable, shareable record of exactly what was done to a
profile. Presets are named stacks. This is a deliberate feature: reporting
"background removed" becomes a stack that can be handed to a reviewer.

Scope of application is explicit. A stack belongs to the current view; applying
it across a grid is a button press, never a side effect.

### Falling out of the cached design

- **Difference view**: showing what a background step removed costs nearly
  nothing and diagnoses over-removal of genuine flat-lying features.
- **Display decimation happens after processing**, never before, so the view is
  a downsampled real result rather than a result computed on downsampled data.

## 8. Rendering

numpy to `QImage`, no matplotlib and no pyqtgraph, so there is no per-platform
dependency risk.

Pipeline: normalise, map to `uint8`, apply colormap LUT, build `QImage`, display
in a `QGraphicsView` for pan/zoom. Axes drawn with `QPainter`: two-way time on
the left, distance along line on the bottom, depth on the right once a velocity
is set. Columns decimate to widget width after processing.

**Default colormap: greyscale, black is high.** Bipolar and symmetric about
zero — white for strong negative, mid-grey for zero, black for strong positive —
following GPR convention. Other ramps may be offered; this is the default.

**Display gain is not a processing step.** Clip percentile, colour range, and
contrast alter the amplitude-to-colour mapping, not the data. Dragging them
remaps a LUT and repaints with no recomputation, and is not recorded in the
stack because the data did not change.

Normalisation sits behind a `Normalizer` interface. v1 ships percentile clip;
fixed-range, per-trace, and RMS variants are drop-ins requiring no renderer
change.

## 9. Plugin UI

Three docks around the existing QGIS canvas, so GPR data composes with the rest
of the project's layers.

```
┌──────────────┬────────────────────────────────┬──────────────┐
│ Survey tree  │        QGIS map canvas         │ Step stack   │
│  Site        │                                │ params and   │
│   └ Grid A   │   ═══════ line 12 ═══════      │ curve editor │
│      ├ L11   │        ▲ trace cursor          │              │
│      └ L12 ◀ │                                │              │
├──────────────┴────────────────────────────────┴──────────────┤
│  Profile viewer — line 12                                    │
└──────────────────────────────────────────────────────────────┘
```

### Map to profile link

Line geometries are generated from placements into a layer styled per grid.

- Click a line on the canvas: it opens in the profile viewer
- Move the cursor in the profile: a marker slides along that line on the map at
  that trace's real coordinate
- Move the cursor near a line on the map: the profile's vertical cursor snaps to
  the nearest trace
- Drag-select a distance range in the profile: that segment highlights on the map

All four ride on the trace-index join and require no additional machinery.

### Anomaly picking

Clicking a feature in the profile drops a point into a QGIS layer at that
trace's world coordinate, with two-way time, depth (when a velocity is set), and
source line as attributes. This turns the plugin from a viewer into a tool that
produces an interpretation overlayable on surface features.

### Threading

DZT loading runs off the main thread via `QgsTask`. Header parsing is cheap, so
the tree and map layer populate almost immediately while sample data streams in.

## 10. Persistence

Source of truth is `survey.nsgeo.json` in the project folder: grids, line
assignments, placements, processing stacks, relative DZT paths, and a schema
version. Human-readable, diffable, git-friendly, and readable by core with no
QGIS present.

Files outside the project directory are refused by default. `save_site(..., allow_absolute=True)`
stores such a file's absolute POSIX path instead, at the explicit cost of tying the survey file to
that machine's mount points and drive letters; in-tree files stay relative regardless. Decided
after Plan 1 review: shared-drive raw data is a normal layout, and an explicit opt-in beats both
a silent fallback and a hard refusal.

The plugin derives a GeoPackage of line geometries from it for map display. That
layer is regenerable and explicitly not the source of truth.

Import guesses line indices from GSSI file numbering, then presents a table for
correction before committing.

## 11. Testing and CI

Core tests are pure pytest, numpy in and numpy out, no QGIS, running on
GitHub Actions across Linux, macOS, and Windows. Core targets Python 3.9+ to
support QGIS LTR releases, which requires `from __future__ import annotations`
and no `X | Y` union syntax.

**Test data.** A synthetic DZT *writer*, used only in tests, generates files
with known headers and sample values for round-trip property tests without
committing binaries. Synthetic files prove self-consistency only; real GSSI
files are needed to catch real header quirks. The real files now in hand are ten
single-channel SIR-4000 DZT files from a campus training run, with nine `.DZX`
sidecars; no `.DZG` yet, so `TrackPlacement` remains unvalidated against real
data. Real survey files live in
`packages/nsgeo-core/tests/data/local/`, which is **gitignored**: DZT headers can
carry GPS and DZG files certainly do, and publishing archaeological site
locations in a public repository is not reversible. Survey data is additionally
ignored by extension across the whole tree — GSSI `.DZT`/`.DZG`/`.DZX`, MALA
`.rd3`/`.rd7`/`.rad`/`.cor`, Sensors & Software `.DT1` — because a path-scoped
rule does not catch a file dropped in the wrong directory. Committing a fixture
therefore requires `git add -f`, making it a deliberate act. Committed fixtures under
`tests/data/fixtures/` must be synthetic, or real files truncated and scrubbed
of coordinates after inspection.

**The boundary is enforced mechanically, not by discipline.** A test walks every
module under `src/nsgeo`, parses the AST, and asserts that nothing imports
`qgis`, `PyQt5`, `PyQt6`, `matplotlib`, or `scipy` at module level. It lands in
M0, before there is any code to violate it. This is what makes a single
repository safe: the rule fails the build rather than relying on vigilance.

**Plugin testing stays thin** by keeping logic out of widgets: file-to-line
matching, layer generation, and coordinate lookups are plain functions tested
headless. Widget behaviour is tested by hand. No `pytest-qt` scaffolding
investment for a one-person project.

**Property tests worth naming:** `background_mean` output has zero mean along
the trace axis; `bandpass` passes an in-band sinusoid and attenuates an
out-of-band one; `background_svd` with n=0 is the identity; `time_zero` updates
`t0_ns` consistently with the rows it dropped.

**CI:** ruff lint and format, mypy on core, pytest on the OS matrix, and a
plugin zip build so releases are never manual.

## 12. Distribution

Development: symlink `nsgeo_qgis/` into the QGIS plugins directory and
`pip install -e packages/nsgeo-core` into QGIS's Python. Edit core, use Plugin
Reloader, see the change.

Release: `build_zip.py` vendors the core into `nsgeo_qgis/_vendor/nsgeo/` with a
`sys.path` shim in `__init__.py`. Users install one zip from the QGIS Plugin
Repository. This is only safe because the core is numpy-only.

## 13. Milestones

| | Milestone | Rationale |
|---|---|---|
| M0 | Repo scaffold, licences, CI green, boundary test | Nothing else is verifiable without it; the boundary test lands before any code can violate it |
| M1 | DZT reader plus golden-file tests | Highest risk; everything depends on it |
| M2 | Data model, placements, grid geometry, JSON round-trip | The join everything uses |
| M3 | Processing steps, registry, property tests | Fully testable before any UI exists |
| M4 | Plugin skeleton, survey tree, import, lines on map | First clickable thing |
| M5 | Profile viewer: render, pan/zoom, axes | First sight of real data |
| M6 | Step stack panel, gain curve editor, difference view | The processing UI |
| M7 | Bidirectional map to profile cursor sync | The differentiator |
| M8 | Anomaly picking into a point layer | Becomes an interpretation tool |
| M9 | Zip build, docs, first release | Usable by other people |

M1 through M3 involve no QGIS, so they are fast to write and properly testable
rather than verified by clicking.

### Plan decomposition

Nine milestones is too much for one implementation plan. This splits cleanly at
the package boundary:

- **Plan 1 — core (M0 to M3).** No QGIS anywhere. Ends with a tested, installable
  `nsgeo` that reads DZT files, models a georeferenced survey, and applies
  processing steps, verified by pytest rather than by hand.
- **Plan 2 — plugin (M4 to M9).** Consumes Plan 1's public API. Ends with an
  installable zip.

Plan 2 should not be written until Plan 1 is done, because the plugin's design
depends on what the core's API actually turns out to look like, and guessing at
that in advance is how the boundary erodes.

## 14. Decisions log

- Name `nsgeo`, chosen over `subterra`, `archaeo-geophysics`, and `geoprospect`;
  free on PyPI
- Core MIT, plugin GPL-2.0-or-later
- numpy required, scipy optional, matplotlib excluded
- Own DZT reader rather than wrapping readgssi
- Grid is a coordinate frame; Site holds a flat line list
- Placement protocol chosen over grid parameters on Line, so GPS transects need
  no restructuring
- No automatic processing, at the user's explicit request
- Default colormap greyscale black-high, bipolar symmetric about zero
- Anomaly picking promoted into v1
- Public repository
- Line position stored in metres on the placement, not as index times spacing
  on the grid, so one grid can hold cross-hatched lines in both directions
- No `known_length` field; odometer correction deferred to processing
- Header size rule `1024 * rh_data` verified empirically against ten real files
- Single repository, with the core/plugin boundary enforced by a CI import test
  rather than by repository separation; split triggers documented in section 3
- Absolute paths for out-of-tree survey files are supported as an explicit `allow_absolute` opt-in
  on `save_site`, never as a silent fallback (2026-09-10, post-Plan-1 user decision)
