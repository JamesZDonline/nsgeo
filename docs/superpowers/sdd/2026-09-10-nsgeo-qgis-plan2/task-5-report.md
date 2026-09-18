# Task 5 Report: Plugin skeleton, core path shim, boundary test, offscreen harness, CI

Commit: `c71f030854f6a5771ff754d9b69fdf87376b5df4` — "feat: QGIS plugin skeleton with core path shim and offscreen test harness"

## What was implemented

Exactly the file set the brief specifies, in `packages/nsgeo-qgis/`:

- `nsgeo_qgis/__init__.py` — `_find_core`, `CORE_PATH`, `plugin_version()`, `classFactory(iface)`. Runs the path shim (vendored `_vendor/nsgeo` first, then sibling `../nsgeo-core/src`) before any qgis import, and inserts it onto `sys.path`.
- `nsgeo_qgis/metadata.txt` — `qgisMinimumVersion=3.40`, `supportsQt6=True`, plus the rest of the QGIS plugin metadata fields.
- `nsgeo_qgis/qtcompat.py` — `event_pos(event) -> QPointF`, the one Qt5/Qt6 `pos()`/`position()` shim.
- `nsgeo_qgis/plugin.py` — `NsgeoPlugin(iface)` with `initGui()`, `unload()`, `toolbar`, `session` (`None`, reserved for Task 6), `show_about()` which reports both plugin and core versions via the message bar.
- `tests/conftest.py` — puts `tests/`, the plugin dir, and `packages/nsgeo-core` on `sys.path`; imports `nsgeo_qgis` (runs the shim). No qgis import — stays Qt-free as required.
- `tests/plugin_testing.py` — `REAL_DZT` (list of real `.DZT` files under `nsgeo-core/tests/data/local`, empty list if absent), `needs_real_data` skip marker, `synthetic_dzt(folder, name, n_traces=60, **kw)`.
- `tests/pure/test_plugin_boundary.py` — the plugin's mirror of the core's boundary test: no `PyQt5`/`PyQt6`/`PySide2`/`PySide6`/`matplotlib`/`scipy` at module level anywhere in `nsgeo_qgis/`; `nsgeo.processing` imported only through the nine-name allowlist; `nsgeo_qgis/__init__.py` imports no qgis at module level; a scan-is-really-happening guard.
- `tests/pure/test_plugin_shim.py` — five tests for `_find_core`/`CORE_PATH`/`plugin_version`.
- `tests/qgis/conftest.py` — `qgis_app` (session-scoped, offscreen `QgsApplication`), `FakeIface` / `fake_iface` fixture; the whole directory skips via `pytest.importorskip("qgis.core")` when qgis isn't importable.
- `tests/qgis/test_plugin_loads.py` — builds the plugin through `classFactory`, exercises `initGui`/`show_about`/`unload` against `FakeIface`.
- `scripts/dev_link.py` — symlinks `nsgeo_qgis/` into the QGIS profile's plugin directory, cross-platform path logic, `--profile`/`--remove`.
- `README.md` — dev-install and two-tier test instructions.
- `.github/workflows/ci.yml` — added `python -m pytest packages/nsgeo-qgis/tests/pure -v` to the `test` job; added a new `plugin-qgis` job running the full `tests/` tree inside `qgis/qgis:ltr`.
- `.gitignore` — added `.venv-qgis/` next to `.venv/`.

All content matches the brief's reference code, with one mechanical fix noted below.

## Testing — both tiers

**Pure tier** (`.venv`, no QGIS):
```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
→ 294 passed, 2 skipped
```
(285 core + 9 plugin-pure = 294; the 2 skips are pre-existing core skips, unrelated to this task.)

