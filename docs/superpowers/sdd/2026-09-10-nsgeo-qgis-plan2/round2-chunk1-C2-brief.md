# Round-2 chunk 1 — C2 only: the gain strip writes one step's curve onto another

BASE: `5cc5a12` on branch `nsgeo-qgis`, worktree
`/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-qgis`. The tree is clean and
verified green. Work only in this worktree; never `cd` to the main checkout.

## Scope — exactly one item

Fix **C2** as specified in `.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/final-fix-brief.md`
(section "C2 — The gain strip writes one step's curve onto a different step"). Read that section
in full before writing anything; it carries the reproduction, the file:line anchors, and the
prescribed shape of the fix.

Nothing else. Items C3, C4, I4, I5, I6 and I8 are later chunks and are NOT yours. The
"Out of scope — do not touch" list at the end of that brief binds you too.

## The preserved WIP — a hint, not a patch

`.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/C2-partial-WIP.diff` is 278 lines from a previous
implementer that was stopped mid-thought. It is UNVERIFIED and was deliberately never applied.
Read it for direction — its owner-token shape and its reasoning about why the owner must be
`(key, row)` rather than the step object look sound — but you own the result. Do not `git apply`
it blind. Anything you take from it you must re-derive and prove with a test.

Known gaps in that WIP, so you do not have to rediscover them:
- It contains **no regression test for C2 itself** — the row-change-mid-drag reproduction from
  the brief is missing entirely. That test is the deliverable; the production change is what
  makes it pass.
- It edits `show_gain_strip` to take `owner: Any = None` — confirm `Any` is actually imported in
  `profile_dock.py` and that a defaulted owner is the behaviour you want, or make it required.
- It never resets the strip's `_owner` on the hide paths. Decide whether that matters and say so.
- Its `_forget_gain_owner` placement and the `self._gain_step = new` ordering around
  `replace_step` are asserted in comments but nothing tests them.

## How to work

1. **Test first.** Write the brief's reproduction as a test that FAILS on `5cc5a12` for the
   reason C2 names — a real `Qt.Key_Down` through the plugin, curve step A being edited, the
   selection moving to curve step B, and B's authored points coming back as A's. Run it, see it
   fail, paste the failure into your report. A test you never saw fail proves nothing.
2. Then make it pass with the smallest production change that is actually right.
3. Keep the belt-and-braces second barrier the brief asks for (`_on_gain_points` refusing when
   the row's step is not the one the strip was given) and pin it with its own test — a test per
   barrier, so removing either one goes red.
4. Mutation-check your work: disable each barrier in turn, confirm a test of yours fails,
   restore. Report which test killed which mutation.

## Verification — all of it, before you report

Run from the worktree root with `PYTHONDONTWRITEBYTECODE=1` exported (stale `.pyc` files fake
passing mutants on this repo):

```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py -q -p no:xonsh
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```

Baseline to beat, measured by the controller at `5cc5a12` just now:
qgis tier **336 passed**; pure+core **363 passed, 3 skipped**; boundary **6 passed**; ruff clean;
mypy clean. Your run must be green with strictly more tests, and you must quote the real
counts — not "all tests pass".

`-p no:xonsh` is required on this machine only (a system-site-packages plugin conflict); it does
not go into any config file.

## Commit

One commit, conventional-commit subject, a body that explains *why* the design is what it is —
that is this repo's standard, see `git log` — ending with exactly:

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

Do NOT push. Do NOT merge. Leave the branch at your commit.

## Report

Write `.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/round2-chunk1-C2-report.md` covering: the
failing-test output before the fix, the design decision you made and what you rejected, the
mutation results, the four verification command outputs with real counts, any deviation from this
brief and why, and anything you found that is out of scope (name it, do not fix it).
