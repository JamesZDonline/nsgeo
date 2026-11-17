# Walkthrough results: processing step edge cases and trace stacking

Walkthrough: https://claude.ai/artifact/4SSVqVU75JiWUGMkR4JmFG. QGIS profile `ns_geo_step_edges`,
branch `nsgeo-step-edges` at f0bd986, project copy `~/nsgeo-step-edges-walk/`. Run by the author on 2026-11-16.

**9 passed, 1 answered without a status, 0 failed.** Both gates (opening a project that holds a
now-refused value; Trace stack on a real line with the Difference view) passed.

| Check | Result | Note |
|---|---|---|
| R1 The project opens, and says what it changed | pass | |
| R2 The repaired step on its line | pass | |
| R3 The repaired preset | pass | |
| R4 Save, close, reopen | pass | |
| T1 Add it | pass | |
| T2 The Difference view | pass | |
| T3 A few window sizes | pass | Window they would use on these lines: "Probably 3" (the default). |
| T4 Slices with a stacked preset | pass | |
| E1 A one-sample dewow window (optional) | no status | "It appeared as a toast. no not easy to see, wrapped under a scroll and only there for a few seconds. but don't fix this now" |
| E2 A band too narrow to hold a frequency (optional) | pass | |

Follow-up from E1 (not fixed on this branch, at the author's request): a refused step's reason
reaches the user only through the 6-second message-bar toast (`plugin.message`), where a long
message wraps out of sight. Offered as a new issue at merge time.

After the walkthrough, origin/main (5f1c105, carrying #191's DZT sample-format fix and per-trace
header zeroing) was merged into the branch and the core and QGIS suites rerun.
