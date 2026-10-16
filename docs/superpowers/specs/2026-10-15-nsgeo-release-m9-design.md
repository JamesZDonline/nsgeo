# nsgeo M9 — the first release (0.1.0) — design

M9 was the last milestone of Plan 3 (M7–M9). It was skipped while M10 and M11 went ahead, so it
now ships the plugin with everything on `main`: map link, picking, and time and depth slices.
That includes #7's axis-caption fix, which was merged to `main` as `2a6293d` before M9 started.

This document supersedes §5 of `2026-09-18-nsgeo-qgis-plan3-design.md` where the two disagree.
The main differences are that QGIS 4 is now in scope, and that the zip is proven to load in a
real QGIS before anything is published.

---

## 1. Intent

**Who it is for.** The user's colleagues: geophysical survey practitioners who process GPR data.
They know GPR processing well, but they are not developers and have never seen this repository.

**The first real use.** The user loads the plugin on a campus computer to show colleagues what
it does. Next, a colleague installs it themselves and processes their own data.

**What success looks like.** Someone downloads one zip and installs it through *Plugins → Manage
and Install Plugins → Install from ZIP*. They then work with their own DZT files without git,
pip, a terminal, or the author's help. This has to hold on Windows with either QGIS 3 or QGIS 4.

**Why now.** M7, M8, M10 and M11 are merged, and nothing installable exists. QGIS 4.2 enters the
long-term-release repositories this month, October 2026, so a campus machine set up this autumn
may well run QGIS 4.

---

## 2. Goals, non-goals, anti-goals

**Goals**

- A `build_zip.py` that produces one QGIS-installable zip with the core inside it.
- The zip loads on QGIS 3.40–3.44 **and** QGIS 4.x.
- CI builds the zip on every push, tests on both QGIS majors, and proves that the built zip
  starts in a real QGIS.
- Pushing a `v*` tag publishes a GitHub release with the zip attached.
- `metadata.txt` and the licences are ready for a plugin-repository listing.
- A getting-started guide written for a GPR practitioner.
- A named, documented public API for the `nsgeo` core.

**Non-goals**

- Submitting to the QGIS plugin repository. Only the preparation is in scope.
- Fixing open bugs. The user's decision: "leave the rest". The data-loss ones are disclosed
  instead (§5.5).
- Waiting for the help pages. They are not on `main` yet, and 0.1.0 does not wait for them.
  The zip is ready to carry them whenever they merge (§5.1).
- Publishing `nsgeo-core` to PyPI.
- Verifying macOS. It is best effort: the user has no Mac, and a Mac failure does not block the
  release.
- A plugin icon, screenshots in the docs, or a bundled sample dataset.
- Any new feature. The one exception is extending the About message (§5.1).

**Anti-goals.** Shipping any of these counts as failure, even if everything else works.

- **A zip that only works on the developer's machine.** The shim falls back to the repo's
  `packages/nsgeo-core/src`. A zip-loading test that can reach that fallback proves nothing,
  so the smoke test must show the core was imported from `_vendor/`.
