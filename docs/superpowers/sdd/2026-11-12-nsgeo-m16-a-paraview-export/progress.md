# SDD ledger — plan: docs/superpowers/plans/2026-11-12-nsgeo-m16-a-paraview-export.md

Spec: docs/superpowers/specs/2026-11-11-nsgeo-m16-3d-design.md (reachable, binding).
Branch nsgeo-m16, worktree .worktrees/nsgeo-m16. Branch base 414b6aa (origin/main at start).
Execution: subagent-driven (user: "build it", after I recommended subagent-driven).
Models: implementers sonnet; task reviews opus; quick fixes haiku; final review opus.

## Coordinator setup
- Real data symlinked file by file into packages/nsgeo-core/tests/data/local (+ with-dzg/). Git status clean.
- Baseline: core 1031 passed 4 skipped (41 s); pure 251 passed 1 skipped; QGIS 1734 passed (14 min)
- NSGEO_PVPYTHON=/home/jameszd/Documents/Software/ParaView-6.2.1-MPI-Linux-Python3.12-x86_64/bin/pvpython

## Pre-flight scan

| Pair / task | Produces vs consumes | Found |
|---|---|---|
| T1 -> T3 | fill_levels, prepare_volume, VolumeSettings, VolumeStopped, PreparedVolume.slab/depths_m/trend/covered | Consistent. slab is shallow-first; T3 writes deepest first, flipping each slab. Each array callable recomputes slabs (2-3x the "few seconds"): acceptable. |
| T1 -> T3 (settings) | VolumeSettings.to_dict keys vs _clean_volume keys | period_ns/blur_m/trend_m match. VolumeChoice.to_record keys must equal exactly the 7 keys _clean_volume keeps, or a save drops them. Carried in T3 dispatch. |
| T2 -> T3 | write_image_data, write_poly_data, image_data_bytes, write_scene_files(folder, record, paraview_path), scene_record | CONFLICT: run(grid_id, choice, *, progress) has no paraview path to pass to write_scene_files. Ruling R1. |
| T2 -> T3 (picks array) | spec §5.2: picks.vtp has true_depth_m, line, feature; plan T3 says true_depth_m, line_index | CONFLICT with spec. Ruling R2. |
| T3 -> T4 | ParaViewExport.defaults/estimate/run, VolumeChoice, export_size_bytes, paraview_folder, ParaViewExportCancelled | CONFLICT: dialog gets size_for -> int only, so it cannot know the frame exceeds MAX_FRAME_CELLS. Ruling R3. |
| T3 -> T4 (progress) | _export_progress callback(done, of) resets its maximum on each call | Consistent: run may change `of` (cache hit skips fill levels). |
| T3 estimate vs spec §9.7 | "stated size matches what it writes" | No test pins estimate vs written size. Ruling R4. |
| T1 depth_axis (layered) | plan: "uniform depths", step unspecified | Gap. Ruling R5. |
| T3 / T4 share slices_plan.py | T3 adds VolumeChoice/volume_choice/export_size_bytes; T4 adds (R3) too-fine message | Sequential, no clash. |
| T3 -> T5 | spike "uses the export from Task 3" | Spike only needs Grid 1's fill at 0.05 m / 0.1 ns, which the trial already holds. Ruling R6. |
| T4 step 1 / T5 step 3 | human checkpoints | Tracked. Mockup produced early so the verdict arrives before T4. |
| T1 self | tests vs code | Consistent (src[0]==5 checked by hand: t=-0.476+0.5=0.024 is the first t>=0). "idw" is a valid METHOD. |
| T2 self | tests vs files | Consistent. Templates .txt, zip ships .txt. |
| T3 self | tests vs code | Consistent after R1-R4. Merge origin/main before T3 (plan global constraint). |
| T4 self | tests vs code | Consistent after R3. Message text for "how to open" lives in paraview_scene.py (plugin boundary). |

