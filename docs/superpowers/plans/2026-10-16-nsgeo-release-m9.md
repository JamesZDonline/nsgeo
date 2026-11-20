# nsgeo M9 — the first release (0.1.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce one QGIS-installable zip of the nsgeo plugin, with the core bundled inside, that loads on QGIS 3.40–3.44 and on QGIS 4.x. CI builds it, proves it starts in a real QGIS, and attaches it to a GitHub release when a `v*` tag is pushed.

**Architecture:**
- The release half of the plugin's core-path shim already exists: `nsgeo_qgis/__init__.py` prefers `_vendor/`. M9 adds `build_zip.py`, which fills `_vendor/` from tracked files.
- A smoke probe runs inside real QGIS (`qgis --code`, under xvfb). It proves the zip loads from its own bundled core, and that QGIS's own installer accepts the metadata.
- QGIS 4 support is a metadata line plus test-harness fixes. Measured in spec §3.2: the product code needed no changes.

**Tech Stack:** Python ≥3.9 with numpy only (core); PyQGIS through `qgis.PyQt` (plugin); pytest; GitHub Actions; the `qgis/qgis:3.44` and `qgis/qgis:4.2` Docker images; the `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-10-15-nsgeo-release-m9-design.md`. Read it first. Section numbers below (§) refer to it.

## Global Constraints

- Plugin and core versions are both `0.1.0`. They move together, and the release tag is `v0.1.0` (§4, §5.3).
- `metadata.txt` must contain `qgisMinimumVersion=3.40`, `qgisMaximumVersion=4.99`, `supportsQt6=True` and `experimental=True` (§4, §5.2). QGIS 3.44's installer rejects the plugin on any Qt 6 build unless `supportsQt6` is true (`installer_data.py:832`), so it must stay.
- The core stays numpy-only and import-clean. Both boundary test files must stay green: `packages/nsgeo-core/tests/test_boundary.py` (2 tests) and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`.
- The zip has one top-level folder, `nsgeo_qgis/`, with the core at `nsgeo_qgis/_vendor/nsgeo/`. It is built from `git ls-files` only. Allowed file types are `.py`, `.txt`, `.md`, `LICENSE*` and `VERSION`, plus `.html`, `.css` and `.png` only under `nsgeo_qgis/help/` (§5.1).
- CI pins `qgis/qgis:3.44` and `qgis/qgis:4.2`, never `qgis/qgis:ltr` (§3.3).
- Never commit survey data. Nothing published may reveal a site location (§2 anti-goals).
- **Never push a `v*` tag.** The tag is the user's act, after the merge (§4).
- Push the `nsgeo-m9` branch after each task's commits. Merging to `main` asks first.
- Verification commands, run exactly as written from the worktree root:
  - pure + core: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q` (baseline: 546 passed, 2 skipped)
  - qgis, local QGIS 3.44.7: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh` (baseline: 659 passed)
  - lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
  - mypy: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- Known flake: `test_a_choice_delivered_during_the_cancel_wait_does_not_reopen_the_overlap` (#41) fails intermittently on both QGIS majors. Re-run it, record the re-run in the ledger, and do not fix it here.
- The worktree `.worktrees/nsgeo-m9` has its own `.venv` and `.venv-qgis`, and real DZT files are symlinked into `packages/nsgeo-core/tests/data/local/`. Check that `./.venv/bin/python -c "import nsgeo; print(nsgeo.__file__)"` names the worktree.

## Review Focus

These are inputs the spec implies but no test exercises until this plan adds one. They are listed most likely to bite first, and each has a test in its owning task.

1. **A Windows profile path with spaces or non-ASCII characters**, such as `C:\Users\José Müller\AppData\...`. The extracted zip must still import its bundled core. Test: Task 3's extract-and-import test uses such a directory.
2. **Files that must never ship.** An untracked `.DZT` in the plugin folder, a tracked `.png` outside `help/`, or any `__pycache__` must be left out or refused, never zipped. Test: Task 3.
3. **A tag that does not match the version**: `v0.1`, `0.1.0`, `v0.1.0-rc1`, or `v0.1.1` against metadata `0.1.0`. The build must refuse and name both values. Test: Task 3, parametrized.
4. **A Qt 6 build of QGIS 3.** If `supportsQt6` is ever dropped, QGIS 3 on Qt 6 rejects the plugin. Test: Task 1's metadata test asserts it.
5. **Upgrading in place without restarting QGIS.** The old `nsgeo` stays in `sys.modules`, so plugin and core versions mix. The guide tells the user to restart QGIS after installing or upgrading, and the About text shows the build, so a mismatch is diagnosable. Test: Task 5's guide test checks that the restart instruction is present, and Task 6's Windows QGIS 3 pass installs over the earlier install.

---

### Task 1: QGIS 4 compatibility — metadata, test harness, dev tools, CI on both majors

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt` (add `qgisMaximumVersion=4.99`)
- Modify: `packages/nsgeo-qgis/tests/conftest.py` (also put `PLUGIN_DIR / "scripts"` on `sys.path`)
- Modify: `packages/nsgeo-qgis/tests/plugin_testing.py` (two helpers)
- Modify: `packages/nsgeo-qgis/tests/qgis/conftest.py:174-178` (`_forbid`) and `:259-285` (`message_log`)
- Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py:1455-1475`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py:640-660` (log listeners)
- Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py:497-510`, `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py:1350`
- Modify: `packages/nsgeo-qgis/scripts/dev_link.py`
- Create: `packages/nsgeo-qgis/scripts/in_qgis_docker.sh`
- Create: `packages/nsgeo-qgis/tests/pure/test_metadata.py`, `packages/nsgeo-qgis/tests/pure/test_dev_link.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_qt_compat.py`
- Modify: `.github/workflows/ci.yml`, `packages/nsgeo-qgis/README.md` (the Development install and Tests sections)

**Interfaces:**
- Produces: `plugin_testing.connect_message_log(slot: Callable[[str, str, int], None]) -> Callable[[], None]`. It connects `slot` to `QgsMessageLog.messageReceivedWithFormat` when that signal exists (QGIS 4), and to `messageReceived` otherwise. It returns the matching disconnect. The slot receives `(message, tag, int(level))`, with any extra format argument dropped.
- Produces: `plugin_testing.send_hover(widget, local_pos: QPoint) -> None`. It sends a buttonless `MouseMove` `QMouseEvent` directly. It is `send_move_while_pressed(widget, local_pos, held_button=Qt.MouseButton.NoButton)`.
- Produces: `dev_link.profile_plugins_dir(profile: str, major: int = 3) -> Path`, with base `.../QGIS/QGIS{major}/profiles/...`, and a CLI flag `--qgis-major {3,4}` that defaults to 3.
- Produces: `packages/nsgeo-qgis/scripts/in_qgis_docker.sh IMAGE CMD...`. It runs `CMD` in `IMAGE` against a throwaway copy of the worktree under `/work`, with pytest installed and the real-data symlinks resolvable, and exits with `CMD`'s status. Task 4 reuses it.

- [ ] **Step 1: Write the failing pure tests**

`test_metadata.py` reads `nsgeo_qgis/metadata.txt` with `configparser`:

```python
def test_metadata_admits_qgis_3_40_through_4():
    g = _general()
    assert g["qgisMinimumVersion"] == "3.40"
    assert g["qgisMaximumVersion"] == "4.99"

