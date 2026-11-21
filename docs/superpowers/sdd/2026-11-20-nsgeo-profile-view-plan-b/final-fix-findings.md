# Final review (Plans A+B) — the fix wave's findings

Fix all three. Pin I1-adjacent behaviour where a test applies; M1 needs a test that fails first.

## I1. The user guide has no sentence for Time zero by eye
docs/guide/getting-started.md — near the Gain curve bullet (~line 561; read the surrounding bullets and match their voice; plain, no headings). The line only appears when Time zero is in `sample` mode and its row is selected, and selecting it changes the picture (the raw input on its own scale, cropped rows dimmed above). Read cold that can look like a glitch. The time cutoff's line isn't in the guide either. Suggested text (adapt to the guide's voice, keep it short):

"Select a **Time cutoff** step, or a **Time zero** step set to **sample**, and a line on the profile marks it; drag the line or type the value, and the two always agree. While Time zero is selected the profile shows the record Time zero receives, with the rows it crops dimmed above the line, which reads 0 ns. Switching Time zero's **Mode** to **sample** starts the row at the automatic first break, so nothing moves until you drag."

Check whether a release-docs test pins guide text (tests/pure/test_release_docs.py) and run it.

## M1. A hidden field that parses but is out of bounds still blocks a mode switch
packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py:430–449 (`values()` fallback). Probe: type threshold "5" (refused, correct), then switch the mode to `sample` → nothing commits; the error "threshold must be <= 1.0" names a field now hidden; the combo reads `sample` while the step stays `first_break`. Plan B's earlier fix (RB3/M5) covered only parse failures. Fix: in the hidden branch, also fall back to the shown/stored value (else the default) when `param_problem(spec, value)` is not None. Visible fields keep today's errors. Test: the probe's sequence commits `mode="sample"` and the step keeps its last good threshold; show it failing first.

## M3. Stale wording in three docstrings
- packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py:129–130 — `cutoff_dragged` says "the snapped end time"; for a row handle it is a row top.
- packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py:3 — the module docstring names only "the draggable time-cutoff line".
- packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py:~2277 — `_handle_row` says "when it is the cutoff row".
