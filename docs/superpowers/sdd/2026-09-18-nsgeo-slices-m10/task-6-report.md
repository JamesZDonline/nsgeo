# Task 6 Report: Persistence — the `.npz` and the survey JSON

## What was implemented

Per the brief, in the brief's step order:

- `packages/nsgeo-core/src/nsgeo/slices/store.py` (new) — `save_cube`, `load_cube`, `CubeStoreError`, `_meta`, `STORE_VERSION`. Implemented verbatim from the brief's code block, with one change per the stated ruling: `typing.Union`/`typing.Dict` replaced with `str | Path` / `dict[str, Any]` (kept `Any`), since `ruff`'s `UP` rules (UP007/UP006) would otherwise fail and every module already carries `from __future__ import annotations`.
- `packages/nsgeo-core/src/nsgeo/slices/__init__.py` — added `from nsgeo.slices.store import CubeStoreError, load_cube, save_cube  # noqa: F401`.
- `packages/nsgeo-core/src/nsgeo/model/survey.py` — added `Site.cubes: dict[str, dict[str, Any]] = field(default_factory=dict)`, verbatim.
- `packages/nsgeo-core/src/nsgeo/project.py` — `save_site` writes `doc["cubes"] = site.cubes` only `if site.cubes:`; `load_site` reads `site.cubes = doc.get("cubes", {})`. `SCHEMA_VERSION` left at 1, verbatim.
- `packages/nsgeo-core/tests/test_slices_store.py` (new) — the brief's six tests verbatim, plus three tests I added for the standing discrimination requirement (see below).
- `packages/nsgeo-core/tests/test_project.py` — appended the brief's three cube-persistence tests verbatim. `json`, `Site`, `save_site`, `load_site` were already imported at the top, so no import changes were needed.
- `packages/nsgeo-core/tests/test_real_files.py` — appended the brief's Step 7 end-to-end test verbatim (only whitespace reformatted by `ruff format`, no semantic change).

No other files were touched. No production code beyond the brief's own snippets was added.

## TDD evidence

**RED** — before `store.py` existed and before `Site.cubes` existed:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py packages/nsgeo-core/tests/test_project.py -v
...
ModuleNotFoundError: No module named 'nsgeo.slices.store'
```

and, isolating the `Site.cubes` tests:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_project.py -v -k cubes
test_cubes_round_trip_through_the_survey_json FAILED
    AttributeError: 'Site' object has no attribute 'cubes'
test_a_site_with_no_cubes_writes_no_cubes_key PASSED   (trivially true before the field exists)
test_an_older_file_without_cubes_still_loads FAILED
    AttributeError: 'Site' object has no attribute 'cubes'
2 failed, 1 passed
```

Both failure reasons match the brief's Step 2 expectation exactly.

**GREEN** — after implementing `store.py`, `Site.cubes`, and the `project.py` persistence:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py packages/nsgeo-core/tests/test_project.py -v
...
28 passed in 0.23s
```

**Step 7 (real-data end-to-end), run in isolation:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -v -rs
...
test_a_cube_binned_from_real_files_is_covered_and_finite PASSED
33 passed in 0.39s
```

**Full core suite, before committing:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q -rs
........................................................................ [ 17%]
........................................................................ [ 34%]
...................................................s..s................. [ 51%]
........................................................................ [ 68%]
........................................................................ [ 85%]
.............................................................            [100%]
SKIPPED [1] packages/nsgeo-core/tests/test_schema.py:51: bandpass has required parameters by design
SKIPPED [1] packages/nsgeo-core/tests/test_schema.py:51: gain_curve has required parameters by design
419 passed, 2 skipped in 1.63s
```

419 = 406 baseline + 13 new (9 in `test_slices_store.py`, 3 in `test_project.py`, 1 in `test_real_files.py`). The only skips are the two pre-existing, deliberate schema skips named in the task brief — no new skips, no missing-data skips.

**Lint and types:**

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
105 files already formatted
$ ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
Success: no issues found in 29 source files
```

One brief-vs-lint mismatch, fixed silently at implementation time as the task instructions allowed: `test_slices_store.py`'s `test_round_trip_preserves_the_arrays_exactly`, copied verbatim from the brief, had a call wrapped across two lines that `ruff format` collapses to one (under the 100-column limit once collapsed). Ran `ruff format` on that one file; no semantic change, confirmed by the unchanged test outcome.

