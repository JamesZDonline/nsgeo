# Line Identity (#89) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Line` equality and hash become the object's own (`eq=False`), so a `Line` can be
hashed again and no field type can break `==`.

**Architecture:** One decorator change on `Line` in `nsgeo.model.survey`, the same choice
`Profile` already makes in that module. Session code is unchanged: `list.index` finds the object
it is given.

**Tech Stack:** Python 3.12 dataclasses, pytest.

**Spec:** `docs/superpowers/specs/2026-11-12-nsgeo-line-identity-design.md`

## Global Constraints

- `Line` stays `frozen=True`. No field, field order or default changes.
- No change to `session.py`, `project.py` or any lookup by key.

## Review Focus

- A line holding stored fits (a non-empty `velocity_fits` dict) must hash. The test stores a fit,
  so it exercises the field that broke hashing rather than only the default.
- `site.lines.index(line)` with an equal-content copy earlier in the list must return the
  position of `line` itself. Today's value equality returns the copy's position.

---

### Task 1: Identity equality on `Line`

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (`class Line`, decorator + docstring)
- Test: `packages/nsgeo-core/tests/test_survey.py` (after `test_profile_is_hashable_with_identity_equality`)
- Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_dialog.py::test_cancel_changes_nothing`

**Interfaces:**
- Produces: `Line.__eq__`/`__hash__` inherited from `object` (identity).

- [ ] **Step 1: Write the failing tests** in `test_survey.py`

```python
def test_a_line_with_stored_fits_is_hashable_with_identity_equality(tmp_path):
    line = dataclasses.replace(_line(tmp_path), velocity_fits={"fit-1": _fit()})
    assert line == line
    assert hash(line) == hash(line)
    assert len({line, line}) == 1
    assert {line: "x"}[line] == "x"
    assert line != dataclasses.replace(line)  # same fields, another object


def test_index_finds_the_line_it_is_given_not_an_equal_copy(tmp_path):
    line = _line(tmp_path)
    copy = dataclasses.replace(line)
    site = Site(lines=[copy, line])
    assert site.lines.index(line) == 1
```

`_fit()` is a module helper returning a `StoredFit` (values as in `test_project.py:440`).

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_survey.py -q -k "stored_fits or equal_copy"`
Expected: 2 failed: `TypeError: unhashable type: 'dict'`, and `index` returning 0.

- [ ] **Step 3: `@dataclass(frozen=True, eq=False)` on `Line`**, docstring stating: equality and
  hash are identity; across saves a line is named by its file (`project.line_key`); comparing
  two lines' contents is a test concern, done field by field.

- [ ] **Step 4: Run `test_survey.py`, then the core and pure tiers**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q`
Expected: all pass.

- [ ] **Step 5: Add `assert s.line_for_key(key) is before`** to `test_cancel_changes_nothing`
  (keeping the `==` line), then run that file with `.venv-qgis` from the main checkout, with
  `PYTHONPATH` set to the worktree's `packages/nsgeo-core/src` and `packages/nsgeo-qgis`.
  Expected: pass, and `nsgeo.__file__` names the worktree.

- [ ] **Step 6: ruff, ruff format, mypy, commit, push.** CI runs the full matrix.
