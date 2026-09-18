# Final-review fix round — Criticals and data-loss Importants

Twelve items. Four Criticals, eight Importants, all chosen on one rule: **each one can lose or
silently corrupt a user's archaeological survey data.** Everything else the final review found is
being opened as GitHub issues and is explicitly out of scope for you.

Base: `b64eed8`. Every finding below was reproduced by a reviewer or by me; none is speculative.
Where a reproduction is quoted, it is real output.

---

## C1 — A symlinked data directory makes a project permanently unsaveable (core)

`packages/nsgeo-core/src/nsgeo/project.py`

`save_site` (`:131`) keys `site.stacks` by `_line_key(line.path, root, ...)`, which does
`Path(...).resolve()` (`:103`). `load_site` (`:196`) keys it by the **raw stored string**
`entry["path"]` and stores `Line.path` unresolved (`:181`). They agree only when the stored string
already equals the canonical relative-POSIX form of the resolved path.

Reproduced end to end, with survey files on an external disk symlinked in as `site/data` — an
ordinary arrangement when GPR data runs to gigabytes:

```
load_site           : OK -- the project opens normally
site.stacks keys    : ['data/L0.DZT']
key the session asks: /.../external/L0.DZT
STACK LOOKUP HITS?  : False      <-- the saved processing is invisible in the UI
re-save             : FAILED -- "not under the project directory"
re-save allow_abs   : FAILED -- "stacks are keyed by paths that match no line"
```

That second failure is what makes it Critical: `allow_absolute` is exactly what `plugin.py` offers
the user when the first save fails, so the escape hatch is broken too. **The site opens, shows no
processing, and can never be saved again.** A hand-edited `"./L0.DZT"` reproduces it identically,
and `project.py:1-11` advertises the format as "human-readable, diffable, git-friendly".

**Fix:** canonicalise once, so exactly one function computes the key for load, save and session.
In `load_site`, after `dzt = root / stored`, resolve it and derive the key through the same
`_line_key(...)` call the save path uses, for both `Line.open(...)` and the `stacks[key]` entry.

**Test:** a regression test with a genuinely symlinked subdirectory — create the site with a real
directory, save, move the data aside, symlink it back, then assert load → stack lookup hits → save
succeeds. `tmp_path` supports symlinks.

While you are here, also promote `_line_key` to a public `line_key()` with a docstring:
`packages/nsgeo-qgis/nsgeo_qgis/session.py:24` already imports the private name, and this fix makes
it the shared contract.

---

## C2 — The gain strip writes one step's curve onto a different step (plugin UI)

`packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py:97-104` (`set_points`),
`ui/profile_dock.py:468-477` (`show_gain_strip`), `nsgeo_qgis/plugin.py:304-322` (`_on_gain_points`)

`set_points` refuses **any** incoming payload while `_drag is not None`. That is right for an echo
of the strip's own edit, but the strip cannot tell an echo from a payload belonging to a
**different step**. Meanwhile `_on_gain_points` resolves its write target from
`processing_dock.current_row()` **at write time** — a different source. When the selected row
changes mid-drag and the new row also holds a curve step, the strip keeps step A's points while the
writes go to step B.

Reproduced with the full plugin, widgets shown, a real `Qt.Key_Down`:

```
focus widget: QListWidget            # strip.focusPolicy() is NoFocus -- pressing it
after press,  focus: QListWidget     # does NOT take focus; the list keeps the keyboard
row after Key_Down: 1  hidden: False  drag: 1
B before: [[0.0, 0.0], [40.0, -12.0]]
B after:  [[0.0, 0.0], [39.067, 6.632]]     <- B's authored curve replaced by A's
```

No error, no log, no undo — and the strip **still displays A's curve**, so there is no visual cue.
`replace_step` dirties the session and the corrupted curve is written to `survey.json` on save.
`hideEvent` covers a curve→non-curve change; it cannot cover curve→curve, because the strip never
hides.

