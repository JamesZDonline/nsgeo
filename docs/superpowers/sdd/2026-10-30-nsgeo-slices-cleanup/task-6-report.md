# Task 6 report (commit fb14a06, pushed)

## Steps
1. #75 cubes-stay-clean: `test_opening_a_survey_that_has_saved_cubes_stays_clean` added; passed at once.
2. #75 import pick-up: two `..._after_save_and_reopen` tests added (shared helpers `_reopened_with_a_late_import`, `_dispose`); both passed at once. The new key is found by diffing the grid's keys before/after, rather than hard-coding it.
3. #75 self-comparing assert: C's expected velocity is `plugin.session.resolved_velocity(<C's first key>)`, with an assert it is neither v_a nor v_b. Passed.
4. #75 export tests: all seven `ds = None` were already inside `finally:`; replaced by `ds.Close()`.
5. #54: `_sweep` docstring now says both files are kept (`self.path` and live `source()`); module docstring says stale files go at the end of the superseding tick. New test `test_a_persistently_failing_update_from_a_corrupt_file_keeps_the_scratch_folder_bounded` (real `_repoint`, `_write` patched to write junk). First draft asserted `<= 2` entries and failed (3: the kept file's `.aux.xml` sidecar); the assert now checks every entry is the layer's source or `self.path` (plus sidecars) and at most two `.tif` files, and the layer source exists.
6. #75 `_remember_source` docstring: names `restore_cube` as a third caller; says it writes the source only, the resolution being remembered by `_on_resolution_edited` and `restore_cube`.

## Keep-guard mutation table (PYTHONDONTWRITEBYTECODE=1, original copied to scratchpad `slice_layer.py.orig` first, docstring edits made after)
| Mutant | Result | Restore |
|---|---|---|
| M1: `keep = {self.path.name}` -> `keep = set()` | SURVIVED both new/old failing-update tests (3 passed); also survived whole slice_layer + slice_export files (49 passed) | cp + cmp OK |
| M2: remove `keep.add(<live source name>)` | CAUGHT by the new corrupt-file test (1 failed; faked test passed) | cp + cmp OK |

FINDING (M1): the `self.path` keep is redundant while the layer is alive, because `self.path` is only assigned after a successful repoint/create, so it equals the live source. It only matters when the layer is gone/None (`_layer_gone`) after a good tick, and no test covers that. I reported it rather than weakening the claim; a third test (layer removed from the project, then a failing write, assert `self.path` still exists) would pin it. The docstring I wrote says they differ "when setDataSource took a file the layer cannot read": true for the corrupt-file case (source becomes the junk path, self.path stays the last good one), which is why M2 is caught.
Before commit: `git diff` showed no change to the `keep` lines in `_sweep`.

## Verification
- core+pure: 821 passed, 3 skipped
- qgis: 1238 passed (9m32s)
- ruff check clean; ruff format --check: 155 files formatted (one file reformatted by me)
- mypy: no issues in 36 files

## Files changed
slice_layer.py, ui/slices_dock.py (docstrings only); tests: test_plugin_slices_dock.py, test_plugin_site_scope.py, test_plugin_slice_export.py, test_plugin_slice_layer.py.

## Self-review
No behaviour change in source. Docstrings avoid `_note_z_edit` / `z_custom`. Concern: M1 survivor above.

# Fix round 1 (commit follows fb14a06)

My earlier "M1 is redundant" finding was wrong: in the corrupt-file case the layer is invalid on the junk file and `self.path` still names the last good one.

1. Added to the corrupt-file test: `assert not sl.layer.isValid() and read != sl.path` and `assert sl.path.exists()`.
2. `_sweep` docstring: the kept files are the same after a good tick and after a `setDataSource` that raised; they differ when it took an unreadable file.
3. Summary line changed (no longer "does not read"); `self.path` described as the file the last successful repoint set, or the one `_create_layer` was given.
4. Default-choice reopen test: B->A round trip first, asserts `lines` is None before save and after reopen (stored-null branch), then imports.

Mutation (scratch copy slice_layer.py.orig2, PYTHONDONTWRITEBYTECODE=1, cp + cmp restore after each, no guard diff before commit):
| Mutant | Result |
|---|---|
| unmutated | 3 passed |
| M1 (`keep = set()`) | CAUGHT by the corrupt-file test (1 failed) |
| M2 (drop live-source keep) | CAUGHT by the corrupt-file test (1 failed) |

Tests: test_plugin_slice_layer.py + test_plugin_slices_dock.py 123 passed; ruff check and format clean.
