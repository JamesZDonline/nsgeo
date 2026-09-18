### M5 follow-up: two defects found by the user's manual checkpoint

Both were found by a human running the M5 walkthrough in real QGIS on 2026-09-11, and both
were approved for immediate fix. Neither is reachable by the offscreen test tier as written,
because both are about what a person expects to see.

---

## Finding 1: the display-gain slider is inverted relative to intuition, and its range is floored

`packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:

    self.percentile_slider.setRange(900, 1000)   # 90.0 % .. 100.0 %
    self.percentile_slider.setValue(990)         # 99.0 %
    ...
    def percentile(self) -> float:
        return self.percentile_slider.value() / 10.0

`nsgeo.render.PercentileClip.limit()` returns the given percentile of `|data|`, and samples
above that limit saturate. So:

- a HIGHER percentile -> a HIGHER clip limit -> FEWER samples saturate -> a FLATTER image
- a LOWER percentile -> a LOWER clip limit -> MORE saturation -> more black/white

Dragging the slider RIGHT therefore currently makes the image LESS gained. The user's words:

> intuitively for me the moving the slider to the right should make it more gained (black and
> white saturated) and moving it to the left should make it less so. This is currently reversed.

They are describing the standard convention, and they will be using this control constantly
through M6 to judge the result of every processing step.

Second half of the same finding:

> The display gain is a little weird in that its thresholded at 90.0% on the bottom. I may want
> to go further than that sometimes.

**What to implement**

1. **Invert the direction** so dragging right increases apparent gain (i.e. lowers the
   percentile). Qt's `setInvertedAppearance(True)` does exactly this in one line and leaves the
   value semantics untouched, which is the idiom for this situation — but decide for yourself
   whether that or an explicit inverse mapping reads better in this file, and say why in your
   report. Whichever you choose, the `percentile` property must keep returning the TRUE
   percentile, because `RadargramImage` consumes it directly.
2. **Widen the range downward.** The floor of 90.0 % is arbitrary. Take it to **50.0 %**
   (`setRange(500, 1000)`), keeping the 99.0 % default. `PercentileClip` validates
   `0 < percentile <= 100`, so 50.0 is well inside its contract — confirm that, do not assume it.
3. **The label must keep showing the true percentile** (`"99.0 %"`). Do not relabel it to a
   made-up "gain" number; the percentile is the honest quantity and the user reads it.

**Test it.** Pin BOTH properties, and make each test fail if that property breaks:
- that moving the slider toward its right-hand end produces a LOWER percentile (the direction),
- that the reachable range now extends to 50.0 % (the floor),
- that the label still reports the true percentile at both ends.
Assert on the resulting `percentile` value, not on the slider's raw integer, or the test will
pass for the wrong reason if the mapping changes again.

---

## Finding 2: a grid outline and its own lines share a colour

`packages/nsgeo-qgis/nsgeo_qgis/layers.py` uses the same palette index for both:

    line 703 (_style_lines):  symbol.setColor(QColor(GRID_COLOURS[i % len(GRID_COLOURS)]))
    line 724 (_style_grids):  outline.setStrokeColor(QColor(GRID_COLOURS[i % len(GRID_COLOURS)]))

That was a deliberate decision, to let a line be associated with its grid by colour. It works
with several grids and is useless with one, which is the common case. The user's words:

> The grid outline is good now, no fill (which was a problem before) but the lines and the grid
> are the same color. I think we should make them different colors by default.

**What to implement**

Offset the grid outline's palette index from its lines' index, so the two stay associated by
position but are visually distinct. `GRID_COLOURS` has 6 entries; an offset of **3** puts them
at opposite ends of the palette, which is the maximum separation available.

Keep the dashed, unfilled stroke exactly as it is — that was itself a fix from the M4
checkpoint and the user confirmed it is now right ("the grid outline is good now, no fill").

Note the consequence and decide whether it is acceptable, stating your reasoning: with 6
colours and an offset of 3, a fourth grid's outline would reuse the first grid's line colour.
They are different layers with different geometry types, so this is probably fine — but say so
deliberately rather than leaving it unexamined.

**Test it.** Assert that a grid's outline colour differs from its own lines' colour. Do not
hard-code the two hex values and compare them to themselves — derive one side independently, or
the test is a tautology that holds for any offset including zero.

---

## Global constraints (binding)

- The plugin package contains NO signal processing. Display gain is not processing: the
  percentile and colormap change how amplitude maps to colour, never the data, and are never
  recorded in a stack.
- `from __future__ import annotations` in every module you touch.
- All Qt access through `qgis.PyQt`, never `PyQt5`/`PyQt6`. Scoped enums only
  (`Qt.Orientation.Horizontal`, not the short form). The boundary test enforces this.
- Run BOTH test tiers and report them SEPARATELY: `.venv` for `packages/nsgeo-core` and
  `tests/pure/`, `.venv-qgis` for `tests/qgis/`. Add `-p no:xonsh` to every pytest invocation.
- Also run the boundary test, `ruff check`, `ruff format`, and the CI mypy line.
- Mutation-test each fix with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` cleared between
  runs; a stale `.pyc` re-runs the ORIGINAL code and manufactures a false survivor. Report every
  mutation and its honest outcome.

## Commits

One commit per finding. End each commit message with:

    Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

## Report

Write your full report to
`.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/m5-followup-report.md`.
Return only: status, commit SHAs, per-tier counts, and concerns.

Do not dispatch subagents. Review arrives separately, from the controller.
