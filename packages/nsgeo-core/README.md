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
| `CUT_KEY_PREFIX` | The prefix (`cut:`) of a cut's key, which no line key can have. |
| `Cut` | A path drawn on a grid, in grid metres, whose vertical section the cube gives. |
| `Line` | One collected survey line; headers are eager, samples are lazy. |
| `Profile` | One channel of one radargram; its data is raw and never mutated. |
| `Site` | The grids, lines, step stacks, presets, saved cubes, slice sources and site view of a survey. |
| `clear_profile_cache` | Drop the cached profiles. |
| `cut_key` | A cut's key from its id. |
| `is_cut_key` | Whether a key names a cut rather than a line. |

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
| `STEP_GROUPS` | The groups a step menu is laid out in, in processing order. |
| `Step` | A pure function of (parameters, radargram). |
| `StepStack` | An ordered list of steps applied to a radargram. |
| `TIME_BASE_RADAR` | `"radar"`: times are on the radar's own clock. |
| `TIME_BASE_TIME_ZERO` | `"time_zero"`: times are measured from each line's first break. |
| `available_steps` | The names of the registered steps. |
| `build_step` | The one way to construct a step; validates its parameters. |
| `default_params` | Constructor parameters that have a real default. |
| `first_break_ns` | The radar-clock time of a radargram's first break, by the Time zero step's own rule. |
| `get_step` | Look a step class up by name. |
| `grouped_steps` | The registered steps by group, in menu order. |
| `is_unipolar` | Whether a step's output has no negative side. |
| `nyquist_mhz` | Nyquist frequency in MHz for a sample interval in ns. |
| `required_params` | Parameters that must be collected before a step can be built. |
| `retime_ns` | A time on one clock, read on another: `t + (from_zero_ns - to_zero_ns)`. The one conversion rule between clocks. |
| `sets_time_zero` | Whether a list of step dicts has an enabled Time zero step. |
| `step_title` | The human title a front end shows for a step. |
| `time_base_of` | `TIME_BASE_TIME_ZERO` when a list of step dicts sets a time zero, else `TIME_BASE_RADAR`. |

### `nsgeo.slices`

Time and depth slices: binning lines into a cube and cutting it, and composing
several grids' slices into one site view.

