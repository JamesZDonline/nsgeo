# M17a fix W2 — the two tests that fail on CI's QGIS 4.2 job

Branch `nsgeo-m17-gps`, worktree `.worktrees/nsgeo-m17-gps`.
Head before this fix: `6d3ecb1`. Read `constraints.md` beside this brief for the project's rules and
commands (use them as written; `-p no:xonsh` matters locally).

## Why

CI's `plugin-qgis (qgis/qgis:4.2)` job (QGIS 4.2.3, Qt 6, PyQt 6, Python 3.13) has failed on every
push of this branch since Task 4. Main's CI is green, so the cause is on this branch. Locally only
QGIS 3 (Qt 5) is installed, where both tests pass. Latest failing run: 44120633874, job
134170729763 (`gh run view 44120633874 --log-failed`). Result there: 2 failed, 2762 passed.

### Failure 1 — `test_plugin_gps_import_dialog.py::test_the_cells_worth_a_look_are_amber_and_refused_statuses_red`

```
>       assert colours(d, 0, COL_ENDS) == AMBER and plain(d, 0, COL_GAP)
E       ... and False)
E        +  where False = plain(<GpsImportDialog>, 0, 3)
```

The helper at test_plugin_gps_import_dialog.py:211 is
`return d.table.item(row, col).background().style() == 0  # Qt.NoBrush`. Under PyQt6, `style()`
returns a `Qt.BrushStyle` enum, which never equals the int 0. This looks like a test-only fault.
Confirm it on 4.2, and check that the dialog really leaves those cells unpainted on Qt 6. If the
code is at fault too, fix the code.

### Failure 2 — `test_plugin_layers_gps.py::test_the_gap_table_is_dotted_pink_and_not_selectable`

```
>       assert not (layer.flags() & QgsMapLayer.LayerFlag.Identifiable)
E       AssertionError: assert not (<LayerFlag.7: 7> & <LayerFlag.Identifiable: 1>)
```

`SiteLayers._style_rtk_gaps` (layers.py ~2084) does
`layer.setFlags(layer.flags() & ~QgsMapLayer.LayerFlag.Identifiable)`. On QGIS 4.2 the layer still
reports Identifiable afterwards (flags 7 = Identifiable | Removable | Searchable). This is a real
defect on QGIS 4: a gap on the map can be clicked with the Identify tool there, which the plan's
ruling R15 rules out. Find out why on 4.2 itself, by measuring rather than guessing. Candidates:
- `~` on QGIS's `LayerFlag` under PyQt6 does not give the complement;
- `setFlags` does not take that type;
- something later resets the flags.

Then fix it with code that works on QGIS 3.44 (PyQt5) **and** 4.2 (PyQt6). Use only API both have.
`nsgeo_qgis/qtcompat.py` holds the project's Qt 5/6 shims, so look there first. If the cause is the
`~` idiom, also check whether any other place in the plugin uses `~` on a QGIS (not Qt) flag enum,
and list them in your report. Do not change Qt `ItemFlag` uses; those pass on 4.2.

## How to run QGIS 4.2 locally

Docker Desktop is installed but usually stopped. Start it with `systemctl --user start docker-desktop`.
Then run `docker pull qgis/qgis:4.2`, because the tag was rebuilt in October 2026 and a stale local
image misleads. Run tests with the project's script, which copies the worktree into the container:

```
packages/nsgeo-qgis/scripts/in_qgis_docker.sh qgis/qgis:4.2 \
    python3 -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_layers_gps.py -q -p no:cacheprovider
```

The container needs pytest installed the way CI does it. Read the script and ci.yml's `plugin-qgis`
job to see how. Docker Desktop cannot bind-mount paths under /tmp. Home paths mount fine, and the
script mounts the worktree. The local Docker VM is slow (about 6x CI), so run single files, never the
whole tier. Stop Docker Desktop when you are done: `systemctl --user stop docker-desktop`.

If Docker cannot be started or the image cannot be pulled, stop and report BLOCKED with the error.
Do not guess a fix you cannot run on 4.2.

## Tests

- Failure 1: fix the helper to compare against the enum (`Qt.BrushStyle.NoBrush`), so it works on both.
- Failure 2: the existing assertion stays as it is. It is the right check, and it is what caught this.
  Show it fails on 4.2 before your fix and passes after.
- Both files must pass on QGIS 3 locally (`.venv-qgis`) **and** on 4.2 in Docker:
  `test_plugin_gps_import_dialog.py`, `test_plugin_layers_gps.py`, and also `test_plugin_layers.py`
  if you touch layers.py.
- Then core + pure, ruff check and format check, and mypy, per constraints.md.

## Commit

One commit, e.g. `fix(m17a): rtk_gaps is not identifiable on QGIS 4; the dialog test reads Qt 6 brush styles (#134)`.
End the message with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Do NOT push; the
controller pushes. Touch nothing outside this brief's scope.

## Report

Append to `walkthrough-fix-w2-report.md` beside this brief:
- the cause of each failure, as measured on 4.2;
- the fix;
- the exact commands run on both QGIS versions, with their final lines;
- any other `~`-on-QGIS-flag uses you found.

Then reply with the status (DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT), the commit SHA,
and one line per concern.
