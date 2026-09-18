# Task 7 report: `lookup.py` -- Qt-free import planning, nearest trace, polygon corners

Commit: `4f43b08` "feat: Qt-free import planning, nearest-trace search, polygon corners"

## What was implemented

`packages/nsgeo-qgis/nsgeo_qgis/lookup.py`, following the brief's file structure and
public interface exactly:

- `trailing_number(stem) -> int | None` -- vendor-neutral trailing-sequence-number parse.
- `sort_files(paths) -> list[Path]` -- sorts by trailing number, files with none go last.
- `ImportOptions` (frozen dataclass) -- exact fields/defaults from the brief.
- `ImportRow` (mutable dataclass) with `.placeable` property -- exact fields/defaults.
- `plan_import(paths, options) -> list[ImportRow]` -- reads each file's header, trace
  count and `.DZX` sidecar, builds one row per file, then calls `recompute_offsets`.
- `recompute_offsets(rows, options) -> None` -- assigns offsets/direction/label/notes
  over included rows in table order; honours `offset_edited`; excluding a row pulls
  later rows into its slot.
- `rows_to_lines(rows, options) -> list[Line]` -- builds `Line.open(...)` with a
  `GridPlacement` per included+placeable row.
- `nearest_trace(coords_by_key, xy, tolerance) -> tuple[str, int, float] | None`.
- `PolygonCorners` + `corners_from_polygon(vertices, origin_index, plus_y_index)`.
- `identity_curve(t0_ns, dt_ns, n_samples) -> list[list[float]]`.

