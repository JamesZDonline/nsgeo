# Re-review: walkthrough fix round 2, milestone B (#108), d2b8ba2..50935c0

Reviewer: Claude Opus 5.5. Scoped re-review: are the findings of `walkthrough-fix-review.md`
addressed as R26–R31 ruled, and did the fixes break anything? Read-only: nothing in the worktree
was edited, created or deleted apart from this file (`git status` clean before and after).
Scratch work is under
`/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/0356759e-44aa-46ca-bfe2-a82acefa658a/scratchpad/rereview-2/`:
`sweep.py`, `variants.py` and `lead_sweep.py` (frame rule), `tests/` (scratch pytest files that load
the worktree's conftests read-only), and `app/probe.py` (run inside the real QGIS 3.44.7 app,
`qgis --profiles-path <scratch>/profiles --profile probe --noplugins --code probe.py`, offscreen,
`PYTHONPATH` to the worktree).

Counts for this round: **new Critical 0 · new Important 0 · new Minor 3** (plus 4 nits).

## Tests run

- pure + core: **1265 passed, 5 skipped** (local pytest 9.1.1).
- `test_pure_export_pipeline.py` under pytest **9.2.0** (the implementer's throwaway venv
  `scratchpad/p92/v`): **23 passed**.
- QGIS targeted (band-times-on-add, temporal navigation, slice export, export task, the two export
  dialog files, site scope, plugin loads, layers): **609 passed** in 7 min 47 s (QGIS 3.44.7,
offscreen). The one warning is GDAL's FutureWarning about `UseExceptions`, raised by the hook's
first `gdal.Open` in the test process. It does not appear inside QGIS (see below).
- CI at 50935c0 (run 43157951454): every job green, including `plugin-qgis (qgis/qgis:3.44)`,
  `plugin-qgis (qgis/qgis:4.2)` and the pure jobs on 3.9/3.12/3.13 on all three OSes. Per the report,
  the 3.44 job passed on a re-run after an unrelated timing test (`test_plugin_refine.py`, the
  #165/#166 family) failed once; the failure was "the solve is too quick", which the hook cannot cause.
- Site names: none in the diff or in the five commit messages; no local paths. Each commit ends
  with the `Co-Authored-By: Claude Opus 5.5` line.

## Status of each finding

| Finding | Status | Evidence |
|---|---|---|
| I1 min-gap frame drifts | **ADDRESSED** | Mean step `(last − first)/(n − 1)` ms, 2 ms lead, end `start + floor(n·F) − 1` (`slice_export.py:670-686`). The 180-case test sweep passes; my own 4,935-case sweep (n 1–2000, dz 0.004–1.2 ns, t0 −30…30, one-level thick to 20 levels) has **0 failures**; the old rule fails 52/180 of the test sweep. |
| I2 reopen not set up / false claim | **ADDRESSED** | The hook rewires band times from `NSGEO_WINDOW_NS` on every add, and `readProject` → `QTimer.singleShot(0, …)` refits. Re-verified in the real app through `iface.addProject` (QgisApp's own open path, which the implementer's probe did not use): Animated, 200 frames → bands 1..200, panel's Animated button checked, project not marked modified. The claim is gone from the docstring; the project time setters are dropped. (The test does not pin the refit: N1.) |
| I3 guide's hand set-up impossible | **ADDRESSED** | The by-hand sentence is gone; with nsgeo the file is timed on add; without it the guide points to the Symbology band choice (`getting-started.md:550-565`). (N2, N3 on wording.) |
| M1 single zero-length band | **ADDRESSED** | One band: its length floored at 1 s; `test_a_single_zero_length_band_still_gets_a_frame` gives 1 frame → band 1. |
| M2 name rule beats a values file | **ADDRESSED** | Name rule only without `NSGEO_INTERPOLATION`/`NSGEO_SITE_INTERPOLATION`, after the `largest_count` check (`slice_export.py:710-723`); new `full_coverage.tif` test; the old-companion test kept. |
| M3 wrong frame-count comment | **ADDRESSED** | Docstring now says `ceil(extent / frame)`; the "end at (n−1)·F" simplification it warned about fails 160/180 of the test sweep, so the sweep would catch it. |
| M4 guide: before-zero times, labels | **ADDRESSED** | "Times before 0 ns show as the last seconds of 31 December 1969, so −1.8 ns is 23:59:58"; the wrongly labelled hand set-up is gone, so no QGIS labels remain to get wrong. |
| M5 flag-order test cannot fail | **ADDRESSED** | `drop_stale_files` monkeypatched to raise; asserts `not ok and values_written`. The module-level name is what `ExportTask.run` calls after the flag (`export_task.py:209-211`), so swapping the two lines makes it fail. The companion-failure case stays covered at `test_plugin_export_task.py:285` and in the dialog tests. |
| Nit: bench `--export-smooth` docstring | **ADDRESSED** | "sets the export rows' smoothing". |
| Nit: no canvas | **ADDRESSED** | `canvas.temporalController() if canvas is not None else None`, so it skips quietly. |
| CI: pytest 9.2 nested `approx` | **ADDRESSED** | `_flat` compares sorted keys and then flat values; passes on 9.2.0 locally and in CI; no other nested-dict `approx` in the branch's tests (grepped `main...HEAD`). |

## The layersAdded hook and the readProject refit (R27)

**Raising out of a slot.** No. `_on_layers_added` wraps each layer in `try/except Exception`
and logs to "nsgeo" at Warning. `_refit_after_open` is wrapped the same way. `_on_project_read`
only schedules the timer, and `_forget_timed_layers` only clears a list. The except handler of
`_fit_temporal_controller` calls `layer.name()`, which could raise on a deleted layer, but
both callers catch that. The autouse escaped-exception guard in the QGIS conftest covers the new
tests.

**Unload and reload.** All three connections are dropped at the very top of `unload()`, before
anything that could raise, each under `suppress`. Verified:
- After `unload()`, a hand add is not timed (branch test).
- After `unload()`, a project read does not refit (my scratch `test_unload_disconnects_the_read_refit`).
- In the real app, unload, then a new instance's `initGui()`, then one add gives exactly **1**
  `restore_band_times` and **1** fit. Nothing is connected twice.

**The deferred refit when the project is cleared or the plugin unloaded first.**
- Project cleared first: `cleared` empties the list, and `mapLayer(id)` would return None
  anyway. In the real app: no fit, no log line.
- Plugin unloaded first: safe, with no exception. But the timer holds the bound method, so
  `_refit_after_open` still runs **once** on the unloaded instance and fits the controller
  (real app: mode Animated after unload, 1 fit). It is harmless, and it needs an unload in the
  same event-loop turn as a project read. Nit.

**Cost.** Measured in the real app, adding layers one by one:

| Layers added | With the hook | Without |
|---|---|---|
| 200 plain local single-band `.tif` | 22.3 s | 21.5 s |
| 20 nsgeo files of 460 bands | 0.45 s | 0.12 s |

- Plain `.tif`: about 4 ms each, against roughly 100 ms each for QGIS's own add.
- nsgeo files: about 16 ms each, for the GDAL read, 460 ranges and the fit.
- Remote, `/vsi…`, VRT, WMS/XYZ and other non-`gdal` providers make no GDAL call: at most one
  `stat`, with no network. Checked with `/vsimem/` and a missing `.tif` in scratch.
- On a slow network share, each local `.tif` still costs one extra GDAL open on the GUI thread,
  and that open includes GDAL's sibling-file directory listing. This is within R27's "one GDAL
  metadata read", so not a finding.

**Files it must leave alone.** In the real app, a project held:
- a non-nsgeo `.tif` the user had given its own band times (100–400 s);
- a counts file tagged `largest_count`;
- an nsgeo file.

After it was saved and reopened through `iface.addProject`:
- The non-nsgeo layer's band times were unchanged.
- The counts layer stayed untimed.
- The nsgeo layer was timed and fitted.

The branch tests also cover a file with no windows. Every non-nsgeo GeoTIFF is opened read-only
once and returns `"missing"` at band 1. `gdal.UseExceptions` is already set by QGIS (checked in
the app), so the GDAL FutureWarning seen in the test run does not show in QGIS.

**Overlap with the plugin's own export and restore paths.** No conflict.
- Export: the hook fits from the file, then the direct call fits from the plan. The file's
  windows are the plan's windows written with `repr` (`slice_export.py:601`,
  `site_export.py:390`), so the two fits are identical.