## Confirmation the real-data test genuinely ran, not skipped

`packages/nsgeo-core/tests/data/local/` contains ten real GSSI `.DZT` files (via symlink, as stated in the task). `test_real_files.py`'s `pytestmark = pytest.mark.skipif(not FILES, reason=...)` only skips the whole module when `FILES` is empty; it wasn't here. Running with `-rs`:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -v -rs
... 33 items collected, all PASSED, including
test_a_cube_binned_from_real_files_is_covered_and_finite PASSED
33 passed in 0.39s
```

No `SKIPPED` line appears anywhere in that run — the `-rs` summary is empty for this file, confirming the new end-to-end test (and every other real-file test) executed rather than skipped. In the full-suite run above, the only two skips reported are the pre-existing `bandpass`/`gain_curve` schema skips, matching the stated baseline exactly.

## Wrong-implementation discrimination evidence

For each numeric/structural claim I pinned, I constructed the corresponding wrong implementation, ran the test suite against it, confirmed the FAIL, then restored the correct file (verified by `md5sum` matching the pre-mutation hash) and confirmed PASS. All five items named in the brief's standing requirement were checked; a sixth (dtype-loss) needed a second, better-targeted test after the first one failed to discriminate — reported honestly below.

### 1. `allow_pickle=True`

Mutated `load_cube`'s `np.load(path, allow_pickle=False)` → `allow_pickle=True`.

```
FAILED test_load_cube_refuses_a_pickled_object_array
    Failed: DID NOT RAISE CubeStoreError
1 failed, 7 passed
```

Only the pickle-specific test caught it (as expected — the other 7 tests never construct an object-dtype array). Restored; all 9 tests pass (hash-verified restore).

### 2. Round-trip losing dtype

First attempt — removing the narrowing `.astype()` calls on the **load** side — did **not** discriminate:

```
9 passed  (mutant undetected)
```

Root cause: `make_cube()`'s inputs are already `float32`/`int32`, so `save_cube` writes narrow arrays to disk regardless of whether `load_cube` re-narrows; the existing `test_dtypes_survive_the_round_trip` only checks what `load_cube` returns, and since the disk file itself is narrow, removing the load-side cast is invisible.

This is a real coverage gap the brief's own tests didn't close (SliceCube does not enforce dtype in `__post_init__`), so I added `test_save_narrows_a_wider_input_dtype`, which:
- constructs a `SliceCube` with `mean` cast to `float64` and `count` cast to `int64` (legal, since there's no dtype check),
- calls `save_cube`,
- inspects the **on-disk** array dtype directly via a fresh `np.load`, not what `load_cube` hands back (since `load_cube`'s own cast would mask a save-side bug).

Mutated `save_cube` to skip its narrowing casts (`mean=cube.mean` instead of `mean=cube.mean.astype(np.float32, copy=False)`, same for `count`):

```
FAILED test_save_narrows_a_wider_input_dtype
    AssertionError: assert dtype('float64') == <class 'numpy.float32'>
1 failed, 8 passed
```

Restored (hash-verified); all 9 pass.

### 3. Round-trip losing a `Provenance` field, populated case

The brief's own `make_cube()` already populates `steps` (one dict) and `velocity` (non-`None`), so `test_round_trip_preserves_provenance` already exercises the populated case, not just `steps=()`/`velocity=None`.

Mutated `load_cube` to reconstruct `Provenance` field-by-field, dropping `steps` and `velocity` (hardcoding `steps=()`, `velocity=None`) instead of delegating to `Provenance.from_dict`:

```
FAILED test_round_trip_preserves_provenance
    Differing attributes: ['steps', 'velocity']
1 failed, 8 passed
```

Restored (hash-verified); all 9 pass.

### 4. `Site.cubes` written as an empty dict rather than omitted; older file failing to load

Mutant A — `save_site` always writes `doc["cubes"] = site.cubes` (dropping the `if site.cubes:` guard) and `load_site` never reads the key back (simulating a build that predates this task entirely, so `Site()`'s default `{}` is the only thing ever seen):

```
FAILED test_cubes_round_trip_through_the_survey_json
    AssertionError: assert {} == {'grid-a-standard': {...}}