`.github/workflows/ci.yml`'s `lint` job now also type-checks
`packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (see "Deviation 3" below for why
`--follow-imports=silent` was added to that mypy invocation).

## TDD evidence

**RED** -- `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py` written verbatim from
the brief's Step 1 (plus two extra tests for defects found, see below), then run
before `lookup.py` existed:

```
.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -q
```
```
ImportError while importing test module '.../test_pure_lookup.py'.
packages/nsgeo-qgis/tests/pure/test_pure_lookup.py:8: in <module>
    from nsgeo_qgis.lookup import (
E   ModuleNotFoundError: No module named 'nsgeo_qgis.lookup'
```
Expected and correct: the module did not exist yet.

**GREEN** -- after implementing `lookup.py`:

```
.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -v
```
```
15 passed in 0.19s
```
All 13 of the brief's given tests pass, plus the 2 I added for defects found (below).

## Real-file validation (the point of this task)

`test_real_files_plan_cleanly` (marked `@needs_real_data`, runs because the worktree
has the ten symlinked `.DZT`/`.DZX` files) passed:

- `len(rows) == 10`.
- Trace counts read back exactly `[608, 625, 629, 658, 613, 608, 635, 666, 653, 606]`
  in FILE__001..010 order (via `sort_files`, not filesystem order).
- All ten lengths land in `(9.0, 13.0)` m at 60 traces/m -- 10.1 m to 11.1 m as the
  brief states.
- `sum(sidecar is not None) == 9` -- FILE__010 (no `.DZX`) correctly comes back `None`.
- FILE__007's sidecar has exactly 1 mark (verified directly against the real
  `FILE__007.DZX`, which has one `<WayPt><scan>634</scan>...</WayPt>`).
- FILE__008 (666 traces / 60 = 11.10 m) is the one that overruns the 11.0 m grid --
  its `note` contains `"exceeds"`, confirmed by inspection of the actual number.

This exercised real header parsing, real `.DZX` XML parsing, and the exact
over-length row this task was meant to validate -- not just synthetic self-consistency.

## Full verification suite

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
  -> 309 passed, 2 skipped   (was 294/2 before this task; +15 new tests, 0 regressions)

.venv/bin/ruff check .
  -> All checks passed!

.venv/bin/ruff format --check .
  -> 61 files already formatted

.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  -> Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
  -> 47 passed   (was 32; this command collects tests/pure too, so +15 matches exactly)
```

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (new)
- `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py` (new)
- `.github/workflows/ci.yml` (modified: `lint` job's mypy line)

## Self-review

- **Completeness**: every symbol in the brief's "Produces" list is implemented with
  the exact signature/defaults given. All consumers named in the task (Tasks 10, 11,
  17) have their exact dependency covered; `nearest_trace` is implemented and tested
  per the explicit instruction not to omit it despite having no Plan-2 consumer.
- **Naming**: matches the brief exactly (`ImportRow`, `ImportOptions`, `PolygonCorners`,
  etc.); private helpers (`_read_sidecar`, `_merge_note`) follow the underscore
  convention already used in `dzt.py`/`dzx.py`.
- **YAGNI**: I did not add anything beyond the brief's public surface. The two
  behavioural changes below are narrow, contained fixes to logic already present in
  the brief's reference code, not new features.
- **Tests verify behaviour, not implementation**: assertions check row contents,
  note substrings, ordering, and geometry outputs the way the brief's own tests do;
  my two added tests assert observable outcomes (note content survives + doesn't
  duplicate; a corrupt file doesn't erase the good rows), not internal call counts.
- **Output**: pytest, ruff, and mypy are all clean; no warnings suppressed, no
  `# noqa`/`# type: ignore` added anywhere.
- **Geometry care**: `corners_from_polygon` was checked by hand against the brief's
  fittable-rectangle test -- traced the adjacency logic (`o`, `y`, `x`, `far` index
  derivation) and confirmed the local/world correspondence is positionally consistent
  regardless of ring winding direction. Found no defect there; used as given.

## Deviations from the brief's reference code (with reasoning)

**Deviation 1 -- `recompute_offsets` no longer silently erases an unrelated note.**
The reference implementation always did `row.note = "; ".join(notes)` (or, in the
excluded branch, `"; ".join(notes) or row.note`) using only notes computed fresh in
that call. Combined with `plan_import`'s own `try/except DzxError` around `read_dzx`
(which sets `row.note` to a "sidecar unreadable: ..." message on a malformed
sidecar), this meant: the moment `recompute_offsets` ran -- which `plan_import`
always does, immediately, before returning -- that sidecar-parse note was
unconditionally overwritten and lost, for both the placeable/exceeds branch and the
not-placeable/excluded branch. This is undetectable by any of the brief's given
tests (none of the ten real `.DZX` files fail to parse), but it is a real bug: a
diagnostic message the user should see would silently vanish on return from
`plan_import`, and would vanish again on every subsequent call as the import dialog
(Task 11) recomputes offsets after each table edit -- which is exactly what the
function's own docstring says it is for.

Fix: added `_merge_note(note, marker, text)`, which replaces (or clears) only the
component of `note` starting with a given marker, leaving everything else -- e.g. a
sidecar-parse warning -- untouched. `recompute_offsets` now uses this for both of
its own derived notes ("time-triggered" and "exceeds grid size along"), making it
safe to call repeatedly without accumulating duplicates and without clobbering
notes it did not itself write. Covered by
`test_recompute_offsets_preserves_other_notes_and_is_idempotent`.

**Deviation 2 -- `plan_import` no longer lets one bad header crash the whole batch.**
The reference implementation called `read_header`/`trace_count` with no exception
handling. A single corrupt or non-DZT file anywhere in the import batch would raise
`DztError` uncaught, and `plan_import` would produce zero rows for the entire
batch -- including every other, perfectly good file. This is precisely the "crash
that kills the whole import" the brief's sharp edges explicitly warn against for the
`traces_per_metre <= 0` case; the same principle clearly applies to an unreadable
header, since an import dialog (Task 11) will be pointed at a folder a user picked,
where a stray non-GPR file is a realistic occurrence, not a hypothetical.

Fix: wrapped the header read in `except (DztError, OSError)`, producing a row with
`n_traces=None`, `length_m=None`, `traces_per_metre=0.0` (which naturally makes
`.placeable` False, reusing the already-tested not-placeable path), `include=False`,
and a `"cannot read header: ..."` note -- combined with any sidecar note via the
same `; `-joining convention already used elsewhere. Every other file in the batch
still gets a normal row. Covered by
`test_plan_import_survives_one_corrupt_header_among_good_files`.

Both fixes are additive/defensive only -- they do not change behaviour for any file
that reads cleanly, and all 13 of the brief's given tests (including the real-file
one) pass unmodified against the fixed implementation.

**Deviation 3 -- the brief's Step 4 mypy command is not actually clean as given.**
Running `mypy --config-file packages/nsgeo-core/pyproject.toml
packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py` reports 2
errors, not a clean pass:

```
packages/nsgeo-qgis/nsgeo_qgis/plugin.py:12: error: Cannot find implementation or
  library stub for module named "qgis.core"  [import-not-found]
packages/nsgeo-qgis/nsgeo_qgis/plugin.py:13: error: Cannot find implementation or
  library stub for module named "qgis.PyQt.QtWidgets"  [import-not-found]
```

Root cause: `lookup.py` lives inside the `nsgeo_qgis` package, so mypy also
processes `nsgeo_qgis/__init__.py` to resolve the package. `__init__.py`'s
`classFactory` does a (deliberately lazy, runtime-only) `from nsgeo_qgis.plugin
import NsgeoPlugin`; mypy's default `follow_imports=normal` type-checks that target
too, even though nothing in `lookup.py` itself imports it, and `plugin.py` imports
real `qgis.*` modules that aren't installed/stubbed in this environment (they only
exist in `.venv-qgis`). This isn't a `lookup.py` defect -- it's an artifact of
`--follow-imports`'s default reaching a sibling Qt-bound module through the
package's own lazy-import machinery.

Fix: added `--follow-imports=silent` to both the verification command and the CI
`lint` job's mypy invocation. I verified this doesn't weaken the check for the
files that matter: with the flag in place, I temporarily broke `trailing_number`'s
return type (changed `-> int | None` to `-> int` while the body still returned
`None`) and re-ran the exact command -- mypy still reported
`Incompatible return value type (got "int | None", expected "int")` for
`lookup.py` itself. `--follow-imports=silent` only suppresses errors *originating*
in modules reached solely through import-following (like `plugin.py`), not in
files given explicitly on the command line (`lookup.py`, and all of
`nsgeo-core/src/nsgeo`). The baseline core-only mypy run
(`mypy ... packages/nsgeo-core/src/nsgeo`, no flag, no `lookup.py`) is unaffected
and still reports "Success: no issues found in 22 source files".

## Concerns

None outstanding. All three deviations are narrow, verified both by targeted new
tests and by manual injection of a real error to confirm the fix doesn't mask
genuine problems. The real-file test is the primary validation this task asked for,
and it passed against the actual header/trace-count/sidecar facts given in the task
context, not just against synthetic fixtures.

---

# Fix report -- review round 1

Commit: `ecaa1e1` "fix: lookup.py review round 1 -- reversed placement, mirrored
corners, false time-triggered note", on top of `4f43b08`.

## Finding 1 -- reversed zigzag lines placed outside the grid

**Root cause.** `plan_import` set `row.start_along = options.start_along` for every
row, and `recompute_offsets` never revisited it. `GridPlacement.distance_along`
(`placement.py:65`) is `start_along + direction * (arange(n) / spm)`, so a
`direction == -1` row starting at the same point as a `direction == 1` row runs
*backward* from there, off the far side of the origin edge, rather than down into
the grid from the far end.

**Fix.** In `recompute_offsets`, a row with `direction == -1` now gets
`start_along = options.start_along + options.grid_size_along` when
`grid_size_along` is known (making it start at the far edge and run back toward the
origin, landing in `[start_along_base, start_along_base + grid_size_along]` as
intended). When `grid_size_along` is `None`, the row keeps the naive
`options.start_along` -- unchanged from before, since there's no far edge to compute
-- but now also gets a note (marker `"reversed direction"`) saying it cannot be
positioned without a known grid length, via the same `_merge_note` idempotent
merge used elsewhere, rather than silently guessing.

**Before/after, real files** (`ImportOptions(grid_id="A", axis="y", spacing=0.5,
grid_size_along=11.0)`, computed directly, not by hand):

Before (buggy -- every row's `start_along` was the shared `0.0` scalar regardless
of direction):

```
line             dir  start(before)  along[0]  along[-1]   in [0,11]?
FILE__001.DZT      1          0.000     0.000     10.117   True
FILE__002.DZT     -1          0.000     0.000    -10.400   False
FILE__003.DZT      1          0.000     0.000     10.467   True
FILE__004.DZT     -1          0.000     0.000    -10.950   False
FILE__005.DZT      1          0.000     0.000     10.200   True
FILE__006.DZT     -1          0.000     0.000    -10.117   False
FILE__007.DZT      1          0.000     0.000     10.567   True
FILE__008.DZT     -1          0.000     0.000    -11.083   False
FILE__009.DZT      1          0.000     0.000     10.867   True
FILE__010.DZT     -1          0.000     0.000    -10.083   False
```

After (fixed -- reversed rows start at the far edge):

```
line             dir   start  along[0]  along[-1]   in [0,11]?
FILE__001.DZT      1   0.000     0.000     10.117   True
FILE__002.DZT     -1  11.000    11.000      0.600   True
FILE__003.DZT      1   0.000     0.000     10.467   True
FILE__004.DZT     -1  11.000    11.000      0.050   True
FILE__005.DZT      1   0.000     0.000     10.200   True
FILE__006.DZT     -1  11.000    11.000      0.883   True
FILE__007.DZT      1   0.000     0.000     10.567   True
FILE__008.DZT     -1  11.000    11.000     -0.083   False
FILE__009.DZT      1   0.000     0.000     10.867   True
FILE__010.DZT     -1  11.000    11.000      0.917   True
```

Every reversed line now lands within the grid except FILE__008, whose `-0.083 m`
overrun matches the already-known real fact (666 traces / 60 traces-per-metre =
11.1 m in an 11.0 m grid, i.e. an overrun of about a tenth of a metre) rather than
the ~10 m a mirrored placement produced before. `along[-1]` uses `(n-1)/spm`, one
sample short of `length_m = n/spm`, which is why the overrun reads as 0.083 m here
against the 0.10 m figure quoted from `length_m` elsewhere -- an existing,
pre-defect fencepost distinction in the core placement code, not something this fix
introduces or touches.

**Covering test:** `test_reversed_lines_are_placed_within_the_grid_on_real_files`
in `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py` (marked
`@needs_real_data`) -- asserts, for all five reversed real lines, `along.max() ==
grid_size_along` and `along.min() > -0.15`, and that exactly one of them
(FILE__008) actually overruns.

## Finding 2 -- `corners_from_polygon` accepted a mirrored corner pick

**Root cause.** Adjacency was checked (`plus_y_index` must be one of the origin's
two ring-neighbours), but nothing distinguished *which* of the two valid neighbours
was intended. One choice yields a right-handed `(+X, +Y)` frame matching a real
`Grid`'s axes (`Grid.axes()` always has `cross(x_hat, y_hat) == +1`, since
`to_world` is a pure rotation, never a reflection); the other silently swaps the
two axes, i.e. mirrors the frame. `fit_grid_from_corners` forbids reflection by
construction, so a mirrored pick still returns a plausible-looking
origin/size/azimuth -- only `residual_rms` is large, and that number is captioned
elsewhere as "grid not square", which misdiagnoses this case.