**Fix — give the strip an owner token, the same shape that already works for the parameter form.**
`ProcessingDock._show_form` keeps `_shown_step` in lockstep *and* re-checks step identity before
every write (`processing_dock.py:341-382`); that is the pattern. `_sync_gain_strip` already knows
`(key, row, step)`. Pass an owner through `show_gain_strip(points, owner)`; when the owner differs
from the one the strip is currently editing, **end the gesture** (`_drag = _drag_db_range = None`)
*before* `set_points`, so the payload is accepted and no later move writes to the wrong step.
Consider also having `_on_gain_points` refuse when the row's step is not the one the strip was
given — the belt-and-braces second check that made the form's fix robust.

**Test:** the reproduction above, driven through the real plugin.

---

## C3 — The picks migration's verification step is untested (tests)

`packages/nsgeo-qgis/nsgeo_qgis/layers.py:438`

`layers.py`'s own module docstring says picks "has no other source of truth, so its rebuild
migrates every row into a fresh table and **verifies it** before ever touching the original". Four
dedicated tests surround that sequence and **none covers the verification itself**. With
`if written != len(old_rows)` disabled, all 290 tests pass. In the field, an `addFeatures` that
returns `ok=True` having written fewer rows leads straight to `renameVectorTable` +
`dropVectorTable` on the original. Authored picks, permanently gone.

**Fix:** no production change needed — the guard is correct. Write the missing test. Monkeypatch
`QgsVectorDataProvider.addFeatures` (or `temp_layer.featureCount`) to under-report, assert the
`RuntimeError` mentioning "wrote N of M", and **read the original `picks` back off disk with a
fresh `QgsVectorLayer`** — the same shape `test_picks_survive_a_failure_while_building_the_temporary_table`
already uses, deliberately not going through `layers` in case a failed rebuild left its registry
stale. Confirm by running the mutation: disable the gate, watch your new test fail, restore.

---

## C4 — "New site" and "Open site" do not protect unsaved work (tests, and verify the code)

`packages/nsgeo-qgis/nsgeo_qgis/plugin.py:349, 368, 417`

Deleting `if self.session.dirty and not self.save_with_prompt(ask_first=True): return` from **both**
`new_site` and `open_site` leaves the suite green. So does ignoring the user's **Cancel** at
`:417`. `NsgeoPlugin.open_site()` has no test at all; `new_site()` has one, and it runs against a
clean session so the guard short-circuits before it is ever exercised. What is lost is grids, line
placements and processing stacks — the survey source of truth.

`unload()`'s equivalent prompt is thoroughly tested: `test_unload_does_not_offer_a_cancel_that_would_be_ignored`
pins the *button set*, and `test_unload_warns_explicitly_when_the_chosen_save_then_fails` asserts
the message says "unsaved changes will be lost". New and Open got none of that treatment.

**Fix:** three tests mirroring the existing unload trio, for each of `new_site` and `open_site` —
dirty site + `answer_modal(..., Cancel)` asserts the site is unchanged **and** `QFileDialog` was
never reached; `Discard` asserts it proceeds; `Save` asserts the file was written first. Verify the
production code is actually correct while you are there; if the Cancel path has a real defect, fix
it and say so.

Related, same file: **`session.py:123`'s guard against `new_site` overwriting a folder that already
holds a `survey.nsgeo.json` has no test either** — I grepped both test trees for its message and
for `new_site` + `pytest.raises` and found nothing. It is the only thing between "New site…" on an
existing project folder and `save_site` overwriting it. Add that test too.

---

## I1 — Parameter bounds are declared everywhere and enforced nowhere (core)

`packages/nsgeo-core/src/nsgeo/processing/base.py:99-100, 162`

Every step declares bounds (`gain.py:42-52` `min=0.0`, `timezero.py:44-52` `min=0.0, max=1.0`,
`background.py:54,86`, `bandpass.py:38-63`). `build_step` passes `**params` straight to the
constructor without consulting `schema()`. And `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`
contains **no reference to `spec.min` or `spec.max` at all**, while its own docstring
(`param_form.py:5-6`) says "Commit builds the step through the core, so the core's validation is the
only validation." **Both halves believe the other one checks.**

Verified consequences, all through `build_step` with no exception raised:

- `gain_parametric(mode="exponential", alpha=1e6)` → 99.8% of samples `inf`; `PercentileClip.limit`
  sees the 0.2% finite tail and `to_index8` clips every infinity to 255 — a fully saturated garbage
  radargram presented as a result.
