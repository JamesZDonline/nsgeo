# Final review fix wave (FIX_BASE 55fdc59)

The opus whole-branch review rated the branch **With fixes**. Core and plugin meet the spec, the C14 decisions and
every Review Focus item. #97 time zero (now merged in from main) does not affect Measure. This is the ONE fix
wave, so fix everything below in one go.

When you're done:
- Append a "## Final fix wave" section to task-3-report.md: each item, the change, file:line, the covering test,
  the command and the output.
- Commit and push, then confirm with `git ls-remote origin refs/heads/nsgeo-auto-destagger`.

Rules as before:
- No subagents, and nothing from tests/data/local.
- PYTHONDONTWRITEBYTECODE=1, and no bare git stash.
- Never commit a mutation probe.
- Python 3.9 in core: no zip(strict=), no match.

## Important 1: a wrong reason when every line is excluded (Ruling 12)

**The problem** (`packages/nsgeo-core/src/nsgeo/destagger/measure.py:207-208`;
`packages/nsgeo-qgis/nsgeo_qgis/destagger_job.py:116-117`):
- When no line survives the exclusions, `failed(ONE_WAY if len(remaining) >= 2 else TOO_FEW)` reports TOO_FEW.
- The summary for "every axis failed" is only the failure sentence, so the per-line reasons are hidden.
- The reviewer's probes show three cases where the message is wrong. Each gives "Could not measure: too few lines
  walked in opposite directions to measure":
  - 20 zigzag lines of 5 m, where every line is really TOO_SHORT;
  - 20 timer-recorded lines, where every line is NO_DISTANCE;
  - 17 of 20 files unreadable, where the unreadable files are not named at all.

**The fix:**
- **Core:** when no line survives the exclusions before the neighbour stage, the axis fails with a new reason
  constant `NO_LINES = "none of the grid's lines could be measured"`. Export it the way the other reason constants
  are exported, if they are. ONE_WAY and TOO_FEW keep their current meanings for lines that did survive.
- **Plugin `measure_summary`:** when every axis failed, the summary is the failure sentence(s), followed by the
  "Not measured, left as they were:" group, built as usual.
  - Unreadable files are included, with `could not be read: …`.
  - Lines whose reason is NO_NEIGHBOUR are left out, because the axis reason (ONE_WAY or TOO_FEW) already covers
    them.
  - If nothing is left to name, the summary is the failure sentence alone, as today. So the one-way grid's message
    is unchanged, and so are its existing test and the walkthrough's expected text.
  - The Ruling 9 path (no axes at all, every file unreadable) stays as it is.
- **Tests:**
  - core: synthetic short lines give an axis with NO_LINES and every line TOO_SHORT;
  - pure: the all-failed summary names the excluded lines with their reasons, leaves out NO_NEIGHBOUR lines, and
    names unreadable files; the one-way summary is unchanged.
- **Plan amendment:** in docs/superpowers/plans/2026-11-11-nsgeo-auto-destagger.md, change "When every axis failed,
  the summary is only the failure sentence or sentences." to say the not-measured group follows, without
  NO_NEIGHBOUR lines. Add NO_LINES to the reason strings there.

## Minors

1. **The spread depends on row order** (`profiles.py:238-261` with `measure.py:241-242`).
   - The bootstrap resamples curve rows in input (table row) order. Reversing Grid 1's input gives ±0.0127 against
     ±0.0113.
   - Make the result independent of input order: build the bootstrap rows in offset order, or sort the lines by
     offset (ties by key) before measuring.
   - Add a real-data test (needs_grid1): reversed input gives the identical AxisResult (destagger and spread_m)
     and identical per-line values.
3. **Ruling 15:** the status label's tooltip carries the uncapped summary, naming every line in every group. The
   visible line keeps the 6-name cap (P12).
   - Give `measure_summary` a way to build the uncapped text, e.g. `limit: int | None = 6`.
   - The dialog sets the tooltip whenever it sets a Measure summary, and clears it, or sets it to the plain status,
     for other status text.
   - Test both: pure for the uncapped text, QGIS for the tooltip after a canned run with more than 6 own values.
4. **A stale dialog can measure against another site** (`edit_lines_dialog.py:516-544`, `:170`/`:602`).
   - After site A is closed and site B opened, the A dialog stays open.
   - `_measure` has no `json_path != _opened_against` guard, and `_bins` is keyed by relative line key, which
     repeats across sites.
   - Refuse at press with the same check `_accept` uses, and the same message `_accept` shows (reuse it; don't
     invent copy).
   - Also key `_bins` by the line's resolved file path, not its relative key.
   - Add a QGIS test: open the dialog, close the site, open another site, press Measure. It refuses, starts no job
     and writes nothing.
7. **Ruling 14:** `box_value` takes the axis with the most `lines_used` among the axes whose `destagger` is not
   None. It returns None only when no axis measured. Update the pure test: the larger axis failed and the smaller
   measured, so the box gets the smaller axis's value.
8. **The mirror test checks only the grid value** (`test_destagger_grid.py:78-83`). Spec §10 says "gives the same
   values".
   - Also compare per-line values: for every line that is OWN in both runs, values within 0.02 m.
   - Allow borderline status flips: Grid 1 unfitted FILE__036 flips CHANGES to GRID. Assert that at most 2 lines
     change status.
   - Don't loosen anything else.
9. **The guide paragraph** (`docs/guide/getting-started.md:353`) should also say:
   - lines Measure cannot use are left as they were and named in the status, with the reason;
   - the button turns into Stop while it runs.

   Keep the paragraph short and in the guide's plain voice.

Not in this wave:
- Minor 2 (Ruling 13; the column keeps 2 decimals);
- Minors 5 and 6 (Ruling 16; a follow-up issue).

## Verification
- core+pure: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider` (paste the tail);
- the Measure QGIS file and test_plugin_edit_lines_dialog.py (as before);
- ruff check and format --check;
- mypy with the CI list.

The controller runs the full QGIS tier afterwards.