**Fix.** After resolving `o` (origin), `x` (+X), and `y` (+Y), compute
`cross = (pts[x] - pts[o]) x (pts[y] - pts[o])` (2D scalar cross product). A
non-positive cross means the pick is mirrored (or degenerate); raise
`ValueError("these corners are mirrored: pick the other corner adjacent to the "
"origin for +Y")`, distinct from the existing "must be adjacent" message and from
anything `fit_grid_from_corners`'s residual reports.

**Covering tests:**
- `test_corners_from_polygon_rejects_a_mirrored_plus_y_pick` -- reproduces the
  reviewer's exact example (`origin_index=1, plus_y_index=2` on the brief's 5x11
  grid) and asserts it raises with `match="mirrored"`.
- `test_corners_from_polygon_mirror_check_is_winding_independent` -- builds the
  same four world points in reverse ring order and checks the *same physical*
  corner is still accepted as +Y and the *same physical* corner is still rejected
  as mirrored, confirming the check depends on world-coordinate handedness, not on
  which way the ring happens to be wound.

## Finding 3 -- an unreadable header was reported as time-triggered

**Root cause.** `recompute_offsets`'s not-placeable branch always added the
"time-triggered (traces/m = 0): cannot be grid-placed" note whenever
`traces_per_metre <= 0`, without checking *why*. Deviation 2 from the first round
(header-read resilience) synthesizes `traces_per_metre = 0.0` for a file whose
header could not be read at all (`n_traces is None`), so that row got both
`"cannot read header: ..."` (accurate) and `"...time-triggered..."` (fabricated --
nothing is known about the acquisition mode of a file that was never parsed).

