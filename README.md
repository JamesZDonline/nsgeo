# nsgeo

Near-surface geophysics: survey processing, analysis, and visualisation.

A cross-platform toolstack for GPR, magnetometry, conductivity, and resistivity
data — built as an independent core library with thin front-end layers, starting
with a QGIS plugin.

> **Status: early development.** The core library (DZT reader, survey model,
> processing) is complete and tested. The QGIS plugin loads sites, imports
> lines onto the map, and shows and processes profiles. Map↔profile cursor
> sync, picking, and a release zip are next.

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

Timeslices, migration, velocity analysis, and other instruments are designed for
but out of scope for v1.

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