## Rulings
- Ruling R1: `ParaViewExport.run(grid_id, choice, *, progress, paraview_path: str = "")`, passed to write_scene_files; T4 passes the dialog's path — the plan's run() signature has no path but open.sh needs one — cost if wrong: one keyword argument.
- Ruling R2: picks.vtp's line array is named `line` (int index into the grid's sorted line keys), per spec §5.2; no `feature` array until Plan B — spec is binding over the plan's `line_index` — cost if wrong: a rename.
- Ruling R3: `ParaViewExport.estimate` raises ValueError when the frame exceeds MAX_FRAME_CELLS; its text comes from a new `slices_plan.too_fine_for_export(cell, grid_id, cells, safe) -> str` containing "too fine" and the safe cell; the dialog shows it in size_label and disables Export; run() raises the same before anything is written — the dialog's size_for returns only an int — cost if wrong: small refactor of the dialog's check.
- Ruling R4: test_export_writes_the_folder_ParaView_opens also asserts estimate(grid, choice) is within 5% of cube.vti's size; estimate must not prepare lines (dock engine's prepared_z_bounds when its source matches, else the lines' header time ranges) — spec §9.7 "its stated size matches what it writes" — cost if wrong: a loosened tolerance.
- Ruling R5: depth_axis keeps the number of source levels with t >= 0 and spreads them evenly from the first such level's depth to the last level's depth; a constant velocity gives integer source positions (snapped within 1e-6) — keeps the file size equal to the estimate and Grid 1 unresampled — cost if wrong: layered grids get a slightly coarser or finer depth step than the shallowest layer.
- Ruling R6: the T5 spike runs on the trial's own Grid 1 cube and fill (~/nsgeo-m4-check/m16-paraview-trial: high_quality_cube_grid_1.npz, filled_hq.npy, envelope recipe) in parallel with T1-T3, outside the repo — it is the same 0.05 m / 0.1 ns data the export would produce, and running it early gets the user's verdict sooner — cost if wrong: its prepared volume could differ slightly from the export's; the verdict is by eye.