**Fix.** Gated the time-triggered note on `row.n_traces is not None`. A row whose
header never read now keeps only `plan_import`'s own "cannot read header" note; a
row whose header read fine but reports `traces_per_metre <= 0` still gets the
time-triggered note exactly as before (unchanged behaviour for the case
`test_time_triggered_files_are_flagged_and_excluded` covers).

**Covering test:** extended
`test_plan_import_survives_one_corrupt_header_among_good_files` with
`assert "time-triggered" not in bad.note`.

## Commands run and output (fix round 1)

```
.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -v
```
```
18 passed in 0.23s
```

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
```
```
312 passed, 2 skipped in 0.81s
```
(was 309/2 before this round; +3 new tests plus 1 extended assertion in an
existing test, 0 regressions)

```
.venv/bin/ruff check .
```
```
All checks passed!
```

```
.venv/bin/ruff format --check .
```
```
61 files already formatted
```
(one intermediate run flagged `lookup.py`'s new `ValueError` message string as
unformatted -- a line-wrap-width issue, not a logic change; fixed with
`ruff format` and reverified clean)

```
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
```
```
Success: no issues found in 23 source files
```

```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
```
```
50 passed in 1.33s
```
(was 47; this collects `tests/pure` too, so +3 matches the three new tests exactly)

## Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (modified: `recompute_offsets`,
  `corners_from_polygon`)
- `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py` (modified: extended one
  existing test, added three new tests)

## Concerns

None outstanding. All three findings are fixed at the root cause identified by the
review, each with its own targeted test, and the real-file regression test for
Finding 1 reproduces the reviewer's own worked numbers exactly. The six items
explicitly marked out of scope for this round (NaN handling in `nearest_trace`,
`origin_index % 4` wraparound, missing `ImportOptions.__post_init__` validation,
duplicate hand-edited offsets, `identity_curve` for `n_samples <= 1`, and a stale
"exceeds grid size" note on an excluded row) were left untouched, as instructed.

---

# Fix report -- review round 2

Commit: `2793faa` "fix: lookup.py review round 2 -- reversed-direction note embedded
`_merge_note`'s own delimiter", on top of `ecaa1e1`.

## The finding

Round 1's fix for Finding 1 added a note for the case where a reversed
(`direction == -1`) row cannot be positioned because `options.grid_size_along` is
`None` (no far edge to start it from). That note's text was:

```
"reversed direction cannot be positioned without a known grid length along this axis; using start_along as given"
```

`_merge_note` splits `note` on `"; "` and drops only the parts starting with the
given `marker`. Because the text itself contained `"; "`, it split into two
components on the *next* call -- "...along this axis" (still starting with the
"reversed direction" marker, so recognised and removed) and "using start_along as
given" (starting with "using", so *not* recognised by the marker, so kept). The
fresh text was then appended in full again, so the note grew by one copy of the
orphaned fragment on every `recompute_offsets` call, and the whole note could never
be cleared -- even after the grid length became known and the row was correctly
repositioned -- because the orphaned fragment survived every subsequent merge.

## Reproduction (before fixing)

Simulated directly against `_merge_note`'s logic using the exact old message text,
to confirm the mechanism the review described (this is not the shipped code --
`_merge_note` now asserts against this input -- but the transformation logic is
identical to before round 2):

```
recompute 1: reversed direction cannot be positioned without a known grid length along this axis; using start_along as given
recompute 2: using start_along as given; reversed direction cannot be positioned without a known grid length along this axis; using start_along as given
recompute 3: using start_along as given; using start_along as given; reversed direction cannot be positioned without a known grid length along this axis; using start_along as given
recompute 4: using start_along as given; using start_along as given; using start_along as given; reversed direction cannot be positioned without a known grid length along this axis; using start_along as given
```

This matches the reviewer's own reproduction exactly (growing by one orphaned
"using start_along as given" fragment per call, prepended each time because it is
kept ahead of the freshly re-appended full text).

## The fix

1. **Message text**: replaced the embedded `"; "` with a comma, so the whole
   message is one component: `"reversed direction cannot be positioned without a
   known grid length along this axis, so start_along is used as given"`.
