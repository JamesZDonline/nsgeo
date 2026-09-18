# Task 3 report: `nsgeo.velocity` and velocity on `Grid` and `Line`

## What I implemented

1. **`packages/nsgeo-core/src/nsgeo/velocity.py`** (new) — `VelocityModel`, a frozen
   dataclass wrapping `layers: tuple[tuple[float, float], ...]` (two-way time in ns,
   interval velocity in m/ns). Validates in `__post_init__`: non-empty, first top is
   0.0, tops strictly increasing, velocities positive and finite. Provides:
   - `constant(v)` / `from_dielectric(epsr)` constructors (`from_dielectric` rejects
     `epsr <= 0`)
   - `is_constant`, `surface_velocity` properties
   - `velocity_at(times_ns)` / `depth_at(times_ns)` — vectorised numpy lookups;
     `depth_at` integrates `v/2` piecewise over two-way time, so depth is continuous
     and strictly increasing wherever velocity is positive, including for times
     before the first boundary (extrapolated with the first layer's velocity) and
     past the last boundary (extrapolated with the last layer's velocity)
   - `to_dict()` / `from_dict(doc)` round-trip helpers
   - Module constant `C_M_PER_NS = 0.299792458`
   - `resolve_velocity(line, grid) -> VelocityModel`: line override, then grid's
     model, then `VelocityModel.from_dielectric(line.header.epsr)`. Takes `Any` for
     both parameters and duck-types on `.velocity` / `.header.epsr` — this module is
     imported *by* `geometry/grid.py` and `model/survey.py`, so importing `Grid` or
     `Line` here for type hints would create a cycle.

2. **`packages/nsgeo-core/src/nsgeo/geometry/grid.py`** — added
   `velocity: VelocityModel | None = None` as the last field of `Grid` (positional
   construction of existing `Grid(...)` calls is unaffected).

3. **`packages/nsgeo-core/src/nsgeo/model/survey.py`** — added
   `velocity: VelocityModel | None = None` as the last field of `Line`; extended
   `Line.open(cls, path, placement, velocity=None)` to thread it through.

4. **`packages/nsgeo-core/src/nsgeo/project.py`** — serialisation, symmetric with the
   existing `stack` handling:
   - `_grid_to_dict`: builds a local `doc` dict, adds `doc["velocity"] =
     grid.velocity.to_dict()` only when set
   - `_grid_from_dict`: passes `velocity=VelocityModel.from_dict(doc["velocity"])
     if "velocity" in doc else None`
   - `save_site`'s line loop: adds `entry["velocity"] = line.velocity.to_dict()`
     only when set
   - `load_site`: passes the equivalent conditional `velocity=` into `Line.open(...)`
   - The `"stack" in entry` try/except block that re-raises as `ProjectError`
     (added in Task 1) is untouched — I inserted the new `Line.open(...)` call
     immediately before it without altering its body.

5. **`packages/nsgeo-core/tests/test_velocity.py`** (new) — the brief's test file,
   copied verbatim then auto-reformatted by `ruff format` for one line-length wrap
   (see Deviations).

## What I tested and the results

- `packages/nsgeo-core/tests/test_velocity.py`: 11 passed (including the
  real-header test — real `.DZT` symlinks were present in
  `tests/data/local/`, so it ran rather than skipped).
- Full core suite: `264 passed, 2 skipped` (up from the stated baseline of
  `253 passed, 2 skipped`; the 2 skips are the same pre-existing ones, unrelated
  to velocity — confirmed the real-header velocity test is not one of them).
- `ruff check .` — all checks passed.
- `ruff format --check .` — all 44 files formatted (after I ran `ruff format` on
  the two files it flagged, see below).
- `mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo`
  — `Success: no issues found in 21 source files`.
- Explicit import check: `import nsgeo.velocity; import nsgeo.geometry.grid;
  import nsgeo.model.survey; import nsgeo.project` all succeed — no circular
  import from `Grid`/`Line` importing `VelocityModel`.
- `test_boundary.py` (the qgis/PyQt/matplotlib/scipy import-boundary walk):
  2 passed — `velocity.py` imports only `math`, `dataclasses`, `typing`, `numpy`.

## TDD Evidence

**RED**

Command: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_velocity.py -q`

Relevant output (before `velocity.py` existed):
```
ImportError while importing test module '.../tests/test_velocity.py'.
packages/nsgeo-core/tests/test_velocity.py:19: in <module>
    from nsgeo.velocity import C_M_PER_NS, VelocityModel, resolve_velocity
E   ModuleNotFoundError: No module named 'nsgeo.velocity'
1 error in 0.21s
```
This is the expected failure per the brief's Step 2 — the module did not exist yet,
so nothing beyond the import could have run. It rules out a false-positive pass
from a stale module or typo in the test file.

**GREEN**

Command: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_velocity.py -q -v`

Output:
```
collected 11 items
packages/nsgeo-core/tests/test_velocity.py ...........   [100%]
11 passed in 0.11s
```

Full-suite command: `.venv/bin/python -m pytest packages/nsgeo-core/tests -q`
```
264 passed, 2 skipped in 0.67s
```

Lint/type commands and output are in the "What I tested" section above — all clean.

## Files changed

- `packages/nsgeo-core/src/nsgeo/velocity.py` (new)
- `packages/nsgeo-core/src/nsgeo/geometry/grid.py` (modified)
- `packages/nsgeo-core/src/nsgeo/model/survey.py` (modified)
- `packages/nsgeo-core/src/nsgeo/project.py` (modified)
- `packages/nsgeo-core/tests/test_velocity.py` (new)

Commit: `f493568` — "feat: add a layered velocity model, stored per grid with a
line override" (message exactly as given in the brief, plus the required
`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer). Staged only
`packages/nsgeo-core` as instructed; an unrelated untracked `.venv-qgis/`
directory in the worktree was left alone.

## Self-review findings

- **Completeness against the brief**: all four deliverables (velocity.py,
  Grid.velocity, Line.velocity/Line.open, project.py serialisation) and the test
  file are present, matching every signature and test case in the brief verbatim
  (module docstring, class, methods, `resolve_velocity`).
- **Naming**: matches the brief exactly (`VelocityModel`, `layers`, `top_ns` /
  `v_m_ns` dict keys, `C_M_PER_NS`, `resolve_velocity`). No renames.
- **YAGNI**: no layered-fitting routine, no layered UI, no extra convenience
  methods beyond what the brief and its tests require. `resolve_velocity` stays
  duck-typed and free of any import of `Grid`/`Line`, exactly as documented.
- **Tests verify behaviour, not implementation**: each test in
  `test_velocity.py` asserts on physical/observable outcomes (depth values,
  raised-error message substrings, dict shape, resolution order via real
  `Grid`/`Line` objects and `save_site`/`load_site` round-trips) rather than
  reaching into internals. The two "resolve" tests and the project round-trip
  test exercise the real `Grid`/`Line`/`project` code paths, not mocks.
  I did not weaken any assertion to make it pass — every test passed against the
  brief's own reference math and validation messages once implemented.
- **Numerical edge cases** (per the brief's explicit callout), each pinned by a
  test that already existed in the brief and that I did not alter:
  - negative time (before t0): `test_negative_time_gives_negative_depth` —
    depth extrapolates linearly using the first layer's velocity, giving a
    negative depth. This is correct for a SIR-4000 file whose `position_ns` is
    about -11.09 ns before time-zero correction.
  - exactly on a layer boundary: `test_two_layers_integrate_piecewise` checks
    `velocity_at` at `t=20.0` (the second layer's boundary) returns the
    *deeper* layer's velocity (0.05, not 0.1) — i.e. the boundary belongs to
    the layer that starts there, implemented via `searchsorted(..., side="right")`.
  - past the last layer: `test_two_layers_integrate_piecewise` (`t=99.0`, only
    two layers) and `test_depth_is_monotone_for_any_valid_model` (`t` up to 120
    against a boundary at 60) — extrapolates using the last layer's velocity.
  - single-layer (constant) model: `test_constant_velocity_depth_is_half_v_t`
    and `is_constant`/`surface_velocity` — reduces to `depth = v*t/2` exactly.
  - I additionally ran the real-header test against the actual local `.DZT`
    files (not skipped) as the strongest edge-case check: `read_header` on a
    real symlinked SIR-4000 file gives `epsr=14.0`, `position_ns≈-11.086`, and
    `VelocityModel.from_dielectric(14.0).depth_at([position_ns])` landed in
    `(-0.46, -0.43)` as required.

## Concerns

None regarding correctness or scope. The implementation matches the brief and
all four verification commands (tests, ruff check, ruff format, mypy) are
clean with no ignores, workarounds, or weakened assertions.

## Deviations from the brief

1. **Removed the `# type: ignore[no-any-return]` comments in `resolve_velocity`.**
   The brief's reference code has:
   ```python
   if getattr(line, "velocity", None) is not None:
       return line.velocity  # type: ignore[no-any-return]
   ...
   return grid.velocity  # type: ignore[no-any-return]
   ```
   Under this project's actual mypy config (`packages/nsgeo-core/pyproject.toml`),
   `warn_return_any` is **not** enabled (only `disallow_untyped_defs`,
   `warn_unused_ignores`, `warn_redundant_casts`, `no_implicit_optional` are).
   Without `warn_return_any`, mypy does not flag returning an `Any`-typed
   expression (`line.velocity`, since `line: Any`) from a function declared to
   return `VelocityModel` — there is nothing to suppress. Because
   `warn_unused_ignores = true` is on, mypy reported both comments as
   `error: Unused "type: ignore" comment [unused-ignore]`, which would have
   failed the mandated clean-mypy verification step. I removed the two
   superfluous ignore comments rather than adding a workaround (e.g. stacking
   `unused-ignore` onto the ignore code, or disabling `warn_unused_ignores`) —
   the removal is the correct fix for this codebase's config, not a weakening
   of any check; `mypy` is still clean and unmodified in its settings.
2. **Reformatted two lines with `ruff format`** that the brief's reference
   code, copied verbatim, did not wrap to this project's 100-column line
   length: `Line.open`'s signature in `survey.py`, and one
   `np.testing.assert_allclose(...)` call in the test file. Purely
   whitespace/wrapping; no semantic change. Ran `ruff format` (not hand-edits)
   so the result matches the project's own formatter exactly.

No other deviations — the rest of the brief's reference code (validation
logic, layer-index/depth-integration math, dict round-trip, `Grid`/`Line`
field additions, `project.py` serialisation shape) was implemented as given
and verified correct against its own test cases plus the real-data test.

---

## Fix report (round 1)

Four Important findings from the independent review, all fixed. No findings
were disputed; the reviewer's four "not in scope" items (the ndarray-in/
scalar-out annotation gap, the `epsr <= 0` header fallback, and the two
in-body `from dataclasses import replace` imports) were left untouched as
instructed.