- Restore: two identical reads and fits. The "untimed" accounting stays on the direct path.
- Companions are tagged `largest_count`, so the hook skips them.
- The live slice preview `.tif` has no windows, so it costs one GDAL open when the preview layer
  is created; `_repoint`'s `setDataSource` never fires `layersAdded`.

**The frame rule against QGIS 3.44's ceil count.**
- Frame count: `ceil((floor(n·F) − 1)/F) = n` whenever F > 2 ms. A single band has F ≥ 1000 ms,
  so its count is 1.
- Frame to band: each ms-rounded begin lies within ±1 ms of `b0 + k·F_mean`. QGIS truncates frame
  times by up to 1 ms. With the 2 ms lead, frame k starts at or before `b_k − 1` and ends at or
  before `b_{k+1} − 1`. So band k is inside frame k, and band k+1 never reaches it, for F above
  about 4 ms.
- Measured with QGIS's own `totalFrameCount` and `bandForTemporalRange`: **0 failures in 4,935
  cases**, including dz 0.004 ns (4 ms steps), n = 2000, negative t0, single zero-length bands
  and single long bands.
- The 2 ms lead is a safety margin, not something the measurements need: leads of 0 and 1 ms also
  pass every case, both in the test sweep and in my 4,305-case sweep. So the tests do not pin the
  lead. Nit; nothing to do.

