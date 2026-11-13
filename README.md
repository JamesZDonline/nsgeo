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

*Last updated 2026-11-13.* Large pieces of work are numbered milestones (M0,
M1, …), each designed in [`docs/superpowers/specs/`](docs/superpowers/specs/)
before it is built. Smaller requests are issues. This list is updated whenever
a milestone merges or the plan changes.

### Done

One row per milestone, plus one for the smaller work in each release. Each
release's notes list everything in it.

| Milestone | What | Released in |
|---|---|---|
| M0–M3 | The core library: DZT reader, data model, grid geometry, processing steps | [0.1.0](https://github.com/JamesZDonline/nsgeo/releases/tag/v0.1.0) (2026-10-16) |
| M4–M6 | The QGIS plugin: sites, grids and import, the profile viewer, the processing stack | 0.1.0 |
| M7–M9 | The map ↔ profile link, picks, and the first release | 0.1.0 |
| M10–M11 | Time and depth slices, with GeoTIFF export | 0.1.0 |
| M12 | Whole-site slices | [0.2.0](https://github.com/JamesZDonline/nsgeo/releases/tag/v0.2.0) (2026-10-31) |
| M13 | Velocity from diffraction hyperbolas | 0.2.0 |
| | Time cutoff, display gain, grid corners from the map, zigzag profiles, the Panels menu | 0.2.0 |
| M14 | Migration (Stolt f-k) | [0.3.0](https://github.com/JamesZDonline/nsgeo/releases/tag/v0.3.0) (2026-11-06) |
| | Slice interpolation (kriging, IDW, minimum curvature) and line editing | 0.3.0 |
| M15 | Cut anywhere: the vertical section beneath any line drawn on the map | [0.4.0](https://github.com/JamesZDonline/nsgeo/releases/tag/v0.4.0) (2026-11-12) |
| | Faster, sturdier slices at fine cells; time zero sets the clock; line placement corrections (stretch to fit, destagger); grid velocity is optional | 0.4.0 |
| | Whole site at fine cells: both exports at a finer cell and pixel, run in the background, with a style file beside the GeoTIFF ([#108], [#175]) | next release |
| | The Survey panel marks lines with saved velocity fits; Save fit clears the points for the next hyperbola ([#126], [#128]); a line is identified by itself, settled before M17's GPS lines ([#89]) | next release |

### In progress

- **Colour a slice with QGIS's own symbology** ([#180]): a Colours choice in
  the Slices panel keeps the slice layer's own QGIS style (a colour ramp, a
  typed min/max, a cumulative cut) as you move through the depths; M19's
  magnetometer maps will reuse it. Built, awaiting its walkthrough.
- **A grid velocity from its fits** ([#127], [#86]): a grid's Set velocity…
  lists every saved fit on the grid's lines, averages the ones you tick, and
  remembers which fits made the grid's velocity. Slices take their depths
  from the grid's velocity, as cuts already do. Designed, with a five-task
  plan.
- **M16: 3-D**, in four plans. **Plan A, Export for ParaView:** one action
  writes a grid's prepared volume, picks and lines to a folder ParaView opens
  ready to explore. Built, awaiting its walkthrough. **Plan B, surfaces from
  picks:** select picks on the map and nsgeo builds the surface they name,
  leaving holes where the radar saw nothing; it shows on the map, in the
  ParaView export and in a Surfaces panel with its fit. Planned, with the
  panel's mockup under review. Then the QGIS 3-D view, and cuts in the
  ParaView scene.

### Next, in order

Most are things the next milestones build on, so doing them now is cheaper
than reworking M16–M17 afterwards.

1. **M16: 3-D.** In progress (above).
2. **M17: GPS lines.** Read the RTK GPS records in GSSI `.DZG` files and place
   lines by their track ([#134]). Design drafted, in three parts: GPS lines,
   profiles at true distance, and GPS areas.
3. **M18: issue cleanup.** Work through the backlog of open bugs and review
   follow-ups in the [issues](https://github.com/JamesZDonline/nsgeo/issues).
4. **M19: magnetometer data.** The first instrument other than GPR:
   Bartington Grad601 grids placed on the map with the GPR, cleaned up in
   the Processing panel (zero, destripe, despike) and Edit lines (destagger),
   joined into one map with the grids levelled to each other, and a mag strip
   above the radargram on lines and cuts. Designed, in three parts; the first
   is planned once [#180] merges.

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
  placement together is done); the scroll wheel no longer moves a line to
  another grid in Edit lines ([#176]).
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
  alone or the max distance is large ([#147]); lines processed differently in
  one cube, such as migration at each line's own velocity ([#178]); the scroll
  wheel no longer changes dz, z0 and z1 by accident, which can freeze QGIS
  ([#177]); whole site at fine cells, the follow-ups: coverage edge lines on
  coarse previews, averaged previews, a memory estimate for This grid, refusals
  that stay on screen, and where the preview note sits ([#157]); exports of
  large sites at fine cells, holding one grid at a time so they fit in memory
  ([#167]).
- **Cuts:** a faster minimum-curvature solve and first preview ([#169]); clear
  the picks a deleted cut leaves behind ([#170]); the review follow-ups
  ([#171]).
- **Output:** annotated, publication-quality profile figures ([#83]); one
  cloud-optimised GeoTIFF per depth band, for hosting slices online ([#146]); a help
  page for each processing step (the first page is built and waiting for a
  walkthrough).

[#11]: https://github.com/JamesZDonline/nsgeo/issues/11
[#34]: https://github.com/JamesZDonline/nsgeo/issues/34
[#36]: https://github.com/JamesZDonline/nsgeo/issues/36
[#47]: https://github.com/JamesZDonline/nsgeo/issues/47
[#58]: https://github.com/JamesZDonline/nsgeo/issues/58
[#83]: https://github.com/JamesZDonline/nsgeo/issues/83
[#86]: https://github.com/JamesZDonline/nsgeo/issues/86
[#88]: https://github.com/JamesZDonline/nsgeo/issues/88
[#89]: https://github.com/JamesZDonline/nsgeo/issues/89
[#108]: https://github.com/JamesZDonline/nsgeo/issues/108
[#114]: https://github.com/JamesZDonline/nsgeo/issues/114
[#125]: https://github.com/JamesZDonline/nsgeo/issues/125
[#126]: https://github.com/JamesZDonline/nsgeo/issues/126
[#127]: https://github.com/JamesZDonline/nsgeo/issues/127
[#128]: https://github.com/JamesZDonline/nsgeo/issues/128
[#129]: https://github.com/JamesZDonline/nsgeo/issues/129
[#130]: https://github.com/JamesZDonline/nsgeo/issues/130
[#131]: https://github.com/JamesZDonline/nsgeo/issues/131
[#132]: https://github.com/JamesZDonline/nsgeo/issues/132
[#134]: https://github.com/JamesZDonline/nsgeo/issues/134
[#138]: https://github.com/JamesZDonline/nsgeo/issues/138
[#140]: https://github.com/JamesZDonline/nsgeo/issues/140
[#146]: https://github.com/JamesZDonline/nsgeo/issues/146
[#147]: https://github.com/JamesZDonline/nsgeo/issues/147
[#157]: https://github.com/JamesZDonline/nsgeo/issues/157
[#158]: https://github.com/JamesZDonline/nsgeo/issues/158
[#162]: https://github.com/JamesZDonline/nsgeo/issues/162
[#167]: https://github.com/JamesZDonline/nsgeo/issues/167
[#169]: https://github.com/JamesZDonline/nsgeo/issues/169
[#170]: https://github.com/JamesZDonline/nsgeo/issues/170
[#171]: https://github.com/JamesZDonline/nsgeo/issues/171
[#175]: https://github.com/JamesZDonline/nsgeo/pull/175
[#176]: https://github.com/JamesZDonline/nsgeo/issues/176
[#177]: https://github.com/JamesZDonline/nsgeo/issues/177
[#178]: https://github.com/JamesZDonline/nsgeo/issues/178
[#180]: https://github.com/JamesZDonline/nsgeo/issues/180

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