FAILED test_a_site_with_no_cubes_writes_no_cubes_key
    assert 'cubes' not in {'schema_version': 1, 'grids': [], 'lines': [], 'cubes': {}}
2 failed, 1 passed
```

`test_an_older_file_without_cubes_still_loads` did not catch this particular mutant (dropping the read entirely still defaults to `{}`, which happens to match), so I also tried the more literal version of "an older file lacking that key fails to load":

Mutant B — restored the always-write behaviour to correct, but changed `load_site`'s `site.cubes = doc.get("cubes", {})` → `site.cubes = doc["cubes"]` (no default):

```
FAILED test_an_older_file_without_cubes_still_loads
    KeyError: 'cubes'
1 failed, 2 passed
```

This is exactly the scenario the brief's third test targets. Restored `project.py` (hash-verified); full `test_project.py` + `test_slices_store.py` run: 31 passed.

### 5. `load_cube` accepting a file missing a required array, returning a half-built cube

Mutated the required-key check to default each missing array/meta to placeholder zeros/an empty-ish metadata dict instead of raising:

```
FAILED test_loading_a_file_that_is_not_a_cube_fails_clearly
    Failed: DID NOT RAISE CubeStoreError
FAILED test_loading_a_file_missing_one_required_array_fails_clearly
    ValueError: mean must be (1, 1), got (2, 3)   [raised by SliceCube.__post_init__, not CubeStoreError]
2 failed, 7 passed
```

Both the brief's original "not a cube" test and the new one I added for a partial (missing-one-key) file catch this — one because nothing raises at all, the other because the wrong exception type propagates (a bare `ValueError` from `SliceCube.__post_init__`'s shape check, not `CubeStoreError`). Restored (hash-verified); all 9 pass.

### Restore verification

After every mutant, `md5sum` was checked against the pre-mutation hash of the touched file (`store.py`: `1957c8c2e326310bc73ffdac5657c589`; `project.py`: `226229dea7ad5afca15c1cc491c0c374`) before re-running the suite, confirming the working tree was genuinely back to the committed, correct implementation and not a lookalike.

## Files changed

- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/src/nsgeo/slices/store.py` (new)
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/src/nsgeo/model/survey.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/src/nsgeo/project.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/tests/test_slices_store.py` (new)
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/tests/test_project.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/tests/test_real_files.py`

Commit: `01afdec` — `feat(slices): persist cubes as .npz and record them in the survey JSON`, pushed to `origin/nsgeo-m10`.

## Self-review findings

- **Completeness:** all 8 brief steps done in order; `Site.cubes` and the persistence round trip match `presets`'s existing pattern exactly, as the brief intends. `M10 deliberately does not do` list checked — nothing here strays into GeoTIFF, GDAL, residency tiers, or mosaicking.
- **Quality:** names and docstrings match the brief verbatim except the typing ruling. No dead code, no unused imports (`ruff` confirms).
- **Discipline:** the only additions beyond the brief's literal text are the three discrimination tests, each directly required by the task's standing requirement and each demonstrated to catch a specific, named class of wrong implementation. No production code was added beyond the brief's snippets — `store.py` is the same shape and size the brief specifies.
- **Testing:** TDD was followed for the brief's own tests (RED confirmed via `ModuleNotFoundError`/`AttributeError` before GREEN). The three added tests were written GREEN-first against the already-implemented `store.py`/`project.py` (since those files already existed by the time the discrimination gaps were identified), then validated by deliberately breaking the implementation and confirming RED, then restoring — i.e., mutation-tested after the fact rather than TDD'd from scratch. This is disclosed rather than glossed over.
- **A brief-level observation, not a deviation:** in `load_cube`, `meta["frame"]`, `meta["z"]`, and `meta["provenance"]` are accessed after the `try/except` block that wraps the `np.load` call, so a `.npz` with all three required arrays but a malformed `meta` JSON (missing `"frame"`, say) would raise a bare `KeyError` rather than `CubeStoreError`. This matches the brief's code exactly and no brief test exercises it, so I implemented it as specified rather than extending scope on my own judgement. Flagging it in case the reviewer wants it tightened in a follow-up.

## Issues or concerns

None that block. The one thing worth the reviewer's attention is the disclosed `KeyError` edge case above, and the fact that the "dtype loss" discrimination test needed a rewrite after the first version failed to discriminate — both are called out explicitly rather than smoothed over.