**What the tests pin, and what they do not.**

Pinned:
- A hand-added file is timed and fitted.
- A file with no windows, a counts file, a non-`.tif` file and a non-`gdal` provider are left alone.
- A failure is logged and the layer is still added.
- After unload, `layersAdded` no longer reacts.
- A reopened project's band times come back exact.
- The frame rule, through the 180-case sweep.

Not pinned:
- The refit after a read (N1).
- The `readProject` and `cleared` disconnects on unload.
- What the deferred timer does when the plugin is unloaded or the project cleared before it fires.

## New findings

### N1 (Minor). The reopen test cannot catch a missing refit
`packages/nsgeo-qgis/tests/qgis/test_plugin_band_times_on_add.py:116-132`

The test switches the controller off before `read()`. During the read, `layersAdded` fits it
again, so the test passes with the `readProject` connection removed. I checked this with the
branch test's body and the refit disconnected: it passed. The docstring says "fitted again after
the read, whatever it was set to in between", but nothing sets the controller between the read
and the timer, which is what QGIS's panel does (the real-app `probe_norefit.py`). So the one
mechanism that makes I2's reopen work in QGIS has no automated pin. A refactor that drops it
stays green. This is the same class as last round's M5.

**Fix (verified in scratch):** before the read, connect a slot to `readProject` that switches the
controller off. It is connected after the plugin's, as the panel is in the app. Then process
events and assert Animated, plus the frame-to-band list. My
`tests/test_rereview_hook.py::test_a_panel_like_reader_after_the_read` passes with the refit and
fails without it. Also pin that `unload()` drops `readProject`: read after unload, and the
controller stays off.

### N2 (Minor). Two ways in that the hook does not see, against the guide's "however it gets into the project"
`plugin.py:1569-1594`, `docs/guide/getting-started.md:550-553`

1. **A layer repaired after opening.** A file moved since the project was saved opens as an
   unavailable layer. The hook skips it, because the path is not a file. QGIS's "Handle
   Unavailable Layers" dialog and **Change Data Source** then call `setDataSource`, which emits
   no `layersAdded`. The layer keeps QGIS's whole-second band times and the controller is not
   fitted. Verified offscreen: after the repair the ranges are
   `(-2000,-1000), (-1000,0), (0,1000), …` ms where the file records −1.8, −0.7175, 0.365, … ns,
   and the mode is still Disabled. That is I2's failure, for this path.
2. **The plugin enabled while a project is already open.** Layers already in the project are
   never timed until the project is reopened.

**Fix:** in `_on_layers_added`, also connect each `gdal` raster's `dataSourceChanged` to the same
wiring. In `initGui`, run
the wiring once over `QgsProject.instance().mapLayers().values()`. Or narrow the guide's sentence
to the three ways it lists and file the rest.

### N3 (Minor). The guide does not cover a project saved with nsgeo and opened without it
`docs/guide/getting-started.md:561-565`

"Where nsgeo is not installed, the file carries no time setting for QGIS" is true of the file.
But a project saved with nsgeo carries QGIS's own whole-second band times for these layers. Opened
on a machine without nsgeo, the controller there skips the first band and repeats others, with
nothing to say so: the I2 failure, now only without the plugin. A colleague given the project
is exactly this reader.

**Fix:** one sentence: "A project saved with nsgeo and opened without it keeps QGIS's own band
times, rounded to whole seconds, which skip and repeat bands; use the band choice there too."
While there, "installed" should read "installed and enabled": QGIS tells the two apart, and the
hook exists only while the plugin is loaded.

### Nits (not counted)
- The pending refit runs once on an unloaded plugin (see above). A check at the top of
  `_refit_after_open` for an unloaded flag, or for `self.session is None`, would stop it.
- Two docstrings still describe only the old callers:
  - `restore_band_times` (`slice_export.py:698`): "For a layer put back from an export's file".
  - `_fit_temporal_controller` (`plugin.py:1623`): "the file was just made or put back".

  Both now also serve hand-added and reopened layers.
- The 2 ms lead is unpinned (leads of 0 and 1 ms pass the test sweep). It also never matters in
  4,305 measured cases, so this is only worth knowing.
- `_timed_layer_ids` keeps the ids of removed layers until the project clears. It only grows by
  one id per timed add.