- `gain_agc(target=-3.0)` (schema says `min=0.0`) → **every sample's polarity inverted.** On a
  radargram that is a real misinterpretation, not a cosmetic one.
- `time_zero(threshold=5.0)` (schema says `max=1.0`) → the first-break pick finds nothing and
  silently returns an uncropped radargram: the correction appears applied and does nothing.
- `gain_curve` has **no dB bound in core at all** — `GainCurve.__init__` (`gain.py:133-139`) checks
  only "≥2 points" and "finite". The 1.6-million-dB runaway this branch fixed was fixed in
  `gain_strip.py`'s drag clamp **only**, so a project written by an earlier commit on this branch
  (`9298a1b`..`91012d3`) or hand-edited reproduces it on load.

**Fix in `build_step`** — it is the single funnel for the UI, `StepStack.from_dicts`, and presets.
Validate unknown and missing param names, and `min`/`max` for `float`/`int` kinds, against
`schema()`. Fix it here and a second front end gets it free; fix it later and every front end has
already shipped its own copy. Give `gain_curve`'s `points` a sane dB bound in its schema so the same
funnel catches it.

Reachable from any hand-edited project file, any preset copied between machines, and any future
front end.

---

## I2 — A zero `rh_data` fabricates 64 traces and shifts every position by a metre (core)

`packages/nsgeo-core/src/nsgeo/io/dzt.py:91`

`data_offset = MINHEADSIZE * rh_data if rh_data < MINHEADSIZE else MINHEADSIZE * n_channels` yields
`0` when `rh_data == 0`. The divisibility guard at `:126-130` — whose stated purpose is "refusing to
truncate because that would silently misalign data" — then **passes**, because the header length is
itself a whole multiple of the trace size.

Verified against a real file with `rh_data` zeroed: `data_offset 0`, `trace_count 672` against a
true 608, and `read_samples` returns `(1, 512, 672)` with no exception. Sixty-four traces of raw
header bytes are prepended, shifting the whole distance axis by 64/60 ≈ **1.07 m**. Every map
position and every pick on that line is silently wrong by a metre.

**Fix:** one line in `parse_header` — `if data_offset < MINHEADSIZE: raise DztError(...)`. It
provably cannot reject a real file: the observed value across all ten real files is 131072, and the
`else` branch floors at `1024 * n_channels`. **Re-run the real-file tests to confirm 10/10 still
parse.**

---

## I3 — `register()` silently overwrites a step that already owns the name (core)

`packages/nsgeo-core/src/nsgeo/processing/base.py:140-148`

`_REGISTRY[cls.name] = cls` with no duplicate check. Verified: defining a class with
`name = "dewow"` and calling `register` makes `build_step("dewow")` return the impostor, with no
warning. A second front end, or a user's own step module, registering `name = "gain_agc"` means
**import order decides which implementation a saved `{"step": "gain_agc"}` resolves to** — a stack
saved against one loads and runs against the other, changing the processing applied to
irreplaceable survey data with nothing in the file or the UI indicating it.

**Fix:** `if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls: raise ValueError(...)`.

---

## I4 — Every "Digitise on map" click permanently leaks a canvas item (plugin)

`packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py:19`

`QgsRubberBand(canvas)` is a `QgsMapCanvasItem`, owned by the canvas's `QGraphicsScene`, not by the
tool. Nothing ever removes it. `plugin.py:626` creates a fresh tool per digitise attempt, and
`plugin.py:649`/`:584` only call `canvas.unsetMapTool(tool)`, which neither deletes the tool nor
frees the band.

Verified, with the tool's Python reference dropped and `gc.collect()` between each cycle:

```
baseline scene items: ['QGraphicsItem']
after 3 digitise cycles: ['QgsRubberBand', 'QgsRubberBand', 'QgsRubberBand', 'QGraphicsItem']
```

They draw nothing (`reset()` clears the geometry), so there is no visible symptom — but this is
exactly the object `plugin.py:585-592`'s own gdb note implicates in a shutdown segfault "once enough
of them pile up alongside a `QgsMapCanvas`/`QgsRubberBand` from the digitise flow". That round fixed
the *dialogs*; the bands were never addressed.

