### Task 1: Scale and travel shift in the core and the survey file

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/placement.py`. Add the two fields after `label`, because positional construction up to `label` is used in tests. Add validation in `__post_init__`. Change the formula in `distance_along`, and explain both fields in the class docstring.
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`, in `_placement_to_dict` and `_placement_from_dict`. In `load_site`, wrap the `_placement_from_dict` call: `(KeyError, TypeError, ValueError)` becomes `ProjectError(f"invalid placement for line {entry['path']!r}: {exc}")`. The `ProjectError` that `_placement_from_dict` raises for an unknown type must still pass through unwrapped (`test_rejects_unknown_placement_type`).
- Test: `packages/nsgeo-core/tests/test_placement.py`, `packages/nsgeo-core/tests/test_project.py`

**Interfaces:**
- Produces: `GridPlacement(grid_id, axis, offset, start_along=0.0, direction=1, label=None, scale=1.0, travel_shift=0.0)`. It is frozen. `ValueError` unless `scale` is finite and > 0 and `travel_shift` is finite.

- [ ] **Step 1: Write the failing tests** in `test_placement.py`, using its `header` (60 traces/m) and `frames` fixtures:

```python
def test_scale_stretches_the_recorded_distance_from_the_start(header):
    d = GridPlacement("G", "y", 0.5, 1.0, scale=0.9).distance_along(120, header)
    assert d[0] == pytest.approx(1.0) and d[60] == pytest.approx(1.9)


def test_a_reversed_line_scales_toward_its_start(header):
    d = GridPlacement("G", "y", 0.5, 20.0, -1, scale=1.1).distance_along(120, header)
    assert d[0] == pytest.approx(20.0) and d[60] == pytest.approx(18.9)


def test_travel_shift_moves_every_trace_forward_along_its_own_direction(header):
    fwd = GridPlacement("G", "y", 0.5, 0.0, 1, travel_shift=0.24).distance_along(120, header)
    rev = GridPlacement("G", "y", 1.0, 20.0, -1, travel_shift=0.24).distance_along(120, header)
    assert (fwd[0], fwd[60]) == (pytest.approx(0.24), pytest.approx(1.24))
    assert (rev[0], rev[60]) == (pytest.approx(19.76), pytest.approx(18.76))


def test_the_shift_is_not_scaled(header):
    d = GridPlacement("G", "y", 0.5, scale=2.0, travel_shift=0.1).distance_along(120, header)
    assert d[60] == pytest.approx(2.1)


def test_the_defaults_place_exactly_as_before(header):
    d = GridPlacement("G", "y", 0.5, 3.5, -1).distance_along(120, header)
    assert np.array_equal(d, 3.5 - np.arange(120, dtype=float) / 60.0)


@pytest.mark.parametrize(
    "kw",
    [
        {"scale": 0.0},
        {"scale": -1.0},
        {"scale": float("nan")},
        {"scale": float("inf")},
        {"travel_shift": float("nan")},
        {"travel_shift": float("inf")},
    ],
)
def test_a_scale_or_shift_that_cannot_place_a_line_is_refused(kw):
    with pytest.raises(ValueError):
        GridPlacement("G", "y", 0.5, **kw)


def test_trace_coords_use_the_corrected_distance(header, frames):
    pl = GridPlacement("G", "x", 2.0, 1.0, 1, scale=1.5, travel_shift=0.2)
    xy = pl.trace_coords(60, header, frames)
    assert xy[:, 0] == pytest.approx(pl.distance_along(60, header))


def test_a_real_line_fitted_to_its_grid_ends_on_both_edges():
    """FILE__008 is the campus line that runs 11.10 m on its 10 m grid (#3)."""
    path = next((p for p in CAMPUS_LINES if p.stem == "FILE__008"), None)
    if path is None:
        pytest.skip("real campus data not present")
    h = read_header(path)
    n = trace_count(path)
    scale = 10.0 / ((n - 1) / h.traces_per_metre)
    fwd = GridPlacement("G", "y", 0.25, 0.0, 1, scale=scale).distance_along(n, h)
    rev = GridPlacement("G", "y", 0.75, 10.0, -1, scale=scale).distance_along(n, h)
    assert (fwd[0], fwd[-1]) == (pytest.approx(0.0), pytest.approx(10.0, abs=1e-9))
    assert (rev[0], rev[-1]) == (pytest.approx(10.0), pytest.approx(0.0, abs=1e-9))
    assert h.traces_per_metre == pytest.approx(60.0)  # the header stays as recorded
```

  Imports to add: `from nsgeo.io import trace_count` and `from tests.real_data import CAMPUS_LINES`.

  Then, in `test_project.py`, using its `site` fixture:

```python
def test_scale_and_travel_shift_round_trip(tmp_path, site):
    site.lines[1] = dataclasses.replace(
        site.lines[1],
        placement=dataclasses.replace(site.lines[1].placement, scale=0.9542, travel_shift=0.24),
    )
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    assert back.lines[1].placement == site.lines[1].placement
    assert back.lines[0].placement.scale == 1.0 and back.lines[0].placement.travel_shift == 0.0


def test_a_line_without_corrections_writes_neither_key(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    for entry in json.loads(out.read_text())["lines"]:
        assert "scale" not in entry["placement"] and "travel_shift" not in entry["placement"]


@pytest.mark.parametrize("field,value", [("scale", 0), ("scale", "x"), ("travel_shift", None)])
def test_a_bad_scale_in_the_file_is_a_project_error_naming_the_line(tmp_path, site, field, value):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["placement"][field] = value
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(out)
```

- [ ] **Step 2: Run the two test files and see the new tests fail.** Only the new tests should fail, with `TypeError: unexpected keyword argument 'scale'`, an assertion, or `ValueError` not being a `ProjectError`.
- [ ] **Step 3: Implement.**
  - Write `scale` only when `!= 1.0` and `travel_shift` only when `!= 0.0`, compared exactly (call 13).
  - Read both with `float(doc.get(..., default))`. `float(None)` raises `TypeError`, which `load_site` wraps.
- [ ] **Step 4: Run core + pure. Everything passes, and the skip count is 5.** Then run lint and types.
- [ ] **Step 5: Commit** `feat(core): a placement's scale and travel shift (#3, #47)`, then push.

---

