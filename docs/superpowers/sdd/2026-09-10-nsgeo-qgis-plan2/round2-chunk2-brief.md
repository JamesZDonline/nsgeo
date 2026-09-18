# Round-2 chunk 2 — I4, I5, I6: three data-loss defects in the plugin

BASE: the branch tip of `nsgeo-qgis` when you start (the C2 fix has already landed). Worktree
`/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-qgis`. Work only there; never
`cd` to the main checkout. Confirm the tree is clean before you touch anything.

## Scope — exactly three items, in this order

Read `.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/final-fix-brief.md` and implement, in full:

- **I4** — "Every 'Digitise on map' click permanently leaks a canvas item"
- **I5** — "Renaming the site folder orphans every authored pick"
- **I6** — "Closing a site discards uncommitted pick edits with no prompt"

Each section carries its own reproduction, file:line anchors and prescribed fix. Read all three
before starting: I5 and I6 both touch the picks package and you want one coherent design, not
three independent ones.

Nothing else is yours. C3, C4 and I8 are the next chunk. The "Out of scope — do not touch" list
at the end of the final-fix brief binds you.

## What the controller already knows, so you do not re-derive it

**I4.** `DigitiseGridTool.__init__` (`maptools/digitise_tool.py:19`) creates
`QgsRubberBand(canvas)`, which the canvas's `QGraphicsScene` owns; nothing ever takes it back.
There are **three** places in `plugin.py` that finish with a tool, not one — `done()` (~`:649`),
the `cancelled` connection just after it, and the grid dialog's `finished` teardown (~`:584`,
which calls `blockSignals(True)` then `unsetMapTool`). All three need the disposal, and disposal
must be **idempotent**: more than one of them can run for the same tool. The brief is explicit
that this must NOT live in `deactivate()` alone — that fires on every tool switch and the tool can
legitimately be reactivated afterwards, so a tool whose band is gone must still not crash if it is
(`reset()` and `_on_click` both touch `self._band`).

**I5.** `session.py:82-84`'s `gpkg_path` is `self.root / f"{self.site_name}.nsgeo.gpkg"` with
`site_name = self.root.name`. The brief prefers a fixed basename and *requires* that an existing
old-style package be handled gracefully rather than ignored — a one-time rename-on-open, or at
minimum a log line naming the file it found. Pick one, justify it in the commit body, and pin the
migration path with a test: a site directory holding only `OldName.nsgeo.gpkg` must not come up
with an empty picks layer. Consider what happens when BOTH names exist.

**I6.** `layers.py:182-187`'s `detach()` calls `removeMapLayers` unconditionally and runs on
`site_closed` — i.e. on every "Open site…" and on `unload()`. The picks layer is deliberately
writable (`layers.py:266`). A layer with `isEditable()` and `isModified()` true is destroyed with
no prompt, no signal and no exception. `commitChanges()` or refuse-and-report at `Critical`; the
brief allows either, so choose and say why. Whichever you choose, a test must prove a buffered
feature survives (or that the user is told, loudly, that it did not).

## How to work

1. One item at a time, test-first. For each, write the test that fails on the current tip for the
   reason the brief names, run it, and keep that failure output for your report.
2. Then the smallest production change that is actually right.
3. Mutation-check each fix: revert the production change, confirm your test goes red, restore.
   Report which test killed which mutation.
4. Three commits, one per item — not one lump. Each with a conventional-commit subject and a body
   explaining *why* the design is what it is (see `git log` for the standard), ending with
   exactly:
   `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## Verification — after each commit, and again at the end

Export `PYTHONDONTWRITEBYTECODE=1` for every test run; stale `.pyc` files on this repo have
faked passing mutants before. From the worktree root:

```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py \
  packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```

Controller-measured baseline at `5cc5a12`, before C2: qgis tier **336 passed**; pure+core
**363 passed, 3 skipped**; boundary **6 passed** (BOTH boundary files -- the core one alone is 2); ruff clean; mypy clean. Your final run must be
green with strictly more tests than the tip you started from, and you must quote real counts from
real output — never "all tests pass".

`-p no:xonsh` is a this-machine-only workaround for a system-site-packages plugin conflict. It
does not go into any config file.

Do NOT push, merge or rebase.

## Report

Write `.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/round2-chunk2-report.md`: per item, the
before-fix failure output, the design decision and what you rejected, the mutation result, and
the commit SHA; then the final verification output with real counts; then deviations and
out-of-scope observations (name them, do not fix them).
