# SDD ledger — plan: docs/superpowers/plans/2026-09-19-nsgeo-slices-m11.md

Spec: docs/superpowers/specs/2026-09-18-nsgeo-slices-design.md (present, read)
Worktree: /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m11
Branch: nsgeo-m11, based on main @ ee0fdea
Venvs: ./.venv (editable install of THIS worktree's nsgeo-core) and ./.venv-qgis
  (--system-site-packages + pytest). Verified: nsgeo resolves to this worktree's src.
Real data: packages/nsgeo-core/tests/data/local/ — 10 DZT symlinked from the main checkout
Baseline reproduced here: 502 core+pure passed / 2 skipped; 470 QGIS passed.

Test commands (from the worktree root):
  ./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
  QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
  ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
  ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py

NOTE: `git push` requires the sandbox disabled in this environment (DNS is blocked inside it).

## Pre-flight scan

### Cross-task rows (every pair sharing a file or an interface)

| Pair | Produced | Consumed | Found |
|---|---|---|---|
| T1 -> T2 | display names re-exported from `nsgeo.slices`; `clear_kernel_cache` left in `fill` | engine imports display names from `nsgeo.slices`, `clear_kernel_cache` from `nsgeo.slices.fill` | agree — T1 Step 24 exports the display+frame names only, and T2 imports the fill helper by module |
| T1 -> T4 | `to_north_up`, `window_times_ns`, `window_label`, `fill` | `slice_layer.py`, `slices_dock.py`, T4 tests | agree — `fill`/`disc_kernel` were already exported by M10's `__init__` |
| T1 -> T6/T7 | `plan_windows`, `window_label`, `to_north_up`, `slice_extent` | `slice_export.py` | agree |
| T2 -> T3 | `SliceEngine(session, on_prepared, on_error, on_progress)`, `SourceChoice`, `Resolution`, `transform_names`, `preset_transform_conflict`, `estimate_memory`, `format_bytes` | dock constructs the engine with bound methods | agree |
| T2 -> T4 | `slice_at`, `shared_limit`, `output_unipolar`, `status_text`, `frame`, `z`, `is_prepared`, `mode` | `refresh_slice`, `display_limit`, `status_label` | agree |
| T2 -> T6/T7 | `cube()`, `provenance()`, `frame`, `z` | exporter | **DISAGREE — findings 1 below**: T6/T7 tests read `engine._choice` and `engine._cube`, which T2 never made public |
| T3 -> T4 | the dock's widgets, `rebuild_source`, the `_updating` depth counter, `prepare()` | T4 appends three groups to the same file | **DISAGREE — finding 2 below**: T3 never says `_on_source_changed` honours `_updating`, so refilling the combos would auto-prepare |
| T3 -> T7 | the Source group's layout | T7 inserts `cube_combo` at its top | agree |
| T4 -> T5 | `refresh_slice`, `current_window`, `step_slice`, `slice_changed` | T5 emits `window_changed` from inside `refresh_slice` | agree |
| T4 -> T6 | `status_label`'s position, `display_limit`, `radius_cells`, `view_settings` widgets | T6 adds the two buttons beneath the status line | agree |
| T6 -> T7 | `cube_record(session, choice, frame, z, view, npz_path)`, `ViewSettings` | `recipe_from_record` | agree |
| T3,T4,T5,T6 -> plugin.py | each appends to `initGui`/`unload` | strictly sequential, no parallel dispatch | agree |
| T2 -> .github/workflows/ci.yml | the mypy file list | only T2 touches it | agree |

### Self-consistency rows (each task's own tests against its own code)

| Task | Found |
|---|---|
| T1 | Arithmetic re-derived by hand: `plan_windows` counts (10 abutting, 19 overlapping, 4 in the shared-limit fixture), `window_times_ns` at `(96,100)` -> `(48.0, 49.5)`, `slice_extent` at 30 deg (two-corner miss = 3.46 m > the test's 1.0 m floor) and 45 deg (`hypot(10,10)`), depths at v=0.08 -> `(0.6, 0.78)`. All agree. **One defect — finding 3 below**: Step 14's pytest `-k` expression is unquoted. |
| T2 | Every imported name is used; `format_status` for 4 lines at the default budget yields `"streaming"`, matching the status test's expected prefix. |
| T3 | The `docked` fixture registers preset `p` before construction, so `rebuild_source` sees it. Subject to finding 2. |
| T4 | `ZAxis.from_range(2.0, 30.0, 0.5)` gives nz=57, so slider values 30 and 40 are in range; cell 0.25 over a 6 m grid gives (24,24) and 0.5 gives (12,12), as asserted. |
| T5 | step 2.5 ns at dz 0.5 = 5 levels, satisfying both `moved == round(2.5/dz)` and `moved > 1`. |
| T6 | nz=57 gives 10 bands at (10,5) — bands 7 and 8 exist as asserted — and 54 bands at (4,1), so `ranges[1]`/`ranges[2]` exist. Subject to finding 1. |
| T7 | `recipe_from_record` returns `None` for absent `z`/`view`, which is what the old-record test asserts. |

### Findings and rulings

Finding 1: Tasks 6 and 7's tests read `engine._choice` and `engine._cube`, private attributes
  Task 2 never exposes.
Ruling A: add two read-only properties to `SliceEngine` — `choice -> SourceChoice | None` and
  `has_cube -> bool` — to Task 2's Produces block, and use them in Tasks 6 and 7 instead of the
  private attributes. Why: a test that reaches into a private attribute pins an implementation
  detail rather than a contract, and the review rubric treats that as a defect; both facts the
  exporter genuinely needs (what the source was, whether a cube got built behind the user's back)
  are legitimately public. Cost if wrong: two three-line properties, each with a real caller and
  a real test.

Finding 2: Task 3 specifies a `_updating` depth counter for `rebuild_source` and, separately,
  that `_on_source_changed` calls `prepare()`. It never connects the two. `rebuild_source` refills
  the grid and preset combos, which emits `currentTextChanged`, which would re-prepare — on dock
  construction, and again on every `grids_changed`, `lines_changed` and `presets_changed`. That is
  ~0.9 s of work per unrelated session signal, and it is the "nothing runs automatically" the spec
  does forbid.
Ruling B: `_on_source_changed` returns immediately while `self._updating` is non-zero. Why: spec
  §9.1's auto-preparation is the execution of a choice *the user made*; the dock refilling its own
  combos is not such a choice. The guard already exists for the same reason in
  `processing_dock.py`. Cost if wrong: a genuine user change arriving during a rebuild is dropped,
  and the next change re-prepares — visible and self-correcting.

Finding 3: Task 1 Step 14's command `pytest ... -q -k limit or shared` is unquoted, so the shell
  splits it and pytest never sees the expression.
Ruling C: quote it — `-k "limit or shared"`. Why: as written the command fails or silently runs
  the wrong selection, and Step 14's whole purpose is to watch specific tests fail. Cost if wrong:
  none; it is shell quoting.

All three ruled before Task 1 dispatch; the plan was patched to match.

## Progress

Task 1: dispatched (sonnet, agent a097756abfab4c6fb), BASE 8f7e605
Task 1: implementer DONE_WITH_CONCERNS, commits 6e5a0d3, 43f2b56, bf52eaf, 87af23a.
  529 passed / 1 FAILED / 2 skipped; ruff + mypy clean. Real-data test confirmed RUNNING
  (10 DZT resolved, 35 tests in test_real_files.py), not skipping.
  Open: the brief's own real-data assertion `median(idx@correct) > 1.5 * median(idx@raw)`
    fails at 1.08x (79.0 vs 73.0, needs > 109.5). Measured limits: shared_limit(cube,10)
    = 2.5165, UnipolarClip().limit(cube.mean) = 2.7178 -> ratio 0.926.
  Two of my brief's five mutation predictions were WRONG, both diagnosed correctly by the
    implementer and both reported plainly instead of being papered over:
    - Step 11 mutant 2: `test_abutting_windows_tile_the_axis...` cannot discriminate
      `range(0, nz-t+1, s)` from `range(0, nz, s)` when thickness == step, because both
      floor to the same last multiple (0..90 for nz=100, s=10). The band-count test does
      catch it. My prediction named the wrong test.
    - Step 29: `test_padding_to_a_smooth_size_does_not_change_the_answer` does NOT catch an
      off-by-exactly-one undersized FFT. Verified independently: max abs difference 2.74e-14.
      Mechanism — the wraparound aliasing lands at index 0 mod M, which the crop
      `[r : r+ny]` excludes for every r >= 1. The wrap invariant is enforced ONLY by
      `_smooth_size`'s own `m >= n` test. My "load-bearing" claim for the agreement test
      was overstated for this particular mutant.

Ruling D: the real-data magnitude bar is MY defect, not the code's, and it is removed rather
  than recalibrated. Two things are wrong with it. First, `thickness=10` at dz=0.2165 ns is a
  2.2 ns window -- SHORTER THAN ONE PULSE WIDTH (~2.9 ns at this 350 MHz antenna), which spec
  6.6 and Conyers both say a slice thickness must exceed. The test exercised a thickness no
  user should choose. Second, the size of the effect is a property of the data's depth
  decorrelation, not of the code: adjacent levels in this real amp_envelope cube correlate at
  0.95-0.99, because envelope detection is itself a smoothing operation, so a window mean
  barely differs from its levels. The 1.5x figure came from an M10 measurement on different
  data and I generalised it without checking -- the same mistake M10's own Ruling J records
  me making with an energy identity.
  The fix: (a) raise the thickness to 23 levels (~5.0 ns), which satisfies 6.6's own rule;
  (b) replace the magnitude bar with two claims that are TRUE and DISCRIMINATING on real
  data -- the exact mechanism (`shared_limit` equals the percentile over the actually
  displayed slices) and the direction at the display (`median(correct) > median(raw)`);
  (c) put the measured thickness table and the correlation figure in the test's docstring so
  nobody re-adds a magnitude bar. The strong magnitude claim stays where it belongs, on the
  synthetic fixture whose levels are i.i.d. by construction.
  Cost if wrong: the real-data test pins direction and mechanism rather than magnitude, so a
  regression that halved the effect while keeping its sign would be caught only by the
  synthetic `< 0.8` bar. That is the right place for it -- only the synthetic fixture
  controls decorrelation.
Ruling E: annotate both wrong mutation predictions in the plan rather than leaving them to be
  read as history. Why: the plan is the artefact a later milestone reads, and M10's Ruling V
  established that a plan literally prescribing a defect will have it reintroduced. Cost if
  wrong: two markdown notes; no behaviour touched.
Task 1: fix round 1/5 dispatched (resumed implementer a097756abfab4c6fb, 1 finding)
Controller note (worktree hygiene, not a task finding): my own setup left two artefacts —
  a stray `DATA_LINK` symlink at the worktree root, and `tests/data/local/README.md` replaced
  by a symlink (it is the one TRACKED file in that otherwise-gitignored directory, and my
  blanket `ln -sf` over the directory caught it). Both removed and README.md restored from
  git; the 10 DZT symlinks are intact. Neither would have been a code defect, but the
  type-changed README would have shown up as a spurious hunk in the final whole-branch diff.
Task 1: fix round 1/5 implemented — commit 8dc5ff3. 530 passed / 2 skipped; real-data 34 passed,
  0 skipped; ruff + mypy clean. I re-ran all four verification commands myself rather than take
  the report: 530/2, test_real_files.py 34 passed, ruff clean, format clean, mypy 32 files.
  Implementer's mutation re-check, reported honestly: mutant 1 (shared_limit -> clip.limit(
  cube.mean)) is caught by the DIRECTION assertion rather than the new mechanism one, because
  both limits collapse to the same value under that mutant and the `<` fails first; mutant 2
  (plan_windows step=1) is caught by the mechanism assertion (2.0861 vs 2.0738).
Task 1: task review dispatched (opus, agent a65ce881328ddd427), diff 8f7e605..8dc5ff3
Task 1: review verdict — spec COMPLIANT (one Minor gap), quality NEEDS FIXES. Three Importants,
  two of them the exact "green test blind to the defect" pattern this milestone guards against.
  I reproduced both numerically myself before ruling rather than take the reviewer's word.
  Important 1: to_north_up's `math.ceil((xmax-xmin)/cell)` rounds an exact integer UP, because
    the span is `n + 4e-15` in floating point for most sub-metre cells. Reproduced: a
    cell=0.1/nx=29 frame yields a (13, 30) raster with an all-NaN last row AND column where
    (12, 29) is right; 102 of 1000 widths trip at cell=0.1. Contradicts display.py:186's own
    claim that the output is the frame's rows reversed exactly. The pinning test uses cell=1.0,
    where the arithmetic is exact, so it cannot see it — at spec 6.4's 0.10 m cells it always
    would.
  Important 2: shared_limit's "every level contributes exactly once" is FALSE whenever the
    thickness does not divide nz. Reproduced: nz=181, thickness=23 -> 7 windows covering 161
    levels, so levels 161-180 are excluded from the shared stretch entirely — and the reviewer
    measured those as the BRIGHTEST part of the real cube (level-mean 1.169 vs 0.858). Effect on
    this corpus is small (-0.63%), but a cube with a strong deep reflector would drop it from
    its own stretch. The test named for the claim uses nz=40/thickness=10, divisible, so it
    cannot fail for the reason it exists.
  Important 3 (mine): the plan's Step 17 still carries a mutation prediction the implementer
    disproved, while Steps 11 and 29 were amended. Doc-only.

Ruling F: fix Important 2 by covering the tail with a FINAL PARTIAL WINDOW inside shared_limit,
  not by weakening the docstring and not by changing plan_windows. Why: `plan_windows` emits
  whole windows only and must keep doing so — spec 9.4 makes its output the GeoTIFF's bands, and
  bands of unequal thickness are not comparable. But `shared_limit` is a MEASUREMENT, not an
  export, and a thin end window is not a defect there — it is exactly what the viewer produces:
  `ZAxis.level_range` genuinely returns a thinner window at either end of the axis (that is trap
  3, and spec 6.6 requires the readout to say so). So the displayed set really does include thin
  end windows, and a partial final window is the faithful representation of what a user can see.
  This keeps "exactly once" TRUE rather than restating it as "at least once". Cost if wrong: the
  final window is thinner than the others, so its higher variance biases the limit slightly up —
  measured by the reviewer at under 1.4% across every thickness tried, against excluding 11% of
  the cube including its brightest levels.
Ruling G: fix Important 1 by snapping the ratio before the ceil, not by changing cell_index or
  the frame. Why: the defect is purely the float representation of an exact integer span; the
  geometry is right. An epsilon on the RATIO (not on the world span) is scale-free, which the
  alternative — an absolute tolerance in metres — is not. Cost if wrong: a frame whose true span
  genuinely exceeds a whole number of cells by less than one part in a billion loses its last
  row; that is 1e-10 m at a 0.1 m cell, far below any real survey's precision.
Ruling H: also fix two Minors in the same round, both one-liners: `clear_kernel_cache` missing
  from the `nsgeo.slices` re-export (the brief's Interfaces block states it), and render.py:91's
  M10 docstring saying a raw-level limit is "systematically too low" where display.py:150 says
  "too high" — the numbers both cite make display.py right. Why fold them in: both are one line,
  both are in code this task is already touching or directly about, and a docstring that states
  the opposite of the truth about THIS task's subject is worse than a missing one. Cost if
  wrong: two lines; the render.py edit touches an M10 file, visible in the diff.
Ruling I: do NOT fix the reviewer's Minor 5 (to_north_up drops 15-18% of frame cells at rotated
  azimuths, because the output lattice is rotated relative to the source at the same pitch) in
  this task. Why: it is a design question about the EXPORT's output pixel size, not a defect in
  what Task 1 was asked to build, and Task 6 owns the exporter. It is also largely mitigated in
  practice — the export path is slice -> fill -> to_north_up, and the fill at spec 6.4's default
  radius has already spread any isolated cell across many before the resample, so the
  "one-in-six chance of not appearing" applies to the radius-0 case. CARRIED INTO TASK 6's
  DISPATCH and flagged to the final review. Cost if wrong: an unfilled rotated export loses some
  isolated single-cell anomalies; the fix (a finer output pitch) is a one-line change in Task 6.
Task 1: fix round 2/5 dispatched (resumed implementer a097756abfab4c6fb, 3 Important + 2 Minor)
Task 1: fix round 2/5 implemented — commit fa8db17. 531 passed / 2 skipped (not 532: Important 2
  extends an existing test rather than adding one), ruff + mypy clean. I verified both fixes
  myself before re-review rather than take the report: 0 mis-sized frames across 6000
  (width x cell) combinations where 102/1000 tripped before; and with a synthetic cube carrying
  an 8x bright reflector in the excluded tail, shared_limit now sees 4 windows and the bright
  tail reaches the stretch.
  The implementer departed from MY prescriptions in two places, disclosed both, and was right
  both times:
    - Ruling G's fixed `1e-9` on the ratio was itself too small at UTM origins (measured residual
      1.86e-9 to 3.73e-9). My "an epsilon on the ratio is scale-free" reasoning was incomplete:
      `slice_extent`'s `xmax - xmin` cancels two ~5e6 numbers and injects error proportional to
      coordinate magnitude, so the residual is not scale-free at all. They scaled by the same
      `64 * eps * max(1, |coord|)` margin `cell_index` already uses. Correct, and consistent with
      the frame's own convention.
    - My prescribed test assertion (`nz * n_cells`) was arithmetically unsatisfiable, because
      `slice_levels` is a mean over the window and returns one value per cell per WINDOW. They
      corrected it to a window count and showed it discriminates (1200 seen vs 1600 expected).
