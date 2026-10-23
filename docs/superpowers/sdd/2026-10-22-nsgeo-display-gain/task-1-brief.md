### Task 1: Core: bypass several steps, remember the result, and the row envelope

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/stack.py` (`result_bypassing`, the mutators, `source` setter)
- Modify: `packages/nsgeo-core/src/nsgeo/render.py` (add `row_envelope`, add it to `__all__`)
- Test: `packages/nsgeo-core/tests/test_stack.py`, `packages/nsgeo-core/tests/test_render.py`, `packages/nsgeo-core/tests/test_real_files.py`

**Interfaces:**
- Produces: `StepStack.result_bypassing(self, *indices: int) -> Radargram`. What `result()` would be with every step in `indices` switched off. No indices returns `self.result()`. Any index out of range raises `IndexError` with the existing message, `f"step index {i} out of range (0..{len(self._entries) - 1})"`. Duplicates are allowed. The prefix before the smallest index comes from the intermediate cache, as today; the rest is run fresh, skipping the bypassed and the disabled steps.
- Produces: the bypass memo. `result_bypassing` returns the *same object* for the same index set until it is invalidated. It holds at most two index sets and drops the least recently used. `replace_step(i, step)` keeps the memo entries whose set contains `i` and drops the rest. The `source` setter, `append`, `insert`, `remove`, `move` and `set_enabled` drop everything. `cache_size` still counts only real intermediates.
- Produces: `nsgeo.render.row_envelope(data: np.ndarray, percentile: float, max_traces: int = 2048) -> np.ndarray`. For each row, the `percentile` (numpy's default linear method) of `|data[row, :]|` over the traces, as float64 with shape `(n_rows,)`. Above `max_traces` columns it uses the strided subset `data[:, ::ceil(n / max_traces)]`. Non-finite samples are excluded, and a row with no finite sample gives `0.0`, with no warning. `percentile` must be in `(0, 100]` and `max_traces >= 1`, else `ValueError`, matching `PercentileClip`.

- [ ] **Step 1: Write the failing stack tests** in `test_stack.py`, using the file's `stack_of` and `source` helpers. Curve points sit on the helper's 0–12.6 ns axis.

```python
CURVE = ("gain_curve", {"points": [[0.0, 0.0], [12.0, 12.0]]})

def test_result_bypassing_several_steps_skips_each_of_them():
    st = stack_of(CURVE, ("dewow", {"window_ns": 4.0}), CURVE, ("gain_agc", {"window_ns": 2.0}))
    expected = stack_of(("dewow", {"window_ns": 4.0}), ("gain_agc", {"window_ns": 2.0})).result()
    np.testing.assert_array_equal(st.result_bypassing(0, 2).data, expected.data)

def test_result_bypassing_nothing_is_the_result():
    st = stack_of(("dewow", {"window_ns": 4.0}))
    assert st.result_bypassing() is st.result()

def test_result_bypassing_rejects_any_out_of_range_index():
    with pytest.raises(IndexError, match="out of range"):
        stack_of(("dewow", {"window_ns": 4.0})).result_bypassing(0, 5)

def test_a_bypass_survives_replacing_a_bypassed_step():
    st = stack_of(("dewow", {"window_ns": 4.0}), CURVE, ("background_mean", {}))
    first = st.result_bypassing(1)
    st.replace_step(1, build_step("gain_curve", points=[[0.0, 0.0], [12.0, 30.0]]))
    assert st.result_bypassing(1) is first
```

`test_a_bypass_is_recomputed_after_any_other_change` is parametrised over seven ids, each a mutation of `st = stack_of(("dewow", {"window_ns": 4.0}), CURVE, ("background_mean", {}))` after `first = st.result_bypassing(1)`:

| id | mutation |
|---|---|
| `replace-other` | `st.replace_step(0, build_step("dewow", window_ns=2.0))` |
| `set_enabled` | `st.set_enabled(2, False)` |
| `append` | `st.append(build_step("gain_agc", window_ns=2.0))` |
| `insert` | `st.insert(0, build_step("dewow", window_ns=2.0))` |
| `remove` | `st.remove(2)` |
| `move` | `st.move(0, 2)` |
| `source` | `st.source = source(seed=1)` |

Each asserts `st.result_bypassing(1) is not first`, and that its data equals a fresh stack's: `StepStack.from_dicts(st.to_dicts())` with `.source = st.source`, then `.result_bypassing(1)`. For `remove` and `move`, index 1 must still exist.

`test_the_bypass_memo_holds_the_two_most_recent_sets`: `a = st.result_bypassing(1)`, `c = st.result_bypassing(0)`, then `assert st.result_bypassing(1) is a` (this refreshes `{1}`). Then `st.result_bypassing(2)`, `assert st.result_bypassing(1) is a`, and `assert st.result_bypassing(0) is not c`.

- [ ] **Step 2: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_stack.py -q`. Expected: the new tests fail. Several-index calls fail with `TypeError: ... takes 2 positional arguments`, and the memo tests fail on `is`. The four existing `result_bypassing` tests still pass.