### Finding 1 — malformed velocity escaped `load_site` as a bare exception

`project.py`'s `_grid_from_dict` and the line-velocity parse in `load_site`
each called `VelocityModel.from_dict(...)` unguarded. Fixed by mirroring the
existing `"stack" in entry` pattern exactly:

- `_grid_from_dict` now parses velocity into a local first, inside
  `try/except (KeyError, TypeError, ValueError)`, re-raising as
  `ProjectError(f"invalid velocity for grid {doc.get('id', '<unknown>')!r}: {exc}")`.
- `load_site`'s line loop does the same before calling `Line.open`, re-raising
  as `ProjectError(f"invalid velocity for line {entry['path']!r}: {exc}")`.

Both now name the grid id or the line's stored path, and both convert
`ValueError` (bad values, e.g. non-zero first top), and `KeyError`/`TypeError`
(malformed shape, e.g. a typo'd `"lyaers"` key or a non-dict `"layers"`
entry) into `ProjectError`.

Test added: `test_malformed_velocity_block_raises_project_error` in
`test_velocity.py`, covering all three failure modes the reviewer verified by
hand — a grid velocity block with a non-zero first top, a line velocity block
with a negative interval velocity, and a typo'd `"lyaers"` key — asserting
`ProjectError` (not `ValueError`/`KeyError`) is raised in each case, with the
grid id or line path present in the message.

