# Walkthrough fix round 2 — review findings

The review of round 1 (8862ded..d2b8ba2) is `walkthrough-fix-review.md` in this folder: read it in
full first, especially I1–I3 and M1–M5 and "Outside this round". Same rules as round 1's brief
(`walkthrough-fix-brief.md`, "Rules" and "Report"), same global constraints.

## Rulings (the controller's decisions; follow them)

**R26 — I1, the frame rule.** Replace the min-gap frame with the mean step between band begins:
`frame = (last_begin − first_begin) / (n − 1)` (fractional milliseconds are fine; `QgsInterval` takes
seconds as a float), extent starting 2 ms before the first begin and ending so QGIS counts exactly
n frames (QGIS 3.44 counts `ceil(extent / frame)`, per M3; fix the comment). One band: frame = that
band's length, floored at 1 s (covers M1). Pin with a parametrised sweep in the tests like the
reviewer's (long exports: 200 and 460 bands at dz 0.0977 and 0.2165 ns, one-level step; abutting,
overlapping, gapped; non-zero and negative first begins), asserting frame count == n and frame k →
band k+1 for every k. Keep the sweep fast (seconds, not minutes).

**R27 — I2 and I3, band times come from the file whenever the layer is added.** Do not change the
time scale (1 ns → 1 s stays; the band descriptions and `NSGEO_WINDOW_NS` are the authority). Instead:
- When a raster layer is added to the project — by an export, a restore, a project being opened, or
  by hand (Layer → Add Raster Layer) — and it is a local GDAL file whose metadata records every
  band's window (`NSGEO_WINDOW_NS`) and is not a counts/coverage file, nsgeo sets its band times
  from the file (`restore_band_times`) and fits the Temporal Controller to it. Hook
  `QgsProject.instance().layersAdded` (connect in `initGui`, disconnect in `unload`); keep it cheap
  and safe: only `gdal` provider layers whose source is an existing local `.tif`/`.tiff`; one GDAL
  metadata read; every failure logged ("nsgeo", Warning) and swallowed — never raise from a slot.
  The existing export/restore paths may then rely on the hook or keep calling directly; avoid fitting
  twice in a way that matters, and say which you chose.
- On project open: the band times come back exact through the hook, but the Temporal Controller
  panel restores its own mode from the project after layers are read (review I2 point 1), which can
  undo a fit made while layers load. Make the fit stick: e.g. fit again on
  `QgsProject.readProject` (deferred with `QTimer.singleShot(0, …)` if the panel reads after the
  signal), fitting to the last nsgeo-timed layer. **Verify in the real QGIS app** the way the
  reviewer did (their probe and method are in the review): export-like timed layer → save the
  project → clear → read → the controller is Animated and frames 0..n−1 show bands 1..n. Put the
  probe script under the scratchpad and describe it in the report. If the real-app check is not
  possible, say so plainly — do not claim it.
- Drop the false "saved project reopens set up" claim wherever it is (docstring, report), or make
  it true by the above and say how it was verified. Keep or drop the project time-settings setters
  — your call; say which.
- Cost if wrong: a user with nsgeo installed who adds an unrelated nsgeo export to a project gets
  the controller re-fitted to it — intended.

**R28 — the guide** (`docs/guide/getting-started.md`, the "Stepping through depths" paragraph):
rewrite to what is now true: with nsgeo installed, any exported file steps one band per frame
wherever and however it is added (export, reopened project, Add Raster Layer); the times shown are
ns written as seconds after midnight, 1 January 1970, and times before 0 ns show as the last seconds
of 31 December 1969 (M4); where nsgeo is not installed, the file carries no time setting for QGIS,
so step through bands with the layer's band choice in its Symbology (or another GIS's band list).
Use QGIS's real labels (M4: **Set to Full Range**; the Animated mode is the icon whose tooltip is
"Animated temporal navigation"). Plain, short sentences, as the rest of the guide.

**R29 — M2:** apply the companion-by-name rule only when the file has neither
`NSGEO_INTERPOLATION` nor `NSGEO_SITE_INTERPOLATION`; the `largest_count` tag check stays first. Test
with a windowed values file named `*_coverage.tif` (and keep the old-companion test).

**R30 — M5:** make the flag-order test able to fail (monkeypatch `export_task.drop_stale_files` to
raise; assert `not result.ok and result.values_written`), and check it fails with the two lines
swapped (then swap back — revert any probe edit before committing; set
`PYTHONDONTWRITEBYTECODE=1` for that run).

**R31 — CI:** the pure tests fail on pytest 9.2 ("`pytest.approx()` does not support nested
dictionaries", `tests/pure/test_pure_export_pipeline.py:164`); CI has been red on this branch since
551b237. Fix the test so it passes on pytest 9.1 and 9.2 (compare per key, or flatten). Check the
rest of the branch's new tests for other nested `approx` uses. If you can install pytest 9.2 into a
throwaway venv under the scratchpad to confirm, do; never upgrade the project venvs.

**Also:** the 3.5 nit (bench docstring: `--export-smooth` sets the export rows' smoothing; it does not
re-run them) and the no-canvas nit (skip quietly when `mapCanvas()` is None). After pushing, check CI
on the branch with `gh run list --branch nsgeo-fine-cells-export --limit 3` and
`gh run view <id> --log-failed` until it is green or you can say exactly what still fails.

Report to `walkthrough-fix-2-report.md` in this folder. Return only status, commits, a one-line test
summary (including CI), and concerns.
