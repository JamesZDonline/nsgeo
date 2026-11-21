# Task 3 (W5) report
Status DONE. Commit: see git log (feat(profile): the read-out shows the selection's length ...).
- profile_view.py readout_text: while `_dragging` and `_selection != (-1,-1)` returns "{d:.2f} m selected (trace a-b)" (d = abs(m(b+.5)-m(a+.5)) via metres_at_trace_units) or "{n} traces selected ..." without metres. Repaint: set_selection already calls update() on every drag move, so no extra strip repaint was needed.
- Convention: 0-based trace index, same as the pointer read-out (trace_at index); drag 20->80 gives _selection (20, 80), 1.00 m, 61 traces: the brief's numbers hold.
- Tests (test_plugin_profile_view.py, 6 new): drag text, release returns to cursor, no metres, mirrored (absolute), monkeypatched helper pair (120.00 m), set_selection without drag leaves read-out. RED on 73f342d: 4 failed (read-out showed the pointer text); the other 2 passed trivially (release / no-drag behaviours).
- Docs: getting-started.md Profile paragraph clause.
- Results: profile_view 143 passed, profile_dock 180, time_cutoff 13, pure 434 passed 4 skipped, ruff check + format clean.
