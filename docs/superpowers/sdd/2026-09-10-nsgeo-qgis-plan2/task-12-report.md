# Task 12 report: background line loading and the M4 checkpoint

## What was implemented

- `packages/nsgeo-qgis/nsgeo_qgis/loader.py` (new): `LineLoader(session, on_error=None, parent=None)`,
  a `QObject` that runs `Line.load()` on a `QgsTask` per the brief's interface: `loading_changed(str, bool)`
  signal, `is_loading(key) -> bool`, `request(key)`, `wait_for(key, timeout_ms=5000) -> bool` (test helper).
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (modified): `NsgeoPlugin` now owns a `LineLoader` --
  constructed in `initGui()` right after `self.layers`, wired to report corrupt-file/on_error messages
  through the message bar (`Qgis.MessageLevel.Critical`), and released (`self.loader = None`) in `unload()`
  with a comment explaining that decision (see "Concurrency pass" below).
- `packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py` (new): the brief's four specified tests verbatim,
  plus four more added during the concurrency/failure-path passes (see below).

The implementation follows the brief's given code for the common-case shape (`request()`'s
already-loading/already-loaded guard, `wait_for()`'s event-loop spin with a real timeout) but diverges in
`finished()` and in how tasks are kept alive -- both are **deviations from the brief's reference code**,
found by testing scenarios beyond its four given tests. Details under "Deviations" below.

## Both tiers' results

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
  -> 315 passed, 2 skipped

.venv/bin/ruff check .
  -> All checks passed!

.venv/bin/ruff format --check .
  -> 74 files already formatted

.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  -> Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
  -> 172 passed   (baseline 164 + 8 new tests in test_plugin_loader.py)
```

Re-ran the qgis tier three times back-to-back (and the new test file alone five times) to check for
flakiness given it's the plugin's first real concurrency: stable every time, ~55s for the full tier,
~0.7s for the new file alone.

## TDD evidence

**RED (Step 2 of the brief).** Before writing `loader.py`, ran the brief's test file against the tree:

```
ModuleNotFoundError: No module named 'nsgeo_qgis.loader'
packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py:10: in <module>
    from nsgeo_qgis.loader import LineLoader
