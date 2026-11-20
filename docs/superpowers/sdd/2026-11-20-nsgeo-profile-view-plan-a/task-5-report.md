# Task 5 report: cursor read-out (#11)

Commit a6d72e3, pushed.

Implemented in ui/profile_view.py: `_hover` (set in `_handle_mouse_move` before any early return, None off the image), `readout_text()`, `_paint_readout` (9 pt, AXIS_COLOUR, right/vcentre in QRectF(r.left(),0,r.width(),MARGIN_TOP), called after `_paint_axes`), `leaveEvent` (try/except, logs). Metres only via `metres_at_trace_units`.

Tests: 7 view tests (sample, units, no metres/velocity, depth left out above 0, clears off image, clears on leave, mirrored line metres) + 1 cut test (readout, axis menu "sample", repaint, 1:1 state).

RED (stub readout_text returning ""): `7 failed, 1 passed` for -k "readout or mirrored_line_reads"; e.g. `assert '' == '1.67 m along (trace 100) · 10.00 ns · 0.50 m deep'`. The leave test passed on the stub, so I added a non-empty pre-assertion before leaving.
GREEN: profile_view/cut/dock files 290 passed; real_data 52 passed; pure 418 passed 4 skipped; ruff check and format --check clean.

Notes: the one warning (ruler.py RuntimeWarning) is from an existing test. Hover is set before pan/drag early returns so the read-out tracks while dragging; update() is called per mouse move.

## Fix round 1

Changes: (1) mirrored test asserts `D[i]` for i = 10, 11, 150 and the helper float to 1e-9; (2) new cut test with `session.resolved_velocity` raising KeyError, unconditional asserts (no velocity, 1:1 greyed, read-out works, no "deep"); (3) message_log checks in the view and cut tests, plus a pixel check of the top strip (ink while hovering, none after Leave); (4) clears-off-image test hovers the bottom and top margins at an image column; (5) `readout_text` returns "" when the stored hover is outside the current transform (test hovers bottom-right, shrinks height); (6) helper-pair test patches `metres_at_trace_units` to `np.asarray(42.0)`; (7) the RuntimeWarning came from `test_true_scale_is_off_where_the_metre_span_is_not_finite`; wrapped in `np.errstate(invalid="ignore")`, no production change; (8) the move handler repaints only `QRect(0,0,width,MARGIN_TOP)` and only when the read-out text changes.

RED (command: `qgis_tests.sh test_plugin_profile_view.py test_plugin_profile_cut.py -q -k "readout or mirrored_line_reads"`, each against a temporary mutant, restored afterwards):
- `metres_at_trace_units(i + 1.0)`: 5 failed (mirrored test, sample, units, depth-above-zero, shrink), e.g. `'1.68 m along...' == '1.67 m along...'`.
- `_paint_readout` call removed: painted-pixel test failed.
- `_paint_readout` raising: painted test and the cut test failed (log message).
- `inside` check removed: `test_the_readout_clears_off_the_image` failed, `'0.47 m along...· 1.59 m deep' == ''`.
- no stale-hover guard (before the fix): shrink test failed, `'3.30 m along...· 1.59 m deep' == ''`.
Notes: the shrink test (item 5) failed in every run of those mutants because the guard was not yet written; the first shrink test (width shrink) passed without the guard, so it was changed to a height shrink.

GREEN: profile view/cut/dock files 293 passed with no warnings; real_data 52 passed; pure 418 passed 4 skipped; ruff check and format --check clean.