**Fix:** give `DigitiseGridTool` a disposal path that takes the band back —
`self.canvas().scene().removeItem(self._band)` then `self._band = None` — called from `plugin.py`'s
`done()`/`finished()` finalisers alongside `unsetMapTool`, plus `tool.deleteLater()` for the tool.
**Not in `deactivate()` alone**: that fires on every tool switch and the tool can be reactivated.

---

## I5 — Renaming the site folder orphans every authored pick (plugin)

`packages/nsgeo-qgis/nsgeo_qgis/session.py:82-84`

`gpkg_path` is `self.root / f"{self.site_name}.nsgeo.gpkg"` with `site_name = self.root.name`. The
survey JSON is deliberately portable — `save_site`'s docstring says the project directory can be
moved intact — but nothing ties the package's *name* to anything stable.

Create the site in `Site1/`, author picks into `Site1/Site1.nsgeo.gpkg`, rename the folder to
`Kavusan2026/` once the fieldwork has a name. Reopening works (line paths are relative), but
`gpkg_path` now resolves to a file that does not exist, so `ensure_tables` creates a **fresh empty
package** and the picks layer comes up empty **with no message**. The old data is still on disk
under the old filename, so it is recoverable — but nothing tells the user that.

**Fix:** use a fixed basename (`site.nsgeo.gpkg`), or record the package filename in the survey
JSON. Trivial now; a migration once any package exists in the field. If you pick the fixed
basename, handle an existing old-style package gracefully rather than ignoring it — a one-time
rename-on-open, or at minimum a log line naming the file it found.

---

## I6 — Closing a site discards uncommitted pick edits with no prompt (plugin)

`packages/nsgeo-qgis/nsgeo_qgis/layers.py:182-187`

`picks` is deliberately writable (`layers.py:266`: `layer.setReadOnly(name in DERIVED)`), so a user
can toggle editing on it in QGIS today. `detach()` calls `self.project.removeMapLayers(ids)`
unconditionally, and it runs on `site_closed` — i.e. on every "Open site…" and on `unload()`.

Verified: a layer with `isEditable() == True`, `isModified() == True` and one buffered feature is
destroyed by `removeMapLayers` with **no prompt, no signal, and no exception**. QGIS's own
unsaved-edits prompt lives in the application's layer-removal *action*, not in
`QgsProject::removeMapLayers`.

Toggle editing, digitise 20 depth picks over an hour, forget to click "Save Layer Edits", click
"Open site…" — silently gone.

**Fix:** in `detach()`, before removing, check `layer.isEditable() and layer.isModified()` for
`picks` and either `commitChanges()` or refuse and report through `_log` at `Critical`.

---

## I7 — The stack cache-invalidation tests are hollow (tests)

`packages/nsgeo-core/src/nsgeo/processing/stack.py:60, 82`

`insert()` and `set_enabled()` both **survive removal of `_invalidate_from`** across both tiers
(627 tests). The consequence was confirmed numerically: `result()` returns data differing from the
correct output by up to 0.75 max-abs in both cases. `set_enabled` is reachable from the UI today —
`processing_dock.py:394`, the per-step checkbox — so unticking a step after the profile has rendered
shows the **unchanged** radargram, which the user can then save or apply to a whole grid.

The production code is **correct** — I verified it independently with 400 randomized interleavings
against a from-scratch recomputation, 0 mismatches, cache warmed mid-sequence. This is purely a test
gap, and its cause is a textbook constructed precondition: `test_stack.py:35` calls
`st.set_enabled(0, False)` **before** `st.result()`, so the cache is empty and invalidation has
nothing to do. `insert()` has no cache test at all, while `append`/`replace_step`/`remove`/`move`
each have one.

**Fix:** warm the cache with `st.result()` first, then toggle, then assert **both** `cache_size`
**and** that `result().data` actually changed. Add the missing `insert` analogue. Run both
mutations to confirm your tests now kill them.

---

## I8 — The survey dock context menu is dead to the suite, and its destructive confirmations survive (tests + conftest)

`packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py:306, 317, 330`

The whole of `_on_context_menu` is never entered by any test: `menu.exec` can be replaced with
`pass` unnoticed, so which actions appear for site/grid/line and the lambdas wiring each to its slot
are unverified. This is the same defect class as this branch's own "menu whose entire click path was
dead while 22 tests passed" — here the path is not even read, it is simply never entered.

