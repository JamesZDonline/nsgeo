# Isosurfaces and 3-D views: research and sizing

**Status: researched, not designed.** Asked on 2026-10-30 as a possible new milestone: how
isosurfaces work, and whether QGIS can carry them. This note records what was read, what was
measured on the real files, and the open questions a design would start from.

## How isosurfaces work for GPR

An isosurface is the surface of equal value through a volume: every point where amplitude
crosses a threshold. For GPR the volume is the binned cube (our `SliceCube`), and the surface
wraps the strong reflectors in 3-D. The pipeline, as GPR-SLICE runs it and as the probe below
reproduced it:

1. **A unipolar, gap-free volume.** Envelope or squared amplitude, since a bipolar wavelet
   would give an onion of alternating shells. Gaps between lines are filled first; GPR-SLICE
   interpolates nine radargrams between 0.5 m lines before building its 3-D file.
2. **Balance every slice.** GPR-SLICE's quickstart runs "Auto-Gain-All" to normalise each
   time slice before "Interpolate+3D File". On our data this is not optional (see Measured).
3. **Smooth in 3-D.** GPR-SLICE offers 3×3×3 up to 17×17×17 boxcars, plus z-only variants.
4. **Cut the near surface.** Its own burial-mound example sets the top of the volume at 15 ns
   to drop the surface reflection.
5. **Pick a level.** GPR-SLICE uses percent of the volume maximum, defaulting to 75%. A
   *negative* setting draws the weak side instead: a soil-filled moat shows as a low-amplitude
   isosurface where strong-side rendering shows nothing.
6. **Extract a triangle mesh.** Marching cubes (Lorensen & Cline 1987; GPR-SLICE since 2010)
   or a variant. Surface nets need no 256-case table and vectorise in numpy, which is what the
   probe used.
7. **Render.** Lit surfaces, often two nested levels with the outer one translucent, combined
   with slices or radargrams in the same scene, with vertical exaggeration.

GPR-SLICE also reports the enclosed volume (cell count × cell volume at the site velocity) and
exports the mesh as CSV triangles, DXF or STL, and the volume as XYZ/XYZIRGB ASCII.

**The alternative is direct volume rendering.** Low amplitudes get zero opacity and the rest
is ray-cast with a transfer function, as in Kadıoğlu's Temple of Augustus work (2010). No
threshold decision is needed, but it needs a real volume renderer.

**Migration matters more here than in slices.** An unmigrated point diffractor is a
hyperboloid in the cube, and its isosurface is an umbrella, not a point. M14's 2-D migration
collapses tails along lines only; cross-line tails remain.

## What QGIS can do

| Capability | Status | Source |
|---|---|---|
| PolyhedralSurface / TIN geometries, 2-D and 3-D | **Yes, since 3.40** | Oslandia 2024; measured |
| Lit polygon meshes in the 3-D view | **Yes** | measured, 3.44.7 |
| Terrain off, so things below ground are visible | **Yes**: `setTerrainRenderingEnabled(False)` | PyQGIS 3.44/4.2; measured |
| Cross-section tool (rotated box clip) | **Yes, 3.44**; Python access to its clipping planes in 4.0 | changelogs |
| Custom 3-D map tools from Python (`Qgs3DMapTool`) | **4.0 only** | 4.0 changelog |
| Point clouds with attribute colour ramps and PDAL filters | Yes | user manual |
| Export scene to OBJ; 3-D map item in print layouts | Yes | user manual; measured |
| Vertical exaggeration of vector layers | **No**: layer `zScale` has no effect in 3-D | measured |
| Volume rendering, voxel layer type | **No** | not found anywhere |
| One slice at its depth | **Yes**: drape the slice raster on a flat terrain lowered with `QgsFlatTerrainSettings.setElevationOffset` | measured, 3.44.7 |
| Several slices at their depths | **Yes**: one mesh layer (2DM + ASCII DAT), coloured by the layer's own colour ramp | measured, 3.44.7 |
| Custom Qt3D entities from Python | **No**: QGIS ships no PyQt3D | `qgis._3d` contents |

**The engine's future is open.** Qt 3D has been deprecated since Qt 6.8. In February 2026
Martin Dobias (Lutra) asked on QGIS-Developer whether QGIS should move off it, naming QRhi as
the candidate; no decision or QEP was found. A plugin that only *produces layers and sets
renderers* is insulated from an engine swap. One that reaches into the scene graph would not
be, and from Python it cannot anyway.

## Measured on the real files

Probe scripts were kept out of the repo. Lines `FILE__001`–`010`, placed 0.5 m apart and
20 m long, as the real-data tests do. Preset `time_zero, dewow, background_mean, gain_agc,
amp_envelope`; cube binned, every level filled at 1.5 × spacing, 3×3×3 boxcar, surface nets,
depth at the header's ε_r (v = 0.080 m/ns). QGIS 3.44.7.

