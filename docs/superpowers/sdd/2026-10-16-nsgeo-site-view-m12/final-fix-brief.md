# M12 final-review fix wave: the complete list

M12's final whole-branch review (base 232fc18, head 3ef95d2) found no Critical issues. It returned "ready to merge with fixes". Every item below is in scope for this one fix wave. File and line references are to 3ef95d2.

Binding documents:
- `docs/superpowers/specs/2026-10-16-nsgeo-site-view-design.md`
- the plan's Global Constraints and traps, at `.superpowers/sdd/2026-10-16-nsgeo-site-view-m12/global-constraints.md`

Trap 1 still governs everything: at most one line-preparation `QgsTask` may run at a time, across all engines.

## Important

### I1. `compose` makes a full-lattice pass per layer, so a site laid at a bearing other than north is slow

Where:
- `nsgeo/slices/site.py:128-150` (`compose`)
- `site_engine.py:709-741` (`_gather`)
- `site_engine.py:842` (the compose call)

What happens:
- Ruling 2 halves the lattice pixel for any rotated frame.
- The reviewer ran core `compose` on the spec's 10 × 50 m site at a 30° bearing:
  - the lattice is 2133 × 1693 (3.6 Mpx);
  - compose costs 281–426 ms per tick;
  - north-up costs 30–37 ms.
- `scripts/bench_site.py:67` only ever measured azimuth 0.

Fix:
- Keep each gather's bounding window on the lattice, `(row0, row1, col0, col1)`, with the ids for that window only.
- Accumulate each layer into its window only.
- Output must be bit-identical to today's `compose`. Keep `compose`'s current signature and behaviour for existing callers. You may add a footprint-aware variant in `site.py`, or an optional per-layer window; your call. Core stays numpy-only.
- The reviewer's prototype gave identical output at 44 ms (30°) and 5 ms north-up.

Tests:
- Footprint compose equals full compose:
  - on a rotated frame;
  - on the real-data mixed-azimuth case in `test_slices_site.py`;
  - with overlapping layers, which must still average.
- Show the test fails against a footprint mutant that drops the edge row or column of a window.

Benchmark:
- Add a bearing case to `bench_site.py` (10 × 50 m at 30°).
- Re-run the benchmark and report the table: north-up and 30°, `slice_at` median and p90, resident and streaming as chosen automatically.

### I2. Any grid edit, including a velocity edit, drops every site grid's resident cube, gathers, seams and cached stretch

Where:
- `slices_engine.py:879`: `self._cube = None` on every `grids_changed` whose fingerprint is unchanged.
- `site_engine.py:532`
- `site_scope.py:573`

What happens:
- The reviewer forced residency on site3 and called `set_grid_velocity("B", …)`. `has_cube` turned False for A, B and C, and the cached gathers went from 3 to 0.
- The next tick rebuilds every cube on the UI thread. The benchmark's first tick was 3077 ms at 128 samples per trace, and real sample counts are several times that.
- Plan Review Focus 3 says "a velocity edit only relabels depths".
- `test_a_velocity_edit_does_not_re_prepare_or_change_the_slice` dodges this because its grids are tiny and streaming.

Fix:
- `SliceEngine` keeps the `Grid` it last saw and drops its cube only when its OWN grid changed. Ruling Q still applies to the engine's own grid's velocity: that edit drops that engine's cube, because the cube freezes provenance.
- `SiteEngine` drops a grid's gather only when that grid's fingerprint changed, and drops the seams only when a fingerprint or a spacing changed.
- `site_scope`'s cached stretch is dropped only on changes that alter values: fingerprint, source, resolution, method, gains, radius or thickness. Never on a velocity-only edit.

Test, in forced-resident mode on site3:
- `set_grid_velocity("B", …)` keeps A's and C's cubes and every gather;
- B's cube is dropped (Ruling Q);
- `slice_at` values are unchanged.

Prove it against the old drop-everything behaviour. M11's Ruling Q tests must still pass.

## Minor (from the final review)

### M1. A line choice in site scope can be thrown away

