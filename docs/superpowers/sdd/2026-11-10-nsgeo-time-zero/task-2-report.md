# Task 2 report
Commit 904b3e6, pushed. Files: profile_dock.py, plugin.py, tests in time_cutoff, gain_strip, profile_dock, param_form.
Implemented per brief: _shown_radargram, shown_zero_ns, step_input_zero_ns; _set_axes_holding compares t0/dt; _render sets rg + refreshes picks; _refresh_picks, _show_cutoff, _on_cutoff_dragged (no-write when equal to drawn); plugin _sync_gain_strip/_on_gain_points via _points_on_clock (retime_ns), no-write compared on shown clock.
RED: 6 new tests failed (AttributeError shown_zero_ns / axis -11.086). Two tests needed set_profiles to render (fixtures were header-only); fixed in test.
GREEN: 6 brief files, 359 passed. ruff check/format, mypy clean.
param_form test already passed after Task 1; updated ground truth/docstring (t0 == 0.0).
No failures in my files from other tasks.

## Fix round 1
Fixed: I1 (show_gain_strip takes step-clock points + input_zero_ns, converts at draw, incl. deferred replay); M2 (removed _shown_radargram=None in _render rg-None branch); M3 (conversion inside try, TypeError/ValueError reported); M4 (unmoved tests use zero/times with inexact round trip, precondition asserted); M5 (retime_ns grouped t + (from - to), core test, cutoff stored-value-unchanged guard); M6 (ruler-None test, removed duplicate _refresh_picks in _show_line except header-only branch, docstring break).
Tests: QGIS time_cutoff, gain_strip, profile_dock, param_form, processing_dock: 261 passed; core test_processing_base: 37 passed; ruff check/format, mypy clean.
Note: tests were written alongside the fix, not run RED first.