2. **Guard in `_merge_note`**: added `assert "; " not in marker and (text is None or
   "; " not in text)`, with a docstring paragraph naming `"; "` as the function's
   own delimiter contract, so a future note text that accidentally embeds it fails
   loudly (an `AssertionError` naming the offending text) instead of silently
   corrupting a row's note history. Audited every other `_merge_note`/note-building
   call site in the module for the same problem -- the "time-triggered" and
   "exceeds grid size along" messages, and `plan_import`'s one-time "cannot read
   header" join, contain no `"; "` and are unaffected.

## Reproduction (after fixing), via the real `_merge_note`

```
recompute 1: reversed direction cannot be positioned without a known grid length along this axis, so start_along is used as given
recompute 2: reversed direction cannot be positioned without a known grid length along this axis, so start_along is used as given
recompute 3: reversed direction cannot be positioned without a known grid length along this axis, so start_along is used as given
recompute 4: reversed direction cannot be positioned without a known grid length along this axis, so start_along is used as given
clearing (grid length now known): ''
```

Unchanged across repeated calls, and clears to `''` the moment `grid_size_along`
becomes known -- confirming both halves of the regression are fixed.

## Covering test

`test_reversed_direction_note_is_idempotent_and_clears_once_grid_length_is_known`
in `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`:
- Builds two synthetic files under `ImportOptions(..., grid_size_along=None)`
  (default `direction_mode="alternate"`, so the second row is reversed).
