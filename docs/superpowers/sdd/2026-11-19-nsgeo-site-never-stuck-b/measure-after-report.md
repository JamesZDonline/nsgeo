# #193 "after" measurement (branch head 1d48977, Sunnyside COPY, cell 0.02 m)

Data: `~/nsgeo-site-walk/Sunnyside` (copy only). Survey settings as stored: Whole site kriging, max distance 0.5 spacings, start cell 0.1;
Grid1 min_curvature (max dist 0.5, smooth_y 0.1 m, start cell 0.05); Grid6 kriging (0.75, start cell 0.1).
Probe: `test_zz_measure_after.py.keep` in this folder. One run per case unless noted (the Whole site case ran 3 times; all three are listed).

## Results

| scope | largest gap | p99 gap | edit -> picture | edit -> stretch | peak RSS (VmHWM) |
|---|---|---|---|---|---|
| Whole site (run 2, with gap positions) | 3.06 s | 0.012 s | 101.2 s | 102.2 s | 2.12 GB |
| Whole site (run 1) | 2.68 s | 0.012 s | 103.9 s | 105.0 s | 2.16 GB |
| Whole site (run 3, with callback timing) | 2.75 s | 0.011 s | 95.0 s | 96.2 s | 2.17 GB |
| This grid, Grid1 (min_curvature) | 1.00 s | 0.012 s | 24.0 s | 26.4 s (first, preview) / 63.7 s (final, after the refine rest) | 1.02 GB |
| This grid, Grid6 (kriging) | 0.27 s | 0.012 s | 8.1 s | 8.5 s | 0.76 GB |

Gaps are the 10 ms QTimer's inter-fire intervals, from just before `cell_spin.setValue(0.02)` until the flow is idle and 2 s have passed with no event
(the 2 s quiet tail adds nothing: "all incl quiet" maxima equal the to-last-event ones).

Where the big gaps sit (seconds after the edit, duration):
- Whole site run 2: (0.12, 0.11), (0.23, 0.35), **(98.15, 3.06)**. Run 3: (0.11, 0.11), (0.22, 0.35), **(92.28, 2.75)**.
  The 0.35 s at 0.2 s is the debounce firing `_apply_resolution` (the edit itself); every other gap in the 95-100 s of fill work is under 15 ms.
  The big one ends exactly at the picture: run 3 timed the callbacks: `on_done` (the draw on landing of the last grid) = **2.734 s**; `on_stretch` = 0.045 s;
  `FillFlow._fill_landed` itself ~0 s for every grid. So the GUI stays live during all ten grids' fills and the stretch measure, then freezes ~2.7-3.1 s for the one draw.
- Grid1: (0.12, 0.28) the edit, **(22.99, 1.00)** ending at the picture (the draw on landing), (23.99, 0.34), (29.05, 0.35), (61.27, 0.27); rest <15 ms.
- Grid6: (0.12, 0.27) the edit, (7.98, 0.17) the draw on landing.

Peak RSS is the process high-water mark after `clear_refs` reset just before the edit; it includes the loaded survey (the worker is a thread of the same process).

## Cancel latency (Whole site)