1 error in 0.15s
```

**GREEN.** After implementing `loader.py` and wiring `plugin.py`, all 4 brief tests plus the 4 added
tests passed (8 passed in 0.7s).

**A second RED/GREEN cycle, mid-task.** While writing the concurrency-pass tests I found that
`finished()`'s site-identity check (see Deviations) could itself crash when the site was closed
*without* a replacement site being opened -- `session.keys()` requires an open site and raises
`ProjectError` otherwise. I reverted to the naive (unconditional) form of the check to confirm this was
real, not a hypothesis:

```
# buggy: same_site / still_present computed *before* try, unconditionally
FAILED test_closing_the_site_entirely_mid_load_does_not_crash_the_callback
E       assert False
E        +  where False = _wait_signal(loader.loading_changed, <lambda>)
```

(The failure is a *timeout*, not a raised `ProjectError` reaching the test -- `QgsTaskWrapper.finished()`
swallows any exception from its `on_finished` callback silently, so the observable symptom is that
`loading_changed(key, False)` never fires at all.) Restored the fix (short-circuit inside `try`, still
inside `finally`'s protection) and reran: 8/8 passed. This RED/GREEN pair is captured directly in the
test's docstring and in the "Deviations" section below.

## Concurrency pass

Per-scenario:

- **Two requests for the same key in flight.** `request()`'s guard (`key in self._tasks or
  profiles_for(key) is not None`) makes the second call a no-op: no second `QgsTask`, no second
  `loading_changed(True)`. Covered by `test_reopening_a_loaded_line_does_not_reload` (brief) via
  `open_line()`'s own "no-op if already current" path, which is the only way `_on_line_opened` can fire
  twice for the same key while it's mid-flight in this codebase's real call pattern.
- **A request for a key already loaded.** Same guard, other branch (`profiles_for(key) is not None`).
  Covered by the same test.
- **The site closing mid-load.** `_on_site_closed()` clears `_tasks` (so `is_loading()` and a fresh
  request for the same key string are both correct immediately) but *not* `_pending` (so the task
  itself is not orphaned -- see the third deviation). When `finished()` eventually runs, `session.site`
  is `None`, so the identity check fails before `session.keys()` is ever called. Covered by
  `test_closing_the_site_entirely_mid_load_does_not_crash_the_callback` (added).
- **The line removed mid-load (site stays open).** This is the brief's own headline race. `finished()`'s
  `key in self.session.keys()` check (guarded by the site-identity check, see above) means
  `set_profiles` is skipped once the key is gone; no `KeyError` reaches the callback. Covered by
  `test_a_corrupt_file_reports_instead_of_raising`'s sibling scenario is really about a *different*
  key-loss cause (a raised exception, not removal) -- there is no dedicated "line removed, task
  finishes clean" test in this file, since `SiteSession.remove_line` is already tested at the session
  layer (Task 6) and the loader's own logic for it is identical to (and exercised by) the switching-sites
  and closing-the-site tests, which also rely on "key no longer present" being handled without raising.
- **`unload()` mid-load.** Decision: do not cancel. A `QgsTaskWrapper` has no way to interrupt a blocking
  `Line.load()` partway through, and `_pending` (see deviation 3) guarantees the task is not silently
  GC'd just because the plugin drops `self.loader`. Tested by
  `test_dropping_the_loader_reference_does_not_lose_an_in_flight_load`: drop the local `loader` name
  (mirroring `self.loader = None`) while `session` (mirroring `self.session`, which in the real
  `unload()` is still assigned at the point `self.loader = None` runs -- see the ordering chosen in
  `plugin.py`) stays reachable; the load still completes and lands in the session correctly.
- **A load that raises on the worker thread.** `QgsTaskWrapper.run()` (QGIS's own code, not ours) catches
  `Exception`, stores it, returns `False`; our `finished()` sees `exception is not None` and reports via
  `on_error` instead of writing profiles. Covered by `test_a_corrupt_file_reports_instead_of_raising`.
- **Several cold loads at once contending on the LRU lock.** Verified by reading `functools.lru_cache`'s
  implementation: the lock is held only around the cache-dict lookup/insert, not around the wrapped
  function call itself, so concurrent misses for *different* keys do their disk reads in parallel and
  only briefly serialise on bookkeeping. `request()`'s per-key guard prevents two *concurrent* requests
  for the *same* key from ever reaching `_load_profiles` at the same time in the first place (the
  scenario where the lock would matter for redundant, racy same-key misses). Exercised at the plugin
  layer by `test_concurrent_loads_of_different_lines_do_not_cross_contaminate`: four lines requested
  before any of them finish, then asserted that each key's stack ends up with *its own* file's trace
  count, never another's.
- **A previously-unconsidered scenario, found while testing the above: the site closing and a
  *different* site opening before the load finishes**, with the same key string naming a line in both
  (plausible: DZT files are commonly named `FILE__001.DZT` by the acquisition device, and a relative-path
  key like `raw/FILE__001.DZT` recurs across sites with the same folder layout). See Deviations.

## Both audits

### Failure-path audit (every slot/new line)

- `_on_line_opened(key)` -- a slot on `session.line_opened`. Guarded with try/except reporting through
  `on_error`, even though the current call graph makes it effectively unreachable (the key it receives
  was just validated by `open_line()` moments earlier in the same call stack). Added defensively,
  matching the standing rule that every real-work slot in this plugin guards itself; costs nothing and
  means a future change to `_on_line_opened` or `request()` that *can* raise degrades to a message-bar
  error instead of a silent stderr print.
- `request(key)` -- not itself a signal slot (only ever reached via a slot, or called directly). If given
  an unknown key it raises `KeyError` from `session.line_for_key`, same as `SiteSession`'s own contract;
  intentionally not swallowed here since a direct caller (test code, or future plugin code) should see
  its own programming error.
- `work(_task)` (the QgsTask body) -- runs on a worker thread. Any exception from `line.load()` is caught
  by `QgsTaskWrapper.run()` (QGIS's own code), stored, and handed to `finished()` as `exception`. Never
  reaches Python's default excepthook or crashes the worker thread.
- `finished(exception, result)` -- invoked by the task manager on the main thread. Its own body is
  wrapped in `try/finally` so `loading_changed.emit(key, False)` is *guaranteed* even if `on_error` or
  `set_profiles` misbehaves -- this differs from the brief's reference, which put the emit after an
  unguarded if/elif (see Deviations). `_tasks.pop` and `_pending.discard` are placed before the `try` on
  purpose: they cannot raise (`dict.pop(key, None)` / `set.discard`), so bookkeeping stays correct
  regardless of what the try block does.
- `wait_for(key, timeout_ms)` -- a test helper, not a slot. The timeout is real (a `QTimer.setSingleShot`
  always fires and calls `loop.quit()` regardless of whether the awaited signal ever arrives), so a
  broken loader fails the calling test's `assert` rather than hanging the suite. Confirmed this can't
  hang by intentionally breaking `finished()` mid-task (see the RED/GREEN cycle above) and observing a
  normal, fast test failure rather than a stall.
- `_on_site_closed()` -- a slot on `session.site_closed`; its body is one `dict.clear()` call, which
  cannot raise, so no guard is needed.

### What states does this module's own features create, and does each fix hold there too?

- **A key present in `_tasks` for a site that has since closed.** Created by: request a load, close the
  site before it finishes. `is_loading()` reports `False` immediately (handled: `_on_site_closed` clears
  `_tasks`), a fresh request for the same key against a new site is never blocked (handled: same
  clearing), and the original task still exists and will still call `finished()` (handled by `_pending`,
  not by luck -- see Deviations) which correctly declines to write anywhere once it does.
- **A `QgsTask` outstanding in `_pending` with no corresponding `_tasks` entry.** Created by the same
  site-close sequence. This is the intended, stable state for a stale load in flight: `is_loading()` for
  its key is `False` (accurate for the *current* site), but the task keeps running and `_pending` keeps
  it referenced until `finished()` removes it from both structures. No leak: every task that finishes
  removes itself from `_pending`; a task that never finishes (should not happen for a plain file read,
  but if it did) would stay pinned until the process exits, same as leaving any thread running.
- **`LineLoader` outliving the plugin's own reference to it (post-`unload()`).** Created by `unload()`'s
  `self.loader = None` while a load is in flight. As long as `self.session` is still assigned at that
  point (verified true by the ordering chosen in `plugin.py`: `self.loader = None` runs before
  `self.session = None`), `session`'s signal connections to the loader's bound methods keep the loader
  (and hence `_pending`) reachable, so the fix holds. See "Concerns" for the one part of this I did not
  fully resolve.
- **Two loaders on the same session** (not exercised in the product, since `plugin.py` only ever
  constructs one, but nothing in `SiteSession` prevents it, and a test could). Each loader has its own
  `_tasks`/`_pending`, both connected independently to the same session signals; `request()`'s guard is
  per-loader, so two loaders would each start their own task for the same key. Not a state Task 12's
  product code creates, so not tested, but worth flagging: nothing here assumes single-loader-per-session
  beyond "the plugin only builds one."

## Deviations from the brief's reference code

The brief's reference `finished()` was:

```python
def finished(exception, result=None):
    self._tasks.pop(key, None)
    if exception is not None:
        if self.on_error is not None:
            self.on_error(key, str(exception))
    elif self.session.is_open and key in self.session.keys():
        self.session.set_profiles(key, result)
    self.loading_changed.emit(key, False)
