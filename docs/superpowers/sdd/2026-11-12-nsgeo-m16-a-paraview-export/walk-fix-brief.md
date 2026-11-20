# M16 Plan A: walkthrough fix round (before merge)

Branch `nsgeo-m16`, worktree `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m16`, head 4a04ee4.
The user is midway through the walkthrough (profile `ns_geo_m16`, dev-linked to this worktree).
Four items. The first is a user decision; the other three are parked residuals (ledger Ruling R18).

## 1. "Down to": the export's own deepest time (user decision, 2026-11-13)

**The problem, found in the walkthrough.**
- The export takes Grid1's whole record, about 100 ns, so the dialog reads "400 × 320 cells × 1001 depths, 0 – 3.55 m".
- The Slices panel's z1 cutoff for Grid1 (`slice_resolution("Grid1")["t1_ns"] == 40.0`) is ignored.

**The user chose to give the export its own deepest time, the same pattern as the 3-D cell and depth step (spec decision 8):**
- it is remembered per grid in the volume record;
- at first use it starts from what the Slices panel remembers for that grid (its `t1_ns`), else the whole record;
- after that, browsing slices never changes it.

The export still starts at time zero, as now. There is no z0 field.

**What to build:**
- **`slices_plan.VolumeChoice`:**
  - It gains `t1_ns: float | None = None`. None means to the end of the record.
  - It is validated as None, or finite and > 0.
  - `to_record()` includes `"t1_ns"` only when it is set.
- **`slices_plan.volume_choice(...)`:**
  - It gains a keyword `t1_default: float | None = None`.
  - A usable `t1_ns` in the record wins; otherwise `t1_default` is used.
- **`nsgeo-core` `project._clean_volume`:**
  - It keeps `t1_ns` when finite and > 0. Its docstring's field count changes.
  - Extend the round-trip tests in `packages/nsgeo-core/tests/test_project.py`.
- **`ParaViewExport.defaults`** passes `t1_default`: the grid's `slice_resolution(grid_id).get("t1_ns")` when that is a positive float, else None.
- **Clipping the time range.** Everywhere the export works out its time range, clip the end to `choice.t1_ns` when that is set. That is `_time_range`, used by `estimate`, `summary` and `cache_bytes`, and `run`, through `_bounds(lines)`.
  - If the clipped range leaves fewer than 2 depth levels, refuse with ValueError, in plain words.
  - The wording lives in `paraview_scene.py` or `slices_plan.py`, never in the widget. For example: "Down to must be deeper than time zero; it is 0.0 ns".
- **Cache keys:**
  - `_settings_key` must include `choice.t1_ns`, or `cache_bytes` would claim that a fill for another depth can be reused.
  - `_cache_key` already includes the clipped t0 and t1.
- **The dialog (`ui/paraview_dialog.py`).** Add a "Down to" spin box in the "3-D resolution" group, under Depth step:
  - It is in ns, with the same decimals the Slices panel uses for z1.
  - Its range runs from just above 0 to the end of the record, so the dialog needs that end time. Extend what `hints_for` / `ParaViewExport.panel_values` return, and update its callers and tests.
  - Its hint gives the depth it reaches at the grid's velocity and where the record ends. For example: "1.42 m; the record ends at 100.0 ns". The hint text is built in `paraview_scene.py`.
  - It shows `choice.t1_ns`, or the record's end when that is None.
  - Editing it refreshes the summary, as Cell and Depth step do.
  - Return in it never starts the export: install the existing event filter on it.
  - The mouse wheel behaves as it does on the other spin boxes.
  - `choice()` returns it, and `remember_volume` stores it after an export, as today.
- **The guide.** One sentence in `docs/guide/getting-started.md`'s Export for ParaView section: "Down to" sets how deep the export goes, and it starts from the Slices panel's z1 the first time.

**Tests:**
- **Pure:**
  - `volume_choice` takes `t1_default` at first use, and then the record's `t1_ns` wins;
  - None round-trips as absent;
  - a bad value reads as unset.
- **QGIS (`test_plugin_paraview_export.py`, on `synth_site` so it runs in CI):**
  - `summary().nd` and `max_depth_m` follow `t1_ns`;
  - `run` writes a `cube.vti` with that many depth levels;
  - two values of `t1_ns` give two different cache names;
  - a `t1_ns` at or above time zero's level count is refused with the message;
  - `defaults()` takes the panel's remembered `t1_ns` at first use, and ignores a change to it once the volume record has one.
- **QGIS (`test_plugin_paraview_dialog.py`):**
  - the field shows the remembered value;
  - editing it refreshes the size;
  - Return in it does not export;
  - `choice().t1_ns` is what was typed.

## 2. R18(a): the dialog test file segfaults at shutdown when run alone

Add `gc.collect()` in the `qgis_app` fixture of `packages/nsgeo-qgis/tests/qgis/conftest.py`, after `yield` and before `exitQgis()`.

The cause was diagnosed in the ledger: a parentless `ParaViewExportDialog` sits in a gc cycle and is collected after `exitQgis`. Verify it: run `tests/qgis/test_plugin_paraview_dialog.py` alone, and it exits 0.

## 3. R18(b): open.bat should not hold the export folder on Windows

In `nsgeo_qgis/paraview/open.bat.txt`, replace the start line with:
`start "" /D "%HERE%.." "{{PARAVIEW}}" --script="%HERE%open_scene.py"`

Update its CRLF and contents test in `tests/pure/test_paraview_scene.py`.

## 4. R18(c): `launch_failed_message` reads awkwardly when lines were skipped

`paraview_scene.launch_failed_message` glues `exported_message(...)` (which may end in a sentence naming skipped lines) to ", but ParaView could not be started …".

Reword it so it reads as plain sentences in both cases, with and without skipped lines. Update its tests.

## Process

- **TDD:** write the failing tests first.
- **Run, using the commands in `global-constraints.md` in this folder:**
  - the touched test files;
  - then the pure and core tiers;
  - then `tests/qgis/test_plugin_paraview_export.py` and `tests/qgis/test_plugin_paraview_dialog.py`;
  - ruff, ruff format --check, and mypy.
- **Commit messages:** two or more commits are fine, for example the depth field, then the residuals. Each ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Push** to `origin nsgeo-m16`, with the sandbox off.
- **Never touch:** the user's walkthrough site `~/nsgeo-m16-walk/`, the QGIS profile, or the main checkout.
