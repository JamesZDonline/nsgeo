### Task 4: #75 Whole site UI

**Already gone, verified while planning (at 3104edb):**
- **The unguarded `_note_z_edit` slot:** the method no longer exists, and its replacement is cited
  at `P/ui/slices_dock.py:~2649`.
- **dz seeded from the first ready grid:** `site_scope.py:~503` seeds from the finest sample
  interval among the included grids.
- **The self-compared velocity assertion:** `test_plugin_site_scope.py:~1005` compares C's own
  resolved velocity.

Confirm each, and list it in the report.

**Files:**
- Modify: `P/slices_plan.py` (add `snap_inside`, `window_levels`)
- Modify: `P/ui/slices_dock.py` (drop `_snap_inside`; `_step_levels` / `thickness_step_levels`
  use `window_levels`; expose `finish_debounce_ms`)
- Modify: `P/ui/site_scope.py` (a `SlicesDockView` Protocol for `dock`; no lazy import; `levels`
  uses `window_levels`; no `dock._…` reads)
- Modify: `P/plugin.py` (`_export_site` refuses while the site is busy)
- Test: `T/pure/test_pure_slices_plan.py`, `T/qgis/test_plugin_site_scope.py`

**Interfaces:**
- **Produces `snap_inside(value: float, decimals: int, *, upper: bool) -> float`** in
  `P/slices_plan.py`. It is today's `_snap_inside`, moved verbatim with its docstring.
- **Produces `window_levels(thickness_ns: float, step_ns: float, dz_ns: float) -> tuple[int, int]`**
  in `P/slices_plan.py`, returning `(max(1, round(thickness/dz)), max(1, round(step/dz)))`.
  `site_scope.levels(z, …)` and the dock's This grid rounding both call it.
- **Produces `SlicesDockView`,** a `typing.Protocol` in `P/ui/site_scope.py` naming every dock
  attribute `site_scope.py` reads, typed as precisely as the imports allow.
  - `SiteScope.__init__(self, dock: SlicesDockView)`, and the module-level functions that take
    `dock: Any` take `SlicesDockView`.
  - The one private read left, `dock._finish_debounce.interval()`, becomes a public
    `SlicesDock.finish_debounce_ms` property.
- **Produces the busy refusal in `QgisPlugin._export_site`.** While `site.is_running`, it shows
  `"wait until the site's grids finish preparing, then export."` (Warning, lowercase like the
  method's other refusal) and opens no dialog.

- [ ] **Step 1: Write the failing tests**
  - **Pure:**
    - `test_snap_inside_never_escapes_its_bound`: the cases of today's dock test, if any, moved,
      plus `snap_inside(2.00049, 3, upper=False) == 2.001` and
      `snap_inside(5.9996, 3, upper=True) == 5.999`;
    - `test_window_levels_rounds_and_floors_at_one`: `window_levels(1.0, 0.25, 0.5) == (2, 1)` and
      `window_levels(0.1, 0.1, 0.5) == (1, 1)`.
  - **QGIS, `test_plugin_site_scope.py`:**
    - `test_site_export_refuses_while_a_grid_prepares`. Hold a grid's `Line.load` behind an
      `Event`, as in Task 1. Call `plugin._export_site()` directly. The message log gets the
      refusal, and no export dialog opened (the `answer_modal` / dialog-driver guard sees none).
      Then release.
    - **The seeding rules #75 says are untested.** First grep for existing tests that cover each.
      Write only the missing ones, named for the rule:
      - the cell comes from the finest-spaced included grid;
      - the default inclusion is every grid with lines;
      - seeding happens only when the included set changes, not on every tick or a re-send of the
        same set.

- [ ] **Step 2: Run them and see them fail.** Pure: ImportError. QGIS: the export test fails (a
  dialog opens, or there is no message). Seeding tests that pass at once are recorded as "was
  untested, now pinned".

- [ ] **Step 3: Implement** the Interfaces block. `site_scope.py` then imports `snap_inside` at the
  top, and `grep -n "dock\._" packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` prints only comments.

- [ ] **Step 4: Run** the pure suite, `test_plugin_site_scope.py`, `test_plugin_slices_dock.py` and
  ruff. Expected: all pass, except a #196 flake (note it).

- [ ] **Step 5: Commit and push:** `refactor(site-scope): a typed dock view, one level rounding, export refuses while preparing (#75)`.

---