### Finding 2 — `resolve_velocity(line: Any, grid: Any)` couldn't catch a swapped call

I agreed with the reviewer's correction of the plan: `from __future__ import
annotations` means every annotation in `velocity.py` is an unevaluated
string, so a `TYPE_CHECKING`-guarded import of `Grid` and `Line` runs no code
at import time and cannot join the runtime cycle that a real (unguarded)
import would. Changed:

```python
if TYPE_CHECKING:
    from nsgeo.geometry.grid import Grid
    from nsgeo.model.survey import Line
```

and `resolve_velocity(line: Line, grid: Grid | None) -> VelocityModel`,
dropping the `getattr` on `line` entirely (`grid` keeps its `is not None`
guard, since `None` is a real, valid argument per the existing tests). Also
rewrote the docstring to drop the now-incorrect "duck-typed ... cannot create
an import cycle" rationale — it now just states the resolution order.

`mypy` stays clean on the actual source tree (`Success: no issues found in 21
source files`). As a negative check (not part of the committed diff — a
temporary file created, verified, then deleted), I confirmed a call with
swapped positional arguments is now caught:

```
$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
packages/nsgeo-core/src/nsgeo/_scratch_swap_check.py:9: error: Argument 1 to "resolve_velocity" has incompatible type "Grid"; expected "Line"  [arg-type]
packages/nsgeo-core/src/nsgeo/_scratch_swap_check.py:9: error: Argument 2 to "resolve_velocity" has incompatible type "Line"; expected "Grid | None"  [arg-type]
Found 2 errors in 1 file (checked 22 source files)
```
After deleting the scratch file, mypy returns to `Success: no issues found in
21 source files`. This is exactly the mistake the reviewer identified (before
the fix, the same swapped call type-checked cleanly because both parameters
were `Any`).

No pytest test pins this finding: it is a static-typing gap, not a runtime
behaviour difference (both `Grid` and `Line` now carry a `.velocity`
attribute, so a swapped call does not raise at runtime — only mypy catches
it), so the meaningful regression test is the mypy check above, not a new
assertion in `test_velocity.py`.

### Finding 3 — NaN/inf layer top accepted, silently making a layer unreachable

`__post_init__`'s strict-increase check (`b <= a`) is `False` for any
comparison involving NaN, and a genuinely infinite top also passes it, so
either was silently accepted and made every layer at or after it
unreachable. Added a finiteness check on all tops, run before the "starts at
0 ns" and "strictly increase" checks (so a non-finite first top gets the more
specific "must be finite" message rather than a confusing "must start at 0
ns" one):

```python
if any(not math.isfinite(t) for t in tops):
    raise ValueError(f"layer tops must be finite, got {tops}")