- **Survey data in anything published.** That covers the zip, the guide and the release notes.
  Here, survey data means raw instrument files and anything that reveals where a site is:
  coordinates, map views, file names. Site locations are not reversible once public (see the
  README's note on survey data). One exception is already settled: the help-page figures made
  from the campus training lines. The user approved publishing those, including in a release
  zip (help-pages design, `docs/help-pages-design` branch, §5).
- **A release the user did not explicitly approve.** The repository is public, so a tag push
  publishes immediately.
- **Install steps that need a terminal, pip, or git.**

---

## 3. Measured starting state

### 3.1 What exists

- `scripts/dev_link.py` symlinks the plugin into a profile. It hardcodes the
  `.../QGIS/QGIS3/profiles/...` path.
- `nsgeo_qgis/__init__.py` already looks for the core in `_vendor/` first, then in the sibling
  development checkout. The release half of the shim exists. Nothing creates `_vendor/`.
- `metadata.txt` declares `version=0.1.0`, `qgisMinimumVersion=3.40`, `supportsQt6=True` and
  `experimental=True`. It has no `qgisMaximumVersion`. Its `about` text predates picks and
  slices.
- The core's version, `0.1.0.dev0`, is written in two places: `pyproject.toml` and
  `nsgeo/__init__.py`.
- CI's `plugin-qgis` job runs in `qgis/qgis:ltr`, which is currently 3.44.15 (Qt 5). The plugin
  has never run on QGIS 4 in CI or by hand.
- The licences are already in place: `packages/nsgeo-qgis/LICENSE` is GPL-2.0 and
  `packages/nsgeo-core/LICENSE` is MIT.
- There are no tags and no releases.

### 3.2 QGIS 4 compatibility, measured on 2026-10-15

Tested in the `qgis/qgis:4.2` image: QGIS 4.2.3, Qt 6.9.2, PyQt 6.9.1, Python 3.13.7,
numpy 2.2.4.

**QGIS 4 will not load the plugin as shipped today.** QGIS 4 loads a 3.x plugin only if
`metadata.txt` declares `qgisMaximumVersion` ≥ 4, for example 4.99. `supportsQt6` is no longer
consulted for that decision (plugins.qgis.org's QGIS 4 migration notes).

**The product code ran on QGIS 4 without changes.** The plugin was installed into a QGIS 4
profile in the zip's layout, with the core copied into `_vendor/`. Real QGIS 4.2 was then
started under xvfb with a `--code` probe. Results:

- `loadPlugin` and `startPlugin` both returned true.
- The core was imported from `.../QGIS4/profiles/default/python/plugins/nsgeo_qgis/_vendor/`.
- The four docks (Survey, Profile, Processing, Slices) and the `nsgeo` toolbar were all created.
- `unloadPlugin` returned true.

`loadPlugin` skips the plugin manager's metadata version check. That check still needs the
metadata fix above, and a test of its own (§5.3).

**The test suite on QGIS 4.** The first run gave 684 passed and 38 failed. None of the failures
is a plugin defect that only QGIS 4 exposes. Four causes are in the test harness, and one
pre-existing problem shows up on QGIS 3 as well:

| | Cause | Fix |
|---|---|---|
| a | `conftest.py`'s modal guard monkeypatches `QDialog.exec_` / `QMenu.exec_`. PyQt6 removed `exec_`, so every test using the guard errors in setup. | Skip names that do not exist. |
| b | On QGIS 4, `QgsMessageLog.logMessage` emits `messageReceivedWithFormat(msg, tag, level, format)` and **not** `messageReceived`, so every test that asserts on the log sees `[]`. Verified with a direct probe on both versions. There are three listeners: `tests/qgis/conftest.py:282`, `test_plugin_layers.py:1468` and `test_plugin_session.py:653`. | Connect whichever signal exists, in one shared helper. |
| c | `test_mouse_move_emits_the_trace_under_the_cursor` fails in full-suite order but passes alone and in its own file. A hand-built `QMouseEvent` delivered with `sendEvent` produces the right trace, so the widget is fine. Qt 6's `QTest` mouse state is leaking between files. | Make the test independent of the previous pointer position. |
| d | `test_a_choice_delivered_during_the_cancel_wait_does_not_reopen_the_overlap` failed once in the slow full run but passed 3/3 alone and in its own file. **This one is not specific to QGIS 4.** On `qgis/qgis:3.44` it failed 1 of 6 isolated runs on unmerged `main`, and it fails by never finishing within 20 s. Tracked as **#41**. | Out of M9's scope (see below). |
| e | `SlicesDock.sizeHint().width()` is 253 px on Qt 6, against a test floor of 280. This is a real difference in Qt 6 font and style metrics. | Judge by eye in the QGIS 4 walkthrough, then fix either the dock or the threshold. |

#41 matters to M9 only because the tag job needs every job green. A red run from it is re-run,
with the re-run recorded in the decision record, and never waved through silently. Fixing it
belongs to #41, not to this milestone.

With (a) and (b)'s shared fixture patched in a scratch copy, the run gave **1194 passed and
10 failed**. Those 10 are (b)'s other two listeners, (c), (d) and (e). **No product-code failure
specific to QGIS 4 was found.**

What this evidence does not cover: it is offscreen tests with a fake `iface`, plus one real GUI
start. It is not a person using the plugin. The QGIS 4 walkthrough (§6) is where that happens.

On QGIS 4.2 locally, the full qgis-tier run took about 6 minutes. The 3.44 job in CI takes 76 s.
Expect a slower job, and investigate only if it becomes a problem.

### 3.3 Environment facts that shape the design

- QGIS 4 keeps profiles under `.../QGIS/QGIS4/profiles/<name>/`, confirmed with
  `QgsApplication.qgisSettingsDirPath()` in the 4.2 image.
- **`qgis/qgis:ltr` will move to 4.2** when 4.2 becomes LTR. Today's CI would then quietly stop
  testing QGIS 3. Docker Hub already carries pinned `3.44` and `4.2` tags.
- The QGIS standalone installers ship numpy, so the plugin vendors only the core. For Windows,
  the walkthrough confirms this directly. For macOS it is not verified, consistent with the
  best-effort stance.

---

## 4. Decisions the user made

| | Decision |
|---|---|
| Version | **0.1.0** for both plugin and core. This is the first release. |
| Audience | GPR practitioners, and first a demo on a campus computer. |
| Platforms | **Windows first.** macOS best effort, never a gate. The user hand-tests Linux and Windows. |
| QGIS range | **3.40 or newer, with QGIS 4 in scope** ("future-proof it"). |
| Maturity | `experimental=True` stays. |
| Publishing | A `v0.1.0` tag push publishes. **The user gives the go explicitly. The coordinator never pushes the tag unprompted.** |
| Install docs | A guide written for a geophysicist, with no developer setup in it. It covers install plus a first session. |
| Bugs | #7's fix merged before M9 (done). **Nothing else is fixed in M9.** |
| Help pages | 0.1.0 does not wait for them. The Help button is not on `main` yet. |
| Windows check | The user has **both QGIS 3 and QGIS 4 on Windows**, so the Windows walkthrough covers both majors. |

---

## 5. The design

Items marked *(my call)* were decided by the coordinator, not the user, and can be overridden.

### 5.1 The zip

`packages/nsgeo-qgis/scripts/build_zip.py` writes `dist/nsgeo_qgis-<version>.zip`. The version
is read from `metadata.txt`, which remains the single source for the plugin version.

- **One top-level folder, `nsgeo_qgis/`.** It is the same folder name the dev symlink uses, so a
  profile's plugin settings carry over.
- **Built from tracked files only**, via `git ls-files` *(my call)*. Copying the working tree
  could pick up an untracked file that `.gitignore` happens not to cover.
- **An extension allowlist as a second guard.** The build fails if the zip would contain anything
  outside `.py`, `.txt`, `.md`, `LICENSE*` and `VERSION`. The one addition is `.html`, `.css`
  and `.png`, allowed **only under `nsgeo_qgis/help/`**. The help-pages project, developed in
  parallel, puts its pages there and asks M9 to ship them (help-pages design §7). Any later need
  for an icon or a `.ui` file is added to the list deliberately. A stray `.DZT` cannot ship
  either way. *(my call)*
- **Excluded:** `tests/`, `scripts/`, caches, and bytecode.
- **The core is vendored at `nsgeo_qgis/_vendor/nsgeo/`**, from `packages/nsgeo-core/src/nsgeo`.
  This is the path the shim already expects.
- **Licences inside the zip:** the plugin's GPL-2.0 text at `nsgeo_qgis/LICENSE`, and the core's
  MIT text inside `_vendor/` next to the code it covers.
- **`_vendor/VERSION`** records the core version and the git commit SHA of the build.
- **The About message** shows plugin version, core version and build SHA. In a dev checkout,
  where no `_vendor/VERSION` exists, it says so instead. When a colleague reports a problem, the
  About text identifies exactly what they are running. This is the one product change in M9.
- **Refuses a dirty tree** unless an explicit flag is passed. Running the test suite is CI's job,
  not the build script's. This drops a clause from the parent spec, which had `build_zip.py`
  refuse on failing core tests. *(my call)*
- **Zip entries use forward slashes and a stable order**, so two builds of one commit can be
  compared.

### 5.2 QGIS 4

- **`metadata.txt` gains `qgisMaximumVersion=4.99`.** `supportsQt6=True` stays. It no longer
  decides QGIS 4 compatibility, but it is harmless and still meaningful to Qt 6 builds of QGIS 3.
  *(my call)*
- **The test harness fixes (a), (b) and (c) from §3.2.** For (b), one helper connects whichever
  log signal exists, and all three listeners use it.
- **(e) is settled after the walkthrough.** If 253 px looks right, the threshold is changed.
  Otherwise the dock is fixed. Until then, the test is marked as an expected failure on Qt 6
  only, with the reason in the marker, so the QGIS 4 job can go green. *(my call)*
- **`dev_link.py` learns the QGIS 4 profile directory.** Existing `--profile ns_geo` usage must
  behave exactly as now. The mechanism is the builder's call.

### 5.3 CI and the release pipeline

- **Both QGIS majors on every push.** `plugin-qgis` becomes a matrix over **pinned**
  `qgis/qgis:3.44` and `qgis/qgis:4.2`, not `ltr` (see §3.3). The existing excepthook and
  unraisablehook guard applies to both.
- **Python 3.13 joins the core and pure-tier matrix**, since QGIS 4.2 runs it. The 3.9 floor
  stays. *(my call)*
- **The zip is built on every push** and uploaded as a workflow artifact.
- **A smoke job installs the built zip** into a fresh profile in both containers. It starts real
  QGIS under xvfb with a probe script, generalised from the §3.2 spike and committed to the repo.
  The probe asserts four things:
  1. The plugin loads, starts and unloads.
  2. `nsgeo.__file__` is under `_vendor/`. This is the anti-goal in §2.
  3. The four docks and the toolbar exist.
  4. QGIS's own plugin-compatibility check accepts the zip's `metadata.txt` for the running
     QGIS version. This is the check `loadPlugin` skips. The builder should use the installer's
     own function, not a reimplementation.
- **On a `v*` tag:** every job must pass, including the macOS core and pure-tier tests. The tag
  must equal `v` plus the metadata version, and
  the core version must match it. The job then creates a GitHub release with the zip attached
  and notes that link the getting-started guide. It is a **normal release, not a pre-release**,
  so it shows as *Latest* on the repository page and is easy to find from a campus machine.
  The `experimental` flag carries the maturity message. *(my call)*

### 5.4 Metadata and licensing

- `about` is rewritten to match what ships: map link, picking, slices. A `changelog` entry
  is added for 0.1.0.
- `repository`, `tracker` and `homepage` are kept. They point at the public GitHub repository,
  which a listing requires.
- "GPL-2.0-**or-later**" is stated somewhere a user of the zip will see it, not only in the
  repository README. The licence file itself is the bare GPL-2.0 text. The builder chooses where.
- The core version moves to `0.1.0` in both places. Either it is single-sourced, or a test
  asserts the two agree.

### 5.5 Documentation for practitioners

- **A getting-started guide** under `docs/` (the builder chooses the filename), written for a
  geophysicist. GPR vocabulary is fine; developer vocabulary is not. It covers:
  - Installing from ZIP: Windows first, with short macOS and Linux notes. It says to expect
    QGIS's untrusted-source warning, and how to upgrade or uninstall.
  - The docks and toolbar, and where each lives.
  - A first session: new site → import DZT files → place a grid (GNSS corners, digitise on the
    map, or an existing polygon) → open a line and hover the map → apply processing or a preset
    → pick → build slices.
  - Where data lives. The site folder holds `survey.nsgeo.json` and the GeoPackage. Picks are
    authored data and cannot be regenerated.
  - How to report a problem, including copying the About text.
  - It is text only for 0.1.0.
- **The repository README** gets a current status section and an *Install* section that links
  the guide and the Releases page.
- **The release notes** are short. They link the guide, say the release is experimental, list
  what is in it, and state the known limits: macOS is untested, and the known issues below.
- **Known issues, disclosed rather than fixed.** The release notes and the guide's "where data
  lives" section name the open bugs that can lose a practitioner's work, each with a workaround a
  geophysicist can follow. *(my call — the user said to leave the bugs unfixed, not whether to
  disclose them)* The builder confirms each workaround against the code before writing it:
  - **#22**: unsaved pick edits in the attribute table can be lost. The probable workaround is to
    save layer edits before editing a grid.
  - **#23**: moving or renaming the `.gpkg` on its own can lose data. The probable workaround is
    to move the whole site folder, with QGIS closed.
  - **#40**: dewow and sliding background removal blank the line at a one-sample window. The
    probable workaround is to use a window wider than one sample.

### 5.6 The named core API

- **Each public subpackage declares `__all__`.** That is `nsgeo.io`, `nsgeo.model`,
  `nsgeo.geometry`, `nsgeo.processing` and `nsgeo.slices`, and the modules `nsgeo.project`,
  `nsgeo.render` and `nsgeo.velocity`. The union of those lists is the supported surface.
- **Top-level `nsgeo` keeps exporting only `__version__`**, which keeps import cost and plugin
  start-up unchanged. *(my call)*
- **The plugin may import only supported names.** The boundary test's hand-kept
  `ALLOWED_FROM_PROCESSING` set is generalised to read the core's `__all__` lists, so the
  allowlist cannot drift from the declaration.
- **The plugin's deep imports move to the subpackage level.** Known today:
  - `nsgeo.slices.store._npz_path`, a private name. It is promoted under a public name or the
    need for it is removed.
  - `nsgeo.slices.fill.clear_kernel_cache`.
  - `nsgeo.geometry.grid.Grid` and `nsgeo.model.survey.Line`.

  The builder should re-grep rather than trust this list.
- **`packages/nsgeo-core/README.md` documents the surface**: what each name is for, that
  anything else is internal, and that 0.x means named, not frozen.

---

## 6. Verification

**Automated.** Both QGIS majors are green in CI. The smoke job passes on both. The zip-contents
check and the version check pass.

**By hand, before the merge decision.** This is the standing build-and-walkthrough procedure.
Nothing is tagged before it is done.

1. **Linux, QGIS 3.44.7.** Install the built zip into a **new** profile, not `ns_geo`, whose
   plugin is a symlink into a worktree and would load the repository's copy of the core.
2. **Windows, QGIS 4.x and QGIS 3.x.** The user has both installed. On QGIS 4, do a fresh
   install from the zip, then a real DZT session that follows the getting-started guide step by
   step. This tests the guide as much as the plugin. Check the Slices dock width (§3.2e) here.
   On QGIS 3, a shorter pass is enough: install, open a line, process it, build one slice.
3. **macOS** is not gated.

**After the merge, with the user's go:** push `v0.1.0`, download the release's zip from GitHub,
and install it once more. That file is what colleagues will get.

---

## 7. Left to the builder

- The task breakdown, within the standing 3–6 task size.
- `build_zip.py`'s flags and the exact dirty-tree override.
- How `dev_link.py` chooses between QGIS 3 and QGIS 4.
- Where the smoke probe lives, and how the release is created (the `gh` CLI or an action).
- The guide's filename and structure within §5.5's coverage.
- Single-sourcing the core version versus testing that the two copies agree.
- Whether the (e) dock-width resolution changes the dock or the test, decided after the
  walkthrough.
