### M4 follow-up: two defects found by the user's manual checkpoint

Both were found by a human running the M4 walkthrough in real QGIS on 2026-09-11.
Neither is reachable by the existing offscreen test tier as written.

---

## Finding 1 (REAL DEFECT — spec miss): the `grids` layer has no renderer

The binding spec, `docs/superpowers/specs/2026-09-10-nsgeo-qgis-plugin-design.md`
line 272, requires:

> a categorized renderer on `grid_id` for lines **and a dashed outline for grids**

`packages/nsgeo-qgis/nsgeo_qgis/layers.py` implements only the first half.
`_style_lines()` exists at line ~696 and is called from `refill_lines()` at
line ~664. There is no `_style_grids()` at all, so QGIS assigns the `grids`
polygon layer its default random fill — the user saw an opaque green polygon
where a dashed outline was specified.

**What to implement**

Add `_style_grids()` alongside `_style_lines()`, and call it from
`refill_grids()` the same way `refill_lines()` calls `_style_lines()`.

Requirements, all binding:
- The grid polygon must render as a **dashed outline with no fill** — the grid
  is a reference frame drawn over imagery and basemaps; an opaque fill hides
  the very ground the user is judging the placement against. Use a transparent
  fill brush and a dashed stroke.
- Use `qgis.PyQt` imports only (Qt5/Qt6 compatibility) and **scoped enum
  access** — `Qt.PenStyle.DashLine`, `Qt.BrushStyle.NoBrush`, never the
  unscoped short forms. The existing file is the pattern to follow.
- Keep the module's numpy/Qt import discipline: `from __future__ import
  annotations` at the top, no new third-party dependency.
- Match `_style_lines()`'s existing shape: build the symbol, set the renderer,
  call `triggerRepaint()`.
- Decide for yourself whether grids should also be categorized by `grid_id`
  (so grid A and grid B differ) or use one shared outline style. `GRID_COLOURS`
  at line 115 already exists and `_style_lines()` indexes it by grid position —
  if you categorize, be consistent with that so a grid's outline matches the
  colour of its own lines. State your reasoning in the report.

**Test it.** Add a test to `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`
asserting on the renderer actually installed on the `grids` layer — its symbol's
stroke style is dashed and its fill is transparent. Assert on rendered symbol
properties, not on the fact that a method was called. A test that would still
pass with `_style_grids()` deleted is not a test.

---

## Finding 2 (discoverability): nothing says right-click aborts a pick

`packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py` line 25 implements
right-click as the abort gesture ("the universal QGIS abort this tool
gesture"). It works. But the grid dialog **hides itself** during a pick, so
there is no visible Cancel button, and nothing on screen tells the user that
right-click is the way out. The user hit exactly this and could not determine
how to cancel — they marked the expectation blocked rather than failed,
because the instruction could not be carried out at all.

**What to implement**

`packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`, `_build_digitise_tab()` at
line ~243. Its instruction label currently reads:

    "Click the grid origin on the map, then a point along the +Y edge. "
    "Then enter the sizes."

Extend it so the abort gesture is stated. Keep it one short sentence; match the
existing plain, imperative voice; do not restructure the tab or add widgets
beyond what the text needs.

This is a copy change. A test is optional here — use your judgement, and if you
add one, assert on the label's text containing the gesture, not on exact
punctuation.

---

## Global constraints (binding)

- The plugin package contains **no signal processing**. Display styling is not
  processing; this task touches neither.
- `from __future__ import annotations` in every module you touch.
- All Qt access through `qgis.PyQt`, never `PyQt5`/`PyQt6` directly. The
  boundary test `tests/pure/test_plugin_boundary.py` enforces this and must
  stay green.
- Scoped enum access everywhere (`Qt.PenStyle.DashLine`, not `Qt.DashLine`).
- Never mutate a step in place; not relevant here, but the rule stands.
- Run BOTH test tiers before reporting: `.venv` for `tests/pure/`, `.venv-qgis`
  for `tests/qgis/`. Report the counts for each.
- Run `ruff check`, `ruff format`, and `mypy` over what you touched.

## Commits

One commit per finding, or one commit for both if they read naturally together.
End each commit message with:

    Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

## Report

Write your full report to
`.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/m4-followup-report.md`.
Return only: status, commit SHAs, a one-line test summary per tier, and any
concerns. Do not paste the report back.

Do not dispatch subagents. Review arrives separately, from the controller.
