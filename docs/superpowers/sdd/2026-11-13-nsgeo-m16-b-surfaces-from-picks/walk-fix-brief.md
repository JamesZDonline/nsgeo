# M16 Plan B: walkthrough fix round 1 — a pick in several surfaces

Branch `nsgeo-m16-b`, worktree `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m16-b`, head 27b64b5.

The user is midway through the walkthrough (profile `ns_geo_m16b`, which runs this worktree; site copy at `~/nsgeo-m16b-walk/Sunnyside/`). Do not touch the site copy or the profile.

## 1. A pick can belong to several surfaces (the user's decision, 2026-11-13)

**Why.** The user made a surface "all" from every Grid1 pick, to compare it with the bowl. That took the bowl's picks away from the bowl's own surface. The user asked for picks to be able to belong to several surfaces.

This replaces spec §4 call 8's "A pick belongs to at most one feature, through `feature_id`", and ruling R9 (moves).

**Storage (Ruling R14).** Keep the picks table's existing `feature_id` column (str). It now holds the list of surfaces a pick belongs to: feature ids joined by `";"`, with no spaces, in the order they were added.
- NULL or empty means none.
- A single id, as today's data already has, is a list of one. No migration.
- Read the column tolerantly: split on `;`, strip whitespace, drop empty parts and duplicates. That copes with hand edits in QGIS's attribute table.
- No new table, no change to the picks schema. Membership survives a picks-table rebuild because it stays an attribute.
- Put the parse and join helpers in `surface_plan.py`, pure and tested: `feature_ids(value) -> tuple[str, ...]` and `join_feature_ids(ids) -> str | None`.

**Behaviour:**
- **Create** adds the new surface's id to each selected pick and removes nothing. Other surfaces keep their picks and don't go stale.
- **Add selected picks** adds this surface's id. A pick already in it is unchanged; if nothing changed, nothing is written and no signal is emitted.
- **Remove selected picks** removes only this surface's id. The "fewer than 3 left" refusal stays.
- **Delete** removes this surface's id from every pick that lists it, using a raw scan as today (including members whose time was blanked), then removes the record. No pick is ever deleted.
- **`members_by_feature()`** maps every listed id that names a record to its members. A pick in two surfaces appears under both.
- **`SelectionCheck`**: drop the move bookkeeping (`moving`, `left`) and the move note.
  - The New surface dialog and Add selected picks may instead say, informationally, "12 of these picks are also in “Bowl”". Wording goes in `surface_plan.py`.
  - Keep `left` only if something still needs it; nothing should.
  - Remove `move_note`'s callers, and remove `move_note` if it is unused.
- **Writes** go through the provider, committed rows only (as now), as one `changeAttributeValues` per operation. The transaction-group refusal stays on create, add, remove and delete.
- **The ParaView export.** `picks.vtp`'s `feature` array keeps one int per pick: the index of the first surface in the pick's list that has a build in this export, or −1. Add a second int array `n_surfaces` per pick, counting the built surfaces it belongs to. Update the scene README paragraph if it describes `feature`.
- **Staleness is unchanged:** each surface's `picks` input is its own members.

**Tests.** Update or replace the tests that pinned moves, then add:
- create B from picks already in A: A keeps all its picks and is not stale; B has them too;
- remove a pick from B: it stays in A;
- delete A: B keeps its picks, and those picks' column no longer lists A;
- a hand-edited column `" a ; ;b;a "` reads as (a, b);
- a picks-table rebuild (the CRS change) keeps multi-membership;
- `picks.vtp`'s `feature` and `n_surfaces` for a pick in two built surfaces;
- the dialog and the panel show the "also in" note, not a move.

**Docs:**
- Amend the spec, `docs/superpowers/specs/2026-11-11-nsgeo-m16-3d-design.md` §4 call 8: a pick can belong to several surfaces; `feature_id` holds the list; the user decided this on 2026-11-13 after the walkthrough.
- Update the guide's surface section where it says a pick moves.

## 2. Keep the build message until it is closed (the user said yes)

The message bar's "Built …" message disappears before it can be read. Show the build result messages, success and warning alike, with no timeout (QGIS message bar duration 0), so they stay until the user closes them.

Check how `plugin.message` is used for other long reports first. Change only the surface-build messages.

Test that the message is pushed with duration 0, or whatever `plugin.message` exposes for that.

## Process
- **TDD.**
- **Run:**
  - the touched files;
  - the membership, build, layers, dock, new-surface and ParaView export tests;
  - the pure tier;
  - then the whole QGIS tier once, in one process;
  - lint.
- **Commit:** `feat: a pick can belong to several surfaces; build messages stay until closed (M16 B walkthrough)`, ending with the `Co-Authored-By` line. Push to `origin nsgeo-m16-b` with the sandbox off.
- **Report:** append to `walk-fix-report.md` in this folder.