---

# Fix report — review round 2

The review confirmed both disclosures and named three Important findings plus two promoted Minors. All five are fixed. Commit `2da595b` — `fix(slices): tighten load_cube's error contract and close cube-store review gaps`, pushed to `origin/nsgeo-m10`.

For every finding: RED against the exact prior (reviewed) code first, then the fix, then GREEN. For the two findings inside `load_cube` (error contract + `STORE_VERSION`), I additionally isolated each with a standalone revert-and-retest so the two are independently attributable, not just bundled RED/GREEN evidence.

## Finding 1 — `load_cube`'s error contract was far narrower than `CubeStoreError` claims

Added six tests to `test_slices_store.py`, each targeting one of the reviewer's probed escapes, plus a helper `_good_parts(tmp_path)` that saves a real cube and hands back its raw `(mean, count, meta-dict)` so a test can tamper with exactly one part of an otherwise-valid file.

**RED, against the code as it stood (pre-fix, i.e. the code the reviewer reviewed):**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py -v \
    -k "truncated or zip_magic or missing_a_key or null_metadata or disagrees_with_its_arrays or unsupported_store_version"
...
test_loading_a_truncated_file_fails_clearly                                    -> zipfile.BadZipFile escaped
test_loading_a_file_with_a_zip_magic_number_but_garbage_fails_clearly          -> zipfile.BadZipFile escaped
test_loading_a_file_with_metadata_missing_a_key_fails_clearly                  -> KeyError: 'z' escaped
test_loading_a_file_with_null_metadata_fails_clearly                          -> TypeError: 'NoneType' object is not subscriptable escaped
test_loading_a_file_whose_metadata_disagrees_with_its_arrays_fails_clearly     -> ValueError from SliceCube.__post_init__ escaped
test_loading_an_unsupported_store_version_fails_clearly                       -> DID NOT RAISE (no version check existed)
6 failed, 10 deselected in 0.32s
```

Every failure reason matches the reviewer's probe table exactly.

**Fix:** added `import zipfile`; widened the `except` tuple in `load_cube` to `(OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile)`; moved the `meta["frame"]`/`meta["z"]`/`meta["provenance"]` reads and the `SliceCube(...)` construction inside the `try` block (previously only the `np.load` and array/meta decoding were guarded); added the `STORE_VERSION` check (see Finding 2 below) inside the same guarded block.

**GREEN:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py -v
...
16 passed in 0.14s
```

## Finding 2 (promoted Minor) — `STORE_VERSION` written and never read

Isolated from Finding 1's fix by reverting only the version-check block (keeping the widened `except` tuple and the moved construction) and re-running:

```
$ # store.py with only the STORE_VERSION check removed
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py -v
...
test_loading_an_unsupported_store_version_fails_clearly FAILED
    Failed: DID NOT RAISE CubeStoreError
1 failed, 15 passed in 0.18s
```

Confirms the version check is the only thing that test depends on; everything else in Finding 1's fix stands independently. Restored (`md5sum` verified back to the fixed file, `ef76cde6e328faf7ff6b911edeec8a05`) and re-ran: `16 passed in 0.14s`.

## Finding 3 (Important) — `save_cube`/`load_cube` disagree about an extensionless path

Added `test_save_and_load_agree_on_a_path_without_the_npz_suffix` to `test_slices_store.py`.

**RED, against the prior code:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py -v -k npz_suffix
...
CubeStoreError: no cube file at .../grid-a
1 failed, 9 deselected in 0.11s
```

Reproduces the reviewer's exact finding.

**Fix:** added a private `_npz_path(path) -> Path` helper (`Path(path).with_suffix(".npz")`), called from both `save_cube` and `load_cube`, so an extensionless path resolves to the same file on both sides regardless of which function normalises internally.

**GREEN:** `10 passed in 0.12s` (full file at that point).

**Mutant isolation** — reverted only `load_cube`'s call to `_npz_path` back to plain `Path(path)` (keeping `save_cube`'s normalisation, since `np.savez_compressed` appends `.npz` on its own regardless):

```
FAILED test_save_and_load_agree_on_a_path_without_the_npz_suffix
    CubeStoreError: no cube file at .../grid-a
