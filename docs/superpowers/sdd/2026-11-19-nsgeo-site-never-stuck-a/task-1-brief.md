### Task 1: The busy report, and every site wait prints it (#166 part 1)

**Files:**
- Modify: `P/site_engine.py` (add `busy_report`)
- Modify: `P/slices_engine.py` (add `pending_tasks`)
- Modify: `T/plugin_testing.py` (add `wait_for_site`)
- Modify: `T/qgis/test_plugin_site_engine.py`, `T/qgis/test_plugin_site_scope.py`,
  `T/qgis/test_plugin_site_export.py` (use `wait_for_site`)
- Test: `T/qgis/test_plugin_site_engine.py`

**Interfaces:**
- **Produces `SliceEngine.pending_tasks -> int`,** a property: how many of this engine's tasks have
  not run `finished` yet (`len(self._pending)`).
- **Produces `SiteEngine.busy_report() -> str`.** It never raises: on any exception it returns
  `f"could not describe the site: {exc}"`. The lines, in this order, use exactly these spellings
  (tests pin them):
  ```
  active: True · preparing: 'A' · queue: ['B']
  retry timer: on · reaper timer: off · in dispatch: False
  engine A: running True · live task True · pending tasks 1
  engine B: running False · live task False · pending tasks 0
  retiring engine 1: running False · live task True · pending tasks 1
  exclusive peer 1: live task False
  grid A: preparing (0 of 4)
  grid B: queued
  ```
  - `preparing:` shows `None` when nothing prepares. When the preparing grid's registration no
    longer equals `_preparing_fp`, append ` (moved since dispatch)`.
  - The `retiring engine` and `exclusive peer` lines appear only when there are any. They are
    numbered from 1.
  - The `grid` lines come in source order, then any other grid in `_states`. The `(done of total)`
    part comes from `_progress`, only while it is set.
- **Produces `wait_for_site(site, timeout_ms: int = 60_000) -> None`** in `T/plugin_testing.py`.
  It returns once `site.wait_until_idle(timeout_ms)` is true. Otherwise it raises
  `AssertionError(f"the site did not finish preparing in {timeout_ms} ms\n{site.busy_report()}")`.

- [ ] **Step 1: Write the failing tests** in `T/qgis/test_plugin_site_engine.py`

```python
def test_a_timed_out_wait_names_what_holds_the_site(site3, make_site, monkeypatch):
    release = threading.Event()
    real_load = Line.load  # from nsgeo.model.survey import Line

    def held_load(self):
        release.wait(30)
        return real_load(self)

    monkeypatch.setattr(Line, "load", held_load)
    site = make_site(site3.session)
    site.set_source(site3.source(grids="AB"))
    try:
        with pytest.raises(AssertionError) as caught:
            wait_for_site(site, 300)
    finally:
        release.set()
    message = str(caught.value)
    assert "the site did not finish preparing in 300 ms" in message
    assert "active: True · preparing: 'A' · queue: ['B']" in message
    assert "engine A: running True · live task True" in message
    assert "grid A: preparing (0 of 4)" in message
    assert "grid B: queued" in message
    wait_for_site(site)  # released: it finishes


def test_the_busy_report_never_raises_on_a_disposed_site(site3, make_site):
    site = make_site(site3.session)
    site.set_source(site3.source(grids="A"))
    wait_for_site(site)
    site.dispose()
    report = site.busy_report()
    assert report.startswith("active: False · preparing: None · queue: []")
```

- [ ] **Step 2: Run them and see them fail**

Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py -k "busy_report or names_what_holds" -q`

Expected: FAIL, with an ImportError for `wait_for_site` or an AttributeError for `busy_report`.

- [ ] **Step 3: Implement** `SliceEngine.pending_tasks`, `SiteEngine.busy_report()` and
  `wait_for_site`, as the Interfaces block gives them.

- [ ] **Step 4: Run the two tests and see them pass.** Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Make every asserting site wait use `wait_for_site`**
  - In the three test files, replace each `assert <x>.wait_until_idle(N)` (with or without a
    message) with `wait_for_site(<x>, N)`. That includes `settle()` in
    `test_plugin_site_scope.py` (~line 116) and `prepared()` in `test_plugin_site_engine.py`
    (~line 81).
  - Leave the waits that don't assert alone. Those are the teardown ones (`make_site`'s
    `engine.wait_until_idle(20_000)`, `finally:` blocks).
  - Check with: `grep -n "assert .*wait_until_idle" packages/nsgeo-qgis/tests/qgis/test_plugin_site_{engine,scope,export}.py`.
    Expected: no output.

- [ ] **Step 6: Run the three files.**

Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py -q`

Expected: all pass, except a #196 flake if any. Note it and move on.

- [ ] **Step 7: Commit and push:** `test(site): a timed-out site wait names what holds it (#166)`.

> **Controller, after Task 1 lands:** start the "before" loop, as described under **The #166
> loop** at the end of this plan. Do it in a detached worktree at Task 1's commit, in the
> background, and carry on with Task 2.

---

