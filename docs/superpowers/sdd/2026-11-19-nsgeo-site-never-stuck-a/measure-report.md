# Measure report (partial): the work after the fill lands

PARTIAL. 0.02 m is complete for Whole site, Grid1 and Grid6 (This grid). No 0.01 m number: the
Grid6 0.01 fill had not landed after a long wait under load, so I stopped the queue; Grid1 0.01,
Whole site 0.01 and a kriging variant of Grid1 never ran.

Load: load average 5.9-6.7 throughout (other sessions' pytest runs, ~92% CPU), never below 2.5 in
about 40 minutes of waiting; 9 later. ALL TIMINGS ARE UNDER LOAD (upper bounds). MemAvailable 4.4-5.8 GB.

Settings (the survey's own): Whole site kriging, 0.5 spacings, ten grids, thickness 5 ns, dz 0.2165,
shared stretch. Grid1: min_curvature, 0.5 spacings, smooth_y 0.1 m, z 0-40 ns. Grid6: kriging,
0.75 spacings, z 0-99.6 ns. Cell 0.1 -> 0.02.

| scope | cell | fill | draw after landing min/med | stretch after landing min/med | first north-up min/med | second north-up | peak RSS |
|---|---|---|---|---|---|---|---|
| Whole site (10 grids) | 0.02 | 196.9 s (_fill_for 110 calls = 187.5 s) | 1.126 / 1.251 s | 7.40 / 8.21 s | n/a | n/a | 2.05 GB |
| Grid1 (20x16, min_curv) | 0.02 | 44.5 s | 0.311 / 0.319 s (preview; solves running) | 2.455 / 2.488 s (provisional) | 0.438 / 0.456 s | 0.040 / 0.041 s | 0.99 GB |
| Grid6 (10x10, kriging) | 0.02 | 13.2 s | 0.042 / 0.042 s | 0.494 / 0.507 s | 0.197 / 0.237 s | 0.014 / 0.018 s | 0.72 GB |

3 repeats for draw, stretch, north-up.

Bracketing: fill = dock._apply_resolution() then (site) SiteScope._run_tick() after wait_for_site
(refresh_slice -> SiteEngine.slice_at -> SliceEngine.finish -> _fill_for, plus first stretch via the
layer limit); This grid = dock._apply_resolution() (set_resolution + first refresh_slice + map update).
Draw = slider moved (signals blocked) then SiteScope.refresh_slice() / dock.refresh_slice() (includes
slice_changed -> map layer), fills held. Stretch = refine.stretch=None then dock.display_limit()
(SiteEngine.stretch_limit / SliceEngine.stretch_limit). North-up = nsgeo.slices.clear_north_up_plans()
then to_north_up(dock._values, engine.frame), then a second call.

Caveat: Grid1 (min_curvature) is still provisional after the fill, so it is not a true "after landing"
number. Probe: scratchpad/test_zz_measure.py.keep.

Verdict at 0.02 m: Whole site draw ~1.1-1.3 s (borderline over 1 s, under load) and Whole site stretch
7-9 s (well over); This grid first north-up 0.2-0.46 s (under).