1 failed, 9 deselected
```

Confirms `load_cube`'s own normalisation is the operative half of the fix. Restored and re-verified: `10 passed`.

## Finding 4 (Important) — `cubes` was the only `load_site` collection with no type validation

Added a parametrized test to `test_project.py`:

```python
@pytest.mark.parametrize("bad_cubes", [["x"], 5, "slices/a.npz"], ids=["list", "int", "str"])
def test_cubes_must_be_an_object_keyed_by_id(tmp_path, bad_cubes): ...
```

**RED, against the prior code:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_project.py -v -k must_be_an_object
...
test_cubes_must_be_an_object_keyed_by_id[list] FAILED  Failed: DID NOT RAISE ProjectError
test_cubes_must_be_an_object_keyed_by_id[int]  FAILED  Failed: DID NOT RAISE ProjectError
test_cubes_must_be_an_object_keyed_by_id[str]  FAILED  Failed: DID NOT RAISE ProjectError
3 failed, 22 deselected in 0.18s
```

Reproduces exactly the three cases (`list`, `int`, `str`) the reviewer probed.

**Fix:** mirrored the `presets` guard immediately above it in `load_site`:

```python
cubes = doc.get("cubes", {})
if not isinstance(cubes, dict):
    raise ProjectError(
        f"{path}: 'cubes' must be an object keyed by id, got {type(cubes).__name__}"
    )
site.cubes = dict(cubes)
```

**GREEN:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_project.py -v
...
25 passed in 0.19s
```

(This RED→GREEN pair against the actual prior committed `project.py` is itself the mutant evidence — the "wrong version" here is exactly the code the reviewer reviewed, not a separately constructed mutant.)

## Finding 5 (promoted Minor) — the real-data test's persistence leg proved nothing about the data

Independently reproduced the reviewer's mutant first: patched `save_cube` to write `np.zeros_like(cube.mean/count, ...)` instead of the real arrays (metadata untouched), and confirmed the *existing* assertion (`load_cube(out).provenance == prov`) still passed:

```
$ # save_cube mutated to write all-zero mean/count
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -v -k cube_binned
test_a_cube_binned_from_real_files_is_covered_and_finite PASSED
1 passed, 32 deselected in 0.31s
```

Confirmed the gap independently. Strengthened the assertion in `test_real_files.py`:

```python
reloaded = load_cube(out)
assert reloaded.provenance == prov
np.testing.assert_array_equal(reloaded.count, cube.count)
np.testing.assert_allclose(
    reloaded.slice_levels(10, 28)[cube.coverage() > 0], covered, rtol=1e-4, atol=1e-5
)
```

**RED, with the strengthened assertion still against the all-zero mutant:**

```
FAILED test_a_cube_binned_from_real_files_is_covered_and_finite
    AssertionError: Arrays are not equal
    Mismatched elements: 400 / 1200 (33.3%)
1 failed, 32 deselected in 0.30s
```

Restored the real `save_cube` (`md5sum` verified: `ef76cde6e328faf7ff6b911edeec8a05`) and confirmed GREEN, real data still genuinely exercised:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -v -rs
...
test_a_cube_binned_from_real_files_is_covered_and_finite PASSED
33 passed in 0.39s
```

No skips reported anywhere in that run.

## Docstring fix (promoted Minor)

`test_loading_a_file_missing_one_required_array_fails_clearly`'s docstring said `` `mean` and `meta` alone are not a cube `` while the test actually saves `mean` and `count` (missing `meta`). Corrected the sentence to `` `mean` and `count` alone are not a cube either ``. No behavioural change; not separately mutant-tested since it's a comment-only fix.

## Full verification after all five fixes

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q -rs
........................................................................ [ 16%]
........................................................................ [ 33%]
......................................................s..s.............. [ 50%]
........................................................................ [ 66%]
........................................................................ [ 83%]
.......................................................................  [100%]
SKIPPED [1] packages/nsgeo-core/tests/test_schema.py:51: bandpass has required parameters by design
SKIPPED [1] packages/nsgeo-core/tests/test_schema.py:51: gain_curve has required parameters by design
429 passed, 2 skipped in 1.42s
```

429 = 419 (previous total) + 10 new tests (6 for Finding 1, 1 for Finding 3, 3 parametrized for Finding 4). The only skips remain the two pre-existing, deliberate schema skips — no new skips, no missing-data skips, confirming the real-data test still genuinely runs.

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
105 files already formatted
$ ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
Success: no issues found in 29 source files
```

