# M16 Plan B: the final review's fix wave

Branch `nsgeo-m16-b`, worktree `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m16-b`, head 027d082.

A whole-branch review (opus) found two Important issues and ten Minor ones. This is the one fix wave for all of them. The controller's rulings R11–R13 below settle the design choices.

The reviewer's probes are in `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/7ec288b0-6c3d-4401-b51d-656c73323d21/scratchpad/probe/`:
- `test_probe_t1.py` reproduces I1;
- `bowl_probe.py` and `bowl_probe2.py` reproduce I2 on the trial's real data, outside the repo.

Read them, and don't edit them.

## I1: building, then exporting, marks every surface stale and refills the grid (Ruling R11)

**How it happens:**
1. `surfaces.py:542-546` remembers `t1_ns` rounded UP to 4 decimals (R10).
2. `ui/paraview_dialog.py:291` sets the "Down to" maximum to the record end, which Qt rounds to 4 decimals. When the end rounds down, `setValue` clamps the remembered value. In the probe the build remembered 101.9863, while the dialog's maximum and value were 101.9862.
3. Exporting at the dialog's untouched defaults writes the clamped value back. `state().stale` becomes `("resolution",)`.
4. `_effective_t1` (`paraview_export.py:157`) now sees an end below the record end, so the cache key changes and the grid fills twice.

**R11, the fix:**
- The dialog's Down to maximum is the record end rounded UP to 4 decimals: `math.ceil(end * 1e4) / 1e4`. Do it in `ParaViewExport.panel_values`, or in the dialog, wherever the record end reaches the spin box.
- Also move the build's `remember_volume` in `_compute` to after the per-record loop, so a refused build remembers nothing.

**Test.** Build first. Then load the dialog through the real `ParaViewExportDialog`, accept its choice as `export_paraview` does (`remember_volume(**choice.to_record())`), and export. Expect `state().stale == ()` and no new `fill_levels` call.

## I2: the fit counts picks held at the window's edge as "within 2 cm" (Ruling R12, which completes R4)

**The problem:**
- `surface.py:397` flags "edge" only when the window clamp lands within 1 µm of the edge.
- When the strongest swing lies just outside the window, the tracked argmax falls on the window's first or last level, which is a rising flank. Refinement moves it at most half a level, so it stops short of the edge and is counted "within 2 cm".
- On the real Bowl this is 19 of the 79 (`bowl_probe2.py`).

**R12, the fix:**
- `_track` also returns a per-column flag that is True when the argmax level is the window's first or last level AND the swing at the next level outside the window is larger. Make it NaN-safe: if no level lies outside, the flag is False.
- `_fit` treats a pick as `at_edge` when its cell was clamped (as now) OR this flag is set.
- Edge picks never count in `within_close` or `within_near`, and the categories still sum to the number of picks.

**Test.** A synthetic test with the window edge between two levels and the reflection peak about 0.3 level outside it. The pick is `at_edge` with reason `"edge"`. The existing `window_m = 0.0225` test was tuned so the clamp acts, which dodges this case.

**Parity.** Re-run `~/nsgeo-m4-check/m16-paraview-trial/core_parity.py`, outside the repo. Report the new disjoint fit (about 60 within 2 cm, 26 at edge, 2 holes expected) and the R5 numbers, which must be unchanged: agreement ≥ 90%, median |Δdepth| ≤ 0.5 cm, south-west holes within 10 points of the trial's. R12 changes only the classification, not the surface.

## R13: no flat guide far from every pick (from M3)

With the `min_curvature` join, region cells beyond the join's reach currently take the mean pick depth (`surface.py:386`). That is cells where `plan_curvature(...).apply` gives NaN, more than `JOIN_REACH_M` from any pick. Leave those cells out of the region instead (`region &= isfinite(joined)`), so the surface can't snap to an unrelated reflection with nothing in the fit to show it. IDW is unchanged.

Test: picks in two clusters more than 4 m apart, where the gap between them is inside the hull. The gap cells beyond the reach are outside the region and NaN. The Bowl parity is neutral here (0 such cells); confirm it in the parity run.