- Asserts the reversed row's note contains "reversed direction" after the first
  `plan_import`, then calls `recompute_offsets` three more times and asserts the
  note is **byte-identical** to after the first call, and that "reversed direction"
  occurs exactly once (not growing).
- Then recomputes once more with `grid_size_along=11.0` supplied, and asserts the
  note no longer mentions "reversed direction" (cleared, not left stale) and
  `start_along` is now `11.0` (correctly repositioned).

## Commands run and output (fix round 2)

```
.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -v
```
```
19 passed in 0.24s
```

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
```
```
313 passed, 2 skipped in 0.84s
```
(was 312/2 before this round; +1 new test, 0 regressions)

```
.venv/bin/ruff check .
```
```
All checks passed!
```

```
.venv/bin/ruff format --check .
```
```
61 files already formatted
```
(one intermediate run flagged the new assert's message string as unformatted --
line-wrap only, not a logic change; fixed with `ruff format` and reverified clean)

```
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
```
```
Success: no issues found in 23 source files
```

```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
```
```
51 passed in 1.32s
```
(was 50; +1 matches the one new test)

## Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (modified: `_merge_note`'s message
  text and docstring/guard; the reversed-direction note text in `recompute_offsets`)
- `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py` (modified: one new test)

## Concerns

None outstanding. Audited every note-building call site in the module for the same
delimiter hazard and found none other; the new assert in `_merge_note` also stands
as a standing guard against a future call site reintroducing it. The three items
marked out of scope for this round (the `cross == 0` collinear-rejection message,
`"traces/m = 0"` mislabelling a negative rate, and the `length_m` vs `(n-1)/spm`
fencepost) were left untouched, as instructed.
