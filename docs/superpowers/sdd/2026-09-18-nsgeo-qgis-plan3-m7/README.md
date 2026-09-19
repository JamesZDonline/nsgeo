# M7 (the map ↔ profile link) — decision record

How `MapLink` and the session's preview state came to be what they are.
Branch `nsgeo-m7`, 19 commits on top of `79401fd`.

The code says what it does; these files say **why**, and what was tried and rejected.
They were written as the work happened, not reconstructed afterwards.

## Where to start

- **`progress.md`** — the ledger, and the thing worth reading. Sixteen numbered rulings,
  each recording a decision made on the author's behalf, the evidence for it, and the cost
  if it turned out wrong. When you find code here that looks strange, search this file
  before changing it: the odd shape is usually load bearing.
- **`deferred-minors.md`** — everything found and deliberately not fixed, triaged by the
  whole-branch review. None of it blocked merge; several are M8's opening backlog.

## The rest

- `task-N-brief.md` / `task-N-report.md` — one pair per task, five of them. The brief is
  what was asked for; the report is what was built, what deviated, and why.
- `final-fix-report.md` — the single fix wave after the whole-branch review.

## What is not here

The `review-*.diff` files that sat alongside these are dropped: every one is
`git diff <sha>..<sha>` over commits now in the branch, so they are regenerable, and they
were 400 KB of the original 664 KB.

## Two things worth knowing before you change this code

1. **The C2 invariant.** `SiteSession.current_key` is the working line — what every write
   resolves through. `preview_key` drives the view and nothing else, ever. Three separate
   review findings in this milestone were attempts by a preview to reach a write
   (`_channel_changed`, the gain strip's deferred payload, a lazily-inserted `StepStack`).
   If you add a path from the pointer to the session, assume it is a fourth until you have
   proved otherwise.

2. **`MapLink.dispose()` is longer than it looks like it needs to be.** It survived four
   review rounds so that a deleted canvas wrapper, a canvas that is not a sip object, and a
   `disconnect` that raises all still reach its scene-removal loop. Shortening it
   reintroduces the leak it exists to prevent — which already happened once, inside this
   milestone, and was caught only by a re-review.