## Files changed (round 2, in addition to round 1)

- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/src/nsgeo/slices/store.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/src/nsgeo/project.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/tests/test_slices_store.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/tests/test_project.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/tests/test_real_files.py`

## Remaining scope note

Per the coordinator's message, `save_cube`'s own error contract (a read-only directory/full disk raising a raw `OSError`; a non-JSON-serialisable `Provenance` field raising a raw `TypeError`) was explicitly deferred to the final whole-branch review and is intentionally untouched here.

---

# Fix report — review round 3

Round 2's own fix for the save/load path mismatch (`Path.with_suffix`) introduced a new, worse bug: it silently aliased two different dotted cube names onto the same file, destroying data. The reviewer found this plus two remaining `load_cube` escapes and a path-normalisation-before-the-guard regression. All four fixed. Commit `9ea8dd7` — `fix(slices): stop aliasing dotted cube names and close remaining load_cube escapes`, pushed to `origin/nsgeo-m10`.

## Finding A (Important) — `with_suffix` aliased dotted cube names onto one file

First reproduced the collision directly against the round-2 code, independent of the reviewer's numbers:

```
$ python3 -c "... np.savez_compressed('grid.v2', ...); print(list of files) ..."
'grid.v2' -> ['grid.npz']        # not 'grid.v2.npz'
```

Matches the reviewer's measurement exactly.

Added to `test_slices_store.py`:
- a parametrized `test_save_appends_npz_rather_than_replacing_a_dot_in_the_name` covering all four of the reviewer's names plus `cube.bin` (the reviewer's separate Minor about an unloadable name, fixed by the same rule change),
- `test_save_does_not_alias_two_dotted_names_onto_one_file` — the concrete collision: two *different* cubes (`make_cube(seed=1)`, `make_cube(seed=2)`, via a new optional `seed` parameter on `make_cube`) saved as `grid.v1` and `grid.v2`, asserting two distinct files exist and each loads back its own (different) array,
- `test_a_dot_in_a_directory_name_is_unaffected` — the regression guard for `/a.b/cube`.

**RED, against the round-2 `with_suffix` implementation:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py -v \
    -k "appends_npz or does_not_alias or directory_name_is_unaffected"
...
test_save_appends_npz_rather_than_replacing_a_dot_in_the_name[grid.v2-grid.v2.npz]              FAILED
test_save_appends_npz_rather_than_replacing_a_dot_in_the_name[Grid A v1.2-Grid A v1.2.npz]       FAILED
test_save_appends_npz_rather_than_replacing_a_dot_in_the_name[2026-09-18.grid-2026-09-18.grid.npz] FAILED
test_save_appends_npz_rather_than_replacing_a_dot_in_the_name[cube.tar.gz-cube.tar.gz.npz]       FAILED
test_save_appends_npz_rather_than_replacing_a_dot_in_the_name[cube.bin-cube.bin.npz]             FAILED
test_save_does_not_alias_two_dotted_names_onto_one_file                                         FAILED
    AssertionError: assert ['grid.npz'] == ['grid.v1.npz', 'grid.v2.npz']
test_a_dot_in_a_directory_name_is_unaffected                                                     PASSED  (unaffected, as expected)
6 failed, 1 passed, 16 deselected in 0.18s
```

**Fix:** `_npz_path` rewritten to mirror numpy's own rule exactly:

```python
p = Path(path)
return p if p.suffix == ".npz" else p.with_name(p.name + ".npz")
```

**GREEN:** `23 passed in 0.19s` (full file at that point).

**Mutant verification** — reverted `_npz_path` back to `Path(path).with_suffix(".npz")` and re-ran the same six tests:

```
FAILED test_save_appends_npz_rather_than_replacing_a_dot_in_the_name[grid.v2-...]  (and the other 4 parametrized cases)
FAILED test_save_does_not_alias_two_dotted_names_onto_one_file
    AssertionError: assert ['grid.npz'] == ['grid.v1.npz', 'grid.v2.npz']
6 failed, 1 passed, 16 deselected in 0.17s
```

Identical failure set to the RED phase, confirming the fix is what the tests actually depend on. Restored (`md5sum`-verified: `349ff42862bf07d6c06b5b11de72959f`) and re-ran: `23 passed`.