`plugin.py:1456`: selecting another row while the modeless chooser is open discards a choice the dialog names explicitly. `set_included_for` already addresses the grid by id.

Fix: apply Ruling Z's moved-selection check only in grid scope. Flip `test_a_line_choice_is_dropped_when_the_selection_moved_meanwhile` for site scope: the choice is applied to the grid it was opened for.

### M2. The site's memory is invisible from *This grid*

After leaving *Whole site*, every prepared site grid stays held.

Fix: when the site holds memory, *This grid*'s status line appends `+<N MB> held by the site view`. Use M11's `format_bytes`, and take the figure from SiteEngine's existing memory accounting.

### M3. Refreshing the grid list is too expensive

`site_scope.py:159-181` and `580-588`: `site_rows` walks every line twice per grid, on every progress step.

Fix: build the grid → line-keys mapping once per refresh.

### M4. Included grids that were left out of the export are not recorded in the file

`site_export.py:217`. Ruling F-2 adds a dataset key, `NSGEO_SITE_LEFT_OUT`:
- a compact JSON object mapping grid id to state string, from `grid_state`, for example `"failed: …"` or `"no lines"`;
- present only when at least one included grid is left out.

Test: read the file back and check the key is present when a grid is left out and absent when none is.

### M5. The lattice refusal message ignores the half pitch

`site_engine.py:586-591` says "too far apart". When any frame is rotated, the message should also say that rotated grids use a half-cell pitch, because that is often the actual cause.

## Folded-in deferred minors (the reviewer recommended these)

- **D1.** `_drop_grid` race. Remove the grid from `_queue`, and pop its state, BEFORE calling `_drop_engine`. Today a retry timer that fires inside the cancel wait can re-dispatch a dropped grid and stall the queue.
- **D2.** Trap-1 window on leaving the site (`slices_dock.py:2181-2183`). Keep `_mark_grid_stale` installed as the dock engine's `on_grid_moved` until `_run_pending_grid_prepare` sees `site_engine.has_live_task` False, and reset it to None only then.
  - Test: a site task outlives its cancel wait, This grid's grid is moved inside that window, and `max_concurrent == 1`.
- **D3.** Ruling F-5, azimuth snap. Change `_azimuth_in` in `site_engine.py`, or the `lattice_pixel` input. Treat a frame as axis-aligned when its deviation from a multiple of 90° moves the frame's far corner by less than 1% of a cell across the frame's own extent: `extent_m × |sin(deviation)| < 0.01 × cell`. A datum-only CRS shift then no longer quadruples the lattice.
  - Test: a frame at 1e-6° and a frame at 90 + 1e-6° each get lattice pixel = cell, and a frame at 2° still gets cell / 2.
- **D4.** An empty remembered line set is treated as the default. In the dock's restore (`_restore_remembered_source`), if the filtered keys come out empty, fall back to the default and set `_included_is_default = True`. Separately, a cube record with no `lines` key now remembers `lines=None` instead of `[]`.
  - Test both.
- **D5.** Fix the exit-139 crash after a failing export test. `open_tif` in `test_plugin_site_export.py` must close its GDAL datasets explicitly, either through a fixture that closes them at teardown or by setting `ds = None` in each test. Otherwise a failing test's traceback keeps a dataset alive past `qgis_app`'s `exitQgis()`.
  - Check it: force one assertion to fail in a scratch copy and confirm pytest exits 1, not 139. Then revert.
- **D6.** Spec drift. In the site-view spec at about line 141 (§3, starting state), add a one-line pointer saying that M12 changed residency to a per-trace estimate (T3-c). Leave the rest of the starting-state text as it is.

## Then

1. Run each changed test file, both full tiers once, the concurrency tests 20 times in a loop, ruff check, ruff format --check, and mypy.
2. Prove the new tests against the mutants named above, with `PYTHONDONTWRITEBYTECODE=1`.
3. Commit in as many commits as is clean. Each commit ends with a `Co-Authored-By:` trailer naming your own model. Push to origin nsgeo-m12.
4. Write `final-fix-report.md` in this directory. Include, per item, what changed, the covering tests, commands and output, and mutant results. Include the new benchmark table.