Skip-path check (`.venv` running the *whole* plugin tests tree, no qgis installed):
```
.venv/bin/python -m pytest packages/nsgeo-qgis/tests -q
→ 9 passed, 1 skipped
```
The 1 skip is the `tests/qgis` directory (via its conftest's `importorskip`).

**QGIS tier** (`.venv-qgis`, offscreen):
```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest -p no:xonsh packages/nsgeo-qgis/tests -q
→ 10 passed
```
(9 pure + 1 qgis test.) See "Concerns" below for why `-p no:xonsh` was needed on this machine.

**Lint/typecheck:**
```
.venv/bin/ruff check .            → All checks passed!
.venv/bin/ruff format --check .   → 57 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
                                   → Success: no issues found in 22 source files
```
(mypy is only wired to the core per the brief/CI; running it against `nsgeo_qgis` too, out of curiosity, produces expected `import-not-found` for `qgis.*` under `.venv` — not a required check, not a regression, see below.)

## TDD Evidence

### Cycle 1 — pure tier (steps 1–4)

**RED** — ran before `nsgeo_qgis/__init__.py` existed (only an empty `nsgeo_qgis/` directory was present from `mkdir -p`):
```
$ .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q
ERROR collecting .../test_plugin_boundary.py
  SRC = Path(nsgeo_qgis.__file__).parent
  TypeError: argument should be a str or an os.PathLike object where __fspath__ returns a str, not 'NoneType'
ERROR collecting .../test_plugin_shim.py
  ImportError: cannot import name '_find_core' from 'nsgeo_qgis' (unknown location)
2 errors in 0.14s
```
Why expected: `nsgeo_qgis` had no `__init__.py` yet, so Python treated the empty directory as a namespace package (`__file__ is None`) and `_find_core`/`CORE_PATH`/`plugin_version` did not exist. This is the same underlying condition the brief's literal `ModuleNotFoundError` describes (module has no real implementation) — it surfaces slightly differently here only because the directory itself already existed from scaffolding `mkdir -p`, making it a namespace package rather than absent entirely.

**GREEN** — after creating `nsgeo_qgis/__init__.py`, `metadata.txt`, `qtcompat.py`, `plugin.py`:
```
$ .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q
.........
9 passed in 0.03s
```

### Cycle 2 — QGIS tier (steps 5–6)

Because `plugin.py` was already implemented in cycle 1, a literal "module missing" RED did not apply here. To produce a real RED for this cycle, I temporarily removed `tests/qgis/conftest.py` (which supplies the `qgis_app`/`fake_iface` fixtures the new test needs) and re-ran:

**RED**:
```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest -p no:xonsh packages/nsgeo-qgis/tests -q
ERROR at setup of test_class_factory_builds_a_plugin_that_adds_and_removes_its_ui
  fixture 'fake_iface' not found
9 passed, 1 error in 0.04s
```
Why expected: `test_plugin_loads.py` depends on the `fake_iface` fixture defined only in `tests/qgis/conftest.py`; with that conftest absent, pytest cannot resolve the fixture.

**GREEN** — conftest restored:
```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest -p no:xonsh packages/nsgeo-qgis/tests -q
..........
10 passed in 1.09s
```
And the no-QGIS skip path re-confirmed:
```
$ .venv/bin/python -m pytest packages/nsgeo-qgis/tests -q
.........
9 passed, 1 skipped in 0.03s
```

## Boundary-test violation proof

Two separate violation shapes were injected, one at a time, to prove the guard actually scans the tree and actually fails on each forbidden pattern (not just "finds nothing"):

**1. Forbidden root import.** Appended `import scipy` to `qtcompat.py`:
```
$ .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
FAILED test_no_direct_qt_or_forbidden_imports
AssertionError: forbidden imports:
  qtcompat.py:20: ['scipy']
1 failed, 3 passed in 0.03s
```
Reverted; re-ran → `4 passed in 0.02s`.

**2. Disallowed name from `nsgeo.processing`.** Added `from nsgeo.processing import dewow` to `plugin.py` (`dewow` is not in the nine-name allowlist):
```
$ .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
FAILED test_processing_is_used_only_through_its_public_surface
AssertionError: processing internals imported by the plugin:
  plugin.py:12: ['dewow']
1 failed, 3 passed in 0.03s
```
Reverted; re-ran full pure tier → `9 passed in 0.04s`.

`git status`/`git diff` after both reverts confirmed `plugin.py` and `qtcompat.py` were restored to exactly their committed content (no residual diff) before staging.

## Files changed

New:
- `packages/nsgeo-qgis/nsgeo_qgis/__init__.py`
- `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt`
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- `packages/nsgeo-qgis/nsgeo_qgis/qtcompat.py`
- `packages/nsgeo-qgis/tests/conftest.py`
- `packages/nsgeo-qgis/tests/plugin_testing.py`
- `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`
- `packages/nsgeo-qgis/tests/pure/test_plugin_shim.py`
- `packages/nsgeo-qgis/tests/qgis/conftest.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`
- `packages/nsgeo-qgis/scripts/dev_link.py`
- `packages/nsgeo-qgis/README.md`

Modified:
- `.github/workflows/ci.yml` (added the pure-plugin pytest line to `test`; added the `plugin-qgis` container job)
- `.gitignore` (added `.venv-qgis/`)

Not touched: `packages/nsgeo-qgis/LICENSE` (already existed, left as-is per instructions).

## Self-review findings

- Read every new file back after writing. Naming follows the test-module-naming rule exactly (`test_plugin_*` in both tiers; no `test_boundary.py` collision with the core's).
- Confirmed every name in `ALLOWED_FROM_PROCESSING` in the boundary test actually exists in `nsgeo.processing.__init__` (`StepStack`, `build_step`, `available_steps`, `get_step`, `Radargram`, `ParamSpec`, `REQUIRED`, `default_params`, `required_params` — all present), so the allowlist isn't accidentally vacuous.
- Smoke-tested `plugin_testing.py`'s helpers directly (not exercised by any test in this task, but required by the interface list for later tasks): `REAL_DZT` found the 10 real `.DZT` files under `packages/nsgeo-core/tests/data/local`; `synthetic_dzt()` wrote a file that `nsgeo.io.dzt.read_header`/`read_samples` read back with the expected `(1, 512, 10)` shape.
- `__pycache__` directories created during test runs are correctly ignored by the existing root `.gitignore` — confirmed they never appeared in `git status`/`git add`.
- No dead code, no unused imports, no scope creep beyond the brief's file list.
- YAGNI: `plugin.py` holds no survey state (`session = None`, as required — Task 6's job) and no docks; `qtcompat.py` is one function, as the brief's own comment insists it stay.

## Deviations from the brief

1. **Import ordering in `test_plugin_shim.py`.** The brief's reference code has:
   ```python
   import pytest

   import nsgeo_qgis
   from nsgeo_qgis import _find_core, plugin_version
   ```
   Ruff's `I` (isort) rule flagged this as unsorted (`nsgeo_qgis`/`from nsgeo_qgis import ...` belong before `pytest` alphabetically within the third-party block, or rather ruff wants `import nsgeo_qgis` merged adjacent to its `from nsgeo_qgis import ...` line, both before `pytest`). Ran `ruff check --fix` to reorder to:
   ```python
   import nsgeo_qgis
   import pytest
   from nsgeo_qgis import _find_core, plugin_version
   ```
   This is purely mechanical (same imports, same behavior) and required for the "ruff clean" verification step to pass — not a design change, so I applied the autofix rather than treating it as a substantive deviation to second-guess.

2. **Dropped all `# noqa: N802` comments**, not just the two the brief's step 9 explicitly names (`initGui`/`classFactory`). The brief's reasoning ("ruff's N rules are not enabled, so ... need no noqa") applies identically to every other camelCase QGIS-API method in `tests/qgis/conftest.py`'s `FakeIface` (`mainWindow`, `mapCanvas`, `messageBar`, `addToolBar`, `addDockWidget`, `removeDockWidget`, `addPluginToMenu`, `removePluginMenu`) and to `plugin.py`'s `unload`. Since `RUF100` (unused-noqa) isn't enabled either, leaving them in would have been silently inert; I dropped all of them for consistency, per the brief's own "be consistent" instruction, rather than leaving some in and some out.

No behavioral deviations. No brief-code defects found in this task (unlike prior tasks) — the reference code as given was already correct; the only two changes were the mechanical ones above.

## Concerns

- **Local environment quirk, not a repo issue:** running `.venv-qgis`'s pytest bare (`QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q`, exactly as the brief/Environment section states) fails at plugin-registration time with `PluginValidationError: Plugin 'xonsh' for hook 'pytest_collect_file' ... Argument(s) {'path'} are declared in the hookimpl but can not be found in the hookspec`. This is because `.venv-qgis` was created with `--system-site-packages`, which exposes this machine's system-wide `xonsh` (0.14.4, installed via apt) and its pytest11 entry-point plugin, built against an older pytest hookspec than the `pytest 9.1.1` installed in `.venv-qgis`. Passing `-p no:xonsh` (a normal, harmless pytest flag — a no-op if the plugin isn't present) works around it locally. This is specific to this machine's system Python installation, not something the CI container (`qgis/qgis:ltr`, which won't have `xonsh`) will hit, and not something I changed any repo file to work around — flagging it here rather than silently patching test configuration to hide it. Worth knowing if you or another contributor hits the same `PluginValidationError` locally.
- Everything else ran clean; no other concerns.

---

# Fix Round 1 Report

Commit: `8c6c1c9` — "fix: close processing-import hole, CI QGIS gate, seed stability, action leak"

All six review findings addressed. Confirmed by the reviewer as out of scope and correctly left alone: the `-p no:xonsh` local quirk, and everything under "Explicitly NOT in scope."

## What changed, per finding

**Finding 1 (Important) — processing guard missed `from nsgeo import processing`.**
`packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`: extracted the per-file scan out of `test_processing_is_used_only_through_its_public_surface` into a standalone `_processing_offenders(path) -> list[tuple[int, str]]`, and added a branch:
```python
elif node.module == "nsgeo" and any(a.name == "processing" for a in node.names):
    offenders.append((node.lineno, "from nsgeo import processing"))
```
This catches `from nsgeo import processing` and `from nsgeo import processing as P` — the branch matches on `a.name` (the imported name), not `a.asname`, so the alias doesn't matter. Extracting the scan into its own function also let me prove it directly against a scratch file (below) instead of only through the full pytest run over the package tree.

**Finding 2 (Important) — `plugin-qgis` CI job passes green with no QGIS bindings.**
`.github/workflows/ci.yml`: added a step before the pytest run:
```yaml
- name: assert QGIS bindings are actually importable
  run: python3 -c "from qgis.core import Qgis; print(Qgis.QGIS_VERSION)"
```
If `qgis.core` isn't importable under whatever `python3` the container resolves to, this now fails the job outright instead of letting `tests/qgis/conftest.py`'s `importorskip` quietly skip the one QGIS-specific test and exit 0.

**Finding 3 (Important) — `synthetic_dzt`'s seed isn't reproducible across processes.**
`packages/nsgeo-qgis/tests/plugin_testing.py`: replaced `np.random.default_rng(abs(hash(name)) % (2**32))` with `np.random.default_rng(zlib.crc32(name.encode()))`. `crc32` is a fixed, unsalted digest (unlike `str.__hash__`, which is seeded per-process by `PYTHONHASHSEED`), and already returns an unsigned 32-bit int so no `% (2**32)` is needed.

**Finding 4 (Minor, promoted) — `test_vendored_core_wins_when_present` didn't test precedence.**
`packages/nsgeo-qgis/tests/pure/test_plugin_shim.py`: the test now also creates `nsgeo-core/src/nsgeo/__init__.py` under the same `tmp_path` before asserting `_find_core(pkg) == pkg / "_vendor"`, so both candidates exist and the assertion actually exercises which one `_find_core` prefers.

**Finding 5 (Minor, promoted) — inconsistent AST traversal.**
`test_plugin_boundary.py`: `test_package_init_imports_no_qgis_at_module_level` now iterates `ast.walk(tree)` instead of `tree.body`, matching the traversal the other two boundary checks already use, so a module-level `try: import qgis` nested inside a `Try`/`If` node would no longer evade it.

**Finding 6 (Minor, promoted) — `unload()` leaked the QAction.**
`packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: added `action.deleteLater()` inside the existing `for action in self.actions:` loop in `unload()`, mirroring what the dock loop above it already does for `dock.deleteLater()`.

## Proof 1 — Finding 1's hole is closed (and really was a hole)

Built a scratch file with both violation forms, independent of the tracked package tree:

```
/tmp/.../scratchpad/finding1_violation.py:
    from __future__ import annotations

    from nsgeo import processing
    from nsgeo import processing as P


    def use_them():
        return processing.bandpass.Bandpass, P._registry
```

**Before the fix** (re-ran the exact pre-fix detection logic, reconstructed from `git show c71f030:.../test_plugin_boundary.py`, against the scratch file):
```
$ .venv/bin/python - <<'EOF'
... [old_processing_offenders(), copied verbatim from the c71f030 function] ...
offenders = old_processing_offenders(Path(".../finding1_violation.py"))
print("pre-fix offenders found:", offenders)
assert offenders == []
EOF
pre-fix offenders found: []
CONFIRMED HOLE: pre-fix logic misses both 'from nsgeo import processing' forms
```

**After the fix**, calling the new standalone `_processing_offenders` (imported directly from the amended test module) against the same scratch file:
```
$ .venv/bin/python - <<'EOF'
import sys
from pathlib import Path
root = Path("packages/nsgeo-qgis").resolve()
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tests"))
sys.path.insert(0, str(root / "tests" / "pure"))
import test_plugin_boundary as tpb
offenders = tpb._processing_offenders(Path(".../finding1_violation.py"))
print("offenders found:", offenders)
assert len(offenders) == 2
assert all(msg == "from nsgeo import processing" for _, msg in offenders)
EOF
offenders found: [(3, 'from nsgeo import processing'), (4, 'from nsgeo import processing')]
PASS: both 'from nsgeo import processing' and '... as P' are flagged
```
Both the plain and aliased forms are now caught, at their correct line numbers (3 and 4).

## Proof 2 — Finding 3's seed is stable across separate interpreter processes

**Before the fix** (`abs(hash(name)) % (2**32)` for `name = "grid_a.DZT"`, three separate `.venv/bin/python` invocations, default randomized `PYTHONHASHSEED`):
```
3331753531
3872915604
2356055009
```
Three different seeds for the same name — confirms the bug as described.

**After the fix**, calling `plugin_testing.synthetic_dzt(tmp_path, "grid_a.DZT", n_traces=8)` in three separate `.venv/bin/python` processes (two with `PYTHONHASHSEED` unset/randomized, one with it forced to `12345`) and hashing the resulting file's bytes:
```
$ env -u PYTHONHASHSEED .venv/bin/python proc_seed_check.py
4bbc3cf74dd7154939fd7c0999ef8be93ef1538e9332acce80eb9a995635e013
$ env -u PYTHONHASHSEED .venv/bin/python proc_seed_check.py
4bbc3cf74dd7154939fd7c0999ef8be93ef1538e9332acce80eb9a995635e013
$ PYTHONHASHSEED=12345 .venv/bin/python proc_seed_check.py
4bbc3cf74dd7154939fd7c0999ef8be93ef1538e9332acce80eb9a995635e013
```
Identical SHA-256 of the written file across all three independent processes, including with a different `PYTHONHASHSEED` — the same `name` now produces byte-identical output regardless of process-local hash salting.

## Tests re-run after the fixes

**Pure tier** — `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`, `packages/nsgeo-qgis/tests/pure/test_plugin_shim.py`, plus the full core suite (unaffected but re-run as the standard combined command):
```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
294 passed, 2 skipped in 0.72s
```
Skip-path re-check (`.venv`, whole plugin tree, no qgis):
```
$ .venv/bin/python -m pytest packages/nsgeo-qgis/tests -q
9 passed, 1 skipped in 0.03s
```

**QGIS tier** — `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` (exercises the amended `plugin.py`), plus the pure files again under `.venv-qgis`:
```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest -p no:xonsh packages/nsgeo-qgis/tests -q
10 passed in 1.08s
```
(`-p no:xonsh` remains the local-machine-only workaround from the initial report; reviewer confirmed it's out of scope for this repo.)

**Lint/typecheck:**
```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
57 files already formatted
$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
Success: no issues found in 22 source files
```

## Notes

- The CI hard gate (Finding 2) and the QGIS-tier tests themselves were not re-run inside the actual `qgis/qgis:ltr` container (no container runtime available in this session) — verified by direct inspection of the added step and by reasoning about its failure mode (a bare `python3 -c` import that raises `ModuleNotFoundError`/`ImportError` and exits non-zero if bindings are absent, which GitHub Actions treats as a job failure). The `.venv-qgis` run above exercises the same pytest invocation the container step uses.
- No new deviations from the brief in this round; all six changes are direct fixes to code this task itself introduced.
