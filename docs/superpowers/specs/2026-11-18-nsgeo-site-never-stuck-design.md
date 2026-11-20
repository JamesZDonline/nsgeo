# Whole site: never stuck, never frozen (session H)

Date: 2026-11-18. Branch `nsgeo-site-never-stuck`, from `origin/main` b69c31c.
Issues: #166, #193, #75 (the Site engine, Site export and Whole site UI sections),
#157 items 1 and 3. Session plan: https://claude.ai/artifact/A1w1dKGNENHd2S2GbmqECj.

Paths are under `packages/nsgeo-qgis/nsgeo_qgis/` unless they start with `nsgeo/`,
which is `packages/nsgeo-core/src/nsgeo/`. Line numbers are from 9691c7b.

## Why

Whole site is where a person sees a whole survey at once, and today it can fail
them in two ways:

- **It can get stuck.** About 3 CI runs in 100, on both QGIS majors, the site
  engine never finishes preparing (#166). Nobody has seen it in the plugin yet,
  but the same lost wakeup in a real session would leave Whole site at
  "preparing the site…" until something else kicks the queue.
- **It freezes QGIS at a fine cell** (#193). At the session A walkthrough, typing
  0.02 m on the ten-grid site froze QGIS for about 105 s. The author's words:
  "It froze QGIS." This grid has the same freeze, about 24 s at 0.02 m on one
  grid. The author chose to keep Cell size's 0.05 m wheel step, so two notches
  down from 0.1 m reach the 0.01 m floor.

Alongside, the session clears the site engine's review leftovers (#75's H
sections, several of which are suspects for #166) and two fine-cell follow-ups
(#157 items 1 and 3).

## Goals

1. Whole site always finishes preparing, or a timed-out wait says exactly what
   holds it.
2. No fine cell freezes QGIS in Whole site or This grid. The fill is worked out
   in the background with progress and a Cancel, and the map keeps the last
   picture until it lands.
3. The #75 items in H's sections are fixed or listed as already gone.
4. #157 item 1 (coverage misses an edge line on coarse previews) and item 3
   (north-up plans hold more memory than they say) are fixed.

## Non-goals

- #75's **Core `site.py`**, **Survey memory** and **Tooling and docs** sections:
  session N.
- #196, the refine-test flake under load: session N. It shows up when the
  site-scope tests are looped; note it and move on. It fails at
  `assert finished_late.is_set()`, which is not the hang.
- #157 item 2 (averaged previews): later, with #138.
- Speeding up the fill itself (`_neighbourhoods`). Even 4× faster, ten grids at
  0.01 m would still take minutes, so the background fill is needed anyway.
- Other places that build a fill on the GUI thread: a cut's section
  (`section_fills`, via `cut_sections.py`) and the ParaView export
  (`paraview_export.py:826`). They stay as they are; one follow-up issue is
  filed for both.
- **The work after the fill lands** (the author's call, at the builder check).
  It stays on the GUI thread for now:
  - each draw applying every grid's fill;
  - the shared stretch, which applies fills at up to 12 windows per grid in
    Whole site, and at every window in This grid with IDW or kriging
    (`SliceEngine.shared_limit`);
  - This grid's first north-up draw on a new frame.

  Estimated, not measured:
  - ten grids at 0.02 m: about 0.25 s a tick and 3 s for the stretch;
  - ten grids at 0.01 m: about 1 s a tick and 10 s for the stretch.

  These are **measured before Plan B is written** (see Part 5).

## Anti-goals

- **A watchdog that hides the lost wakeup**, such as a timer that re-kicks the
  queue. The cause gets fixed, or the report names it next time.
- **Closing #166 on a race found only by reading the code.** The author's rule:
  #166 closes only if the local loop reproduces the hang and the fix stops it.
- **A fill that lands for settings no longer chosen**, such as a 0.02 m fill
  drawn after the cell went back to 0.1 m.
- **A half state after Cancel**, such as a panel that says 0.01 m over a map
  drawn at 0.05 m with nothing working.
- **Refusing or coarsening a cell.** The author chose to keep the cell they
  asked for. The 0.05 m step and the 0.01 m floor stay.

## Approaches considered

**#193.** Three ways were on the table (from the issue):

1. Work out the fill off the GUI thread, with progress and a Cancel, as minimum
   curvature's refine already works (`Refiner`, `refine.py:71`). The map keeps
   the last picture until the fill lands.
2. Draw a coarser live picture when the fill would be slow, say so under
   Warnings, and let export keep the full cell.
3. A cost guard that refuses a cell whose fill would take more than a few
   seconds, with a Warnings entry.

**The author picked 1, wired into This grid as well as Whole site.** It is the
only option that never freezes QGIS and still shows the cell asked for. Options
2 and 3 both need a cost model that predicts the fill time before it runs, and
the cost isn't linear in the number of cells. A probe on a synthetic 20 × 16 m
grid of lines 0.5 m apart measured the plan's cost per cell:

| Cell | Plan cost per cell |
|---|---|
| 0.1 m | 2.7 µs |
| 0.05 m | 6.4 µs |
| 0.03 m | 15 µs |

The neighbour search covers a disc whose radius in cells doubles each time the
cell halves. Extrapolated, one grid takes about 22 s at 0.02 m, which matches the
24 s measured, and about 4 minutes at 0.01 m. Ten grids at 0.01 m would take
nearer 20 minutes than the 7 the issue estimated. Option 3 would also refuse what
two wheel notches reach.

**#166.** Reproduce it first by looping the site-scope tests under load. If it
won't reproduce, still ship the `settle()` report and the #75 suspects. Also fix
every lost-wakeup path found by reading the code, each pinned by a deterministic
test. **The author's rule:** #166 stays open unless the loop reproduces it and the
fix stops it.

## Delivery

One branch and one PR, built from **two plans** of 3–6 tasks each:

- **Plan A, the engine:** #166, #75's Site engine items, #157 items 1 and 3, then
  #75's Site export and Whole site UI items.
- **Plan B, the background fill:** #193 in both scopes.

Plan B is written after Plan A is built, so it plans against the engine as Plan A
leaves it. One short walkthrough covers both, and merging asks the author first.

## Part 1: #166, Whole site sometimes never finishes preparing

### Today

- `SiteEngine.is_running` (`site_engine.py:316`) is true while any of these
  holds:
  - `_preparing` is set;
  - `_active` is set and `_queue` is non-empty;
  - `has_live_task` (:324) is true for any engine, retiring ones included.
- `_start_next` (:545) returns without arming the retry while `_preparing` is
  set. So if `_preparing` is never cleared, nothing dispatches again.
- In the CI failures, the test's 60 s wait ran out with no exception and no
  captured log.

### The report

- **What it says.** The engine gains a method that describes, in plain text, what
  is keeping it running:
  - `_active`, `_preparing` (and whether its registration still matches
    `_preparing_fp`), and `_queue`;
  - whether the retry and reaper timers are active, and `_in_dispatch`;
  - for each engine (owned, retiring, and `exclusive_with` peers): which grid it
    is, `is_running`, `has_live_task` and its pending-task count;
  - each grid's `grid_state` and progress.
- **Where it shows.** It goes in the assertion message wherever a test waits for
  the site:
  - `settle()` in `tests/qgis/test_plugin_site_scope.py:116`;
  - the helper in `tests/qgis/test_plugin_site_engine.py:81`;
  - the bare `assert site.wait_until_idle(...)` calls in those files, through
    one shared helper.

  The brief's pointer to `tests/plugin_testing.py:441` is the layout probe's
  `settle`, not a site wait, so it is unchanged.
- **Test, failing first:** a timed-out wait names what holds it.

### Reproducing it

- Loop `test_plugin_site_scope.py` under load, with several copies at once. That
  is how #196 was reproduced: 12 copies × 3 rounds on this 4-core machine.
- Do it on QGIS 3.44 and on 4.2 (Docker, `qgis/qgis:4.2`) if the first doesn't
  show it.
- Every timed-out run now prints the report.
- How long to loop before giving up is the builder's call. Record the batches
  run, and any #196 failures seen along the way, in the decision record.

### The fix

- Root cause first (systematic debugging). Each lost-wakeup path found gets a
  test that drives its interleaving deterministically, as #41's fix did, by
  calling the engine's callbacks in the bad order or stubbing an engine. Each
  test must fail before its fix.
- **Starting points:**
  - `_on_engine_prepared` (:584) returns early, with `_preparing` still set,
    when the grid's registration no longer matches `_preparing_fp`. It counts on
    `_on_grid_moved` arriving afterwards. If that never comes, or came earlier,
    nothing clears `_preparing`.
  - `_preparing_fp` is captured (:557) before the "preparing 0 of n" notify, and
    the dispatch gate isn't re-run after that notify (a #75 item).
  - Retiring engines stay connected, and disposed engines stay parented (#75
    items).
  - The places where `_preparing` and `_queue` are set: :381, :385, :428, :557.
- **When this merges:**
  - Close #166 only under the author's rule above.
  - Otherwise, comment on #166 with what the report now says and what was
    fixed, and leave it open.

## Part 2: #75, the Site engine section

**Check each item against main before fixing it.** Sessions A and B rewrote much
of the site scope and the dock after #75 was written. Items found already gone
are listed, not fixed. Known so far:

- **F-9 is done.** `SlicesDock._resume_grid` (`ui/slices_dock.py:3536`) hands the
  hook back from a `finally`, and its docstring cites #75 F-9.
- `SiteScope._note_z_edit` is gone. Its replacement is cited at
  `ui/slices_dock.py:2649`. That item is in the UI section.
- `_dispatch_again` still exists. The dispatch loop uses it.

**The items:**

- **The geometry rebuild runs inside the `grids_changed` emission.** Document the
  assumption, or defer the rebuild with a 0 ms single-shot. Builder's call, with
  the reason recorded.
- **The gate isn't re-run after the progress notify.** Re-check the gate, and
  re-capture `_preparing_fp`, after the notify.
- **Retiring engines stay connected,** so a deleted grid's task that outlives its
  cancel wait causes a second bounded wait and an extra "no longer exists"
  report. Disconnect a retiring engine, so its waits don't stack.
- **Disposed engines stay parented.** `deleteLater()` after `dispose()`.
- **The progress total can shift.** It counts choice keys at dispatch, while the
  engine reports resolved jobs. Make the list read one total from start to
  finish.
- **Mixed-CRS edge cases:**
  - `_transform` makes one Python call per point. Vectorise it.
  - The site CRS follows the first grid only as of the last rebuild. Rebuild
    when it changes, or document it. Builder's call, with the reason recorded.
  - `_azimuth_in`'s cross-CRS result gets a test.
- **Test gaps:**
  - The asynchronous failure path: a task that finishes with no lines reads
    `failed: <first error>`.
  - `test_the_hook_can_be_given_to_the_constructor` disposes its second engine.
- **Size.** `site_engine.py` is 1,489 lines. Its CRS, outline and gather helpers
  move to their own module. Pure moves, with no behaviour change. The builder
  names the module.

## Part 3: #157 items 1 and 3

- **Item 1, a missed edge line on coarse previews.**
  - In `compose_footprints` (`nsgeo/slices/site.py:265`), the reach becomes
    `max(ceil(n/√2), n − 1)`. This was verified in a scratch copy: 0 of 64
    phases miss at 8× and 16×.
  - **Test, failing first:** sweep the lattice phase across one pixel, including
    the last column, at 8× and 16×, and find no missed edge line. The current
    test's offsets miss the bad window, about 0.175–0.225 m of a 0.4 m pixel at
    8×.
- **Item 3, north-up plans hold more memory than they say.**
  - The plans are the `Taps` built by `nsgeo/slices/resample.py` and cached two
    deep by `functools.lru_cache` in `nsgeo/slices/display.py:267–271`. The
    brief pointed at `_plans` in `slices_engine.py`, but those are the line
    binning plans, not these.
  - An exact (axis-aligned) plan only reads `nearest`, so it drops its `ids`
    and `weights`: 3.2 MB instead of 41.6 MB at 800 k cells.
  - The cached plans are counted in the held memory the status line reports.
    How the cache exposes its size is the builder's call, since an `lru_cache`
    doesn't list what it holds.
  - **Tests, failing first:** an exact plan holds no `ids` or `weights`, and
    held memory counts the cached plans.

## Part 4: #75, the Site export and Whole site UI sections

Read #75 itself (`gh issue view 75`) and check every item against main first,
as in Part 2. The items are as #75 lists
them:

- **Site export:**
  - share the writer and temporal helpers with `slice_export.py`;
  - record the source's transform, checked against the engines' `choice.transform`;
  - `NSGEO_SITE_CELL_M` is the export cell, never the lattice pixel;
  - put `site_export.py` under CI's mypy and fix what it finds (see #18);
  - fix the stale module docstring;
  - the five test fixes.
- **Whole site UI:**
  - the unguarded slot, if it still exists;
  - `SiteScope` reaching into the dock: a `Protocol`, and moving `_snap_inside`
    out;
  - level rounding written twice;
  - dz seeded from the first ready grid rather than the finest, if session A
    hasn't already changed this;
  - the export method's busy check;
  - the seeding-rule tests;
  - the self-compared velocity assertion.

If an item is bigger than #75 makes it look, the builder stops and reports it
rather than growing the plan.

## Part 5: #193, the fill worked out in the background (Plan B)

### Today

- A live draw builds a grid's fill on the GUI thread whenever the fill it holds
  doesn't match. The fill is IDW or kriging weights, or minimum curvature's plan
  plus its kriging preview. The match is on the key (frame, method, max distance,
  search radius) and on the window's covered cells.
- The **Whole site** path: `SiteScope._run_tick` → `refresh_slice`
  (`ui/site_scope.py:986`) → `SiteEngine.slice_at` → each engine's `finish` or
  `preview` → `SliceEngine._fill_for` (`slices_engine.py:1409`) → `plan_fill` →
  `_neighbourhoods` (`nsgeo/slices/interpolate.py:278`, :200).
- The **This grid** path: `SlicesDock._finished` (`ui/slices_dock.py:~3005`) →
  the same engine calls.
- **The stretch measurement builds too.** `stretch_limit` / `shared_limit`
  finish up to twelve windows.
- **Export doesn't freeze.** The GeoTIFF exports build their fills on the export
  task's own thread (`export_pipeline.py:441`).

### Behaviour

**Decided by the author:**
- The fill is worked out off the GUI thread, in Whole site and in This grid.
- The map keeps the last picture until the fill lands.
- There is progress and a way to cancel.

**My calls (to check):**

- **What goes to the background:** any build a live draw would otherwise make on
  the GUI thread. That includes the stretch measurement's windows, and a rebuild
  because a window's covered cells differ from those the held fill was built for.
  Today's `weights_cached` compares the key only, so it can't be the test.
- **No flicker for quick fills.** The draw hands the build to the worker and
  waits up to about 0.2 s for it. If it lands in time, the draw goes ahead in
  the same tick, as today. Only a slower build switches to the working state, so
  ordinary cell changes look as they do now. No cost model is involved.
- **While working:**
  - The map layer isn't updated, so the last picture stands.
  - The refine line under the depth readout shows the work:
    - Whole site: "Working out the fill at 0.02 m: grid 3 of 10 · Cancel";
    - This grid: "Working out the fill at 0.02 m: 40% · Cancel".
  - The line keeps its one-line fixed height (walkthrough rule W1), with Cancel
    as a link in it. The wording is the builder's, in this register.
  - The slider and spins stay live. When the fill lands, the tick draws at
    whatever the panel says then.
- **A change mid-fill:**
  - A change that alters the fill's key restarts the work: cell, method, max
    distance, search radius, or which grids are ready.
  - A change that doesn't (slider, thickness, step, normalisation, smoothing,
    gains) only changes what is drawn when it lands.
  - **A fill never lands for settings no longer chosen.** On landing, the engine
    installs it only if it is still for the engine's current frame, key and
    covered cells, as `holds` does for solves.
- **Cancel:**
  - The worker stops within a fraction of a second. The core plan checks a stop
    flag between neighbour offsets and between solve chunks.
  - **With a picture on the map:**
    - The settings the fill was for (cell, method, max distance, search radius)
      go back to those of the picture on the map, so the panel and the map
      agree.
    - The undo is complete: the panel, the saved setting (the site's own, or
      the grid's, as #71 saves them), and whether the value counted as chosen
      or seeded. Reopening the survey or switching scope then finds the old
      settings, not the cancelled ones.
    - **Known cost:** going back to the old cell rebuilds that cell's fill. It
      drew before, so it is usually quick. If it was itself slow, the same
      working line shows again over the unchanged map.
  - **With no picture on the map,** for example on opening a survey whose saved
    cell is 0.01 m:
    - There is nothing to go back to, so the settings stay, saved value
      included.
    - Warnings says the picture wasn't drawn because its fill was cancelled,
      and that changing the cell or the interpolation draws again.
    - The cancel holds, so the work doesn't restart on its own. Redraws from
      the slider, a grid becoming ready, or a preparation landing build
      nothing while it holds.
    - It ends when a fill setting (cell, method, max distance, search radius)
      changes, when the scope switches, or when the survey is reopened. Each of
      those is a new request.
- **Minimum curvature:** its plan and kriging preview are built as one job. The
  refine then solves as it does today. A running refine list is still cancelled
  before a rebuild (`RefineFlow.before_draw`).
- **Leaving the work behind:** switching scope, closing the site, removing or
  unticking a grid, or a grid moving cancels the work for the engines that no
  longer want it. A landing for a dropped engine is discarded.
- **Export is unchanged.** The button keeps its current rules, and the export
  builds its own fills in its task.

### Measure first: the work after the fill lands

**The author's call:** Plan B covers the fill build only. Before Plan B is
written, measure the costs that come after the fill lands, on the Sunnyside
copy, at 0.02 m and 0.01 m, in both scopes:
- one draw (a slider tick);
- the shared stretch;
- This grid's first north-up draw.

**What happens next:**
- **If any of these is over about 1 s at 0.02 m,** stop and bring the numbers to
  the author before Plan B is set.
- **Otherwise,** they go into the follow-up issue with cuts and the ParaView
  export.

The numbers go in the decision record either way.

### How

**My calls:**

- **Core.**
  - `plan_fill` and `plan_curvature` take an optional `should_stop` and an
    optional progress callback. They raise `SolveStopped` when stopped.
  - The checks go between neighbour offsets in `_neighbourhoods`, between plan
    chunks, and between kriging solve chunks.
  - Core stays numpy-only, with no Qt, and on Python 3.9.
  - **Test:** a plan made this way is bit-identical to today's.
- **The worker.**
  - Each panel scope gets a fill worker built like the cut solve's: a `Refiner`
    with its own thread-name prefix, e.g. `nsgeo-fill`. Fill builds and
    minimum-curvature solves then never wait on each other.
  - The fill is pure numpy on a mask the job owns, with no Qt, no file reads and
    no session. So it doesn't conflict with the one-preparation-at-a-time rule
    (M12 trap 1), and it may run while a grid prepares.
- **The engine.**
  - `SliceEngine` gains three things:
    - a way to ask whether the fill for a window is held, by key and covered
      cells;
    - a fill job for the worker;
    - a landing that installs the job's fill only if it still matches.
  - The old fill is dropped before the job starts, as `_fill_for` does today, so
    memory peaks are unchanged.
  - The direct `finish` / `preview` calls keep building inline for the callers
    left out of scope: cuts and the ParaView export.
- **The scopes.** The site tick and This grid's draw ask whether the fill is
  held before drawing. When it isn't, they start the jobs and either wait the
  short budget or switch to the working state. The site's jobs run one grid
  after another, in `ready_grids` order.

### Tests, each failing first

- **The GUI is never blocked.** A fill past the budget never blocks the GUI
  thread for more than a fraction of a second, in Whole site and in This grid. A
  10 ms timer on the event loop measures it, and its largest gap stays under
  about 250 ms while a multi-second fill runs. The fixture's fill must take
  several seconds on CI's machines.
- **Cancel with a picture on the map** stops the worker promptly, puts the
  panel and the saved settings back, and draws nothing new.
- **Cancel with no picture on the map** holds: a slider move or a grid becoming
  ready builds nothing until a fill setting changes.
- **A stale fill never lands.** A fill that finishes after the cell changed is
  discarded.
- **A quick fill draws in the same tick,** with no working state shown.
- **A grid dropped mid-fill** (unticked or removed) never receives a landing,
  and the rest of the site still draws.

## Real data and the walkthrough

- **Real data.** Measure #193 before and after on a copy of the ten-grid site,
  `~/nsgeo-m4-check/Sunnyside` (10 grids). Copy it under `~/nsgeo-site-walk/`
  and never touch the original.
- **The walkthrough.** A short page on the branch's own QGIS profile, checking:
  - Whole site on the ten-grid site at a fine cell (0.02 m, then the 0.01 m
    floor): QGIS stays responsive while the fill is worked out, the progress
    line moves, and Cancel goes back to the last picture's cell. The work after
    the fill lands is out of scope (see Non-goals), so a short pause when the
    picture appears is expected;
  - This grid at 0.02 m, the same way;
  - ticking and unticking grids while the site prepares;
  - removing a grid mid-preparation;
  - a fine-cell site export.
- **Evidence beyond the walkthrough:**
  - the local test recipe;
  - the site-scope loops under load, before and after the fix;
  - branch CI on both QGIS majors.

## When it merges

- **#166:** closed under the author's rule; otherwise a comment with what the
  report now says, and left open.
- **#193:** closed.
- **#157:** a comment that items 1 and 3 are done. Item 2 stays open, for later
  with #138.
- **#75:** a comment listing the items done and those found already gone. The
  rest stays open for session N.
- **A new issue** for the remaining GUI-thread fills: a cut's section and the
  ParaView export.
- **The README roadmap** is updated.

## Left to the builder

- Every name: the report method, the helper module, the worker prefix, the
  engine's new methods.
- The loop budget for reproducing #166.
- The exact wait budget (about 0.2 s) and the gap threshold in the
  never-blocked test.
- Progress granularity inside one grid's plan.
- How the north-up plan cache exposes its size.
- The two "document or change" calls in Part 2, with the reason recorded.
