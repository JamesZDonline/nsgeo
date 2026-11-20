## Global Constraints

- **Core:** numpy only (no scipy, no pyproj). Runtime Python 3.9: no `zip(strict=)`, no `match`, no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new file.
- **Plugin:** Qt only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green: every new signal is connected in `plugin.py`.
- **Every Qt slot guards its own body:** `except Exception as exc:  # noqa: BLE001 -- a slot …`, reporting through `plugin.message`, the dialog's status line or `_log`, never by raising.
- **Both QGIS versions:** code and tests run on QGIS 3.44 (PyQt5) and 4.2 (PyQt6). Compare Qt enums to enums, never to ints; clear QGIS flags with `qtcompat.without_layer_flag`. Local QGIS is 3.44 only, so CI's `plugin-qgis (qgis/qgis:4.2)` job is the Qt 6 check: read it after every push.
- **Tape lines and Grid mode are unchanged** in what they place and save. A site without GPS lines saves byte-for-byte as before.
- **A GPS line never moves when its grid changes** (C3, C13): only `TrackPlacement.grid_id` changes.
- **GPS lines never join a magnetometer grid.** main has no mag grids yet (M19a is unmerged); whichever of M17b and M19a merges second filters `Grid.instrument == "mag"` out of the Target grid list, Move to grid ▸ and Fit to these tracks, and folds M19a's `Import mag…` button into the Add data menu as `Magnetometer…`.
- **Privacy:** `tests/data/local/` is gitignored and reaches the worktree only by symlink; nothing from it is ever `git add -f`ed. No coordinate from a real DZG or DZT header appears in any committed file. Real-data tests assert relative quantities only (lengths, spacings, angles between lines and grid axes, counts, fractions). No site name in any committed file. Synthetic DZGs use made-up positions near lat 45.2, lon 10.5.
- **Shared-worktree safety:** reviewers and mutation probes work on a scratch copy, never on this worktree. `PYTHONDONTWRITEBYTECODE=1` for every run.
- **Commits:** end each message with a `Co-Authored-By:` line naming the model that wrote it. Push each commit to `origin nsgeo-m17b` as it is made. Touch no other worktree.

### Copy (exact)

Strings the user reads. `{n}`, `{gid}` and the like are filled in; `(s)` stays literal, as elsewhere in the plugin.