## The minors

- **M1: one scan per sync, not one per surface.**
  - `surface_layers.py:319` calls `state(fid)` without `members`, so every call scans the whole picks table.
  - `paraview_export.py:388` (`_surface_states`) and `:909` (`_write_features`) do the same.
  - Call `members_by_feature()` once per sync, summary or export, and pass it in. `_surface_states` must also stop loading every npz on each dialog refresh: cache by build key, or count from the json.
- **M2: a sweep must not trust an unreadable features table.** `surface_layers.py:373-378` sweeps every folder by `records()`. If the features table couldn't be opened, `records()` is `[]`, and every built surface's json and files get deleted.
  - Skip the sweep when the features layer is unavailable.
  - Test it.
- **M4: the outlier heading and the guide misdescribe edge picks.**
  - `surface_plan.py:539` reads "More than 2 cm from the surface (n)".
  - The guide's step 4 says "more than the window from the surface".
  - Both lists include hole and edge picks, and edge picks are within 2 cm. Word the heading so it covers all three reasons, for example "Picks the surface doesn't follow (n): on a hole, at the window's edge, or more than 2 cm off". Check that each outlier line names its reason.
- **M5: "No need to Save site" is only half true after a build.**
  - A build remembers the grid's 3-D choice, which marks `survey.nsgeo.json` dirty.
  - If the user closes without saving, a grid whose first 3-D use was a build reopens with its surfaces stale (resolution).
  - Say so in `docs/guide/getting-started.md` (around line 814): surfaces and their picks are saved as you go, while the grid's 3-D settings are saved with Save site.
- **M7: membership edits in a transaction group.** With QGIS's "automatic transaction groups" on and the picks layer in editing mode, Add and Remove selected picks write inside the user's open transaction, so a Discard silently reverts them.
  - Refuse every membership write while the picks layer is editable and the project groups transactions: create, add, remove and delete. Use plain wording in `surface_plan`: save or leave editing mode first.
  - Detect transaction grouping across the QGIS 3.40–4.x API: `QgsProject.instance().transactionMode()`, or `autoTransaction()` on older versions. Guard with `hasattr`.
  - Test with the project setting on.
- **M8: only "database is locked" gets the picks-layer advice.** `write_failure_text` (`surface_plan.py:493`) gives the save-the-picks-layer advice for any message containing "locked". Match "database is locked" (SQLite's text) instead. A Windows file lock such as "…has locked a portion of the file" gets its own plain text, or the raw reason.
- **M9: one too-small surface must not block its grid's Rebuild** (`surfaces.py:470`).
  - Skip that surface, with its `rebuild_refusal` reported, and build the others.
  - Test a Rebuild of [ok, too-small].
- **M10: Remove selected picks must not do nothing silently.** When the selection holds none of the surface's picks, give a plain notice.
- **`layers.py:1020` (addAttributes) and `layers.py:1872` (`write_pick`)** still read the bare `provider.error().message()`. Switch both to `_provider_reason`. `write_pick` otherwise loses a lock's reason when it loses the pick.

## Process
- Write the failing tests first where the brief names one.
- **Run:**
  - the touched files;
  - the core tier, with `test_slices_surface.py` under `-W error`;
  - the pure tier;
  - the ParaView export, dialog and scene tests, with `NSGEO_PVPYTHON=/home/jameszd/Documents/Software/ParaView-6.2.1-MPI-Linux-Python3.12-x86_64/bin/pvpython`;
  - the surfaces dock, dialog, layers, build and membership tests;
  - lint;
  - finally, the whole QGIS tier once, in one process, about 26 min.
- **Commit:** `fix: M16 B final review — build-then-export stays fresh, honest edge count, no flat guide, membership guards` (one or more commits). End with the `Co-Authored-By` line. Push to `origin nsgeo-m16-b` with the sandbox off.
- **Report:** append to `final-fix-report.md` in this folder: what you changed per item, the covering tests, the commands and outputs, and the parity numbers.
