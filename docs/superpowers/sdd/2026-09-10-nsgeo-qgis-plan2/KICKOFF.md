# Kickoff — nsgeo-qgis, resuming the final fix round

Paste the block below as your first message. Everything it needs is on disk; nothing depends on
the previous conversation.

---

Resume the nsgeo-qgis final fix round.

Worktree: `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-qgis`
Ledger: `.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/progress.md` — read the `PAUSED` block at
the very end FIRST; it is the authoritative state. Then `final-fix-brief.md` in the same
directory for the requirements.

Where things stand: branch clean at `5cc5a12`, all pushed, verified green locally (qgis 290;
pure+core 363 passed / 2 skipped; boundary 6; ruff clean; scoped mypy clean). 6 of 14 fix items
are done. 19 of 19 plan tasks were already complete before this round.

Do these in order:

1. **Pay the controller debt first.** Reproduce C1, C5 and C6 myself rather than trusting the
   implementer — the standing rule for this round is "verify each Critical by reproduction, not
   by report", and a green suite is not that. C1 has a written repro in the brief (a symlinked
   data dir makes the project unsaveable); C6's repro is running the two named tests and
   confirming they now fail loudly instead of swallowing.
2. **Check CI**, which has not been looked at since those 6 commits landed:
   `gh run list --branch nsgeo-qgis --limit 5 -R JamesZDonline/nsgeo`. This is the ONLY verifier
   for C5's macOS leg — case-insensitive filesystems cannot be reproduced on Linux. Expect the
   `plugin-qgis` job to now run past test 208 of 290 for the first time; do not call it healthy
   until it reports a full count.
3. **Finish the remaining 8 items** — C2, C3, C4, I4, I5, I6, I8 (I8's conftest half is already
   done inside C6, so only the menu tests remain). Dispatch a fresh implementer on **opus**
   (Ruling 78: this diff spans core + plugin + tests at a merge gate). Start it at C2.
   `C2-partial-WIP.diff` holds 278 lines of unverified, mid-thought work from the stopped agent —
   offer it as a direction hint, not as a patch to reapply blind.
4. **One scoped re-review (opus)**, then adjudicate residuals.
5. Then `superpowers:finishing-a-development-branch`. **MERGING ASKS ME FIRST.**

Standing constraints: implementers sonnet / reviews opus unless escalation is recorded; push
feature-branch commits as made; real DZT files never get committed; core stays numpy-only. If a
human checkpoint is needed, stop and ask for it rather than simulating one.

Open questions I still owe an answer on, carried forward — do not re-ask unless I raise them:
whether to install `pytest-timeout`, and whether I want to edit a header's `position_ns` directly
(relabel the axis without touching data) as distinct from the `time_zero` processing step.
