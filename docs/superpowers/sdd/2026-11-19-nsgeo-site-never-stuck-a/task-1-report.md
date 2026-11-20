# Task 1 report
Implemented SliceEngine.pending_tasks, SiteEngine.busy_report (never raises), plugin_testing.wait_for_site; every asserting site wait in the engine/scope/export test files now uses wait_for_site (grep for "assert .*wait_until_idle" is empty). Two new tests added.
RED: with source reverted, the two new tests failed: AttributeError: 'SiteEngine' object has no attribute 'busy_report' (2 failed). GREEN: same command, 2 passed.
Three site files: 263 passed in 799s. ruff check/format clean. No #196 flake seen.
Files: site_engine.py, slices_engine.py, plugin_testing.py, test_plugin_site_{engine,scope,export}.py.
Notes: the sed rewrite dropped the optional assert messages ("the site did not finish preparing", "the queue stalled behind the dropped grid"); wait_for_site's message replaces them. Added imports (threading, Line, wait_for_site).

## Fix report
Added test_the_busy_report_reports_a_failing_probe_instead_of_raising (SliceEngine.pending_tasks patched to raise RuntimeError("probe broke") on a site with engine A). Fixed the pending_tasks docstring (the `_pending` half of has_live_task).
RED (guard's except narrowed to ZeroDivisionError): 1 failed, `E RuntimeError: probe broke`. Guard restored (site_engine.py has no diff vs the commit).
GREEN: `qgis_tests.sh test_plugin_site_engine.py -k "busy_report or names_what_holds" -q`: 3 passed. ruff check and format clean.
