# Review: post-walkthrough fix round, milestone B (#108), 8862ded..d2b8ba2

Reviewer: Claude Opus 5.5 (read-only; nothing in the worktree was edited, created or deleted —
`git status` clean before and after). Scratch probes live under
`/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/0356759e-44aa-46ca-bfe2-a82acefa658a/scratchpad/review-fix/`
(`probe_rules.py`, `probe_fit.py`, `probe_candidate.py`, `probe_count.py`, `probe_handadd.py`,
and under `app/` four probes run inside the real QGIS 3.44.7 application:
`qgis --profiles-path <scratch>/profiles --profile probe --noplugins --code …`, offscreen).

## Verdicts

- **Spec compliance: ❌** Items 2 and 3.1–3.8 are done as asked. Item 1 is mostly done and its
  departure from the brief's extent rule is right, but two of item 1's stated goals are not met:
  the stepping rule is not one-to-one for long, small-step exports (1.4 asked exactly this), and
  "a saved project reopens set up" does not hold (the code's docstring claims it does). The guide
  paragraph (1.6) follows the brief's wording, but that wording sends a hand-added file down a dead
  end.
- **Quality: ❌** One correctness bug in the fit rule (drift), one false claim about reopen, one
  wrong guide instruction; the rest is clean, guarded and tested.

Counts: **Critical 0 · Important 3 · Minor 5**.

## Tests run

- pure + core: **1265 passed, 5 skipped** (matches the report).
- QGIS targeted (`test_plugin_temporal_navigation.py`, `test_plugin_slice_export_dialogs.py`,
  `test_plugin_export_task.py`, `test_plugin_slice_export.py`, `test_plugin_export_dialog.py`, the
  new site-scope test): **176 passed**.
- QGIS full tier (3.44.7, offscreen): **1782 passed** in 17 min (matches the report).
- CI at d2b8ba2: `lint`, `plugin-qgis (3.44)`, `plugin-qgis (4.2)`, `smoke (3.40/3.44/4.2)`,
  `build-zip` green; the pure `test` jobs on Python 3.12/3.13 are red — pre-existing, see "Outside
  this round".

---

## Important

### I1. The min-gap frame drifts off the bands on long, small-step exports
`packages/nsgeo-qgis/nsgeo_qgis/slice_export.py:665-679`

The frame is the smallest gap between the millisecond-rounded band starts, so it is up to 1 ms
shorter than the real step, and the error adds up one band at a time. Frame k starts at
`b0 + k·F` while band k starts at about `b0 + k·step`. Once the lag reaches one frame, frame k
no longer reaches band k: it shows band k−1 again (or no band, `-1`, when the windows are one
level thick, i.e. zero-length ranges), and the last bands are never shown. The frame count stays
right (n), so nothing looks wrong until the user reaches the late bands.

Measured with the branch's own `apply_band_windows` + `fit_temporal_navigation` and QGIS's own
`bandForTemporalRange(layer, dateTimeRangeForFrameNumber(k))` (windows built exactly as
`window_times_ns` builds them, t0 in {0, −1.8, −11.09, 2.0} ns):

| native dz | step | bands | result |
|---|---|---|---|
| 0.2165 ns | 5 levels (abut / overlap / gap) | 17–40 | correct |
| 0.2165 ns | 1 level | 200 | correct |
| 0.2165 ns | 1 level | 460 | **wrong from frame 431** (29 frames repeat a band) |
| 0.0977 ns (GSSI 512 samples / 50 ns) | 1 level | 200 | **wrong from frame 138** (62 frames) |
| 0.0244 ns | 1 level | 60 | **wrong** |
| 0.0391 ns | 1 level | 400 | **wrong from frame 385** |

A 4,500-case sweep (10 native dz values × 6 t0 × 10 step/thickness pairs + 150 random cases, at
1, 2, 17, 60, 200 and 460 bands, steps ≥ 8 ms) gives **288 failures** for the branch's rule
(123 of them are M1 below; the rest are drift at 60, 200 and 460 bands).

So, to the brief's question "can a 200-band export drift off by one?": not at dz 0.2165 ns (it
takes about 430 bands at a one-level step there), but yes at other native intervals the plugin
reads, from about 140 bands at dz ≈ 0.098 ns and a one-level step. The step box goes down to
0.01 ns, so a one-level step is reachable.

The tests cannot see this: every case in `test_plugin_temporal_navigation.py:52-61` has 17 bands
(the lag stays under 9 ms), and the plugin-level tests use the default step.