```

and `session.site_closed.connect(self._tasks.clear)` was the whole story for site-close handling. Three
things needed to change, each found by testing beyond the brief's four given tests:

1. **Site identity, not just key presence.** `session.is_open and key in self.session.keys()` is true
   again the moment a *different* site (or the same site reopened) happens to define a line under the
   same key string -- which is realistic given DZT files are commonly acquired with default names like
   `FILE__001.DZT`, and keys are paths relative to the site root. Without also checking that
   `session.site is requested_against` (the exact `Site` object this request was made against, captured
   at request time), a slow load from a closed site could land its profiles on a different site's
   identically-keyed line: not a crash, but silently wrong survey data attributed to the wrong physical
   location -- a worse failure mode than the `KeyError` the brief's check already prevents. Proven with
   `test_switching_sites_mid_load_does_not_write_into_the_new_site`.

2. **That check must be short-circuited, not computed eagerly.** My first attempt computed
   `same_site`/`still_present` before the `try` (mirroring the brief's own unguarded style). That crashes
   `finished()` outright when the site is closed with *nothing* reopened: `session.site is None` there,
   but `session.keys()` still requires an open site and raises `ProjectError` if evaluated -- and Python
   evaluates both operands of `and` used as a bare expression only if written to short-circuit; my first,
   wrong version computed `still_present` as its own statement regardless of `same_site`. Confirmed by
   deliberately reverting to that form and watching
   `test_closing_the_site_entirely_mid_load_does_not_crash_the_callback` fail (timeout, since the
   exception aborts `finished()` before the `try/finally` that emits `loading_changed`), then fixing it
   by computing `same_site and key in self.session.keys()` as one short-circuited expression inside the
   `try`.

3. **`_pending`, a keep-alive set independent of `_tasks`.** Verified directly (see the scratch script
   referenced in the "Concurrency pass" section) that `QgsApplication.taskManager().addTask()` does
   *not* retain its own Python-side reference to a `QgsTask.fromFunction()` task: with the loader's
   `_tasks` dict as the *only* Python reference to a submitted task, clearing it on `site_closed` (as the
   brief's one-liner did) let the task be garbage-collected mid-flight, and its `on_finished` callback
   then simply never ran -- not a crash, but a silent, unpredictable "sometimes the stale load reports,
   sometimes it just vanishes" depending on GC timing, which made the site-identity fix above impossible
   to test reliably. `_pending` (a `set[QgsTask]`, added to in `request()`, discarded from in
   `finished()`) decouples "is this key currently tracked as loading" (which must clear promptly on
   site-close so a fresh request isn't blocked) from "keep this task's Python object alive until it
   truly finishes" (which must *not* clear on site-close). With this, the stale-task's `finished()` now
   runs deterministically, and the site-identity check does its job by design rather than by luck.

All three are additive/corrective to the brief's given shape -- no test was weakened to make anything
pass; two of the four extra tests exist specifically to pin these fixes down and would fail against the
brief's literal reference code.

## The M4 checkpoint (manual -- for you to run)

I cannot drive QGIS interactively, so I did not attempt this. Per the brief, run through this with the
dev symlink in place and the plugin reloaded in QGIS:

1. **Toolbar > New site...** > pick an empty folder. Expect: the survey dock shows the folder name, and
   no "modified" dot/marker appears next to `survey.nsgeo.json` (a fresh site is clean).
2. **Toolbar > Add grid...** > GNSS corners tab. Enter four corners (any UTM numbers forming a roughly
   5 x 11 m rectangle), click Fit, confirm the residual reads near zero, set id `A`, CRS `EPSG:32616`,
   confirm velocity shows `0.08`, click OK. Expect: a dashed grid outline appears on the canvas, inside a
   layer group named after the site.
3. **Right-click grid A > Import DZT files...** > Add files... > select the ten real files from
   `packages/nsgeo-core/tests/data/local/`. Expect: 10 rows in the table; `FILE__008`'s note says it
   exceeds the grid; the sidecar column shows `epsilon_r 14` for nine of the files. Uncheck `FILE__005`,
   confirm `FILE__006` moves to offset `2.00`. Re-check `FILE__005`. Click Import; expect 10 lines
   imported.
4. Expect: ten coloured lines appear inside the grid outline, with one mark point at the end of
   `FILE__007`. Click a line in the survey dock's tree. Expect: nothing visible changes yet (there is no
   viewer until a later task), but **no error appears**, and the QGIS task bar briefly shows a background
   load running (this is what Task 12 adds -- the click triggers `LineLoader` in the background rather
   than blocking).
5. **Toolbar > Save site.** Open the saved `survey.nsgeo.json` in a text editor: expect grids to carry a
   `velocity` field and lines to carry `placement` data. Open the `.nsgeo.gpkg` file in QGIS's browser
   panel: expect four tables.
6. **Digitise tab: Add grid...** > Digitise on map > Pick on map > two clicks on the canvas. Expect: the
   dialog returns with origin and azimuth fields filled in; enter sizes and id `B`, click OK. Expect: grid
   B appears on the canvas.

Anything that fails here should be fixed before Task 13 starts.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/loader.py` (new, 167 lines)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (modified: import, `__init__` field, `initGui()`
  construction, `unload()` teardown -- 15 lines added, 0 removed)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py` (new, 224 lines: the brief's 4 tests + 4 added)

Commit: `eed9ec1` "feat: load line samples on a QgsTask" on branch `nsgeo-qgis`.

## Self-review findings

- Checked naming against the rest of the plugin: `LineLoader`, `_tasks`, `_pending`, `request`,
  `is_loading`, `loading_changed`, `wait_for` all read consistently with `SiteSession`/`SiteLayers`'s
  existing style (short, literal, no abbreviations beyond what's already established).
- Checked for YAGNI: did not add a `cancel()`/`shutdown()` method to `LineLoader` even though `unload()`
  needed to "decide what happens" to in-flight tasks -- the decision (let them finish; `_pending` plus
  the site-identity check makes that safe) needed no new public API, only the internal `_pending` set.
  Did not add per-site task scoping (e.g., keying `_tasks`/`_pending` by `(site, key)` pairs) -- that
  would fix nothing further given the site-identity check already makes a stale write impossible; it
  would only add complexity for no behavioural gain.
- Checked the extra tests assert on state, not on implementation: all four added tests assert on
  `session.profiles_for()`/`session.stack_for()`/`loader.is_loading()`/the `loading_changed` signal's
  observed sequence -- none assert on `loader._tasks` or `loader._pending` directly except where a test
  needs `_wait_signal` because `wait_for()` cannot apply (documented inline why).
- Re-read `finished()` once more end-to-end after the two fixes: confirmed `_tasks.pop` and
  `_pending.discard` are unconditional and precede the `try`, confirmed the site-identity check is fully
  inside the `try` and short-circuited, confirmed `loading_changed.emit` is the only thing in `finally`.
- Confirmed the module boundary guard (`test_plugin_boundary.py`) still passes: `loader.py` imports
  nothing from `nsgeo.processing` and no direct `PyQt5`/`PyQt6`.
- Ran the new test file and the full qgis tier multiple times each to rule out flakiness from the
  concurrency additions; all stable.

## Concerns

- **`LineLoader` and `SiteSession` are both parentless `QObject`s**, relying entirely on Python reference
  counting (plus, for `LineLoader`, the new `_pending` set) for their lifetime -- there is no Qt
  object-tree parent anchoring either one. I verified `unload()`'s specific ordering (`self.loader = None`
  before `self.session = None`) keeps a live reference chain for as long as `unload()` itself is running,
  which is what the added test exercises. I did *not* verify what happens if a load outlives the *entire*
  unload() call and every other reference plugin.py holds (docks, layers, etc.) has also been torn down
  by then -- at that point `{loader, task, session}` could become a reference cycle with no external
  anchor, and Python's cyclic garbage collector would eventually reclaim it (not necessarily immediately
  or synchronously with anything else). I believe this is a pre-existing characteristic of how this
  plugin constructs its major QObjects (`SiteSession`, `SiteLayers` are equally unparented, equally
  reliant on `self.<attr> = None` plus refcounting), not something Task 12 introduced, and fixing it
  would mean re-architecting parenting for objects outside loader.py's scope. Flagging it rather than
  silently declaring the "unload() mid-load" decision fully solved for every possible timing.
- The four extra tests (concurrent loads, dropping the loader reference, switching sites, closing the
  site outright) go beyond the brief's four specified tests. I believe each is warranted by a real defect
  or a real, plausible race the brief's file list and "concurrency deserves its own pass" instruction
  asked for, but flagging the count in case a reviewer wants a smaller footprint here.

---

# Fix round 1

The reviewer's controlled experiments confirmed all three deviations from the original submission
(site-identity check, the short-circuit fix, and `_pending` as a load-bearing keep-alive -- refcount 2
immediately after `addTask`, work never running when dropped while queued, `on_finished` never firing
when dropped mid-read) and found nine further issues: one real bug (Finding 1) and four guards that were
correct but shipped with no test proving it (Findings 2, 4, 5, 6), plus a genuine gap in the failure path
(Finding 7), an unchecked return value (Finding 8), a vacuous assertion (Finding 9), and a missing
plugin-wiring check. This section is a straight record of what changed and how each fix was verified.

## Corrections to the original report

The reviewer is right on both counts:

- **`test_dropping_the_loader_reference_does_not_lose_an_in_flight_load` does not exercise `_pending`.**
  My original report's audit table claimed it did. It does not: in that test, `session` (the test's own
  local, still alive) keeps the loader reachable through its signal connections to the loader's bound
  methods, exactly as the test's own (already-corrected, mid-task) docstring says. `_pending` is
  exercised by the two site-close tests, where the task keeps running after `_tasks.clear()` has already
  dropped the loader's other reference to it. The test itself needed no change; only my claim about what
  it proved was wrong, and I have not touched that claim again here since the docstring already reads
  correctly.
- **The coverage claims for Findings 2 and 4 in my original report were wrong.** I wrote that the brief's
  four given tests exercised the key-removal race and the duplicate-request guard. They do not:
  `test_reopening_a_loaded_line_does_not_reload` reaches `_on_line_opened` a second time only after
  `open_line()`'s own early-return on an unchanged key -- which means `request()` is never even called
  for the second `open_line(a)`, let alone while the first load is genuinely in flight -- so neither the
  duplicate-request guard nor a load-in-flight key-removal path was ever driven by it. Both now have
  their own tests (below).

## The nine findings

**Finding 1 -- a stale task's `finished()` could pop and report on a live task's entry (Important).**
`finished()` unconditionally did `self._tasks.pop(key, None)` and unconditionally emitted
`loading_changed(key, False)`. A stale task (its originating site closed, `_tasks.clear()` having freed
its key for a fresh request under the same key string) reporting *after* a new, live task had already
been registered for that key would tear the live task's bookkeeping down: `is_loading(key)` would go
`False` and `wait_for(key)` would report success while the live task was still genuinely running.

Fix: `finished()` now computes `live = self._tasks.get(key) is task` right after discarding itself from
`_pending`, and only pops `_tasks`/emits `loading_changed` `if live`. The `_pending.discard(task)` line
stays unconditional -- every task, live or stale, must release its own keep-alive slot regardless.

Test: `test_a_stale_tasks_finished_does_not_clobber_a_live_tasks_bookkeeping`. Rather than race two real
background reads (unreliable -- there is no way to guarantee which of two real disk reads finishes
first), it controls the interleaving directly: grab site A's task, close the site, open site B with the
same relative key (registering its own, live task), then call site A's *stale* `on_finished` directly --
the exact production callback, invoked at a moment of the test's choosing rather than whenever its own
background thread happens to finish. This is legitimate because `on_finished` is a plain, reassignable
Python attribute on the `QgsTaskWrapper` instance (confirmed directly), so calling it is calling exactly
what QGIS's own task manager would call, on demand.

Mutation: reverted `finished()` to the unconditional pop + emit shown in the original report. The test
failed with `is_loading('raw/FILE__001.DZT')` returning `False` while `task_b` was still genuinely
in flight.

**Finding 2 -- the brief's headline race had no test (Important).** Confirmed by the reviewer: dropping
the `key in self.session.keys()` half of `finished()`'s check (leaving only `same_site`) left all 8
original tests passing. The reason is not that the check was unnecessary -- it's that `remove_line()`'s
own cleanup (`site.stacks.pop(key, None)`, `del self._lines_by_key[key]`) makes `set_profiles()` raise a
`KeyError` from inside `stack_for()` regardless of whether `finished()`'s own check runs first, so
`session.profiles_for(key) is None` holds either way and does not discriminate.

Test: `test_removing_the_line_mid_load_is_not_written_back`. It asserts `errors == []` instead --
discriminating because Finding 7's new `except` clause (see below) routes that `KeyError` to `on_error`
if and only if `finished()` actually attempted `set_profiles()`, which only happens if the key-presence
check is missing.

Mutation: `still_present = same_site and key in self.session.keys()` -> `still_present = same_site`. The
test failed: `errors` contained `('raw/FILE__001.DZT', "no line with key 'raw/FILE__001.DZT'")`.

**Finding 3 -- `wait_for()` could report success after a bare timeout (Important).** It returned
`key not in self._tasks`, computed *after* `finished()`'s own `pop` (not after a confirmed `emit`) --
so if the pairing between "pop" and "emit" that Finding 1 relies on were ever broken elsewhere, or the
key were removed from `_tasks` by anything other than a genuine, reported finish, `wait_for` would agree
with the timeout rather than say so.

Fix: `wait_for` now tracks `fired` (set only inside `on_change`, which only runs on a real
`loading_changed(key, False)` emission) and returns `fired and key not in self._tasks`.

Test: `test_wait_for_does_not_report_success_from_a_timeout_alone`. Manually seeds `_tasks["ghost"]` with
a plain `object()` (nothing real is loading it) and schedules a `QTimer.singleShot(20, ...)` that pops
`"ghost"` from `_tasks` without ever emitting `loading_changed` for it -- standing in for exactly the
"guarantee broken elsewhere" scenario the fix defends against, without needing a real task at all.

Mutation: reverted `wait_for` to `return key not in self._tasks`. The test failed: `wait_for('ghost',
timeout_ms=200)` returned `True`.

**Finding 4 -- `request()`'s duplicate-in-flight guard had no test (Important).** Confirmed by the
reviewer, and corrected in this report's audit above: `test_reopening_a_loaded_line_does_not_reload`
does not exercise it, because `open_line()`'s early-return means `request()` is never reached a second
time while the first load is still in flight.

Test: `test_request_is_a_no_op_while_already_in_flight`, calling `loader.request(key)` twice directly
(public interface, reachable outside the `open_line` path) and asserting exactly one `(key, True)`.

Mutation: `if key in self._tasks or self.session.profiles_for(key) is not None:` ->
`if self.session.profiles_for(key) is not None:`. The test failed: `states` contained two `(key, True)`
entries instead of one.

**Finding 5 -- `_on_site_closed`'s `_tasks.clear()` had no test (Minor, promoted).** Pinned by the same
Finding-1 test: its `assert task_b is not task_a` only holds if `_on_site_closed` actually frees `key` --
otherwise `request()` for site B would see `key` still "in flight" and silently skip registering
`task_b` at all, leaving `loader._tasks[key]` pointing at `task_a` still.

Mutation: `_on_site_closed` body replaced with `pass`. The test failed at `assert task_b is not task_a`
(both sides were the same object).

**Finding 6 -- the empty-key guard had no test (Minor, promoted).** `close_site()` emits
`line_opened("")` whenever a line was current (per its own docstring); `_on_line_opened`'s `if not key:
return` exists to treat that as a no-op rather than routing `""` into `request()`.

Test: `test_line_opened_empty_key_is_a_no_op`: open a line, close the site, assert `errors == []`.

Mutation: removed the `if not key: return` guard. The test failed: `errors == [('', 'no site is open')]`
(`request("")` reached `line_for_key("")`, which raises `_require_site()`'s `ProjectError` since the site
is already gone by the time `close_site()` emits).

**Finding 7 -- a main-thread failure after a successful load was invisible (Minor, promoted -- but the
one with the most reach).** `finished()`'s `try/finally` had no `except`. `QgsTaskWrapper.finished()`
(QGIS's own code) swallows any exception an `on_finished` callback raises completely -- confirmed by
reading its source: a bare `except Exception as ex: self.exception = ex`, no logging, no re-raise,
nowhere for it to go. Worse than the standing signal/slot hazard (which at least reaches stderr).

Fix: `finished()` now has its own `except Exception as exc: ... self.on_error(key, str(exc))` around the
whole try body, so a bug in `set_profiles` or anywhere else on that path reaches the message bar instead
of vanishing. (The `finally` clause's `pop`/`emit`, gated by `live`, still runs regardless, per Finding 1
-- `except` and `finally` compose normally here.)

Test: `test_an_unexpected_failure_after_a_successful_load_is_reported_not_lost`, monkeypatching
`session.set_profiles` to raise `RuntimeError("boom")` and asserting it reaches `on_error`.

Mutation: removed the `except` clause. The test failed: `errors == []` (the `RuntimeError` propagated out
of `finished()`, through the guaranteed `finally`, and was silently swallowed by `QgsTaskWrapper.finished()`
with no trace at all -- exactly the invisible-failure mode this finding is about).

**Finding 8 -- `addTask()`'s return value was unchecked (Minor, promoted).** `addTask()` returns `0`
(confirmed via its docstring: "return: unique task ID, or 0 if task could not be added") if it could not
schedule the task at all -- and per the module's own `_pending` docstring, nothing else keeps an
un-scheduled task alive either, so `on_finished` would never run for it, permanently pinning
`is_loading(key)` `True`.

Fix: `request()` now checks the return value and, on failure, rolls back its own bookkeeping (`_tasks`,
`_pending`, `loading_changed(key, False)`) and reports through `on_error`.

Test: `test_a_task_the_manager_refuses_to_schedule_does_not_pin_the_key_forever`, monkeypatching
`QgsTaskManager.addTask` (confirmed patchable directly) to always return `0`.

Mutation: reverted to `QgsApplication.taskManager().addTask(task)` with the return value discarded. The
test failed: `is_loading(key)` stayed `True` forever.

**Finding 9 -- one vacuous assertion (Minor).** Removed `assert not session.is_open` from
`test_closing_the_site_entirely_mid_load_does_not_crash_the_callback` -- true by construction from
`close_site()` two lines above and asserting nothing about the loader.

**Plugin-wiring check.** Added `assert plugin.loader is not None` (after `initGui()`) and
`assert plugin.loader is None` (after `unload()`) to
`test_class_factory_builds_a_plugin_that_adds_and_removes_its_ui` in `test_plugin_loads.py`, matching the
existing convention for `plugin.toolbar`.

## A consequence of Finding 1: two existing tests had to change how they wait

`test_switching_sites_mid_load_does_not_write_into_the_new_site` and
`test_closing_the_site_entirely_mid_load_does_not_crash_the_callback` both used to wait on
`loading_changed` firing for the stale task. With Finding 1's fix, a stale task (one that is no longer
"live" for its key) no longer emits `loading_changed` at all -- correctly, since Finding 1 exists
precisely to stop it from claiming to have ended a request nobody is tracking. Both tests now grab the
stale task's `QgsTask` object directly (before `close_site()` clears it out of `_tasks`) and use a new
helper, `_wait_for_task_finished(task)`, which wraps `task.on_finished` to detect completion directly
rather than through the loader's own signal.

## Verification (fix round 1)

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
  -> 315 passed, 2 skipped

.venv/bin/ruff check .
  -> All checks passed!

.venv/bin/ruff format --check .
  -> 74 files already formatted

.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  -> Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
  -> 179 passed   (164 baseline + 15 in test_plugin_loader.py; test_plugin_loads.py's existing test
     grew two assertions rather than a new test)
```