## Tasks
Task 1: dispatched (BASE b103bbc, implementer aa9be720a6aa80919, sonnet)
Task 4 step 1 (human checkpoint): mockup .lavish/paraview-dialog.html (worktree, git-ignored) opened 2026-11-12; options A compact / B grouped; asks size line (export + kept fill + free space vs export only). First poll: browser_disconnected, no feedback. Verdict PENDING.
Task 5 (spike, R6): dispatched early in parallel (sonnet, a56a3dd3c76e17738), outputs in ~/nsgeo-m4-check/m16-paraview-trial/fill3d/. Verdict PENDING.
Task 1: implementer DONE 8dd5406 (core 1044 passed; real strength medians 0.884-1.080); review dispatched (opus a18f41e57c552ae54) on review-b103bbc..8dd5406.diff
Task 5 spike: DONE. fill3d/compare-{1-iso,2-depth-slice,3-across}.png + REPORT.md. Bodies at iso 2.5 in bowl box 23 -> 15 (mostly debris); >=1% bodies 8 vs 9; largest share 74% -> 79%; dip fill ~13 s vs ~154 s. My read of the renders: smoother flanks and no striping, but lower contrast in the depth slice and the real lumps remain; shifts near +-1.7 ns may cycle-skip. Sent to user; verdict PENDING.
Task 1: review: Needs fixes. Important: (1) RMS level-by-level ~7x slower than a bit-identical shifted-sum (40-50 s vs 6-8 s per pass); (2) plan-mandated: spec §9.1 real-data tests (unipolar, one hump, uncovered NaN, slabs==whole) left synthetic.
- Ruling R7: spec §9.1 binds over the brief — add the four real-data tests on CAMPUS_LINES (GPS_LINES too if cheap); the hump test must use lines NOT through amp_envelope (amp_square or bipolar), else it is vacuous — cost if wrong: a slower core suite.
- Ruling R8: prepare_volume gains `progress: Callable[[int, int], bool] | None = None`, called once per slab of its trend pass; False raises VolumeStopped — spec anti-goal "Freezing QGIS while preparing or exporting" and the export runs on the GUI thread, so an uncounted trend pass freezes QGIS — cost if wrong: one unused keyword. Task 3 must count it in run()'s progress.
Task 1: minor (deferred): balance arithmetic (window length, padding, NaN where trend<=0) has no direct test.
Task 1: minor (deferred): prepare_volume with t0 < 0 untested end to end.
Task 1: minor (deferred): PreparedVolume frozen dataclass with ndarray fields keeps eq=True (== raises); use eq=False.
Task 1: minor (deferred): even windows (trend tw=42, RMS w=12 at 0.2165 ns) are off-centre by half a level (~0.2 cm).
Task 1: minor (deferred): test nits — leftover print (test:170), local import (test:89), redundant out[:, :2, :] (test:78).
Task 1: fix round 1/5 (3 addressed, 0 open — RMS shifted-sum bit-identical, prepare_volume 19.3 s -> 12.0 s on 455x320x400 (blur now the larger share); real-data tests unipolar/NaN/hump/slabs on CAMPUS amp_square; R8 progress; commits 8dd5406..ff33329)
Task 1: minor (deferred): hump test shares a module-level _SQUARED cache and prints counts.
Task 1: complete (commits b103bbc..ff33329, review clean)
- Ruling R9: export.json `slices` = {"depth_m", "x_m", "y_m", "lines_along": "x"|"y"}; the scene's "Slice along a line" plane contains the line direction (normal across the lines) and "Slice across the lines" has its normal along them — a grid's lines may run along grid X or Y, and the plan's "depth, x, y" can't orient the two vertical slices — cost if wrong: one key.
Task 2: dispatched (BASE ff33329, implementer ad00c8cac78de662d, sonnet; R2 R9 carried)
Task 2: implementer DONE bd5122c (core 1056, pure 257, pvpython scene test passes, screenshot ok); no RED run recorded; review dispatched (opus a03c2c4c32e4ced37)
Task 2: review Approved (reviewer independently read every writer output back with real VTK in pvpython 6.2.1; scene visibility/LUTs/clip/slices checked).
Task 2: minor (deferred): zero picks -> ColorBy on empty picks.vtp logs "Could not determine array range" WARN (may pop Output Messages in GUI) — check in walkthrough.
Task 2: minor (deferred): pvpython test asserts only rc 0 + no Traceback; add "ERR|" not in stderr and "open_scene:" not in stdout.
Task 2: minor (deferred): write_poly_data has no points.shape[-1]==3 check nor connectivity < n_points check.
Task 2: minor (deferred): big-endian arrays rejected; newbyteorder line is a no-op.
Task 2: minor (deferred): array names unescaped in XML header.
Task 2: minor (deferred): scene_record doesn't json.dumps-check, so numpy scalars fail only in write_scene_files after the cube is written (heads-up carried to Task 3).
Task 2: minor (deferred): open.bat keeps its console open (use start "").
Task 2: minor (deferred): quote or $ in the ParaView path breaks open.sh.
Task 2: minor (deferred): process — no RED run recorded.
Task 2: complete (commits ff33329..bd5122c, review clean)
Merged origin/main (0259444, #159) before Task 3 as the plan requires: 3d61005; README roadmap conflict resolved (M16 item 2; Plan A in progress). Core 1110 passed (after linking tests/data/local/grid2), pure 272, ruff clean. Pushed.
Task 3: dispatched (BASE 3d61005, implementer a01f3e15a7173f808, sonnet; R1 R2 R3 R4 R8 R9 + numpy-scalar heads-up carried)
- Ruling R10: M15 (#172) merged to main as b0d724a while Task 3 was already running on 3d61005 (pre-M15). Merge origin/main again after Task 3's review is clean and before dispatching Task 4 (which edits slices_dock.py and plugin.py, both heavily changed by M15); re-run Task 3's test files on the merged tree — changing the tree under a running implementer is worse — cost if wrong: conflict resolution in session.py/project.py/slices_plan.py after Task 3.
Task 5 (human checkpoint) verdict 2026-11-12: user — NOT adopted; filed #174 at the user's word ("file the issue"). Mockup re-sent on request (lavish reopened, poll bzeygk3bh).
Task 4 step 1 (human checkpoint) verdict 2026-11-12: user chose layout B (grouped: "3-D resolution (this grid's own)", "The volume", "What will be written") and the size line with export + kept fill + free space. User asked "What is depth trend?" → relabelled "Depth balance" with hint "strength = each value ÷ what is typical at its depth, averaged over this much depth" (answered in Lavish). Mockup fixed (a stray header from the old fine-cells mockup had been copied in).
- Ruling R11: Task 4's dialog takes `summary_for: Callable[[str, VolumeChoice], ExportSummary]` instead of `size_for`; Task 4 adds `ParaViewExport.summary(grid_id, choice) -> ExportSummary` (folder, nx, ny, nd, max_depth_m, fill method, n_picks, n_lines, export_bytes, cache_bytes = 0 when this key's fill cache already exists, free_bytes from shutil.disk_usage), raising the R3 ValueError when too fine; the summary's wording is a pure function in paraview_scene.py — layout B shows "what will be written", which an int can't carry — cost if wrong: a dialog refactor.
Task 4 note: user asked whether depth balance is on top of gain curves (yes: preset stack incl. gain, then transform, then balance). The guide step should say so, and suggest comparing a lighter-gain preset when calibrating.
Task 3: implementer DONE 742e5e7 (core 1125, pure 279, QGIS export 9 + engine 79 + dock 165); concerns: QGIS/pure RED not captured; estimate probes one file for time_zero; cache can't see raw DZT edits outside nsgeo; run() spins a nested event loop when it prepares lines
Task 3: review Needs fixes. Important: (1) two tests (second-preparation refusal, too-fine refusal) error on CI: the fixture indexes REAL_DZT without needs_real_data; (2) the never-two-preparations guard is checked once, then run() waits in an AllEvents nested loop that neither dock engine nor the site engine can see -> a source change, a second click or the site engine's 50 ms retry can start a second preparation (segfault); (3) disk use beyond the stated size: permanent fill cache (plan-mandated), an amplitude.tmp scratch the implementer added, .partial beside the old export.
Merged origin/main again (R10; M15 b0d724a) at 64002c1 BEFORE the fix round, since the fix touches slices_dock.py/site_engine.py: conflicts only sorted name lists + roadmap. Core 1224 passed, pure 279, ruff/format/mypy clean, export tests 9 passed on the merge; full QGIS suite running on 64002c1.
- Ruling R12 (fix for Important 2): the export registers its standalone engine with the dock for the whole preparation — a `dock.foreign_preparation(engine)` context manager (name is the implementer's) that adds it to the site engine's exclusive peers (make `_exclusive_with` extendable: add/remove) and to the grid engine's prepare gate (treated like `site_engine.has_live_task`: set pending + retry timer); on exit it is removed and pending work resumes through the existing retry timers. The export's entry check also refuses while `site_engine.is_running` (queued grids) — and waits with ExcludeUserInputEvents — the guard must hold for the whole wait, not just at entry — cost if wrong: touches two engine gates; a deadlock risk the tests must rule out.
- Ruling R13: Minor 1 (the cancel test never cancels while writing, so its "no *.partial" assertion is vacuous) is a confirmed gap against the plan's Review Focus 3 (cancelling halfway), so it enters the fix loop: add a cancel in the write pass — cost if wrong: one more test.
- Ruling R14 (fix for Important 3): drop the amplitude.tmp scratch — recompute the amplitude per slab in the write pass (steps 2-6 are seconds; p99 comes from that pass); the kept fill cache stays (plan + user: quick re-exports) and its size is stated by Task 4's summary (R11, the user chose "export, kept fill and free space"); Task 4 also warns when free space < export + new cache — cost if wrong: one more ~12 s slab pass per export.
Task 3: minor (deferred): VolumeStopped branch (:328) skips the .npy.part cleanup in except BaseException.
Task 3: minor (deferred): cache cleanup glob f"{safe}-*.npy" also deletes grid "A-1"'s cache when exporting "A"; match the fixed 16-hex key; stale .npy.part from a crash never removed; _safe maps "Grid A" and "Grid_A" to one folder (plan-mandated).
Task 3: minor (deferred): no recovery after a crash between the two renames in _swap (restore .old when <grid> is missing).
Task 3: minor (deferred): picks on grid lines outside the prepared set are dropped silently; export.json has no skipped count.
Task 3: minor (deferred): Windows: a cancel during the first fill may keep the memmap open so cache_part.unlink raises PermissionError.
Task 3: minor (deferred): _bounds duplicates SliceEngine.prepared_z_bounds (DRY).
Task 3: minor (deferred): _clean_volume keeps any transform string (no validation, unlike _clean_resolution).
Task 3: minor (deferred): folder test doesn't assert the cube's level count for choice.dz_ns exactly.
Task 3: minor (deferred): estimate's header/probe path has no test; the probe reads profiles[session.channel(key)] while the engine prepares profiles[0].
Task 3: note: estimate reads one whole line file for a time_zero preset (R4 asked headers only) — accepted: prepares nothing, more accurate.
Task 3: fix round 1 implementer DONE 4e2dc53 (QGIS 509 incl. export 12; REAL_DZT emptied: refusals pass, rest skip; hold test mutation-checked); concern: cache_bytes treats any same-shape grid cache as a hit when the panel doesn't match; re-review dispatched (opus a70da82915a212838)
Task 3: fix round 1/5 (4 addressed, 1 new open — Important: cache_bytes reports 0 for any same-shape cache when the panel doesn't match, so a transform change writes a full new cache beside the old (peak old+new, SIGBUS risk on a full disk); commits 64002c1..4e2dc53)
- Ruling R15: the re-review's Minor 2 (foreign registration lifted while the export's engine still has a live task after dispose's bounded wait gives up -> second preparation 50 ms later) and Minor 3 (nothing tests the export's own wiring: foreign_preparation use, ExcludeUserInputEvents, site_engine.is_running refusal) and Minor 4's dispose-in-finally are the global never-two-preparations constraint's guard, so they enter the loop with Important 1 — cost if wrong: one more small round.
Task 3: minor (deferred): hold test's running["now"] never decremented ("max" counts starts); cancel-test comment says "last slab" for the second-to-last tick.
Task 3: note for Task 4: line preparation inside run() can block up to 600 s with user input excluded and no progress calls — show the progress dialog at once with a "Preparing lines" label; Cancel can't be heard in that phase.
Task 3: minor (deferred): grid engine self re-preparation in _on_grids_changed/_on_lines_changed doesn't check _foreign_live (unreachable today: user actions only, input excluded).
Full QGIS suite on merge 64002c1: 1936 passed (22.5 min, under load from a concurrent implementer).
Task 3: fix round 2 implementer DONE 94e3a2f (QGIS 513 incl. export 16; six mutations killed)
Task 3: fix round 2/5 (3 addressed, 1 open — cache_bytes still states 0 after an nsgeo version bump: settings key lacks the version the full key has; commits 4e2dc53..94e3a2f)
- Ruling R16: the re-review's out-of-scope Important (a second export can start a preparation while the first export's engine is still live after a timeout: _prepared's refusal checks dock.engine/site_engine has_live_task + is_running, none of which sees foreign engines; reproduced) enters the loop — it is the global never-two-preparations constraint on the path this fix built — cost if wrong: none beyond one more check + test.
Task 3: minor (deferred): a line label rename refills the cache (repr(placement) includes label; strip it as SliceEngine._without_label does).
Task 3: minor (deferred): dispose_site stops _grid_retry but not _foreign_reaper (harmless; polls 50 ms until dock deletion with a stuck engine).
Task 3: minor (deferred): crash/SIGBUS leftovers <name>.npy.part are never cleaned (regex matches only .npy) — a full-size sparse file stays on a near-full disk.
Task 3: fix round 3 implementer DONE 903ba4b (export 18; both mutations killed)
Task 3: fix round 3/5 (2 addressed, 0 open — version in settings key; foreign_preparing refusal; commits 94e3a2f..903ba4b)
Task 3: complete (commits 3d61005..903ba4b, review clean; merge 64002c1 inside the range)
Task 4: dispatched (BASE 903ba4b; layout B per the user's verdict; R3 R11 R14 + the prepare-phase and gain notes carried)
Task 4: implementer a3bded68532d61c63 (sonnet)
Task 4: implementer DONE_WITH_CONCERNS 5545be2 (pure+core 1508, QGIS 218 incl. 17 dialog tests); fixed a Task 3 bug: defaults() read transform_combo.currentText() (a title) -> .value(); push failed: DNS down (github.com unresolvable), push pending
Task 4: pushed 5545be2 (DNS back); review dispatched (opus acf4a95e86cc90268)
Task 4: review Needs fixes. Critical: Transform None -> choice() returns "none" (expects NO_TRANSFORM ""), export fails "unknown step 'none'" and the grid's volume record is poisoned; _load_grid set_value("") fails silently so switching grids keeps the old transform. Important: Enter in a spin box (keyboard tracking off) clicks the default "Export and open" before the new size is seen (spec anti-goal: size stated first).
Task 4: minor (deferred): hints_for sits before parent (make extras keyword-only).
Task 4: minor (deferred): every keystroke in the ParaView path recomputes the whole summary (only _set_buttons needed).
Task 4: minor (deferred): "Slices panel: not set" when no resolution is remembered, though the panel shows default_cell(...).
Task 4: minor (deferred): depth step spin has 4 decimals: native 0.216531 ns becomes 0.2165, remembered, and the volume is resampled off-native.
Task 4: minor (deferred): macOS Browse returns X.app (a directory) which launch_paraview refuses; open.sh would exec the bundle.
Task 4: minor (deferred): guide omits wave period from what re-exports quickly.
Task 4: minor (deferred): some message wording still inline in plugin.py (:1245, :1272, :1302).
Task 4: minor (deferred): test looseness — startswith(A) or startswith(B); no committed test that the real dock's state is unchanged by an export; progress-label test never exercises the real preparing phase.
Task 4: minor (deferred): Fill row shows only the method label (verdict allows).
Task 4: note: screenshot predates the committed .4g dt hint.
Task 4: fix round 1 implementer DONE 9a5854e (dialog 23, export/loads/dock 201, pure 285, core 1224)
Task 4: fix round 1/5 (2 addressed, 0 open — None transform maps via transform_value + heals stored 'none'; Return in spins/path swallowed; commits 5545be2..9a5854e)
Task 4: complete (commits 903ba4b..9a5854e, review clean)
Task 5: complete (spike outside the repo; user verdict: not adopted; #174 filed)
Task 6: started — full suites + pvpython + zip, then final review (opus)
Merged origin/main again before Task 6 (#175 fine-cell export, #181 fit marks): 51d8f3f, pushed. #175 removed plugin._export_progress, QProgressDialog/busy_cursor imports and SlicesDock.refining_paused (GeoTIFF exports went to a background task); the ParaView export used them, so 9 dialog tests failed after the merge (AttributeError swallowed into "could not export").
- Ruling R17: restore `_export_progress` (plugin.py) and `refining_paused` (slices_dock.py) as the ParaView export's own, rather than move the ParaView export onto #175's background ExportTask — plan A chose synchronous-behind-modal-progress to keep its preparation on the GUI thread's guard; a background move is a design change — cost if wrong: two small helpers duplicated in spirit with #175's flow; revisit if the walkthrough finds the modal export clumsy. ParaView tests 59 passed after.
Final review question: may a ParaView export run while #175's background GeoTIFF export (running_export) is in flight? It prepares no lines (no set_source), so no segfault rule; memory contention only.
Task 6 step 1: core 1226 passed 4 skipped; pure 321 passed 1 skipped (pvpython scene test ran with NSGEO_PVPYTHON); mypy clean; ruff clean; zip nsgeo_qgis-0.4.0.zip ships volume.py, vtkxml.py, paraview/*.txt, paraview_export/scene/dialog. Full QGIS running (b79q0wtt1). Final review dispatched (opus a59052178dc79ca28) on review-724cb0a..51d8f3f.diff
Task 6 step 3: profile ns_geo_m16 = cp -a ns_geo + dev_link to this worktree; offscreen probe: plugin loads from the profile link, core from the worktree, paraview_button + export_paraview present; profiles.ini lastProfile untouched (ns_geo_velocity_fixes). Walk copy ~/nsgeo-m16-walk/Sunnyside (survey.nsgeo.json + gpkg via sqlite backup; schema 2; Grid1 164 picks, Grid2 none; Grid1 remembers cell 0.05, dz 0.1, min_curvature).
Task 6 step 4: walkthrough page drafted (scratchpad walk/paraview-walkthrough.html; 14 checks D1-D3 X1-X2 P1-P5 R1-R4); publish after the final review's fixes with the final head.
Final review (opus): Ready for the walkthrough: Yes; before merge fix Important 1-3, Minor 4, guide wave period. Measured: Grid2-size IDW export 29 s / 1.1 GB peak; Grid1-size min-curv 229 s / 1.2 GB peak (under load); estimate within 0.2%; cancel heard within ~3 s.
- Important 1: full disk can SIGBUS QGIS while the sparse memmapped fill cache is written; R14's warn-only is wrong for the cache -> refuse in run() before the memmap when free < cache bytes + margin.
- Important 2: Windows: ParaView launched with cwd = export folder (and open.bat cd's there) blocks _swap's rename -> raw WinError 32 on re-export while ParaView is open.
- Important 3: Windows: cancel during the first fill -> cache_part.unlink PermissionError replaces the cancel and leaves a ~230 MB .npy.part (deferred Task 3 minor promoted); clean stale .npy.part at run start.
- Minors 4-11: stale _export_progress docstring; partly failed preparation drops lines silently; no refusal while a #175 GeoTIFF export runs; Whole site scope always re-prepares (follow-up); summary() rescans every pick per edit; guard tests need real data so CI skips them; peak memory not recorded (walkthrough); fill caches add up (follow-up).
- Rulings: R14 half wrong (cache needs a refusal); R17 acceptable, but the fill/write could move to a QgsTask later (follow-up; walkthrough judges); R1-R13, R15, R16 right. ParaView + #175 GeoTIFF export at once: safe (GeoTIFF first only), contention only.
Final fix wave dispatched (one implementer, sonnet): Important 1-3, Minor 4, 5, 6, 8, 9, guide wave period, zero-picks ColorBy WARN, open.bat start "". Deferred to follow-ups: Minor 7, 10 (walkthrough records), 11, R17 QgsTask, and the remaining can-wait minors.
Full QGIS suite on 51d8f3f: 2294 passed, 1 FAILED test_plugin_paraview_dialog.py::test_with_no_paraview_path_it_writes_and_says_how_to_open (passes alone; full run overlapped the fix-wave implementer, which may have edited templates read at run time; output truncated) — rerun the full suite after the fix wave with full output; if it reproduces it is order-dependent and goes into the loop.
Final fix wave DONE 4a04ee4 (core 1226, pure 326 w/ pvpython, QGIS 370; 15 mutants killed). Concern confirmed by controller: test_plugin_paraview_dialog.py run ALONE segfaults at interpreter shutdown (rc 139) after all tests pass; export and loads files alone exit 0; CI runs packages/nsgeo-qgis/tests in one process.
Scoped re-review of the fix wave dispatched (opus ac5315bde7bd3a9ad), incl. the shutdown segfault diagnosis; full plugin test tree (as CI: packages/nsgeo-qgis/tests) running on 4a04ee4 with full output in scratchpad qgis-full-4a04ee4.txt
Final fix wave re-review (opus): all 10 findings ADDRESSED (4a04ee4); clear_frames verified to unmap the .part; pvpython zero-picks mutation-checked; guard tests run on synth_site (13 passed, none skipped).
Shutdown segfault diagnosed: tests only — parentless ParaViewExportDialog from _make_dialog sits in a gc cycle (8 self-capturing lambdas) and is collected by pytest_unconfigure's gc after exitQgis; fix = gc.collect() in tests/qgis/conftest.py qgis_app between yield and exitQgis (verified in scratch). CI risk low (one process), not zero.
- Ruling R18 (residuals, no second fix wave): park three for the walkthrough's fix round, before merge — (a) conftest gc.collect() (one line; stops the 139 when the dialog file runs alone), (b) open.bat `start "" /D "%HERE%.."` so a hand-launched ParaView doesn't hold the folder on Windows (today it fails gracefully with the "in use" message), (c) launch_failed_message wording with skipped lines — all small, none affects the Linux walkthrough — cost if wrong: they ride to merge unfixed if the walkthrough has no fix round; then a two-line follow-up commit.
Task 6: parked (deferred): the dialog doesn't see a stale .npy.part on a tight disk (run() sweeps it first); "an export is already running" text now inline 3x in plugin.py.
Task 6 step 4: walkthrough page published https://claude.ai/artifact/9FJsin3NSYnsugaQ2EMJkC (db results, 14 checks D1-D3 X1-X2 P1-P5 R1-R4; head 4a04ee4); results collection reads back empty as expected. AWAITING THE USER.
CI-style run (packages/nsgeo-qgis/tests, one process) on 4a04ee4: 2635 passed, 3 skipped, rc 0 (21.5 min). The earlier lone failure of test_with_no_paraview_path_it_writes_and_says_how_to_open did not recur (it overlapped the fix wave).

## Walkthrough fix round (2026-11-13)
- Walkthrough D1 found: the export ignores Grid1's z1 cutoff (t1_ns 40.0) and exports the whole record (1001 depths, 0 – 3.55 m, ~1.5 GB). User decided: give the export its own "Down to" (deepest time), remembered per grid, defaulting at first use from the panel's t1_ns (decision 8 pattern). Brief walk-fix-brief.md also carries R18 (a)–(c).
- Dispatched implementer sonnet (agent a0dc6c8c6d509856b), BASE 4a04ee4, report walk-fix-report.md. Next: scoped re-review (opus), CI-style QGIS run, update walkthrough page D1 (expect ~401 depths, 0 – 1.42 m, ~0.62 GB + ~0.21 GB fill), tell the user to restart QGIS.
- Walk fix: implementer DONE_WITH_CONCERNS, commits c3b33af (R18 a,b) + e037125 (Down to + R18c). Export+dialog QGIS files re-run after ruff format: 70 passed. Review (opus): spec ❌ — Important: choice() returns None at the spin max → remember_volume merge keeps a stale t1_ns / lets the panel's z1 leak in later (breaks decision 8); Minors: settings key on raw t1 (refill), misleading short-Down-to refusal, stale hint, hints before spins. Trailers say Sonnet 5.5 (subagent's own attribution; memory says no trailer mandate for subagents — accepted).
- Walk fix: fix round 1/5 sent (Important + 3 minors + optional 4th).
- Walk fix: fix round 1/5 (5 addressed, 0 open — choice() keeps the typed value, settings key on the effective end, short-Down-to refusal names the step, hint cleared, spins before hints; commits e037125..b8ec2ed; push done by controller after the subagent's DNS failure). Re-review (sonnet): all addressed.
- Walk fix: minor (deferred): QDoubleSpinBox rounds the record end to 4 decimals, so Down to at max can store e.g. 99.9765 < 99.97654 → non-None effective t1 → one refill vs a None export, and possibly the last level lost when the end sits on a depth step.
- Walk fix: minor (deferred): a stored number no longer follows a lengthened record (decision 8 behaviour; the field shows it) — mention in the guide if the user wants.
- Walk fix: complete (commits 4a04ee4..b8ec2ed, review clean). Walkthrough page updated (D1, D2, R3, intro; head b8ec2ed).
- Walk fix: whole QGIS suite on b8ec2ed (one process, CI-style): 2654 passed, 3 skipped, 1 warning in 1457.80s (0:24:17)