Worse: **both destructive confirmations survive removal.** Answering anything but Yes to "Remove
line from site" / "Remove grid?" still removes. Every existing test calls
`remove_line_action(..., confirm=False)`, bypassing the gate entirely — and `session.remove_line`
drops the line's processing stack with it.

**This needs a conftest change first, and it is a real hole in the guard.** Verified against live
Qt: `'exec' in QMenu.__dict__` is `True` — `QMenu` defines its own `exec`, so patching
`QDialog.exec` does **not** cover it. `survey_dock.py:306` calls `menu.exec(...)`, which blocks
forever offscreen, so a test of the context menu would **hang the suite** rather than fail fast —
precisely what `_no_unhandled_modals` exists to prevent, on the one reachable path it misses. Also
verified: `QDialog.exec is QDialog.exec_` is `False`, so the valid PyQt5 spelling slips through.

**Fix:**
1. Forbid `QMenu.exec` and both `exec`/`exec_` spellings in `tests/qgis/conftest.py`'s
   `_no_unhandled_modals`. This is what makes the rest testable.
2. Expose the built menu the way `processing_dock` already exposes `presets_menu`, assert the action
   set per item kind, and `.trigger()` each.
3. Two `answer_modal(QMessageBox, "question", StandardButton.No)` tests asserting **nothing was
   removed** — one for a line (and assert its stack survives too), one for a grid.

---

## C5 (Critical, CI-red) — `sidecar_for` trusts `exists()` as a case-accurate probe

**File:** `packages/nsgeo-core/src/nsgeo/io/dzx.py:41-44`
**Fails:** `test (macos-latest, 3.9)` and `test (macos-latest, 3.12)`, EVERY run since `9164ec7`
("feat: read the GSSI .DZX sidecar for import hints"). macOS was already in the matrix on `main`
and `main` was green, so this arrived with the branch, exactly as the user reported.

**Reproduction (from the run-14 macOS log, verbatim):**
```
FAILED packages/nsgeo-core/tests/test_dzx.py::test_lowercase_extension_is_found
  assert PosixPath('.../a.DZX') == (PosixPath('...') / 'a.dzx')
  where PosixPath('.../a.DZX') = sidecar_for(PosixPath('.../a.dzt'))
```
1 failed, 249 passed, 12 skipped — this single test is the whole macOS failure.

**Root cause.** The loop tries `.DZX` before `.dzx` and accepts the first whose `.exists()` is
True. On a case-INsensitive filesystem (macOS APFS, Windows NTFS) `a.DZX`.exists() is True when
the real directory entry is `a.dzx`, so the function returns a path whose spelling is not the
name on disk.

**Why only macOS goes red, though Windows has the identical bug.** Verified locally:
```
PureWindowsPath('a.DZX') == PureWindowsPath('a.dzx')  ->  True
PurePosixPath('a.DZX')   == PurePosixPath('a.dzx')    ->  False
```
`pathlib` comparison is case-insensitive on the Windows flavour and case-sensitive on posix.
macOS gets a posix `Path` on a case-insensitive filesystem — the one combination where the wrong
spelling is both produced and detected. **Do not "fix" this by relaxing the assertion:** that
would hide the same defect on Windows, where it is already hidden.

**User-visible consequence** (small but real, and the reason to fix the function not the test):
the wrong-case path escapes into user-facing text at `dzx.py:93,95` —
`DzxError(f"{side.name} is not well-formed XML: ...")` names `a.DZX` when the user's directory
listing shows `a.dzx`.

**Fix.** Resolve the real directory entry instead of trusting `exists()`. Keep `.DZX` ahead of
`.dzx` so a case-sensitive filesystem holding both still prefers the GSSI-conventional spelling:

```python
parent = path.parent
try:
    names = {e.name for e in parent.iterdir()}
except OSError:
    return None
for suffix in (".DZX", ".dzx"):
    name = path.with_suffix(suffix).name
    if name in names:
        return parent / name
return None
```
Add a test that pins the returned **spelling**, not just that it resolves — e.g. assert
`sidecar_for(dzt).name == "a.dzx"`, which fails on today's code on macOS/Windows and passes on
Linux only by luck of the filesystem.