def test_qt6_builds_of_qgis_3_still_accept_the_plugin():
    # QGIS 3.44 installer_data.py:832 rejects a Qt6 build without it.
    assert _general()["supportsQt6"] == "True"

def test_release_is_marked_experimental():
    assert _general()["experimental"] == "True"
```

`test_dev_link.py` imports `dev_link`, which the conftest change puts on the path:

```python
def test_qgis4_profiles_live_under_QGIS4(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux"); monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert dev_link.profile_plugins_dir("ns_geo", major=4) == (
        tmp_path / ".local/share/QGIS/QGIS4/profiles/ns_geo/python/plugins")

def test_default_major_is_unchanged_for_existing_usage(monkeypatch, tmp_path):
    ...same setup...
    assert "QGIS3" in dev_link.profile_plugins_dir("ns_geo").parts
```

- [ ] **Step 2: Write the failing qgis-tier test**

In `test_plugin_qt_compat.py`, write `test_message_log_fixture_sees_the_plugins_own_log(message_log)`. It calls `nsgeo_qgis.log.log("m9-probe")` and asserts `"m9-probe" in message_log`. On QGIS 4 this test fails before the fix, because `message_log` listens to `messageReceived`.

- [ ] **Step 3: Run them and see them fail**

Run the pure + core command. Expected: the `test_metadata` max-version test and both `test_dev_link` tests fail. The local qgis tier passes (QGIS 3).

- [ ] **Step 4: Make them pass**

- Add `qgisMaximumVersion=4.99` to `metadata.txt`, directly after `qgisMinimumVersion`.
- Change `dev_link.py`: `profile_plugins_dir(profile, major=3)` builds `QGIS{major}` into the base path on all three platforms, and the CLI gains `--qgis-major` with `choices=[3, 4]` and `type=int`.
- In `_forbid` (qgis conftest), return early when `not hasattr(cls, name)`. PyQt6 has no `exec_`.
- Add `connect_message_log` and `send_hover` to `plugin_testing.py`, keeping Qt imports local to each function, as the module docstring requires. Route the `message_log` fixture and the two local listeners (`test_plugin_layers.py:1468` and `test_plugin_session.py:653`) through `connect_message_log`.
- In `test_mouse_move_emits_the_trace_under_the_cursor`, replace `QTest.mouseMove` with `send_hover`. Keep the m2 comment's coordinate reasoning, and add one line on why: Qt 6's `QTest` mouse state leaks across files (§3.2c).
- Mark `test_the_dock_minimum_does_not_force_the_main_window_to_grow` with `pytest.mark.xfail(QT_VERSION_STR.startswith("6."), reason="§3.2e: Qt 6 metrics give 253 px; settle in the QGIS 4 walkthrough", strict=True)`. The import is `from qgis.PyQt.QtCore import QT_VERSION_STR`.
- Write `in_qgis_docker.sh`, a bash script with `set -euo pipefail`:
  - `docker run --rm` with `-e QT_QPA_PLATFORM=offscreen -e QGIS_PREFIX_PATH=/usr -e PYTHONDONTWRITEBYTECODE=1 -e LANG=C.UTF-8`.
  - Mount the worktree read-only at `/src`.
  - Mount, read-only and at the same absolute path, every directory that a `packages/nsgeo-core/tests/data/local/*` symlink resolves into. Without this, the real-data tests open dangling links.
  - Inside the container: copy `/src` to `/work` with `cp -a`, skipping `.venv` and `.venv-qgis`. Keep `dist/`, because Task 4 smoke-tests zips from it. Then `cd /work`, run `python3 -m pip install -q --break-system-packages --root-user-action=ignore pytest`, and `exec "$@"`.
- In `ci.yml`:
  - `plugin-qgis` gets `strategy.matrix.image: ["qgis/qgis:3.44", "qgis/qgis:4.2"]` with `fail-fast: false`, and `container: ${{ matrix.image }}`.
  - `test`'s python matrix becomes `["3.9", "3.12", "3.13"]`.
- In the plugin README, document `--qgis-major 4` and `in_qgis_docker.sh`.

- [ ] **Step 5: Verify on all three QGIS environments**

1. Run the pure + core command. Expected: baseline + 5 passed.
2. Run the local qgis command. Expected: 660 passed, which is the baseline plus the new log test. The dock-width test passes, because its xfail applies only on Qt 6.
3. Run `packages/nsgeo-qgis/scripts/in_qgis_docker.sh qgis/qgis:4.2 python3 -m pytest packages/nsgeo-qgis/tests -q -p no:cacheprovider`. Expected: everything passes except one `xfailed` (the dock width), and #41 at most. This takes about 6 minutes on this machine's 4-CPU Docker VM.
4. Run the same command with `qgis/qgis:3.44`. Expected: all pass, #41 at most.

- [ ] **Step 6: Lint, commit, push, watch CI**

```bash
git add -A packages/nsgeo-qgis .github/workflows/ci.yml
git commit -m "feat: run on QGIS 4 — qgisMaximumVersion, Qt6-safe test harness, CI on 3.44 and 4.2"
git push
gh run watch --exit-status $(gh run list --branch nsgeo-m9 --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: every job is green, including both `plugin-qgis (qgis/qgis:3.44)` and `plugin-qgis (qgis/qgis:4.2)`.

---

### Task 2: The named core API

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/__init__.py`, plus `io/__init__.py`, `model/__init__.py`, `geometry/__init__.py`, `processing/__init__.py` and `slices/__init__.py`
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`, `render.py`, `velocity.py` (add `__all__`)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/store.py` (rename `_npz_path` to `npz_path`)
- Modify the plugin imports in: `layers.py:33-35`, `session.py:24-25`, `slice_export.py:101`, `slices_engine.py:132`, `lookup.py:17-20`, `ui/grid_dialog.py:14-15`, `ui/import_dialog.py:32` and `ui/add_step_dialog.py:12`. Re-grep `from nsgeo\.[a-z]*\.` before trusting this list.
- Create: `packages/nsgeo-core/tests/test_public_api.py`
- Modify: `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` (replace `ALLOWED_FROM_PROCESSING` and `_processing_offenders`)
- Modify: `packages/nsgeo-core/README.md`

**Interfaces:**
- Produces: the supported surface. Each module below declares exactly this `__all__`, sorted. A public module is any module one level below `nsgeo` that declares `__all__`.

| Module | `__all__` |
|---|---|
| `nsgeo` | `__version__` |
| `nsgeo.io` | `DztError, DztHeader, DzxError, DzxInfo, DzxMark, read_dzx, read_header, read_samples, sidecar_for, trace_count` |
| `nsgeo.model` | `Line, Profile, Site, clear_profile_cache` |
| `nsgeo.geometry` | `Grid, GridFit, GridPlacement, Placement, fit_grid_from_corners` |
| `nsgeo.processing` | `ParamSpec, REQUIRED, Radargram, Step, StepStack, available_steps, build_step, default_params, get_step, is_unipolar, nyquist_mhz, required_params` |
| `nsgeo.slices` | every name `slices/__init__.py` re-exports today, plus `npz_path` |
| `nsgeo.project` | `ProjectError, line_key, load_site, save_site` |
| `nsgeo.render` | `DEFAULT_COLORMAP, FixedRange, Normalizer, PercentileClip, UNIPOLAR_COLORMAPS, UnipolarClip, colormap, colormap_names, decimate_columns, to_index8, to_index8_unipolar, to_rgb8, to_rgba8` |
| `nsgeo.velocity` | `C_M_PER_NS, VelocityModel, resolve_velocity` |

`register` stays out of `processing`, because defining steps is the core's job. The old allowlist excluded the step modules and `register`, and that stays true.

- Produces: `nsgeo.slices.npz_path(path: str | Path) -> Path`. The behaviour is unchanged from `_npz_path`.

- [ ] **Step 1: Write the failing core tests** in `test_public_api.py`

```python
EXPECTED_PUBLIC = {"io", "model", "geometry", "processing", "slices", "project", "render", "velocity"}

def test_the_public_modules_are_exactly_the_named_ones():
    assert public_modules() == EXPECTED_PUBLIC   # helper: one level below nsgeo, declares __all__

@pytest.mark.parametrize("name", sorted(EXPECTED_PUBLIC))
def test_every_public_name_resolves_and_none_is_private(name):
    mod = importlib.import_module(f"nsgeo.{name}")
    assert mod.__all__ == sorted(mod.__all__)
    for n in mod.__all__:
        assert not n.startswith("_") and hasattr(mod, n), n

def test_top_level_exports_only_the_version():
    assert nsgeo.__all__ == ["__version__"]

def test_register_is_not_public():
    assert "register" not in nsgeo.processing.__all__

def test_the_readme_names_every_public_name():
    text = (CORE / "README.md").read_text(encoding="utf-8")
    missing = [f"{m}.{n}" for m in EXPECTED_PUBLIC
               for n in importlib.import_module(f"nsgeo.{m}").__all__ if f"`{n}`" not in text]
    assert not missing, missing
```

`public_modules()` lives in the test file. It walks `Path(nsgeo.__file__).parent` one level deep: `x/__init__.py` or `x.py`, skipping names that start with `_`. It parses each with `ast` and checks for a top-level `__all__` assignment.

- [ ] **Step 2: Write the failing boundary test**

In `test_plugin_boundary.py`, replace `ALLOWED_FROM_PROCESSING` and `_processing_offenders` with:
- `_public_api() -> dict[str, set[str]]`, which maps `"nsgeo.<x>"` to its `__all__` for every public module, plus `"nsgeo"` mapped to `{"__version__"}`. It finds public modules the same way `public_modules()` does.
- `_core_import_offenders(path: Path, public: dict[str, set[str]]) -> list[tuple[int, str]]`. It flags:
  - any `from nsgeo... import` whose module is not a key of `public`;
  - any imported name not in that key's set;
  - any `import nsgeo.<anything>`;
  - any attribute read `nsgeo.<attr>` on a bare `nsgeo` name where `attr` is not in `public["nsgeo"]`.
  - It ignores `nsgeo_qgis`: compare `module.split(".")[0] == "nsgeo"`.

Tests:
- `test_plugin_imports_only_the_named_core_api`, which scans `_py_files()`.
- `test_the_checker_flags_each_kind_of_offence(tmp_path)`. It writes a scratch file with one deep import (`from nsgeo.slices.store import npz_path`), one unlisted name (`from nsgeo.processing import register`), one `import nsgeo.processing`, and one `nsgeo.slices` attribute read. It asserts exactly four offenders, one per line.

Keep `test_no_direct_qt_or_forbidden_imports` and the other existing tests unchanged.

- [ ] **Step 3: Run them and see them fail**

Run the pure + core command. Expected failures:
- `test_the_public_modules_are_exactly_the_named_ones`, because no `__all__` exists yet.
- The README test.
- `test_plugin_imports_only_the_named_core_api`, which lists the deep imports, including `nsgeo.slices.store._npz_path`.

- [ ] **Step 4: Implement**

1. Add the `__all__` lists from the table. In `io`, `model` and `geometry`, add the re-exports their `__init__.py` files lack. There are no import cycles: `geometry → velocity` is guarded by `TYPE_CHECKING`, and `model → geometry, io` is acyclic.
2. Rename `_npz_path` to `npz_path` in `store.py`, export it from `nsgeo.slices`, and update `slice_export.py` and the docstrings that name it (`plugin.py:675`, `slice_export.py:479`, `test_plugin_slice_export_dialogs.py:97-114`).
3. Point every plugin import at the subpackage level, for example `from nsgeo.geometry import Grid`.
4. In `packages/nsgeo-core/README.md`, add a "Public API" section. Give one table per public module, with a one-line purpose for each name in backticks. State that anything not listed is internal, and that 0.x means the surface is named, not frozen.

- [ ] **Step 5: Verify**

Run pure + core, the local qgis tier, lint and mypy. Expected: all green, and the qgis count unchanged from Task 1.

- [ ] **Step 6: Commit and push**

```bash
git add -A packages/nsgeo-core packages/nsgeo-qgis
git commit -m "feat(core): name the public API with __all__; the plugin imports only it"
git push
```

---

### Task 3: `build_zip.py`, the build stamp, and version 0.1.0

**Files:**
- Create: `packages/nsgeo-qgis/scripts/build_zip.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_build_zip.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/__init__.py` (add `build_label`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py:887-888` (`show_about`)
- Modify: `packages/nsgeo-core/pyproject.toml` and `packages/nsgeo-core/src/nsgeo/__init__.py` (`0.1.0.dev0` becomes `0.1.0`)
- Modify: `packages/nsgeo-qgis/tests/pure/test_plugin_shim.py` (`build_label` tests) and `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py:24-26` (About text)

**Interfaces:**
- Consumes: Task 2's `nsgeo.__all__`. Not functionally, but the zip must vendor the post-Task-2 tree.
- Produces, in `build_zip.py`, each importable as `import build_zip`:
  - `class BuildError(Exception)`
  - `read_versions(repo: Path) -> tuple[str, str]` returns `(plugin_version, core_version)`. The plugin version comes from `metadata.txt` and the core version from `nsgeo/__init__.py`, parsed with `ast`, never imported.
  - `check_tag(tag: str, repo: Path) -> str` returns the version. It raises `BuildError` unless `tag == "v" + plugin_version`, `plugin_version == core_version`, and `docs/releases/<version>.md` exists. The message names the tag and both versions.
  - `zip_plan(repo: Path) -> list[tuple[str, Path]]` returns `(arcname, source)` sorted by arcname, and covers tracked files only:
    - `packages/nsgeo-qgis/nsgeo_qgis/**` maps to `nsgeo_qgis/**`;
    - `packages/nsgeo-core/src/nsgeo/**` maps to `nsgeo_qgis/_vendor/nsgeo/**`;
    - `packages/nsgeo-qgis/LICENSE` maps to `nsgeo_qgis/LICENSE`;
    - `packages/nsgeo-core/LICENSE` maps to `nsgeo_qgis/_vendor/nsgeo/LICENSE`.

    It raises `BuildError` listing every arcname outside the allowlist in Global Constraints.
  - `build_zip(repo: Path, out_dir: Path, *, allow_dirty: bool = False, tag: str | None = None) -> Path` writes `out_dir / f"nsgeo_qgis-{version}.zip"`:
    - Every entry is dated at the HEAD commit's time (`git log -1 --format=%ct`), with `ZIP_DEFLATED` compression.
    - It adds `nsgeo_qgis/_vendor/VERSION` containing `core=<core_version>\ncommit=<full HEAD sha>\n`.
    - It refuses (`BuildError`) when `git status --porcelain --untracked-files=no` is non-empty, unless `allow_dirty` is set.
    - It calls `check_tag` first when `tag` is given.
  - `main(argv: list[str] | None = None) -> int` with the CLI `build_zip.py [--out DIR] [--allow-dirty] [--tag TAG]`. The default `--out` is `<repo>/dist`, and the repo is found with `git rev-parse --show-toplevel`. On success it prints the zip path and returns 0. On `BuildError` it prints to stderr and returns 1.
- Produces: `nsgeo_qgis.build_label(core_path: Path = CORE_PATH) -> str`. It returns `"build <first 12 hex of commit>"` when `core_path / "VERSION"` exists, and `"development checkout"` otherwise. It stays Qt-free.
- Produces: About text `f"plugin {plugin_version()} · core {nsgeo.__version__} · {build_label()}"`.

- [ ] **Step 1: Write the failing tests**

In `test_build_zip.py`:
- A `repo` fixture builds a minimal tracked tree in `tmp_path` with `git init`, user config and one commit:
  - `packages/nsgeo-qgis/nsgeo_qgis/__init__.py`;
  - `metadata.txt` with `version=0.1.0`;
  - `packages/nsgeo-qgis/LICENSE`;
  - `packages/nsgeo-core/src/nsgeo/__init__.py` with `__version__ = "0.1.0"`;
  - `packages/nsgeo-core/LICENSE`;
  - `docs/releases/0.1.0.md`.
- A second fixture copies nothing. It runs against the real repository (`git rev-parse --show-toplevel`) with `allow_dirty=True`.

```python
def test_the_zip_has_one_top_level_folder_and_vendors_the_core(repo, tmp_path):
    z = zipfile.ZipFile(build_zip.build_zip(repo, tmp_path / "out"))
    names = z.namelist()
    assert {n.split("/")[0] for n in names} == {"nsgeo_qgis"}
    assert "nsgeo_qgis/_vendor/nsgeo/__init__.py" in names
    assert "nsgeo_qgis/LICENSE" in names and "nsgeo_qgis/_vendor/nsgeo/LICENSE" in names
    assert all("\\" not in n for n in names)

def test_version_file_records_core_version_and_commit(repo, tmp_path): ...
    # VERSION == f"core=0.1.0\ncommit={head_sha}\n"

def test_untracked_survey_file_never_ships(repo, tmp_path):
    (repo / "packages/nsgeo-qgis/nsgeo_qgis/FILE__001.DZT").write_bytes(b"x")
    names = zipfile.ZipFile(build_zip.build_zip(repo, tmp_path / "o")).namelist()
    assert not any(n.lower().endswith(".dzt") for n in names)

def test_a_tracked_file_outside_the_allowlist_is_refused(repo, tmp_path):
    # commit nsgeo_qgis/map.png  -> BuildError naming "nsgeo_qgis/map.png"

def test_help_pages_are_allowed_only_under_help(repo, tmp_path):
    # commit nsgeo_qgis/help/dewow.html, help/style.css, help/fig/a.png -> all in zip

def test_a_dirty_tree_is_refused_unless_allowed(repo, tmp_path): ...

@pytest.mark.parametrize("tag", ["v0.1", "0.1.0", "v0.1.0-rc1", "v0.1.1"])
def test_a_tag_that_does_not_match_is_refused(repo, tag):
    with pytest.raises(build_zip.BuildError, match="0.1.0"):
        build_zip.check_tag(tag, repo)

def test_matching_tag_needs_release_notes(repo):
    assert build_zip.check_tag("v0.1.0", repo) == "0.1.0"
    (repo / "docs/releases/0.1.0.md").unlink()
    with pytest.raises(build_zip.BuildError, match="docs/releases/0.1.0.md"):
        build_zip.check_tag("v0.1.0", repo)

def test_two_builds_of_one_commit_are_identical(repo, tmp_path): ...  # bytes equal

def test_the_real_zip_loads_its_bundled_core_from_an_awkward_path(real_repo, tmp_path):
    z = build_zip.build_zip(real_repo, tmp_path / "out", allow_dirty=True)
    dest = tmp_path / "Prof ile José Müller" / "plugins"
    zipfile.ZipFile(z).extractall(dest)
    out = subprocess.run([sys.executable, "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); import nsgeo_qgis, nsgeo; "
        "print(nsgeo.__file__); print(nsgeo_qgis.build_label())", str(dest)],
        capture_output=True, text=True, check=True).stdout.splitlines()
    assert Path(out[0]).is_relative_to(dest / "nsgeo_qgis" / "_vendor")   # 3.9: use resolve() + parents
    assert out[1].startswith("build ") and len(out[1]) == len("build ") + 12

def test_versions_agree_across_metadata_core_and_pyproject():
    # metadata version == nsgeo/__init__ __version__ == pyproject `version = "..."` (regex; no tomllib on 3.9)
```

`Path.is_relative_to` does not exist on 3.9. Compare with `dest.resolve() in Path(out[0]).resolve().parents`.

In `test_plugin_shim.py`, add `test_build_label_names_the_commit_in_a_zip(tmp_path)`, which writes `VERSION` into a temporary `_vendor`, and `test_build_label_says_development_checkout_without_one(tmp_path)`.

In `test_plugin_loads.py:26`, extend the About assertion to `"core" in text and ("build " in text or "development checkout" in text)`.

- [ ] **Step 2: Run them and see them fail**

Run pure + core. Expected: `ModuleNotFoundError: build_zip` and `ImportError: build_label`, and the version-agreement test fails on `0.1.0.dev0`.

- [ ] **Step 3: Implement** `build_zip.py` and `build_label` to the interfaces above, change `show_about`, and set the core version to `0.1.0` in both places.

- [ ] **Step 4: Verify**

Run pure + core and the local qgis tier. Then build a zip from the real tree:
```bash
.venv/bin/python packages/nsgeo-qgis/scripts/build_zip.py --allow-dirty
python3 -m zipfile -l dist/nsgeo_qgis-0.1.0.zip | head -20
```
Expected: the zip is written to `dist/nsgeo_qgis-0.1.0.zip`, every entry is under `nsgeo_qgis/`, and nothing is under `tests/` or `scripts/`.

- [ ] **Step 5: Commit and push**

```bash
git add -A packages/nsgeo-qgis packages/nsgeo-core
git commit -m "feat: build_zip.py — the release zip, with the core vendored and a build stamp in About"
git push
```

---

### Task 4: The smoke probe and the release pipeline

**Files:**
- Create: `packages/nsgeo-qgis/scripts/smoke_probe.py` (runs inside QGIS through `qgis --code`)
- Create: `packages/nsgeo-qgis/scripts/smoke_install.sh` (runs inside a QGIS container)
- Modify: `.github/workflows/ci.yml` (jobs `build-zip`, `smoke`, `release`, and actionlint in `lint`)

**Interfaces:**
- Consumes: Task 3's `build_zip.py --tag` and `--out`, and `nsgeo_qgis.build_label()`; Task 1's `in_qgis_docker.sh` (local runs only).
- Produces: `smoke_install.sh ZIP`. It installs `xvfb` and `xauth` through apt when `xvfb-run` is missing. It reads the major version as `Qgis.QGIS_VERSION_INT // 10000`, then removes and extracts `ZIP` into `$HOME/.local/share/QGIS/QGIS$major/profiles/default/python/plugins/` using `python3 -m zipfile -e`. It runs `timeout 300 xvfb-run -a qgis --nologo --code <dir>/smoke_probe.py` with `NSGEO_SMOKE_OUT=/tmp/nsgeo-smoke.json`, prints that JSON, and exits with QGIS's status.
- Produces: `smoke_probe.py`, which on a `QTimer.singleShot(3000, ...)` records these named checks into a JSON object, writes it to `$NSGEO_SMOKE_OUT`, and calls `os._exit(0 if all checks are true else 1)`:
  - `installer_accepts`: `pyplugin_installer.installer_data.plugins.getInstalledPlugin("nsgeo_qgis", path=<plugin dir>, readOnly=False)["error"] == ""`. This is QGIS's own compatibility verdict, which `loadPlugin` skips. Record `error_details` alongside it.
  - `loads` and `starts`: `qgis.utils.loadPlugin` and `startPlugin` both return `True`.
  - `plugin_from_profile`: `nsgeo_qgis.__file__` is under `QgsApplication.qgisSettingsDirPath()`.
  - `core_from_vendor`: `nsgeo.__file__` is under `<plugin dir>/_vendor/`. This is the §2 anti-goal.
  - `stamped`: `nsgeo_qgis.build_label()` starts with `"build "`.
  - `docks`: the main window's `QDockWidget` titles include `"nsgeo Survey"`, `"nsgeo Profile"`, `"nsgeo Processing"` and `"nsgeo Slices"`.
  - `toolbar`: a `QToolBar` has `objectName() == "nsgeoToolBar"`.
  - `unloads`: `qgis.utils.unloadPlugin` returns `True`.

  An exception anywhere is recorded as `"error": traceback` and counts as a failure.

  In GitHub's container jobs, `HOME` is `/github/home`. `smoke_install.sh` must therefore use `$HOME`, never `/root`. If the two ever disagree, the `plugin_from_profile` and `loads` checks catch it.

- [ ] **Step 1: Write the probe and installer, then prove the probe can fail**

Write both scripts. Build a zip with `qgisMaximumVersion` temporarily deleted from `metadata.txt` (`build_zip.py --allow-dirty`), then run:
```bash
packages/nsgeo-qgis/scripts/in_qgis_docker.sh qgis/qgis:4.2 bash packages/nsgeo-qgis/scripts/smoke_install.sh dist/nsgeo_qgis-0.1.0.zip
```
Expected: exit 1, with `"installer_accepts": false` and details `Plugin designed for QGIS 3.40 - 3.99`. That is the measured QGIS 4.2 verdict for today's metadata. Restore `metadata.txt` with `git checkout -- packages/nsgeo-qgis/nsgeo_qgis/metadata.txt`, then check `git status` is clean.

- [ ] **Step 2: Run the probe green on both majors**

Rebuild with `build_zip.py --allow-dirty` and run the same command with `qgis/qgis:4.2` and with `qgis/qgis:3.44`. Expected: exit 0 on both, with every check `true`.

- [ ] **Step 3: Add the CI jobs**

All in `ci.yml`. The trigger stays `on: [push, pull_request]`, which already includes tag pushes.

- `build-zip`: `ubuntu-latest`, python 3.12.
  - It runs `python packages/nsgeo-qgis/scripts/build_zip.py --out dist`, adding `--tag "$GITHUB_REF_NAME"` when `startsWith(github.ref, 'refs/tags/v')`.
  - Then `actions/upload-artifact@v4` with name `nsgeo_qgis-zip`, path `dist/*.zip`, and `if-no-files-found: error`.
- `smoke`:
  - `needs: build-zip`, `fail-fast: false`, matrix image `["qgis/qgis:3.44", "qgis/qgis:4.2"]`, `container: ${{ matrix.image }}`.
  - Steps: checkout, download the artifact into `dist/`, then `bash packages/nsgeo-qgis/scripts/smoke_install.sh dist/*.zip`.
- `release`:
  - `if: startsWith(github.ref, 'refs/tags/v')`, `needs: [test, plugin-qgis, lint, build-zip, smoke]`, `permissions: contents: write`.
  - Steps: checkout, download the artifact, then `gh release create "$GITHUB_REF_NAME" dist/*.zip --title "nsgeo ${GITHUB_REF_NAME#v}" --notes-file "docs/releases/${GITHUB_REF_NAME#v}.md"` with `GH_TOKEN: ${{ github.token }}`. It is not a pre-release (§5.3).
- `lint` gains a step `uses: docker://rhysd/actionlint:latest` with `args: -color`, so a broken `release` job is caught before the one-shot tag.

- [ ] **Step 4: Commit, push and watch CI**

```bash
git add packages/nsgeo-qgis/scripts .github/workflows/ci.yml
git commit -m "ci: build the zip on every push, smoke-test it in QGIS 3.44 and 4.2, release on v* tags"
git push
gh run watch --exit-status $(gh run list --branch nsgeo-m9 --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected:
- `build-zip` is green and the run has an `nsgeo_qgis-zip` artifact.
- `smoke (qgis/qgis:3.44)` and `smoke (qgis/qgis:4.2)` are both green, and their logs show the JSON with every check `true`.
- `release` is skipped, because this is not a tag.
- `lint` is green, including actionlint.

---

### Task 5: Documentation for practitioners, and the metadata copy

**Files:**
- Create: `docs/guide/getting-started.md`
- Create: `docs/releases/0.1.0.md`
- Modify: `README.md` (status section, plus a new *Install* section)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt` (`about`, `changelog`)
- Create: `packages/nsgeo-qgis/tests/pure/test_release_docs.py`

**Interfaces:**
- Consumes: Task 3's `docs/releases/<version>.md` convention, which `check_tag` requires.

The audience is a GPR practitioner. GPR vocabulary is fine, but there must be no developer vocabulary, no terminal, no pip and no git (§2). Use no screenshots, no coordinates and no site names.

- [ ] **Step 1: Write the failing doc tests** in `test_release_docs.py`

```python
def test_release_notes_exist_for_the_metadata_version_and_link_the_guide():
    v = _metadata()["version"]
    notes = (REPO / f"docs/releases/{v}.md").read_text(encoding="utf-8")
    assert "docs/guide/getting-started.md" in notes and "experimental" in notes.lower()

def test_every_relative_link_in_the_user_docs_resolves():
    # README.md, docs/guide/getting-started.md, docs/releases/*.md: every ](relative) target exists

def test_known_issues_are_disclosed_in_notes_and_guide():
    for doc in (NOTES, GUIDE):
        text = doc.read_text(encoding="utf-8")
        for n in ("#22", "#23", "#40"): assert n in text, (doc.name, n)

def test_the_guide_says_to_restart_qgis_after_installing():
    assert "restart qgis" in GUIDE.read_text(encoding="utf-8").lower()

def test_about_states_both_licences_and_the_changelog_names_this_version():
    g = _metadata()
    assert "GPL-2.0-or-later" in g["about"] and "MIT" in g["about"]
    assert g["version"] in g["changelog"]
```

- [ ] **Step 2: Run them and see them fail**

Run pure + core. Expected: all five fail, because the files and fields are missing.

- [ ] **Step 3: Write the docs**

**`docs/guide/getting-started.md`.** Cover §5.5 in this order:
1. Install from ZIP:
   - On Windows, through *Plugins → Manage and Install Plugins → Install from ZIP*. Say to expect the untrusted-source warning, then **restart QGIS**.
   - Short macOS and Linux notes. Mark macOS as untested.
   - How to upgrade (install the new zip, then restart) and how to uninstall.
2. The four docks and the toolbar.
3. A first session: new site → import DZT → place a grid (GNSS corners, digitise, or an existing polygon) → open a line and hover the map → processing step or preset → a pick (the Pick toggle, or Shift+click) → build slices.
4. Where data lives: the site folder holds `survey.nsgeo.json` and the GeoPackage. Picks are authored data and cannot be regenerated.
5. Known issues with workarounds. Read each issue and confirm the workaround against the code before writing it:
   - **#22**: save or discard picks-layer edits before *Edit grid…* changes a grid's CRS.
   - **#23**: move, rename or back up the whole site folder with QGIS closed, never the `.gpkg` alone.
   - **#40**: dewow `window_ns` must be at least two sample intervals, and sliding background `window_traces` at least 2.
6. Reporting a problem: copy the About text (*Plugins → nsgeo → About nsgeo*) into a GitHub issue or an email.

**`docs/releases/0.1.0.md`.** Cover:
- links that work from a GitHub release page. Relative links do not resolve there, so link the guide as `https://github.com/JamesZDonline/nsgeo/blob/v0.1.0/docs/guide/getting-started.md` and the issues by full URL;
- what 0.1.0 is (first release, experimental);
- which QGIS versions it runs on (3.40–3.44 and 4.x);
- what's in it (map link, processing, picking, time and depth slices);
- a link to the guide;
- the known limits: macOS untested, plus the three known issues, each linked.

**`README.md`.** Replace the stale status paragraph, which still says "picking, and a release zip are next". Add an *Install* section that links the guide and the GitHub Releases page.

**`metadata.txt`.**
- Rewrite `about` to cover the map link, processing, picking and time and depth slices. End it with: "The plugin is GPL-2.0-or-later; the bundled nsgeo core library is MIT."
- Add a `changelog` entry in QGIS's multi-line format: `0.1.0 - first release ...`.

- [ ] **Step 4: Verify**

Run pure + core and lint. Then read the guide once as its reader: a geophysicist who has never seen this repository. Every menu path should be one that exists in `plugin.py`'s actions and dock titles.

- [ ] **Step 5: Commit and push**

```bash
git add docs/guide docs/releases README.md packages/nsgeo-qgis/nsgeo_qgis/metadata.txt packages/nsgeo-qgis/tests/pure/test_release_docs.py
git commit -m "docs: the getting-started guide, 0.1.0 release notes, and current metadata"
git push
```

---

### Task 6: Build, deploy and walkthrough (human gate — stop and ask)

This task runs after the whole-branch review comes back clean. It follows the standing build-and-walkthrough procedure. **It is a human gate.** Until the user has done it, the milestone is "code complete", never "complete".

- [ ] **Step 1: Download the zip CI built for the branch head** with `gh run download <run-id> -n nsgeo_qgis-zip -D dist/ci`. This is the artifact under test, not a local build.
- [ ] **Step 2: Build the walkthrough as an Artifact with the `db` capability**, so results persist. Mark data-loss checks clearly. Write positive, observable expectations at the precision the UI shows. It covers:
  1. **Linux, QGIS 3.44.7, in a new profile.** Do not use `ns_geo`: its plugin is a symlink into a worktree. Install from ZIP, then confirm the About text shows `build <12 hex>`.
  2. **Windows, QGIS 4.x.** Install from ZIP, then follow `docs/guide/getting-started.md` step by step with real DZT files. Judge the Slices dock's opening width (§3.2e).
  3. **Windows, QGIS 3.x.** Install over any earlier install and restart. Then open a line, process it, and build one slice.
- [ ] **Step 3: Stop and ask the user to run it.** Record the results in the ledger.
- [ ] **Step 4: Settle §3.2e from the result.** Either fix `SlicesDock` so `sizeHint().width() >= 280` on Qt 6 and drop the xfail, or lower the threshold to the accepted width and drop the xfail. Then commit and push.

---

## After the merge (the user's go, not a task)

1. With `main` green, the user says go. Then `git tag v0.1.0 <main sha> && git push origin v0.1.0`. This is the user's explicit act (§4).
2. Watch the tag's run. If it goes red only on #41, re-run it once and record that in the ledger. Do not wave it through.
3. Download `nsgeo_qgis-0.1.0.zip` from the published release and install it once more on Windows. That file is what colleagues get.