- **Toolbar:** a button `Add data` with an instant-popup menu holding one entry, `GPR…`. Tooltip: `"Add survey data to the site: GPR lines placed by a grid's tapes or by GPS."` It replaces `Import DZT…` and `Import GPS lines…`, at their place after `Add grid…`.
- **Dialog title:** `Add GPR data into {gid}`, `Add GPR data into new grid {name}`, `Add GPR data into a new grid` (no name yet), `Add GPR data` (no target).
- **Switch:** the label `Place lines by`, then two exclusive checkable buttons `Grid` and `GPS`.
- **GPS-available note (Grid mode only):** `"{n} of {m} files have a GPS log beside them."`, or `"This file has a GPS log beside it."` when one file was added and it has one. Hidden when no file has one.
- **Grid mode, a site with no grid:** status `"This site has no grid yet. Add one with Add grid…, or place the lines by GPS."`, Import disabled.
- **Import button:** `Import {n} line(s) into {gid}`, `Import {n} line(s) into new grid {name}`, `Import {n} line(s) into a new grid`.
- **GPS page form, in order:** `Target grid` (first entry `New grid`, then the site's grids by id); `Name` (New grid only); `Spacing (m)` (New grid only); `Fitted` (New grid only); `Destagger (m)`; `Processing preset`; `Coordinates:`.
  - Spacing note: `"measured from the tracks; type over it if it is wrong"` while measured; empty once typed; `"type one: one line gives nothing to measure it from"` or `"type one: these lines share no direction to measure it along"` while there is none.
  - Fitted: `"{w:.1f} × {l:.1f} m, azimuth {a:.1f}°, lined up with the lines, half a spacing outside the outer ones"`, or `"{w:.1f} × {l:.1f} m, azimuth {a:.1f}°, the smallest rectangle around them; these lines share no direction"`, or `"—"`.
  - Status: `"Name the new grid."`, `"A grid named {name} already exists."`.
- **Existing grid:** a column `Outside {gid}` before `Status`: `"—"` under 0.05 m, `"{m:.1f} m"` (amber), `"all {m:.1f} m"` (red) for a line wholly outside, whose refusal is `outside {gid}`.
- **After a GPS import:** `"imported {n} GPS line(s) into new grid {gid} ({w:.1f} × {l:.1f} m, spacing {s:.2f} m)"` or `"imported {n} GPS line(s) into {gid}"`; then M17a's warnings unchanged; then `"{file}: {m:.1f} m lies outside {gid} and is left out of its slices"` per line with 0.05 m or more outside; then M17a's `"not imported: {file} ({refusal})"` for refused files that are not handed on.
- **Hand-on banner** (Grid page, amber): `"{n} GPS line(s) are in {gid}. GPS could not place {k} file(s): place them by the tapes, or Cancel to leave them out."`, plus `" Offsets and directions are guessed from the GPS lines either side of each one."` when at least one row was guessed.
- **Guess notes:** `"between {a} and {b}"`, `"{k} spacing after {a}"` / `"{k} spacings after {a}"`, `"{k} spacing before {b}"` / `"{k} spacings before {b}"` (stems of the neighbouring files; `{k}` a whole number).
- **Survey panel:** a grid's `Import DZT files…` becomes `Add GPR data…`. A GPS line gains `Move to grid ▸` (after `Set destagger…`) and `Fit a grid to this track…`. A selection of only GPS lines gains `Move {phrase} to grid ▸` and `Fit a grid to these {n} tracks…`. A selection holding both kinds gets `Edit {phrase}…` (when all on one grid) and `Move {phrase} to grid ▸`, as a tape-only selection does.
- **After Fit to these tracks:** `"moved {n} GPS line(s) into {gid}"`.
- **Edit lines, a GPS row:** Offset, Dir, Start and Scale read `—`, read-only, tooltip `"A GPS line is placed by its track: Offset, Dir, Start and Scale do not apply."`; Along reads `GPS`. A bulk change or Measure that skips GPS rows says `"Left {n} GPS line(s) alone: {what} applies to tape lines only."` with `{what}` one of `Offset`, `Dir`, `Start`, `Scale`, `Fit to grid edges`, `Measure`.

### Verification commands (from the worktree root)

The worktree uses the main checkout's virtualenvs with the worktree's core on `PYTHONPATH`. `.venv-tools` (git-excluded, in this worktree) holds CI's ruff 0.17.1 and mypy 2.4.0. A real-data test that skips has validated nothing: the skip count must not rise.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider -p no:xonsh`
- **qgis, the files a task touches:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q -p no:cacheprovider`
- **qgis, real data:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q -p no:cacheprovider -rs`
- **The whole qgis tier** runs only as `qgis_tests.sh full`, and only by the coordinator; CI runs it on 3.44 and 4.2 on every push.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** the mypy line in `.github/workflows/ci.yml`, run with `.venv-tools/bin/mypy` (the core's `track_fit.py` is inside `packages/nsgeo-core/src/nsgeo`, already on it).


## Review Focus

Inputs the spec implies that are most likely to bite, each pinned by a test in the task that owns the code:

1. **The site changes under an open dialog:** the target grid is removed, a grid named like the typed Name appears, or the site closes, while Add data sits on New grid with its preview. Import must refuse with the status line and leave nothing behind; the preview must leave the map when the dialog closes, however it closes. (Task 5)
2. **Import half-succeeds:** `add_grid` succeeds and `add_lines` then refuses (a CRS mismatch, a key already in the site). The new grid must be removed again, and the slice preset put back. (Task 5)
3. **A site with no CRS and no grid, project CRS in degrees:** the new grid and the lines both land in the UTM zone the CRS rule picks, and the site's CRS is pinned to it. (Task 5)
4. **Switching mode with edits in flight:** Grid-mode hand edits (offset, direction, label) survive a switch to GPS and back while the file list is unchanged; the GPS page's destagger and target survive the reverse. (Task 4)
5. **Edit lines after a GPS line changed elsewhere:** a destagger set from the Survey panel while Edit lines is open makes that row skip as changed elsewhere on OK, and every other row still applies. (Task 3)

