# M16 Plan C walkthrough: results

The author ran it on this machine with profile `ns_geo_m16c` (the plugin linked to the branch's worktree), on a copy of the Plan B walk site with its three surfaces. The page, with 15 checks and results in its database, is https://claude.ai/artifact/DRA8vht1AyKmKGXAC1mYoQ.

- **Round 1** (2026-11-17 evening): branch at 47de12d.
- **Round 2** (2026-11-18 evening): branch at c3e0177. Only the outlined checks were re-run: L2, L3 (rewritten), L4 (new), C2 and X2.

## Results

| Check | Round 1 | Round 2 | Author's note |
|---|---|---|---|
| B1 The button waits for a site | pass | (stands) | |
| V1 Grid1 in 3-D | pass | (stands) | "almost instantaneous and the picks sit on the surfaces. how did it decide which surface to show?" (Answered in chat: it shows the Slices panel's grid, and every built surface of that grid.) |
| V2 QGIS's own controls | pass | (stands) | |
| L1 A new pick appears | pass | (stands) | |
| L2 A rebuild and a stale surface | **fail** | pass | Round 1: "qgis stopped responding on rebuild and then crashed entirely both times I tried it. It doesn't do that when the 3d view is not open" |
| L3 Depth stretch | pass | pass | Round 1: the view took its stretch from the ParaView export, which was "utterly unintuitive… Depth stretch should be a setting in the surfaces panel probably." Rewritten for the Surfaces panel box (R16, R17). Round 2: "I expected it to be in the settings box? but that works I guess. It is kindof a different thing than the other settings that require a rebuild. leave it where you put it for now." |
| L4 Deleting a surface with the view open | (new) | pass | Added after the review's C1 (R18). |
| G1 This grid moves the scene; Whole site doesn't | pass | (stands) | |
| C1 Close it by hand, and reopen | pass | (stands) | |
| C2 Closing the site closes the view | **fail** | pass | Round 1: "open a new site with the view open crashed qgis." |
| C3 Docking the view | pass | (stands) | |
| X1 A project in another CRS | pass | (stands) | |
| X2 No "temporary layers" warning | unmarked | pass | Round 1: "there's always that warning because slices is a temporary layer." Fixed for the Slices layer too (R19). |
| P1 Many surfaces | skip | skip | |
| D1 The guide | skip | skip | |

## Walk fix round 1 (d70900f)

**Root cause of L2 and C2.** The scene keeps a raw pointer to every layer that has a 3-D entity. A rebuild deletes the old surface layer, and opening another site deletes the old site's layers. The next `setLayers` then touches the deleted layer:

- the core dump shows a SIGSEGV in `Qgs3DMapScene::removeLayerEntity`;
- under xvfb, a real 3-D window crashed 8 times in 9 with nsgeo's flow.

**The fixes:**

- **R15:** a `QgsProject.layersWillBeRemoved` handler clears the renderer of every layer nsgeo manages before QGIS deletes it. With it, 0 of 18 runs crashed.
- **R16 and R17:** a per-grid **3D view depth stretch** box in the Surfaces panel drives only the QGIS view. ParaView keeps its own stretch.
- **Slice layer:** the first attempt set `skipMemoryLayersCheck` on it, which turned out not to work.

## Walk fix round 2 (ea99935, c3e0177)

An opus review of d70900f (`walk-fix-review.md`) found the following, all fixed:

- **C1:** deleting a surface still bypassed the handler, because SurfaceLayers forgot the layer before removing it. In a real window this crashed 2 times in 2.
  - **R18:** two fixes. The handler also counts the layers it gave renderers to, and SurfaceLayers drops a layer before forgetting it. Afterwards, 3 runs in 3 survived.
- **I1:** `skipMemoryLayersCheck` only covers memory layers, and a GDAL file under the temp folder still counts as temporary.
  - **R19:** Slices previews now live under the cache folder, `<CacheLocation>/nsgeo/nsgeo-slice-<pid>-*`, and dead-pid folders are swept. A test pins `isTemporary()` as False.
- **I2:** the loading test could not fail. It was rewritten (R20).
- **I3:** the guide now says which grids the stretch box lists (R21).
- **M1 to M4:** the site-close test drives the real path; the box rests at ×3; stored values are clamped to the box's range; a non-number raises `ValueError`.

## Offered, not filed

- R6 multi-channel `_zero_of`.
- A failed `_zero_of` read is retried on every refresh.
- A real-window hand check on QGIS 4.2. CI's 4.2 job runs the calls but does not render.