Re-ran the qgis tier three times back to back: stable at 179 passed, ~55-60s each time.

**Mutation testing, all nine findings:** each fix was reverted in isolation (the rest of the file left
exactly as fixed), its named test run alone, confirmed to fail, and the file restored before moving to
the next. Summary of the nine RED results (all captured live, not reconstructed):

| Finding | Mutation | Test | Result without the fix |
|---|---|---|---|
| 1 | unconditional pop/emit in `finished()` | `test_a_stale_tasks_finished_does_not_clobber_a_live_tasks_bookkeeping` | `is_loading(key)` False while task_b still running |
| 2 | `still_present = same_site` (key check dropped) | `test_removing_the_line_mid_load_is_not_written_back` | `errors` non-empty (`no line with key ...`) |
| 3 | `wait_for` returns `key not in self._tasks` | `test_wait_for_does_not_report_success_from_a_timeout_alone` | returned `True` after the bare timeout |
| 4 | `request()` guard drops `key in self._tasks or` | `test_request_is_a_no_op_while_already_in_flight` | two `(key, True)` emissions, not one |
| 5 | `_on_site_closed` body replaced with `pass` | `test_a_stale_tasks_finished_does_not_clobber_a_live_tasks_bookkeeping` | `task_b is not task_a` failed (same object) |
| 6 | `_on_line_opened`'s `if not key: return` removed | `test_line_opened_empty_key_is_a_no_op` | `errors == [('', 'no site is open')]` |
| 7 | `finished()`'s new `except` clause removed | `test_an_unexpected_failure_after_a_successful_load_is_reported_not_lost` | `errors == []` (exception vanished) |
| 8 | `addTask()`'s return value discarded | `test_a_task_the_manager_refuses_to_schedule_does_not_pin_the_key_forever` | `is_loading(key)` stuck `True` |
| 9 | (assertion removed, not a code fix) | -- | -- |

