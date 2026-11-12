# nsgeo

Near-surface geophysics: survey processing, analysis, and visualisation.

nsgeo processes GPR surveys inside QGIS, so each profile is seen and worked on in
its map context. It is built as an independent core library with a thin QGIS
plugin on top. Today it reads GSSI DZT files. The core is laid out so that other
instruments, such as magnetometry, conductivity and resistivity, can be added later
without touching the plugin.

> **Status: 0.4.0, experimental.** The QGIS plugin imports DZT files into grids
> placed on the map, lets you fix, fit and destagger a line's placement after
> import, links the map and the profile both ways, processes and migrates
> profiles, shows a vertical section along any line you draw (a cut), records
> picks that stay on their line, measures velocities from diffraction
> hyperbolas, and builds time and depth slices for one grid or the whole site.
> It installs from a single zip on QGIS 3.40–3.44 and QGIS 4.x, and each release's
> zip is checked by installing it into QGIS 3.40, 3.44 and 4.2. macOS is
> untested, and the [getting-started guide](docs/guide/getting-started.md) lists
> the known issues.

## Install

1. Download `nsgeo_qgis-<version>.zip` from the
   [Releases page](https://github.com/JamesZDonline/nsgeo/releases), not the
   *Source code* downloads, which will not install. Do not unzip it.
2. In QGIS, choose **Plugins → Manage and Install Plugins… → Install from ZIP**,
   choose the zip, and click **Install Plugin**. Click **Yes** at QGIS's security
   warning, which it shows for any plugin installed from a zip.
3. Restart QGIS.

Nothing else needs installing. The
[getting-started guide](docs/guide/getting-started.md) covers installing,
upgrading, a first session from DZT files to slices, where your data lives, and
the known issues.

## What it does

- **Sites, grids and lines.** Grids are placed from corners typed, picked on the
  map or read from a polygon. Then import GSSI DZT files into a grid,
  single- or multi-channel, with their DZX marks. Depths use a line's own
  velocity, else its grid's, else the dielectric in the file header. After import, a line's label, offset, direction,
  start and grid can be edited, one line at a time or several together, and
  lines can be moved to another grid. A line can be stretched or compressed so
  its ends sit on the grid's edges, and destaggered along its direction of
  travel, by an amount typed or measured from the data.
- **The map and the profile, linked both ways.** Hover a line on the map to
  preview its radargram. Moving along the profile moves a marker along the line
  on the map, and a range selected on the profile lights up on the map.
- **Processing, under your control.** Each line has a stack of steps, and
  **nothing runs automatically**. The steps are time-zero, dewow, bandpass,
  three gains (AGC, parametric, and a manual gain curve you drag on the profile),
  background removal (full-line mean, sliding window, or SVD), and amplitude
  transforms (absolute value, square, envelope), plus a time cutoff you drag on
  the profile and migration (Stolt f-k), which collapses diffraction hyperbolas.
  Stacks can be saved as presets and applied to a whole grid. A
  difference view shows what a step removed.
- **Display.** Display gain and colour tables change only how the profile looks,
  never the data.
- **Picks.** Click the profile to record a pick at a trace and two-way time. Picks
  are stored in the site's GeoPackage as a QGIS point layer, with the distance
  along the line and the depth. A pick stays on its line when the grid or the
  line is edited, and its depth follows the line's velocity.
- **Time and depth slices.** Bin a grid's processed lines into a volume, fill
  between the lines by kriging, inverse distance or minimum curvature, step
  through slices on the map as a live raster layer, and export them as GeoTIFFs.

Not built yet: instruments other than GPR. The [roadmap](#roadmap) below shows
what is coming, and known issues and smaller gaps are tracked in the
[issues](https://github.com/JamesZDonline/nsgeo/issues).

## Roadmap

*Last updated 2026-11-12.* Large pieces of work are numbered milestones (M0,
M1, …), each designed in [`docs/superpowers/specs/`](docs/superpowers/specs/)
before it is built. Smaller requests are issues. This list is updated whenever
a milestone merges or the plan changes.

### Done

| Milestone | What | Released in |
|---|---|---|
| M0–M3 | The core library: DZT reader, data model, grid geometry, processing steps | 0.1.0 (2026-10-16) |
| M4–M6 | The QGIS plugin: sites, grids and import, the profile viewer, the processing stack | 0.1.0 |
| M7–M9 | The map ↔ profile link, picks, and the first release | 0.1.0 |
| M10–M11 | Time and depth slices, with GeoTIFF export | 0.1.0 |
| M12 | Whole-site slices | 0.2.0 (2026-10-31) |
| M13 | Velocity from diffraction hyperbolas | 0.2.0 |
| | Time cutoff, display gain, grid corners from the map, zigzag profiles that all read the same way, the Panels menu, and other field requests | 0.2.0 |
| | Slice interpolation: kriging, IDW and minimum curvature ([#110], [#122]) | 0.3.0 (2026-11-06) |
| | A bandpass that no longer wraps the direct wave into the bottom of the trace ([#115]) | 0.3.0 |
| M14 | Migration (Stolt f-k) ([#123]) | 0.3.0 |
| | Survey panel grids start collapsed ([#133]) | 0.3.0 |
| | Line editing: edit a line's placement after import, move lines between grids, and keep picks on their line when it moves ([#29], [#64], [#35]) | 0.3.0 |
| | Grid velocity is optional: without one, lines use their header dielectric, and import flags a header dielectric no soil has ([#4]) | 0.4.0 (2026-11-12) |
| | Shift+scroll over the map moves the depth one Step per wheel notch ([#109]) | 0.4.0 |
| | Local real-data tests read one survey at a time, so the GPS lines for M17 no longer break them ([#141]) | tests only |
| | A cube held in memory stores only the cells its lines cross: 3–8× less memory at fine cells, the same slices. Saved cubes use the compact format, and older saved cubes still load ([#113]) | 0.4.0 |
| | A faster minimum-curvature solver: multigrid, about 4–5× faster at a 0.05 m cell with the same slices, so the sharp slice arrives in under a second after the depth stops ([#111]) | 0.4.0 |
| | Whole site never refuses a fine cell: past a size it draws a coarser preview and says why in the panel. Every slice blends the cells around each pixel at the cell size and is drawn smooth when zoomed in ([#107], [#112]) | 0.4.0 |
| | The Hilbert envelope no longer leaks the top of a trace into the bottom, and a bandpass whose Low edge is below its taper width now removes DC ([#116], [#117]) | 0.4.0 |
| | The background solver lets go of a cancelled solve's memory at once, not at the next solve, and its errors name their type (the worker items in [#120]) | 0.4.0 |
| | The Slices memory warning counts what minimum curvature really holds: its plan beside the kriging preview, about twice the weights of IDW or kriging ([#148]) | 0.4.0 |
| | This grid and Whole site read a grid's lines and preset the same way, and a refused preparation clears the map. Ticking every line in the line chooser means every line, including lines imported later ([#100], [#101], [#106], [#103]) | 0.4.0 |
| | Line placement corrections: stretch or compress a line so its ends sit on the grid's edges (in Edit lines, or at import), and a destagger shift along each line's direction of travel, typed for a line or a selection ([#3], [#47]) | 0.4.0 |
| | Time zero sets the clock: the row the Time zero step lands on reads 0 ns, so depths, fits and slices measure from each line's first break. Picks, saved fits, cubes and GeoTIFFs record the zero they were measured from, so older projects and saved cubes open where they were ([#97]) | 0.4.0 |
| | Measure the destagger: a Measure button in Edit lines works out each grid's shift from its own lines, and each line's own shift where it is clearly off, as a starting point to adjust before OK ([#159]) | 0.4.0 |
| M15 | Cut anywhere: draw a line on the map with the **Cut** tool and see the vertical section beneath it, read from the grid's slices, with the same hover, cursor and picks as a survey line. Cuts and their picks move with their grid. Under minimum curvature a kriging preview shows at once, and the solved section replaces it in the background (about 100 s on Sunnyside Grid 1, [#169]). A site with cuts saves as schema 2, which 0.3.0 cannot open ([#172]) | 0.4.0 |

### In progress

- **Whole site at fine cells: the export** ([#108]): an export finer than the
  preview, streamed to disk in the background. Designed; the plan is next.
- **Velocity from fits** ([#126], [#128], [#127], [#86]): the Survey panel
  marks the lines that have saved fits, and Save fit clears the points for
  the next hyperbola. Built, in review. Next, a grid velocity dialog that
  averages the fits on a grid's lines and remembers which fits it used, with
  slices taking their depths from the grid's velocity. Designed.

### Next, in order

Most are things the next milestones build on, so doing them now is cheaper
than reworking M16–M17 afterwards.

1. **M16: a 3-D scene.** Cuts stood upright, picked surfaces and isosurfaces.
   Being designed.
2. **How a line is identified** ([#89]), settled before M17 stores GPS
   coordinates in it.
3. **M17: GPS lines.** Read the RTK GPS records in GSSI `.DZG` files and place
   lines by their track ([#134]). Design drafted, in three parts: GPS lines,
   profiles at true distance, and GPS areas.
4. **M18: issue cleanup.** Work through the backlog of open bugs and review
   follow-ups in the [issues](https://github.com/JamesZDonline/nsgeo/issues).
5. **M19: magnetometer data.** The first instrument other than GPR.

Also worth doing early: edit or delete a pick from the profile ([#36]), now
that cuts carry picks too; the migration real-data test ([#125]), before M16
builds on migrated cubes; and the three ways a restored cube can still come
back on the wrong clock without a note ([#162]).

### Wishlist, not yet scheduled

Grouped by area. The order within a group is not a priority.

- **Line placement and survey geometry:** grids that are not rectangles
  ([#130]; the outline and its slice mask come with M17's GPS areas); balancing
  lines walked in different directions (the second half of [#47]); a preset or
  velocity override for a selection of lines at once ([#58]; editing their
  placement together is done).
- **Velocity:** a modifier-click for velocity points ([#88]); draw a box
  around a hyperbola and let the plugin mark it ([#140]).
- **Processing and the profile:** choose a preset when importing ([#129]); hide
  the slice band ([#131]); set time zero by eye, dragging it on the profile
  ([#158]); trace stacking ([#114]); a frequency profile
  ([#34]); configurable axes ([#11]).
- **Sites and the Survey panel:** more than one site in a QGIS project
  ([#132]); Whole site sharpening as you zoom, for sites too big to draw at the
  cell size ([#138]). Whether several sites will ever be open at once is worth
  deciding before M16, which adds more code that assumes one.
- **Slices:** minimum curvature accurate beyond float32 where a line stands
  alone or the max distance is large ([#147]).
- **Cuts:** a faster minimum-curvature solve and first preview ([#169]); clear
  the picks a deleted cut leaves behind ([#170]); the review follow-ups
  ([#171]).
- **Output:** annotated, publication-quality profile figures ([#83]); one
  cloud-optimised GeoTIFF per depth band, for hosting slices online ([#146]); a help
  page for each processing step (the first page is built and waiting for a
  walkthrough).

[#3]: https://github.com/JamesZDonline/nsgeo/issues/3
[#4]: https://github.com/JamesZDonline/nsgeo/issues/4
[#11]: https://github.com/JamesZDonline/nsgeo/issues/11
[#29]: https://github.com/JamesZDonline/nsgeo/issues/29
[#34]: https://github.com/JamesZDonline/nsgeo/issues/34
[#35]: https://github.com/JamesZDonline/nsgeo/issues/35
[#36]: https://github.com/JamesZDonline/nsgeo/issues/36
[#47]: https://github.com/JamesZDonline/nsgeo/issues/47
[#58]: https://github.com/JamesZDonline/nsgeo/issues/58
[#64]: https://github.com/JamesZDonline/nsgeo/issues/64
[#83]: https://github.com/JamesZDonline/nsgeo/issues/83
[#86]: https://github.com/JamesZDonline/nsgeo/issues/86
[#88]: https://github.com/JamesZDonline/nsgeo/issues/88
[#89]: https://github.com/JamesZDonline/nsgeo/issues/89
[#97]: https://github.com/JamesZDonline/nsgeo/issues/97
[#100]: https://github.com/JamesZDonline/nsgeo/issues/100
[#101]: https://github.com/JamesZDonline/nsgeo/issues/101
[#103]: https://github.com/JamesZDonline/nsgeo/issues/103
[#106]: https://github.com/JamesZDonline/nsgeo/issues/106
[#107]: https://github.com/JamesZDonline/nsgeo/issues/107
[#108]: https://github.com/JamesZDonline/nsgeo/issues/108
[#109]: https://github.com/JamesZDonline/nsgeo/issues/109
[#110]: https://github.com/JamesZDonline/nsgeo/pull/110
[#111]: https://github.com/JamesZDonline/nsgeo/issues/111
[#112]: https://github.com/JamesZDonline/nsgeo/issues/112
[#113]: https://github.com/JamesZDonline/nsgeo/issues/113
[#114]: https://github.com/JamesZDonline/nsgeo/issues/114
[#115]: https://github.com/JamesZDonline/nsgeo/issues/115
[#116]: https://github.com/JamesZDonline/nsgeo/issues/116
[#117]: https://github.com/JamesZDonline/nsgeo/issues/117
[#120]: https://github.com/JamesZDonline/nsgeo/issues/120
[#122]: https://github.com/JamesZDonline/nsgeo/pull/122
[#123]: https://github.com/JamesZDonline/nsgeo/issues/123
[#125]: https://github.com/JamesZDonline/nsgeo/issues/125
[#126]: https://github.com/JamesZDonline/nsgeo/issues/126
[#127]: https://github.com/JamesZDonline/nsgeo/issues/127
[#128]: https://github.com/JamesZDonline/nsgeo/issues/128
[#129]: https://github.com/JamesZDonline/nsgeo/issues/129
[#130]: https://github.com/JamesZDonline/nsgeo/issues/130
[#131]: https://github.com/JamesZDonline/nsgeo/issues/131
[#132]: https://github.com/JamesZDonline/nsgeo/issues/132
[#133]: https://github.com/JamesZDonline/nsgeo/issues/133
[#134]: https://github.com/JamesZDonline/nsgeo/issues/134
[#138]: https://github.com/JamesZDonline/nsgeo/issues/138
[#140]: https://github.com/JamesZDonline/nsgeo/issues/140
[#141]: https://github.com/JamesZDonline/nsgeo/issues/141
[#146]: https://github.com/JamesZDonline/nsgeo/issues/146
[#147]: https://github.com/JamesZDonline/nsgeo/issues/147
[#148]: https://github.com/JamesZDonline/nsgeo/issues/148
[#158]: https://github.com/JamesZDonline/nsgeo/issues/158
[#159]: https://github.com/JamesZDonline/nsgeo/issues/159
[#162]: https://github.com/JamesZDonline/nsgeo/issues/162
[#169]: https://github.com/JamesZDonline/nsgeo/issues/169
[#170]: https://github.com/JamesZDonline/nsgeo/issues/170
[#171]: https://github.com/JamesZDonline/nsgeo/issues/171
[#172]: https://github.com/JamesZDonline/nsgeo/pull/172

## Why

Most GPR software makes you choose between processing your profiles and seeing
them in spatial context. This aims at both, and specifically at one thing that
is missing from most of it: **map-driven navigation**. Click a survey line on a
map, see its profile, move the cursor along the profile and watch a marker track
across the map — with your excavation plans, imagery, GNSS points, and other
geophysics visible underneath.

## Structure

| Package | Licence | Contents |
|---|---|---|
| [`packages/nsgeo-core`](packages/nsgeo-core) | MIT | Readers, data model, geometry, processing, slices. Pure Python, numpy only. No QGIS, no Qt. |
| [`packages/nsgeo-qgis`](packages/nsgeo-qgis) | GPL-2.0-or-later | QGIS plugin: docks, map tools, rendering. No signal processing. |

The boundary is strict and load-bearing. The core has no `qgis` or `PyQt`
import anywhere, which keeps it testable without a QGIS runtime, reusable by
other front ends, and extensible to new instruments without touching UI code.
The plugin imports only the core's named public API, which
[`packages/nsgeo-core/README.md`](packages/nsgeo-core/README.md) documents.

The core requires **numpy and nothing else**, because QGIS ships its own Python
interpreter that users on Windows and macOS generally cannot `pip install` into.
A numpy-only core can be safely vendored into the plugin zip. scipy and
matplotlib are not used: the bandpass and the slice gridding use numpy's FFT,
and everything else is plain numpy.

To work on the code, see
[`packages/nsgeo-qgis/README.md`](packages/nsgeo-qgis/README.md) for the
development install, the tests, and building the zip.

## Design

The design documents live in
[`docs/superpowers/specs/`](docs/superpowers/specs/), starting with the original
[GPR and QGIS design](docs/superpowers/specs/2026-09-10-nsgeo-gpr-qgis-design.md).
Each milestone's implementation plan is in
[`docs/superpowers/plans/`](docs/superpowers/plans/).

## A note on survey data

Real `.DZT` and `.DZG` files are **never committed**. DZT headers can carry GPS,
and DZG files contain per-trace coordinates; publishing archaeological site
locations is not reversible. Local development data goes in
`packages/nsgeo-core/tests/data/local/`, which is gitignored. Committed fixtures
are synthetic, or truncated and coordinate-scrubbed after inspection.

## Prior art

[GPRPy](https://github.com/NSGeophysics/GPRPy) (MIT),
[readgssi](https://github.com/iannesbitt/readgssi) (GPL-3.0), and
[RGPR](https://github.com/emanuelhuber/RGPR) are the existing open-source GPR
tools, and all three are worth your attention. `nsgeo` writes its own DZT reader
rather than wrapping any of them, to keep the core permissively licensed and to
own the component everything else depends on.

## Licence

Core is MIT. The QGIS plugin is GPL-2.0-or-later, as QGIS requires. See each
package's `LICENSE`.