Edit to 0.02 m, spin 5 s (label then read "Working out the fill at 0.02 m: grid 1 of 10", `fill_flow.working` True), then `dock.fill_flow.cancel()`
(the same method the Cancel link's slot calls). `cancel()` returned in 0.055 s; worker not busy and `cell_spin` back at 0.1 by that point
(`to_idle_and_restored` = 0.055 s). Largest GUI gap over the whole case 0.35 s (the edit's debounce firing at 0.2 s); none after Cancel. Peak RSS 1.0 GB.

## Refine-line samples (the `dock.refine_label` text, sampled every 100 ms, change points)

Whole site (run 2): "" (0.07 s) -> "Working out the fill at 0.02 m: grid 1 of 10" (0.58) -> grid 2 (20.8) -> 3 (31.7) -> 4 (33.0) -> 5 (34.1) -> 6 (52.4) -> 7 (60.2)
-> 8 (77.6) -> 9 (85.6) -> 10 (93.5) -> "Working out the colour stretch..." (101.2) -> "" (102.2). Same sequence in runs 1 and 3.

Grid6: "" -> "Working out the fill at 0.02 m: 10%" (0.4) climbing through 98% (7.95) -> "Working out the colour stretch..." (8.15) -> "" (8.56).

Grid1: "Refining..." (0.07) -> "Working out the fill at 0.02 m: 27%" (0.4) ... 99% (22.97) -> "Kriging preview" (24.0) -> "Refining..." (24.3)
-> "Colour stretch (0 of 8)..." (29.4) ... "(7 of 8)..." (57.2) -> "Working out the colour stretch..." (61.6) -> "" (63.7).
(Grid1's fill landed at 24.0 s with the kriging preview, then the existing refine rest and its 8-step stretch ran; that rest is not part of #193's flow.)

## Load averages (1-min, `uptime`, at the start of each case)

Load was 11.8 at first; waited about 5 minutes until it fell below 4. Whole site run 1 started at 2.6; run 2 at 2.08; Grid1 2.03 (rerun 2.20);
Grid6 2.18; Cancel 2.04 (rerun 1.70); Whole site run 3 0.63. None above 4 during any measured run. (Grid1 and Cancel were each rerun once: Cancel's first
run died on a probe bug, an assert on `spin_until` returning False at timeout; Grid1's first run stopped waiting before the refine rest finished.)

## How each number was bracketed

- Edit: `dock.cell_spin.setValue(0.02)` (the real debounce -> `_apply_resolution` path; in Whole site the site scope's tick follows). Edit time = just before that call.
- Picture: end of the flow's `on_done` callback (`FillFlow._on_done`, wrapped; = `dock._on_fill_done`, which draws), also the first `slice_changed` after the edit.
- Stretch: end of the flow's `on_stretch` callback (wrapped; `dock._on_stretch_landed`); `final` flag recorded (Grid1's first landing was non-final, the second final).
- Gaps: 10 ms `QTimer` on the GUI event loop started just before the edit.
- Idle: `fill_flow.working` and `.stretching` False, at least one stretch landed, no event for 2 s, and for This grid `refine_label` empty.
- Stops: 15 min per case and MemAvailable < 2 GB (never hit; MemAvailable stayed above 5 GB at starts).

## Before / after (before: same data at 0.02 m under load 6-9, upper bounds)

| | before | after |
|---|---|---|
| Whole site fill | 196.9 s blocking the GUI | 95-104 s to the picture, GUI live (gaps <15 ms) apart from the 2.7-3.1 s draw on landing |
| Whole site stretch after landing | 7.4-8.2 s blocking | 1.0-1.2 s from picture to stretch, background; `on_stretch` callback 0.045 s |
| Whole site draw after landing | 1.1-1.3 s | on_done 2.73 s measured (blocks the GUI; this is the whole remaining freeze) |
| Grid1 (min_curvature) fill | 44.5 s blocking | 24.0 s to picture, GUI live; worst gap 1.00 s (the draw on landing) |
| Grid6 (kriging) fill | 13.2 s blocking | 8.1 s to picture; worst gap 0.27 s |
| Cancel | not available | 0.055 s to idle and settings restored |

Caveat: the before draw figure (1.1-1.3 s) and the after `on_done` (2.7 s) are not the same bracket (before: the draw alone after a held fill; after: the
whole landing callback in the site scope, incl. whatever the tick does on landing), and loads differed (before 6-9, after under 3).

## Verdict

No for Whole site: the largest GUI gap is 2.7-3.1 s, all of it the single draw on landing (`on_done`); every other moment of the 95-104 s is under 0.35 s
(the edit's own debounce, 0.35 s). Grid6 is under 0.3 s (0.27 s); Grid1 peaks at 1.0 s, again the draw on landing. Cancel is instant.

## Landing draw split

Probe: `test_zz_measure_split.py.keep` (this folder). One run per case, at 0.02 m, Sunnyside copy. Load (1-min) at the start: Whole site 1.04, Grid1 1.16
(load at the edit 1.11 / 1.14). Times are inclusive wall time of wrappers on the class methods (GUI thread), summed over calls; cProfile
ran alongside on the landing only. Landing = the flow's `on_done` callback; tick = `refresh_slice()` called directly with the slider moved
(levels base, +1, -1, base) after everything was idle and held (`fills_missing` false, flow not working).

Caveat on the landing column: when the last fill lands, the flow starts the shared stretch job on the worker thread at once, so the
draw runs while that job competes for the GIL. The landing numbers therefore include some contention that a tick (no worker running) does not.
`_site_seams` was never called (the draw's normalisation is not "edge"), so it is 0 here; `display_limit` is ~1 ms (held or deferred to the stretch).

### Whole site

| part | landing draw (on_done) | later tick, same cell (3 levels: 0.61 / 0.62 / 0.67 total) | first-draw only? |
|---|---|---|---|
| `SiteScope.refresh_slice` total (= on_done) | 2.56 s | 0.61-0.67 s | |
| `SiteEngine.slice_at` (everything below but the layer) | 2.40 s | 0.48-0.54 s | |
| `SiteEngine._gather` (20 calls, 10 grids; largest grid 0.47 s) | 1.85 s | 0.000 s (cached) | yes, per lattice |
| `compose_footprints` | 0.34 s | 0.30-0.36 s | every tick |
| `SiteEngine._shown` (normalise + each grid's `finish`, fills held; `SliceEngine.finish` x10 = 0.18 / 0.16-0.17 s) | 0.20 s | 0.17-0.18 s | every tick |
| `SiteEngine._sliced` (the slicing; `SliceEngine.slice_at` x10) | 0.12 s | 0.08-0.11 s | every tick |
| `_site_seams` | not called | not called | n/a |
| `SiteScope.display_limit` / `dock.display_limit` | 0.001 s | 0.000 s | |
| map layer: `plugin._on_slice_changed` (= `layer.update_north_up`) | 0.036 s | 0.038-0.039 s | every tick |
| `fills_missing`, `update_legend`, `status_text`, `show_refine` | <= 0.003 s | <= 0.002 s | |

Nothing else in `on_done` exceeds 50 ms (the 50 ms+ cProfile rows are all inside `slice_at`: `finish_slice` 1.3 s, `gather_footprint` 0.76 s, `interpolate.apply` 0.9 s
and `stream_slice` 0.86 s, which include the worker's concurrent stretch calls, so they overlap the table above and are not additive).
cProfile attributed 1.23 s to `_gather` against 1.85 s from the wrapper in the same run; the wrapper figure is the one used, the gap is not explained.
The stretch landing callback itself is 0.043 s.

Reading: of the 2.56 s landing, about 1.85 s is the one-off footprint build for the new lattice, and about 0.6-0.7 s is what every tick costs
(`compose_footprints` 0.3 s, finish 0.17 s, slicing 0.1 s, layer 0.04 s). So every slider tick at 0.02 m also blocks the GUI for ~0.6 s.

### This grid, Grid1 (min_curvature -> kriging preview, then refine)

| part | landing draw (`dock.refresh_slice` via on_done) | later tick, same cell (0.23 / 0.26 / 0.22 / 0.29 s total) | first-draw only? |
|---|---|---|---|
| `dock.refresh_slice` total | 0.92 s | 0.22-0.29 s | |
| `layer.update` (= `plugin._on_slice_changed`) | 0.55 s | 0.04 s | |
| of which first `to_north_up` (resample plan build + apply) | 0.53 s | 0.03 s | the plan build is first-draw only (cached) |
| of which `layer.update_north_up` (file write, repoint) | 0.013 s | 0.008 s | every tick |
| `dock._finished` (the preview: `SliceEngine.preview` 0.33 s) | 0.33 s | 0.17-0.19 s (preview 0.19 or `finish` 0.16) | every tick; landing is ~0.15 s dearer |
| `SliceEngine.slice_at` | 0.04 s | 0.02-0.07 s | every tick |
| `display_limit`, readout, status, `show_refine` | ~0 | ~0 | |

cProfile's >50 ms rows for the landing also show the stretch job's own `stretch_jobs` calls (worker thread, overlapping); nothing else on the GUI thread
exceeds 50 ms beyond the rows above. Grid1's landing stretch callbacks: 0.055 s (preview, non-final) and 0.049 s (final).

Reading: of Grid1's 0.92 s, about 0.5 s is the one-off north-up plan, and the remaining ~0.25-0.4 s is the per-tick cost (preview 0.2-0.3, slicing, file write).
Scratch worktree removed afterwards.

## After Task 6

Branch head f09a418; the same two probes at 0.02 m on the Sunnyside copy, one run each (split probe now also logs the thread of every
`site_geometry.gather_footprint` and `nsgeo.slices.display._build_north_up_plan` call: `test_zz_measure_split_t6.py.keep`).
Load (1-min) at the start: after-probe Whole site 0.33, Grid1 1.09; split-probe Whole site 1.14, Grid1 1.23. All under 3.

| scope | largest gap | p99 gap | landing `on_done` | edit -> picture | edit -> stretch | peak RSS |
|---|---|---|---|---|---|---|
| Whole site | 0.651 s (at 91.8 s, the landing draw) | 0.011 s | 0.797 s (split probe; the after probe's gap 0.651 s) | 92.5 s | 95.0 s | 2.04 GB |
| Grid1 | 0.449 s (at 21.9 s, the landing draw) | 0.011 s | 0.439 s | 22.2 s | 24.7 s (preview) / 57.7 s (final, after the refine rest) | 1.00 GB |

Other gaps over 0.1 s: Whole site 0.115 s and 0.349 s at the edit (debounce firing). Grid1: 0.134 s and 0.268 s at the edit, 0.32 s at 22.4 s,
0.32 s at 27.3 s and 0.285 s at 55.9 s (later stretch/refine landings). Nothing else above 15 ms.

Landing split (GUI thread, inclusive):

| part | Whole site before Task 6 -> now | Grid1 before -> now |
|---|---|---|
| on_done total | 2.56 s -> 0.80 s | 0.92 s -> 0.44 s |
| `SiteEngine._gather` | 1.85 s -> 0.000 s (20 calls, all cached) | n/a |
| first `to_north_up` (`layer.to_north_up`) | n/a | 0.53 s -> 0.055 s |
| `compose_footprints` | 0.34 s -> 0.38 s | n/a |
| `_shown` (normalise + finish) | 0.20 s -> 0.25 s | n/a |
| `_sliced` | 0.12 s -> 0.13 s | n/a |
| `_finished` preview (`SliceEngine.preview`) | n/a | 0.33 s -> 0.33 s |
| map layer (`_on_slice_changed`) | 0.036 s -> 0.037 s | 0.55 s -> 0.065 s |
| `display_limit` | 0.001 s | 0 |

Later ticks at the same cell in the same runs: Whole site 0.65 / 0.58 / 0.60 / 0.58 s; Grid1 0.28 / 0.26 / 0.23 / 0.23 s.

Thread check (65 `gather_footprint` calls in the Whole site run, 2 `_build_north_up_plan` calls in the Grid1 run): every call ran on the worker thread
`nsgeo-fill_0`; none ran on the MainThread and none ran while `on_done` was executing. The footprints were built by the fill job near the end of the fill phase
(the last grids' gathers at 89.9-91.8 s, up to 0.65 s each, off the GUI thread); Grid1's plan took 0.36 s on the worker at 21.3 s.

Verdict: yes. The landing pause is now about one per-tick draw (Whole site 0.65 s gap / 0.80 s measured with profiling on, against a 0.58-0.65 s tick;
Grid1 0.44-0.45 s against a 0.23-0.28 s tick, the extra ~0.2 s being the preview solve with the stretch job running concurrently).