**Fix (verified):** use the mean step and start the extent a little early:

```python
n = len(begins)
frame = (begins[-1] - begins[0]) / (n - 1) if n > 1 else max(single_band_length, 1000)  # ms, float
start = begins[0] - 2                                     # 2 ms lead
end = start + math.floor(n * frame) - 1
navigation.setFrameDuration(QgsInterval(frame / 1000.0, Qgis.TemporalUnit.Seconds))
```

Why it holds: each rounded start is within ±1 ms of an exact grid; the mean step is within
±1/(n−1) ms of the true step; QGIS's frame times for a fractional-second frame come out up to
1 ms early (measured: truncation of `k·seconds·1000`). A 2 ms lead keeps every frame end at or
before the next band's start, and every band inside its own frame, for steps above about 6 ms
(dz ≥ 0.006 ns). The same 4,500-case sweep gives **0 failures** for this rule. Checked in the real
app: the panel shows a fractional step to 3 decimals (0.2165 s shows as 0.216) but keeps 0.2165 s
in the navigation object through events and Next clicks, so the rounding on screen does not leak
back. Add at least two long cases to the tests (200 bands at dz 0.0977, one-level step; 460 at
0.2165, one-level step) and a one-level-thick case.

### I2. A saved project does not reopen set up, and the docstring says it does
`packages/nsgeo-qgis/nsgeo_qgis/slice_export.py:654-655, 685-688`

Brief item 1 asked for the project's time settings "so a saved project reopens set up". The
calls are made and they exist (see (c)), but the outcome was never checked, and it does not hold
on QGIS 3.44.7 (probe inside the real app: fit, `QgsProject.write`, `clear`, `read`):

1. **The controller reopens switched off** (navigation mode Disabled). On reopen the panel reads
   the mode from its own project entry (`TemporalControllerWidget/NavigationMode`). A programmatic
   `setNavigationMode` does not write that entry, and the saved `.qgs` has none.
2. **QGIS writes every time in the project at whole-second precision** (`Qt::ISODate`). The
   project's range is saved as `23:59:58Z → 00:00:16Z` for a fitted `−1.800 s → 16.593 s`, and,
   worse, **each layer's own per-band ranges are saved the same way**
   (`<range begin="1970-01-01T00:00:07Z" band="10" end="1970-01-01T00:00:09Z" …>`).
   After the reopen, switching the controller to Animated shows bands
   `[2,3,4,5,6,7,8,9,10,10,11,12,14,15,16,17,17]` for the 17-band walkthrough geometry: band 1 is
   never shown and others repeat. Writing the panel's entries by hand (mode, start and end with
   milliseconds) restores the mode and the exact extent but not the layer's truncated band ranges,
   so it still shows `[2,3,…,17,17]`.

The band-range truncation is the M11 "1 ns → 1 s" mapping meeting QGIS's persistence: the same
trap `band_time_range`'s docstring describes for milliseconds, one level up. At a one-level step
on dz 0.2165 ns (216 ms per band) four or five bands share each saved second and collapse. It
predates this round, but this round is what promises the reopen.

**Failure scenario:** the author exports, saves the QGIS project, reopens it next day, turns the
controller on: it steps, but skips the first band and repeats others, with nothing to say so.

**Fix:** now, drop the claim from the docstring and the report (the setters are harmless; keep or
drop them). Then file a follow-up: either re-wire nsgeo layers from their files' `NSGEO_WINDOW_NS`
on `QgsProject.readProject` (`restore_band_times`) and re-fit, or change the time scale so a
band step is a whole number of seconds (a format decision for the author).

### I3. The guide's hand set-up for "a file you add by hand in another project" cannot work
`docs/guide/getting-started.md:555-558`

The paragraph says: choose Animated, press **Set to full range** (from the layers), and make the
step equal to the band step. A file added by hand has no band times at all. QGIS does not read
`NSGEO_WINDOW_NS`, and the `.qml` beside the file is saved from a fresh, untimed layer
(`export_style.write_style`). Verified: the `.qml` carries
`<temporal mode="0" enabled="0" …>` with no ranges, and the re-added layer reports
`isActive() == False`, zero ranges. So **Set to Full Range** finds no temporal layer, and every
frame draws the same band, which is exactly the walkthrough's complaint. The wording came from the
brief, so this is the brief's error copied faithfully, but the guide is what the user reads.

