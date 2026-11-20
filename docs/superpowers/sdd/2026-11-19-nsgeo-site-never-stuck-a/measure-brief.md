# Measure first: the work after the fill lands (spec Part 5)

You measure; you change no product code. Numbers decide whether Plan B (the background fill,
#193) can be written as designed or must go back to the author first.

## What to measure

On the ten-grid Sunnyside **copy**, `~/nsgeo-site-walk/Sunnyside` (survey.nsgeo.json +
site.nsgeo.gpkg; its 210 lines are DZT files under `<raw data>/…`,
read only). **Never open, write or copy into `~/nsgeo-m4-check/Sunnyside`** (the author's real
project). Opening the copy may save settings into the copy; that is fine.

At cell **0.02 m and 0.01 m**, in **both scopes** (Whole site with all ten grids; This grid on the
largest grid, and on one typical grid), record wall-clock seconds on the GUI thread for:

1. **The fill** (the #193 "before" number): the first draw at a new cell, which builds the fills.
   For Whole site, also per grid if cheap to get.
2. **One draw after the fill lands:** a slider tick (a new window at the same cell, same
   finish), fills held. Time from the tick's start to the map layer updated.
3. **The shared stretch after the fill lands:** the stretch measurement (`stretch_limit` /
   `shared_limit`, up to twelve windows) with the fills held.
4. **This grid's first north-up draw:** `to_north_up` for a frame whose plan is not cached (call
   `nsgeo.slices.clear_north_up_plans()` first), and a second call for comparison.

Repeat 2–4 three times and report min/median. Also record peak RSS (e.g. `resource.getrusage` or
`/proc/self/status` VmHWM) after each cell, and the machine's load average at the start.

## How

- Work in a detached scratch worktree of the branch head:
  `git -C <repo>/.worktrees/nsgeo-site-never-stuck worktree add --detach <scratch> HEAD`
  and put any probe test there (e.g. `packages/nsgeo-qgis/tests/qgis/test_zz_measure.py`) so it
  can use the repo's QGIS fixtures (`plugin`, `fake_iface`, how the `-m real_data` tests open a
  survey). Run it with that tree's `packages/nsgeo-qgis/scripts/qgis_tests.sh <file> -s`.
  Remove the scratch worktree at the end. Never edit the main session worktree.
- Drive the real code paths, not re-implementations: Whole site goes
  `SiteScope._run_tick` → `refresh_slice` → `SiteEngine.slice_at` → each engine's
  `finish`/`preview` → `SliceEngine._fill_for`; This grid goes `SlicesDock._finished` → the same
  engine calls. Wrap functions with timers (monkeypatch in the probe) rather than editing them.
  Say in the report exactly which functions bracket each number.
- Use the survey's own settings (method, max distance, search radius) unless they make the
  numbers meaningless; record them.
- **Budget and safety:** 0.01 m Whole site is estimated at ~20 min of fill. If one fill runs past
  30 min, or available memory (`/proc/meminfo` MemAvailable) drops under 2 GB, stop that case and
  report what you have. Machine: 4 cores, 15 GB. Make sure no other heavy job is running when
  you time (check `uptime`; report it).

## Report

Write `.superpowers/sdd/2026-11-19-nsgeo-site-never-stuck-a/measure-report.md` (that directory in
the main session worktree is the one place you may write there) with a table: scope × cell ×
{fill, draw after landing, stretch after landing, first north-up, second north-up, peak RSS},
min/median, the settings used, the load average, and how each number was bracketed. State
plainly whether any of draw / stretch / first north-up is **over about 1 s at 0.02 m** (the
author's threshold). Reply with the table and that verdict.
