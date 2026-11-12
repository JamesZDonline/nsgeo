# Task 6 report
Implemented mixed_clock_note (slices_plan), grid_time_bases + show_note warning (site_scope; only when bases are mixed, uses source_sent or source()), NSGEO_TIME_BASE in GeoTiffSliceWriter (covers coverage companion), SiteGridRecord.time_base, NSGEO_SITE_TIME_BASE (time_zero/radar/mixed via site_time_base), docstring.
TDD: tests written first; RED confirmed (import errors for mixed_clock_note; 3 export tests failed), then GREEN.
Only SiteGridRecord construction is in plan_site_export (no test constructs it).
Results: core+pure 1281 passed 5 skipped; whole QGIS suite 1724 passed (16:55); ruff check/format and mypy clean.
Concern: show_note now reads source_sent/source() each draw (cheap when source_sent set).

## Fix round 1
R15: grid_time_bases(session, source, site_engine=None) now reads ready grids from engine.provenance().steps, queued/preparing from the live preset, and skips no-lines/failed grids. R16: TIME_BASE_MIXED + combined_time_base (ValueError on empty) in slices_plan, shared by show_note and site_time_base; show_note docstring; warning is its own sentence (_then) in text and hint; test tidying; coverage companion + radar companion cases; preview/Not-drawn combo test.
RED: new R15 tests (prepared_with, losing_the_step, not_drawn_does_not_count, own_sentence) failed against 5a271d8 in a scratch copy (git archive, PYTHONDONTWRITEBYTECODE=1); 3-4 failed there, pass now.
Tests: site_scope+site_export+slice_export+site_engine 275 passed; reworked/new scope tests 7 passed; core+pure 1282 passed 5 skipped; ruff check/format and mypy clean.
