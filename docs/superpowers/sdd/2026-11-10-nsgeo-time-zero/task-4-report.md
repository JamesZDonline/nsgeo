# Task 4 report: pick rows follow their line's zero

Commit fe22e1c (pushed).

Implemented: Pick.zero_ns + radar_ns; picks column zero_ns after time_ns (migrates via _ensure_table -> _rebuild_picks, untouched path); write_pick/_row_to_pick; add_pick(zero_ns=) (radar clamp, stored from line_zero, None -> radar clock); SiteLayers.follow_zero and _on_line_clock_changed (stack_changed + line_loaded; skips preview-only key, keys with no rows, unknown zero; guarded, Critical log); plugin._on_pick_requested passes shown_zero_ns (None-dock guarded); dock _refresh_picks uses p.radar_ns; follow_lines docstring.

Design note: follow_zero emits session.picks_changed when it wrote rows, so the dock redraws regardless of signal order. Writes via data provider only.

TDD: tests written first; RED = 11 failed, 9 passed on the selected subset (no column, no zero_ns kwarg, no following). GREEN after implementing. Step 4 files: 500 passed (300 s), including the real-data test and every existing picks migration test. ruff check, ruff format --check, mypy: clean.

Tests added: layers (pre-time-zero migration with dirty check, add time zero, threshold change, apply-to-grid on unopened line, hover never rewrites, channel switch, unreadable line, follow_zero skips null trace, real line first break) and session (relabelled view pick, unknown-zero fallback).

Concerns: an old row (zero NULL) on a line with a time_zero stack is re-measured when that line loads (radar time preserved, per spec). Not a site-open conversion, but it writes the gpkg on line_loaded of a working/non-preview line.

## Fix round 1
Changes: R10 three-slot wiring in layers.py (stack_changed -> any key, load=True; line_opened -> current key only, load=False; line_loaded -> current key only, load=False; shared guarded `_follow_key`, docstrings state the guarantees). R11: follow_zero skips fids with pending time_ns/zero_ns edits in layer.editBuffer() (read only). Minors 3 (radar_ns via retime_ns), 4 (message_log asserted, no "could not move the picks" message), 5 (no-time row case), 6 (local renamed `zero`), 7 (docstrings).
Tests added: promoting a hover-loaded line follows; apply-to-grid on a previewed line follows; edit-buffer time not shifted; hover test extended with stale-hover case.
RED: scratch copy of fe22e1c (outside worktree, PYTHONDONTWRITEBYTECODE=1) with the new test file: 4 failed (hover/stale, promoting, previewed, edit mode). GREEN: layers+session+profile_dock+map_link+loads = 400 passed. ruff check/format and mypy clean.