---

## C6 (Critical, CI-red) — two tests swallow a modal-guard failure; CI turns it into `Aborted (core dumped)`

**Files:** `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py:154`,
`packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (two tests),
`packages/nsgeo-qgis/tests/qgis/conftest.py`
**Fails:** job `plugin-qgis`, EVERY run since run 14 (`34665049921`, "feat: schema-driven
parameter form and add-step dialog" = Task 17). Runs 5-13 passed this job. The user's
"between CI 13 and 14" is exactly right.

**This is NOT an import failure.** The job dies mid-suite with SIGABRT:
```
Fatal Python error: Aborted
  File ".../nsgeo_qgis/ui/processing_dock.py", line 419 in add_step
  File ".../nsgeo_qgis/ui/processing_dock.py", line 127 in <lambda>
  File ".../tests/qgis/test_plugin_processing_dock.py", line 70 in test_add_menu_action_triggers_add_step
Aborted (core dumped)  -> exit code 134
```
`processing_dock.py:419` is `self.add_step_requested.emit(name)`; test line 70 is
`action_named("bandpass").trigger()`.

**Root cause.** Task 17 added `self.add_step_requested.connect(self.add_step_with_dialog)` at
`processing_dock.py:154` — the dock now listens to its OWN signal and opens a modal. Two Task-16
tests trigger a REQUIRED-params step to assert the signal fires; since Task 17 those same
emissions also open a real modal dialog. `conftest.py`'s `_no_unhandled_modals` correctly raises
`AssertionError: unexpected modal: QDialog.exec()` — but the raise happens inside a slot invoked
from C++, so **local PyQt 5.15.10 only prints it to stderr and the test still passes**. The
container's PyQt routes the same unhandled slot exception to `qFatal()`, which aborts the process
and kills the whole job at the first occurrence.

**Verified locally.** Running the test with `-s` shows the traceback printed while the test
reports PASSED. Instrumenting `sys.excepthook`/`sys.unraisablehook` to fail any test that
swallowed one gives, across the full qgis suite:
```
290 passed, 2 errors
ERROR ...::test_add_menu_action_triggers_add_step        swallowed: unexpected modal: QDialog.exec()
ERROR ...::test_required_steps_are_requested_not_built   swallowed: unexpected modal: QDialog.exec()
```
**Exactly two tests, and no other swallowed exception anywhere in the 290.**

**Fix — both parts are required.**
1. **The structural half (do this first).** Add the hook to `tests/qgis/conftest.py` so a
   swallowed slot exception fails the test locally instead of reaching CI as an abort. Record
   both `sys.excepthook` and `sys.unraisablehook`, and fail the test in an autouse fixture if
   anything was recorded during it. Without this, local green keeps disagreeing with CI and the
   next such bug ships the same way. This also subsumes brief item **I8**'s conftest work — do
   I8's `QMenu.exec` / `exec_` additions in the same edit.
2. **The two tests.** They must handle the dialog the emission now opens rather than rely on it
   being swallowed — stub `add_step_with_dialog`, or disconnect the self-connection for the
   assertion, or drive the dialog and assert on it. Whichever is chosen, the point of both tests
   (the menu action really fires, and a REQUIRED step is requested rather than built) must
   survive; do not delete the assertions.

**Note on residual risk:** CI aborts at the FIRST bad test, so roughly 82 of the 290 qgis tests
have never actually run in the container. The local hook run gives good confidence they pass, but
the container's QGIS/PyQt build differs — expect the possibility of a further container-only
failure surfacing once the abort is removed, and do not treat the first green `plugin-qgis` run
as proof until it reports the full test count.

---

## Out of scope — do not touch

Being opened as GitHub issues: the difference view going stale after a drag-reorder; a failed
velocity refresh leaving the previous line's depth axis; `unload()`'s loader keep-alive reasoning;
the mypy coverage gap; `import_dialog`'s boolean `_updating` and its comma-decimal conversion;
`close_site`'s teardown ordering; the `plugin.py` slot-guard policy sweep; every Minor; and all
remaining parked test items (the selection-render probe, the `dt_ns` test, the distance-tick
window).
