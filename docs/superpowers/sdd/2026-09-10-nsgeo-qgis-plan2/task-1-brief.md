### Task 1: Parameter schema on every step

Resolves the spec §7 deviation recorded in the Plan 1 follow-ups. Each registered step declares its parameters as `ParamSpec` records; the plugin builds forms from them and never names a step. Also moves `GainCurve`'s two-point check into the constructor and makes `load_site` report an invalid stack as a `ProjectError`.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py`
- Modify: `packages/nsgeo-core/src/nsgeo/processing/timezero.py`, `dewow.py`, `gain.py`, `bandpass.py`, `background.py`
- Modify: `packages/nsgeo-core/src/nsgeo/processing/__init__.py`
- Modify: `packages/nsgeo-core/src/nsgeo/project.py:150-160` (the `"stack" in entry` branch)
- Create: `packages/nsgeo-core/tests/test_schema.py`

**Interfaces:**
- Consumes: `register`, `build_step`, `get_step`, `available_steps` (Plan 1)
- Produces: `REQUIRED` sentinel; `ParamSpec(name, kind, label, default, unit=None, min=None, max=None, choices=(), help="")` with `.required` property and `KINDS = ("float", "int", "choice", "curve")`; `Step.schema() -> tuple[ParamSpec, ...]` classmethod on every step; `default_params(name) -> dict[str, Any]`; `required_params(name) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_schema.py`:

```python
"""Every step declares a schema the UI can build widgets from.

The plugin must never name a step. It enumerates the registry, reads each
step's schema, and builds a form. These tests are what make that safe.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from nsgeo.processing import StepStack  # noqa: F401  (registers every step)
from nsgeo.processing.base import (
    REQUIRED,
    ParamSpec,
    Radargram,
    available_steps,
    build_step,
    default_params,
    get_step,
    required_params,
)
from nsgeo.project import ProjectError, load_site

from tests.synthetic import write_dzt


def _placeholder(spec: ParamSpec):
    """Any value acceptable to the constructor, so `params` can be compared."""
    if spec.kind == "float":
        return 1.0
    if spec.kind == "int":
        return 1
    if spec.kind == "choice":
        return spec.choices[0]
    return [[0.0, 0.0], [10.0, 0.0]]  # curve


@pytest.mark.parametrize("name", available_steps())
def test_schema_names_match_params_keys_in_order(name):
    specs = get_step(name).schema()
    assert all(isinstance(s, ParamSpec) for s in specs)
    step = build_step(name, **{s.name: _placeholder(s) for s in specs})
    assert list(step.params) == [s.name for s in specs]


@pytest.mark.parametrize("name", available_steps())
def test_non_required_defaults_build_and_apply(name):
    if required_params(name):
        pytest.skip(f"{name} has required parameters by design")
    rng = np.random.default_rng(0)
    rg = Radargram(data=rng.normal(size=(64, 32)), dt_ns=0.2, t0_ns=-11.0)
    out = build_step(name, **default_params(name)).apply(rg)
    assert isinstance(out, Radargram)


def test_only_the_two_known_steps_have_required_params():
    """Do not invent default passband frequencies; the identity curve is the
    front end's job. Nothing else may become required by accident."""
    req = {n: required_params(n) for n in available_steps() if required_params(n)}
    assert req == {"bandpass": ("low_mhz", "high_mhz"), "gain_curve": ("points",)}


@pytest.mark.parametrize("name", available_steps())
def test_defaults_respect_declared_bounds_and_choices(name):
    for s in get_step(name).schema():
        if s.required:
            continue
        if s.kind == "choice":
            assert s.default in s.choices
        if s.kind in ("float", "int"):
            if s.min is not None:
                assert s.default >= s.min
            if s.max is not None:
                assert s.default <= s.max


def test_choice_kind_requires_choices_and_others_forbid_them():
    with pytest.raises(ValueError, match="choices"):
        ParamSpec(name="mode", kind="choice", label="Mode", default="a")
    with pytest.raises(ValueError, match="choices"):
        ParamSpec(name="w", kind="float", label="W", default=1.0, choices=("a",))


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="kind"):
        ParamSpec(name="x", kind="string", label="X", default="")


def test_required_sentinel_is_recognisable():
    spec = ParamSpec(name="low_mhz", kind="float", label="Low", default=REQUIRED)
    assert spec.required
    assert repr(REQUIRED) == "REQUIRED"
    assert not ParamSpec(name="w", kind="float", label="W", default=1.0).required


def test_default_params_omits_required_ones():
    assert set(default_params("bandpass")) == {"taper_frac"}
    assert default_params("gain_curve") == {}
    assert default_params("background_mean") == {}


def test_gain_curve_rejects_fewer_than_two_points_at_construction():
    with pytest.raises(ValueError, match="two"):
        build_step("gain_curve", points=[[0.0, 0.0]])


def test_gain_curve_rejects_non_finite_points_at_construction():
    with pytest.raises(ValueError, match="finite"):
        build_step("gain_curve", points=[[0.0, 0.0], [10.0, float("nan")]])


def test_load_site_reports_an_invalid_stack_as_project_error(tmp_path):
    dzt = tmp_path / "L0.DZT"
    write_dzt(dzt, np.zeros((512, 20), dtype=np.int32))
    doc = {
        "schema_version": 1,
        "grids": [
            {
                "id": "G",
                "origin": [0.0, 0.0],
                "azimuth": 0.0,
                "size_x": 10.0,
                "size_y": 10.0,
                "crs": "EPSG:32616",
                "default_spacing": 0.5,
            }
        ],
        "lines": [
            {
                "path": "L0.DZT",
                "placement": {"type": "grid", "grid_id": "G", "axis": "y", "offset": 0.0},
                "stack": [{"step": "gain_curve", "params": {"points": [[0.0, 0.0]]}}],
            }
        ],
    }
    (tmp_path / "survey.nsgeo.json").write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(tmp_path / "survey.nsgeo.json")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'REQUIRED'`