| | 0.1 m cell | 0.05 m cell |
|---|---|---|
| cube (nz × ny × nx), window 4–40 ns | 167 × 50 × 200 | 167 × 100 × 400 |
| level (balanced volume) | 98th percentile = 45% of max | 90th percentile = 29% of max |
| triangles | 33,242 | 521,682 |
| bin + fill + smooth + extract | 0.8 s | 2.4 s (extract alone 0.79 s) |
| whole process (read DZT → GeoPackage) | — | 4.3 s, 547 MB peak |
| GeoPackage per layer | ~4 MB | ~57 MB |
| QGIS 3-D render, offscreen | 1.4 s | 5.7 s MultiPolygonZ, 8.8 s PolyhedralSurfaceZ; 1.1 GB peak |

Findings:

- **Without slice balancing, the isosurface is a sheet along the top of the time window,** not
  features. AGC did not prevent it. With the window starting at 1 ns, every vertex of the 98th-
  percentile surface lay at 0.05–0.29 m; with 8 ns, the shallowest vertex was the window top.
  Dividing each level by its own median, as GPR-SLICE balances, gave discrete bodies.
- **The three geometry types render pixel-identically.** MultiPolygonZ was fastest and is
  standard GeoPackage. TIN and PolyhedralSurface are the honest types, but GDAL warns
  "Registering non-standard gpkg_geom_TIN extension". A MultiPolygon of edge-sharing triangles
  is also OGC-invalid, which would trip QGIS validity tools.
- **Layer `elevationProperties().setZScale()` changes nothing in 3-D** (0 of 1.17 M pixels
  differed at 1 vs 5). Exaggeration has to be baked into the stored Z, which makes Z no longer
  true depth.
- **`QT_QPA_PLATFORM=offscreen` renders a black frame and segfaults at exit.** The xcb
  platform, with no window shown, renders correctly. A CI test of the 3-D render needs xvfb
  plus Mesa. Layer-level tests do not.
- Surfaces need consistent outward winding. Back faces from `setAddBackFaces` z-fight into
  stripes.
- **Slices sit at their depth, two ways (added after the first draft wrongly said they
  could not).** (1) One slice: a GeoTIFF draped on a flat terrain with its elevation offset
  set to the slice depth; isosurfaces pass through it. (2) Any number: one mesh layer, a
  sheet of cell-centre vertices per slice at Z = −depth, amplitude as a vertex dataset
  (MDAL 2DM + ASCII DAT, both plain text from numpy), coloured through the layer's 2-D colour
  ramp (`ColorRamp2DRendering`). Three slices, 30 k vertices: 0.6 s alone, 1.5 s with the
  isosurface. Two traps: `QgsMeshLayer3DRenderer` is not in the Python API, so it is built
  from XML through `QgsApplication.renderer3DRegistry()` (a QML style would do the same); and
  the symbol draws nothing unless `setVerticalDatasetGroupIndex` names the "Bed Elevation"
  group. The terrain route gives one slice per 3-D view; the mesh route gives many but the
  sheets are opaque, so lower slices hide what is beneath them. Vertical curtains (profiles
  standing in the scene) were not tried; a 2-D mesh with vertical faces is probably
  degenerate.

## Options

**A. Native QGIS 3-D through layers (lean).** The core gains numpy-only volume preparation
and surface extraction. The plugin writes the mesh as a layer beside the slices, attaches a
polygon 3-D renderer, and opens a 3-D view with terrain off. It keeps every house rule: core
numpy-only, no pip, derived and regenerable, with provenance. It works on 3.40–4.x. Cost: no
live threshold slider (each change re-extracts, then re-tessellates for seconds at 500 k
triangles), and no volume rendering.

**B. Export for external viewers (cheap complement).** VTK ImageData (`.vti`) for the cube
and PLY/OBJ/STL for meshes, all writable with numpy. ParaView then gives volume rendering,
live isosurfaces and clipping for free. About two tasks, but it leaves QGIS and loses the link
back to the profiles.

**C. Embedded VTK/PyVista viewer.** pvGIS (BRGM, AGPLv3, QGIS 3.40–4.99) proves it works. It
pip-installs pyvista, pyvistaqt, meshio, trimesh and embreex through a separate
PackageInstallerQgis plugin, and opens its own window. It is the richest option and breaks the
"no `pip install` into the QGIS interpreter" rule outright. Rejected unless that rule is
revisited.

**D. Voxels as a point cloud.** LAS written from numpy, with amplitude as an attribute and a
PDAL filter as the threshold. Native, and the threshold is a layer filter, not a rebuild. But
it draws as dots, not surfaces, and QGIS indexes it to COPC on first load. Untested.

**Recommendation: A, with B as a later small add-on.** C only if the dependency rule changes.

## Sizing (option A)

**One plan of about five tasks, medium. Not a research problem: the probe already ran it
end to end.**