After each mutation the file was restored (`diff` confirmed byte-identical to the fixed baseline) and the
full loader test file plus `test_plugin_loads.py` (16 tests) was re-run green before committing.

## Files changed (fix round 1)

- `packages/nsgeo-qgis/nsgeo_qgis/loader.py` (Findings 1, 3, 7, 8: production changes; module docstring
  extended with the fourth and fifth "things verified directly")
- `packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py` (7 new tests for Findings 1/5, 2, 3, 4, 6, 7, 8;
  2 existing tests changed to wait on the stale task directly instead of `loading_changed`; 1 vacuous
  assertion removed for Finding 9; helper `_wait_signal` replaced by `_wait_for_task_finished`)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` (2 assertions added for the plugin-wiring check)

Commit: `5ca6699` "fix: loader review round 1 -- stale-task clobbering, three undefended guards, and an
invisible main-thread failure path", on top of `eed9ec1`.

## Concerns carried forward

- The parentless-`QObject` lifetime concern from the original report stands unchanged; nothing in this
  round touched it.
- Findings 2 and 4's tests both depend on Finding 7's `except` clause to discriminate cleanly (without
  it, the exception Finding 2's mutation causes would itself vanish silently, the same way the original,
  unfixed code would have masked it) -- this is a real interaction between two of the nine fixes, not a
  weakness in either test on its own, but worth naming: the two are not independently verifiable from
  each other under this specific mutation.

---

# Fix round 2

The reviewer independently re-ran every round-1 mutation and confirmed all eight code fixes test-for-test,
confirmed F8's rollback leaves clean state with a healthy later load, and confirmed F7 reaches both
`QgsMessageLog` and the message bar at Critical. They also measured my carried-forward interdependence
concern precisely: `M2 + M7` together are needed for F2's *original* test to fail, but `M1 + M7` and
`M4 + M7` are not -- F1 and F4 are independent, so the concern as written overstated its own reach. Two
things remained: `test_closing_the_site_entirely_mid_load_does_not_crash_the_callback` had stopped
discriminating anything after round 1's rewrite, and F2's test should stand on its own rather than
through F7. Both are test-only; `loader.py` is unchanged in this round.

## Finding 1 -- the close-site test discriminated nothing (Important, new)

Root cause: `_wait_for_task_finished` (added in round 1 to work around Finding 1's own fix removing the
`loading_changed` emit for a non-live stale task) appended to `done` inside a bare `finally`, so it
returned `True` regardless of whether the wrapped `on_finished` callback raised. The rewrite traded a
wait that required `finished()` to reach its emit for one that required nothing at all -- any exception
inside the wrapped callback vanished into `QgsTaskWrapper.finished()`'s own swallow, exactly the hazard
the module docstring warns about, and the helper meant to detect completion could no longer tell "ran" from
"ran and blew up."

Two mutations exploited this, and needed two different fixes:

- **Eager evaluation, still caught by Finding 7.** `present = key in self.session.keys()` computed
  unconditionally but still inside `finished()`'s own `try` -- the historical bug my original report's
  test was meant to guard against. `self.session.keys()` raises (site is `None`); Finding 7's `except`
  catches it and routes it to `on_error`. `_wait_for_task_finished` never sees an exception at all (the
  wrapped callback returns normally), so it correctly reports `True` -- but a spurious Critical
  message-bar entry (`[('raw/FILE__001.DZT', 'no site is open')]`) fired on every site close with a load
  in flight, invisible to the old test.
- **Raising outright, escaping the callback entirely.** The same eager, unconditional
  `present = key in self.session.keys()`, but computed *before* `try:` rather than inside it -- so the
  `ProjectError` is not caught by Finding 7's `except` (which only wraps the `try` block) and propagates
  straight out of `finished()`. The *old* helper's bare `finally: done.append(True)` still recorded this
  as "done," so `_wait_for_task_finished` returned `True` for a callback that had, in fact, blown up.

Fix, both halves:
- (a) `_wait_for_task_finished` now wraps the call in `try/except Exception: raised.append(True); raise
  /finally: done.append(True)`, and returns `bool(done) and not raised`. The `raise` after recording
  keeps the wrapped callback's behaviour faithful to what QGIS's real `on_finished` invocation would see
  (still swallowed one level up, by `QgsTaskWrapper.finished()`, but the helper itself now knows).
- (b) `test_closing_the_site_entirely_mid_load_does_not_crash_the_callback` gained an `on_error` recorder
  and `assert errors == []`, which is what actually catches the eager-but-caught case -- (a) alone cannot,
  since that case never reaches the wrapped callback as a raised exception.

`test_switching_sites_mid_load_does_not_write_into_the_new_site` uses the same helper and was already
discriminating the site-identity guard correctly (its own scenario reaches `finished()` with `same_site`
false via a real, different `Site` object, not via `session.keys()` raising) -- (a) strengthens it as a
side effect but it needed no changes of its own.

Verified live, both mutations, against the fixed test:
```
eager evaluation (still inside try)   -> FAILED: assert errors == []  (['raw/FILE__001.DZT', 'no site is open'])
raises outright (before try entirely) -> FAILED: assert _wait_for_task_finished(stale_task)
```

## Finding 2 -- give F2's test a standalone formulation (from my own carried-forward concern)

Replaced the error-recorder formulation with a direct write-spy, exactly as suggested: monkeypatch
`session.set_profiles` to a lambda that records the key and never raises, so the test pins "`finished()`
must not attempt the write-back" without any dependence on whether attempting it would also have been
visible as an error (it is, today, via Finding 7 -- a separate, already-covered concern).

```python
calls = []
monkeypatch.setattr(session, "set_profiles", lambda k, v: calls.append(k))
session.remove_line(key)
assert loader.wait_for(key)
assert calls == []
```

Verified live:
```
M2 alone (still_present = same_site, key check dropped)      -> FAILED: assert calls == []  (['raw/FILE__001.DZT'])
M2 + M7 (except clause also removed)                          -> FAILED: assert calls == []  (['raw/FILE__001.DZT'])
```
Both fail identically, confirming the new formulation no longer depends on Finding 7 at all -- the spy
lambda never raises regardless of whether it runs, so M7's presence or absence is irrelevant to whether
this test catches M2.

## Verification (fix round 2)

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
  -> 315 passed, 2 skipped

.venv/bin/ruff check .
  -> All checks passed!

.venv/bin/ruff format --check .
  -> 74 files already formatted

.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  -> Success: no issues found in 23 source files

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
  -> 179 passed   (unchanged from round 1: this round strengthened two existing tests and the shared
     helper, added no new test functions)
```