- [ ] **Step 3: Add `REQUIRED`, `ParamSpec`, and the helpers to `base.py`**

In `packages/nsgeo-core/src/nsgeo/processing/base.py`, change the imports and add the following after `Radargram` and before `class Step(Protocol)`:

```python
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from typing import Any, ClassVar, Final, Protocol
```

```python
class _Required:
    """Sentinel default meaning: the UI must ask; there is no safe value."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "REQUIRED"


REQUIRED: Final = _Required()


@dataclass(frozen=True)
class ParamSpec:
    """One parameter of a step, declared so a front end can build a widget.

    `kind` decides the widget: float and int are numeric entries with optional
    bounds and a unit, choice is a combo box over `choices`, curve is the gain
    curve editor. `default` is a value or REQUIRED.
    """

    KINDS: ClassVar[tuple[str, ...]] = ("float", "int", "choice", "curve")

    name: str
    kind: str
    label: str
    default: Any
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = field(default=())
    help: str = ""

    def __post_init__(self) -> None:
        if self.kind not in self.KINDS:
            raise ValueError(f"unknown param kind {self.kind!r}; expected one of {self.KINDS}")
        if self.kind == "choice" and not self.choices:
            raise ValueError(f"param {self.name!r} is a choice but declares no choices")
        if self.kind != "choice" and self.choices:
            raise ValueError(f"param {self.name!r} is {self.kind!r} but declares choices")
        if self.kind == "choice" and self.default is not REQUIRED and self.default not in self.choices:
            raise ValueError(f"param {self.name!r} default {self.default!r} is not in choices")

    @property
    def required(self) -> bool:
        return self.default is REQUIRED
```

Extend the `Step` protocol:

```python
class Step(Protocol):
    """A pure function of (parameters, radargram). No I/O, no hidden state."""

    name: str

    @property
    def params(self) -> dict[str, Any]: ...

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]: ...

    def apply(self, rg: Radargram) -> Radargram: ...
```

Append after `build_step`:

```python
def default_params(name: str) -> dict[str, Any]:
    """Constructor kwargs for every parameter that has a real default."""
    return {s.name: s.default for s in get_step(name).schema() if not s.required}


def required_params(name: str) -> tuple[str, ...]:
    """Parameters the UI must collect before the step can be built."""
    return tuple(s.name for s in get_step(name).schema() if s.required)
```

- [ ] **Step 4: Declare schemas on the nine steps**

`timezero.py`, inside `TimeZero` (add the import `from nsgeo.processing.base import ParamSpec, Radargram, register`):

```python
    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(
                name="mode",
                kind="choice",
                label="Mode",
                default="first_break",
                choices=("first_break", "sample"),
                help="Pick the first arrival automatically, or crop at a fixed sample.",
            ),
            ParamSpec(name="sample", kind="int", label="Sample", default=0, min=0,
                      help="Used when mode is 'sample'."),
            ParamSpec(name="threshold", kind="float", label="Threshold", default=0.2,
                      min=0.0, max=1.0, help="Fraction of the peak mean amplitude."),
        )
```

