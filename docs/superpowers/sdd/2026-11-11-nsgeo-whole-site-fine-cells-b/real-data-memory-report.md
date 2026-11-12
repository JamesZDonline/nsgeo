# Real-data memory check, milestone B export: report

Branch nsgeo-fine-cells-export, HEAD d2b8ba2. Nothing in the repo changed. Script and logs:
`/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/0356759e-44aa-46ca-bfe2-a82acefa658a/scratchpad/realdata-mem/`
(`measure.py`, `run_a.log`, `run_b.log`, `session/` = copies of the json and gpkg; the originals were never opened).

## Settings
- Ten grids, all included, 258 lines. Each grid's own preset (one preset), transform amp_square,
  normalisation background, grid gains from the session (all 1.0).
- Live site resolution from the json: cell 0.1, dz 0.2165 ns, t0 -1.775, t1 45.2165.
- Finish: kriging, max distance 0.5 spacings, smoothing 0 / 0 (from site_view).
- 17 windows read from the exported file's NSGEO_WINDOW_NS, as (top, thickness) = (t0, 4.763 ns).
- Spec built with `SiteSession.open_site` + `SiteEngine.set_source/set_resolution` (headless, as the
  plugin's `site_source`) then `site_export.site_export_spec(...)`.
- Memory: 15.9 GB total, about 9 GB available at the start; prepare took about 18 s, no errors.
- Traced run = first 3 bands, generator closed, tracemalloc started after lines were prepared.
  Each setting ran in its own process; timed run first, traced run second.

## Results

| cell / pixel (m) | lattice | pixels | estimate held | tracemalloc peak | estimate / peak | RSS before -> after (MB) |
|---|---|---|---|---|---|---|
| 0.025 / 0.0125 | 5163 x 6069 | 31.3 M | 1309.8 MB | 1239.3 MB | 1.057 | 713 -> 1790 (+1077) |
| 0.025 / 0.025 | 2582 x 3035 | 7.8 M | 535.9 MB | 464.6 MB | 1.153 | 695 -> 1093 (+398) |

Both: 2,229,600 grid cells in total, 17 bands; the estimate is the same for the 3-band and 17-band specs.
The estimate is at or above the measured peak in both cases, so the budget refuses safely.

Estimate parts (MB; kriging so solve = 0, cubes = 0):

| cell / pixel | lines (not in held) | weights | taps | gather | band | file (uncompressed) |
|---|---|---|---|---|---|---|
| 0.025 / 0.0125 | 340.0 | 214.0 | 593.2 | 156.9 | 345.6 | 2841.0 |
| 0.025 / 0.025 | 340.0 | 214.0 | 148.5 | 39.3 | 134.1 | 710.5 |

The dialog's preview calls `estimate_export` on the same spec, so held_bytes is the same number
(the `slices_plan`/`export_flow` path was not run separately).

## Times (seconds per band, timed run)
- 0.025 / 0.0125: band 0 = 49.2 (includes setup: gathers, seams, normalisation), then 0.8, 0.8.
- 0.025 / 0.025: band 0 = 52.3, then 0.3, 0.3 (an earlier, killed attempt: 77.1, 0.5, 0.4).
- Band 0 is dominated by setup, not by the pixel size; later bands are fast with kriging and the
  background normalisation.

## Notes and differences from the bench
- The estimate is 6% over at the fine setting and 15% over at the coarse one, so it stays
  conservative; the tighter margin is at the setting the budget actually gates.
- RSS growth at the fine setting (+1077 MB) is a little under the tracemalloc peak (1239 MB):
  ru_maxrss is a high-water mark of the process and freed pages get reused, so it is a rough
  cross-check only. It agrees with tracemalloc to within about 15%.
- In `site_export_spec` the `method` argument is the normalisation (background), not the
  interpolation; the brief's "the json's method" could be read as kriging, which `normalise`
  rejects. Kriging goes in the `finish`.
- Only 3 of 17 bands were run. Later bands were as fast as bands 1 and 2 and the estimate does not
  depend on band count, but a full 17-band peak was not measured.
- Minimum curvature was not measured (the site view uses kriging); at the fine setting it adds a
  `solve` part to the estimate that this run does not check.
- The bench's synthetic site is smaller per grid (20 m, 0.5 m spacing); here the grids are real
  and rotated up to 98 degrees, 2.2 M cells at 0.025 m.
