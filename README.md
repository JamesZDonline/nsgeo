# nsgeo

Near-surface geophysics: survey processing, analysis, and visualisation.

nsgeo processes GPR surveys inside QGIS, so each profile is seen and worked on in
its map context. It is built as an independent core library with a thin QGIS
plugin on top. Today it reads GSSI DZT files. The core is laid out so that other
instruments, such as magnetometry, conductivity and resistivity, can be added later
without touching the plugin.

> **Status: 0.1.0, the first release, experimental.** The QGIS plugin imports
> DZT files into grids placed on the map, links the map and the profile both
> ways, processes profiles, records picks, and builds time and depth slices. It
> installs from a single zip on QGIS 3.40–3.44 and QGIS 4.x, and each release's
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
  single- or multi-channel, with their DZX marks. Each grid carries a velocity,
  which sets the depth scale.
- **The map and the profile, linked both ways.** Hover a line on the map to
  preview its radargram. Moving along the profile moves a marker along the line
  on the map, and a range selected on the profile lights up on the map.
- **Processing, under your control.** Each line has a stack of steps, and
  **nothing runs automatically**. The steps are time-zero, dewow, bandpass,
  three gains (AGC, parametric, and a manual gain curve you drag on the profile),
  background removal (full-line mean, sliding window, or SVD), and amplitude
  transforms (absolute value, square, envelope), plus a time cutoff you drag on
  the profile. Stacks can be saved as presets and applied to a whole grid. A
  difference view shows what a step removed.
- **Display.** Display gain and colour tables change only how the profile looks,
  never the data.
- **Picks.** Click the profile to record a pick at a trace and two-way time. Picks
  are stored in the site's GeoPackage as a QGIS point layer, with the distance
  along the line and the depth.
- **Time and depth slices.** Bin a grid's processed lines into a volume, step
  through slices on the map as a live raster layer, and export them as GeoTIFFs.

Not built yet: migration, fitting a velocity from hyperbolas, and instruments
other than GPR. Known issues and smaller gaps are tracked in the
[issues](https://github.com/JamesZDonline/nsgeo/issues).

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
