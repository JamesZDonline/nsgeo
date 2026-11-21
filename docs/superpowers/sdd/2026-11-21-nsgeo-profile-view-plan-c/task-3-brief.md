### Task 3: W5, distance while dragging a selection

**Files:** `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (`readout_text`, plus the drag path's repaint of the top strip); tests in `test_plugin_profile_view.py`.

**What changes:**
- While a range-selection drag is in progress (`self._dragging` with `self._selection != (-1, -1)`), `readout_text()` returns the selection text instead of the pointer:
  - `f"{d:.2f} m selected (trace {a}–{b})"`, with `d = abs(m(b + 0.5) − m(a + 0.5))` via `metres_at_trace_units`;
  - `f"{b - a + 1} traces selected (trace {a}–{b})"` when there are no metres.
- On release it goes back to the cursor read-out.
- The drag repaints the top strip whenever the text changes, the same way hover does.
- A selection set programmatically (`set_selection`) without a drag does not change the read-out.

**Tests:**
- On `_sampled` (60 traces/m), press-drag from trace 20 to 80 with the existing drag helpers. During the drag the read-out reads `"1.00 m selected (trace 20–80)"`; check the exact a and b the drag produces.
- After release it is the cursor read-out again.
- With no metres it reads `"61 traces selected (trace 20–80)"`.
- A mirrored line reads its own metres.
- Monkeypatching `metres_at_trace_units` changes the distance, which is the M17c road.

---

## After Plan C

- One scoped final review of Plan C's range.
- Republish the walkthrough with three re-checks, W14–W16, on the same profile and sandbox.
- Ask before merging.