Task 1: scoped re-review dispatched (opus, agent ada0b4779b41fd0f8), diff 8dc5ff3..fa8db17
Task 1: fix round 2/5 (5 addressed, 0 open; commits 8dc5ff3..fa8db17). Re-reviewer bisected the
  epsilon in BOTH directions, which is what I most wanted checked: the bound swallows a genuine
  excess span of at most `64 * eps * max(1, |coord|)` METRES — the /cell and later *cell cancel —
  i.e. 71 nanometres at UTM scale, 1.4e-6 of a 0.05 m cell. 400 random UTM frames gave 0 phantom
  rows; 300 rotated frames gave 0 under-coverage. It also confirmed the real cube's excluded tail
  really was the bright end (level-mean 1.1689 vs 0.8583) and that every docstring number now
  matches the code (2.7244 / 2.1710 / 2.0608 / 2.0513, and 1.2646 pre-fix).

Ruling J: three of the four remaining Minors are DOCUMENTATION defects introduced by my own
  prescribed wording, and one is a small test strengthening. Handle them as a single
  documentation-plus-assertion fix WITHOUT another review cycle, following M10's Ruling V
  precedent ("seven documentation-only annotations, no code, dispatched as a quick fix rather
  than a review cycle") and the project's standing preference that cosmetic and documentation
  tweaks are made directly rather than run through the loop. I verify the one behavioural item
  (the test's discrimination) myself against the two wrong tails the reviewer named.
  Why these three cannot simply be deferred: each is a statement that is FALSE, in a place a
  later task's implementer will read.
    (a) display.py:159-161 retains my sentence "every level contributes exactly once and no depth
        is weighted more heavily than another -- including the tail". The second half is false:
        every WINDOW contributes n_cells values regardless of how many levels it averages, so a
        thin tail's levels carry thickness/tail_levels times the per-level weight. The reviewer
        measured the consequence — shared_limit is no longer monotone in thickness, with a 2.15x
        step between t=180 (2.1455) and t=181 (0.9972). Under 1% across the realistic 14-30 level
        range and conservative in direction (a higher limit clips less), so not a display bug —
        but Task 4 consumes this function and will read that sentence.
    (b) plan:811-814's new amendment note is contradicted by its own commit: it says the test
        "never calls shared_limit", which stopped being true when Ruling F's fix added exactly
        that call. The plan's ORIGINAL Step 17 prediction is now correct.
    (c) test_real_files.py:239-241's cross-check now re-implements the tail rule inline, so it is
        self-consistent by construction and no longer pins tail PLACEMENT — the reviewer measured
        an overlapping (158, 181) tail as indistinguishable from the correct one on both sides.
  Cost if wrong: three prose edits and one assertion; nothing behavioural changes.
Task 1: fix round 3/5 (documentation + one assertion) dispatched (haiku, quick fix)
Task 1: fix round 3/5 implemented — commit 17536ce (documentation + one assertion). 531 passed /
  2 skipped, ruff + mypy clean. No re-review dispatched, per Ruling J; I verified the one
  behavioural item MYSELF instead: injected both wrong tails the re-reviewer named into
  shared_limit and confirmed the strengthened assertion kills each —
  `SliceWindow(k1-3, nz)` (overlapping) FAILS, `SliceWindow(0, thickness)` (duplicate) FAILS,
  and 19/19 pass on revert with a clean working tree. Tail placement is now pinned, not just
  tail count.
Task 1: complete (commits 8f7e605..17536ce, review clean, 4 Minors resolved rather than deferred)

Task 2: dispatched (sonnet, agent abe6cb728834bdfd4), BASE 17536ce
Task 2: implementer DONE, commits 01b7178, 0a7a12f. Verified by me, not taken on report:
  541 core+pure passed / 2 skipped; 491 QGIS passed; ruff clean; format clean; mypy Success over
  33 files in the EXTENDED form; ci.yml's literal mypy list updated.
  Two disclosed changes, both corrections to MY brief and both right:
    - Streaming `shared_limit` missed the tail window that Ruling F added to core's resident
      path, so the two residency modes disagreed by 0.08%. This gap is MINE: Ruling F amended
      `nsgeo.slices.shared_limit` and I never carried it into the engine's streaming branch,
      which calls `plan_windows` directly. Spec 11's property — the mode a user is in must not
      change what they see — would have been violated. Now matched.
    - `dispose()`'s bare try/except replaced with `contextlib.suppress`, matching map_link.py's
      existing convention and satisfying ruff.
  Also corrected my arithmetic: I predicted 481 QGIS, actual 491. `packages/nsgeo-qgis/tests`
  contains BOTH tests/pure and tests/qgis, so the 10 new pure tests are collected in that run
  too. 470 + 11 qgis + 10 pure = 491. Not a regression.
Task 2: task review dispatched (opus), diff 17536ce..0a7a12f
Task 2: review verdict — spec COMPLIANT, quality NEEDS FIXES. Four Importants. The reviewer
  independently confirmed BOTH disclosed departures are sound and sound for the right reason:
  the streaming tail fix makes the two modes agree structurally (identical window lists,
  identical concatenation order, so UnipolarClip's deterministic stride selects the same
  positions and only float32 rounding separates them), not by fixture coincidence; and
  contextlib.suppress is verbatim map_link.py's idiom for the same disconnect-after-C++-deletion
  case.
  Important 1: provenance() re-reads the preset LIVE from site.presets, so it can claim steps
    that were never applied — save_preset overwrites a name in place and delete_preset removes
    it, both ordinary actions while a source is prepared. Prepare with "p", edit "p", export:
    the .npz records the new steps for a cube built from the old ones. Exactly the defect the
    method's own docstring rejects for line_keys, one field over.
  Important 2: test_provenance_names_the_lines_that_were_actually_prepared cannot detect the
    property it is named for, and the implementer's own report says so — they WROTE the
    discriminating extension (a fifth line whose file is deleted), confirmed it fails against
    the mutant, and then discarded it. Reporting it was right; discarding it was not.
  Important 3: nothing invalidates on `grids_changed`. I REPRODUCED THIS MYSELF: move grid A
    100 m east via replace_grid, and the engine keeps frame.origin=(500,700) while the site's
    grid is (600,700), returns a byte-identical slice, reports no error and raises nothing —
    coverage still 12 cells. M10's guard is structurally blind to it because plan.frame and the
    frame the engine passes in are the SAME stale object. Meanwhile layers.py moves the map
    layer to the new position, so the raster and the line geometry would disagree by 100 m on
    screen, silently. This is M10's "M11's first bug" reached by a different input.
  Important 4: three of four terminal paths in `finished` skip _finish_preparation() — the
    exception branch, the outer except, and the addTask-returned-0 branch — so
    wait_for_preparation blocks for its full 20 s and then returns False. loader.py guarantees
    its terminal edge in a `finally` AND in the addTask branch, and its docstring gives the
    reason. The engine took the `except` half of that lesson and dropped the `finally` half.

Ruling K: Important 1 — capture the preset's applied steps at DISPATCH time, beside `_lines`,
  and have provenance() read the captured copy. Why: the steps that were applied are a fact
  about the preparation, not about the site's current state, exactly as `line_keys` already is;
  and they are already computed on the main thread at the dispatch site, so this is a capture,
  not a new computation. Cost if wrong: one more field on the engine; a stale captured copy is
  impossible because `set_source` is the only writer.
Ruling L: Important 2 — re-add the discarded test verbatim. The implementer already wrote and
  verified it, so there is no new work and no new risk. Why: a test whose NAME asserts a rule no
  committed assertion pins is worse than no test, because it reads as coverage; and the rule it
  fails to pin is precisely the one Important 1 breaks. Cost if wrong: none.
Ruling M: Important 3 — the engine connects `session.grids_changed` itself and re-prepares, but
  only when the CHOSEN grid's BINNING-RELEVANT fields changed. Why each half: the engine already
  owns its own invalidation (it connects `site_closed`), so this belongs here and not in the
  dock, where Task 3 could miss it; and re-preparation rather than mere geometry invalidation is
  required because `replace_grid` changes the fields every prepared line's `coords` were
  computed from, not only the frame. The fingerprint is `(origin, azimuth, size_x, size_y, crs)`
  and deliberately EXCLUDES `velocity` and `default_spacing`: a velocity change relabels depths
  without rebinning (that is the whole reason ZAxis is two-way time, spec 5.2) and
  `default_spacing` only seeds the dock's fill radius, so re-running 0.9 s of preparation for
  either would be waste. `Grid` is `@dataclass(frozen=True)`, so field comparison is exact.
  Cost if wrong: a grid edit that changes only velocity or spacing does not re-prepare — correct
  by construction; and `grids_changed` from an unrelated `add_grid` is a no-op rather than 0.9 s.
Ruling N: Important 4 — every terminal path notifies, following loader.py's `finally`. Why: the
  callback is the only terminal edge a caller can watch, and `on_error` is named for errors, so
  resting completion on it is an undocumented obligation. Cost if wrong: a caller sees
  "prepared" with zero lines after a failure, which is the truth and which `is_prepared` already
  reports as False.
Task 2: fix round 1/5 dispatched (resumed implementer abe6cb728834bdfd4, 4 Important)
Task 2: fix round 1/5 implemented — commit 2a037c3. 541 core+pure / 2 skipped; 498 QGIS (470
  baseline + 10 pure + 18 engine); ruff/format/mypy clean. Verified by me, plus my own repro of
  finding 3 re-run: the engine's frame now follows the grid to (600,700), re-preparation
  completes, no error, and the slice content is identical — which is CORRECT for a rigid move.
  The implementer corrected two of MY prescribed tests and declined one, all three right:
    - My "values must differ" assertion after a grid move was physically wrong. GridPlacement
      ties each line's world coords to the grid, so a rigid translation moves grid AND lines
      together and the local coordinates — hence the cell ids — are bit-identical. The defect
      was never content, it was GEOREFERENCING: the raster would sit 100 m from the lines.
      My prescription tested the wrong quantity.
    - remove_grid raises if the grid still has lines (session.py:452-457), so the removal test
      had to remove them first. My draft would have raised before the scenario began.
    - No test for the literal `exception is not None` branch, declined as fragile to force. The
      re-reviewer confirmed the claim from the code and from QGIS's own source: past `notify =
      True` that branch's only distinct statements are a report and a return, leaving through
      the identical `finally`.
Task 2: scoped re-review dispatched (opus, agent a464ca71b528a0747), diff 0a7a12f..2a037c3
Task 2: fix round 1/5 (4 addressed, 1 NEW Important introduced by the fix; commits
  0a7a12f..2a037c3).
  NEW Important A (mine — I prescribed the `finally`): `_finish_preparation()` now runs from
    `finished()`'s `finally`, OUTSIDE its own `except` guard, and `_finish_preparation` is itself
    unguarded. A raising `on_prepared` — which in Task 3 is the dock's widget-rebuilding handler
    — therefore escapes `finished()` and is swallowed by QgsTaskWrapper with no log, no re-raise
    and no traceback. I verified that in QGIS's own source
    (/usr/lib/python3/dist-packages/qgis/core/additions/qgstaskwrapper.py:53-54). Before my fix
    the call sat inside the `try` and a raising callback reached on_error. So the fix re-opened
    the exact hazard the module docstring warns about, and the docstring and the code now
    disagree — the edit even re-asserts "guards its own body with `except`, not merely `finally`"
    while breaking it.

Ruling O: fix New Important A with ONE guarded helper, following `_emit_progress`'s existing
  shape in the same file rather than inventing a pattern. Why a helper and not putting the call
  back inside the `try`: Ruling N's requirement is that EVERY terminal path notifies, which is
  what the `finally` buys, and the guard belongs with the callback invocation so the
  addTask-returned-0 path and the new `grids_changed` slot's `_report` calls are covered by the
  same change. Cost if wrong: a callback that raises is reported rather than propagated, which
  is what every other callback in this file already does.
Ruling P: promote the re-reviewer's Minor 2 to this fix round. Why: `_grid_fp` is set in
  `_rebuild_geometry`, so it is None until a resolution exists — and the window that opens is
  exactly the ordering TASK 3 USES. My Task 3 text has the dock call `prepare()` and
  `_apply_resolution()` separately, and its own `_ready()` helper does `prepare()` then sets the
  spin boxes then flushes. So "prepared, grid changes, then a resolution arrives" is the normal
  path, not an edge case, and it builds a frame from the new grid against coords from the old
  one. The re-reviewer measured the consequence at 1 m: cell ids [48 168 288 408 528] where
  [52 172 292 412 532] is correct — SILENT mis-binning, M10's recorded failure mode. The
  fingerprint's real subject is the prepared coords, so it is captured where those are, in
  `set_source`. Cost if wrong: the fingerprint is captured one call earlier; nothing else moves.
Ruling Q: also fold in the re-reviewer's Minor 5 (a velocity-only edit leaves a resident cube's
  embedded provenance stale, because Ruling M deliberately does not re-prepare for velocity
  while `provenance()` reads `resolved_velocity` live). Drop only `self._cube`, never the
  prepared lines. Why: Tasks 6 and 7 record provenance into the .npz and the survey JSON for
  REPRODUCIBILITY, so a cube whose embedded velocity depends on whether a cube happened to be
  resident is a defect in exactly the thing those tasks exist to guarantee. Cost if wrong: one
  velocity edit costs a cube rebuild (53-248 ms), not a re-preparation.
Task 2: minor (deferred): the re-preparation path re-reads the preset live, so a grid nudge
  silently re-applies a preset edited since preparation — and if it was deleted, prepares with
  zero steps while provenance().preset_name still names it. Whether editing the SELECTED
  preset's contents should re-prepare is a Task 3 design question (spec 9.1 covers changing
  WHICH preset, not editing one in place). CARRIED INTO TASK 3's DISPATCH.
Task 2: minor (deferred): failure terminal paths notify while frame/z still describe the
  previous source, so estimate/status_text report cube bytes for a source that is not prepared.
  No wrong data reaches a slice — `_slice` raises first.
Task 2: minor (deferred): the grid-move test could additionally assert content invariance
  (assert_array_equal before/after plus coverage non-empty), which would also catch a
  sub-extent move where stale coords mis-bin silently rather than raising.
Task 2: fix round 2/5 dispatched (resumed implementer abe6cb728834bdfd4, 1 Important + 2 promoted)
Task 2: fix round 2/5 implemented — commit 19dd038. 541 core+pure / 2 skipped; 501 QGIS
  (470 + 10 pure + 21 engine); ruff/format/mypy clean; mutant 1 re-confirmed failing.
  One unprescribed change, disclosed: a try/finally around wait_for_preparation's inner
  loop.quit(), needed once _finish_preparation's own guard can catch a raise mid-callback —
  without it the waiter would block for its whole timeout instead of waking.
Task 2: scoped re-review dispatched (sonnet — a small, narrowly scoped fix diff, and I had
  already verified both tiers and the headline behaviour myself), diff 2a037c3..19dd038
Task 2: fix round 2/5 (3 addressed, 0 open; commits 2a037c3..19dd038). Re-reviewer traced the
  whole guarded-callback call graph and confirmed every terminal path still notifies exactly
  once, the two deliberately-silent staleness returns are unaffected, and nothing can now reach
  QgsTaskWrapper's swallow. It also checked the guard is not OVERBROAD (scoped to Exception, not
  BaseException, consistent with the file) and confirmed wait_for_preparation's contract still
  holds: `_running` is forced False before the callback runs, so a raising callback cannot
  desynchronise `finished` from `_running`. It independently verified the fingerprint's new
  capture site keys identically to `_on_grids_changed`'s later lookup (`site.frames` vs
  `session.grid`), which is what makes the comparison sound rather than coincidental.
Task 2: complete (commits 17536ce..19dd038, review clean)

Task 3: dispatched (sonnet, agent a530163134890795e), BASE 19dd038
Task 3: implementer DONE, commit ad5178c. 541 core+pure / 2 skipped; 517 QGIS (501 + 16);
  ruff/format/mypy clean. Verified by me. Two unbriefed changes disclosed (engine.dispose() in
  unload(); a stale SHADOWED["error"] pin), plus an honest "mutant 3 not caught by any test".
  Its decision on the carried preset question: editing the SELECTED preset's contents does not
  re-prepare, argued from (a) presets_changed carrying no discriminator, so every emission would
  cost 0.9 s for another dock's activity, and (b) Ruling K having deliberately frozen the steps
  at dispatch.
Task 3: review verdict — spec ❌, quality NEEDS FIXES. Three Importants, all probe-measured by
  the reviewer, and the spec gap turns my "judgement call" into a settled requirement.
  Spec ❌: §9.2's Source row specifies "a prepared/STALE status" and no stale state exists. The
    reviewer also widened the silent-staleness surface beyond the in-place edit I asked about:
    accepting the line chooser leaves `2 of 3` beside `prepared · 3 lines`, and a DELETED
    selected preset makes the combo jump silently while `_updating` suppresses the handler, so
    the dock then NAMES a preset the engine never prepared.
  Important 1: the inclusion set never picks up lines that arrive after the grid. `_sync_included`
    re-seeds only on a grid-id transition. In the plugin's REAL order — the dock is built at
    initGui before any site exists — `grids_changed` fires while the grid is still empty, seeds
    (), latches the grid id, and every later `lines_changed` takes the intersect branch. Measured:
    `0 of 3 included` and `line_keys == ()`. The existing test passes only because its fixture
    builds the dock LAST.
  Important 2: with one grid, one preset and transform `none`, NOTHING in the dock can ever
    prepare. The only triggers are the three `currentTextChanged` connections, every refill is
    suppressed by `_updating`, and a single-item combo cannot change again. So the brief's own
    done-criterion is unmet, and my Step 7 retry claim ("a fixed preset fires presets_changed,
    which rebuild_source is already connected to") is dead, because rebuild_source never
    prepares. This is my Ruling B (the guard) combined with my own removal of the Prepare button,
    with no first-preparation trigger left anywhere.
  Important 3: `Select all`/`Select none` are unguarded Qt slots. Measured with a recording
    excepthook: remove a line elsewhere then Select all -> KeyError escapes the slot; close the
    site then Select none -> ProjectError escapes. That is qFatal() and a dead CI job. The
    checkbox path next door IS guarded, which is what makes this an oversight rather than policy.

Ruling R: keep the implementer's no-auto-re-prepare decision AND add the stale indicator. The two
  are not in tension — the decision is about whether to spend 0.9 s, the indicator is about
  whether the screen tells the truth — and §9.2 already budgeted the string. Report three states
  in `source_status`: not prepared, `prepared · N lines`, and stale naming what diverged. Compare
  `source_choice()` against `engine.choice`, and the live preset steps against
  `engine.provenance().steps`; both accessors are public because Task 2's Rulings K and A made
  them so. Cost if wrong: a status line that says "stale" in a case a user would not have cared
  about; far cheaper than a slice that silently is not what the dock claims.
Ruling S: fix Important 2 by preparing at the END of `rebuild_source` when a complete choice
  exists and nothing is prepared or running, and additionally when the line chooser is accepted.
  Why this does not reopen the churn Ruling B closed: this is a FIRST computation, not a
  recomputation — gated on `not is_prepared and not is_running`, so it fires once per source
  rather than once per signal. And accepting the chooser is a choice made in this dock, exactly
  like a combo change, which is the same test §9.1 applies. Cost if wrong: one 0.9 s preparation
  on a site where the user would rather have chosen lines first; they can, because the chooser
  re-prepares on accept.
Ruling T: promote five Minors into this round, because all five are defects my brief introduced
  and four are cheap: M2 (transform_combo filled AFTER the connections, inverting my own step
  order, so the guard is bypassed once at construction), M3 (`prepare()` catches only ValueError,
  so a preset naming a removed step raises KeyError into a log-only guard and reaches neither
  the status line nor `error` — the one place a refusal is meant to become visible), M4
  (`open_line_choice_dialog` omits `destroyed.connect`, which BOTH established modeless dialogs
  have and whose reason is recorded in plugin.py; a dead wrapper makes the next `Choose...` die
  and `unload()`'s own reject() raise mid-teardown), M5+M6 (two tests that cannot fail — an
  assert on a bound method, and a `"MB" in text` check that passes even with an empty inclusion
  set, which is exactly the I1 state). Cost if wrong: a slightly larger fix round on a task whose
  review was going to be re-run anyway.
Ruling U: M7 (the dialog lists every line in the SITE, not the grid, so `6 of 3 included` is
  reachable and a line placed on another grid can be ticked into this grid's cube) — fix by
  scoping the dialog to the selected grid, not merely by adjusting the denominator. Why the
  stronger fix: the denominator is a symptom; the defect is that a cube binned on grid A's frame
  can be handed lines placed on grid B, whose traces then fall outside the frame and are silently
  dropped by `cell_index`. Spec 9.1 says "every line in the grid". The brief's constructor
  signature omitting `grid_id` is my omission. Cost if wrong: a user who wanted to pull a stray
  line from another grid into a cube cannot; the spec says they should not.
Task 3: minor (deferred): choose_button never disabled with the site, so it does nothing with no
  feedback when none is open (processing_dock.py:243-244 is the established pattern).
Task 3: minor (deferred): a redundant function-local import of NsgeoPlugin in test_plugin_loads.py.
Task 3: noted, not a finding: mutant 3 (depth counter vs plain bool) is genuinely unpinnable here
  — the reviewer confirmed from the code that NO re-entrancy path exists in this dock, so the two
  behave identically. It also observed that processing_dock.py's own analogy is weaker than its
  comment claims, since that dock emits step_selected OUTSIDE its counter block. Revisit in Task
  4, where a Resolution control writing back to the session would create the first real nesting.
Task 3: minor (deferred): slices_dock.py is 327 lines for one of four groups, on a trajectory
  toward profile_dock.py's 848. Watch in Task 4.
Task 3: fix round 1/5 dispatched (resumed implementer a530163134890795e, spec gap + 3 Important
  + 6 promoted)
Task 3: fix round 1/5 implemented — commit 9306afe. 541 core+pure / 2 skipped; 526 QGIS. I ran
  the full QGIS suite myself: 526 passed, exit 0 (the third consecutive clean run counting the
  implementer's two).
  THE IMPLEMENTER FOUND A REAL, REPRODUCIBLE SEGFAULT that my Ruling S introduced, and found it
  only by actually running the tests the review had cleared "by inspection". Two crash sites,
  both the same root cause:
    (a) The first-computation trigger starts a real QgsTask at dock CONSTRUCTION whenever a grid,
        preset and lines already exist. `SliceEngine._generation` discards a superseded task's
        RESULT but never cancels or waits for the TASK, so any test that called prepare() without
        first waiting was dispatching a second real background task reading the same lines while
        the first still ran — two worker threads inside dewow.apply/read_header at once. Task 2's
        "three rapid combo changes are safe without debouncing" describes result-discarding, not
        execution isolation; nothing had exercised it under genuine multi-threading because no
        path before Ruling S ever called set_source twice without an intervening wait.
    (b) Worse and broader: ANY unrelated test that builds a full NsgeoPlugin over a site with a
        grid, lines and a preset now starts an orphaned SliceEngine task
        (test_plugin_difference_presets.py's fixture is a real example). dispose() disconnected
        signals but never waited for work already handed to QgsApplication.taskManager() — a
        SESSION-SCOPED SINGLETON shared by every test in the process — so an orphaned task could
        still be mid-flight when a later, wholly unrelated test pumped the event loop.
    Bisected properly: reproduced twice byte-identically, confirmed absent at ad5178c by stashing
    and re-running the identical suite, and confirmed the crash persisted with --ignore on all
    three of this round's own test files, proving it was the SOURCE change and not test-specific.
  Fixed in two parts: prepare() no-ops when the computed choice already equals engine.choice, and
  dispose() now waits out in-flight work before disconnecting.
Ruling V: fix the residual general case NOW rather than deferring it, in slices_engine.py. The
  implementer correctly declined to expand scope and flagged it: two GENUINELY DIFFERENT choices
  dispatched within ~0.9 s of each other still overlap as real tasks, because only the
  identical-choice case is closed. Why this cannot wait: it is a SEGFAULT, which in QGIS costs
  the user their unsaved session, and it is reachable by a person clicking through combos quickly
  — not only by a test. Tasks 4-7 all drive this dock harder, so the window gets more reachable,
  not less. The pattern already exists in this codebase: `LineLoader.request` refuses to
  double-dispatch the same key at all. The engine's equivalent is to cancel any in-flight
  preparation and wait for it to actually clear before dispatching the next; `work()` already
  checks `task.isCanceled()` once per line, so the wait is bounded by one line's processing
  (~40 ms), not by the whole 0.9 s. Cost if wrong: a combo change made during a preparation
  blocks the UI for about one line's work instead of returning instantly.
Task 3: fix round 2/5 dispatched (resumed implementer a530163134890795e, 1 item — Ruling V)
Task 3: fix round 2/5 implemented — commit 3f81775. 541 core+pure / 2 skipped; 527 QGIS. I ran
  the QGIS suite TWICE myself: 527 passed both times, exit 0 both times. The discriminating test
  was confirmed to fail without the fix at `max_concurrent == 2` and pass with it — the counter
  form I asked for, not a timing assertion. One side effect found and fixed along the way:
  QgsTaskWrapper synthesises Exception("Task canceled") on every deliberate cancel (its source
  does this at qgstaskwrapper.py:46-47), which would have reported a spurious error on every
  combo change; now suppressed only for tasks this engine itself cancelled.
Task 3: scoped re-review dispatched (opus) over BOTH fix rounds as one wave, diff ad5178c..3f81775.
  Reviewing them together rather than separately: round 1's diff had not been reviewed when
  Ruling V sent round 2, so one pass over ad5178c..3f81775 is the same coverage in one seat.
Task 3: fix round 1+2 re-review (opus, agent a31e5310d0ec48002), diff ad5178c..3f81775 —
  all seven findings ADDRESSED, but ONE CRITICAL and one Important introduced by the fix.
  CRITICAL (MINE — Ruling V's prescription): `_cancel_in_flight`'s confirm step calls
    `wait_for_preparation`, which spins `QEventLoop.exec()` with default AllEvents. So a second
    combo change delivered DURING the <=250 ms cancel wait re-enters `set_source` inside the
    outer call, starts its own task, and then the outer frame bumps the generation and starts a
    second one — restoring exactly the concurrency Ruling V was meant to remove. The reviewer
    reproduced it twice, once through the dock's own combos and once at engine level:
    `max_concurrent: 2`, the OLDER choice won (combo said amp_envelope, engine prepared amp_abs),
    and a spurious "did not stop in time" error was reported even though the cancel had
    succeeded. Reachable by a mouse wheel or held arrow key over a QComboBox, which emits
    currentTextChanged every 10-20 ms against a ~40 ms window.
    This is the same hazard class this codebase already documents at length for QDialog.exec() —
    a nested event loop runs arbitrary code inside your own call frame. I prescribed
    "cancel and wait" without accounting for it.
  Important: prepare()'s no-op guard compares only grid/preset-name/transform/line_keys, never
    the steps, so after an in-place preset edit the documented retry path silently does nothing
    and a one-grid/one-preset source is PERMANENTLY stale. The guard's own stated justification
    is obsolete (round 2 made a same-choice double dispatch safe) but it is still needed as an
    efficiency guard, because a zero-line grid leaves is_prepared False and rebuild_source's
    trigger would otherwise re-fire on every session signal.

Ruling W: fix the Critical with BOTH a re-entrancy guard and ExcludeUserInputEvents, not either
  alone. Why both: the guard is the correctness fix — it makes re-entry impossible rather than
  unlikely — while excluding user input also removes the same nested-loop hazard from dispose(),
  where the reviewer noted user input can currently run mid-unload() between engine.dispose()
  and the dock teardown. ExcludeUserInputEvents alone is insufficient because a timer or a queued
  signal can still re-enter; a guard alone leaves dispose()'s window open. And the guard must
  QUEUE rather than refuse: the user's latest choice is the one they meant, and the reviewer
  measured the older choice winning, so "latest wins" is the property to restore. Cost if wrong:
  a choice made during a cancel wait is applied a few tens of milliseconds late instead of
  immediately.
Ruling X: fix the Important by adding a live-steps comparison to prepare()'s guard, keeping the
  guard. Why not delete it: it is still load-bearing as an efficiency guard for the zero-line
  case the reviewer names. Cost if wrong: one extra comparison per prepare().
Ruling Y: promote the reviewer's three falsified comments and its two mis-reporting Minors, on
  the same reasoning as Ruling J — a comment that states the opposite of the code is worse than
  none, and Tasks 4-7 read these files. Specifically: slices_dock.py:75-79 still says the dialog
  "offers every line in the site" (Ruling U made that false and the dialog's own docstring now
  contradicts it); :276 still reasons about a line from another grid; :365-373 still says the
  engine "never actually cancels or waits"; the stale line reports every non-line_keys divergence
  as "the preset changed" where Ruling R asked it to name what diverged; and _on_engine_error no
  longer writes into source_status, so a failed addTask leaves the line reading "prepared · 0
  lines" — a claim nothing prepared.
Ruling Z: also close Ruling U's residual, which the prescribed fix did not reach: the dialog is
  modeless and binds grid_id at open time, so changing the grid combo while it is open and then
  accepting commits the OLD grid's keys, bringing back both `6 of 3 included` and the silent
  trace drop. One comparison in the plugin's finished handler closes it. Why now rather than
  deferred: it reinstates the exact defect Ruling U was raised to fix, so leaving it would make
  that ruling cosmetic.
Task 3: minor (deferred): clear() zeroes _running while a task genuinely executes (site_closed,
  removed grid), so a later cancel skips its confirm — bounded to one line by the unconditional
  cancel(), but the module docstring's "must never run at once" claims more than the code does.
Task 3: minor (deferred): clear() never cancels its own in-flight task, so site_closed leaves a
  real task running unsupervised for up to a full preparation. Pre-existing; more likely now.
Task 3: minor (deferred): Ruling K's snapshot is SHALLOW — `tuple(dict(s) for s in steps)` shares
  each step's nested `params` dict with the live preset, so an in-place params mutation is
  invisible to both the staleness comparison and exported provenance. FLAG TO THE FINAL REVIEW.
Task 3: minor (deferred): _refresh_source_status calls provenance() on every refresh (five
  session signals plus set_included), resolving a velocity and formatting a timestamp each time,
  and catches only RuntimeError.
Task 3: fix round 3/5 dispatched (resumed implementer a530163134890795e, 1 Critical + 1 Important
  + 3 promoted)
Task 3: fix round 3/5 implemented — commit 8efdc72. 541 core+pure / 2 skipped; 533 QGIS. I ran
  the QGIS suite twice myself: 533 passed both times, exit 0 both times.
  One disclosed wobble handled well: Ruling W's own new test was initially flaky for an unrelated
  reason — a cold task-manager thread pool on the first-ever dispatch in a process — fixed with a
  warm-up dispatch and reported plainly rather than retried until green.
Task 3: scoped re-review dispatched (sonnet — round 3's diff is narrow, I have verified both
  tiers twice, and the whole-branch review on the most capable model will see all of it again),
  diff 3f81775..8efdc72
Task 3: fix round 3/5 (5 addressed, 0 open; commits 3f81775..8efdc72). Re-reviewer traced every
  path reaching set_source and confirmed the guard is set BEFORE _cancel_in_flight is invoked, so
  a queued signal or timer arriving during the wait is queued rather than dispatched; that the
  early return mutates nothing (no generation bump, no _choice/_pending change), so bookkeeping
  is never half-updated; and — the thing I most wanted checked — that ExcludeUserInputEvents does
  NOT block the cancelled task's own posted `finished` callback, verified both by Qt semantics
  and empirically, since round 2's concurrency test still passes under the new flag. Without
  that, every combo change would have reported a spurious timeout. It also confirmed the
  disclosed flakiness fix is a genuine cold-thread-pool warm-up rather than race-hiding, by
  independently re-disabling the guard and observing a deterministic max_concurrent=2.
Task 3: minor (deferred): dispose() does not set _dispatching, so a queued signal or QTimer (not
  user input, which is now excluded) firing during dispose()'s own cancel wait could drive a
  fresh set_source that dispatches a task moments before the callbacks are nulled. Narrower than
  Ruling W's case and pre-existing since round 2; not worsened by round 3.
Task 3: minor (deferred): _CANCEL_TIMEOUT_MS = 250's "proceed anyway" branch is a theoretical
  residual overlap window on an extremely slow system. Disclosed and accepted deliberately.
Task 3: complete (commits 19dd038..8efdc72, review clean after 3 fix rounds)

Task 4: dispatched (sonnet, agent a117a8266c42d25fe), BASE 8efdc72
Task 4: implementer DONE, commit 86ad30f. 541 core+pure / 2 skipped; 551 QGIS; ruff/format/mypy
  clean. Verified by me. Three disclosed findings, all good:
    - Two bugs in MY brief's draft tests: test_nodata_renders_transparent's row/alpha assertions
      were reversed relative to Task 1's own already-tested to_north_up row flip (I wrote the
      test against the un-flipped mental model), and the palette-unipolar test never selected a
      transform before asserting unipolar output.
    - A bug of their own, found ONLY by timing refresh_slice() per Step 10 rather than by any
      given test: the seeded z0_spin defaulted to 0.0 while this fixture's DZT header starts at
      -11.086 ns, so every default-resolution slice raised CoverageError. Every supplied test
      overrode z0/z1, so none of them could see it. This is the best argument yet for Step 10's
      "measure it" instruction — the defect was in the DEFAULT state, which no test exercised.
    - Mutant 2 (radius_cells) was a false negative against my exact test for this fixture, because
      a 0.75 m radius truncates to 0 cells on BOTH sides of the mutation under int(); strengthened
      with an absolute assertion. Mutant 1's most natural form also false-passed the specifically
      named test through an axis-edge coincidence, though a different test in the same file caught
      it; a more faithful reconstruction does kill the named test.
CONTROLLER FINDING (mine, before review): the QGIS tier now emits 9 warnings where it emitted 0.
  Test output must be pristine. Both are in code MY brief prescribed:
    - `QgsMapLayer.setAbstract()` is DEPRECATED (slice_layer.py:130). I prescribed it.
    - GDAL FutureWarning: neither gdal.UseExceptions() nor gdal.DontUseExceptions() has been
      called, so in GDAL 4.0 exceptions become the default and this module's error handling would
      change silently under an upgrade. My brief never mentioned it.
  Carried into the review dispatch to be assessed rather than assumed pre-existing.
Task 4: task review dispatched (opus), diff 8efdc72..86ad30f
Task 4: review verdict — spec ❌, quality NEEDS FIXES. Six Importants, no Criticals. The reviewer
  verified all three of the implementer's disclosures are genuinely what they claim (it checked
  the "the brief's test was wrong" claims specifically, on the grounds that "the test was wrong"
  is also what a wrong implementation looks like from the inside — both held up).
  Important 1 (spec ❌, MINE): the readout omits the depth range in metres. Spec §9.2 fixes the
    text as `slice 14 / 40 · 12.0-16.0 ns · 0.60-0.80 m` and says "always ... in both ns and m";
    the code calls window_label(z, window) with no velocity, so metres never appear. A
    VelocityModel is already in hand three lines later.
  Important 2: the coverage view is rendered against an AMPLITUDE limit. Under the default
    "shared across the cube" stretch, display_limit ignores coverage_check and returns
    shared_limit — measured at 7.0e4 on the fixture — while _values holds trace counts of 1..few.
    Every count maps to the bottom stop, so the coverage map is one flat colour with a legend
    reading `0 - 7.04e+04` over a picture of counts. Only nodata transparency still reads. My
    brief's display_limit prose said nothing about coverage.
  Important 3: the preview silently stops appearing after an ordinary site switch, and never
    recovers from a manual layer removal. Probe-verified against this QGIS build:
    SiteLayers.detach() runs on EVERY site_closed — i.e. every "Open site..." — and removes the
    group node and with it the raster's only layer-tree node; update() only ever tests
    `self.layer is None`, so it neither rejoins the new group nor regains a node. Every later
    slider drag writes pixels nobody can see, with no error. And after project.removeMapLayer,
    sip.isdeleted(layer) is True and update() keeps the dead wrapper forever.
  Important 4 (MINE): a stale slice stays on the map and `layer.clear()` is UNREACHABLE.
    refresh_slice's early return sets _values = None without emitting slice_changed, and that is
    the only condition reaching clear(). set_source empties _lines immediately, so from the moment
    a combo changes the map keeps showing the previous source's slice — indefinitely if
    preparation fails, with the status line reading "not prepared · every line failed" beside a
    map showing amplitudes from a different preset. My brief wrote a clear() branch its own dock
    code can never reach.
  Important 5: 9 new warnings in a tier that had 0. Both real. setAbstract() is deprecated and
    the implementer's stated reason for keeping it is refuted by the plugin's own metadata.txt
    (qgisMinimumVersion=3.40; serverProperties() exists since 3.22). The GDAL FutureWarning is NOT
    cosmetic for this module: band.WriteArray's CPLErr return is discarded, so today a failed
    write is silently ignored and reloadData republishes whatever is on disk, while under GDAL
    4.0's default exceptions the same failure would raise into update()'s guard — a genuine
    change of this module's error behaviour, pinned by not calling either function.
  Important 6: the z0 bug the implementer found by TIMING has no regression test. All ten new
    tests go through _ready(), which overwrites z0/z1/dz/cell, so nothing exercises the seeded
    defaults — which is exactly why the bug reached Step 10 alive.

Ruling AA: fix Important 5's GDAL half with a SCOPED `gdal.ExceptionMgr(useExceptions=True)`
  around the write, NOT a module-level gdal.UseExceptions(). Why: UseExceptions() changes the
  mode for the whole QGIS process and every other consumer of the bindings in it — the plugin
  does not own that global. The reviewer verified on this build that the context manager silences
  the warning, leaves GetUseExceptions() == 0 afterwards, and makes a failing Create raise into
  the existing guard. Cost if wrong: the write's error mode differs from the rest of the process,
  which is the point.
Ruling AB: fix Important 2 by having the coverage view measure its OWN limit regardless of the
  stretch combo. Why: the shared stretch exists so DEPTHS stay amplitude-comparable (spec 8), and
  that means nothing for trace counts; a count map needs a count scale. Cost if wrong: switching
  to coverage and back re-measures a limit instead of reusing a cached one.
Ruling AC: promote four Minors — M1 (the end-of-axis readout test cannot discriminate its own
  mutant, because at the clamped last window lo == hi == 30.0 coincides with the mutant's own
  top: same class as the blind tests found in Tasks 1 and 3), M2 (_refill_palette_combo fires
  three spurious full rebuilds and logs `unknown colormap ''` on EVERY prepare, because it
  refills a combo whose currentTextChanged is wired to refresh_slice), M3 (a resolution change
  can rebuild up to three times via setRange/setValue before refresh_slice's own call — invisible
  to the debounce test only because a cell change leaves the slider value untouched), M4
  (refresh_slice's error path leaves _values, _window and the readout describing the previous
  tick, so an out-of-range z1 shows an error bar over a map and readout that still assert the old
  window). All four are cheap and three are my brief's.
Task 4: minor (deferred): _shared_limit_cache survives a same-choice re-prepare, so moving a grid
  leaves the previous binning's shared limit in force until a Resolution widget is touched.
Task 4: minor (deferred): flush_debounce() applies unconditionally, so anything wanting the
  current geometry pays a full set_resolution -> _rebuild_geometry, dropping every LinePlan and
  any resident cube even when nothing is pending. Guard on _debounce.isActive().
Task 4: minor (deferred): SliceLayer.session is stored and never read (my brief prescribed the
  parameter).
Task 4: noted: slices_dock.py is 949 lines but the reviewer measured it as ~467 lines of code
  across 32 defs, under 15 lines per method, and judged the plan's file structure still sound.
  The seam if Task 5 grows it further is the Display trio.
Task 4: fix round 1/5 dispatched (resumed implementer a117a8266c42d25fe, 6 Important + 4 promoted)
Task 4: fix round 1/5 implemented — commit e2910d4. 541 core+pure / 2 skipped; 558 QGIS with
  ZERO warnings (was 9). Verified by me.
  RULING AA WAS FACTUALLY WRONG and the implementer corrected it. I relayed the reviewer's claim
  that `gdal.ExceptionMgr(useExceptions=True)` silences the FutureWarning; it does not. I verified
  the correction myself: under `simplefilter("error")` the warning still fires inside an
  ExceptionMgr block. Their diagnosis of why is right — ExceptionMgr calls the thread-local
  `_SetExceptionsLocal`, while the warning checks the process-global flag that only the real
  UseExceptions()/DontUseExceptions() set.
  What they shipped is better than what I asked for: BOTH halves, scoped. I verified each
  independently — a failed `Create` inside the block raises RuntimeError (so the substantive
  error-handling fix stands, which was the actual point of Important 5), `GetUseExceptions()` is
  still 0 after the block (so no process state is touched), and the warning filter is narrowed to
  FutureWarning within that one `with` only. Suppressing the messenger alone would have been the
  wrong fix; they did not do that.
  Second disclosed find, theirs: closing Important 4 exposed that dz/z0/z1 defaults were never
  seeded AT ALL when lines arrive after the grid — i.e. the ordinary "new site -> add grid ->
  import" flow, not an edge case. Fixed rather than routed around by the new test.
Task 4: scoped re-review dispatched (opus), diff 86ad30f..e2910d4
Task 4: fix round 1/5 (10 addressed, 0 open; commits 86ad30f..e2910d4). The re-reviewer settled
  the GDAL question properly, which neither I nor Ruling AA had: `ExceptionMgr` DOES flip
  `gdal.GetUseExceptions()` — the process-global read that `gdal_array.BandWriteArray`'s
  `if ret != 0: _RaiseException()` is gated on — while NOT flipping
  `_UserHasSpecifiedIfUsingExceptions()`, which is what the warning checks. That is why the
  behaviour fix works and the warning survives, and it means the CPLErr return IS now checked
  rather than papered over. Probed: a write to a read-only dataset raises RuntimeError inside the
  block. It also confirmed slice_layer.py is the repo's ONLY osgeo consumer, so nothing else
  loses the notice, and that nothing outside the block discards a GDAL error return.
  It also verified the second disclosed find is genuine and that re-seed protection holds for the
  ordinary case, while naming two narrow corners where it does not (below).
Task 4: minor (deferred): slices_dock.py:471 passes `str | None` into `_seed_dz_z_defaults(grid_id:
  str)`. Harmless at runtime but the annotation is wrong, and THIS FILE IS OUTSIDE CI'S MYPY LIST
  so nothing catches it. FLAG TO THE FINAL REVIEW — the same is true of slices_engine.py,
  slice_layer.py and the two dialogs; only slices_plan.py, lookup.py and view_transform.py are
  type-checked.
Task 4: minor (deferred): one window re-seeds over a user's deliberate edit — select a grid with
  no lines, hand-set dz/z0/z1, then import lines. And its mirror: the retry lives only in the
  _included_is_default branch and set_included clears that flag permanently, so accepting the
  line chooser for an empty grid keeps the unusable dz=1.0/z0=0.0/z1=100.0 forever.
Task 4: minor (deferred): the error path resets _values/_window/readout but not legend_label,
  which keeps the previous tick's number beside "error: ...".
Task 4: minor (deferred): in coverage mode _renderer_key carries a per-slice max count, so the
  256-stop shader is rebuilt on any tick where the max changes. Same behaviour already accepted
  for the "this slice" stretch.
Task 4: minor (deferred): warnings.catch_warnings() mutates the process-global filter list and is
  not thread-safe; _write is main-thread only, so the exposure is a ~0.5 ms window per tick in
  which a warning emitted by a QgsTask worker would be dropped.
Task 4: minor (deferred): the GDAL FutureWarning is one-shot per process and its "already warned"
  flag is set BEFORE warnings.warn, so if this plugin's first write is the first binding call to
  trip it, no other Python consumer in that QGIS process ever sees the notice. A real third-party
  effect of the chosen fix; still strictly less invasive than the forbidden global call.
Task 4: minor (deferred): the final flush happens via `dataset = None`, and a SWIG destructor
  cannot raise, so a write error materialising only at close is still silent. `dataset.Close()`
  (GDAL >= 3.7; this build is 3.8.4) would surface it through the same guard.
Task 4: minor (deferred): Ruling AB's "regardless of the stretch combo" is pinned only in the
  default shared mode; no test selects "this slice" with coverage on. Code orders the coverage
  check first, so behaviour is right; the assertion is missing.
Task 4: minor (deferred): SliceLayer._create_layer never checks layer.isValid() before
  registering. Pre-existing.
Task 4: complete (commits 8efdc72..e2910d4, review clean)

Task 5: dispatched (sonnet, agent a97c4c4d8eeefaf2c), BASE e2910d4
Task 5: implementer DONE, commit a5339ae. 542 core+pure / 2 skipped; 566 QGIS, 0 warnings;
  ruff/format/mypy clean. Verified by me. Three disclosures:
    - Mutant 1 (paint ordering) confirmed genuinely untested, exactly as my brief predicted, and
      reported rather than papered over with an invented test.
    - Mutant 4's actual behaviour diverged from my prediction: a NaN band silently no-ops rather
      than raising or logging. Guard kept anyway; reasoning in the report.
    - Unbriefed and correct: window_cleared is also emitted on refresh_slice()'s EXCEPTION path,
      not only the early return my brief named, so an error cannot leave a stale band on the
      radargram. That is the same shape as Task 4's Important 4, caught pre-emptively.
Task 5: task review dispatched (opus), diff e2910d4..a5339ae
Task 5: review verdict — spec ✅, quality APPROVED. No Critical, no Important; five Minors. The
  reviewer verified the third disclosure is correct and cannot fire where the band should have
  been left alone (every path emitting window_cleared also clears _values and re-emits
  slice_changed, so the band never survives a tick whose slice and readout were both discarded).
  It also confirmed §9.3 is respected: the filter returns False for every non-wheel event and
  again whenever the delta is 0, so plain scroll still reaches the canvas, and a grep of the diff
  for setMapTool/QgsMapTool/mousePressEvent found no interception.

Ruling AD: no fix LOOP is triggered (no Critical or Important), but fix three of the five Minors
  directly, as a quick round with no review cycle — the Ruling J shape, and the project's
  right-size-the-process preference. Two of them are tests that prove nothing, which is the
  specific failure this milestone exists to catch:
    M2: `_paint_slice_band` mutated to `return` on its first line PASSES ALL 566 TESTS. The band's
      arithmetic is covered; its painting is not. The brief forbade inventing an ORDERING test,
      which is a different thing from a "the band changes pixels" test, and this file already has
      the cheap precedent (a cleared-vs-drawn pixel comparison). With a pick placed under the
      band it pins ordering too — closing the gap the brief said could not be closed.
    M3: a CanvasDepthScroll mutant returning True before the delta == 0 check would take the
      map's zoom away entirely and survives the whole suite. §9.3's "plain scroll still zooms" is
      pinned only at the pure-function level, not at the filter that actually decides. My brief's
      stated reason for avoiding this — Qt 5/6 QWheelEvent constructor divergence — does not
      apply to a three-attribute stub passed straight to eventFilter.
    M1: the two ProfileDock relays are unguarded slots. My brief's PROSE asked for guards and the
      code block I also gave did not have them; the implementation followed the block. The global
      constraint says an escape from any slot aborts CI.
  Cost if wrong: two small tests and two try/except wrappers.
Task 5: minor (deferred): shift+scroll is consumed even when no source is prepared, so the
  gesture is swallowed with no effect. Plain scroll is untouched, so §9.3 is not violated.
Task 5: minor (deferred): the non-finite band guard clears silently with no _log, which is the
  outcome the implementer's own mutant-4 analysis argues against.
Task 5: minor (deferred): _paint_slice_band is DEFINED between _paint_selection and _paint_picks
  but CALLED first, so reading order no longer matches paint order.
Task 5: minor (deferred) FLAG TO FINAL REVIEW: CanvasDepthScroll lives in slices_dock.py, so
  plugin.py now imports a canvas event filter from a UI dock module. This codebase keeps
  canvas-level behaviour in its own modules (map_link.py, maptools/). My brief mandated "the same
  module", so this is my choice rather than an implementation defect.
Task 5: quick fix round dispatched (haiku — three small, fully specified changes)
Task 5: quick fix round implemented — commit 5ee9d05. 542 core+pure / 2 skipped; 568 QGIS, 0
  warnings. No re-review, per Ruling AD; I verified BOTH mutants myself instead:
    - `_paint_slice_band` no-op -> test_the_band_is_actually_painted_under_the_picks FAILS
      (1 failed / 53 passed); previously this mutant passed all 566.
    - CanvasDepthScroll consuming before the delta check ->
      test_canvas_depth_scroll_consumes_shift_wheel_and_leaves_plain_scroll_alone FAILS
      (1 failed / 35 passed); previously it took the map's zoom away undetected.
    Both reverted, working tree confirmed clean.
Task 5: complete (commits e2910d4..5ee9d05, review clean)

Task 6: dispatched (sonnet, agent a6cb68a7f80315189), BASE 5ee9d05
Task 6: implementer DONE, commit 4633ab3. 543 core+pure / 2 skipped; 578 QGIS, 0 warnings;
  ruff/format/mypy clean. Verified by me. Two brief gaps fixed by them: QFileDialog.getSaveFileName
  was not in the qgis conftest's modal-forbid list (added — a change to SHARED test
  infrastructure, flagged to the reviewer), and my Step 7 `git add` omitted survey.py despite
  Step 3 requiring its docstring change.
  Decision on the carried Task-1 finding (export pitch): stays at the frame's own cell size. Three
  reasons — the export path is always slice -> fill -> to_north_up so the fill has already smeared
  any isolated cell; a finer pitch is 4x the pixels, undermining the very "one band is cheap"
  property INTERLEAVE=BAND is chosen for; and implementing it means either changing a shipped
  Task 1 API that has a second caller (SliceLayer) or duplicating its resample loop here.
  Flagged to the reviewer that reason 1 holds only at radius > 0, and the export uses whatever
  radius the dock currently has.
Task 6: task review dispatched (opus), diff 5ee9d05..4633ab3
Task 6: review verdict — spec ❌, quality NEEDS FIXES. Five Importants. I reproduced the two most
  consequential myself before ruling.
  Important 1: the cube id collides for ANY dotted name. `cube_id = f"{grid}__{Path(path).stem}"`
    uses the RAW dialog string while the file written is `_npz_path(path)`. Save `cube.v1` then
    `cube.v2`: two .npz files on disk, ONE record — site.cubes["A__cube"] overwritten, the first
    cube orphaned with no recipe. `store._npz_path`'s own docstring names this case verbatim and
    exists to prevent the file-level version of it; the id derivation reintroduces it one level up.
  Important 2: "Save cube..." in the re-preparation window writes and records an ALL-NaN cube and
    reports success. I verified `build_cube([], [], frame, z, prov)` myself: raises nothing, mean
    all-NaN, counts sum 0. `cube()` lacks the zero-line guard `_slice` has, and `set_source`
    clears _lines but leaves _frame/_z, so `_require_geometry()` succeeds. The survey file then
    gains a record pointing at a cube with no data, announced as a success. The implementer's
    report mischaracterises this as a caught RuntimeError — true for Export, false for Save.
  Important 3: `zip(..., strict=True)` is Python 3.10+ against a py39 floor. Verified: it is the
    ONLY such construct in the repo, and nothing catches it — both venvs are 3.12, the 3.9 CI job
    never imports this module, and ruff's B905 is the inverse rule and gated off below py310. On
    a QGIS 3.40 build running Python 3.9, clicking Export raises TypeError.
  Important 4: the entire UI half (plugin.py:519-617, both buttons, both signals) is untested.
    The implementer WROTE the smoke test and deleted it before committing. Importants 1 and 2
    both live in that code.
  Important 5: the export is lossy at rotated azimuths and says so in neither the UI nor the file.

Ruling AE: the export pitch decision STANDS — the reviewer approved it independently and added a
  fourth reason neither the implementer nor I had: a finer pitch is a MITIGATION, not a fix.
  Backward nearest-neighbour at half pitch still drops cells; it only lowers the probability. The
  actual fix is forward scatter-mapping inside to_north_up, which is Task 1 work. So 4x the
  pixels buys a partial mitigation — the wrong trade twice over.
  But reason 1 must be STRUCK from the docstring, not merely discounted: fill does not put a
  dropped cell into the output at all, it only makes that cell's value recoverable from a
  surviving neighbour. The loss is unconditional at every radius; fill changes only how much it
  matters. And the docstring's claim that radius 0 is "a debugging view, not the archival
  deliverable" is an assertion the code does not enforce — spec 6.4 calls radius 0 the honest
  unfilled truth, the spin box permits it, and its construction default IS 0.0.
  Fix: warn at radius 0, and — the part worth having — carry NSGEO_FILL_RADIUS_CELLS and
  NSGEO_FRAME_AZIMUTH_DEG as dataset-level metadata, so the loss is legible FROM THE FILE. That
  is exactly §9.4's own principle for band descriptions, applied one level up. Cost if wrong: two
  metadata items nobody reads.
Ruling AF: record `provenance().line_keys` (what was actually binned), not `choice.line_keys`
  (what was asked for), and keep the docstring as written. Why: the record's contract is "this is
  what the array contains", and Task 7 restores from it — restoring a requested set would try to
  re-prepare a line that is not in the cube. The requested-vs-prepared difference is already
  surfaced through on_error at preparation time, so nothing is lost by recording the truth.
  Cost if wrong: a record names fewer lines than the user selected, which is the fact.
Ruling AG: close the spec ❌ on the writer interface with the reviewer's ~8-line shape — a
  `SliceWriter` Protocol, a keyword-only `writer` parameter defaulting to None (not a mutable
  default), and one stub-writer test. Why it is worth the eight lines: §9.6's whole argument is
  that adding netCDF must be additive rather than a refactor, and both callers currently name the
  concrete class. The stub test also pins the band-by-band streaming property — the cheapest
  possible test of §7.4's "never requires a resident cube".
Ruling AH: `write_coverage` has no caller anywhere, and §9.4 says coverage exports as a companion
  single-band raster WHEN ASKED — so there must be a way to ask. Wire it to the control that
  already exists: when the dock's coverage toggle is ticked at export time, write the companion
  beside the cube and say so in the message. Cost if wrong: a user with coverage displayed gets an
  extra small file they did not separately request; the message tells them.
Task 6: minor (deferred): ViewSettings.from_dict has no caller and no test — Task 7 is its caller.
Task 6: minor (deferred): save_cube_npz promotes a streaming engine permanently, because cube()
  caches into _cube which only set_source/clear reset. Dropping the cube after the write when
  mode == "streaming" would be truer to §7.4.
Task 6: minor (deferred): Close() in the finally can mask the original error — if WriteArray
  raises, Close() very likely raises too and becomes what the user sees; the write error survives
  only as __context__.
Task 6: minor (deferred) FLAG TO FINAL REVIEW: two private reaches, both my brief's — the import
  of `store._npz_path` (the .npz append rule deserves a public `nsgeo.slices.npz_path`) and
  `session._set_dirty(True)`, the only external caller of that private method in the repo. Every
  other site mutation goes through a SiteSession method; `SiteSession.record_cube(id, record)` is
  the shape this fits.
Task 6: minor (deferred): no test exercises a ROTATED frame — the fixture grid is azimuth 0.0,
  the one azimuth at which to_north_up drops nothing.
Task 6: fix round 1/5 dispatched (resumed implementer a6cb68a7f80315189, 5 Important + spec gap
  + 2 promoted)
Task 6: fix round 1/5 implemented — commit 8f7c14b. 543 core+pure / 2 skipped; 592 QGIS
  (+14), 0 warnings; ruff/format/mypy clean. Verified by me, including that the py3.10-only
  `zip(strict=)` CALL is gone — the four remaining textual matches are all comments explaining
  why it is not used.
  One self-caught gap disclosed: their own first draft of the Important-1 test typed `.npz`
  explicitly and so never exercised the collision; found and fixed before reporting.
Task 6: minor (deferred) FLAG TO FINAL REVIEW: Task 3's concurrency test
  (test_a_choice_delivered_during_the_cancel_wait_does_not_reopen_the_overlap) surfaced as flaky
  ONCE under concurrent CPU load, and was confirmed not a regression (3/3 isolated, 2/2 clean
  full-suite). It is timing-dependent by construction, and CI runners are contended — this is the
  most likely source of an intermittent red build on this branch. Worth deciding whether to make
  it more tolerant or mark it.
Task 6: scoped re-review dispatched (opus), diff 4633ab3..8f7c14b
Task 6: fix round 1/5 (8 addressed, 0 open; commits 4633ab3..8f7c14b). The re-reviewer traced the
  `cube()` guard's three in-repo callers and confirmed it cannot break any — `_slice` is
  unreachable with zero lines (its own identical guard runs three lines earlier), slice_at's
  resident prewarm previously built an all-NaN cube and hit that guard two statements later so it
  now just raises earlier and cheaper, and shared_limit's resident branch previously returned a
  limit measured over an all-NaN cube where the streaming branch already raised — the two now
  agree. It also confirmed the metadata values are the ones the export actually used (same
  radius handed to fill, same frame handed to to_north_up) and that a plan built without a radius
  OMITS the tag rather than writing a 0 that would disagree with the pixels.
Ruling AI: close both remaining Minors directly, no review cycle. (a) The post-loop count check
  replaces `strict=True` in only ONE direction — zip stops at the shorter iterable, so a `slices`
  longer than the plan has its surplus silently discarded and the check never trips. I asked for
  a fix that "keeps the same guarantee"; half of it is not that, and it is one line. (b) A
  write_coverage failure currently surfaces as "could not export the GeoTIFF" at Critical, after
  the main file has been written and its layer added — telling the user the export failed while
  they can see the layer in the tree. Cost if wrong: two small changes to code already reviewed.
Task 6: minor (deferred) FLAG TO FINAL REVIEW: SliceWriter.OPTIONS is declared on the Protocol but
  read only via self.OPTIONS inside GeoTiffSliceWriter, and as a mutable list[str] it is
  invariant — a writer declaring a tuple or Sequence would fail a static conformance check it
  need not. Runtime substitution is unaffected.
Task 6: minor (deferred): slice_export.py is outside the extended mypy set, so
  GeoTiffSliceWriter's conformance to the new Protocol is proven only by the runtime stub test.
Task 6: quick fix dispatched (haiku — two one-line changes)
Task 6: quick fix implemented — commit 7653fd0. 543 core+pure / 2 skipped; 594 QGIS, 0 warnings.
  Both Minors closed with before/after evidence. No re-review, per Ruling AI.
Task 6: complete (commits 5ee9d05..7653fd0, review clean)

Task 7: dispatched (sonnet, agent a62d1daf6f5dd9625), BASE 7653fd0
Task 7: implementer DONE, commit c76084f. 543 core+pure / 2 skipped; 599 QGIS (+5), 0 warnings;
  ruff/format/mypy clean; SCHEMA_VERSION still 1. Verified by me. Four disclosures:
    - My Step 6 mutant-1 prediction was wrong in the opposite direction to the one I warned
      about: dropping "lines" fails BOTH tests, not just the line-set one, which means the
      fixture is not what my brief assumed. They reported it, as asked.
    - Mutant 3 fails NEITHER supplied test, so they added a fifth to cover it.
    - Two of my test snippets were missing the required `line_keys=` kwarg Task 6's review had
      introduced — my brief was written against the pre-review signature.
    - Undocumented find of their own: async preparation could silently DISCARD a restored
      palette, fixed with a _pending_palette mechanism.
  Also disclosed, and a real gap: no automated dock-UI test exercises restore_cube end to end —
  carried into the review dispatch.
Task 7: task review dispatched (opus), diff 7653fd0..c76084f
Task 7: review verdict — spec ✅, quality NEEDS FIXES. Two Importants, both defeating the
  feature's own purpose. I reproduced the first myself.
  Important 1: restore_cube LOSES THE DEEPEST Z LEVEL on most real geometries. z1_spin holds 3
    decimals; the record's t1_ns needs 4, because Task 6 deliberately wrote the axis's own
    t_end_ns = z0 + (nz-1)*dz, and with z0 at 3 dp and dz at 4 dp that is exactly a 4-decimal
    quantity. My own sweep over plausible GSSI headers: 43 of 90 combinations lose a level (the
    reviewer measured 50 of 90 on a slightly different grid — same magnitude). Note the Resolution
    group is already internally inconsistent: dz_spin is setDecimals(4) while z1_spin is 3.
    The brief's own "done when" — the cube selected from the combo produces the identical slice —
    therefore fails for the majority of real files, SILENTLY, with a shorter slider and a missing
    deepest slice. Invisible to test_a_restored_recipe_reproduces_the_identical_slice because
    that test applies recipe.resolution straight to the ENGINE and never touches the widget.
    This is the same shape as every other defect this milestone has caught: the test that was
    supposed to pin the property cannot see the layer where the property breaks.
  Important 2: a record naming a grid, preset or transform the site no longer has restores the
    WRONG source silently under the saved cube's name. setCurrentText on a non-editable QComboBox
    is a NO-OP when the text is not in the list, so a renamed preset or removed grid leaves the
    previous selection in place, prepare() succeeds, the status reads "prepared · N lines", and
    cube_combo still displays the cube id. recipe_from_record's own docstring names this as the
    one failure this feature must not have. Missing LINES are handled well by contrast — each is
    named through _report.

Ruling AJ: fix Important 1 with `z1_spin.setDecimals(4)` — exact given z0 at 3 dp and dz at 4 dp —
  rather than by bypassing the widget. Why not hand recipe.resolution straight to the engine: the
  spin boxes are what the user then sees and edits, so a widget disagreeing with the engine would
  restore correctly once and diverge on the next touch. Fixing the widget's precision fixes both.
  Cost if wrong: one more decimal place visible in a spin box.
Ruling AK: fix Important 2 by CHECKING membership and refusing by name, not by silently
  substituting. `restore_cube`'s existing except already routes a ValueError to source_status and
  error, so the machinery is there. Why refusing rather than restoring what it can: a partially
  restored source under a saved cube's name is precisely the failure the feature exists to
  prevent, and the user can act on "preset 'x' no longer exists" — they cannot act on a picture
  that is quietly wrong. Cost if wrong: a cube whose preset was renamed cannot be restored until
  the preset is renamed back or the cube re-saved; the message says which.
Ruling AL: add the dock-UI test the implementer disclosed as missing. It is the layer where BOTH
  Importants live, and neither recipe_from_record's tests nor the identical-slice test can see the
  widgets at all. The reviewer costed it at ~20 lines on the existing `docked` fixture with no
  second preparation. Cost if wrong: one more test.
Ruling AM: correct the tolerance rationale in the report and the decision record. The reviewer
  showed my/their stated reason ("two separately dispatched preparations are not guaranteed to sum
  in bit-identical order") is unsupported: work() is a single sequential loop over jobs in
  line_keys order, and the restored line_keys come from provenance() in that same order — there is
  no parallel accumulation to reorder. The tolerance is harmless slack, not masked
  nondeterminism, and the record should say so rather than assert a hazard that does not exist.
Task 7: fix round 1/5 dispatched (resumed implementer a62d1daf6f5dd9625, 2 Important + 1 test +
  1 documentation correction)
Task 7: fix round 1/5 implemented — commit 8350853. 543 core+pure / 2 skipped; 604 QGIS (+5
  dock-level tests), 0 warnings; ruff/format/mypy clean. Verified by me, including that
  z1_spin.setDecimals is now 4 while z0_spin stays 3 and dz_spin is 4 — the precision is now
  internally consistent with what t_end_ns actually carries.
Task 7: scoped re-review dispatched (opus), diff c76084f..8350853
Task 7: fix round 1/5 (7 addressed, 0 open; commits c76084f..8350853). Re-reviewer verified the
  decimal chain independently rather than on report: t0_ns is stored unchanged by ZAxis, so a
  3-dp z0 round-trips losslessly, while t_end_ns = t0 + (nz-1)*dz sums a <=3-dp value with a
  4-dp one and so needs exactly 4 — the implementer's conclusion about z0_spin is right. It also
  confirmed the refusal raises BEFORE any mutation (the first widget write is strictly after),
  that the _pending_palette guard correctly distinguishes "dispatched" from "not dispatched" on
  every path reachable from restore_cube, and that the new dock test perturbs every control first
  so restore is not a tautology.
Task 7: complete (commits 7653fd0..8350853, review clean)

ALL SEVEN TASKS COMPLETE. Branch nsgeo-m11 at 8350853.
Final state: 543 core+pure passed / 2 skipped (both pre-existing deliberate schema skips);
604 QGIS passed, 0 warnings; ruff clean; ruff format clean; mypy Success over 33 files.
Baseline at branch start was 502 core+pure / 2 skipped and 470 QGIS.

## Final whole-branch review (opus, ee0fdea..8350853) — verdict: READY TO MERGE WITH FIXES
Read in five passes partitioned by LAYER rather than by commit, because the invariants cross
commit boundaries. Four numeric probes on real DZT data.

IMPORTANT 1 (the headline, and invisible to every per-task review): the shared stretch is
  MEASURED ON UNFILLED SLICES and APPLIED TO FILLED ONES. `refresh_slice` displays
  `fill(values, coverage, radius)`; `display_limit`'s shared branch measures
  `engine.shared_limit` over `_slice(w)[0]`, the UNFILLED array; its "this slice" branch measures
  the FILLED one. So the two modes measure different quantities and the DEFAULT measures
  something never drawn. Measured on this repo's four real DZT files at the dock's own seeded
  defaults: 1.11x too high with amp_envelope, and 1.76x with transform "none" — WHICH IS THE
  OUT-OF-THE-BOX CONFIGURATION, since transform_combo auto-selects "none". Every slice then
  renders at ~57% of intended contrast, identically at every depth: precisely the "reads as dim
  data rather than a wrong limit" failure that render.UnipolarClip's and display.shared_limit's
  docstrings exist to prevent, one layer further out. Flipping to "this slice" jumps 1.76x
  brighter at the same position, which reads as the shared stretch being broken.
  The existing test only checks constancy-across-depth versus variation, never the limit against
  current_values().
IMPORTANT 2: `clear()` BYPASSES the cancel-and-confirm wait, reopening the measured two-task
  segfault. clear() sets _running = False but never cancels _pending, and _cancel_in_flight gates
  its confirm on `if self._running`. So: prepare auto-dispatches, user hits File > Open site mid
  preparation, clear() forces _running False, the next set_source cancels but SKIPS the confirm,
  and two preparations execute on two worker threads for up to ~40 ms. THIS IS THE INTERACTION OF
  TWO SEPARATELY-DEFERRED TASK 3 MINORS — neither task review could see that together they defeat
  the wait Rulings V and W were built to install.
IMPORTANT 3: the residency budget and its override have NO UI AT ALL. set_budget_bytes has zero
  references anywhere, production or test — a complete orphan under spec §11. set_always_resident
  is tests-only. My own Ruling 1 explicitly committed to shipping the binary override; the
  known-and-accepted note covered only the THIRD TIER, not this. And §9.1/§7.4's "warns and
  requires confirmation above the budget rather than hard-capping" is unimplemented — the label
  reports "about N MB" and never compares it to anything.
IMPORTANT 4: save_cube_npz permanently promotes a streaming engine, and format_status then
  under-reports held memory by the whole cube — 28 MB claimed while 111 MB is held at spec §7.2's
  own 24-line row, or 28 vs 359 MB at cell 0.05. Spec §7.2 makes memory the binding constraint
  and §9.2 makes that line the one place a user can see it.
Plus six Minors (5-10): the dock's slice count disagrees with the GeoTIFF's band count near the
  deep end; deleting a contributing line blanks a still-valid slice with a raw KeyError;
  write_coverage poisons the redraw-time readout; zero-coverage cells are transparent on screen
  but 0 in the exported companion; display_limit's per-slice branch bypasses limit_over_slices;
  a one-level cube can be saved but never restored.

VERIFIED CLEAN by the reviewer: the py3.9 sweep (AST over all 69 new/changed files — no 3.10+
  construct anywhere); the TWO shared_limit implementations genuinely agree including the tail;
  "NaN iff count 0" versus fill's denominator; all seven "none"/"" crossings mutually inverse;
  the z round-trip and Ruling AJ's decimal choice; LinePlan staleness; the residency contract
  (nothing promotes except save_cube_npz, which needs the volume); Ruling K's shallow snapshot
  UNREACHABLE (save_preset replaces the whole list); unload() ordering correct including that
  slice_layer is still alive when the nested cancel loop can reach it; spec §12 — nothing
  out-of-scope shipped; and spec §13's M11 list landing in full.

Ruling AN: on Important 3, deliver rather than defer, but place the override in the DOCK, not in
  settings. Why: §9.2 says the override "lives in settings", and this plugin has NO settings
  infrastructure — building one is scope beyond §13's six deliverables, while shipping two
  orphaned methods violates §11 and leaves my own Ruling 1 undelivered. A single checkbox in the
  Display group carrying §9.2's own wording gives set_always_resident a real caller, and the
  over-budget warning §9.1 explicitly requires is cheap and currently missing entirely. DELETE
  set_budget_bytes: the budget is a constant, nothing in the spec requires it configurable, and
  an orphan is worse than an absence. Cost if wrong: a performance detail sits one control away
  from workflow controls, which is the placement §9.2 argued against for "Pin cube..." — mitigated
  by using the spec's own wording, which names what it buys rather than what it is.

## Final fix wave (sonnet, ONE dispatch per the skill), 8350853..37546ac
All four Importants, six Minors, the empty-grid latch and the cheap cluster fixed across six
coherent commits. Verified by me at HEAD: 543 core+pure / 2 skipped; 619 QGIS (604 + 15 new),
0 warnings; ruff, format and mypy clean.
Disclosed by the implementer, not amended (no-amend rule): commit 331e4bd alone is not
independently bisectable — it drops the DEFAULT_BUDGET_BYTES import, textually adjacent to its
own import edit, three commits before d3469e1 removes the last usage. HEAD and every commit from
d3469e1 onward are green. Their own real-DZT measurements (1.10x / 1.69x) differ slightly from the
reviewer's (1.11x / 1.76x) because of a different grid/preset arrangement — same mechanism, same
magnitude.

## PAUSED HERE at the user's request, 2026-09-20.
RESUME POINT: exactly two things remain before a merge decision.
  1. ONE scoped re-review of the final fix wave (diff 8350853..37546ac). The package is not yet
     built; run scripts/review-package with that range. Per the skill there is no second fix
     wave — residual findings get adjudicated and surfaced, not re-dispatched.
  2. The MANUAL WALKTHROUGH GATE, which is a human checkpoint and cannot be delegated:
       .venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo
     (profile is ns_geo, with an underscore), then the twelve steps in the plan's
     "After Task 7: the manual walkthrough gate" section. M11 is entirely UI, so this gate is the
     only thing that actually tests what the milestone claims.
Nothing is merged. The branch is pushed. The decision record under
docs/superpowers/sdd/<plan-name>/ has NOT yet been committed — that is part of landing the
milestone, after the walkthrough.

## Final fix-wave re-review (opus, 8350853..37546ac) — ALL ADDRESSED, no new Critical/Important
Important 1 verified at the level that mattered: the shared branch now measures the IDENTICAL
(values, coverage) pair at the identical radius that refresh_slice renders, the cache key moves
with either spin box, and both stretch branches now go through limit_over_slices so the
NaN-before-stride filtering is shared. The real-DZT test discriminates at unfilled/correct > 1.05.
Important 2: clear() drains on all three paths; no deadlock (wait is QTimer-bounded, nested loops
restore on_prepared LIFO, finished() discards from _pending on every exit including the stale one).
Important 3: the checkbox is genuinely wired and the new test flips engine.mode through it;
set_budget_bytes is gone with only an explanatory comment left.
Python 3.9 floor swept CLEAN with ast.parse(feature_version=(3,9)) over all 15 changed files.
Bisectability: confirmed and LARGER than disclosed — TWO commits (331e4bd, 2081dc4) carry the
undefined DEFAULT_BUDGET_BYTES, not one. Does not block: the window is interior, HEAD is green,
and the failure is a loud NameError that a bisect answers with `git bisect skip`.

Ruling AO: fix the Minor 6 RESIDUAL now rather than carrying it, against the re-reviewer's own
  "non-blocking" recommendation. Why I am overriding that: `engine.cube()` passes
  `self.provenance()` into build_cube, and provenance() resolves a velocity through
  `self._lines[0].key` — so deleting a contributing line raises a raw KeyError that breaks
  "Save cube..." AND "Export GeoTIFF" IN EITHER MODE, i.e. two of §13's six deliverables, after
  an ordinary survey edit. And the reviewer established that THIS WAVE made it worse: Important
  3's new checkbox moved resident mode from "reachable only on 115+ line sites" to one click, so
  the resident-mode refresh path went from obscure to ordinary. The manual walkthrough is the
  very next step and I would rather the user walk through working software than discover this.
  Cost if wrong: a few lines in provenance()'s velocity resolution; the change is small enough
  that I verify it myself rather than spending another review cycle.
Ruling AO implemented — commit 336ff0a. Two-part, both narrow: provenance() falls through to the
  next prepared line, and the dock's _resolved_velocity() guards its own call too (the dock reads
  included_keys()[0], which can equally name a removed line). Verified by me at HEAD: 543
  core+pure / 2 skipped; 621 QGIS, 0 warnings; ruff, format and mypy clean.
  Both new tests confirmed to fail against the pre-fix code with KeyError.

## CARRIED AS KNOWN ISSUES into the merge decision (re-reviewer's own triage, accepted)
1. Bisectability: TWO interior commits (331e4bd, 2081dc4) reference DEFAULT_BUDGET_BYTES after
   its import was dropped and before its last use was removed. HEAD and everything from d3469e1
   on are green. A bisect answers this with `git bisect skip`; a squash or merge commit erases it.
2. display.py:157's docstring still says "the caller is the Slices dock" — commit 331e4bd deleted
   exactly that call, so nsgeo.slices.display.shared_limit now has core tests as its only callers.
   Docs-only.
3. slices_dock.py:758's latch fix also changed a legitimate case: unchecking EVERY line on a
   populated grid and pressing OK now leaves _included_is_default True, so the next session signal
   silently re-includes every line. Benign (a zero-line source renders nothing anyway) and
   strictly better than the latch it replaced, but it is a behaviour change nothing asked for.
4. The concurrency test's slow_load widened 50 -> 150 ms, which buys timer-landing margin at the
   cost of cancel-confirm margin against an unchanged _CANCEL_TIMEOUT_MS = 250 — ~80 ms of slack
   where ~180 ms existed. It re-flaked once after the widening. Most likely source of an
   intermittent red build.
5. clear() is the one _cancel_in_flight caller without a _dispatching guard. Unreachable today
   (every production route to set_source is behind `not is_running`, `_updating`, or the wait's
   own ExcludeUserInputEvents mask), but it is the Important 2 hazard one layer out.

## REMAINING BEFORE A MERGE DECISION: the manual walkthrough gate only. Human checkpoint.