| Name | Purpose |
|---|---|
| `BACKGROUND_FRACTION` | The weakest fraction of populated cells that `background_level` averages. |
| `CoverageError` | A line cannot contribute to the requested cube. |
| `CubeBlock` | The covered cells of one travel direction, packed: cell ids, means and counts. |
| `CubeFrame` | An affine raster frame in world coordinates. |
| `CubeStoreError` | A cube file is missing, unreadable or not a cube. |
| `CurvaturePlan` | Where minimum curvature solves and its operator; solves any slice's values. |
| `FillWeights` | Where to fill and from which neighbours, with weights; applied to any slice's values. |
| `FinishSettings` | How a slice is finished: interpolation method and distances, then smoothing. |
| `Footprint` | Where one grid lands on a site lattice: a window, and the bilinear taps of its pixels. |
| `LinePlan` | Everything about one line that does not change when the window moves. |
| `METHODS` | The interpolation methods: none, IDW, kriging, minimum curvature. |
| `MIN_SEAM_CELLS` | Populated cells a seam needs on each side. |
| `NEIGHBOURS_PER_QUADRANT` | How many nearest data cells each of the four quadrants contributes to a fill. |
| `NORMALISATION_METHODS` | The method names `normalise` accepts. |
| `PreparedLine` | One line, processed and transformed, ready to bin. |
| `Provenance` | What a reader needs to trust a cube. |
| `SEAM_WIDTH_SPACINGS` | A seam's width, in multiples of the pair's larger line spacing. |
| `CROP_MAX_DISTANCE_SPACINGS` | The most a section's max distance may be, in line spacings, for its minimum curvature to be solved on crops; above it the whole frame is solved. |
| `SECTION_MARGIN_SPACINGS` | How far a section's curvature crops reach round the cut, in line spacings. |
| `SECTION_PIECE_M` | The most of a cut one crop covers, in metres. |
| `Seam` | Two grids' facing strips, where their levels are compared. |
| `SectionColumns` | Where a section's columns sit along a cut and among the frame's cells, with their taps. |
| `SectionCrop` | A box of cells round one piece of a cut, and the columns it serves. |
| `SiteLattice` | A north-up pixel lattice in the site's CRS. |
| `SliceCube` | Binned amplitude over a frame and a z axis. |
| `SliceFill` | A planned fill, whichever method built it: what finishing a slice needs. |
| `SliceWindow` | A half-open level range, the unit a slice is cut from. |
| `SolveStopped` | A minimum-curvature solve gave up because it was asked to stop. |
| `Taps` | Where world points sit among a frame's cells: nearest cell and bilinear weights. |
| `ZAxis` | The cube's vertical axis, in two-way travel time. |
| `background_level` | The mean of the weakest `|values|` over populated cells. |
| `bilinear_taps` | The taps of world points on a frame, for blending the four cells around each. |
| `build_cube` | Bin every line into a resident cube. |
| `compose_footprints` | Sample each grid over its own footprint and average the overlaps. |
| `covered_cells` | How many distinct in-frame cells the lines fall in; the size of a packed cube. |
| `covered_pixels` | About how many lattice pixels the grids' windows hold together at a pixel size. |
| `curvature_margin_cells` | The crop margin, in cells, that a minimum-curvature section needs. |
| `edge_match_solve` | Per-grid gains from a weighted least squares over the seams. |
| `find_seams` | Every pair of grids with enough populated cells on each side of their seam. |
| `finest_fitting_cell` | The finest cell, rounded up to 0.01 m, at which the site draws in full under both size limits. |
| `finish_section` | Every level of a cube, finished and read along a section's columns, as the slice picture would show it. |
| `finish_slice` | Interpolate a slice's gaps, then smooth it. |
| `fitting_lattice` | The site lattice at the cell, doubled until it fits both a lattice-pixel limit and a covered-pixel limit. |
| `footprint` | The tight window around the inside points of a block of taps. |
| `frame_lattice` | The north-up lattice over a frame's own extent at any pixel; at the cell it reproduces an axis-aligned grid exactly. |
| `grid_axis` | The levels of the site axis inside one grid's time bounds. |
| `limit_over_slices` | A display limit measured over every finite value in some slices. |
| `load_cube` | Read a cube written by `save_cube`. |
| `max_pool_counts` | Each count becomes the largest within a reach, so a preview pixel cannot skip a one-cell line. |
| `normalise` | An affine gain and offset per grid, by a named method, with any manual multiplier folded in. |
| `npz_path` | Normalise a path to the `.npz` name the store writes. |
| `plan_curvature` | Plan a minimum-curvature solve near the data, within a max distance of it. |
| `plan_fill` | Plan the interpolation of empty cells within a max distance of data. |
| `plan_line` | Precompute the resampling and grouping for one line. |
| `plan_section_curvature` | One minimum-curvature plan per crop of a cut, built once for every level. |
| `plan_windows` | Every window of a thickness, at a step. |
| `sample` | The bilinear blend of a slice at each tap, blank where the nearest cell is blank. |
| `sample_counts` | The largest corner count at each tap, so a line one cell wide stays visible. |
| `save_cube` | Write a cube to disk. |
| `seam_masks` | The cells of each of two frames within a width of the other's footprint. |
| `column_distances` | Distances of a section's columns along a path: 0, step, ... and the length. |
| `section_columns` | Columns half a cell apart along a path, with the pixel rule's taps. |
| `section_crops` | Boxes round a cut, each serving at most a piece of it. |
| `shared_limit` | One display limit for the whole cube. |
| `site_axis` | The union of the grids' time bounds, clipped to a time range. |
| `slice_extent` | The world bounding box of a frame. |
| `smooth` | Gaussian smoothing along frame X and Y in metres; blanks stay blank. |
| `smoothing_reach_cells` | The smoothing kernel's radius in cells. |
| `solve_section_level` | One level solved by minimum curvature on a cut's crops and read along its columns. |
| `solve_section_level_whole` | One level solved by minimum curvature on the whole frame and read along a cut's columns. |
| `stretching_grids` | The grids whose omission alone lets the site draw at full detail under both size limits. |
| `stream_slice` | One slice, binned straight from the lines, holding no cube. |
| `to_north_up` | Resample a grid-local slice into a north-up raster, bilinear at the cell size. |
| `uses_crops` | Whether a section's max distance is small enough for its minimum curvature to be solved on crops. |
| `window_depths_m` | A window in metres, through a velocity model. |
| `window_label` | A window's text label. |
| `window_on` | A site window as a window on one grid's z axis. |
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
| `display_range` | The colour range for an array by one of QGIS's computed rules: minimum and maximum, cumulative cut, or mean ± standard deviations. |
| `gradient_stops` | The fewest colour stops that redraw a lookup table by straight-line blending, for a GIS gradient editor. |
| `row_envelope` | Per-row percentile of amplitude magnitude over the traces (strided above a cap), for showing headroom against the display limit. |
| `section_rgba8` | A section's values to (H, W, 4) uint8, transparent wherever blank, in either polarity. |
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

