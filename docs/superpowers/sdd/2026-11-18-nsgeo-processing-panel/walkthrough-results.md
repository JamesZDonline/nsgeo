# Session E walkthrough results

Page: https://claude.ai/artifact/KD1UtkmHy21zKRNuWVi41W (db collection `results`). Profile `ns_geo_processing`, sandbox `~/nsgeo-processing-walk/` (copy of the campus site; FILE__007's gain curve preloaded with points at +112 and −112 dB, FILE__008's Dewow window set to 0.2 ns). Run by the author 2026-11-19 on fb93c64.

| Check | Result | Author's note |
|---|---|---|
| W1 the gain strip stops at ±120 dB (#49) | pass | |
| W2 Reset asks, then puts back a flat curve (#9) | pass | |
| W3 the caption is readable (#8) | pass | |
| W4 a point outside the record can be reached (#49) | pass | |
| W5 Difference follows a dragged step (#13) | pass | |
| W6 selecting Time zero with Difference on (#48) | pass | |
| W7 a refusal stays until it is fixed (#197, FILE__007) | pass | |
| W8 opening or hovering a line that can't run (#197, FILE__008) | pass | |
| W9 the strip hides behind a step that can't run (#49) | pass | |
| W10 the panel names its line (#33) | pass | No note: the step list did not jump when the preview suffix showed. |
| W11 an attempt at #33 (steps that vanish) | pass | Multi-select opens no line, the panel keeps naming FILE__005, the new step lands there; no other way of losing steps seen. |
| W12 Difference stays quick on a heavy stack (optional) | pass | |

The three items put to the author for judgement (no preview suffix when hovering a cut, a possible jump when the suffix wraps, the dark-red ⛔ row on a dark palette) drew no notes; they stay offered follow-ups, not filed.

## Rule for session F (#158)

Recorded from spec §6.2 for the session that builds on #48: with Difference on, selecting a step that changes the sample count (Time zero) turns Difference off. One toast, the Difference button unchecks, the difference label clears, and the ordinary view shows (the result, or the cutoff bypass when a cutoff row is selected). The differenced step is tracked by identity (Ruling 13), so a moved step keeps its Difference; an edited-in-place or removed step falls back to the index as before.