**Fix:** say that a file added by hand carries no time setting for QGIS. To step through it,
either add it through nsgeo, or, in **Layer Properties → Temporal**, choose a fixed time range
per band and type each band's range (ns as seconds). Or drop the sentence and file a follow-up
for a "wire the band times" action that reads `NSGEO_WINDOW_NS`. Note also that even typed by hand,
those ranges are saved at whole seconds (I2).

---

## Minor

### M1. A single one-level-thick band gets a zero-length extent and 0 frames
`slice_export.py:668-679`. One window of thickness 1 level has `lo == hi`, so the band length is
0, `frame_ms` is floored to 1, and the extent is `begins[0] → begins[0] + 1 − 1`. QGIS 3.44
counts **0 frames** for a zero extent (measured). That needs a one-level thickness and a step
covering the whole axis, so it is rare. The I1 fix's single-band floor (≥ 1 s) covers it.

### M2. The companion-by-name rule wins over the file's own band windows
`slice_export.py:712`. `stem.endswith("_coverage")` is checked before anything else. A values
export the user named, say, `full_coverage.tif` (tagged `bilinear`, every band windowed) is
classed as counts. After a cancelled or failed replace it comes back with no time slider and no
controller fit, and no "without the time slider" note, because `"counts"` is not reported.
Old companions are the files the rule targets, and they carry no interpolation key: This grid's
`coverage_plan_of` sets `finish=None`, and the site companion "carries none of the four". So
apply the name rule only when the file has neither `NSGEO_INTERPOLATION` nor
`NSGEO_SITE_INTERPOLATION` (and, if you like, a single band). The tag check stays first. Add a
test with a windowed values file named `*_coverage.tif`.

### M3. The code comment states QGIS's frame count wrongly
`slice_export.py:674-677` says QGIS counts frames as `floor(extent / frame) + 1`. On 3.44.7 it is
`ceil(extent / frame)`: 1000 ms at 1 s gives 1 frame (floor+1 would say 2), 5000 ms gives 5, and
a zero extent gives 0. The branch's `n·F − 1 ms` end still gives n under ceil for F ≥ 2 ms, so
the code is fine. But the comment invites a wrong "simplification", e.g. an end of
`(n−1)·F`, which ceil turns into n−1 frames.