Re-ran the qgis tier three times back to back after the fix: stable at 179 passed each time (~55s).
After each of the four mutations above, the loader test file (and, separately, the whole qgis tier once
at the end) was confirmed green again on the restored, fixed tree (`diff` against the pre-mutation
baseline confirmed byte-identical before each re-run).

## Files changed (fix round 2)

- `packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py` only -- `loader.py` needed no further production
  changes this round. `_wait_for_task_finished` gained `raised` tracking; the close-site test gained an
  `on_error` recorder and assertion; the removed-line test's body was replaced with the write-spy
  formulation (its signature gained `monkeypatch`).

Commit: `b78ebc5` "fix: loader review round 2 -- close-site test discriminates nothing, F2 test given a
standalone formulation", on top of `5ca6699`.

## Concerns carried forward

- The parentless-`QObject` lifetime concern from the original report stands unchanged.
- Deferred by the reviewer, not addressed here: `loading_changed` is no longer balanced on the stale
  path (a load in flight when `close_site()` is called leaves `states == [(key, True)]` with no matching
  `False`, by design of the round-1 `if live:` gate) -- no production consumer exists today, and
  `_on_site_closed` already zeroes `is_loading()` for every key regardless, so any future per-key spinner
  would need to reset on `site_closed` in any case. Noted for whoever adds such a consumer: if balance is
  wanted without reintroducing Finding 1, gate the *emit* on `live or key not in self._tasks` rather than
  gating the pop.
- Also deferred by the reviewer: `loader.py` is not part of the repo's mypy invocation (only
  `nsgeo_qgis/lookup.py` and the core package are checked per the Global Constraints command), and one
  test (`test_wait_for_does_not_report_success_from_a_timeout_alone`) stores a plain `object()` in a dict
  annotated `dict[str, QgsTask]` -- harmless at runtime (Python does not enforce the hint) and not
  type-checked, but worth naming for anyone who later adds `loader.py` to the mypy invocation.