### `nsgeo.destagger`

The destagger a grid's lines need, measured from the lines themselves: each line is compared with its neighbours walked the other way.

| Name | Purpose |
|---|---|
| `AXIS_FAILED` | The reason a line gets when its grid's value could not be measured. |
| `AxisResult` | One axis's grid value, its 95% spread in metres, the lines used, and the reason when it could not be measured. |
| `DestaggerResult` | The result per axis and per line. |
| `EnvelopeBins` | An envelope averaged into time bins, with the time of bin 0 and the bin spacing. |
| `LineResult` | One line's status, value for its Destagger cell (None when not measured) and reason. |
| `LineStatus` | Grid value, own value, changes partway along, no clear match, or not measured. |
| `MeasureLine` | One line to measure: its bins, its placement as shown now, and its DZT header. |
| `MeasureStopped` | Raised when the caller's `should_stop` returns True. |
| `NO_NEIGHBOUR` | The reason a line gets when no line walked the other way lies beside it. |
| `envelope_bins` | Dewow, background removal, analytic envelope, then 8-sample time bins, for one channel's samples. |
| `measure_destagger` | The grid value per axis, and each line's result, for a set of placed lines: its own value when it is clearly off on its own, otherwise the grid value. |
| `one_way_result` | What `measure_destagger` gives when no axis was walked both ways, from the placements alone, so no line need be read; None when some axis was. |

### `nsgeo.velocity_fit`

Radar velocity from a diffraction hyperbola, with its standard error.

| Name | Purpose |
|---|---|
| `HyperbolaFit` | A fitted hyperbola: apex position, apex time, velocity, velocity standard error, RMS residual and point count. |
| `fit_hyperbola` | Least-squares hyperbola through points in metres and nanoseconds; scans the apex near a guess. Raises `ValueError` when no physical fit exists. |
| `hyperbola_time` | Two-way time in nanoseconds of a fitted hyperbola at given positions in metres; the one statement of the model outside the solver, for drawing a fit. |
| `StoredFit` | A fit as persisted on a `Line`: trace indices not metres, with the clicked points (radar-clock times), the zero its numbers were measured from, and a UTC timestamp, so several fits can later feed a Dix conversion. `to_dict` and `from_dict` give the survey-JSON form. |
| `refit` | A stored fit's clicked points fitted again with times measured from a given radar-clock zero. Raises `ValueError` as `fit_hyperbola` does. |
| `fit_at_zero` | A stored fit measured from a given zero: the fit itself when that is its own zero, else its points refitted. |
| `radar_clock_note` | The note for a fit made on the radar's own clock when the first break is more than half a sample from zero; says what the velocity would be from the first break. |
| `applied_fit_note` | Says so when a velocity applied from a fit is no longer what that fit measures. |
| `unusable_fit_note` | The text for a stored fit that cannot be fitted again at the line's current time zero, with the reason. |

### `nsgeo.velocity_source`

Where a line's or a grid's velocity came from: the saved fits that made it.

| Name | Purpose |
|---|---|
| `VelocitySource` | The record on a `Line` or `Grid`: how the velocity was made (`fit` or `weighted mean`), its member fits, the velocity and its standard error, and when it was applied. `from_fits` builds it, `summary` names it, `to_dict` and `from_dict` give the survey-JSON form. |
| `SourceFit` | One member of a record: the line key, fit id and `fitted_at` that identify the fit, and a copy of its numbers (t0, velocity, standard error, zero) as used, so the record holds after the fit is deleted or its line changes. `of` copies a `StoredFit`. |
| `weighted_mean` | Inverse-variance mean of velocity and standard-error pairs, with its standard error. Raises `ValueError` for no fits or a standard error that is zero, negative or not finite. |
| `METHOD_FIT`, `METHOD_WEIGHTED_MEAN` | The two ways a record's velocity is made: one picked fit, or the weighted mean of several. |