`dewow.py`, inside `Dewow`:

```python
    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(name="window_ns", kind="float", label="Window", default=4.0, unit="ns",
                      min=0.0, help="Running-mean window; must exceed one sample interval."),
        )
```

`gain.py`, inside `GainAgc`:

```python
    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(name="window_ns", kind="float", label="Window", default=20.0, unit="ns", min=0.0),
            ParamSpec(name="target", kind="float", label="Target RMS", default=1.0, min=0.0),
            ParamSpec(name="eps", kind="float", label="Epsilon", default=1e-12, min=0.0,
                      help="Guards all-zero traces at the start of a line."),
        )
```

inside `GainParametric`:

```python
    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(name="mode", kind="choice", label="Mode", default="exponential",
                      choices=("exponential", "power")),
            ParamSpec(name="alpha", kind="float", label="Alpha", default=0.05, unit="1/ns",
                      help="Exponential rate; used when mode is 'exponential'."),
            ParamSpec(name="exponent", kind="float", label="Exponent", default=1.0,
                      help="Used when mode is 'power'."),
        )
```

inside `GainCurve`, replace `__init__` and add `schema`:

```python
    def __init__(self, points: Sequence[Sequence[float]]) -> None:
        pts = [[float(t), float(db)] for t, db in points]
        if len(pts) < 2:
            raise ValueError("gain_curve needs at least two control points")
        if not all(math.isfinite(v) for p in pts for v in p):
            raise ValueError("gain_curve control points must be finite")
        self.points: list[list[float]] = pts

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(name="points", kind="curve", label="Gain curve", default=REQUIRED, unit="dB",
                      help="(two-way time ns, gain dB) control points on the viewer's time axis."),
        )
```

and remove the now-redundant `if len(self.points) < 2` check from `GainCurve.apply`. Add `import math` and import `REQUIRED, ParamSpec` from base.

`bandpass.py`, inside `Bandpass`:

```python
    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]:
        return (
            ParamSpec(name="low_mhz", kind="float", label="Low", default=REQUIRED, unit="MHz", min=0.0,
                      help="No default: a wrong passband silently filters real data."),
            ParamSpec(name="high_mhz", kind="float", label="High", default=REQUIRED, unit="MHz", min=0.0,
                      help="Must be below the Nyquist frequency of the radargram."),
            ParamSpec(name="taper_frac", kind="float", label="Taper", default=0.25, min=0.0,
                      help="Cosine taper width as a fraction of the passband."),
        )
```

`background.py`: `BackgroundMean.schema` returns `()`; `BackgroundSliding.schema` returns `(ParamSpec(name="window_traces", kind="int", label="Window", default=200, unit="traces", min=1),)`; `BackgroundSvd.schema` returns `(ParamSpec(name="n_components", kind="int", label="Components removed", default=1, min=0),)`.

Export the new names from `processing/__init__.py`: add `REQUIRED, ParamSpec, default_params, required_params` to the `from nsgeo.processing.base import (...)` block.

- [ ] **Step 5: Wrap stack errors in `load_site`**

In `packages/nsgeo-core/src/nsgeo/project.py`, replace

```python
        if "stack" in entry:
            stacks[entry["path"]] = StepStack.from_dicts(entry["stack"])
```

with

```python
        if "stack" in entry:
            try:
                stacks[entry["path"]] = StepStack.from_dicts(entry["stack"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProjectError(
                    f"invalid processing stack for line {entry['path']!r}: {exc}"
                ) from exc
```

- [ ] **Step 6: Run the full core suite**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests -q`
Expected: all PASS (196 existing + the new schema tests; `test_curve_requires_at_least_two_points` still passes because construction happens inside its `raises` block).

- [ ] **Step 7: Lint, format, type-check**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo`
Expected: clean. If ruff wants `ClassVar` imported differently or reflows the `ParamSpec(...)` calls, accept its autofix (`ruff format .`).

- [ ] **Step 8: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: declare a parameter schema on every processing step

Resolves the spec §7 deviation from Plan 1: Step.params returned current
values, so a front end could not build widgets or construct bandpass and
gain_curve. Each step now declares ParamSpec records; the two steps with
no safe default mark those parameters REQUIRED rather than inventing
numbers. GainCurve validates at construction so an invalid curve can no
longer be serialised, and load_site reports a bad stack as ProjectError."
```

---