### M4. Guide gaps around the times shown
`getting-started.md:550-558`. Real files start before 0 ns (the walkthrough's bands start at
−1.8 ns), and the controller shows those as **31 December 1969 23:59:58**. The paragraph explains
only `00:00:05`. One sentence fixes it ("times before zero show as the last seconds of
31 December 1969"). Small accuracy points: the button reads **Set to Full Range**, and the
Animated mode is an icon whose tooltip is "Animated temporal navigation".

### M5. The flag-order test cannot catch the order it claims to pin
`tests/qgis/test_plugin_export_task.py:650-668`. The docstring says "The flag is set at the
replace, before the stale files are dealt with". But `drop_stale_files` never raises, so swapping
`export_task.py:210` and `:211` still passes. To pin it, monkeypatch `export_task.drop_stale_files`
to raise a `RuntimeError` and assert `not result.ok and result.values_written`.

Nit, not counted: with no canvas, `self.iface.mapCanvas().temporalController()`
(`plugin.py:1561`) raises AttributeError, which is logged at Warning, not "skipped quietly" as
the brief says. QGIS always has a canvas, so this is harmless.

---

## The specific checks asked for

**(a) The fit rule against QGIS 3.44.** QGIS's rules, measured: frame count =
`ceil(extent/frame)` (M3); frame k = `[start + trunc(k·frame), start + trunc((k+1)·frame))`,
start-inclusive and end-exclusive, with frame times truncated by up to 1 ms for fractional-second
frames (e.g. 1.083 s, 1.001 s); `bandForTemporalRange` picks the overlapping band with the latest
end. The bands are closed ranges, so a band ending exactly where a frame begins still overlaps it,
but the later band wins.
- The departure from the brief's "first begin → last end" is **right**: with ms-rounded starts the
  min-gap frame is shorter than the mean step, so that extent gives n+1 frames (n+2 or more for
  overlapping windows). The implementer reported it rather than hiding it.
- Abutting, overlapping and gapped windows at dz 0.2165, starting at 0 or below: correct for
  ordinary band counts (verified 17–200 bands, four t0 values). Single band with thickness: 1 frame,
  correct. Single zero-length band: 0 frames (M1).
- The tests prove frame k → band k+1 for every band and count == bands, but only for 17 bands,
  t0 = 2 ns and thickness ≥ 2 levels. Long exports drift (I1).
- Real app: the canvas's controller is a `QgsTemporalNavigationObject` (`isinstance` true), and
  **the panel follows the programmatic change**: slider 0..16 for 17 bands, Animated checked,
  step 1.082 s, start and end with milliseconds; the panel's own Next button moves to frame 1 =
  band 2. That answers the report's open question.

**(b) Guarding.** `_fit_temporal_controller` (`plugin.py:1552-1569`) wraps everything in
`try/except Exception` and logs to "nsgeo" at Warning. It runs after `_add_exported_layer` and
`temporal(layer)`, so the layer is in. `_add_export_layer` returns None after it, so the message
is still shown. In `_restore_layers` it runs after `back.append(name)`. The outer guards
(`_finish_export`, `_deliver`) are still there. Skipping a non-`QgsTemporalNavigationObject` is
correct, and in the real app it never skips (verified). Test coverage: fit raising → layer added,
log written; no controller → quiet. Fine.

**(c) API.** `Qgis.TemporalNavigationMode.Animated`, `setNavigationMode`, `setTemporalExtents`,
`setFrameDuration`, `setCurrentFrameNumber`, `QgsInterval(float, Qgis.TemporalUnit)`,
`QgsProjectTimeSettings.setTemporalRange`, `setTimeStep` and `setTimeStepUnit` exist on 3.44.7
(checked locally) and on 4.2: CI `plugin-qgis (qgis/qgis:4.2)` is green at d2b8ba2 and runs
`test_the_project_time_settings_follow`. 3.40 is only smoke-tested in CI, which imports the
module but never calls these. By API history they are all older than 3.40:
`Qgis.TemporalNavigationMode` moved into `Qgis` in 3.36, `Qgis.TemporalUnit` in 3.30, and the
project-settings setters date from 3.14–3.18. No call needed skipping. Docker was not running
locally, so 4.x was not run here.

**(d) Item 3.1.** Done right. `replace_partial`, then `self._values_written = True`, then
`drop_stale_files` (`export_task.py:209-211`). `drop_stale_files` catches `OSError` per file and
logs it from the worker thread (`QgsMessageLog` is thread-safe). An unlink failure after the
replace therefore gives `ok=True` (`test_a_stale_statistics_file_that_cannot_be_removed…`). The
companion goes through `commit_partial`, which is best effort too. The finally clause's
`discard_partial` on the already-moved values partial is a harmless `missing_ok`. The
order test is weak (M5).

**(e) Item 3.2.** Yes, it misclassifies a values file named `*_coverage.tif` (M2). The fallback
order should be: tag → counts, then values-only keys → windows, then the name rule.

**(f) Item 2.** The Memory row comes before File, in budget and over budget
(`slices_plan.py:549-555`). The dialog always shows `summary_lines(preview)`, so no path drops it.
The pure tests pin the exact rows and the over-budget value. The dialog tests pin the exact
in-budget rows and the key order for This grid. The over-budget row is not pinned at the dialog
level, which is adequate since no dialog branch filters rows. The refusal text is unchanged. The
guide sentence lists the row.

**(g) Site names.** None in the diff or in the five commit messages, and no local paths. Every
commit ends with the `Co-Authored-By: Claude Opus 5.5` line.

**Other items.** 3.3: the `ExportCancelled` docstring matches the code (`run_export`'s `_check`
calls at `export_pipeline.py:496/502/513/522`, the curvature solve at 449, `build_overviews` at
`slice_export.py:193`, `ExportTask.run` at `export_task.py:208`). 3.4: no ".;" is possible
(`plain_export_error` never ends in a full stop, restore notes have none, and style notes now go
last); the new test, with a style failure plus a restore note, would have caught the old order.
3.5: fine; nit: `--export-smooth M` sets the export rows' smoothing, it does not re-run them.
3.6, 3.7 and 3.8: done as asked.

## Outside this round (for the controller)

- **CI has been red on this branch since 551b237:** the pure `test` jobs on Python 3.12/3.13 fail
  on pytest 9.2.0 with "`pytest.approx()` does not support nested dictionaries" at
  `tests/pure/test_pure_export_pipeline.py:164`. Locally pytest is 9.1.1, so it passes. The base
  of this round (8862ded) fails the same way. It must be fixed before merge. The implementer's
  report does not mention CI.
- The walkthrough site's name is already in 24 tracked files on `origin/main` (several
  `docs/superpowers/...` records, `tests/plugin_testing.py`, `tests/pure/test_pure_line_edit.py`,
  `packages/nsgeo-core/tests/data/local/README.md`). None of them came from this round. Given
  "no site names anywhere", the author may want a sweep.
