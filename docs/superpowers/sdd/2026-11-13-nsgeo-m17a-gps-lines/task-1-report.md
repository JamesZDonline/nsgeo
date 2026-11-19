# Task 1 report: Read DZG files

Implemented nsgeo/io/dzg.py (RTK_FIXED, DzgError, DzgFix, DzgLog, dzg_for, read_dzg) to P2; exports in nsgeo.io (sorted: ASCII order puts RTK_FIXED after DzxMark); README rows; tests/dzg_data.py (write_dzg, local_xy, nmea, gga_body), test_dzg.py (11 cases incl. ddmm/hemisphere decode), test_dzg_real_files.py (3 tests, all RUN, none skipped).

Pairing: bad-checksum GGA orphans its pending GSSIS (unpaired); GSSIS after GSSIS, unparsable GSSIS, GGA without GSSIS, and trailing GSSIS all count unpaired. No-checksum sentences accepted. Traces checked rising and (with n_traces) in range.

TDD: wrote impl before tests by mistake; RED shown by moving dzg.py away: `pytest tests/test_dzg.py` -> ModuleNotFoundError: No module named 'nsgeo.io.dzg' (expected). GREEN: 14 passed for the new files.
Full core+pure: first run 1 failure (test_public_api: __all__ unsorted, RTK_FIXED placed first); fixed; rerun 1574 passed, 5 skipped. ruff check+format clean; mypy clean (earlier run, before the __all__ reorder only).

Files: packages/nsgeo-core/{README.md, src/nsgeo/io/__init__.py, src/nsgeo/io/dzg.py, tests/dzg_data.py, tests/test_dzg.py, tests/test_dzg_real_files.py}.
Concerns: none. Privacy: real-data tests assert counts, qualities, trace numbers, file names only.

## Fix round 1 (review: unpinned unpaired rules)

Tests only, no production change; no bug found. Added 5 tests to test_dzg.py. Mutants run on a scratch copy outside the worktree (scratchpad/mut), PYTHONDONTWRITEBYTECODE=1; baseline 16 passed there.
- M1 (orphaning of a dropped GGA disabled) -> FAILED test_a_dropped_gga_does_not_pair_the_next_gga_with_its_gssis (1 failed, 15 passed)
- M2 (GSSIS->GSSIS count removed) -> FAILED test_a_gssis_followed_by_a_gssis_is_unpaired
- M3 (end-of-file count removed) -> FAILED test_a_file_ending_in_a_gssis_counts_it_unpaired
- M4 (unparsable-trace count removed) -> FAILED test_a_gssis_with_an_unreadable_trace_is_unpaired_and_takes_no_fix (asserts unpaired == 2: the GSSIS, then its GGA)
- M7 (orphaning widened to any bad sentence) -> FAILED test_a_corrupt_other_sentence_between_a_pair_keeps_the_fix
Restored: 16 passed. Full core+pure: 1579 passed, 5 skipped. ruff check and format clean.
