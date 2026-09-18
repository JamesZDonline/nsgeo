# Plan 2 (M4–M6) — the QGIS plugin: decision record

The working record of how the plugin in `packages/nsgeo-qgis` came to be what it is.
Merged to `main` as `0eadff0`, "Merge nsgeo QGIS plugin (Plan 2, M4–M6)", 78 commits.

The code says what it does; these files say **why**, and what was tried and rejected. They were
written as the work happened, not reconstructed afterwards.

## Where to start

- **`progress.md`** — the ledger, and the thing actually worth reading. ~4,100 lines kept in
  order, carrying roughly 85 numbered rulings. Each ruling records a decision made on the
  author's behalf, the evidence for it, and the cost if it turned out wrong. When you find code
  here that looks strange, search this file before changing it: the odd shape is usually load
  bearing, and the reason is usually a defect that was reproduced and measured.
- **`KICKOFF.md`** — the starting state and the plan's own framing.
- **`final-fix-brief.md`** — the 14 items from the whole-branch final review that were fixed
  before merge, each with its file:line, its reproduction and its fix. The selection rule was
  "can this lose or silently corrupt a user's survey data".
- **`round2-rereview.md`** — the scoped re-review of that fix round. 0 Criticals.

## The rest

- `task-N-brief.md` / `task-N-report.md` — one pair per plan task, 19 of them. The brief is what
  was asked for; the report is what was built, what deviated, and why.
- `task-N-review*.md` — the code review of each task, and any re-review.
- `round2-chunk*-brief.md` / `-report.md` — the three chunks the final fix round was split into.
- `m4-followup-*.md`, `m5-followup-*.md` — milestone follow-ups.
- `final-parked-findings.md` — findings deliberately not fixed, with the reasoning.
- `C2-partial-WIP.diff` — 278 lines of unverified mid-thought work from an implementer that was
  stopped partway through the gain-strip ownership fix. Kept because the ledger refers to it and
  because the eventual fix deviated from it deliberately.

## What is not here

The `review-*.diff` files that sat alongside these during the work were dropped on commit: every
one is `git diff <sha>..<sha>` over commits that are now in `main`, so they are regenerable and
were 2.1 MB of the original 3.8 MB.

## Standing caveats recorded here

Four manual acceptance checks were still untested by hand at merge: a symlinked data directory
(C1), a renamed site folder (I5), the unsaved-work guards on New/Open (C4), and uncommitted pick
edits surviving a site close (I6). All four are covered by automated tests; none had been
confirmed by a person operating the plugin. Everything else deferred is in the issue tracker,
numbers #6 through #30.