- [ ] **Step 3: Implement the generalised `result_bypassing` and its memo** in `stack.py`. Keep `self._bypassed: dict[frozenset[int], Radargram]` alongside `_cache`. A private `_drop_bypassed(keep: int | None = None)` is called from every mutator listed above: `keep` is the replaced index for `replace_step` and `None` everywhere else. Extend the docstring. The fresh suffix is still never written into `_cache`, because those intermediates belong to a chain the stack does not have. The memo keeps only each final result, and holds it while an edit confined to a bypassed step cannot change it, which is what a gain-curve drag needs.

- [ ] **Step 4: Run them and see them pass.** Same command. Expected: all pass, including the existing four bypass tests and `test_result_bypassing_reuses_the_prefix_and_leaves_the_real_chain_alone` (`cache_size == 1`).

- [ ] **Step 5: Write the failing envelope tests** in `test_render.py`.

```python
def test_row_envelope_is_the_per_row_percentile_of_magnitudes():
    x = np.random.default_rng(0).normal(size=(6, 50))
    np.testing.assert_array_equal(row_envelope(x, 90.0), np.percentile(np.abs(x), 90.0, axis=1))

def test_row_envelope_subsamples_wide_data_deterministically():
    x = np.random.default_rng(1).normal(size=(4, 5000))
    got = row_envelope(x, 99.0, max_traces=1000)
    np.testing.assert_array_equal(got, np.percentile(np.abs(x[:, ::5]), 99.0, axis=1))

def test_row_envelope_ignores_non_finite_samples_without_warning():
    x = np.ones((3, 4))
    x[0, 0], x[1, :] = np.inf, np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        got = row_envelope(x, 50.0)
    np.testing.assert_array_equal(got, [1.0, 0.0, 1.0])
```

`test_row_envelope_validates_its_arguments`: `percentile` 0.0 and 100.5, and `max_traces` 0, each raise `ValueError`.

In `test_real_files.py`, add `test_row_envelope_on_a_real_line_is_exact_below_the_cap`, parametrised over `FILES`. Process each file through `time_zero` (`mode="first_break", threshold=0.25`) and `dewow` (`window_ns=4.0`), assert `n_traces <= 2048`, and assert `row_envelope(rg.data, 99.0)` equals `np.percentile(np.abs(rg.data), 99.0, axis=1)` exactly.

- [ ] **Step 6: Run them and see them fail** with `ImportError: cannot import name 'row_envelope'`. Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py packages/nsgeo-core/tests/test_real_files.py -q`.

- [ ] **Step 7: Implement `row_envelope`** in `render.py`, and add it to `__all__` in sorted position. Take the magnitudes of the strided columns, set the non-finite ones to NaN, and use `np.nanpercentile` along axis 1, wrapping only the all-NaN case so it gives `0.0` with no `RuntimeWarning`. The docstring records why the cap is 2048. Every real line in the corpus is under it, so ordinary lines get an exact answer, and a strided subset measured up to 0.14 of the display limit off at stride 2 on a real line.

- [ ] **Step 8: Run the full core + pure command, lint and types.** Expected: everything passes. The real-data test must not skip.

- [ ] **Step 9: Commit and push.**

```bash
git add packages/nsgeo-core
git commit -m "feat(core): bypass several steps with a memo that survives a bypassed edit; row_envelope"
git push
```

---


---

# Plan-wide sections that bind this task (copied from the plan)

## Global Constraints

- Core stays numpy-only, with no Qt imports. `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` must stay green.
- `nsgeo.render.__all__` stays sorted (`test_public_api.py` checks it).
- The plugin imports Qt only through `qgis.PyQt`.
- Every slot connected to a signal, and every Qt-invoked override (`paintEvent` included), guards its own body and reports through `_log`, never raises. Read the module docstrings of `profile_dock.py` and `gain_strip.py` before touching either file.
- Which step is a gain curve is decided by the schema's `kind == "curve"`, never by the step's name. Which step is a time cutoff is decided by `kind == "time"` (`time_param_name`).
- Display gain is never recorded in a stack and nothing here changes what a project saves.
- Any profile without an enabled gain curve renders exactly as today, except while the time cutoff's row is selected (spec call 11).
- ruff 0.17.1 and mypy 2.4.0, as pinned in CI.

## Verification commands (exactly these)

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
- qgis: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh` (several minutes; run single files while iterating)
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`

The coordinator builds the worktree's `.venv` and `.venv-qgis` and symlinks the real DZT files into `packages/nsgeo-core/tests/data/local/` before Task 1, and records the baseline pass counts in the ledger. A real-data test that skips has validated nothing, so check the skip count.