- Core volume preparation: fill all levels, 3-D smooth, balance, cut a window, convert time
  to depth through the existing `VelocityModel`.
- Core surface extraction, oriented and in world coordinates through `CubeFrame` (azimuth
  included). Tests: a synthetic sphere's area and volume, then the real files.
- Plugin: write the layer with provenance, attach the 3-D renderer, store exaggeration.
- Plugin: open and configure a 3-D view (terrain off, camera on the grid).
- UI: level, window, smoothing and exaggeration in the Slices dock, with an explicit Build.

Slices in the scene add a task (mesh layer writer and its XML-built renderer); the probe
already ran it. Risks that would grow it: profiles standing as curtains in the scene; site-wide isosurfaces across grids (amplitude comparability, as M12's edge matching found);
and render tests needing xvfb in CI.

## Open questions for a design

1. Level semantics: percentile, percent of max (GPR-SLICE), or absolute? Negative surfaces
   too?
2. Storage: MultiPolygonZ (standard, technically invalid) or PolyhedralSurfaceZ (honest,
   non-standard extension)? Site GeoPackage or a sidecar file?
3. Exaggeration baked into Z: keep true depth as an attribute, or as a second layer?
4. Per grid or across the site?
5. Wait for M14? Migrated cubes give far cleaner surfaces. The cube is in time, so a velocity
   change means re-extraction.
6. The layer also draws on the 2-D map as footprints. Is that a useful anomaly-outline map, or
   clutter to suppress?
7. Link back: on QGIS 4, `Qgs3DMapTool` could make a click on a surface open the profile
   beneath it. On 3.44 there is no Python hook.

## Sources

Read in full: the GPR-SLICE v7 manual's isosurface chapter (pp. 216–223), volume smoothing
(p. 69) and volume export (p. 334); QGIS 3.44 `qgslayoutitem3dmap.cpp`; pvGIS's
`metadata.txt` and `requirements.txt`. Read from changelogs and docs: the QGIS rows above.
Secondhand, from search summaries only: Quarta et al., Kadıoğlu, and the ISPRS paper.

- [GPR-SLICE v7 user manual](https://s3-ap-southeast-2.amazonaws.com/gprslice/GPR-SLICE_User_Manual.pdf)
- [QGIS 3.44 visual changelog](https://qgis.org/project/visual-changelogs/visualchangelog344/) — cross-section tool, globe, large scenes
- [QGIS 4.0 visual changelog](https://www.qgis.org/project/visual-changelogs/visualchangelog40/) — `Qgs3DMapTool`, clipping planes in Python, dynamic vector chunking
- [QGIS 3-D map view manual](https://docs.qgis.org/latest/en/docs/user_manual/map_views/3d_map_view.html)
- [PyQGIS 4.2 `Qgs3DMapSettings`](https://qgis.org/pyqgis/4.2/_3d/Qgs3DMapSettings.html)
- [Oslandia, complex 3-D geometries in QGIS 3.40 (2024)](https://oslandia.com/en/?p=9042)
- [QGIS-Developer, "QGIS 3D: Move away from Qt 3D?" (Feb 2026)](http://www.mail-archive.com/qgis-developer@lists.osgeo.org/msg57250.html)
- [Qt 6.8: Qt 3D deprecated](https://doc.qt.io/qt-6/whatsnew68.html)
- [QEP #301, large scenes and globe: Qt3D limits](https://github.com/qgis/QGIS-Enhancement-Proposals/issues/301)
- [pvGIS](https://plugins.qgis.org/plugins/pvGIS/) and [its repository](https://gitlab.com/brgm/qgis/pvgis)
- [PackageInstallerQgis](https://plugins.qgis.org/plugins/PackageInstallerQgis/)
- [Qgis2threejs 3.1.2](https://plugins.qgis.org/plugins/Qgis2threejs/version/3.1.2/) — QGIS ≥ 4.0, web export
- [scikit-image marching cubes](https://scikit-image.org/docs/0.25.x/auto_examples/edges/plot_marching_cubes.html)
- [Quarta et al. 2002, Annals of Geophysics](https://doaj.org/article/4c5b5f6e267949f2abd9a388b0c19188) — iso-amplitude surfaces, sensitive to S/N
- [Kadıoğlu 2010, Near Surface Geophysics](https://avesis.ankara.edu.tr/yayin/bca6b2c0-e90c-4c54-b30b-6c194ca90265/definition-of-buried-archaeological-remains-with-a-new-3d-visualization-technique-of-a-ground-penetrating-radar-data-set-in-temple-augustus-in-ankara-turkey) — transparency volume rendering
- [ISPRS, amplitude rendering of GPR volumes](https://www.isprs.org/proceedings/XXXII/part5/618_XXXII-part5.pdf)
- [Bancroft, CREWES 2005, 3-D GPR migration](https://www.crewes.org/Documents/ResearchReports/2005/2005-65.pdf)
