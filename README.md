# nsgeo

Near-surface geophysics: survey processing, analysis, and visualisation.

A cross-platform toolstack for GPR, magnetometry, conductivity, and resistivity
data — built as an independent core library with thin front-end layers, starting
with a QGIS plugin.

> **Status: 0.1.0, the first release, experimental.** The QGIS plugin imports
> DZT files into grids placed on the map, links the map and the profile both
> ways, processes profiles, records picks, and builds time and depth slices. It
> installs from a single zip on QGIS 3.40–3.44 and QGIS 4.x. macOS is untested,
> and the [getting-started guide](docs/guide/getting-started.md) lists the known
> issues.

## Install

1. Download `nsgeo_qgis-<version>.zip` from the
   [Releases page](https://github.com/JamesZDonline/nsgeo/releases). Do not
   unzip it.
2. In QGIS, choose **Plugins → Manage and Install Plugins… → Install from ZIP**,
   choose the zip, and click **Install Plugin**. Click **Yes** at QGIS's security
   warning, which it shows for any plugin installed from a zip.
3. Restart QGIS.

Nothing else needs installing. The
[getting-started guide](docs/guide/getting-started.md) covers installing,
upgrading, a first session from DZT files to slices, where your data lives, and
the known issues.

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
| [`packages/nsgeo-core`](packages/nsgeo-core) | MIT | Readers, data model, geometry, processing. Pure Python, numpy only. No QGIS, no Qt. |
| [`packages/nsgeo-qgis`](packages/nsgeo-qgis) | GPL-2.0-or-later | QGIS plugin: docks, map tools, rendering. No signal processing. |

The boundary is strict and load-bearing. The core has no `qgis` or `PyQt`
import anywhere, which keeps it testable without a QGIS runtime, reusable by
other front ends, and extensible to new instruments without touching UI code.

The core requires **numpy and nothing else**, because QGIS ships its own Python
interpreter that users on Windows and macOS generally cannot `pip install` into.
A numpy-only core can be safely vendored into the plugin zip. scipy is an
optional accelerator with a numpy fallback; matplotlib is not used.

## v1 scope

Load GSSI DZT files, organise them into sites and grids, view profiles, and
apply user-controlled processing.

- DZT reader, single- and multi-channel
- Site / Grid / Line / Profile model, with grid georeferencing from GNSS
  corners, on-map digitising, or existing polygons
- A processing step stack — **nothing runs automatically** — covering time-zero,
  dewow, three gain steps including a draggable manual gain curve, bandpass, and
  background removal by full-line mean, sliding window, or SVD
- Profile viewer with real-time display gain and a difference view showing what
  a background step actually removed
- Bidirectional map ↔ profile cursor synchronisation
- Anomaly picking from the profile into a QGIS point layer

Migration, velocity analysis, and other instruments are designed for but out of
scope for v1. Time and depth slices, first planned for later, shipped in 0.1.0.

## Design

The full design document lives at
[`docs/superpowers/specs/2026-09-10-nsgeo-gpr-qgis-design.md`](docs/superpowers/specs/2026-09-10-nsgeo-gpr-qgis-design.md).

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
