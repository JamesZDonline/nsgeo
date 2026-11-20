# M17a walkthrough fix W1 — `rtk_gaps` only on a site with GPS lines

Branch `nsgeo-m17-gps`, worktree `.worktrees/nsgeo-m17-gps`.
Head before this fix: `ef53e2c`. Read `constraints.md` beside this brief for the project's rules and
the exact test, lint and type commands (use them as written; `-p no:xonsh` matters).

## Why

At the M17a walkthrough (check G9) the author answered the open question: every site, even one with
only tape grids, now gets an empty `rtk_gaps` layer in the Layers panel. The author agreed it should
appear **only once a site has GPS lines**. A layer that is always empty on a tape-only site is
noise; the author does not want to be reminded of GPS on sites that do not use it.

## What to build (all in `packages/nsgeo-qgis/nsgeo_qgis/layers.py` unless a test needs a helper)

Today `ensure_tables()` creates every table in `TABLES` in the GeoPackage and opens every name in
`LEGEND_ORDER` as a layer in the site's group; `rtk_gaps` is one of them (`DERIVED`, `LEGEND_ORDER`,
`refill_rtk_gaps`, `_style_rtk_gaps`). Change that so:

1. **A site with no GPS line never gets `rtk_gaps`:** no table created in its GeoPackage and no
   layer opened in its group. "GPS line" = a site line whose placement is a `TrackPlacement`
   (`session.is_gps_line(key)` exists; a direct `isinstance` over `site.lines` is fine too).
2. **The first GPS line brings it:** the refresh after a GPS line is added creates the table if
   needed and opens the layer at its `LEGEND_ORDER` place (between `cuts` and `lines`), using the
   existing `_legend_row` placement, styled and filled as today.
3. **The last GPS line leaving takes it away:** when a refresh finds no GPS line any more, the
   `rtk_gaps` layer leaves the site's group and the QGIS project, and `self.layers` no longer holds
   it. Follow how the module already forgets a layer (`_on_layers_removed`, `detach`) so nothing is
   left pointing at a deleted layer. The GeoPackage table may stay (empty it first, so a later
   reader of the file sees no stale gaps); dropping a GPKG table is not required.
4. **Opening a site** with no GPS line does not open `rtk_gaps`, even when its GeoPackage already
   holds an `rtk_gaps` table (sites made on this branch before the fix have one).
5. Everything that reads `self.layers["rtk_gaps"]` (`refill_rtk_gaps`, `_style_rtk_gaps`, any
   other) must cope with it being absent: no `KeyError`, and no Critical log line on a tape-only
   site. Every other table and layer behaves exactly as today.
6. If the user removes the `rtk_gaps` layer from the Layers panel by hand while the site has GPS
   lines, the existing behaviour for any removed table applies (it comes back on the next refresh,
   at its place). Do not add new behaviour for that.

## Tests (TDD: write each failing test first and see it fail on the current code)

In `packages/nsgeo-qgis/tests/qgis/test_plugin_layers_gps.py` (the GPS layer tests) unless a test
clearly belongs in `test_plugin_layers.py`:

- a tape-only site: the group lists no `rtk_gaps` and the GeoPackage has no `rtk_gaps` table;
- a site that gains its first GPS line: `rtk_gaps` appears between `cuts` and `lines` and draws its
  gaps (reuse the existing GPS helpers in `tests/plugin_testing.py`, e.g. `synthetic_gps_dzt`);
- removing the site's last GPS line: the layer leaves the group and the project and `layers.layers`
  has no `rtk_gaps`; adding a GPS line again brings it back at its place;
- reopening a tape-only site whose GeoPackage already has an (empty) `rtk_gaps` table: no layer;
- a tape-only site's refresh logs nothing Critical about `rtk_gaps`.

The plan's Task 5 (ruling R14) added `rtk_gaps` to seven legend-order assertions in
`test_plugin_layers.py` (lines ~2577–2648). Those sites have no GPS lines, so they go back to
`["picks", "marks", "cuts", "lines", "grids"]`. Keep the `LEGEND_ORDER` constant test (~3049) as it
is: the constant still names where `rtk_gaps` goes when it is there.

Then read `docs/guide/getting-started.md` around lines 415–425 and 768: the GeoPackage row already
says "(with GPS lines) **rtk_gaps**"; make sure nothing in the guide says every site has it.

## Run before committing

- `test_plugin_layers_gps.py`, `test_plugin_layers.py`, `test_plugin_survey_dock.py`,
  `test_plugin_gps_import_dialog.py` (QGIS tier, single files);
- core + pure (fast);
- ruff check + format check, and mypy per constraints.md.

The full QGIS tier is the controller's job.

## Commit

One commit (or two if a test-only commit reads better), message style as the branch's history,
e.g. `fix(m17a): rtk_gaps appears only on a site with GPS lines (walkthrough G9, #134)`, ending with
the line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Do NOT push; the controller
pushes. Do not touch any file outside this brief's scope.

## Report

Append your report to `walkthrough-fix-w1-report.md` beside this brief: what changed and where, each
new test and the failure it showed on the old code, the exact commands run with their final output
lines, and anything you were unsure of. Then reply with: status (DONE / DONE_WITH_CONCERNS /
BLOCKED / NEEDS_CONTEXT), the commit SHA(s), and one line per concern.