```

Test added: `test_non_finite_layer_top_is_rejected`, asserting `ValueError`
(matching `"finite"`) for both a NaN and an infinite second-layer top.

### Finding 4 — `velocity_at(NaN)` silently returned the last layer's velocity

`np.searchsorted` sorts NaN to the end of the array, so `_layer_index`
resolved a NaN time to the last layer as though it were a real, very late
time; `depth_at` already returned NaN for the same input only as a side
effect of `t - tops[idx]` propagating NaN through the arithmetic —
`velocity_at` had no equivalent arithmetic to catch it. Fixed by masking
non-finite times to NaN explicitly:

```python
def velocity_at(self, times_ns: np.ndarray) -> np.ndarray:
    t = np.asarray(times_ns, dtype=float)
    tops, vs = self._arrays()
    resolved = vs[self._layer_index(tops, t)]
    return np.where(np.isfinite(t), resolved, np.nan)
```

This masks both NaN and +/-inf inputs to NaN output (matching the finding's
"non-finite", not only the literal NaN case demonstrated), so `velocity_at`
and `depth_at` now agree that an invalid time carries no real velocity or
layer membership.

Test added: `test_velocity_at_of_non_finite_time_is_nan`, asserting NaN
output for both a NaN and an `inf` input time, and a real value (0.1) for an
ordinary finite time in the same call.

### Covering tests run

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_project.py packages/nsgeo-core/tests/test_velocity.py packages/nsgeo-core/tests/test_boundary.py -q
```
Output:
```
.................................                                        [100%]
33 passed in 0.21s
```
(`test_project.py` because `project.py` changed; `test_velocity.py` because
`velocity.py` changed and gained the three new tests above — 14 tests total,
up from 11; `test_boundary.py` because it's the qgis/PyQt/matplotlib/scipy
import-boundary guard and `velocity.py`'s `TYPE_CHECKING` block is new
import-adjacent code worth re-checking.)

Lint and type commands, run after the fix:
```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
44 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
Success: no issues found in 21 source files
```

Full core suite, run once at the end as final confirmation:
```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests -q
........................................................................ [ 26%]
.......................................................................s [ 53%]
..s..................................................................... [ 80%]
.....................................................                    [100%]
267 passed, 2 skipped in 0.73s
```
(267 = the prior 264 plus the 3 new tests; the 2 skips are the same
pre-existing ones, unrelated to velocity.)

### Files changed in this round

- `packages/nsgeo-core/src/nsgeo/project.py` — wrapped both velocity parse
  sites in `try/except` → `ProjectError`, mirroring the `stack` pattern.
- `packages/nsgeo-core/src/nsgeo/velocity.py` — `TYPE_CHECKING` import of
  `Grid`/`Line`, real parameter types on `resolve_velocity` (dropped
  `getattr`/duck-typing), finiteness check on layer tops, NaN-masking in
  `velocity_at`.
- `packages/nsgeo-core/tests/test_velocity.py` — three new tests (malformed
  velocity → `ProjectError`, non-finite layer top rejected, non-finite time
  in `velocity_at` resolves to NaN).

### Concerns after this round

None. All four findings are fixed and covered by tests (three findings by new
pytest tests; the fourth, a static-typing gap, by a manual mypy negative
check reported above since it has no runtime behaviour to assert on).