## Finding B (Important) — two escapes remained inside the classes `load_cube`'s docstring named

Independently reproduced both against the round-2 code before writing tests:

```
zero-byte file  -> escaped as EOFError No data left in file
short origin ([1.0] instead of [x, y]) -> escaped as IndexError list index out of range
```

Added `test_loading_a_zero_byte_file_fails_clearly` and `test_loading_a_file_with_a_too_short_origin_fails_clearly` to `test_slices_store.py`.

**RED:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py -v -k "zero_byte or too_short_origin"
FAILED test_loading_a_zero_byte_file_fails_clearly            -> EOFError escaped
FAILED test_loading_a_file_with_a_too_short_origin_fails_clearly -> IndexError escaped
2 failed, 23 deselected in 0.24s
```

**Fix:** added `EOFError` and `IndexError` to the `except` tuple.

**GREEN:** `25 passed in 0.17s`.

**Mutant verification, isolated per exception type** — removed only `EOFError` (kept `IndexError`):

```
FAILED test_loading_a_zero_byte_file_fails_clearly    -> EOFError escaped
1 failed, 1 passed, 23 deselected
```

Restored, then removed only `IndexError` (kept `EOFError`):

```
FAILED test_loading_a_file_with_a_too_short_origin_fails_clearly -> IndexError escaped
1 failed, 1 passed, 23 deselected
```

Each addition is independently attributable to its own test. Restored (`md5sum`-verified: `eac34530e4b1aebc5e8ebccd61a7997e`); `25 passed`.

## Minor — `_npz_path` ran before `load_cube`'s guard

Added `test_loading_a_degenerate_path_fails_clearly`, parametrized over `""` and `"."`.

**RED, against the round-2 code:**

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py -v -k degenerate
FAILED test_loading_a_degenerate_path_fails_clearly[]   -> ValueError: PosixPath('.') has an empty name
FAILED test_loading_a_degenerate_path_fails_clearly[.]  -> same
2 failed, 25 deselected in 0.15s
```

**Fix:** wrapped the normalisation call in its own guard:

```python
try:
    path = _npz_path(path)
except ValueError as exc:
    raise CubeStoreError(f"{path!r} is not a usable cube path: {exc}") from exc
```

**GREEN:** `27 passed in 0.18s`.

**Mutant verification** — reverted to the unguarded `path = _npz_path(path)`:

```
FAILED test_loading_a_degenerate_path_fails_clearly[]   -> ValueError escaped
FAILED test_loading_a_degenerate_path_fails_clearly[.]  -> ValueError escaped
2 failed, 25 deselected
```

Restored (`md5sum`-verified: `458dd4d92818ef5c09dfa3af03915d66`); `27 passed`.

## Full verification after all four fixes

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q -rs
........................................................................ [ 16%]
........................................................................ [ 32%]
......................................................s..s.............. [ 48%]
........................................................................ [ 65%]
........................................................................ [ 81%]
........................................................................ [ 97%]
..........                                                               [100%]
SKIPPED [1] packages/nsgeo-core/tests/test_schema.py:51: bandpass has required parameters by design
SKIPPED [1] packages/nsgeo-core/tests/test_schema.py:51: gain_curve has required parameters by design
440 passed, 2 skipped in 1.20s
```

440 = 429 (previous total) + 11 new tests (5 parametrized + 1 collision + 1 directory-dot for Finding A; 2 for Finding B; 2 parametrized for the Minor). Only the two pre-existing, deliberate schema skips remain.

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -v -rs
...
test_a_cube_binned_from_real_files_is_covered_and_finite PASSED
33 passed in 0.36s
```

No skips reported — the real-data test still genuinely executes.

```
$ ./.venv/bin/ruff check .
All checks passed!
$ ./.venv/bin/ruff format --check .
105 files already formatted
$ ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
Success: no issues found in 29 source files
```

## Files changed (round 3)

- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/src/nsgeo/slices/store.py`
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10/packages/nsgeo-core/tests/test_slices_store.py`

## Remaining scope note (unchanged)

`save_cube`'s own error contract remains deferred to the final whole-branch review, as does `frame_doc["crs"]` passing through unconverted (a metadata `"crs": null` loads with `frame.crs is None`, uncomplained-about) — both were explicitly called out as not in scope for this round.
