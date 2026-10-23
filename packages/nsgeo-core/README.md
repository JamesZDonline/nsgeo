# nsgeo

Near-surface geophysics core library: readers, survey model, geometry,
processing, and time and depth slices — numpy only, no QGIS.

MIT licensed. See the repository-root [`README.md`](../../README.md) for the
full project overview.

## Public API

This section names the supported surface of the core. Anything not listed
here is internal, and may change or move without notice. Top-level `nsgeo`
exports only `__version__`; everything else is imported from the subpackage
or module named below, for example `from nsgeo.geometry import Grid`. The
plugin imports only these names, and a test enforces that.

The version is 0.x: the surface is named, not frozen. It may still change
between minor releases.

### `nsgeo.io`

DZT and DZX readers.

| Name | Purpose |
|---|---|
| `DztError` | Raised when a DZT file is malformed or unsupported. |
| `DztHeader` | The parsed DZT header. |
| `DzxError` | Raised when a DZX sidecar exists but cannot be parsed. |
| `DzxInfo` | What the DZX sidecar records: name, scan range, dielectric, system and marks. |
| `DzxMark` | One marker from a DZX sidecar. |
| `read_dzx` | Parse the sidecar for a DZT, or return None when there is none. |
| `read_header` | Read only the header, cheaply. |
| `read_samples` | Read all samples as (channels, samples, traces). |
| `sidecar_for` | The DZX beside a DZT, or the path itself if it is one; None when there is none. |
| `trace_count` | Number of traces, from the file size. |

### `nsgeo.model`

The survey data model.

| Name | Purpose |
|---|---|
| `Line` | One collected survey line; headers are eager, samples are lazy. |
| `Profile` | One channel of one radargram; its data is raw and never mutated. |
| `Site` | The grids, lines, step stacks, presets and saved cubes of a survey. |
| `clear_profile_cache` | Drop the cached profiles. |

### `nsgeo.geometry`

Coordinate frames and trace placement.

| Name | Purpose |
|---|---|
| `Grid` | A survey grid: origin, azimuth, size, CRS, default line spacing and an optional velocity model. |
| `GridFit` | The result of fitting a grid to corner points. |
| `GridPlacement` | A line positioned parametrically within a grid frame. |
| `Placement` | How traces are positioned; the protocol placements satisfy. |
| `fit_grid_from_corners` | Least-squares rigid fit of grid-local metres to world coordinates. |

### `nsgeo.processing`

User-ordered processing steps. Nothing runs automatically.

| Name | Purpose |
|---|---|
| `ParamSpec` | One declared parameter of a step. |
| `REQUIRED` | Marks a parameter with no default. |
| `Radargram` | A radargram as the steps see it. |
| `Step` | A pure function of (parameters, radargram). |
| `StepStack` | An ordered list of steps applied to a radargram. |
| `available_steps` | The names of the registered steps. |
| `build_step` | The one way to construct a step; validates its parameters. |
| `default_params` | Constructor parameters that have a real default. |
| `get_step` | Look a step class up by name. |
| `is_unipolar` | Whether a step's output has no negative side. |
| `nyquist_mhz` | Nyquist frequency in MHz for a sample interval in ns. |
| `required_params` | Parameters that must be collected before a step can be built. |

### `nsgeo.slices`

Time and depth slices: binning lines into a cube and cutting it.

| Name | Purpose |
|---|---|
| `CoverageError` | A line cannot contribute to the requested cube. |
| `CubeFrame` | An affine raster frame in world coordinates. |
| `CubeStoreError` | A cube file is missing, unreadable or not a cube. |
| `LinePlan` | Everything about one line that does not change when the window moves. |
| `PreparedLine` | One line, processed and transformed, ready to bin. |
| `Provenance` | What a reader needs to trust a cube. |
| `SliceCube` | Binned amplitude over a frame and a z axis. |
| `SliceWindow` | A half-open level range, the unit a slice is cut from. |
| `ZAxis` | The cube's vertical axis, in two-way travel time. |
| `build_cube` | Bin every line into a resident cube. |
| `clear_kernel_cache` | Drop the cached fill-kernel spectra. |
| `disc_kernel` | A flat disc kernel of a given radius. |
| `fill` | Smear values and counts with a disc; the weighted mean. |
| `limit_over_slices` | A display limit measured over every finite value in some slices. |
| `load_cube` | Read a cube written by `save_cube`. |
| `npz_path` | Normalise a path to the `.npz` name the store writes. |
| `plan_line` | Precompute the resampling and grouping for one line. |
| `plan_windows` | Every window of a thickness, at a step. |
| `save_cube` | Write a cube to disk. |
| `shared_limit` | One display limit for the whole cube. |
| `slice_extent` | The world bounding box of a frame. |
| `stream_slice` | One slice, binned straight from the lines, holding no cube. |
| `to_north_up` | Resample a grid-local slice into a north-up raster. |
| `window_depths_m` | A window in metres, through a velocity model. |
| `window_label` | A window's text label. |
| `window_times_ns` | A window's first and last two-way time. |

### `nsgeo.project`

The survey definition file (`survey.nsgeo.json`).

| Name | Purpose |
|---|---|
| `ProjectError` | A survey definition file is malformed or unreadable. |
| `line_key` | The string a line is stored, keyed and looked up by. |
| `load_site` | Read a site from a survey definition file. |
| `save_site` | Write a site to a survey definition file. |

### `nsgeo.render`

Amplitude to pixels, with no Qt.

| Name | Purpose |
|---|---|
| `DEFAULT_COLORMAP` | The default colormap's name. |
| `FixedRange` | A user-chosen display limit. |
| `Normalizer` | The protocol that chooses a symmetric amplitude limit. |
| `PercentileClip` | A limit at a percentile of the absolute amplitude. |
| `UNIPOLAR_COLORMAPS` | Names of the colormaps for data with no negative side. |
| `UnipolarClip` | A limit for data with no negative side. |
| `colormap` | A 256-entry RGB lookup table, by name. |
| `colormap_names` | The table names, optionally filtered by polarity. |
| `decimate_columns` | Block-mean along the trace axis to a maximum width. |
| `to_index8` | Map amplitudes to 0..255, zero at 128. |
| `to_index8_unipolar` | Map 0..limit to 0..255. |
| `to_rgb8` | Amplitudes, a limit and a (256, 3) lookup table to an (H, W, 3) uint8 RGB array, mapped as `to_index8` does. |
| `to_rgba8` | Amplitudes, a limit and a lookup table to an (H, W, 4) uint8 RGBA array. Keyword-only `unipolar`: when true, maps as `to_index8_unipolar` does and alpha is 0 wherever the data is not finite; when false, maps as `to_rgb8` does, fully opaque. |

### `nsgeo.velocity`

Wave velocity and time-to-depth conversion.

| Name | Purpose |
|---|---|
| `C_M_PER_NS` | The speed of light, in metres per nanosecond. |
| `VelocityModel` | A layered velocity model; converts time to depth. |
| `resolve_velocity` | The model for a line: line override, then grid, then header dielectric. |
