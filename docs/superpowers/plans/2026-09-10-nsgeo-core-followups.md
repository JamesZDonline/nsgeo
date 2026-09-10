# nsgeo core (Plan 1) — follow-ups and notes for Plan 2

Written at the end of Plan 1 execution (branch `nsgeo-core`, HEAD after the final fix wave).
Everything here came out of the per-task and whole-branch reviews and was deliberately
**not** fixed in Plan 1, either because it belongs to the plugin layer or because it is a
design decision the user should make. Nothing here is a known bug in shipped behaviour.

## Spec deviations to resolve in Plan 2's first task

1. **`Step.params` is current values, not the "declared schema" spec §7 requires.** The UI
   cannot build parameter widgets from it (no types, ranges, or widget hints), and two of
   the nine steps are not default-constructible: `build_step("bandpass")` and
   `build_step("gain_curve")` raise `TypeError`. Resolve in the **core** (a `schema`
   classmethod or a dataclass-based parameter declaration), not by hardcoding widget
   knowledge in the plugin — otherwise §3's extensibility claim quietly dies. Do not
   invent default passband frequencies: a wrong default silently filters real data.
2. **`GainCurve` validates "≥ 2 points" in `apply()`, not `__init__`.** An invalid curve can
   be serialised into a stack and only fails when applied. The UI wants validation at
   widget-commit time; decide where it lives when the schema work happens.

## Sharp edges the plugin must respect

- **Always build radargrams with `Radargram.from_profile(profile)`**, never
  `Radargram(data=profile.data, ...)`. `Profile.data` is int32; `from_profile` is the
  float-casting route. (AGC used to overflow on int32 — fixed — but the rule stands.)
- **`Site.stacks` keys are relative POSIX paths from the `survey.nsgeo.json` directory**, not
  filenames and not `Line.path`. `Site` does not know the project root; keep the JSON path
  alongside the `Site`, or use `project._line_key`. A mismatched key now raises
  `ProjectError` (it used to be dropped silently).
- **Never mutate a step object in place.** `StepStack.entries` hands back live objects; editing
  one bypasses cache invalidation and desynchronises `to_dicts()` from the cached result.
  Use `replace_step(i, build_step(name, **params))` — that is also the fast path.
- **`gain_curve` control points are in absolute two-way time** (`times_ns()` includes `t0_ns`),
  and real SIR-4000 files have `t0_ns ≈ -11.09 ns`. The curve editor's time axis must be the
  same absolute axis the profile viewer draws. `gain_parametric` is anchored to elapsed time
  from the first row. Both are pinned by tests at `t0_ns = -11.0`.
- **`StepStack.difference(i)` raises `ValueError` for any step that changes the sample count**
  (`time_zero`). Disable or special-case the difference view for such steps.
- **`Line` is lazy**: `Line.open` reads 1024 bytes plus a `stat`; `Line.load()` goes through a
  16-entry LRU keyed on `(path, size, mtime_ns)`. `clear_profile_cache()` exists for a
  "reload from disk" action. `lru_cache` is thread-safe; a cold multi-line load on `QgsTask`
  threads will contend on its lock.
- **`GridPlacement.distance_along` raises if `traces_per_metre <= 0`** (time-triggered
  acquisition). The import table must surface that as "cannot be grid-placed", not a crash.
- **`nsgeo/__init__.py` exports only `__version__`.** Promote the stable names (`Grid`, `Line`,
  `Site`, `Radargram`, `StepStack`, `build_step`, `available_steps`, `load_site`, `save_site`)
  once Plan 2 shows which are load-bearing — not before.

## Test-coverage debts (ship-as-is, worth closing opportunistically)

- Real-file tests: `dt_ns` / `position_ns` never pinned; leading-zero and axis-order invariants
  run on `FILES[:1]` only; the sample test asserts `shape[0] == 1` but not the full shape.
- `tests/data/local/` discovery uses `rglob`, which follows symlinked *files* but does not
  descend symlinked *directories*. Symlink files, or use real subdirectories.
- `_mask` test locates frequencies by exact float equality on `linspace(0, 1000, 10001)`.
- Untested paths: `StepStack.insert`, `replace_step` flag preservation, `intermediate()`
  `IndexError`, disabled-step `cache_size` alignment; `background_svd` at `n == rank`;
  `gain_agc` `window < 1`; `read_samples(path, header=...)` explicit-header branch;
  `Grid.to_world` wrong-ndim.
- `test_curve_is_fast_enough_to_drag` asserts wall-clock `< 0.1 s` (≈40× headroom) — a
  possible flake source on shared CI runners.

## Small hardening candidates

- `parse_header` never checks `rh_tag` membership; a garbage 1 KB file fails later as
  "non-integer trace count", which misdirects. A `{255, 2047, ...}` check would name the cause.
- `Profile.data` is a read-only view, but `data.base` (the `fromfile` buffer) stays writable.
- `save_site` does not call `site.validate()`; a dangling `grid_id` saves cleanly and fails on load.
- `pyproject.toml` `license = { text = "MIT" }` is PEP 639-deprecated in setuptools ≥ 77
  (warning today); no `classifiers`. CI's lint job installs `ruff mypy numpy` unpinned.
- `StepStack` error text on an empty stack reads "0..-1".
- `taper_frac` validation runs before the band checks — arbitrary ordering.

## Format notes for later readers

- `.gpr` files (second instrument, unidentified): magic `GPR\x01`, 16-byte header, 195-byte
  records, 8-bit samples. No reader planned until the instrument is identified.
- `.DZX` sidecars (XML) accompany the DZT files and are unparsed; may carry marks/line info.
- No `.DZG` has been available; `TrackPlacement` is designed but unbuilt and unvalidated.
