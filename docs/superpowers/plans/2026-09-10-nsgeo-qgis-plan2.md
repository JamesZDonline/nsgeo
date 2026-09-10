# nsgeo QGIS Plugin — Plan 2 (M4–M6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put real GPR data on the QGIS map and on screen, processable through the core's step stack: schema-driven parameter forms, a site GeoPackage with lines on the canvas, a numpy→QImage profile viewer with display gain, and the processing dock. Ends at M6 (no map↔profile cursor link yet; that is Plan 3).

**Architecture:** Thick core, thin plugin. Four numpy-only modules join the core (`processing.base` schema, `render`, `velocity`, `io.dzx`) and are tested on the normal matrix. The plugin `nsgeo_qgis` holds one `SiteSession` (all survey state, Qt signals on every change), a `SiteLayers` object that mirrors the session into a per-site GeoPackage through the loaded layers' providers, Qt-free `lookup` functions, and widgets that read from the session and never hold survey state. The profile viewer is a custom `QWidget` driven by a pure `ViewTransform`.

**Tech Stack:** Python 3.9+ core (numpy only); plugin on QGIS ≥ 3.40 via `qgis.PyQt` (Qt5 and Qt6 compatible), pytest with an offscreen `QgsApplication` fixture, ruff, mypy, GitHub Actions with a `qgis/qgis:ltr` container job.

**Spec:** `docs/superpowers/specs/2026-09-10-nsgeo-qgis-plugin-design.md` (this plan) and `docs/superpowers/specs/2026-09-10-nsgeo-gpr-qgis-design.md` (the v1 design it extends). Read the plugin spec's §2 (decisions), §3 (core additions), §4 (plugin architecture), §5 (UI) before starting any task.

## Global Constraints

Every task's requirements implicitly include these. Copied from the specs and the Plan 1 follow-ups.

- **Core is numpy-only.** `packages/nsgeo-core/tests/test_boundary.py` fails the build on any module-level import of `qgis`, `PyQt5`, `PyQt6`, `PySide2`, `PySide6`, `matplotlib`, or `scipy` under `src/nsgeo`. New core modules (`render.py`, `velocity.py`, `io/dzx.py`) are covered automatically.
- **Plugin contains no signal processing.** It may import from `nsgeo.processing` only `StepStack`, `build_step`, `available_steps`, `get_step`, `Radargram`, `ParamSpec`, `REQUIRED`, `default_params`, `required_params`. Task 5's boundary test enforces this.
- **Qt5 and Qt6 compatible plugin code.** Every Qt import goes through `qgis.PyQt` (never `PyQt5`/`PyQt6`). Enums are always scoped: `Qt.AlignmentFlag.AlignLeft`, `QImage.Format.Format_RGB888`, `Qt.MouseButton.LeftButton`. Mouse positions go through `nsgeo_qgis/qtcompat.py` (`event_pos`) because Qt6 renamed `pos()` to `position()`. `metadata.txt` declares `qgisMinimumVersion=3.40` and `supportsQt6=True`.
- **Python 3.9 floor, `from __future__ import annotations` in every module.** `X | Y` and builtin generics are fine in annotations, forbidden anywhere evaluated at runtime (`isinstance`, module-level aliases, `dataclasses.field` defaults). Follow ruff's `UP` autofixes; never add `# noqa: UP`.
- **mypy targets 3.12** (numpy ≥ 2 stubs). Run with `--config-file packages/nsgeo-core/pyproject.toml`. The CI 3.9 matrix job is the real 3.9 guard.
- **Always build radargrams with `Radargram.from_profile(profile)`** (int32 → float). Never `Radargram(data=profile.data, ...)`.
- **Never mutate a step in place.** The only stack-editing path is `SiteSession.replace_step(i, build_step(name, **params))` and its siblings, each of which emits `stack_changed`.
- **`Site.stacks` keys are relative POSIX paths from the JSON's directory** (absolute POSIX for out-of-tree files saved with `allow_absolute=True`). Compute them with `nsgeo.project._line_key(line.path, root, allow_absolute=...)`.
- **`StepStack.difference(i)` raises `ValueError` for sample-count-changing steps** (`time_zero`). Catch it; never pre-empt with step-name checks.
- **Nothing processes automatically.** A stack starts empty. Display gain (clip percentile, colormap) is not a processing step and is never recorded in a stack.
- **Default colormap: greyscale, black = high, bipolar symmetric about zero** (`"grey_black_high"`).
- **Do not invent default passband frequencies.** `bandpass.low_mhz` and `bandpass.high_mhz` are `REQUIRED`. `gain_curve.points` is `REQUIRED`, seeded by the front end with the identity (two points at 0 dB spanning the current time axis), which is not a guess.
- **Real survey files are never committed.** They live in `packages/nsgeo-core/tests/data/local/` (gitignored by path and by extension). Tests that need them skip when absent. Real-data validation is primary; synthetic fixtures prove self-consistency only.
- **Verification set, from the worktree root:**
  ```bash
  .venv/bin/ruff check . && .venv/bin/ruff format --check . \
    && .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo \
    && .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q \
    && QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q
  ```
  `.venv` has the core installed editable (`pip install -e "./packages/nsgeo-core[dev]"`). `.venv-qgis` is `python3 -m venv --system-site-packages .venv-qgis` from `/usr/bin/python3` plus `pip install pytest`; it sees the system `qgis` bindings and numpy 1.26 and does **not** have `nsgeo` installed — the plugin's path shim (Task 5) puts `packages/nsgeo-core/src` on `sys.path`. Both venvs exist in the worktree already.
- **Commits:** one per task, message in Plan 1's style (`feat:`, `test:`, `docs:`; body explains *why*). Do not mandate a specific `Co-Authored-By` model name in subagent commits.
- **Licences:** core MIT, plugin GPL-2.0-or-later (its `LICENSE` already exists).

## Verified facts (do not re-derive)

| Fact | Value |
|---|---|
| Real files | Ten SIR-4000 `.DZT` (HS350US, 512 samples, int32, 60 traces/m, header 131,072 bytes, tag 2047, `position_ns` −11.09, `range_ns` 110.86, `dt_ns` 0.2165, `epsr` 14.0, Nyquist 2309 MHz); nine `.DZX` sidecars (FILE__010 has none) |
| Real trace counts | 001: 608 · 002: 625 · 003: 629 · 004: 658 · 005: 613 · 006: 608 · 007: 635 · 008: 666 · 009: 653 · 010: 606 |
| DZX | namespace `www.geophysical.com/DZX/1.02`; `GlobalProperties/dielectric` 14; `DataCollection/system` UtilityScanHS; `File/name`, `File/scanRange` "0,607"; FILE__007 has one `File/Profile/WayPt` (scan 634, mark User, name Mark1) |
| Offscreen QGIS | `QT_QPA_PLATFORM=offscreen`, `QgsApplication.setPrefixPath("/usr", True)`, `QgsApplication([], False).initQgis()` starts in ≈1 s from `/usr/bin/python3` (QGIS 3.44.7, Qt 5.15, PyQt 5.15) |
| Verified QGIS calls | `QgsVectorFileWriter.create(path, fields, wkb, crs, transformContext, opts)` with `opts.actionOnExistingFile = CreateOrOverwriteLayer` adds a table to an existing GeoPackage; `layer.dataProvider().truncate()` then `addFeatures()` refills; `layer.setReadOnly(True)`; `QgsField(name, QMetaType.Type.QString)` works on PyQt5 5.15; `QgsTask.fromFunction(desc, fn, on_finished=cb)` completes under offscreen; `QgsVertexMarker`, `QgsRubberBand`, `QDockWidget`, `QgsMapTool` construct offscreen; `from qgis.PyQt.QtWidgets import QAction` works (the shim re-exports it on Qt6) |
| Render timings | 512 × 6301 stitched radargram: normalise + LUT 120 ms with a full percentile, `QImage` build 1.2 ms, pan/zoom frame 3.1 ms at any zoom, 15.9 ms with smooth transform |
| Docker | `qgis/qgis:ltr` exists (3.44 today); `release-3_44` does not resolve |

---

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

### Task 2: `nsgeo.render` — amplitude to colour, numpy only

The display side of spec §8 without any Qt: a `Normalizer` protocol with percentile clip, colormap lookup tables, index and RGB conversion, and column decimation. The plugin wraps the byte array in a `QImage` and does nothing else.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/render.py`
- Create: `packages/nsgeo-core/tests/test_render.py`

**Interfaces:**
- Consumes: numpy only
- Produces: `Normalizer` protocol (`limit(data) -> float`); `PercentileClip(percentile=99.0, max_samples=200_000)`; `FixedRange(limit_value)`; `DEFAULT_COLORMAP = "grey_black_high"`; `colormap_names() -> list[str]`; `colormap(name) -> np.ndarray` (256, 3) uint8; `to_index8(data, limit) -> np.ndarray` uint8 (H, W); `to_rgb8(data, limit, lut) -> np.ndarray` uint8 (H, W, 3) C-contiguous; `decimate_columns(data, max_width) -> np.ndarray`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_render.py`:

```python
"""Amplitude-to-colour mapping. Display gain is not a processing step: these
functions change how numbers become pixels, never the numbers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.io.dzt import read_samples
from nsgeo.render import (
    DEFAULT_COLORMAP,
    FixedRange,
    PercentileClip,
    colormap,
    colormap_names,
    decimate_columns,
    to_index8,
    to_rgb8,
)

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []


def test_zero_maps_to_mid_grey_and_extremes_to_black_and_white():
    lut = colormap(DEFAULT_COLORMAP)
    idx = to_index8(np.array([[-2.0, -1.0, 0.0, 1.0, 2.0]]), limit=1.0)
    assert idx.tolist() == [[0, 0, 128, 255, 255]]
    rgb = lut[idx]
    assert rgb[0, 0].tolist() == [255, 255, 255]  # strong negative: white
    assert rgb[0, 4].tolist() == [0, 0, 0]  # strong positive: black
    assert 120 <= rgb[0, 2, 0] <= 135  # zero: mid grey


def test_index_is_symmetric_about_zero():
    idx = to_index8(np.array([[-0.5, 0.5]]), limit=1.0)
    assert int(idx[0, 0]) + int(idx[0, 1]) == 255


def test_to_rgb8_shape_dtype_and_contiguity():
    rgb = to_rgb8(np.zeros((4, 7)), limit=1.0, lut=colormap(DEFAULT_COLORMAP))
    assert rgb.shape == (4, 7, 3)
    assert rgb.dtype == np.uint8
    assert rgb.flags["C_CONTIGUOUS"]


def test_non_positive_limit_is_rejected():
    with pytest.raises(ValueError, match="limit"):
        to_index8(np.zeros((2, 2)), limit=0.0)


def test_every_colormap_is_a_256_by_3_uint8_table():
    assert DEFAULT_COLORMAP in colormap_names()
    for name in colormap_names():
        lut = colormap(name)
        assert lut.shape == (256, 3) and lut.dtype == np.uint8


def test_seismic_is_blue_white_red():
    lut = colormap("seismic")
    assert lut[0].tolist() == [0, 0, 255]
    assert lut[128].tolist() == [255, 255, 255]
    assert lut[255].tolist() == [255, 0, 0]


def test_unknown_colormap_names_the_options():
    with pytest.raises(KeyError, match="grey_black_high"):
        colormap("viridis")


def test_colormap_returns_a_copy():
    a = colormap(DEFAULT_COLORMAP)
    a[:] = 0
    assert colormap(DEFAULT_COLORMAP)[0, 0] == 255


def test_percentile_clip_is_symmetric_and_ignores_sign():
    data = np.concatenate([np.linspace(-10, 0, 500), np.linspace(0, 5, 500)]).reshape(10, 100)
    lim = PercentileClip(percentile=100.0).limit(data)
    assert lim == pytest.approx(10.0)


def test_percentile_clip_on_all_zero_data_returns_one():
    assert PercentileClip().limit(np.zeros((8, 8))) == 1.0


def test_percentile_clip_subsamples_large_arrays_deterministically():
    rng = np.random.default_rng(1)
    data = rng.normal(size=(512, 3000))
    clip = PercentileClip(percentile=99.0, max_samples=10_000)
    lim = clip.limit(data)
    step = int(np.ceil(data.size / 10_000))
    expected = float(np.percentile(np.abs(data.ravel()[::step]), 99.0))
    assert lim == expected
    full = float(np.percentile(np.abs(data), 99.0))
    assert abs(lim - full) / full < 0.05


def test_percentile_clip_validates_its_arguments():
    with pytest.raises(ValueError):
        PercentileClip(percentile=0.0)
    with pytest.raises(ValueError):
        PercentileClip(max_samples=0)


def test_fixed_range_is_a_drop_in_normalizer():
    assert FixedRange(3.5).limit(np.ones((2, 2))) == 3.5
    with pytest.raises(ValueError):
        FixedRange(0.0)


def test_decimate_columns_block_means_and_is_a_no_op_when_narrow():
    data = np.arange(20, dtype=float).reshape(1, 20)
    out = decimate_columns(data, max_width=5)
    assert out.shape == (1, 5)
    np.testing.assert_allclose(out[0], [1.5, 5.5, 9.5, 13.5, 17.5])
    same = decimate_columns(data, max_width=20)
    assert same is data


def test_decimate_columns_handles_a_ragged_last_block():
    data = np.arange(7, dtype=float).reshape(1, 7)
    out = decimate_columns(data, max_width=3)  # block of 3 -> widths 3, 3, 1
    np.testing.assert_allclose(out[0], [1.0, 4.0, 6.0])


@pytest.mark.skipif(not FILES, reason="no real DZT files in tests/data/local")
def test_real_file_renders_with_both_extremes_present():
    """The direct wave clips at 99 %, so a real raw render must reach both
    ends of the table; a render that does not is a broken normaliser."""
    data = read_samples(FILES[0])[0].astype(float)
    idx = to_index8(data, PercentileClip().limit(data))
    assert idx.shape == data.shape
    assert idx.min() == 0 and idx.max() == 255
    rgb = to_rgb8(data, PercentileClip().limit(data), colormap(DEFAULT_COLORMAP))
    assert rgb.shape == data.shape + (3,)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.render'`

- [ ] **Step 3: Implement `render.py`**

Create `packages/nsgeo-core/src/nsgeo/render.py`:

```python
"""Amplitude-to-colour mapping for front ends. numpy only.

Display gain is not a processing step. Clip percentile, colour range, and
colormap alter how amplitude maps to colour, not the data, so dragging them
remaps a lookup table and repaints with no recomputation, and none of it is
recorded in a stack. Front ends wrap the byte arrays produced here in their
own image type (QImage, PIL, ...) and do nothing else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

DEFAULT_COLORMAP = "grey_black_high"


class Normalizer(Protocol):
    """Chooses the symmetric amplitude limit that maps to the ends of the
    colour table. Bipolar data is always mapped symmetrically about zero."""

    def limit(self, data: np.ndarray) -> float: ...


@dataclass(frozen=True)
class PercentileClip:
    """Limit = the given percentile of |data|.

    Above `max_samples` values, a strided subsample is used. On a 512 x 6301
    radargram the full percentile costs about 120 ms; the subsample keeps a
    display-gain drag interactive and is deterministic for a given array.
    """

    percentile: float = 99.0
    max_samples: int = 200_000

    def __post_init__(self) -> None:
        if not 0.0 < self.percentile <= 100.0:
            raise ValueError(f"percentile must be in (0, 100], got {self.percentile}")
        if self.max_samples < 1:
            raise ValueError(f"max_samples must be >= 1, got {self.max_samples}")

    def limit(self, data: np.ndarray) -> float:
        flat = np.asarray(data, dtype=float).ravel()
        if flat.size > self.max_samples:
            flat = flat[:: int(math.ceil(flat.size / self.max_samples))]
        if flat.size == 0:
            return 1.0
        lim = float(np.percentile(np.abs(flat), self.percentile))
        return lim if lim > 0.0 else 1.0


@dataclass(frozen=True)
class FixedRange:
    """A user-chosen limit. Drop-in for PercentileClip."""

    limit_value: float

    def __post_init__(self) -> None:
        if not self.limit_value > 0.0:
            raise ValueError(f"limit_value must be positive, got {self.limit_value}")

    def limit(self, data: np.ndarray) -> float:
        return float(self.limit_value)


def _grey(black_high: bool) -> np.ndarray:
    ramp = np.linspace(255.0, 0.0, 256) if black_high else np.linspace(0.0, 255.0, 256)
    g = np.round(ramp).astype(np.uint8)
    return np.stack([g, g, g], axis=1)


def _seismic() -> np.ndarray:
    """Blue for negative, white at zero, red for positive."""
    t = np.linspace(-1.0, 1.0, 256)
    r = np.where(t < 0, 1.0 + t, 1.0)
    g = 1.0 - np.abs(t)
    b = np.where(t > 0, 1.0 - t, 1.0)
    return np.round(np.stack([r, g, b], axis=1) * 255.0).astype(np.uint8)


_COLORMAPS: dict[str, np.ndarray] = {
    "grey_black_high": _grey(black_high=True),
    "grey_white_high": _grey(black_high=False),
    "seismic": _seismic(),
}


def colormap_names() -> list[str]:
    return list(_COLORMAPS)


def colormap(name: str) -> np.ndarray:
    """A (256, 3) uint8 lookup table. Returns a copy."""
    try:
        return _COLORMAPS[name].copy()
    except KeyError:
        raise KeyError(f"unknown colormap {name!r}; available: {colormap_names()}") from None


def to_index8(data: np.ndarray, limit: float) -> np.ndarray:
    """Map amplitudes to 0..255 with -limit -> 0, 0 -> 128, +limit -> 255."""
    if not limit > 0.0:
        raise ValueError(f"limit must be positive, got {limit}")
    scaled = (np.asarray(data, dtype=float) / limit + 1.0) * 127.5
    return np.round(np.clip(scaled, 0.0, 255.0)).astype(np.uint8)


def to_rgb8(data: np.ndarray, limit: float, lut: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8, C-contiguous, ready to wrap as an RGB888 image."""
    lut = np.asarray(lut)
    if lut.shape != (256, 3) or lut.dtype != np.uint8:
        raise ValueError(f"lut must be a (256, 3) uint8 table, got {lut.shape} {lut.dtype}")
    return np.ascontiguousarray(lut[to_index8(data, limit)])


def decimate_columns(data: np.ndarray, max_width: int) -> np.ndarray:
    """Block-mean along the trace axis until there are at most `max_width`
    columns. Happens after processing, never before, so the view is a
    downsampled real result. Returns `data` itself when already narrow."""
    if max_width < 1:
        raise ValueError(f"max_width must be >= 1, got {max_width}")
    n = data.shape[1]
    if n <= max_width:
        return data
    block = int(math.ceil(n / max_width))
    n_blocks = int(math.ceil(n / block))
    padded = np.full((data.shape[0], n_blocks * block), np.nan)
    padded[:, :n] = data
    return np.nanmean(padded.reshape(data.shape[0], n_blocks, block), axis=2)
```

- [ ] **Step 4: Run tests, lint, mypy**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py packages/nsgeo-core/tests/test_boundary.py -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo`
Expected: all PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add nsgeo.render, numpy-only amplitude-to-colour mapping

Normaliser protocol with percentile clip (strided subsample above 200k
values so a display-gain drag stays interactive), colormap lookup tables
with greyscale black-high as the bipolar default, index/RGB conversion,
and column decimation after processing. Lives in the MIT core so a
future standalone front end can use it verbatim; the plugin only wraps
the byte array in a QImage."
```

---

### Task 3: `nsgeo.velocity` and velocity on `Grid` and `Line`

A layered velocity model stored per grid with an optional per-line override, per spec §3.3. The v1 UI exposes only the constant case, but the data shape is the list from day one so no schema migration is needed later.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/velocity.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/grid.py` (add `velocity` field)
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (add `Line.velocity`, `Line.open(..., velocity=None)`)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (serialise both)
- Create: `packages/nsgeo-core/tests/test_velocity.py`

**Interfaces:**
- Consumes: `Grid`, `Line`, `save_site`, `load_site`
- Produces: `VelocityModel(layers: tuple[tuple[float, float], ...])` with `constant(v)`, `from_dielectric(epsr)`, `depth_at(times_ns)`, `velocity_at(times_ns)`, `to_dict()`, `from_dict(doc)`, `is_constant`, `surface_velocity`; `C_M_PER_NS = 0.299792458`; `resolve_velocity(line, grid) -> VelocityModel`; `Grid.velocity: VelocityModel | None = None`; `Line.velocity: VelocityModel | None = None`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_velocity.py`:

```python
"""Layered velocity: boundaries in two-way time, depth by integration.

Depth is measured from time zero. Before a time_zero step a real SIR-4000
file (position -11.09 ns) therefore has negative depth at the top. That is
correct, and the last test pins it against a real header.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzt import read_header
from nsgeo.model.survey import Line, Site
from nsgeo.project import load_site, save_site
from nsgeo.velocity import C_M_PER_NS, VelocityModel, resolve_velocity

from tests.synthetic import write_dzt

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt") if DATA.exists() else []


def test_constant_velocity_depth_is_half_v_t():
    m = VelocityModel.constant(0.1)
    np.testing.assert_allclose(m.depth_at(np.array([0.0, 20.0, 40.0])), [0.0, 1.0, 2.0])
    assert m.is_constant
    assert m.surface_velocity == 0.1


def test_negative_time_gives_negative_depth():
    m = VelocityModel.constant(0.1)
    assert m.depth_at(np.array([-11.0]))[0] == pytest.approx(-0.55)


def test_from_dielectric_matches_c_over_sqrt_epsr():
    m = VelocityModel.from_dielectric(14.0)
    assert m.surface_velocity == pytest.approx(C_M_PER_NS / 14.0**0.5)
    assert m.surface_velocity == pytest.approx(0.0801, abs=1e-4)
    with pytest.raises(ValueError, match="dielectric"):
        VelocityModel.from_dielectric(0.0)


def test_two_layers_integrate_piecewise():
    m = VelocityModel(layers=((0.0, 0.1), (20.0, 0.05)))
    np.testing.assert_allclose(m.depth_at(np.array([0.0, 10.0, 20.0, 40.0])), [0.0, 0.5, 1.0, 1.5])
    np.testing.assert_allclose(m.velocity_at(np.array([-5.0, 5.0, 20.0, 99.0])), [0.1, 0.1, 0.05, 0.05])
    assert not m.is_constant


def test_depth_is_monotone_for_any_valid_model():
    m = VelocityModel(layers=((0.0, 0.12), (15.0, 0.07), (60.0, 0.09)))
    d = m.depth_at(np.linspace(-10, 120, 400))
    assert np.all(np.diff(d) > 0)


def test_validation():
    with pytest.raises(ValueError, match="at least one"):
        VelocityModel(layers=())
    with pytest.raises(ValueError, match="0 ns"):
        VelocityModel(layers=((5.0, 0.1),))
    with pytest.raises(ValueError, match="increase"):
        VelocityModel(layers=((0.0, 0.1), (0.0, 0.2)))
    with pytest.raises(ValueError, match="positive"):
        VelocityModel(layers=((0.0, -0.1),))
    with pytest.raises(ValueError, match="positive"):
        VelocityModel.constant(0.0)


def test_layers_are_normalised_to_floats_and_immutable():
    m = VelocityModel(layers=((0, 1), (10, 2)))
    assert m.layers == ((0.0, 1.0), (10.0, 2.0))
    with pytest.raises(AttributeError):
        m.layers = ()  # type: ignore[misc]


def test_dict_round_trip():
    m = VelocityModel(layers=((0.0, 0.1), (20.0, 0.05)))
    doc = m.to_dict()
    assert doc == {"layers": [{"top_ns": 0.0, "v_m_ns": 0.1}, {"top_ns": 20.0, "v_m_ns": 0.05}]}
    assert VelocityModel.from_dict(doc) == m


@pytest.fixture
def line_and_grid(tmp_path):
    p = tmp_path / "L0.DZT"
    write_dzt(p, np.zeros((512, 30), dtype=np.int32))  # synthetic header has epsr 14
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32616", 0.5)
    line = Line.open(p, GridPlacement(grid_id="G", axis="y", offset=0.0))
    return line, grid


def test_resolution_order_is_line_then_grid_then_header(line_and_grid):
    line, grid = line_and_grid
    header_v = VelocityModel.from_dielectric(14.0)
    assert resolve_velocity(line, grid) == header_v
    assert resolve_velocity(line, None) == header_v
    grid_v = VelocityModel.constant(0.09)
    from dataclasses import replace

    grid2 = replace(grid, velocity=grid_v)
    assert resolve_velocity(line, grid2) == grid_v
    line2 = replace(line, velocity=VelocityModel.constant(0.07))
    assert resolve_velocity(line2, grid2) == VelocityModel.constant(0.07)


def test_project_round_trips_velocities_and_tolerates_their_absence(tmp_path, line_and_grid):
    line, grid = line_and_grid
    from dataclasses import replace

    grid = replace(grid, velocity=VelocityModel(layers=((0.0, 0.1), (20.0, 0.05))))
    line = replace(line, velocity=VelocityModel.constant(0.07))
    out = tmp_path / "survey.nsgeo.json"
    save_site(Site(grids=[grid], lines=[line]), out)
    back = load_site(out)
    assert back.grids[0].velocity == grid.velocity
    assert back.lines[0].velocity == VelocityModel.constant(0.07)

    bare = Site(grids=[replace(grid, velocity=None)], lines=[replace(line, velocity=None)])
    save_site(bare, out)
    text = out.read_text()
    assert "velocity" not in text
    back = load_site(out)
    assert back.grids[0].velocity is None and back.lines[0].velocity is None


@pytest.mark.skipif(not FILES, reason="no real DZT files in tests/data/local")
def test_real_header_suggestion_puts_the_top_of_the_record_below_zero_depth():
    h = read_header(FILES[0])
    m = VelocityModel.from_dielectric(h.epsr)
    top = float(m.depth_at(np.array([h.position_ns]))[0])
    assert -0.46 < top < -0.43  # -11.09 ns at 0.0801 m/ns
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_velocity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.velocity'`

- [ ] **Step 3: Implement `velocity.py`**

Create `packages/nsgeo-core/src/nsgeo/velocity.py`:

```python
"""Layered velocity model: interval velocities bounded in two-way time.

Boundaries are in time because that is what is visible on a radargram; depth
is the derived quantity. A constant velocity is the one-layer case, which is
all the v1 UI exposes, but the shape is a list from the start so adding
layers later changes no file format.

Depth is measured from time zero. Times before zero (a real SIR-4000 file
starts at -11.09 ns) give negative depths, which is correct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

C_M_PER_NS = 0.299792458


@dataclass(frozen=True)
class VelocityModel:
    layers: tuple[tuple[float, float], ...]  # (top_ns, v_m_per_ns), tops increasing, first 0.0

    def __post_init__(self) -> None:
        if not self.layers:
            raise ValueError("a velocity model needs at least one layer")
        layers = tuple((float(t), float(v)) for t, v in self.layers)
        object.__setattr__(self, "layers", layers)
        tops = [t for t, _ in layers]
        if tops[0] != 0.0:
            raise ValueError(f"the first layer must start at 0 ns, got {tops[0]}")
        if any(b <= a for a, b in zip(tops, tops[1:])):
            raise ValueError(f"layer tops must strictly increase, got {tops}")
        if any(not (math.isfinite(v) and v > 0.0) for _, v in layers):
            raise ValueError("interval velocities must be positive and finite")

    @classmethod
    def constant(cls, v_m_per_ns: float) -> VelocityModel:
        return cls(layers=((0.0, v_m_per_ns),))

    @classmethod
    def from_dielectric(cls, epsr: float) -> VelocityModel:
        if not epsr > 0.0:
            raise ValueError(f"relative dielectric permittivity must be positive, got {epsr}")
        return cls.constant(C_M_PER_NS / math.sqrt(epsr))

    @property
    def is_constant(self) -> bool:
        return len(self.layers) == 1

    @property
    def surface_velocity(self) -> float:
        return self.layers[0][1]

    def _arrays(self) -> tuple[np.ndarray, np.ndarray]:
        tops = np.array([t for t, _ in self.layers], dtype=float)
        vs = np.array([v for _, v in self.layers], dtype=float)
        return tops, vs

    def _layer_index(self, tops: np.ndarray, times_ns: np.ndarray) -> np.ndarray:
        # Times below the first top belong to the first layer.
        return np.clip(np.searchsorted(tops, times_ns, side="right") - 1, 0, len(tops) - 1)

    def velocity_at(self, times_ns: np.ndarray) -> np.ndarray:
        tops, vs = self._arrays()
        return vs[self._layer_index(tops, np.asarray(times_ns, dtype=float))]

    def depth_at(self, times_ns: np.ndarray) -> np.ndarray:
        """Depth in metres: cumulative integral of v/2 over two-way time."""
        t = np.asarray(times_ns, dtype=float)
        tops, vs = self._arrays()
        depth_at_tops = np.concatenate([[0.0], np.cumsum(vs[:-1] / 2.0 * np.diff(tops))])
        idx = self._layer_index(tops, t)
        return depth_at_tops[idx] + vs[idx] / 2.0 * (t - tops[idx])

    def to_dict(self) -> dict[str, Any]:
        return {"layers": [{"top_ns": t, "v_m_ns": v} for t, v in self.layers]}

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> VelocityModel:
        return cls(layers=tuple((float(d["top_ns"]), float(d["v_m_ns"])) for d in doc["layers"]))


def resolve_velocity(line: Any, grid: Any) -> VelocityModel:
    """Line override, then the grid's model, then the header's dielectric.

    Duck-typed on `.velocity` and `.header.epsr` so this module imports
    nothing from the model package and cannot create an import cycle.
    """
    if getattr(line, "velocity", None) is not None:
        return line.velocity  # type: ignore[no-any-return]
    if grid is not None and getattr(grid, "velocity", None) is not None:
        return grid.velocity  # type: ignore[no-any-return]
    return VelocityModel.from_dielectric(line.header.epsr)
```

- [ ] **Step 4: Add the fields to `Grid` and `Line`, and serialise them**

`geometry/grid.py`: add `from nsgeo.velocity import VelocityModel` and, as the last field of `Grid`:

```python
    velocity: VelocityModel | None = None
```

`model/survey.py`: add `from nsgeo.velocity import VelocityModel`; add `velocity: VelocityModel | None = None` as the last field of `Line`; change `Line.open` to

```python
    @classmethod
    def open(
        cls, path: Path, placement: Placement, velocity: VelocityModel | None = None
    ) -> Line:
        """Read the header and derive the trace count. Reads 1024 bytes plus
        a stat, regardless of file size."""
        path = Path(path)
        header = read_header(path)
        return cls(
            path=path,
            header=header,
            placement=placement,
            n_traces=trace_count(path, header),
            velocity=velocity,
        )
```

`project.py`: import `VelocityModel`; in `_grid_to_dict` add `if grid.velocity is not None: doc["velocity"] = grid.velocity.to_dict()` (restructure the literal into a local `doc` first); in `_grid_from_dict` pass `velocity=VelocityModel.from_dict(doc["velocity"]) if "velocity" in doc else None`; in `save_site`'s line loop add `if line.velocity is not None: entry["velocity"] = line.velocity.to_dict()`; in `load_site` pass `velocity=VelocityModel.from_dict(entry["velocity"]) if "velocity" in entry else None` to `Line.open`.

- [ ] **Step 5: Run the full core suite, lint, mypy**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo`
Expected: all PASS, clean. Existing `Grid(...)` and `Line.open(...)` calls are unaffected because the new fields default to `None`.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add a layered velocity model, stored per grid with a line override

Grids are the unit of completed fieldwork and conditions change between
them, so velocity lives on the grid; a line may override it. The model is
a list of (two-way time, interval velocity) layers even though v1 only
exposes the constant case, so adding layers later needs no migration.
None means unset: the core never invents a velocity, the header's
dielectric is a suggestion the UI shows. Depth before time zero is
negative, pinned against a real header."
```

---

### Task 4: `nsgeo.io.dzx` — the GSSI sidecar

Reads the XML sidecar for the line name, scan range, dielectric, system, and user marks. Hints only; never geometric truth.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/io/dzx.py`
- Create: `packages/nsgeo-core/tests/test_dzx.py`

**Interfaces:**
- Consumes: stdlib `xml.etree.ElementTree`
- Produces: `DzxMark(scan: int, kind: str, name: str)`; `DzxInfo(name, scan_range, dielectric, system, marks)`; `DzxError`; `read_dzx(path) -> DzxInfo | None`; `sidecar_for(path) -> Path | None`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_dzx.py`:

```python
"""The .DZX sidecar: line name, scan range, dielectric, marks. Hints only."""

from __future__ import annotations

from pathlib import Path

import pytest
from nsgeo.io.dzx import DzxError, DzxInfo, DzxMark, read_dzx, sidecar_for

DATA = Path(__file__).parent / "data" / "local"
REAL = {p.stem: p for p in DATA.rglob("*") if p.suffix.lower() == ".dzt"} if DATA.exists() else {}

XML = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02">
  <GlobalProperties><dielectric>9</dielectric><unitsPerScan>0.016667</unitsPerScan></GlobalProperties>
  <DataCollection><system>UtilityScanHS</system><scanPerMeters>60.000000</scanPerMeters></DataCollection>
  <File>
    <scanRange>0,99</scanRange>
    <name>SYN_0001.DZT</name>
    <Profile>
      <scanRange>0,99</scanRange>
      <WayPt><scan>40</scan><mark>User</mark><name>Mark1</name></WayPt>
      <WayPt><scan>77</scan><mark>User</mark><name>Mark2</name></WayPt>
    </Profile>
  </File>
</DZX>
"""


def test_parses_a_synthetic_sidecar(tmp_path):
    dzt = tmp_path / "SYN_0001.DZT"
    dzt.write_bytes(b"\x00" * 1024)
    (tmp_path / "SYN_0001.DZX").write_text(XML)
    info = read_dzx(dzt)
    assert info == DzxInfo(
        name="SYN_0001.DZT",
        scan_range=(0, 99),
        dielectric=9.0,
        system="UtilityScanHS",
        marks=(DzxMark(40, "User", "Mark1"), DzxMark(77, "User", "Mark2")),
    )


def test_lowercase_extension_is_found(tmp_path):
    dzt = tmp_path / "a.dzt"
    dzt.write_bytes(b"")
    (tmp_path / "a.dzx").write_text(XML)
    assert sidecar_for(dzt) == tmp_path / "a.dzx"
    assert read_dzx(dzt) is not None


def test_missing_sidecar_returns_none(tmp_path):
    dzt = tmp_path / "lonely.DZT"
    dzt.write_bytes(b"")
    assert sidecar_for(dzt) is None
    assert read_dzx(dzt) is None


def test_path_may_point_at_the_sidecar_itself(tmp_path):
    side = tmp_path / "x.DZX"
    side.write_text(XML)
    assert read_dzx(side).name == "SYN_0001.DZT"


def test_malformed_xml_raises_dzx_error(tmp_path):
    side = tmp_path / "bad.DZX"
    side.write_text("<DZX><File>")
    with pytest.raises(DzxError, match="bad.DZX"):
        read_dzx(side)


def test_missing_elements_are_none_not_errors(tmp_path):
    side = tmp_path / "sparse.DZX"
    side.write_text('<DZX xmlns="www.geophysical.com/DZX/1.02"><File/></DZX>')
    info = read_dzx(side)
    assert info == DzxInfo(name=None, scan_range=None, dielectric=None, system=None, marks=())


@pytest.mark.skipif("FILE__001" not in REAL, reason="no real files")
def test_real_sidecar_without_marks():
    info = read_dzx(REAL["FILE__001"])
    assert info is not None
    assert info.name == "FILE__001.DZT"
    assert info.scan_range == (0, 607)
    assert info.dielectric == 14.0
    assert info.system == "UtilityScanHS"
    assert info.marks == ()


@pytest.mark.skipif("FILE__007" not in REAL, reason="no real files")
def test_real_sidecar_with_one_user_mark():
    info = read_dzx(REAL["FILE__007"])
    assert info is not None
    assert info.marks == (DzxMark(scan=634, kind="User", name="Mark1"),)


@pytest.mark.skipif("FILE__010" not in REAL, reason="no real files")
def test_real_file_without_sidecar():
    assert read_dzx(REAL["FILE__010"]) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_dzx.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.io.dzx'`

- [ ] **Step 3: Implement `dzx.py`**

Create `packages/nsgeo-core/src/nsgeo/io/dzx.py`:

```python
"""GSSI .DZX sidecar reader.

The sidecar is XML metadata written next to a .DZT: the line's file name,
scan range, dielectric setting, acquisition system, and user marks. Import
uses it for hints (label, dielectric suggestion, marks layer). Nothing here
is geometric truth, and a missing sidecar is normal, not an error.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class DzxError(Exception):
    """Raised when a sidecar exists but cannot be parsed."""


@dataclass(frozen=True)
class DzxMark:
    scan: int
    kind: str
    name: str


@dataclass(frozen=True)
class DzxInfo:
    name: str | None
    scan_range: tuple[int, int] | None
    dielectric: float | None
    system: str | None
    marks: tuple[DzxMark, ...]


def sidecar_for(path: str | Path) -> Path | None:
    """The .DZX beside a .DZT (either case), or the path itself if it is one."""
    path = Path(path)
    if path.suffix.lower() == ".dzx":
        return path if path.exists() else None
    for suffix in (".DZX", ".dzx"):
        candidate = path.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def _strip_namespaces(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _text(root: ET.Element, xpath: str) -> str | None:
    el = root.find(xpath)
    return el.text.strip() if el is not None and el.text else None


def read_dzx(path: str | Path) -> DzxInfo | None:
    """Parse the sidecar for `path`, or return None when there is none."""
    side = sidecar_for(path)
    if side is None:
        return None
    try:
        root = ET.parse(side).getroot()
    except ET.ParseError as exc:
        raise DzxError(f"{side.name} is not well-formed XML: {exc}") from exc
    _strip_namespaces(root)

    scan_range: tuple[int, int] | None = None
    raw_range = _text(root, "./File/scanRange")
    if raw_range:
        lo, hi = raw_range.split(",")
        scan_range = (int(lo), int(hi))

    raw_dielectric = _text(root, "./GlobalProperties/dielectric")
    marks = tuple(
        DzxMark(
            scan=int(_text(wp, "./scan") or 0),
            kind=_text(wp, "./mark") or "",
            name=_text(wp, "./name") or "",
        )
        for wp in root.findall("./File/Profile/WayPt")
    )
    return DzxInfo(
        name=_text(root, "./File/name"),
        scan_range=scan_range,
        dielectric=float(raw_dielectric) if raw_dielectric else None,
        system=_text(root, "./DataCollection/system"),
        marks=marks,
    )
```

- [ ] **Step 4: Run tests, lint, mypy**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo`
Expected: all PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: read the GSSI .DZX sidecar for import hints

Line name, scan range, dielectric, system, and user marks, parsed
namespace-agnostically. Verified against the nine real sidecars,
including FILE__007's single user mark. A missing sidecar is None, not
an error; a malformed one names the file."
```

---

### Task 5: Plugin skeleton, core path shim, boundary test, offscreen harness, CI

The first thing QGIS can load. Also the mechanical guards (plugin boundary test) and the test harness every later plugin task depends on. No docks yet.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/__init__.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/qtcompat.py`
- Create: `packages/nsgeo-qgis/tests/conftest.py`
- Create: `packages/nsgeo-qgis/tests/plugin_testing.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_plugin_shim.py`
- Create: `packages/nsgeo-qgis/tests/qgis/conftest.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`
- Create: `packages/nsgeo-qgis/scripts/dev_link.py`
- Create: `packages/nsgeo-qgis/README.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `.gitignore` (add `.venv-qgis/`)

**Interfaces:**
- Consumes: `nsgeo.__version__`
- Produces: `nsgeo_qgis.CORE_PATH: Path`; `nsgeo_qgis._find_core(package_dir: Path) -> Path`; `classFactory(iface)`; `NsgeoPlugin(iface)` with `initGui()`, `unload()`, `toolbar`, `session` (None until Task 6); `nsgeo_qgis.qtcompat.event_pos(event) -> QPointF`; `plugin_version() -> str`; test fixtures `qgis_app`, `fake_iface`, `REAL_DZT` (list), `synthetic_dzt(tmp_path, name, n_traces)` helper

**Test-module naming rule (matters):** the plugin `tests/` tree has **no `__init__.py`** files, so pytest imports its modules by basename. Every plugin test file must therefore have a name unique across the repo: prefix them `test_plugin_` (qgis tier) or `test_pure_`/`test_plugin_` (pure tier). Never create `packages/nsgeo-qgis/tests/test_boundary.py` — it collides with the core's. Shared helpers live in `tests/plugin_testing.py`, which the conftest puts on `sys.path`; tests import it as `from plugin_testing import ...` (relative imports do not work without packages).

- [ ] **Step 1: Write the failing pure tests**

Create `packages/nsgeo-qgis/tests/conftest.py`:

```python
"""Shared setup for the plugin tests.

Puts the plugin package, the core's test helpers, and this directory's
`plugin_testing` module on sys.path. Importing `nsgeo_qgis` runs its path
shim, which puts the core *source* on sys.path too, so these tests work in
`.venv-qgis` (no nsgeo installed) as well as in `.venv` (nsgeo editable).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_DIR = HERE.parent  # packages/nsgeo-qgis
CORE_DIR = PLUGIN_DIR.parent / "nsgeo-core"  # for `from tests.synthetic import write_dzt`
for p in (HERE, PLUGIN_DIR, CORE_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import nsgeo_qgis  # noqa: E402,F401  (runs the core path shim)
```

Create `packages/nsgeo-qgis/tests/plugin_testing.py`:

```python
"""Helpers shared by both plugin test tiers. Imported as `plugin_testing`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

CORE_DIR = Path(__file__).resolve().parent.parent.parent / "nsgeo-core"
LOCAL_DATA = CORE_DIR / "tests" / "data" / "local"
REAL_DZT = (
    sorted(p for p in LOCAL_DATA.rglob("*") if p.suffix.lower() == ".dzt")
    if LOCAL_DATA.exists()
    else []
)

needs_real_data = pytest.mark.skipif(not REAL_DZT, reason="no real DZT files in tests/data/local")


def synthetic_dzt(folder: Path, name: str, n_traces: int = 60, **kw) -> Path:
    """A small synthetic DZT with a visible pattern, written into `folder`."""
    from tests.synthetic import write_dzt

    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(abs(hash(name)) % (2**32))
    data = (rng.normal(size=(512, n_traces)) * 1e6).astype(np.int32)
    data[40:44, :] = 5_000_000  # a flat band, so background removal has something to remove
    path = folder / name
    write_dzt(path, data, **kw)
    return path
```

Create `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`:

```python
"""The plugin must contain no signal processing and no direct PyQt imports.

Direct `PyQt5`/`PyQt6` imports break on the other Qt major version; the
`qgis.PyQt` shim works on both. Importing processing internals would let
maths creep into widgets, which is the boundary the whole design rests on.
"""

from __future__ import annotations

import ast
from pathlib import Path

import nsgeo_qgis

SRC = Path(nsgeo_qgis.__file__).parent

FORBIDDEN_ROOTS = {"PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "scipy"}
ALLOWED_FROM_PROCESSING = {
    "StepStack",
    "build_step",
    "available_steps",
    "get_step",
    "Radargram",
    "ParamSpec",
    "REQUIRED",
    "default_params",
    "required_params",
}


def _py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "_vendor" not in p.parts)


def test_src_tree_is_actually_being_scanned() -> None:
    assert len(_py_files()) >= 2


def test_no_direct_qt_or_forbidden_imports() -> None:
    offenders = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            bad = set(names) & FORBIDDEN_ROOTS
            if bad:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {sorted(bad)}")
    assert not offenders, "forbidden imports:\n" + "\n".join(offenders)


def test_processing_is_used_only_through_its_public_surface() -> None:
    offenders = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "nsgeo.processing":
                    bad = {a.name for a in node.names} - ALLOWED_FROM_PROCESSING
                    if bad:
                        offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {sorted(bad)}")
                elif node.module.startswith("nsgeo.processing."):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {node.module}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("nsgeo.processing"):
                        offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: import {a.name}")
    assert not offenders, "processing internals imported by the plugin:\n" + "\n".join(offenders)


def test_package_init_imports_no_qgis_at_module_level() -> None:
    """The pure test tier and the zip's shim both import the package without
    a QGIS runtime. classFactory imports qgis lazily."""
    tree = ast.parse((SRC / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "qgis" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("qgis")
```

Create `packages/nsgeo-qgis/tests/pure/test_plugin_shim.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

import nsgeo_qgis
from nsgeo_qgis import _find_core, plugin_version


def test_core_path_points_at_a_real_nsgeo_package():
    assert (nsgeo_qgis.CORE_PATH / "nsgeo" / "__init__.py").is_file()
    import nsgeo

    assert Path(nsgeo.__file__).resolve().parent == (nsgeo_qgis.CORE_PATH / "nsgeo").resolve()


def test_vendored_core_wins_when_present(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    (pkg / "_vendor" / "nsgeo").mkdir(parents=True)
    (pkg / "_vendor" / "nsgeo" / "__init__.py").write_text("")
    assert _find_core(pkg) == pkg / "_vendor"


def test_sibling_source_tree_is_the_development_fallback(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    pkg.mkdir(parents=True)
    src = tmp_path / "packages" / "nsgeo-core" / "src"
    (src / "nsgeo").mkdir(parents=True)
    (src / "nsgeo" / "__init__.py").write_text("")
    assert _find_core(pkg) == src


def test_missing_core_names_both_places_it_looked(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    pkg.mkdir(parents=True)
    with pytest.raises(ImportError) as exc:
        _find_core(pkg)
    msg = str(exc.value)
    assert "_vendor" in msg and "nsgeo-core" in msg


def test_plugin_version_comes_from_metadata():
    v = plugin_version()
    assert v and v[0].isdigit()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis'`

- [ ] **Step 3: Create the package**

Create `packages/nsgeo-qgis/nsgeo_qgis/__init__.py`:

```python
"""nsgeo QGIS plugin entry point.

Two jobs, both before any qgis import: find the nsgeo core and put it on
sys.path, and expose classFactory for QGIS. The core is found in the
release zip's `_vendor/` first, then in the sibling development checkout
(`packages/nsgeo-core/src`, reached through the dev symlink's real path).
No `pip install` into the QGIS interpreter is ever needed.
"""

from __future__ import annotations

import configparser
import sys
from pathlib import Path
from typing import Any


def _find_core(package_dir: Path) -> Path:
    """The directory to put on sys.path so `import nsgeo` works."""
    vendored = package_dir / "_vendor"
    if (vendored / "nsgeo" / "__init__.py").is_file():
        return vendored
    sibling = package_dir.parent.parent / "nsgeo-core" / "src"
    if (sibling / "nsgeo" / "__init__.py").is_file():
        return sibling
    raise ImportError(
        "nsgeo core library not found. Looked in "
        f"{vendored} (release zip) and {sibling} (development checkout)."
    )


CORE_PATH = _find_core(Path(__file__).resolve().parent)
if str(CORE_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_PATH))


def plugin_version() -> str:
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).resolve().parent / "metadata.txt", encoding="utf-8")
    return cfg["general"]["version"]


def classFactory(iface: Any) -> Any:  # noqa: N802  (QGIS API name)
    from nsgeo_qgis.plugin import NsgeoPlugin

    return NsgeoPlugin(iface)
```

Create `packages/nsgeo-qgis/nsgeo_qgis/metadata.txt`:

```ini
[general]
name=nsgeo
qgisMinimumVersion=3.40
supportsQt6=True
description=Near-surface geophysics: GPR profiles in map context
about=Load GSSI DZT files, organise them into georeferenced grids, view and process radargrams, and navigate them from the QGIS map. Core library is numpy-only and vendored into this plugin.
version=0.1.0
author=James Zimmer-Dauphinee
email=james.r.zimmer-dauphinee@vanderbilt.edu
repository=https://github.com/JamesZDonline/nsgeo
tracker=https://github.com/JamesZDonline/nsgeo/issues
homepage=https://github.com/JamesZDonline/nsgeo
category=Plugins
tags=gpr,geophysics,archaeology,radar,near-surface
hasProcessingProvider=no
experimental=True
```

Create `packages/nsgeo-qgis/nsgeo_qgis/qtcompat.py`:

```python
"""The few places Qt5 and Qt6 differ for this plugin.

Everything else is handled by importing through `qgis.PyQt` and using
scoped enums. Keep this file tiny; if it grows, the design is leaking.
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import QPointF


def event_pos(event: Any) -> QPointF:
    """Local position of a mouse or wheel event on both Qt majors."""
    if hasattr(event, "position"):
        return QPointF(event.position())
    return QPointF(event.pos())
```

Create `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:

```python
"""The QGIS plugin object: builds the toolbar and docks, tears them down.

Holds no survey state. That lives in SiteSession (Task 6); widgets read
from it and never from each other.
"""

from __future__ import annotations

from typing import Any

import nsgeo
from qgis.core import Qgis
from qgis.PyQt.QtWidgets import QAction

from nsgeo_qgis import plugin_version

MENU = "&nsgeo"


class NsgeoPlugin:
    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.toolbar: Any = None
        self.actions: list[QAction] = []
        self.docks: list[Any] = []
        self.session: Any = None

    # QGIS calls these two.
    def initGui(self) -> None:  # noqa: N802
        self.toolbar = self.iface.addToolBar("nsgeo")
        self.toolbar.setObjectName("nsgeoToolBar")
        about = QAction("About nsgeo", self.iface.mainWindow())
        about.triggered.connect(self.show_about)
        self.iface.addPluginToMenu(MENU, about)
        self.actions.append(about)

    def unload(self) -> None:
        for dock in self.docks:
            self.iface.removeDockWidget(dock)
            dock.deleteLater()
        self.docks.clear()
        for action in self.actions:
            self.iface.removePluginMenu(MENU, action)
        self.actions.clear()
        if self.toolbar is not None:
            self.toolbar.setParent(None)
            self.toolbar.deleteLater()
            self.toolbar = None

    def show_about(self) -> None:
        self.iface.messageBar().pushMessage(
            "nsgeo",
            f"plugin {plugin_version()} · core {nsgeo.__version__}",
            Qgis.MessageLevel.Info,
            5,
        )
```

- [ ] **Step 4: Run the pure tests**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`
Expected: all PASS.

- [ ] **Step 5: Write the failing QGIS-tier test and its fixtures**

Create `packages/nsgeo-qgis/tests/qgis/conftest.py`:

```python
"""Offscreen QGIS for tests that construct widgets and layers.

Skips the whole directory when `qgis` is not importable, so the normal CI
matrix (no QGIS) stays green while `.venv-qgis` and the Docker job run it.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qgis_core = pytest.importorskip("qgis.core")


@pytest.fixture(scope="session")
def qgis_app():
    from qgis.core import QgsApplication

    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    yield app
    app.exitQgis()


class FakeIface:
    """The parts of QgisInterface the plugin touches."""

    def __init__(self) -> None:
        from qgis.gui import QgsMapCanvas, QgsMessageBar
        from qgis.PyQt.QtWidgets import QMainWindow

        self._main = QMainWindow()
        self._canvas = QgsMapCanvas(self._main)
        self._main.setCentralWidget(self._canvas)
        self._bar = QgsMessageBar(self._main)
        self.docks: list = []
        self.toolbars: list = []
        self.menu_actions: list = []

    def mainWindow(self):  # noqa: N802
        return self._main

    def mapCanvas(self):  # noqa: N802
        return self._canvas

    def messageBar(self):  # noqa: N802
        return self._bar

    def addToolBar(self, name):  # noqa: N802
        from qgis.PyQt.QtWidgets import QToolBar

        tb = QToolBar(name, self._main)
        self._main.addToolBar(tb)
        self.toolbars.append(tb)
        return tb

    def addDockWidget(self, area, dock):  # noqa: N802
        self._main.addDockWidget(area, dock)
        self.docks.append(dock)

    def removeDockWidget(self, dock):  # noqa: N802
        self._main.removeDockWidget(dock)
        if dock in self.docks:
            self.docks.remove(dock)

    def addPluginToMenu(self, name, action):  # noqa: N802
        self.menu_actions.append((name, action))

    def removePluginMenu(self, name, action):  # noqa: N802
        self.menu_actions.remove((name, action))


@pytest.fixture
def fake_iface(qgis_app):
    return FakeIface()
```

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`:

```python
from __future__ import annotations

import nsgeo_qgis


def test_class_factory_builds_a_plugin_that_adds_and_removes_its_ui(fake_iface):
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.toolbar is not None
    assert plugin.toolbar.objectName() == "nsgeoToolBar"
    assert [name for name, _ in fake_iface.menu_actions] == ["&nsgeo"]

    plugin.show_about()
    item = fake_iface.messageBar().currentItem()
    assert item is not None and "core" in item.text()

    plugin.unload()
    assert plugin.toolbar is None
    assert fake_iface.menu_actions == []
```

- [ ] **Step 6: Run the QGIS tier**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q`
Expected: pure tests PASS; `test_plugin_loads` PASS. Then confirm the skip path: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests -q` (no qgis) → the `qgis/` directory is skipped, pure tests pass.

- [ ] **Step 7: Dev link script and README**

Create `packages/nsgeo-qgis/scripts/dev_link.py`:

```python
"""Symlink nsgeo_qgis/ into the active QGIS profile's plugin directory.

Usage: python packages/nsgeo-qgis/scripts/dev_link.py [--profile NAME] [--remove]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PLUGIN_SRC = Path(__file__).resolve().parent.parent / "nsgeo_qgis"


def profile_plugins_dir(profile: str) -> Path:
    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ["APPDATA"]) / "QGIS" / "QGIS3"
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "QGIS" / "QGIS3"
    else:
        base = home / ".local" / "share" / "QGIS" / "QGIS3"
    return base / "profiles" / profile / "python" / "plugins"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="default")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    target = profile_plugins_dir(args.profile) / "nsgeo_qgis"
    if args.remove:
        if target.is_symlink():
            target.unlink()
            print(f"removed {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not target.is_symlink():
        print(f"refusing: {target} exists and is not a symlink", file=sys.stderr)
        return 1
    if target.is_symlink():
        target.unlink()
    os.symlink(PLUGIN_SRC, target, target_is_directory=True)
    print(f"{target} -> {PLUGIN_SRC}")
    print("Enable 'nsgeo' in QGIS: Plugins > Manage and Install Plugins > Installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `packages/nsgeo-qgis/README.md`:

````markdown
# nsgeo QGIS plugin

GPL-2.0-or-later. Consumes the MIT `nsgeo` core from `../nsgeo-core`; contains no
signal processing (a test enforces it).

## Development install

```bash
python packages/nsgeo-qgis/scripts/dev_link.py      # symlink into the QGIS profile
```

Then enable **nsgeo** in QGIS's plugin manager. The plugin finds the core source
through the symlink's real path; no `pip install` into QGIS's Python is needed.
Use the Plugin Reloader plugin after edits.

## Tests

Two tiers. `tests/pure` needs no QGIS and runs in the normal `.venv`. `tests/qgis`
needs the QGIS Python bindings and an offscreen display:

```bash
python3 -m venv --system-site-packages .venv-qgis     # from the interpreter QGIS uses
.venv-qgis/bin/pip install pytest
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q
```

The `qgis/` directory skips itself when `qgis` is not importable.
````

Add `.venv-qgis/` to `.gitignore` under the Python section (next to `.venv/`).

- [ ] **Step 8: CI**

In `.github/workflows/ci.yml`, add to the `test` job after the core pytest line:

```yaml
      - run: python -m pytest packages/nsgeo-qgis/tests/pure -v
```

and add a new job:

```yaml
  plugin-qgis:
    runs-on: ubuntu-latest
    container: qgis/qgis:ltr
    env:
      QT_QPA_PLATFORM: offscreen
      QGIS_PREFIX_PATH: /usr
    steps:
      - uses: actions/checkout@v4
      - run: |
          python3 -m pip --version || (apt-get update && apt-get install -y python3-pip)
          python3 -m pip install --break-system-packages pytest
      - run: python3 -m pytest packages/nsgeo-qgis/tests -v
```

- [ ] **Step 9: Lint and commit**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: clean (accept `ruff format .` reflows). ruff's `N` rules are not enabled, so `initGui`/`classFactory` need no `noqa` — remove the `# noqa: N802` comments if ruff reports them as unused (`RUF100` is not enabled either, so either way is fine; be consistent and drop them).

```bash
git add packages/nsgeo-qgis .github/workflows/ci.yml .gitignore
git commit -m "feat: QGIS plugin skeleton with core path shim and offscreen test harness

classFactory plus a shim that finds the core in _vendor/ (release zip) or
the sibling source tree (dev symlink), so nothing is pip-installed into
QGIS's Python. A plugin boundary test forbids direct PyQt imports and any
use of nsgeo.processing beyond its public surface. Tests run in two
tiers: pure (normal matrix) and offscreen QGIS (.venv-qgis locally,
qgis/qgis:ltr container in CI)."
```

**Manual checkpoint (2 minutes):** `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py`, start QGIS, enable nsgeo, confirm the toolbar appears and Plugins ▸ nsgeo ▸ About pushes a message naming both versions. If QGIS refuses to load the plugin, the error dialog shows the shim's message or a traceback; fix before continuing.

---

### Task 6: `SiteSession` — the one place survey state lives

A `QObject` that owns the `Site`, its paths, per-line stacks, the current line and trace, and emits a signal on every change. Widgets read from it and never from each other. Also the only legal path for stack mutation.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/session.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`

**Interfaces:**
- Consumes: `Site`, `Line`, `Grid`, `Profile`, `StepStack`, `Radargram.from_profile`, `load_site`, `save_site`, `_line_key`, `resolve_velocity`
- Produces: `SiteSession(parent=None)` with signals `site_opened()`, `site_closed()`, `dirty_changed(bool)`, `grids_changed()`, `lines_changed()`, `line_opened(str)` (`""` = none), `line_loaded(str)`, `trace_changed(str, int)`, `selection_changed(str, int, int)` (`-1, -1` = cleared), `stack_changed(str)`, `picks_changed()`; properties `site`, `json_path`, `gpkg_path`, `site_name`, `root`, `is_open`, `dirty`, `current_key`, `current_trace`, `selection`; methods `new_site(folder)`, `open_site(json_path)`, `save(allow_absolute=None)`, `close_site()`, `line_key(line)`, `line_for_key(key)`, `keys()`, `grid(grid_id)`, `grid_for_line(line)`, `add_grid`, `replace_grid`, `remove_grid`, `set_grid_velocity`, `add_lines`, `remove_line`, `set_line_velocity`, `resolved_velocity(key)`, `stack_for(key)`, `append_step`, `insert_step`, `replace_step`, `remove_step`, `move_step`, `set_step_enabled`, `apply_stack_to_grid(key, grid_id) -> list[str]`, `open_line(key)`, `profiles_for(key)`, `set_profiles(key, profiles)`, `set_channel(key, channel)`, `channel(key) -> int`, `set_trace(key, index)`, `set_selection(key, start, end)`, `clear_selection()`, `SURVEY_FILE = "survey.nsgeo.json"`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`:

```python
from __future__ import annotations

import json

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.project import ProjectError
from nsgeo.velocity import VelocityModel

from nsgeo_qgis.session import SURVEY_FILE, SiteSession

from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


def _lines(folder, n=3):
    out = []
    for i in range(n):
        p = synthetic_dzt(folder / "raw", f"FILE__00{i + 1}.DZT", n_traces=60 + i)
        out.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1 if i % 2 == 0 else -1, p.stem)))
    return out


class Spy:
    def __init__(self, signal):
        self.calls: list = []
        signal.connect(lambda *a: self.calls.append(a))


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    return s


def test_new_site_writes_the_survey_file_and_derives_the_gpkg_name(qgis_app, tmp_path):
    s = SiteSession()
    opened = Spy(s.site_opened)
    s.new_site(tmp_path)
    assert (tmp_path / SURVEY_FILE).is_file()
    assert s.site_name == tmp_path.name
    assert s.gpkg_path == tmp_path / f"{tmp_path.name}.nsgeo.gpkg"
    assert s.is_open and not s.dirty
    assert opened.calls == [()]
    with pytest.raises(ProjectError, match="already"):
        s.new_site(tmp_path)


def test_grids_and_lines_mark_dirty_and_round_trip(session, tmp_path):
    dirty = Spy(session.dirty_changed)
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path))
    assert session.dirty and dirty.calls[0] == (True,)
    assert session.keys() == ["raw/FILE__001.DZT", "raw/FILE__002.DZT", "raw/FILE__003.DZT"]
    session.save()
    assert not session.dirty
    back = SiteSession()
    back.open_site(tmp_path / SURVEY_FILE)
    assert [g.id for g in back.site.grids] == ["A"]
    assert back.keys() == session.keys()


def test_duplicate_grid_ids_and_line_keys_are_refused(session, tmp_path):
    session.add_grid(GRID)
    with pytest.raises(ValueError, match="A"):
        session.add_grid(GRID)
    lines = _lines(tmp_path)
    session.add_lines(lines)
    with pytest.raises(ValueError, match="FILE__001"):
        session.add_lines(lines[:1])


def test_remove_grid_refuses_while_lines_reference_it(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    with pytest.raises(ValueError, match="1 line"):
        session.remove_grid("A")
    session.remove_line("raw/FILE__001.DZT")
    session.remove_grid("A")
    assert session.site.grids == []


def test_remove_line_drops_its_stack_and_closes_it_if_current(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    key = "raw/FILE__001.DZT"
    session.append_step(key, build_step("dewow"))
    session.open_line(key)
    opened = Spy(session.line_opened)
    session.remove_line(key)
    assert key not in session.site.stacks
    assert session.current_key is None
    assert opened.calls == [("",)]


def test_velocity_resolution_and_override(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    assert session.resolved_velocity(key) == VelocityModel.from_dielectric(14.0)
    session.set_grid_velocity("A", VelocityModel.constant(0.09))
    assert session.resolved_velocity(key) == VelocityModel.constant(0.09)
    session.set_line_velocity(key, VelocityModel.constant(0.07))
    assert session.resolved_velocity(key) == VelocityModel.constant(0.07)
    session.set_line_velocity(key, None)
    assert session.resolved_velocity(key) == VelocityModel.constant(0.09)


def test_stack_mutations_emit_and_go_through_the_stack(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 1))
    key = session.keys()[0]
    changed = Spy(session.stack_changed)
    session.append_step(key, build_step("dewow"))
    session.append_step(key, build_step("background_mean"))
    session.insert_step(key, 0, build_step("time_zero"))
    session.set_step_enabled(key, 1, False)
    session.move_step(key, 2, 0)
    session.replace_step(key, 1, build_step("time_zero", mode="sample", sample=3))
    session.remove_step(key, 0)
    names = [s.name for s, _ in session.stack_for(key).entries]
    assert names == ["time_zero", "dewow"]
    assert session.stack_for(key).entries[1][1] is False
    assert len(changed.calls) == 7 and all(c == (key,) for c in changed.calls)


def test_profiles_feed_the_stack_source_and_channel_switching(session, tmp_path):
    session.add_grid(GRID)
    lines = _lines(tmp_path, 1)
    session.add_lines(lines)
    key = session.keys()[0]
    loaded = Spy(session.line_loaded)
    session.set_profiles(key, lines[0].load())
    assert loaded.calls == [(key,)]
    src = session.stack_for(key).source
    assert src is not None and src.n_traces == 60 and src.data.dtype.kind == "f"
    assert session.channel(key) == 0
    with pytest.raises(IndexError):
        session.set_channel(key, 1)


def test_apply_stack_to_grid_copies_independent_stacks(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 3))
    a, b, c = session.keys()
    session.append_step(a, build_step("dewow", window_ns=6.0))
    changed = session.apply_stack_to_grid(a, "A")
    assert changed == [b, c]
    assert session.stack_for(b).to_dicts() == session.stack_for(a).to_dicts()
    assert session.stack_for(b) is not session.stack_for(a)
    session.replace_step(a, 0, build_step("dewow", window_ns=2.0))
    assert session.stack_for(b).to_dicts()[0]["params"]["window_ns"] == 6.0


def test_trace_and_selection_emit_only_on_change_and_only_for_the_current_line(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    a, b = session.keys()
    session.open_line(a)
    trace = Spy(session.trace_changed)
    sel = Spy(session.selection_changed)
    session.set_trace(a, 10)
    session.set_trace(a, 10)
    session.set_trace(a, 999)  # clamped to the last trace
    session.set_trace(b, 5)  # not current: ignored
    assert trace.calls == [(a, 10), (a, 59)]
    session.set_selection(a, 30, 20)
    session.set_selection(a, 30, 20)
    session.clear_selection()
    assert sel.calls == [(a, 20, 30), (a, -1, -1)]
    assert session.current_trace == 59


def test_open_line_resets_trace_and_selection(session, tmp_path):
    session.add_grid(GRID)
    session.add_lines(_lines(tmp_path, 2))
    a, b = session.keys()
    session.open_line(a)
    session.set_trace(a, 4)
    session.set_selection(a, 1, 2)
    session.open_line(b)
    assert (session.current_key, session.current_trace, session.selection) == (b, -1, (-1, -1))
    with pytest.raises(KeyError):
        session.open_line("nope")


def test_save_out_of_tree_line_needs_allow_absolute(qgis_app, tmp_path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    s = SiteSession()
    s.new_site(site_dir)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "elsewhere", "X.DZT")
    s.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    with pytest.raises(ProjectError, match="allow_absolute"):
        s.save()
    s.save(allow_absolute=True)
    doc = json.loads((site_dir / SURVEY_FILE).read_text())
    assert doc["lines"][0]["path"].startswith("/")
    s.add_grid(Grid("B", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    s.save()  # the opt-in is remembered for the session
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.session'`

- [ ] **Step 3: Implement `session.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/session.py`:

```python
"""SiteSession: the one place survey state lives.

Every widget reads from the session and connects to its signals; no widget
holds survey state or talks to another widget directly. Every signal fires
only when a value actually changed, which is the loop guard for the
map<->profile link. Stack mutation goes through the methods here and nowhere
else, so the core's no-in-place-mutation rule stays true.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from nsgeo.geometry.grid import Grid
from nsgeo.model.survey import Line, Profile, Site
from nsgeo.processing import Radargram, StepStack
from nsgeo.project import ProjectError, _line_key, load_site, save_site
from nsgeo.velocity import VelocityModel, resolve_velocity
from qgis.PyQt.QtCore import QObject, pyqtSignal

SURVEY_FILE = "survey.nsgeo.json"


class SiteSession(QObject):
    site_opened = pyqtSignal()
    site_closed = pyqtSignal()
    dirty_changed = pyqtSignal(bool)
    grids_changed = pyqtSignal()
    lines_changed = pyqtSignal()
    line_opened = pyqtSignal(str)  # "" when no line is current
    line_loaded = pyqtSignal(str)
    trace_changed = pyqtSignal(str, int)
    selection_changed = pyqtSignal(str, int, int)  # (-1, -1) when cleared
    stack_changed = pyqtSignal(str)
    picks_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._site: Site | None = None
        self._json_path: Path | None = None
        self._dirty = False
        self._allow_absolute = False
        self._profiles: dict[str, list[Profile]] = {}
        self._channel: dict[str, int] = {}
        self._current_key: str | None = None
        self._current_trace = -1
        self._selection: tuple[int, int] = (-1, -1)

    # ---- state ------------------------------------------------------------
    @property
    def site(self) -> Site | None:
        return self._site

    @property
    def is_open(self) -> bool:
        return self._site is not None

    @property
    def json_path(self) -> Path | None:
        return self._json_path

    @property
    def root(self) -> Path:
        return self._require_path().parent.resolve()

    @property
    def site_name(self) -> str:
        return self.root.name

    @property
    def gpkg_path(self) -> Path:
        return self.root / f"{self.site_name}.nsgeo.gpkg"

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def current_key(self) -> str | None:
        return self._current_key

    @property
    def current_trace(self) -> int:
        return self._current_trace

    @property
    def selection(self) -> tuple[int, int]:
        return self._selection

    def _require_site(self) -> Site:
        if self._site is None:
            raise ProjectError("no site is open")
        return self._site

    def _require_path(self) -> Path:
        if self._json_path is None:
            raise ProjectError("no site is open")
        return self._json_path

    def _set_dirty(self, flag: bool) -> None:
        if flag != self._dirty:
            self._dirty = flag
            self.dirty_changed.emit(flag)

    # ---- lifecycle --------------------------------------------------------
    def new_site(self, folder: str | Path) -> None:
        folder = Path(folder)
        if not folder.is_dir():
            raise ProjectError(f"{folder} is not a directory")
        json_path = folder / SURVEY_FILE
        if json_path.exists():
            raise ProjectError(f"{folder} already holds a {SURVEY_FILE}; open it instead")
        self._install(Site(), json_path)
        save_site(self._require_site(), json_path)
        self.site_opened.emit()

    def open_site(self, json_path: str | Path) -> None:
        json_path = Path(json_path)
        site = load_site(json_path)
        self._install(site, json_path)
        self.site_opened.emit()

    def _install(self, site: Site, json_path: Path) -> None:
        if self._site is not None:
            self.close_site()
        self._site = site
        self._json_path = json_path
        self._profiles.clear()
        self._channel.clear()
        self._current_key = None
        self._current_trace = -1
        self._selection = (-1, -1)
        self._allow_absolute = False
        self._set_dirty(False)

    def save(self, *, allow_absolute: bool | None = None) -> None:
        if allow_absolute is not None:
            self._allow_absolute = allow_absolute
        site = self._require_site()
        site.validate()
        save_site(site, self._require_path(), allow_absolute=self._allow_absolute)
        self._set_dirty(False)

    def close_site(self) -> None:
        if self._site is None:
            return
        self._site = None
        self._json_path = None
        self._profiles.clear()
        self._channel.clear()
        self._current_key = None
        self._current_trace = -1
        self._selection = (-1, -1)
        self._set_dirty(False)
        self.site_closed.emit()

    # ---- keys and lookups -------------------------------------------------
    def line_key(self, line: Line) -> str:
        # Always computable; whether an absolute key may be *saved* is
        # decided in save() via allow_absolute.
        return _line_key(line.path, self.root, allow_absolute=True)

    def keys(self) -> list[str]:
        return [self.line_key(ln) for ln in self._require_site().lines]

    def line_for_key(self, key: str) -> Line:
        for line in self._require_site().lines:
            if self.line_key(line) == key:
                return line
        raise KeyError(f"no line with key {key!r}")

    def grid(self, grid_id: str) -> Grid:
        for g in self._require_site().grids:
            if g.id == grid_id:
                return g
        raise KeyError(f"no grid with id {grid_id!r}")

    def grid_for_line(self, line: Line) -> Grid | None:
        grid_id = getattr(line.placement, "grid_id", None)
        return self._require_site().frames.get(grid_id) if grid_id is not None else None

    # ---- grids ------------------------------------------------------------
    def add_grid(self, grid: Grid) -> None:
        site = self._require_site()
        if any(g.id == grid.id for g in site.grids):
            raise ValueError(f"a grid with id {grid.id!r} already exists")
        site.grids.append(grid)
        self._set_dirty(True)
        self.grids_changed.emit()

    def replace_grid(self, grid: Grid) -> None:
        site = self._require_site()
        for i, g in enumerate(site.grids):
            if g.id == grid.id:
                site.grids[i] = grid
                break
        else:
            raise KeyError(f"no grid with id {grid.id!r}")
        self._set_dirty(True)
        self.grids_changed.emit()
        self.lines_changed.emit()  # line geometry follows the frame

    def remove_grid(self, grid_id: str) -> None:
        site = self._require_site()
        users = [ln for ln in site.lines if getattr(ln.placement, "grid_id", None) == grid_id]
        if users:
            raise ValueError(f"grid {grid_id!r} still has {len(users)} line(s); remove them first")
        site.grids.remove(self.grid(grid_id))
        self._set_dirty(True)
        self.grids_changed.emit()

    def set_grid_velocity(self, grid_id: str, model: VelocityModel | None) -> None:
        self.replace_grid(dataclasses.replace(self.grid(grid_id), velocity=model))

    # ---- lines ------------------------------------------------------------
    def add_lines(self, lines: list[Line]) -> None:
        site = self._require_site()
        existing = set(self.keys())
        for line in lines:
            key = self.line_key(line)
            if key in existing:
                raise ValueError(f"line {key!r} is already in the site")
            existing.add(key)
        site.lines.extend(lines)
        self._set_dirty(True)
        self.lines_changed.emit()

    def remove_line(self, key: str) -> None:
        site = self._require_site()
        line = self.line_for_key(key)
        site.lines.remove(line)
        site.stacks.pop(key, None)
        self._profiles.pop(key, None)
        self._channel.pop(key, None)
        self._set_dirty(True)
        if self._current_key == key:
            self._current_key = None
            self._current_trace = -1
            self._selection = (-1, -1)
            self.line_opened.emit("")
        self.lines_changed.emit()

    def set_line_velocity(self, key: str, model: VelocityModel | None) -> None:
        site = self._require_site()
        line = self.line_for_key(key)
        site.lines[site.lines.index(line)] = dataclasses.replace(line, velocity=model)
        self._set_dirty(True)
        self.lines_changed.emit()

    def resolved_velocity(self, key: str) -> VelocityModel:
        line = self.line_for_key(key)
        return resolve_velocity(line, self.grid_for_line(line))

    # ---- stacks -----------------------------------------------------------
    def stack_for(self, key: str) -> StepStack:
        site = self._require_site()
        stack = site.stacks.get(key)
        if stack is None:
            self.line_for_key(key)  # KeyError for unknown lines
            stack = StepStack()
            site.stacks[key] = stack
            self._attach_source(key, stack)
        return stack

    def _attach_source(self, key: str, stack: StepStack) -> None:
        profiles = self._profiles.get(key)
        if profiles:
            stack.source = Radargram.from_profile(profiles[self._channel.get(key, 0)])

    def _touch_stack(self, key: str) -> None:
        self._set_dirty(True)
        self.stack_changed.emit(key)

    def append_step(self, key: str, step: Any) -> None:
        self.stack_for(key).append(step)
        self._touch_stack(key)

    def insert_step(self, key: str, index: int, step: Any) -> None:
        self.stack_for(key).insert(index, step)
        self._touch_stack(key)

    def replace_step(self, key: str, index: int, step: Any) -> None:
        self.stack_for(key).replace_step(index, step)
        self._touch_stack(key)

    def remove_step(self, key: str, index: int) -> None:
        self.stack_for(key).remove(index)
        self._touch_stack(key)

    def move_step(self, key: str, src: int, dst: int) -> None:
        self.stack_for(key).move(src, dst)
        self._touch_stack(key)

    def set_step_enabled(self, key: str, index: int, flag: bool) -> None:
        self.stack_for(key).set_enabled(index, flag)
        self._touch_stack(key)

    def apply_stack_to_grid(self, key: str, grid_id: str) -> list[str]:
        """Copy this line's stack onto every other line in the grid.
        Explicit button, never a side effect. Returns the keys changed."""
        site = self._require_site()
        dicts = self.stack_for(key).to_dicts()
        changed: list[str] = []
        for line in site.lines:
            other = self.line_key(line)
            if other == key or getattr(line.placement, "grid_id", None) != grid_id:
                continue
            fresh = StepStack.from_dicts(dicts)
            self._attach_source(other, fresh)
            site.stacks[other] = fresh
            changed.append(other)
            self.stack_changed.emit(other)
        if changed:
            self._set_dirty(True)
        return changed

    # ---- current line, samples, cursor ------------------------------------
    def open_line(self, key: str) -> None:
        self.line_for_key(key)
        if key == self._current_key:
            return
        self._current_key = key
        self._current_trace = -1
        self._selection = (-1, -1)
        self.line_opened.emit(key)

    def profiles_for(self, key: str) -> list[Profile] | None:
        return self._profiles.get(key)

    def set_profiles(self, key: str, profiles: list[Profile]) -> None:
        self._profiles[key] = list(profiles)
        self._channel.setdefault(key, 0)
        self._attach_source(key, self.stack_for(key))
        self.line_loaded.emit(key)

    def channel(self, key: str) -> int:
        return self._channel.get(key, 0)

    def set_channel(self, key: str, channel: int) -> None:
        profiles = self._profiles.get(key)
        if profiles is None or not 0 <= channel < len(profiles):
            raise IndexError(f"line {key!r} has no channel {channel}")
        if channel == self._channel.get(key, 0):
            return
        self._channel[key] = channel
        self._attach_source(key, self.stack_for(key))
        self.stack_changed.emit(key)

    def set_trace(self, key: str, index: int) -> None:
        if key != self._current_key:
            return
        n = self.line_for_key(key).n_traces
        index = max(0, min(int(index), n - 1))
        if index != self._current_trace:
            self._current_trace = index
            self.trace_changed.emit(key, index)

    def set_selection(self, key: str, start: int, end: int) -> None:
        if key != self._current_key:
            return
        n = self.line_for_key(key).n_traces
        lo, hi = sorted((int(start), int(end)))
        sel = (max(0, lo), min(n - 1, hi))
        if sel != self._selection:
            self._selection = sel
            self.selection_changed.emit(key, sel[0], sel[1])

    def clear_selection(self) -> None:
        if self._selection != (-1, -1) and self._current_key is not None:
            self._selection = (-1, -1)
            self.selection_changed.emit(self._current_key, -1, -1)
```

- [ ] **Step 4: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: SiteSession, the single owner of plugin survey state

Holds the Site, its paths, per-line stacks, the current line, trace and
selection, and emits a signal on every real change. Stack edits go
through replace_step and friends so the core's no-mutation rule holds;
apply-to-grid copies stacks rather than sharing them. Out-of-tree lines
need an explicit allow_absolute on save, mapping to the core's opt-in."
```

---

### Task 7: `lookup.py` — Qt-free import planning, nearest trace, polygon corners

Pure functions the dialogs and map tools call. Tested on the normal matrix without QGIS. Real-file import planning is validated against the ten local files.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`
- Modify: `.github/workflows/ci.yml` (mypy the plugin's pure modules)

**Interfaces:**
- Consumes: `read_header`, `trace_count`, `read_dzx`, `Line.open`, `GridPlacement`, `fit_grid_from_corners`
- Produces: `ImportOptions(grid_id, axis, spacing, first_offset=0.0, start_along=0.0, direction_mode="alternate", label_source="stem", grid_size_along=None)`; `ImportRow(path, label, offset, direction, start_along, n_traces, length_m, traces_per_metre, sidecar, include=True, offset_edited=False, note="")` with `.placeable`; `trailing_number(stem) -> int | None`; `sort_files(paths) -> list[Path]`; `plan_import(paths, options) -> list[ImportRow]`; `recompute_offsets(rows, options) -> None`; `rows_to_lines(rows, options) -> list[Line]`; `nearest_trace(coords_by_key, xy, tolerance) -> tuple[str, int, float] | None`; `PolygonCorners(local, world, size_x, size_y)`; `corners_from_polygon(vertices, origin_index, plus_y_index) -> PolygonCorners`; `identity_curve(t0_ns, dt_ns, n_samples) -> list[list[float]]`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.fit import fit_grid_from_corners
from nsgeo.geometry.grid import Grid

from nsgeo_qgis.lookup import (
    ImportOptions,
    corners_from_polygon,
    identity_curve,
    nearest_trace,
    plan_import,
    recompute_offsets,
    rows_to_lines,
    sort_files,
    trailing_number,
)

from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt

OPTS = ImportOptions(grid_id="A", axis="y", spacing=0.5, grid_size_along=11.0)


def test_trailing_number_and_vendor_neutral_sort(tmp_path):
    assert trailing_number("FILE__012") == 12
    assert trailing_number("DAT_0007") == 7
    assert trailing_number("LINE03") == 3
    assert trailing_number("notes") is None
    paths = [tmp_path / n for n in ("FILE__010.DZT", "FILE__002.DZT", "FILE__001.DZT", "extra.DZT")]
    assert [p.name for p in sort_files(paths)] == [
        "FILE__001.DZT",
        "FILE__002.DZT",
        "FILE__010.DZT",
        "extra.DZT",
    ]


@pytest.fixture
def three(tmp_path):
    return [synthetic_dzt(tmp_path, f"FILE__00{i}.DZT", n_traces=60 * (i + 1)) for i in (3, 1, 2)]


def test_plan_import_orders_offsets_alternates_direction_and_reads_headers(three):
    rows = plan_import(three, OPTS)
    assert [r.path.name for r in rows] == ["FILE__001.DZT", "FILE__002.DZT", "FILE__003.DZT"]
    assert [r.offset for r in rows] == [0.0, 0.5, 1.0]
    assert [r.direction for r in rows] == [1, -1, 1]
    assert [r.label for r in rows] == ["FILE__001", "FILE__002", "FILE__003"]
    assert [r.n_traces for r in rows] == [120, 180, 240]
    assert rows[0].length_m == pytest.approx(2.0)
    assert all(r.include and r.placeable and r.sidecar is None for r in rows)


def test_excluding_a_row_pulls_later_rows_into_its_slot(three):
    rows = plan_import(three, OPTS)
    rows[1].include = False
    recompute_offsets(rows, OPTS)
    assert [r.offset for r in rows if r.include] == [0.0, 0.5]
    assert [r.direction for r in rows if r.include] == [1, -1]


def test_hand_edited_offsets_survive_recompute(three):
    rows = plan_import(three, OPTS)
    rows[2].offset = 3.25
    rows[2].offset_edited = True
    rows[0].include = False
    recompute_offsets(rows, OPTS)
    assert [r.offset for r in rows if r.include] == [0.0, 3.25]


def test_direction_modes_and_line_number_labels(three):
    forward = ImportOptions("A", "y", 0.5, direction_mode="forward", label_source="number")
    rows = plan_import(three, forward)
    assert [r.direction for r in rows] == [1, 1, 1]
    assert [r.label for r in rows] == ["line 0", "line 1", "line 2"]
    reverse = ImportOptions("A", "y", 0.5, direction_mode="reverse", first_offset=2.0)
    rows = plan_import(three, reverse)
    assert [r.direction for r in rows] == [-1, -1, -1]
    assert rows[0].offset == 2.0


def test_time_triggered_files_are_flagged_and_excluded(tmp_path):
    good = synthetic_dzt(tmp_path, "FILE__001.DZT")
    bad = synthetic_dzt(tmp_path, "FILE__002.DZT", traces_per_metre=0.0)
    rows = plan_import([good, bad], OPTS)
    assert rows[1].placeable is False and rows[1].include is False
    assert "time-triggered" in rows[1].note
    assert rows[1].length_m is None
    lines = rows_to_lines(rows, OPTS)
    assert [ln.path.name for ln in lines] == ["FILE__001.DZT"]


def test_overrunning_the_grid_is_a_warning_note(tmp_path):
    long = synthetic_dzt(tmp_path, "FILE__001.DZT", n_traces=60 * 12)  # 12 m in an 11 m grid
    rows = plan_import([long], OPTS)
    assert "exceeds" in rows[0].note and rows[0].include


def test_rows_to_lines_builds_grid_placements(three):
    rows = plan_import(three, OPTS)
    lines = rows_to_lines(rows, OPTS)
    p = lines[1].placement
    assert (p.grid_id, p.axis, p.offset, p.direction, p.label) == ("A", "y", 0.5, -1, "FILE__002")


def test_nearest_trace_within_tolerance():
    a = np.column_stack([np.zeros(10), np.arange(10.0)])
    b = np.column_stack([np.full(10, 5.0), np.arange(10.0)])
    hit = nearest_trace({"a": a, "b": b}, (4.8, 3.2), tolerance=0.5)
    assert hit is not None
    key, idx, dist = hit
    assert (key, idx) == ("b", 3) and dist == pytest.approx((0.2**2 + 0.2**2) ** 0.5)
    assert nearest_trace({"a": a, "b": b}, (2.5, 3.0), tolerance=0.5) is None
    assert nearest_trace({}, (0.0, 0.0), tolerance=1.0) is None


def test_corners_from_polygon_yields_a_fittable_rectangle():
    grid = Grid("G", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
    world = grid.to_world(np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]]))
    ring = [tuple(p) for p in world] + [tuple(world[0])]  # closed ring, as QGIS gives it
    corners = corners_from_polygon(ring, origin_index=0, plus_y_index=3)
    assert corners.size_x == pytest.approx(5.0) and corners.size_y == pytest.approx(11.0)
    fit = fit_grid_from_corners(corners.local, corners.world)
    assert fit.azimuth == pytest.approx(30.0, abs=1e-6)
    assert fit.residual_rms < 1e-9
    assert fit.origin == pytest.approx((500.0, 700.0))


def test_corners_from_polygon_rejects_non_adjacent_plus_y():
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    with pytest.raises(ValueError, match="adjacent"):
        corners_from_polygon(ring, origin_index=0, plus_y_index=2)
    with pytest.raises(ValueError, match="four"):
        corners_from_polygon(ring[:3], origin_index=0, plus_y_index=1)


def test_identity_curve_spans_the_time_axis_at_zero_db():
    assert identity_curve(-11.0, 0.5, 5) == [[-11.0, 0.0], [-9.0, 0.0]]


@needs_real_data
def test_real_files_plan_cleanly():
    rows = plan_import(REAL_DZT, OPTS)
    assert len(rows) == 10
    assert [r.n_traces for r in rows] == [608, 625, 629, 658, 613, 608, 635, 666, 653, 606]
    assert all(9.0 < r.length_m < 13.0 for r in rows)
    assert sum(r.sidecar is not None for r in rows) == 9
    by_name = {r.path.stem: r for r in rows}
    assert len(by_name["FILE__007"].sidecar.marks) == 1
    assert by_name["FILE__010"].sidecar is None
    assert "exceeds" in by_name["FILE__008"].note  # 11.10 m in an 11.0 m grid
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.lookup'`

- [ ] **Step 3: Implement `lookup.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`:

```python
"""Qt-free helpers behind the dialogs and map tools.

Import planning, the nearest-trace search the map link uses, polygon
corners for the grid dialog, and the identity gain curve. No Qt anywhere,
so all of it runs on the normal CI matrix.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzt import read_header, trace_count
from nsgeo.io.dzx import DzxError, DzxInfo, read_dzx
from nsgeo.model.survey import Line

_TRAILING = re.compile(r"(\d+)\s*$")


def trailing_number(stem: str) -> int | None:
    """GSSI FILE__001, MALA DAT_0001, Sensors & Software LINE01 all end in
    a sequence number. Vendor-neutral by construction."""
    m = _TRAILING.search(stem)
    return int(m.group(1)) if m else None


def sort_files(paths: Sequence[str | Path]) -> list[Path]:
    ps = [Path(p) for p in paths]
    return sorted(ps, key=lambda p: (trailing_number(p.stem) is None, trailing_number(p.stem) or 0, p.name))


@dataclass(frozen=True)
class ImportOptions:
    grid_id: str
    axis: str  # the axis the lines run ALONG
    spacing: float  # across the other axis
    first_offset: float = 0.0
    start_along: float = 0.0
    direction_mode: str = "alternate"  # alternate | forward | reverse
    label_source: str = "stem"  # stem | number
    grid_size_along: float | None = None  # for the over-length warning


@dataclass
class ImportRow:
    path: Path
    label: str
    offset: float
    direction: int
    start_along: float
    n_traces: int | None
    length_m: float | None
    traces_per_metre: float
    sidecar: DzxInfo | None
    include: bool = True
    offset_edited: bool = False
    note: str = ""

    @property
    def placeable(self) -> bool:
        return self.traces_per_metre > 0 and self.n_traces is not None


def plan_import(paths: Sequence[str | Path], options: ImportOptions) -> list[ImportRow]:
    rows: list[ImportRow] = []
    for path in sort_files(paths):
        header = read_header(path)
        n = trace_count(path, header)
        spm = float(header.traces_per_metre)
        try:
            sidecar = read_dzx(path)
            note = ""
        except DzxError as exc:
            sidecar = None
            note = f"sidecar unreadable: {exc}"
        rows.append(
            ImportRow(
                path=Path(path),
                label=Path(path).stem,
                offset=options.first_offset,
                direction=1,
                start_along=options.start_along,
                n_traces=n,
                length_m=n / spm if spm > 0 else None,
                traces_per_metre=spm,
                sidecar=sidecar,
                include=spm > 0,
                note=note,
            )
        )
    recompute_offsets(rows, options)
    return rows


def recompute_offsets(rows: list[ImportRow], options: ImportOptions) -> None:
    """Offsets, directions, labels, and notes over the included rows in
    table order. A hand-edited offset is kept; everything else follows the
    slot index, so excluding a redone line pulls the next file into its
    place."""
    slot = 0
    for row in rows:
        notes: list[str] = []
        if not row.placeable:
            row.include = False
            notes.append("time-triggered (traces/m = 0): cannot be grid-placed")
        if not row.include:
            row.note = "; ".join(notes) or row.note
            continue
        if not row.offset_edited:
            row.offset = options.first_offset + slot * options.spacing
        if options.direction_mode == "alternate":
            row.direction = 1 if slot % 2 == 0 else -1
        elif options.direction_mode == "reverse":
            row.direction = -1
        else:
            row.direction = 1
        if options.label_source == "number":
            row.label = f"line {slot}"
        else:
            row.label = row.path.stem
        if (
            options.grid_size_along is not None
            and row.length_m is not None
            and row.length_m > options.grid_size_along + 1e-9
        ):
            notes.append(
                f"exceeds grid size along {options.axis} ({options.grid_size_along} m) "
                f"by {row.length_m - options.grid_size_along:.2f} m"
            )
        row.note = "; ".join(notes)
        slot += 1


def rows_to_lines(rows: Sequence[ImportRow], options: ImportOptions) -> list[Line]:
    return [
        Line.open(
            row.path,
            GridPlacement(
                grid_id=options.grid_id,
                axis=options.axis,
                offset=float(row.offset),
                start_along=float(row.start_along),
                direction=int(row.direction),
                label=row.label,
            ),
        )
        for row in rows
        if row.include and row.placeable
    ]


def nearest_trace(
    coords_by_key: Mapping[str, np.ndarray], xy: tuple[float, float], tolerance: float
) -> tuple[str, int, float] | None:
    """The (line key, trace index, distance) closest to `xy`, or None when
    nothing lies within `tolerance`. Plain numpy: ten lines are a few
    thousand points, no spatial index needed."""
    best: tuple[str, int, float] | None = None
    point = np.asarray(xy, dtype=float)
    for key, coords in coords_by_key.items():
        if len(coords) == 0:
            continue
        d = np.hypot(coords[:, 0] - point[0], coords[:, 1] - point[1])
        i = int(np.argmin(d))
        if d[i] <= tolerance and (best is None or d[i] < best[2]):
            best = (key, i, float(d[i]))
    return best


@dataclass(frozen=True)
class PolygonCorners:
    local: np.ndarray  # (4, 2) grid-local metres
    world: np.ndarray  # (4, 2) world coordinates
    size_x: float
    size_y: float


def corners_from_polygon(
    vertices: Sequence[tuple[float, float]], origin_index: int, plus_y_index: int
) -> PolygonCorners:
    """Turn a four-vertex ring into the control points a rigid fit wants.
    `plus_y_index` must neighbour `origin_index`; the other neighbour is +X
    and the remaining vertex is +X+Y."""
    pts = [tuple(map(float, v)) for v in vertices]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) != 4:
        raise ValueError(f"expected four corners, got {len(pts)}")
    o = origin_index % 4
    if plus_y_index % 4 not in ((o + 1) % 4, (o - 1) % 4):
        raise ValueError("the +Y corner must be adjacent to the origin corner")
    y = plus_y_index % 4
    x = (o - 1) % 4 if y == (o + 1) % 4 else (o + 1) % 4
    far = ({0, 1, 2, 3} - {o, x, y}).pop()
    world = np.array([pts[o], pts[x], pts[far], pts[y]], dtype=float)
    size_x = float(math.dist(pts[o], pts[x]))
    size_y = float(math.dist(pts[o], pts[y]))
    local = np.array([[0.0, 0.0], [size_x, 0.0], [size_x, size_y], [0.0, size_y]])
    return PolygonCorners(local=local, world=world, size_x=size_x, size_y=size_y)


def identity_curve(t0_ns: float, dt_ns: float, n_samples: int) -> list[list[float]]:
    """Two control points at 0 dB spanning the time axis: the identity, so
    seeding gain_curve with it is not a guess."""
    t_end = t0_ns + dt_ns * (n_samples - 1)
    return [[float(t0_ns), 0.0], [float(t_end), 0.0]]
```

- [ ] **Step 4: Type-check the pure module and wire it into CI**

Run: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
Expected: clean. Then add `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` to the mypy line in `.github/workflows/ci.yml`'s `lint` job (and to the verification set in this plan's Global Constraints when you run it).

- [ ] **Step 5: Run, lint, commit**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS (the real-file test runs because the worktree has the symlinks).

```bash
git add packages/nsgeo-qgis .github/workflows/ci.yml
git commit -m "feat: Qt-free import planning, nearest-trace search, polygon corners

Placement guesses come from the trailing number in the file stem, which
GSSI, MALA, and Sensors & Software all use, so nothing here is
vendor-specific. Excluding a redone line pulls later files into its
slot unless their offsets were hand-edited. Validated against the ten
real files, including the one that overruns an 11 m grid by 10 cm."
```

---

### Task 8: `layers.py` — the site GeoPackage

Mirrors the session into `<site>.nsgeo.gpkg`: grids, lines, and marks are derived and read-only; picks is authored and editable. Regeneration is per table through the loaded layer's provider, never by touching the file.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/layers.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`

**Interfaces:**
- Consumes: `SiteSession` signals and accessors; `Line.trace_coords`, `Grid.to_world`, `read_dzx`
- Produces: `TABLES` (name → (wkb type, [(field, kind)])); `DERIVED = ("grids", "lines", "marks")`; `SiteLayers(session, project=None, parent=None)` with `layers: dict[str, QgsVectorLayer]`, `group`, `refresh()`, `ensure_tables()`, `refill_grids()`, `refill_lines()`, `refill_marks()`, `detach()`, `crs() -> QgsCoordinateReferenceSystem | None`, `feature_count(name) -> int`, `GRID_COLOURS`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer

from nsgeo_qgis.layers import DERIVED, TABLES, SiteLayers
from nsgeo_qgis.session import SiteSession

from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)

DZX = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02"><File><name>FILE__002.DZT</name>
<Profile><WayPt><scan>30</scan><mark>User</mark><name>Mark1</name></WayPt></Profile></File></DZX>"""


@pytest.fixture
def populated(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    (tmp_path / "raw" / "FILE__002.DZX").write_text(DZX)
    session.add_lines(lines)
    yield session, layers, project
    layers.detach()
    project.clear()


def test_tables_exist_with_the_declared_fields_and_flags(populated):
    session, layers, project = populated
    assert session.gpkg_path.is_file()
    for name, (_, fields) in TABLES.items():
        lyr = QgsVectorLayer(f"{session.gpkg_path}|layername={name}", name, "ogr")
        assert lyr.isValid(), name
        assert [f.name() for f in lyr.fields() if f.name() != "fid"] == [f for f, _ in fields]
    assert set(layers.layers) == set(TABLES)
    for name in TABLES:
        assert layers.layers[name].readOnly() is (name in DERIVED)
    assert layers.crs().authid() == "EPSG:32616"
    assert layers.layers["lines"].crs().authid() == "EPSG:32616"


def test_derived_tables_mirror_the_session(populated):
    session, layers, _ = populated
    assert layers.feature_count("grids") == 1
    assert layers.feature_count("lines") == 3
    assert layers.feature_count("marks") == 1
    feat = next(layers.layers["lines"].getFeatures())
    assert feat["line_key"] == "raw/FILE__001.DZT"
    assert feat["n_traces"] == 60
    assert feat["length_m"] == pytest.approx(1.0)
    assert feat.geometry().length() == pytest.approx(59 / 60, abs=1e-6)
    session.remove_line("raw/FILE__003.DZT")
    assert layers.feature_count("lines") == 2


def test_layers_are_grouped_in_the_project_under_the_site_name(populated):
    session, layers, project = populated
    group = project.layerTreeRoot().findGroup(f"nsgeo · {session.site_name}")
    assert group is not None
    assert len(group.findLayers()) == 4


def test_refill_never_touches_the_picks_table(populated):
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 43.1
    assert picks.dataProvider().addFeatures([f])[0]
    session.remove_line("raw/FILE__002.DZT")
    session.add_grid(Grid("B", (600.0, 700.0), 0.0, 2.0, 2.0, "EPSG:32616", 0.5))
    assert layers.feature_count("picks") == 1
    assert layers.feature_count("grids") == 2


def test_reopening_a_site_reuses_the_existing_package(populated, tmp_path):
    session, layers, project = populated
    session.save()
    layers.detach()
    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / "survey.nsgeo.json")
    assert layers2.feature_count("lines") == 3
    layers2.detach()


def test_grid_in_another_crs_is_transformed_into_the_package_crs(populated):
    session, layers, _ = populated
    session.add_grid(Grid("B", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))
    feats = {f["grid_id"]: f for f in layers.layers["grids"].getFeatures()}
    x = feats["B"].geometry().centroid().asPoint().x()
    assert 100_000 < x < 900_000  # UTM easting, not a longitude
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.layers'`

- [ ] **Step 3: Implement `layers.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/layers.py`:

```python
"""The site GeoPackage: one file, several tables, three rules.

1. Regenerate per table, never per file: rebuilding `lines` truncates and
   refills that table; the file is never deleted, so picks survive and
   Windows file locks never bite.
2. All writes go through the loaded QGIS layer's data provider, never a
   second OGR handle on a package QGIS already has open.
3. Derived tables (grids, lines, marks) are read-only in QGIS; the survey
   JSON is the source of truth for geometry. Picks are authored.

The package CRS is the CRS of the first grid; other grids are transformed
into it on write.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from nsgeo.io.dzx import DzxError, read_dzx
from nsgeo.model.survey import Line
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, QObject
from qgis.PyQt.QtGui import QColor

from nsgeo_qgis.session import SiteSession

_KIND = {
    "str": QMetaType.Type.QString,
    "int": QMetaType.Type.Int,
    "float": QMetaType.Type.Double,
}

TABLES: dict[str, tuple[Any, list[tuple[str, str]]]] = {
    "grids": (
        QgsWkbTypes.Type.Polygon,
        [
            ("grid_id", "str"),
            ("azimuth", "float"),
            ("size_x", "float"),
            ("size_y", "float"),
            ("default_spacing", "float"),
            ("velocity_json", "str"),
        ],
    ),
    "lines": (
        QgsWkbTypes.Type.LineString,
        [
            ("line_key", "str"),
            ("grid_id", "str"),
            ("label", "str"),
            ("axis", "str"),
            ("offset_m", "float"),
            ("start_along_m", "float"),
            ("direction", "int"),
            ("n_traces", "int"),
            ("length_m", "float"),
            ("antenna", "str"),
            ("file_name", "str"),
        ],
    ),
    "marks": (
        QgsWkbTypes.Type.Point,
        [("line_key", "str"), ("scan", "int"), ("kind", "str"), ("name", "str")],
    ),
    "picks": (
        QgsWkbTypes.Type.Point,
        [
            ("line_key", "str"),
            ("trace", "int"),
            ("distance_m", "float"),
            ("time_ns", "float"),
            ("depth_m", "float"),
            ("velocity_m_ns", "float"),
            ("stack_json", "str"),
            ("note", "str"),
            ("created", "str"),
        ],
    ),
}
DERIVED = ("grids", "lines", "marks")

GRID_COLOURS = ["#2f6fb2", "#c0392b", "#27ae60", "#8e44ad", "#d35400", "#16a085"]


def _fields(spec: list[tuple[str, str]]) -> QgsFields:
    fields = QgsFields()
    for name, kind in spec:
        fields.append(QgsField(name, _KIND[kind]))
    return fields


class SiteLayers(QObject):
    def __init__(
        self, session: SiteSession, project: QgsProject | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.project = project or QgsProject.instance()
        self.layers: dict[str, QgsVectorLayer] = {}
        self.group: Any = None
        session.site_opened.connect(self._on_site_opened)
        session.site_closed.connect(self.detach)
        session.grids_changed.connect(self.refresh)
        session.lines_changed.connect(self.refresh)

    # ---- lifecycle --------------------------------------------------------
    def _on_site_opened(self) -> None:
        self.detach()
        self.refresh()

    def detach(self) -> None:
        if self.layers:
            self.project.removeMapLayers([lyr.id() for lyr in self.layers.values()])
            self.layers.clear()
        if self.group is not None:
            parent = self.group.parent()
            if parent is not None:
                parent.removeChildNode(self.group)
            self.group = None

    def crs(self) -> QgsCoordinateReferenceSystem | None:
        site = self.session.site
        if site is None or not site.grids:
            return None
        return QgsCoordinateReferenceSystem(site.grids[0].crs)

    def refresh(self) -> None:
        site = self.session.site
        if site is None or not site.grids:
            return  # a table needs a CRS; nothing to show without a grid anyway
        self.ensure_tables()
        self.refill_grids()
        self.refill_lines()
        self.refill_marks()

    # ---- tables -----------------------------------------------------------
    def ensure_tables(self) -> None:
        path = str(self.session.gpkg_path)
        crs = self.crs()
        assert crs is not None
        for name, (wkb, spec) in TABLES.items():
            if not self._table_exists(path, name):
                self._create_table(path, name, wkb, spec, crs)
        if self.group is None:
            self.group = self.project.layerTreeRoot().addGroup(f"nsgeo · {self.session.site_name}")
        for name in TABLES:
            if name in self.layers:
                continue
            layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
            if not layer.isValid():
                raise RuntimeError(f"could not open table {name!r} in {path}")
            layer.setReadOnly(name in DERIVED)
            self.project.addMapLayer(layer, False)
            self.group.addLayer(layer)
            self.layers[name] = layer

    @staticmethod
    def _table_exists(path: str, name: str) -> bool:
        return Path(path).exists() and QgsVectorLayer(f"{path}|layername={name}", name, "ogr").isValid()

    def _create_table(
        self, path: str, name: str, wkb: Any, spec: list[tuple[str, str]], crs: QgsCoordinateReferenceSystem
    ) -> None:
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = name
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            if Path(path).exists()
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        )
        writer = QgsVectorFileWriter.create(
            path, _fields(spec), wkb, crs, self.project.transformContext(), opts
        )
        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            raise RuntimeError(f"could not create table {name!r}: {writer.errorMessage()}")
        del writer  # closes the file handle before the layer opens it

    # ---- geometry helpers -------------------------------------------------
    def _transform_for(self, grid_crs: str) -> QgsCoordinateTransform | None:
        target = self.crs()
        assert target is not None
        source = QgsCoordinateReferenceSystem(grid_crs)
        if source == target:
            return None
        return QgsCoordinateTransform(source, target, self.project)

    def _points(self, xy: np.ndarray, grid_crs: str) -> list[QgsPointXY]:
        tr = self._transform_for(grid_crs)
        pts = [QgsPointXY(float(x), float(y)) for x, y in np.asarray(xy, dtype=float)]
        return [tr.transform(p) for p in pts] if tr is not None else pts

    def _refill(self, name: str, features: list[QgsFeature]) -> None:
        layer = self.layers[name]
        provider = layer.dataProvider()
        if not provider.truncate():
            raise RuntimeError(f"could not truncate {name}: {provider.error().message()}")
        if features:
            ok, _ = provider.addFeatures(features)
            if not ok:
                raise RuntimeError(f"could not write {name}: {provider.error().message()}")
        layer.updateExtents()
        layer.triggerRepaint()

    def feature_count(self, name: str) -> int:
        return int(self.layers[name].featureCount())

    # ---- derived tables ---------------------------------------------------
    def refill_grids(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        for grid in site.grids:
            local = np.array([[0.0, 0.0], [grid.size_x, 0.0], [grid.size_x, grid.size_y], [0.0, grid.size_y]])
            ring = self._points(grid.to_world(local), grid.crs)
            f = QgsFeature(self.layers["grids"].fields())
            f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
            f["grid_id"] = grid.id
            f["azimuth"] = grid.azimuth
            f["size_x"] = grid.size_x
            f["size_y"] = grid.size_y
            f["default_spacing"] = grid.default_spacing
            f["velocity_json"] = json.dumps(grid.velocity.to_dict()) if grid.velocity else ""
            feats.append(f)
        self._refill("grids", feats)

    def refill_lines(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        for line in site.lines:
            grid = self.session.grid_for_line(line)
            if grid is None:
                continue  # trackless lines arrive with TrackPlacement, later
            f = QgsFeature(self.layers["lines"].fields())
            f.setGeometry(QgsGeometry.fromPolylineXY(self._points(line.trace_coords(site.frames), grid.crs)))
            p: Any = line.placement
            f["line_key"] = self.session.line_key(line)
            f["grid_id"] = grid.id
            f["label"] = p.label or ""
            f["axis"] = p.axis
            f["offset_m"] = float(p.offset)
            f["start_along_m"] = float(p.start_along)
            f["direction"] = int(p.direction)
            f["n_traces"] = int(line.n_traces)
            f["length_m"] = float(line.n_traces / line.header.traces_per_metre)
            f["antenna"] = line.header.antenna
            f["file_name"] = line.path.name
            feats.append(f)
        self._refill("lines", feats)
        self._style_lines()

    def refill_marks(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        for line in site.lines:
            grid = self.session.grid_for_line(line)
            if grid is None:
                continue
            try:
                info = read_dzx(line.path)
            except DzxError:
                continue
            if info is None or not info.marks:
                continue
            coords = self._points(line.trace_coords(site.frames), grid.crs)
            for mark in info.marks:
                idx = max(0, min(mark.scan, line.n_traces - 1))
                f = QgsFeature(self.layers["marks"].fields())
                f.setGeometry(QgsGeometry.fromPointXY(coords[idx]))
                f["line_key"] = self.session.line_key(line)
                f["scan"] = int(mark.scan)
                f["kind"] = mark.kind
                f["name"] = mark.name
                feats.append(f)
        self._refill("marks", feats)

    def _style_lines(self) -> None:
        site = self.session.site
        assert site is not None
        categories = []
        for i, grid in enumerate(site.grids):
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.GeometryType.LineGeometry)
            symbol.setColor(QColor(GRID_COLOURS[i % len(GRID_COLOURS)]))
            symbol.setWidth(0.5)
            categories.append(QgsRendererCategory(grid.id, symbol, grid.id))
        self.layers["lines"].setRenderer(QgsCategorizedSymbolRenderer("grid_id", categories))
        self.layers["lines"].triggerRepaint()


def line_for_feature(session: SiteSession, feature: QgsFeature) -> Line:
    """The session line a `lines` feature represents."""
    return session.line_for_key(str(feature["line_key"]))
```

- [ ] **Step 4: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean. If `test_grid_in_another_crs_is_transformed_into_the_package_crs` fails with a null geometry, the transform context needs the project passed as above; check `QgsCoordinateTransform(source, target, self.project)` is used, not the two-argument form.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: per-site GeoPackage mirrored from the session

One package per site holds grids, lines, and marks (derived, read-only,
refilled per table through the loaded layer's provider) and picks
(authored, never touched by a refill). The package CRS is the first
grid's; other grids are transformed on write. Lines are styled per grid
with a categorised renderer."
```

---

### Task 9: Survey dock and the plugin's file actions

The tree of site → grids → lines, bound to the session, plus New/Open/Save on the toolbar. Dialogs the dock needs (grid, import) are requested through signals and provided by Tasks 10 and 11, so this task has no forward dependencies.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/__init__.py` (docstring only; no Qt imports, so the pure tier can import `ui.view_transform` later)
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: `SiteSession`, `SiteLayers`
- Produces: `SurveyDock(session, parent=None)` (a `QgsDockWidget`) with `tree: QTreeWidget`, `status: QLabel`, `rebuild()`, `item_for_key(key) -> QTreeWidgetItem | None`, `grid_id_of(item) -> str | None`, `key_of(item) -> str | None`, signals `new_site_requested()`, `open_site_requested()`, `save_requested()`, `add_grid_requested()`, `edit_grid_requested(str)`, `import_requested(str)`, `grid_velocity_requested(str)`, `line_velocity_requested(str)`; `ROLE_KIND`, `ROLE_ID` item data roles. `NsgeoPlugin` gains `session`, `layers`, `survey_dock`, `save_with_prompt() -> bool`, `new_site()`, `open_site()`, and toolbar actions `act_new`, `act_open`, `act_save`, `act_add_grid`, `act_import`.

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.velocity import VelocityModel
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import Qt

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.survey_dock import ROLE_ID, ROLE_KIND, SurveyDock

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.08))


@pytest.fixture
def dock(qgis_app, tmp_path):
    session = SiteSession()
    dock = SurveyDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1 if i % 2 == 0 else -1, p.stem)))
    session.add_lines(lines)
    return session, dock


def test_tree_mirrors_site_grids_and_lines(dock):
    session, dock = dock
    root = dock.tree.topLevelItem(0)
    assert root.text(0) == session.site_name
    grid_item = root.child(0)
    assert grid_item.data(0, ROLE_KIND) == "grid" and grid_item.data(0, ROLE_ID) == "A"
    assert "0.080" in grid_item.text(0)
    assert grid_item.childCount() == 3
    line_item = grid_item.child(1)
    assert line_item.data(0, ROLE_KIND) == "line"
    assert line_item.data(0, ROLE_ID) == "raw/FILE__002.DZT"
    assert "FILE__002" in line_item.text(0) and "0.50" in line_item.text(0) and "↓" in line_item.text(0)


def test_tree_follows_session_changes(dock):
    session, dock = dock
    session.remove_line("raw/FILE__003.DZT")
    assert dock.tree.topLevelItem(0).child(0).childCount() == 2
    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 1.0, 1.0, "EPSG:32616", 0.5))
    assert dock.tree.topLevelItem(0).childCount() == 2
    assert "empty" in dock.tree.topLevelItem(0).child(1).text(0)


def test_clicking_a_line_opens_it_and_selection_follows_the_session(dock):
    session, dock = dock
    item = dock.item_for_key("raw/FILE__002.DZT")
    dock.tree.itemClicked.emit(item, 0)
    assert session.current_key == "raw/FILE__002.DZT"
    session.open_line("raw/FILE__003.DZT")
    assert dock.tree.currentItem() is dock.item_for_key("raw/FILE__003.DZT")


def test_status_shows_dirty_state(dock):
    session, dock = dock
    assert "modified" in dock.status.text()
    session.save()
    assert "modified" not in dock.status.text()
    assert "survey.nsgeo.json" in dock.status.text()


def test_line_velocity_override_is_marked(dock):
    session, dock = dock
    session.set_line_velocity("raw/FILE__001.DZT", VelocityModel.constant(0.095))
    assert "v 0.095*" in dock.item_for_key("raw/FILE__001.DZT").text(0)


def test_context_actions_remove_lines_and_grids(dock):
    session, dock = dock
    dock.remove_line_action("raw/FILE__001.DZT", confirm=False)
    assert "raw/FILE__001.DZT" not in session.keys()
    with pytest.raises(ValueError):
        dock.remove_grid_action("A", confirm=False)


def test_closing_the_site_empties_the_tree(dock):
    session, dock = dock
    session.close_site()
    assert dock.tree.topLevelItemCount() == 0
    assert dock.status.text() == "no site open"


def test_plugin_wires_the_dock_and_file_actions(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    assert plugin.survey_dock in fake_iface.docks
    assert plugin.survey_dock.allowedAreas() & Qt.DockWidgetArea.LeftDockWidgetArea
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(GRID)
    assert plugin.save_with_prompt() is True
    assert not plugin.session.dirty
    plugin.unload()
    assert plugin.survey_dock is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui'`

- [ ] **Step 3: Implement the dock**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/__init__.py`:

```python
"""Docks, dialogs, and the profile viewer. Widgets read from SiteSession
and never hold survey state. This file imports nothing so that the pure
test tier can import `nsgeo_qgis.ui.view_transform` without Qt."""
```

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`:

```python
"""The survey tree: site -> grids -> lines.

A view of the session. Removing lines and grids is handled here because it
is one session call; anything that needs a dialog (grid editor, import,
velocity) is requested through a signal and provided by the plugin object.
"""

from __future__ import annotations

from typing import Any

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession

ROLE_KIND = int(Qt.ItemDataRole.UserRole)
ROLE_ID = int(Qt.ItemDataRole.UserRole) + 1


class SurveyDock(QgsDockWidget):
    new_site_requested = pyqtSignal()
    open_site_requested = pyqtSignal()
    save_requested = pyqtSignal()
    add_grid_requested = pyqtSignal()
    edit_grid_requested = pyqtSignal(str)
    import_requested = pyqtSignal(str)
    grid_velocity_requested = pyqtSignal(str)
    line_velocity_requested = pyqtSignal(str)

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Survey", parent)
        self.setObjectName("nsgeoSurveyDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.session = session

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        self.tree = QTreeWidget(body)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree)
        self.status = QLabel(body)
        layout.addWidget(self.status)
        self.setWidget(body)

        session.site_opened.connect(self.rebuild)
        session.site_closed.connect(self.rebuild)
        session.grids_changed.connect(self.rebuild)
        session.lines_changed.connect(self.rebuild)
        session.dirty_changed.connect(self._update_status)
        session.line_opened.connect(self._follow_current)
        self.rebuild()

    # ---- building ---------------------------------------------------------
    def rebuild(self) -> None:
        self.tree.clear()
        site = self.session.site
        if site is None:
            self._update_status()
            return
        root = QTreeWidgetItem([self.session.site_name])
        root.setData(0, ROLE_KIND, "site")
        self.tree.addTopLevelItem(root)
        by_grid: dict[str, list[Any]] = {g.id: [] for g in site.grids}
        loose = []
        for line in site.lines:
            grid_id = getattr(line.placement, "grid_id", None)
            (by_grid[grid_id] if grid_id in by_grid else loose).append(line)
        for grid in site.grids:
            v = f" · v {grid.velocity.surface_velocity:.3f}" if grid.velocity else ""
            lines = by_grid[grid.id]
            text = f"{grid.id} · {grid.size_x:g} × {grid.size_y:g} m · {grid.default_spacing:g} m{v}"
            if not lines:
                text += " · empty"
            g_item = QTreeWidgetItem([text])
            g_item.setData(0, ROLE_KIND, "grid")
            g_item.setData(0, ROLE_ID, grid.id)
            root.addChild(g_item)
            for line in lines:
                g_item.addChild(self._line_item(line))
        for line in loose:
            root.addChild(self._line_item(line))
        self.tree.expandAll()
        self._follow_current(self.session.current_key or "")
        self._update_status()

    def _line_item(self, line: Any) -> QTreeWidgetItem:
        p = line.placement
        arrow = "↑" if getattr(p, "direction", 1) == 1 else "↓"
        cross = "x" if getattr(p, "axis", "y") == "y" else "y"
        text = f"{p.label or line.path.stem} · {cross} {p.offset:.2f} · {arrow}"
        if line.velocity is not None:
            text += f" · v {line.velocity.surface_velocity:.3f}*"
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE_KIND, "line")
        item.setData(0, ROLE_ID, self.session.line_key(line))
        item.setToolTip(0, str(line.path))
        return item

    def _update_status(self, *_: Any) -> None:
        if not self.session.is_open:
            self.status.setText("no site open")
            return
        name = self.session.json_path.name if self.session.json_path else ""
        self.status.setText(f"{name} · ● modified" if self.session.dirty else name)

    # ---- lookups ----------------------------------------------------------
    def kind_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_KIND) if item is not None else None

    def key_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_ID) if self.kind_of(item) == "line" else None

    def grid_id_of(self, item: QTreeWidgetItem | None) -> str | None:
        return item.data(0, ROLE_ID) if self.kind_of(item) == "grid" else None

    def item_for_key(self, key: str) -> QTreeWidgetItem | None:
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if self.key_of(item) == key:
                return item
            it += 1
        return None

    # ---- interaction ------------------------------------------------------
    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        key = self.key_of(item)
        if key is not None:
            self.session.open_line(key)

    def _follow_current(self, key: str) -> None:
        item = self.item_for_key(key) if key else None
        self.tree.setCurrentItem(item)

    def _on_context_menu(self, pos: Any) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        kind = self.kind_of(item)
        if kind == "site" or item is None:
            menu.addAction("Add grid…", self.add_grid_requested.emit)
        elif kind == "grid":
            gid = self.grid_id_of(item) or ""
            menu.addAction("Edit grid…", lambda: self.edit_grid_requested.emit(gid))
            menu.addAction("Import DZT files…", lambda: self.import_requested.emit(gid))
            menu.addAction("Set velocity…", lambda: self.grid_velocity_requested.emit(gid))
            menu.addSeparator()
            menu.addAction("Remove grid", lambda: self.remove_grid_action(gid))
        elif kind == "line":
            key = self.key_of(item) or ""
            menu.addAction("Open", lambda: self.session.open_line(key))
            menu.addAction("Set velocity override…", lambda: self.line_velocity_requested.emit(key))
            menu.addSeparator()
            menu.addAction("Remove line from site", lambda: self.remove_line_action(key))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def remove_line_action(self, key: str, *, confirm: bool = True) -> None:
        if confirm:
            answer = QMessageBox.question(
                self,
                "Remove line",
                f"Remove {key} from the site?\nIts picks stay in the picks layer.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.session.remove_line(key)

    def remove_grid_action(self, grid_id: str, *, confirm: bool = True) -> None:
        if confirm:
            answer = QMessageBox.question(self, "Remove grid", f"Remove grid {grid_id}?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.session.remove_grid(grid_id)
        except ValueError as exc:
            if confirm:
                QMessageBox.warning(self, "Remove grid", str(exc))
            else:
                raise
```

- [ ] **Step 4: Wire the plugin object**

Rewrite `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:

```python
"""The QGIS plugin object: builds the toolbar and docks, tears them down.

Holds no survey state; that is SiteSession. Owns the file dialogs and the
save-with-prompt flow, and hands dialog requests from the docks to the
dialog classes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import nsgeo
from nsgeo.project import ProjectError
from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox

from nsgeo_qgis import plugin_version
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SURVEY_FILE, SiteSession
from nsgeo_qgis.ui.survey_dock import SurveyDock

MENU = "&nsgeo"


class NsgeoPlugin:
    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.toolbar: Any = None
        self.actions: list[QAction] = []
        self.docks: list[Any] = []
        self.session: SiteSession | None = None
        self.layers: SiteLayers | None = None
        self.survey_dock: SurveyDock | None = None

    # ---- QGIS entry points ------------------------------------------------
    def initGui(self) -> None:  # noqa: N802
        self.session = SiteSession()
        self.layers = SiteLayers(self.session)
        main = self.iface.mainWindow()

        self.toolbar = self.iface.addToolBar("nsgeo")
        self.toolbar.setObjectName("nsgeoToolBar")
        self.act_new = self._action("New site…", self.new_site)
        self.act_open = self._action("Open site…", self.open_site)
        self.act_save = self._action("Save site", self.save_with_prompt)
        self.toolbar.addSeparator()
        self.act_add_grid = self._action("Add grid…", lambda: self.open_grid_dialog(None))
        self.act_import = self._action("Import DZT…", lambda: self.open_import_dialog(None))

        about = QAction("About nsgeo", main)
        about.triggered.connect(self.show_about)
        self.iface.addPluginToMenu(MENU, about)
        self.actions.append(about)

        self.survey_dock = SurveyDock(self.session, main)
        self.survey_dock.add_grid_requested.connect(lambda: self.open_grid_dialog(None))
        self.survey_dock.edit_grid_requested.connect(self.open_grid_dialog)
        self.survey_dock.import_requested.connect(self.open_import_dialog)
        self.survey_dock.grid_velocity_requested.connect(self.open_grid_dialog)
        self.iface.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.survey_dock)
        self.docks.append(self.survey_dock)
        self._update_enabled()
        self.session.site_opened.connect(self._update_enabled)
        self.session.site_closed.connect(self._update_enabled)

    def unload(self) -> None:
        if self.session is not None and self.session.dirty:
            self.save_with_prompt(ask_first=True)
        for dock in self.docks:
            self.iface.removeDockWidget(dock)
            dock.deleteLater()
        self.docks.clear()
        self.survey_dock = None
        for action in self.actions:
            self.iface.removePluginMenu(MENU, action)
        self.actions.clear()
        if self.toolbar is not None:
            self.toolbar.setParent(None)
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.layers is not None:
            self.layers.detach()
            self.layers = None
        self.session = None

    # ---- helpers ----------------------------------------------------------
    def _action(self, text: str, slot: Any) -> QAction:
        action = QAction(text, self.iface.mainWindow())
        action.triggered.connect(slot)
        self.toolbar.addAction(action)
        return action

    def _update_enabled(self) -> None:
        is_open = self.session is not None and self.session.is_open
        for act in (self.act_save, self.act_add_grid, self.act_import):
            act.setEnabled(is_open)

    def message(self, text: str, level: Any = None, title: str = "nsgeo") -> None:
        self.iface.messageBar().pushMessage(
            title, text, level if level is not None else Qgis.MessageLevel.Info, 6
        )

    def show_about(self) -> None:
        self.message(f"plugin {plugin_version()} · core {nsgeo.__version__}")

    # ---- site files -------------------------------------------------------
    def new_site(self) -> None:
        assert self.session is not None
        if self.session.dirty and not self.save_with_prompt(ask_first=True):
            return
        folder = QFileDialog.getExistingDirectory(self.iface.mainWindow(), "Choose an empty folder for the site")
        if not folder:
            return
        try:
            self.session.new_site(Path(folder))
        except ProjectError as exc:
            self.message(str(exc), Qgis.MessageLevel.Critical)

    def open_site(self) -> None:
        assert self.session is not None
        if self.session.dirty and not self.save_with_prompt(ask_first=True):
            return
        path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(), "Open a survey file", "", f"nsgeo survey ({SURVEY_FILE});;All files (*)"
        )
        if not path:
            return
        try:
            self.session.open_site(Path(path))
        except ProjectError as exc:
            self.message(str(exc), Qgis.MessageLevel.Critical)

    def save_with_prompt(self, *, ask_first: bool = False) -> bool:
        """Save the site. Returns True when the caller may proceed (saved, or
        the user chose to discard). Handles the out-of-tree opt-in."""
        assert self.session is not None
        if not self.session.is_open:
            return True
        if ask_first:
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                "Unsaved changes",
                "Save the site before continuing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Discard:
                return True
        try:
            self.session.save()
            return True
        except ProjectError as exc:
            if "allow_absolute" not in str(exc):
                self.message(str(exc), Qgis.MessageLevel.Critical)
                return False
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                "Files outside the site folder",
                "Some survey files live outside the site folder. Record them by absolute path?\n"
                "The survey file will then only open on machines with the same mount points.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            self.session.save(allow_absolute=True)
            return True

    # ---- dialogs (provided by later tasks) --------------------------------
    def open_grid_dialog(self, grid_id: str | None) -> None:
        self.message("Grid dialog arrives in the next task.", Qgis.MessageLevel.Warning)

    def open_import_dialog(self, grid_id: str | None) -> None:
        self.message("Import dialog arrives in a later task.", Qgis.MessageLevel.Warning)
```

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: survey dock and site file actions

The tree is a view of the session: it rebuilds on every grids/lines
signal, selects the current line, and shows the dirty flag. Removing a
line or grid is one session call so it lives here; grid editing, import
and velocity dialogs are requested through signals. Save handles the
out-of-tree opt-in with a prompt rather than a silent fallback."
```

---

### Task 10: Grid dialog with three georeferencing tabs and the digitise map tool

GNSS corners, digitise on map, or an existing polygon: three UI paths into the same six fields (spec §5.6). Velocity is required and seeded from the header dielectric when the grid already has lines.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/maptools/__init__.py` (docstring only)
- Create: `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_grid_dialog`)
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py`

**Interfaces:**
- Consumes: `fit_grid_from_corners`, `corners_from_polygon`, `VelocityModel`, `SiteSession`
- Produces: `GridDialog(session, grid=None, suggested_velocity=None, parent=None)` with `corner_table`, `fit_corners()`, `residual_label`, `layer_combo`, `feature_picker`, `origin_combo`, `plus_y_combo`, `use_polygon()`, `digitise_requested` signal, `set_digitised(origin_xy, along_xy)`, fields `id_edit`, `crs_widget`, `origin_x`, `origin_y`, `azimuth`, `size_x`, `size_y`, `spacing`, `velocity`, `ok_button`, `result_grid() -> Grid`; `DigitiseGridTool(canvas)` with signal `points_picked(QgsPointXY, QgsPointXY)` and `reset()`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.velocity import VelocityModel
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt

from nsgeo_qgis.maptools.digitise_tool import DigitiseGridTool
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.grid_dialog import GridDialog

TRUE = Grid("A", (500.0, 700.0), 30.0, 5.0, 11.0, "EPSG:32616", 0.5)
LOCAL = np.array([[0.0, 0.0], [5.0, 0.0], [5.0, 11.0], [0.0, 11.0]])


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    return s


def test_ok_is_blocked_until_id_and_velocity_are_set(session):
    d = GridDialog(session)
    assert not d.ok_button.isEnabled()
    d.id_edit.setText("A")
    assert not d.ok_button.isEnabled()  # velocity still 0 = required
    d.velocity.setValue(0.08)
    assert d.ok_button.isEnabled()


def test_corner_fit_fills_origin_azimuth_and_sizes(session):
    d = GridDialog(session, suggested_velocity=0.0801)
    world = TRUE.to_world(LOCAL)
    for row, (lo, wo) in enumerate(zip(LOCAL, world)):
        d.set_corner_row(row, lo[0], lo[1], wo[0], wo[1])
    d.fit_corners()
    assert d.origin_x.value() == pytest.approx(500.0, abs=1e-6)
    assert d.origin_y.value() == pytest.approx(700.0, abs=1e-6)
    assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)
    assert d.size_x.value() == pytest.approx(5.0) and d.size_y.value() == pytest.approx(11.0)
    assert "0.000" in d.residual_label.text()
    d.id_edit.setText("A")
    d.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32616"))
    g = d.result_grid()
    assert g.id == "A" and g.crs == "EPSG:32616"
    assert g.velocity == VelocityModel.constant(0.0801)


def test_polygon_tab_reads_a_selected_feature(session):
    layer = QgsVectorLayer("Polygon?crs=EPSG:32616", "plan", "memory")
    ring = [QgsPointXY(*p) for p in TRUE.to_world(LOCAL)]
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
    layer.dataProvider().addFeatures([f])
    QgsProject.instance().addMapLayer(layer)
    try:
        d = GridDialog(session)
        d.layer_combo.setLayer(layer)
        d.feature_picker.setFeature(next(layer.getFeatures()).id())
        d.origin_combo.setCurrentIndex(0)
        d.plus_y_combo.setCurrentIndex(3)
        d.use_polygon()
        assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)
        assert d.size_y.value() == pytest.approx(11.0, abs=1e-6)
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_digitised_points_set_origin_and_azimuth(session):
    d = GridDialog(session)
    d.set_digitised((500.0, 700.0), (500.0 + 5.0 * np.sin(np.radians(30)), 700.0 + 5.0 * np.cos(np.radians(30))))
    assert (d.origin_x.value(), d.origin_y.value()) == (500.0, 700.0)
    assert d.azimuth.value() == pytest.approx(30.0, abs=1e-6)


def test_editing_an_existing_grid_prefills_and_keeps_its_id(session):
    session.add_grid(Grid("A", (1.0, 2.0), 45.0, 3.0, 4.0, "EPSG:32616", 0.25, velocity=VelocityModel.constant(0.1)))
    d = GridDialog(session, grid=session.grid("A"))
    assert d.id_edit.text() == "A" and not d.id_edit.isEnabled()
    assert d.velocity.value() == pytest.approx(0.1)
    d.azimuth.setValue(46.0)
    assert d.result_grid().azimuth == 46.0 and d.result_grid().default_spacing == 0.25


def test_digitise_tool_emits_after_two_clicks(qgis_app, fake_iface):
    tool = DigitiseGridTool(fake_iface.mapCanvas())
    got = []
    tool.points_picked.connect(lambda a, b: got.append((a, b)))
    tool.canvasClicked.emit(QgsPointXY(1.0, 2.0), Qt.MouseButton.LeftButton)
    assert got == []
    tool.canvasClicked.emit(QgsPointXY(1.0, 5.0), Qt.MouseButton.LeftButton)
    assert len(got) == 1 and got[0][1].y() == 5.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.maptools'`

- [ ] **Step 3: Implement the map tool**

Create `packages/nsgeo-qgis/nsgeo_qgis/maptools/__init__.py` with a one-line docstring: `"""Canvas tools. Each is a QgsMapTool that talks to the session or a dialog."""`

Create `packages/nsgeo-qgis/nsgeo_qgis/maptools/digitise_tool.py`:

```python
"""Two clicks define a grid frame: the origin, then a point along +Y."""

from __future__ import annotations

from qgis.core import QgsPointXY
from qgis.gui import QgsMapCanvas, QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor


class DigitiseGridTool(QgsMapToolEmitPoint):
    points_picked = pyqtSignal(QgsPointXY, QgsPointXY)

    def __init__(self, canvas: QgsMapCanvas) -> None:
        super().__init__(canvas)
        self._origin: QgsPointXY | None = None
        self._band = QgsRubberBand(canvas)
        self._band.setColor(QColor(48, 140, 198))
        self._band.setWidth(2)
        self.canvasClicked.connect(self._on_click)

    def _on_click(self, point: QgsPointXY, _button: int) -> None:
        if self._origin is None:
            self._origin = QgsPointXY(point)
            self._band.reset()
            self._band.addPoint(self._origin)
            return
        origin, self._origin = self._origin, None
        self._band.reset()
        self.points_picked.emit(origin, QgsPointXY(point))

    def reset(self) -> None:
        self._origin = None
        self._band.reset()

    def deactivate(self) -> None:
        self.reset()
        super().deactivate()
```

- [ ] **Step 4: Implement the dialog**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`:

```python
"""Grid dialog: three ways in, one set of numbers.

GNSS corners (rigid least-squares fit with a residual shown as QC),
digitising two points on the map, or reading a selected polygon feature.
All three fill the same fields; the user can still edit any of them.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from nsgeo.geometry.fit import fit_grid_from_corners
from nsgeo.geometry.grid import Grid
from nsgeo.velocity import VelocityModel
from qgis.core import QgsCoordinateReferenceSystem, QgsMapLayerProxyModel, QgsProject
from qgis.gui import QgsFeaturePickerWidget, QgsMapLayerComboBox, QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.lookup import corners_from_polygon
from nsgeo_qgis.session import SiteSession

CORNER_NAMES = ("origin", "+X", "+X+Y", "+Y")


def _spin(lo: float, hi: float, decimals: int, step: float, value: float = 0.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    return s


class GridDialog(QDialog):
    digitise_requested = pyqtSignal()

    def __init__(
        self,
        session: SiteSession,
        grid: Grid | None = None,
        suggested_velocity: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.existing = grid
        self.setWindowTitle(f"Grid · {grid.id}" if grid else "New grid")
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_corner_tab(), "GNSS corners")
        self.tabs.addTab(self._build_digitise_tab(), "Digitise on map")
        self.tabs.addTab(self._build_polygon_tab(), "From polygon")
        layout.addWidget(self.tabs)

        form = QFormLayout()
        self.id_edit = QLineEdit()
        self.crs_widget = QgsProjectionSelectionWidget()
        self.origin_x = _spin(-1e8, 1e8, 3, 0.1)
        self.origin_y = _spin(-1e8, 1e8, 3, 0.1)
        self.azimuth = _spin(0.0, 360.0, 3, 0.5)
        self.azimuth.setWrapping(True)
        self.size_x = _spin(0.0, 1e5, 2, 0.5, 10.0)
        self.size_y = _spin(0.0, 1e5, 2, 0.5, 10.0)
        self.spacing = _spin(0.01, 100.0, 3, 0.05, 0.5)
        self.velocity = _spin(0.0, 0.3, 4, 0.001)
        self.velocity.setSpecialValueText("required")
        self.velocity_hint = QLabel("")
        origin_row = QHBoxLayout()
        origin_row.addWidget(self.origin_x)
        origin_row.addWidget(self.origin_y)
        size_row = QHBoxLayout()
        size_row.addWidget(self.size_x)
        size_row.addWidget(self.size_y)
        vel_row = QHBoxLayout()
        vel_row.addWidget(self.velocity)
        vel_row.addWidget(self.velocity_hint)
        form.addRow("Id", self.id_edit)
        form.addRow("CRS", self.crs_widget)
        form.addRow("Origin E, N", origin_row)
        form.addRow("Azimuth (° cw from N to +Y)", self.azimuth)
        form.addRow("Size X, Y (m)", size_row)
        form.addRow("Default spacing (m)", self.spacing)
        form.addRow("Velocity (m/ns)", vel_row)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.id_edit.textChanged.connect(self._validate)
        self.velocity.valueChanged.connect(self._validate)
        self.size_x.valueChanged.connect(self._validate)
        self.size_y.valueChanged.connect(self._validate)

        project_crs = QgsProject.instance().crs()
        if project_crs.isValid():
            self.crs_widget.setCrs(project_crs)
        if grid is not None:
            self._prefill(grid)
        elif suggested_velocity is not None:
            self.velocity.setValue(suggested_velocity)
            self.velocity_hint.setText("from the header dielectric")
        self._validate()

    # ---- tabs -------------------------------------------------------------
    def _build_corner_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.corner_table = QTableWidget(4, 5)
        self.corner_table.setHorizontalHeaderLabels(["corner", "local x", "local y", "world E", "world N"])
        for row, name in enumerate(CORNER_NAMES):
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.corner_table.setItem(row, 0, item)
            for col in range(1, 5):
                self.corner_table.setItem(row, col, QTableWidgetItem(""))
        v.addWidget(self.corner_table)
        row = QHBoxLayout()
        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_corners)
        self.residual_label = QLabel("rigid fit: rotation + translation, no scale")
        row.addWidget(self.fit_button)
        row.addWidget(self.residual_label)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _build_digitise_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Click the grid origin on the map, then a point along the +Y edge. Then enter the sizes."))
        self.digitise_button = QPushButton("Pick on map")
        self.digitise_button.clicked.connect(self.digitise_requested.emit)
        v.addWidget(self.digitise_button)
        v.addStretch(1)
        return w

    def _build_polygon_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
        self.feature_picker = QgsFeaturePickerWidget()
        self.layer_combo.layerChanged.connect(self.feature_picker.setLayer)
        self.feature_picker.setLayer(self.layer_combo.currentLayer())
        self.origin_combo = QComboBox()
        self.plus_y_combo = QComboBox()
        for i in range(4):
            self.origin_combo.addItem(f"vertex {i}")
            self.plus_y_combo.addItem(f"vertex {i}")
        self.plus_y_combo.setCurrentIndex(3)
        self.use_polygon_button = QPushButton("Use polygon")
        self.use_polygon_button.clicked.connect(self.use_polygon)
        form.addRow("Layer", self.layer_combo)
        form.addRow("Feature", self.feature_picker)
        form.addRow("Origin corner", self.origin_combo)
        form.addRow("+Y corner", self.plus_y_combo)
        form.addRow(self.use_polygon_button)
        self.polygon_status = QLabel("")
        form.addRow(self.polygon_status)
        return w

    # ---- the three paths --------------------------------------------------
    def set_corner_row(self, row: int, lx: float, ly: float, wx: float, wy: float) -> None:
        for col, val in zip((1, 2, 3, 4), (lx, ly, wx, wy)):
            self.corner_table.item(row, col).setText(f"{val:.6f}")

    def _corner_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        local, world = [], []
        for row in range(self.corner_table.rowCount()):
            vals = [self.corner_table.item(row, c).text().strip() for c in range(1, 5)]
            if not all(vals):
                continue
            nums = [float(v) for v in vals]
            local.append(nums[:2])
            world.append(nums[2:])
        return np.array(local, dtype=float), np.array(world, dtype=float)

    def fit_corners(self) -> None:
        local, world = self._corner_arrays()
        try:
            fit = fit_grid_from_corners(local, world)
        except ValueError as exc:
            self.residual_label.setText(str(exc))
            return
        self.origin_x.setValue(fit.origin[0])
        self.origin_y.setValue(fit.origin[1])
        self.azimuth.setValue(fit.azimuth)
        self.size_x.setValue(float(local[:, 0].max()))
        self.size_y.setValue(float(local[:, 1].max()))
        self.residual_label.setText(f"rigid fit RMS {fit.residual_rms:.3f} m (nonzero = grid not square)")

    def set_digitised(self, origin_xy: tuple[float, float], along_xy: tuple[float, float]) -> None:
        dx = along_xy[0] - origin_xy[0]
        dy = along_xy[1] - origin_xy[1]
        self.origin_x.setValue(origin_xy[0])
        self.origin_y.setValue(origin_xy[1])
        self.azimuth.setValue(math.degrees(math.atan2(dx, dy)) % 360.0)
        self.tabs.setCurrentIndex(1)

    def use_polygon(self) -> None:
        feature = self.feature_picker.feature()
        layer = self.layer_combo.currentLayer()
        if layer is None or not feature.isValid() or feature.geometry().isNull():
            self.polygon_status.setText("select a polygon feature first")
            return
        geom = feature.geometry()
        polygon = geom.asPolygon() if not geom.isMultipart() else geom.asMultiPolygon()[0]
        ring = [(p.x(), p.y()) for p in polygon[0]]
        try:
            corners = corners_from_polygon(ring, self.origin_combo.currentIndex(), self.plus_y_combo.currentIndex())
            fit = fit_grid_from_corners(corners.local, corners.world)
        except ValueError as exc:
            self.polygon_status.setText(str(exc))
            return
        self.origin_x.setValue(fit.origin[0])
        self.origin_y.setValue(fit.origin[1])
        self.azimuth.setValue(fit.azimuth)
        self.size_x.setValue(corners.size_x)
        self.size_y.setValue(corners.size_y)
        self.crs_widget.setCrs(layer.crs())
        self.polygon_status.setText(f"rigid fit RMS {fit.residual_rms:.3f} m")

    # ---- result -----------------------------------------------------------
    def _prefill(self, grid: Grid) -> None:
        self.id_edit.setText(grid.id)
        self.id_edit.setEnabled(False)  # lines reference the id; renaming is a different feature
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem(grid.crs))
        self.origin_x.setValue(grid.origin[0])
        self.origin_y.setValue(grid.origin[1])
        self.azimuth.setValue(grid.azimuth)
        self.size_x.setValue(grid.size_x)
        self.size_y.setValue(grid.size_y)
        self.spacing.setValue(grid.default_spacing)
        if grid.velocity is not None:
            self.velocity.setValue(grid.velocity.surface_velocity)

    def _validate(self, *_: Any) -> None:
        ok = bool(self.id_edit.text().strip()) and self.velocity.value() > 0 and self.size_x.value() > 0 and self.size_y.value() > 0
        self.ok_button.setEnabled(ok)

    def result_grid(self) -> Grid:
        return Grid(
            id=self.id_edit.text().strip(),
            origin=(self.origin_x.value(), self.origin_y.value()),
            azimuth=self.azimuth.value(),
            size_x=self.size_x.value(),
            size_y=self.size_y.value(),
            crs=self.crs_widget.crs().authid(),
            default_spacing=self.spacing.value(),
            velocity=VelocityModel.constant(self.velocity.value()),
        )
```

Import `Qt` alongside `pyqtSignal`: `from qgis.PyQt.QtCore import Qt, pyqtSignal`. If `QgsMapLayerProxyModel.Filter.PolygonLayer` is reported missing on your QGIS build, use `Qgis.LayerFilter.PolygonLayer` from `qgis.core` instead; both exist on 3.40+.

- [ ] **Step 5: Wire it into the plugin**

In `plugin.py`, replace the `open_grid_dialog` stub:

```python
    def open_grid_dialog(self, grid_id: str | None) -> None:
        assert self.session is not None
        if not self.session.is_open:
            return
        grid = self.session.grid(grid_id) if grid_id else None
        suggestion = None
        if grid is None:
            lines = self.session.site.lines if self.session.site else []
            if lines:
                suggestion = VelocityModel.from_dielectric(lines[0].header.epsr).surface_velocity
        dialog = GridDialog(self.session, grid=grid, suggested_velocity=suggestion, parent=self.iface.mainWindow())
        dialog.digitise_requested.connect(lambda: self._start_digitise(dialog))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = dialog.result_grid()
        try:
            if grid is None:
                self.session.add_grid(result)
            else:
                self.session.replace_grid(result)
        except (ValueError, KeyError) as exc:
            self.message(str(exc), Qgis.MessageLevel.Critical)

    def _start_digitise(self, dialog: GridDialog) -> None:
        canvas = self.iface.mapCanvas()
        tool = DigitiseGridTool(canvas)

        def done(origin: Any, along: Any) -> None:
            dialog.set_digitised((origin.x(), origin.y()), (along.x(), along.y()))
            dialog.crs_widget.setCrs(canvas.mapSettings().destinationCrs())
            canvas.unsetMapTool(tool)
            dialog.show()
            dialog.raise_()

        tool.points_picked.connect(done)
        dialog.hide()
        canvas.setMapTool(tool)
```

Add the imports `from qgis.PyQt.QtWidgets import QDialog`, `from nsgeo.velocity import VelocityModel`, `from nsgeo_qgis.ui.grid_dialog import GridDialog`, `from nsgeo_qgis.maptools.digitise_tool import DigitiseGridTool`.

- [ ] **Step 6: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: grid dialog with corner fit, map digitising, and polygon import

Three UI paths into the same six fields. The corner fit is the core's
rigid least-squares and its residual is shown as a QC number; the
polygon path goes through the pure corners_from_polygon; digitising is
two clicks on a QgsMapToolEmitPoint. Velocity is required and seeded
from the header dielectric when the site already has lines."
```

---

### Task 11: Import dialog

Select files, choose the grid and axis, correct the guessed placements in a table, import. Include checkbox, remove, reorder, and the vendor-neutral guess from Task 7. Validated on the ten real files.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_import_dialog`)
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`

**Interfaces:**
- Consumes: `plan_import`, `recompute_offsets`, `rows_to_lines`, `ImportOptions`, `SiteSession.add_lines`
- Produces: `ImportDialog(session, grid_id=None, parent=None)` with `add_files(paths)`, `rows: list[ImportRow]`, `options() -> ImportOptions`, `table: QTableWidget`, column constants `COL_INCLUDE .. COL_NOTE`, `remove_selected()`, `move_selected(delta)`, `set_include(row, flag)`, `set_offset(row, value)`, `import_button`, `status`, `imported_keys: list[str]` after `accept()`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.PyQt.QtCore import Qt

from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.import_dialog import COL_DIR, COL_INCLUDE, COL_LABEL, COL_NOTE, COL_OFFSET, ImportDialog

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(GRID)
    return s


def test_table_shows_planned_rows_and_edits_flow_back(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT", n_traces=60) for i in (2, 1, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    assert d.table.rowCount() == 3
    assert [d.table.item(r, COL_LABEL).text() for r in range(3)] == ["FILE__001", "FILE__002", "FILE__003"]
    assert [d.table.item(r, COL_OFFSET).text() for r in range(3)] == ["0.00", "0.50", "1.00"]
    assert d.table.item(1, COL_DIR).text() == "−1"
    d.set_include(1, False)
    assert [d.table.item(r, COL_OFFSET).text() for r in range(3) if d.rows[r].include] == ["0.00", "0.50"]
    d.set_offset(2, 3.25)
    d.set_include(1, True)
    assert d.rows[2].offset == 3.25 and d.rows[2].offset_edited
    assert d.table.item(1, COL_OFFSET).text() == "0.50"


def test_remove_and_reorder(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.table.selectRow(2)
    d.move_selected(-1)
    assert [r.path.stem for r in d.rows] == ["FILE__001", "FILE__003", "FILE__002"]
    assert [r.offset for r in d.rows] == [0.0, 0.5, 1.0]
    d.table.selectRow(0)
    d.remove_selected()
    assert [r.path.stem for r in d.rows] == ["FILE__003", "FILE__002"]
    assert d.rows[0].offset == 0.0


def test_accept_adds_lines_and_fills_the_layer(session, tmp_path):
    layers = SiteLayers(session)
    files = [synthetic_dzt(tmp_path / "raw", f"FILE__00{i}.DZT") for i in (1, 2, 3)]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.set_include(1, False)
    d.accept()
    assert d.imported_keys == ["raw/FILE__001.DZT", "raw/FILE__003.DZT"]
    assert session.keys() == d.imported_keys
    assert layers.feature_count("lines") == 2
    layers.detach()


def test_duplicate_import_is_reported_not_raised(session, tmp_path):
    files = [synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")]
    d = ImportDialog(session, grid_id="A")
    d.add_files(files)
    d.accept()
    d2 = ImportDialog(session, grid_id="A")
    d2.add_files(files)
    d2.accept()
    assert "already" in d2.status.text()
    assert d2.result() != d2.DialogCode.Accepted


def test_axis_and_spacing_options_come_from_the_widgets(session, tmp_path):
    d = ImportDialog(session, grid_id="A")
    d.axis_combo.setCurrentIndex(d.axis_combo.findData("x"))
    d.spacing.setValue(0.25)
    d.first_offset.setValue(1.0)
    d.direction_forward.setChecked(True)
    d.label_number.setChecked(True)
    o = d.options()
    assert (o.axis, o.spacing, o.first_offset, o.direction_mode, o.label_source) == ("x", 0.25, 1.0, "forward", "number")
    assert o.grid_size_along == 5.0  # size_x when lines run along x


@needs_real_data
def test_real_files_import_into_the_grid(session):
    d = ImportDialog(session, grid_id="A")
    d.add_files(REAL_DZT)
    assert d.table.rowCount() == 10
    assert "exceeds" in d.table.item(7, COL_NOTE).text()  # FILE__008, 11.10 m
    assert d.table.item(0, COL_INCLUDE).checkState() == Qt.CheckState.Checked
    d.accept()
    assert len(session.keys()) == 10
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.import_dialog'`

- [ ] **Step 3: Implement the dialog**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py`:

```python
"""Import DZT files into a grid, with a correction table.

The guess (Task 7's plan_import) is vendor-neutral and the table is the
real mechanism: Include, Label, Offset, Dir, Start are editable; Traces,
Length, Sidecar come from the file. Excluding a redone line pulls later
files into its slot unless their offsets were hand-edited.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.lookup import ImportOptions, ImportRow, plan_import, recompute_offsets, rows_to_lines
from nsgeo_qgis.session import SiteSession

COL_INCLUDE, COL_FILE, COL_LABEL, COL_OFFSET, COL_DIR, COL_START, COL_TRACES, COL_LENGTH, COL_SIDECAR, COL_NOTE = range(10)
HEADERS = ["", "File", "Label", "Offset (m)", "Dir", "Start (m)", "Traces", "Length (m)", "Sidecar", "Note"]
EDITABLE = {COL_LABEL, COL_OFFSET, COL_DIR, COL_START}


class ImportDialog(QDialog):
    def __init__(self, session: SiteSession, grid_id: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.rows: list[ImportRow] = []
        self.imported_keys: list[str] = []
        self._updating = False
        self.setWindowTitle("Import DZT files")
        self.resize(900, 520)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.grid_combo = QComboBox()
        site = session.site
        for g in site.grids if site else []:
            self.grid_combo.addItem(g.id, g.id)
        if grid_id:
            self.grid_combo.setCurrentIndex(max(0, self.grid_combo.findData(grid_id)))
        self.axis_combo = QComboBox()
        self.axis_combo.addItem("y (lines run along Y, offsets across X)", "y")
        self.axis_combo.addItem("x (lines run along X, offsets across Y)", "x")
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0.01, 100.0)
        self.spacing.setDecimals(3)
        self.first_offset = QDoubleSpinBox()
        self.first_offset.setRange(-1e4, 1e4)
        self.first_offset.setDecimals(3)
        self.start_along = QDoubleSpinBox()
        self.start_along.setRange(-1e4, 1e4)
        self.start_along.setDecimals(3)
        form.addRow("Target grid", self.grid_combo)
        form.addRow("Lines run along", self.axis_combo)
        form.addRow("Spacing across", self.spacing)
        form.addRow("First line at", self.first_offset)
        form.addRow("Start along", self.start_along)

        direction_row = QHBoxLayout()
        self.direction_alternate = QRadioButton("alternate (zigzag)")
        self.direction_forward = QRadioButton("all +1")
        self.direction_reverse = QRadioButton("all −1")
        self.direction_alternate.setChecked(True)
        self._direction_group = QButtonGroup(self)
        for b in (self.direction_alternate, self.direction_forward, self.direction_reverse):
            self._direction_group.addButton(b)
            direction_row.addWidget(b)
        direction_row.addStretch(1)
        form.addRow("Direction", direction_row)
        label_row = QHBoxLayout()
        self.label_stem = QRadioButton("file name")
        self.label_number = QRadioButton("line number")
        self.label_stem.setChecked(True)
        self._label_group = QButtonGroup(self)
        for b in (self.label_stem, self.label_number):
            self._label_group.addButton(b)
            label_row.addWidget(b)
        label_row.addStretch(1)
        form.addRow("Label from", label_row)
        layout.addLayout(form)

        buttons_row = QHBoxLayout()
        self.add_button = QPushButton("Add files…")
        self.add_button.clicked.connect(self._choose_files)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self.remove_selected)
        self.up_button = QPushButton("↑")
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button = QPushButton("↓")
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        for b in (self.add_button, self.remove_button, self.up_button, self.down_button):
            buttons_row.addWidget(b)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.status = QLabel("")
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Import")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.grid_combo.currentIndexChanged.connect(self._grid_changed)
        for w in (self.axis_combo,):
            w.currentIndexChanged.connect(self._replan)
        for s in (self.spacing, self.first_offset, self.start_along):
            s.valueChanged.connect(self._replan)
        for b in (self.direction_alternate, self.direction_forward, self.direction_reverse, self.label_stem, self.label_number):
            b.toggled.connect(self._replan)
        self._grid_changed()

    # ---- options ----------------------------------------------------------
    def _grid(self) -> Any:
        gid = self.grid_combo.currentData()
        return self.session.grid(gid) if gid else None

    def _grid_changed(self, *_: Any) -> None:
        grid = self._grid()
        if grid is not None:
            self.spacing.setValue(grid.default_spacing)
        self._replan()

    def options(self) -> ImportOptions:
        grid = self._grid()
        axis = self.axis_combo.currentData() or "y"
        along = None
        if grid is not None:
            along = grid.size_y if axis == "y" else grid.size_x
        mode = "alternate" if self.direction_alternate.isChecked() else "forward" if self.direction_forward.isChecked() else "reverse"
        return ImportOptions(
            grid_id=grid.id if grid else "",
            axis=axis,
            spacing=self.spacing.value(),
            first_offset=self.first_offset.value(),
            start_along=self.start_along.value(),
            direction_mode=mode,
            label_source="number" if self.label_number.isChecked() else "stem",
            grid_size_along=along,
        )

    # ---- rows -------------------------------------------------------------
    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select DZT files", "", "GSSI DZT (*.DZT *.dzt);;All files (*)")
        if paths:
            self.add_files([Path(p) for p in paths])

    def add_files(self, paths: list[Path]) -> None:
        known = {r.path.resolve() for r in self.rows}
        fresh = [Path(p) for p in paths if Path(p).resolve() not in known]
        if not fresh:
            return
        try:
            new_rows = plan_import(fresh, self.options())
        except Exception as exc:  # DztError, OSError: name the file, keep the dialog alive
            self.status.setText(f"could not read a file: {exc}")
            return
        self.rows.extend(new_rows)
        self._replan()

    def _replan(self, *_: Any) -> None:
        recompute_offsets(self.rows, self.options())
        self._refresh_table()

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def remove_selected(self) -> None:
        for r in reversed(self._selected_rows()):
            del self.rows[r]
        self._replan()

    def move_selected(self, delta: int) -> None:
        sel = self._selected_rows()
        if len(sel) != 1:
            return
        i, j = sel[0], sel[0] + delta
        if not 0 <= j < len(self.rows):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self._replan()
        self.table.selectRow(j)

    def set_include(self, row: int, flag: bool) -> None:
        self.rows[row].include = flag
        self._replan()

    def set_offset(self, row: int, value: float) -> None:
        self.rows[row].offset = float(value)
        self.rows[row].offset_edited = True
        self._replan()

    # ---- table ------------------------------------------------------------
    def _refresh_table(self) -> None:
        self._updating = True
        try:
            self.table.setRowCount(len(self.rows))
            for r, row in enumerate(self.rows):
                inc = QTableWidgetItem("")
                inc.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                inc.setCheckState(Qt.CheckState.Checked if row.include else Qt.CheckState.Unchecked)
                if not row.placeable:
                    inc.setFlags(Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, COL_INCLUDE, inc)
                sidecar = ""
                if row.sidecar is not None:
                    parts = ["✓"]
                    if row.sidecar.dielectric is not None:
                        parts.append(f"ε {row.sidecar.dielectric:g}")
                    if row.sidecar.marks:
                        parts.append(f"{len(row.sidecar.marks)} mark(s)")
                    sidecar = " ".join(parts)
                values = {
                    COL_FILE: row.path.name,
                    COL_LABEL: row.label,
                    COL_OFFSET: f"{row.offset:.2f}",
                    COL_DIR: "+1" if row.direction == 1 else "−1",
                    COL_START: f"{row.start_along:.2f}",
                    COL_TRACES: "" if row.n_traces is None else str(row.n_traces),
                    COL_LENGTH: "" if row.length_m is None else f"{row.length_m:.2f}",
                    COL_SIDECAR: sidecar,
                    COL_NOTE: row.note,
                }
                for col, text in values.items():
                    item = QTableWidgetItem(text)
                    if col not in EDITABLE:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, col, item)
            self.table.resizeColumnsToContents()
            n = sum(1 for r in self.rows if r.include and r.placeable)
            self.import_button.setText(f"Import {n} line(s)")
            self.import_button.setEnabled(n > 0)
        finally:
            self._updating = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        r, c = item.row(), item.column()
        row = self.rows[r]
        try:
            if c == COL_INCLUDE:
                row.include = item.checkState() == Qt.CheckState.Checked
            elif c == COL_LABEL:
                row.label = item.text().strip() or row.path.stem
                return  # label edits need no replan
            elif c == COL_OFFSET:
                row.offset = float(item.text().replace(",", "."))
                row.offset_edited = True
            elif c == COL_DIR:
                row.direction = -1 if item.text().strip().lstrip("+") in ("-1", "−1") else 1
            elif c == COL_START:
                row.start_along = float(item.text().replace(",", "."))
        except ValueError:
            pass
        self._replan()

    # ---- accept -----------------------------------------------------------
    def accept(self) -> None:
        opts = self.options()
        if not opts.grid_id:
            self.status.setText("choose a target grid")
            return
        # A label edited in the table must survive recompute_offsets; it does,
        # because recompute only rewrites labels when label_source == "number".
        try:
            lines = rows_to_lines(self.rows, opts)
            self.session.add_lines(lines)
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.imported_keys = [self.session.line_key(ln) for ln in lines]
        super().accept()
```

**Known wrinkle to handle while implementing:** `recompute_offsets` rewrites `row.label` to the file stem when `label_source == "stem"`, which would discard a hand-edited label on the next replan. Fix it in `lookup.py` the same way offsets are protected: add `label_edited: bool = False` to `ImportRow`, set it in `_on_item_changed` for `COL_LABEL`, and make `recompute_offsets` skip rows with `label_edited`. Add a pure test for it in `test_pure_lookup.py`:

```python
def test_hand_edited_labels_survive_recompute(three):
    rows = plan_import(three, OPTS)
    rows[1].label = "line 6a"
    rows[1].label_edited = True
    recompute_offsets(rows, OPTS)
    assert rows[1].label == "line 6a"
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py`, replace the `open_import_dialog` stub:

```python
    def open_import_dialog(self, grid_id: str | None) -> None:
        assert self.session is not None
        if not self.session.is_open:
            return
        if not (self.session.site and self.session.site.grids):
            self.message("Add a grid before importing lines.", Qgis.MessageLevel.Warning)
            return
        dialog = ImportDialog(self.session, grid_id=grid_id, parent=self.iface.mainWindow())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.message(f"imported {len(dialog.imported_keys)} line(s)")
```

with `from nsgeo_qgis.ui.import_dialog import ImportDialog`.

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: import dialog with a correction table

Files, grid, axis, spacing, direction mode, and label source feed the
vendor-neutral planner; the table is the real mechanism. Include
checkboxes and Remove pull later files into a redone line's slot;
hand-edited offsets and labels survive replanning. Validated on the ten
real files, including the 11.10 m line that overruns an 11 m grid."
```

---

### Task 12: Background line loading and the M4 checkpoint

`Line.load()` on a `QgsTask`, so clicking a line never blocks the canvas. The session gets the profiles when the task finishes. Ends M4: real lines on the map from real files.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/loader.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (own a `LineLoader`)
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py`

**Interfaces:**
- Consumes: `SiteSession.line_opened`, `profiles_for`, `set_profiles`, `Line.load`
- Produces: `LineLoader(session, on_error=None, parent=None)` with signal `loading_changed(str, bool)`, `is_loading(key) -> bool`, `request(key)`, `wait_for(key, timeout_ms=5000) -> bool` (test helper; spins a `QEventLoop`)

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt

from nsgeo_qgis.loader import LineLoader
from nsgeo_qgis.session import SiteSession

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def session(qgis_app, tmp_path):
    s = SiteSession()
    s.new_site(tmp_path)
    s.add_grid(GRID)
    return s


def test_opening_a_line_loads_it_in_the_background(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=200)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    loader = LineLoader(session)
    states = []
    loader.loading_changed.connect(lambda k, f: states.append((k, f)))
    loaded = []
    session.line_loaded.connect(loaded.append)

    session.open_line(key)
    assert loader.is_loading(key)
    assert loader.wait_for(key)
    assert not loader.is_loading(key)
    assert states == [(key, True), (key, False)]
    assert loaded == [key]
    assert session.stack_for(key).source.n_traces == 200


def test_reopening_a_loaded_line_does_not_reload(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    q = synthetic_dzt(tmp_path / "raw", "FILE__002.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0)), Line.open(q, GridPlacement("A", "y", 0.5))])
    a, b = session.keys()
    loader = LineLoader(session)
    session.open_line(a)
    assert loader.wait_for(a)
    session.open_line(b)
    assert loader.wait_for(b)
    states = []
    loader.loading_changed.connect(lambda k, f: states.append((k, f)))
    session.open_line(a)
    assert states == [] and not loader.is_loading(a)


def test_a_corrupt_file_reports_instead_of_raising(session, tmp_path):
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0))])
    key = session.keys()[0]
    p.write_bytes(p.read_bytes()[:-7])  # non-integer trace count now
    errors = []
    loader = LineLoader(session, on_error=lambda k, msg: errors.append((k, msg)))
    session.open_line(key)
    assert loader.wait_for(key)
    assert errors and errors[0][0] == key and "trace count" in errors[0][1]
    assert session.profiles_for(key) is None


@needs_real_data
def test_real_line_loads(session):
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    loader = LineLoader(session)
    session.open_line(key)
    assert loader.wait_for(key, timeout_ms=10_000)
    src = session.stack_for(key).source
    assert src.n_samples == 512 and src.t0_ns == pytest.approx(-11.09, abs=0.01)
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.loader'`

- [ ] **Step 3: Implement the loader**

Create `packages/nsgeo-qgis/nsgeo_qgis/loader.py`:

```python
"""Load sample arrays off the main thread.

Header reads are 1 KB and stay synchronous; Line.load() reads megabytes and
runs on a QgsTask. The session is only touched from the main thread, in the
task's finished callback.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer, pyqtSignal

from nsgeo_qgis.session import SiteSession


class LineLoader(QObject):
    loading_changed = pyqtSignal(str, bool)

    def __init__(
        self,
        session: SiteSession,
        on_error: Callable[[str, str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.on_error = on_error
        self._tasks: dict[str, QgsTask] = {}
        session.line_opened.connect(self._on_line_opened)
        session.site_closed.connect(self._tasks.clear)

    def is_loading(self, key: str) -> bool:
        return key in self._tasks

    def _on_line_opened(self, key: str) -> None:
        if key:
            self.request(key)

    def request(self, key: str) -> None:
        if key in self._tasks or self.session.profiles_for(key) is not None:
            return
        line = self.session.line_for_key(key)

        def work(_task: QgsTask) -> Any:
            return line.load()

        def finished(exception: BaseException | None, result: Any = None) -> None:
            self._tasks.pop(key, None)
            if exception is not None:
                if self.on_error is not None:
                    self.on_error(key, str(exception))
            elif self.session.is_open and key in self.session.keys():
                self.session.set_profiles(key, result)
            self.loading_changed.emit(key, False)

        task = QgsTask.fromFunction(f"nsgeo: load {line.path.name}", work, on_finished=finished)
        self._tasks[key] = task
        self.loading_changed.emit(key, True)
        QgsApplication.taskManager().addTask(task)

    def wait_for(self, key: str, timeout_ms: int = 5000) -> bool:
        """Spin the event loop until `key` finishes loading. For tests."""
        if key not in self._tasks:
            return True
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def on_change(k: str, flag: bool) -> None:
            if k == key and not flag:
                loop.quit()

        self.loading_changed.connect(on_change)
        timer.start(timeout_ms)
        loop.exec()
        self.loading_changed.disconnect(on_change)
        return key not in self._tasks
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py` `initGui`, after creating `self.layers`:

```python
        self.loader = LineLoader(
            self.session,
            on_error=lambda key, msg: self.message(f"{key}: {msg}", Qgis.MessageLevel.Critical),
        )
```

with `from nsgeo_qgis.loader import LineLoader`, an `self.loader: LineLoader | None = None` in `__init__`, and `self.loader = None` in `unload`.

- [ ] **Step 5: Run everything, lint, commit**

Run the full verification set from Global Constraints.
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: load line samples on a QgsTask

Clicking a line never blocks the canvas: Line.load() runs in the task
pool and the session receives the profiles on the main thread. Errors
from a corrupt file reach the message bar instead of a traceback."
```

**M4 checkpoint (manual, 10 minutes).** With the dev symlink in place, reload the plugin in QGIS and:

1. Toolbar ▸ New site… ▸ pick an empty folder. The survey dock shows the folder name and `survey.nsgeo.json · ● modified` is not shown (a fresh site is clean).
2. Toolbar ▸ Add grid… ▸ GNSS corners tab. Enter four corners (any UTM numbers forming a ≈5 × 11 m rectangle), Fit, confirm the residual reads near zero, set id `A`, CRS EPSG:32616, velocity shows 0.08, OK. A dashed grid outline appears on the canvas in a group named after the site.
3. Right-click grid A ▸ Import DZT files… ▸ Add files… ▸ select the ten real files from `packages/nsgeo-core/tests/data/local/`. Check: 10 rows, FILE__008's note says it exceeds the grid, sidecar column shows ε 14 for nine files. Uncheck FILE__005, confirm FILE__006 moves to offset 2.00. Re-check it. Import 10 lines.
4. Ten coloured lines appear inside the grid outline, one mark point at the end of FILE__007. Click a line in the tree: nothing visible happens yet (no viewer), but no error appears and the QGIS task bar briefly shows a load.
5. Toolbar ▸ Save site. Open the saved `survey.nsgeo.json` in a text editor: grids carry `velocity`, lines carry placements. Open the `.nsgeo.gpkg` in QGIS's browser: four tables.
6. Digitise tab: Add grid… ▸ Digitise on map ▸ Pick on map ▸ two clicks on the canvas ▸ the dialog returns with origin and azimuth filled; enter sizes and id `B`, OK. Grid B appears.

Anything that fails here is fixed before Task 13.

---

### Task 13: `ViewTransform` — the pure mapping behind the viewer

One frozen dataclass maps trace index and two-way time to widget pixels and back, given the visible window and the widget size. Axes, the cursor, drag-selection, picking, and the gain strip all go through it, so there is one place where "which trace is under the mouse" can be wrong. No Qt; tested on the normal matrix.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
- Create: `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`
- Modify: `.github/workflows/ci.yml` (add the module to the mypy line)

**Interfaces:**
- Consumes: numpy
- Produces: `ViewTransform(n_traces, n_samples, t0_ns, dt_ns, width, height, trace_lo, trace_hi, time_lo, time_hi)` frozen, with `fit(n_traces, n_samples, t0_ns, dt_ns, width, height)`, `t_end`, `x_of_trace(i)`, `trace_of_x(x)`, `y_of_time(t)`, `time_of_y(y)`, `trace_index_at(x) -> int`, `sample_index_at(y) -> int`, `source_rect() -> (x, y, w, h)` in image pixel units, `zoomed(factor, anchor_x, anchor_y)`, `panned(dx_px, dy_px)`, `resized(width, height)`, `with_window(trace_lo, trace_hi, time_lo, time_hi)`; `nice_ticks(vmin, vmax, target=6) -> np.ndarray`; `MIN_TRACE_SPAN = 4.0`, `MIN_SAMPLE_SPAN = 4.0`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo_qgis.ui.view_transform import MIN_TRACE_SPAN, ViewTransform, nice_ticks

FIT = ViewTransform.fit(n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300)


def test_fit_maps_the_data_extent_onto_the_widget():
    assert FIT.x_of_trace(0) == 0.0
    assert FIT.x_of_trace(608) == 800.0
    assert FIT.y_of_time(-11.09) == 0.0
    assert FIT.y_of_time(FIT.t_end) == pytest.approx(300.0)
    assert FIT.t_end == pytest.approx(-11.09 + 512 * 0.2165)


def test_round_trips():
    for x in (0.0, 123.4, 799.0):
        assert FIT.x_of_trace(FIT.trace_of_x(x)) == pytest.approx(x)
    for y in (0.0, 57.2, 300.0):
        assert FIT.y_of_time(FIT.time_of_y(y)) == pytest.approx(y)


def test_index_lookups_clamp_to_the_data():
    assert FIT.trace_index_at(-50) == 0
    assert FIT.trace_index_at(800) == 607
    assert FIT.trace_index_at(400) == 304
    assert FIT.sample_index_at(-5) == 0
    assert FIT.sample_index_at(300) == 511
    assert FIT.sample_index_at(150) in (255, 256)  # exactly half the record; float rounding either side


def test_source_rect_is_the_visible_window_in_image_pixels():
    assert FIT.source_rect() == (0.0, 0.0, 608.0, 512.0)
    z = FIT.with_window(100.0, 300.0, 0.0, 20.0)
    x, y, w, h = z.source_rect()
    assert (x, w) == (100.0, 200.0)
    assert y == pytest.approx((0.0 + 11.09) / 0.2165)
    assert h == pytest.approx(20.0 / 0.2165)


def test_zoom_keeps_the_point_under_the_anchor_fixed():
    trace_before = FIT.trace_of_x(600.0)
    time_before = FIT.time_of_y(100.0)
    z = FIT.zoomed(2.0, anchor_x=600.0, anchor_y=100.0)
    assert z.trace_of_x(600.0) == pytest.approx(trace_before)
    assert z.time_of_y(100.0) == pytest.approx(time_before)
    assert (z.trace_hi - z.trace_lo) == pytest.approx(304.0)


def test_zoom_is_clamped_to_the_data_and_a_minimum_span():
    out = FIT.zoomed(0.5, 400.0, 150.0)  # zooming out past the data extent
    assert (out.trace_lo, out.trace_hi) == (0.0, 608.0)
    z = FIT
    for _ in range(40):
        z = z.zoomed(2.0, 400.0, 150.0)
    assert z.trace_hi - z.trace_lo == pytest.approx(MIN_TRACE_SPAN)
    assert 0.0 <= z.trace_lo and z.trace_hi <= 608.0


def test_pan_is_clamped_to_the_data():
    z = FIT.with_window(100.0, 300.0, 0.0, 20.0)
    p = z.panned(-100.0, 0.0)  # drag left by 100 px = 25 traces at 4 px/trace
    assert (p.trace_lo, p.trace_hi) == pytest.approx((125.0, 325.0))
    far = z.panned(-100_000.0, 0.0)
    assert (far.trace_lo, far.trace_hi) == (408.0, 608.0)
    up = z.panned(0.0, 100_000.0)
    assert up.time_lo == pytest.approx(-11.09)


def test_resized_keeps_the_window():
    r = FIT.with_window(100.0, 300.0, 0.0, 20.0).resized(400, 150)
    assert (r.width, r.height) == (400, 150)
    assert (r.trace_lo, r.trace_hi, r.time_lo, r.time_hi) == (100.0, 300.0, 0.0, 20.0)
    assert r.x_of_trace(300.0) == 400.0


def test_nice_ticks():
    np.testing.assert_allclose(nice_ticks(0.0, 10.13), [0, 2, 4, 6, 8, 10])
    np.testing.assert_allclose(nice_ticks(-11.09, 99.8), [0, 20, 40, 60, 80])
    np.testing.assert_allclose(nice_ticks(0.0, 4.0, target=8), [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
    assert nice_ticks(5.0, 5.0).size == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.view_transform'`

- [ ] **Step 3: Implement**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`:

```python
"""Trace/time <-> pixel mapping for the profile viewer. No Qt.

The visible window is [trace_lo, trace_hi) in trace-index units and
[time_lo, time_hi) in two-way time. Widget size is the image area only;
axis margins are the widget's business.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

MIN_TRACE_SPAN = 4.0
MIN_SAMPLE_SPAN = 4.0


@dataclass(frozen=True)
class ViewTransform:
    n_traces: int
    n_samples: int
    t0_ns: float
    dt_ns: float
    width: int
    height: int
    trace_lo: float
    trace_hi: float
    time_lo: float
    time_hi: float

    @classmethod
    def fit(
        cls, n_traces: int, n_samples: int, t0_ns: float, dt_ns: float, width: int, height: int
    ) -> ViewTransform:
        return cls(
            n_traces=n_traces,
            n_samples=n_samples,
            t0_ns=t0_ns,
            dt_ns=dt_ns,
            width=max(1, width),
            height=max(1, height),
            trace_lo=0.0,
            trace_hi=float(n_traces),
            time_lo=t0_ns,
            time_hi=t0_ns + n_samples * dt_ns,
        )

    @property
    def t_end(self) -> float:
        return self.t0_ns + self.n_samples * self.dt_ns

    # ---- forward and inverse ------------------------------------------------
    def x_of_trace(self, i: float) -> float:
        return (i - self.trace_lo) / (self.trace_hi - self.trace_lo) * self.width

    def trace_of_x(self, x: float) -> float:
        return self.trace_lo + x / self.width * (self.trace_hi - self.trace_lo)

    def y_of_time(self, t: float) -> float:
        return (t - self.time_lo) / (self.time_hi - self.time_lo) * self.height

    def time_of_y(self, y: float) -> float:
        return self.time_lo + y / self.height * (self.time_hi - self.time_lo)

    def trace_index_at(self, x: float) -> int:
        return int(min(self.n_traces - 1, max(0, math.floor(self.trace_of_x(x)))))

    def sample_index_at(self, y: float) -> int:
        s = math.floor((self.time_of_y(y) - self.t0_ns) / self.dt_ns)
        return int(min(self.n_samples - 1, max(0, s)))

    def source_rect(self) -> tuple[float, float, float, float]:
        """Visible window as (x, y, w, h) in image pixels: traces and samples."""
        y0 = (self.time_lo - self.t0_ns) / self.dt_ns
        y1 = (self.time_hi - self.t0_ns) / self.dt_ns
        return (self.trace_lo, y0, self.trace_hi - self.trace_lo, y1 - y0)

    # ---- window changes -----------------------------------------------------
    def with_window(
        self, trace_lo: float, trace_hi: float, time_lo: float, time_hi: float
    ) -> ViewTransform:
        t_span = min(max(trace_hi - trace_lo, MIN_TRACE_SPAN), float(self.n_traces))
        s_span = min(
            max(time_hi - time_lo, MIN_SAMPLE_SPAN * self.dt_ns), self.n_samples * self.dt_ns
        )
        lo = min(max(trace_lo, 0.0), self.n_traces - t_span)
        tlo = min(max(time_lo, self.t0_ns), self.t_end - s_span)
        return replace(self, trace_lo=lo, trace_hi=lo + t_span, time_lo=tlo, time_hi=tlo + s_span)

    def zoomed(self, factor: float, anchor_x: float, anchor_y: float) -> ViewTransform:
        """Scale both spans by 1/factor keeping the data point under the
        anchor pixel fixed. Clamped by with_window."""
        at = self.trace_of_x(anchor_x)
        tt = self.time_of_y(anchor_y)
        t_span = (self.trace_hi - self.trace_lo) / factor
        s_span = (self.time_hi - self.time_lo) / factor
        fx = anchor_x / self.width
        fy = anchor_y / self.height
        return self.with_window(at - fx * t_span, at - fx * t_span + t_span, tt - fy * s_span, tt - fy * s_span + s_span)

    def panned(self, dx_px: float, dy_px: float) -> ViewTransform:
        """Drag by (dx, dy) pixels: positive dx moves the data right, i.e.
        the window moves to lower trace indices."""
        dt = -dx_px / self.width * (self.trace_hi - self.trace_lo)
        ds = -dy_px / self.height * (self.time_hi - self.time_lo)
        return self.with_window(self.trace_lo + dt, self.trace_hi + dt, self.time_lo + ds, self.time_hi + ds)

    def resized(self, width: int, height: int) -> ViewTransform:
        return replace(self, width=max(1, width), height=max(1, height))


def nice_ticks(vmin: float, vmax: float, target: int = 6) -> np.ndarray:
    """Round tick positions covering [vmin, vmax] at a 1-2-5 step."""
    if not vmax > vmin:
        return np.array([], dtype=float)
    raw = (vmax - vmin) / max(1, target)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 5.0, 10.0):
        step = m * mag
        if step >= raw:
            break
    first = math.ceil(vmin / step - 1e-9) * step
    ticks = np.arange(first, vmax + step * 1e-9, step)
    return np.round(ticks, 10)
```

- [ ] **Step 4: Type-check and wire mypy**

Run: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
Expected: clean. Add the module to the mypy line in `.github/workflows/ci.yml`.

- [ ] **Step 5: Run, lint, commit**

Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis .github/workflows/ci.yml
git commit -m "feat: ViewTransform, the pure trace/time to pixel mapping

One frozen dataclass behind axes, cursor, selection, picking and the
gain strip, so 'which trace is under the mouse' has exactly one
implementation and it is tested without Qt. Zoom keeps the anchored
data point fixed; zoom and pan are clamped to the data."
```

---

### Task 14: `RadargramImage`, `ProfileView`, and the QImage wrapper

The custom `QWidget` viewer: draws a cached full-resolution image through the transform, axes on three sides, a cursor, a selection band, and pick markers. Pan and zoom draw a sub-rectangle of the cached image (3 ms per frame measured); only display-gain or stack changes re-run numpy.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/render/__init__.py` (docstring only)
- Create: `packages/nsgeo-qgis/nsgeo_qgis/render/qimage.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`

**Interfaces:**
- Consumes: `nsgeo.render` (`PercentileClip`, `colormap`, `to_rgb8`, `decimate_columns`, `DEFAULT_COLORMAP`), `Radargram`, `VelocityModel`, `ViewTransform`, `nice_ticks`, `event_pos`
- Produces: `rgb_to_qimage(rgb) -> QImage`; `RadargramImage(rg, percentile=99.0, colormap_name=DEFAULT_COLORMAP, max_width=8192)` with `.rg`, `.percentile`, `.colormap_name`, `.limit`, `.image` (lazy `QImage`), `.with_display(percentile=None, colormap_name=None)`, `.with_radargram(rg)`; `ProfileView(parent=None)` with signals `trace_hovered(int)`, `range_selected(int, int)`, `pick_requested(int, float)`, `view_changed()`, methods `set_axes(n_traces, n_samples, t0_ns, dt_ns, distance_along=None)`, `set_image(image | None)`, `set_velocity(model | None)`, `set_cursor(trace)`, `set_selection(a, b)`, `clear_selection()`, `set_picks(list[tuple[int, float]])`, `set_pick_mode(bool)`, `set_direction(int)`, `fit()`, `one_to_one()`, `image_rect() -> QRect`, `transform: ViewTransform | None`, `grab_image() -> QImage`; margins `MARGIN_LEFT=56, MARGIN_RIGHT=48, MARGIN_TOP=8, MARGIN_BOTTOM=28`; colours `CURSOR_COLOUR`, `SELECTION_COLOUR`, `PICK_COLOUR`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.io.dzt import read_header, read_samples
from nsgeo.model.survey import Profile
from nsgeo.processing import Radargram
from nsgeo.render import DEFAULT_COLORMAP
from nsgeo.velocity import VelocityModel
from plugin_testing import REAL_DZT, needs_real_data
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtTest import QTest

from nsgeo_qgis.render.qimage import RadargramImage, rgb_to_qimage
from nsgeo_qgis.ui.profile_view import (
    CURSOR_COLOUR,
    MARGIN_LEFT,
    MARGIN_TOP,
    ProfileView,
)


def _rg(n_traces=200, n_samples=128):
    rng = np.random.default_rng(3)
    data = rng.normal(size=(n_samples, n_traces))
    data[20:24, :] += 8.0
    return Radargram(data=data, dt_ns=0.5, t0_ns=-4.0)


def test_rgb_to_qimage_owns_its_memory_and_matches_pixels():
    rgb = np.zeros((2, 3, 3), dtype=np.uint8)
    rgb[0, 1] = (255, 0, 0)
    img = rgb_to_qimage(rgb)
    del rgb
    assert (img.width(), img.height()) == (3, 2)
    assert QColor(img.pixel(1, 0)).red() == 255 and QColor(img.pixel(0, 0)).red() == 0


def test_radargram_image_caches_and_rebuilds_on_display_change():
    ri = RadargramImage(_rg())
    img = ri.image
    assert img is ri.image  # cached
    assert (img.width(), img.height()) == (200, 128)
    ri2 = ri.with_display(percentile=95.0)
    assert ri2.rg is ri.rg and ri2.limit < ri.limit
    ri3 = ri.with_display(colormap_name="grey_white_high")
    assert ri3.image.pixel(0, 0) != img.pixel(0, 0) or ri3.colormap_name != DEFAULT_COLORMAP


def test_radargram_image_decimates_very_wide_lines():
    ri = RadargramImage(Radargram(data=np.zeros((8, 20_000)), dt_ns=0.5, t0_ns=0.0), max_width=4096)
    assert ri.image.width() <= 4096


@pytest.fixture
def view(qgis_app):
    v = ProfileView()
    v.resize(800, 300)
    v.show()
    rg = _rg()
    v.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns, distance_along=np.arange(rg.n_traces) / 60.0)
    v.set_image(RadargramImage(rg).image)
    return v, rg


def test_paints_the_image_inside_the_margins(view):
    v, rg = view
    shot = v.grab_image()
    r = v.image_rect()
    assert r.left() == MARGIN_LEFT and r.top() == MARGIN_TOP
    inside = [QColor(shot.pixel(r.left() + 5 + i, r.top() + 5 + j)).value() for i in range(20) for j in range(20)]
    assert np.std(inside) > 5  # radargram texture, not a flat fill
    margin = QColor(shot.pixel(5, r.top() + 5))
    assert margin.red() == margin.green() == margin.blue()  # axis gutter is neutral


def test_loading_state_when_there_is_no_image(qgis_app):
    v = ProfileView()
    v.resize(400, 200)
    v.set_axes(100, 50, 0.0, 0.5)
    v.set_image(None)
    v.grab_image()  # must not raise
    assert v.transform is not None and v.transform.n_traces == 100


def test_cursor_is_drawn_at_the_trace(view):
    v, rg = view
    v.set_cursor(100)
    shot = v.grab_image()
    r = v.image_rect()
    x = int(r.left() + v.transform.x_of_trace(100.5))
    column = [QColor(shot.pixel(x, r.top() + y)) for y in range(10, r.height() - 10, 7)]
    assert any(c.red() > 200 and c.blue() < 120 for c in column), CURSOR_COLOUR.name()


def test_mouse_move_emits_the_trace_under_the_cursor(view):
    v, rg = view
    got = []
    v.trace_hovered.connect(got.append)
    r = v.image_rect()
    QTest.mouseMove(v, QPoint(r.left() + r.width() // 2, r.top() + 20))
    assert got and got[-1] == v.transform.trace_index_at(r.width() // 2) == 100


def test_wheel_zooms_about_the_cursor_and_emits_view_changed(view):
    v, rg = view
    changed = []
    v.view_changed.connect(lambda: changed.append(1))
    r = v.image_rect()
    before = v.transform
    v.zoom_at(2.0, r.width() // 2, r.height() // 2)
    assert changed and v.transform.trace_hi - v.transform.trace_lo == pytest.approx(100.0)
    v.fit()
    assert (v.transform.trace_lo, v.transform.trace_hi) == (before.trace_lo, before.trace_hi)


def test_shift_click_and_pick_mode_request_picks(view):
    v, rg = view
    picks = []
    v.pick_requested.connect(lambda t, time_ns: picks.append((t, time_ns)))
    r = v.image_rect()
    p = QPoint(r.left() + 40, r.top() + 30)
    QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, p)
    assert len(picks) == 1 and picks[0][0] == v.transform.trace_index_at(40)
    assert picks[0][1] == pytest.approx(v.transform.time_of_y(30))
    v.set_pick_mode(True)
    QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    assert len(picks) == 2


def test_drag_selects_a_trace_range(view):
    v, rg = view
    sel = []
    v.range_selected.connect(lambda a, b: sel.append((a, b)))
    r = v.image_rect()
    QTest.mousePress(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(r.left() + 100, r.top() + 50))
    QTest.mouseMove(v, QPoint(r.left() + 300, r.top() + 50))
    QTest.mouseRelease(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(r.left() + 300, r.top() + 50))
    assert sel == [(28, 86)]  # floor(100/696*200), floor(300/696*200)


def test_depth_axis_uses_the_velocity_model(view):
    v, rg = view
    v.set_velocity(VelocityModel.constant(0.1))
    labels = v.depth_tick_labels()
    assert labels and labels[0].startswith("-") or labels[0] == "0"  # top of the record is above time zero


@needs_real_data
def test_real_file_renders_at_full_resolution(qgis_app):
    h = read_header(REAL_DZT[0])
    rg = Radargram.from_profile(Profile(data=read_samples(REAL_DZT[0])[0], header=h))
    ri = RadargramImage(rg)
    assert (ri.image.width(), ri.image.height()) == (rg.n_traces, 512)
    v = ProfileView()
    v.resize(900, 320)
    v.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns)
    v.set_image(ri.image)
    v.grab_image()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.render'`

- [ ] **Step 3: Implement the QImage wrapper**

Create `packages/nsgeo-qgis/nsgeo_qgis/render/__init__.py` with the docstring `"""The only place a numpy byte array becomes a QImage."""`.

Create `packages/nsgeo-qgis/nsgeo_qgis/render/qimage.py`:

```python
"""RGB byte array -> QImage, and a cache keyed on (radargram, display settings).

Everything numeric happens in nsgeo.render. Display gain (percentile,
colormap) is not a processing step and is never recorded in a stack.
"""

from __future__ import annotations

import numpy as np
from nsgeo.processing import Radargram
from nsgeo.render import DEFAULT_COLORMAP, PercentileClip, colormap, decimate_columns, to_rgb8
from qgis.PyQt.QtGui import QImage


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    h, w, _ = rgb.shape
    # QImage does not own the buffer; copy() so the array may be freed.
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class RadargramImage:
    """One radargram rendered once per display setting. Pan and zoom draw
    sub-rectangles of `image`; only a new radargram or a display change
    re-runs numpy."""

    def __init__(
        self,
        rg: Radargram,
        percentile: float = 99.0,
        colormap_name: str = DEFAULT_COLORMAP,
        max_width: int = 8192,
    ) -> None:
        self.rg = rg
        self.percentile = percentile
        self.colormap_name = colormap_name
        self.max_width = max_width
        self.limit = PercentileClip(percentile).limit(rg.data)
        self._image: QImage | None = None

    @property
    def image(self) -> QImage:
        if self._image is None:
            data = decimate_columns(self.rg.data, self.max_width)
            self._image = rgb_to_qimage(to_rgb8(data, self.limit, colormap(self.colormap_name)))
        return self._image

    def with_display(
        self, percentile: float | None = None, colormap_name: str | None = None
    ) -> RadargramImage:
        return RadargramImage(
            self.rg,
            self.percentile if percentile is None else percentile,
            self.colormap_name if colormap_name is None else colormap_name,
            self.max_width,
        )

    def with_radargram(self, rg: Radargram) -> RadargramImage:
        return RadargramImage(rg, self.percentile, self.colormap_name, self.max_width)
```

- [ ] **Step 4: Implement the view**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`:

```python
"""The profile viewer: a QWidget that paints a cached radargram image
through a ViewTransform, with axes, a cursor, a selection band and picks.

Measured: drawing a sub-rectangle of the cached image costs about 3 ms per
frame at any zoom, so pan and zoom never touch numpy.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from nsgeo.velocity import VelocityModel
from qgis.PyQt.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

from nsgeo_qgis.qtcompat import event_pos
from nsgeo_qgis.ui.view_transform import ViewTransform, nice_ticks

MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 56, 48, 8, 28
BACKGROUND = QColor(250, 250, 250)
AXIS_COLOUR = QColor(60, 60, 60)
CURSOR_COLOUR = QColor(255, 159, 26)
SELECTION_COLOUR = QColor(48, 140, 198, 60)
SELECTION_EDGE = QColor(48, 140, 198)
PICK_COLOUR = QColor(224, 66, 27)
DRAG_THRESHOLD_PX = 3


class ProfileView(QWidget):
    trace_hovered = pyqtSignal(int)
    range_selected = pyqtSignal(int, int)
    pick_requested = pyqtSignal(int, float)  # trace index, two-way time (ns)
    view_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(240, 120)
        self.transform: ViewTransform | None = None
        self._image: QImage | None = None
        self._distance: np.ndarray | None = None
        self._velocity: VelocityModel | None = None
        self._direction = 1
        self._cursor = -1
        self._selection = (-1, -1)
        self._picks: list[tuple[int, float]] = []
        self._pick_mode = False
        self._press: QPointF | None = None
        self._pan_last: QPointF | None = None
        self._dragging = False
        self._message = "no line open"

    # ---- state ------------------------------------------------------------
    def image_rect(self) -> QRect:
        return QRect(
            MARGIN_LEFT,
            MARGIN_TOP,
            max(1, self.width() - MARGIN_LEFT - MARGIN_RIGHT),
            max(1, self.height() - MARGIN_TOP - MARGIN_BOTTOM),
        )

    def set_axes(
        self,
        n_traces: int,
        n_samples: int,
        t0_ns: float,
        dt_ns: float,
        distance_along: np.ndarray | None = None,
    ) -> None:
        r = self.image_rect()
        self.transform = ViewTransform.fit(n_traces, n_samples, t0_ns, dt_ns, r.width(), r.height())
        self._distance = None if distance_along is None else np.asarray(distance_along, dtype=float)
        self._message = "loading…"
        self.view_changed.emit()
        self.update()

    def set_image(self, image: QImage | None) -> None:
        self._image = image
        self.update()

    def set_velocity(self, model: VelocityModel | None) -> None:
        self._velocity = model
        self.update()

    def set_direction(self, direction: int) -> None:
        self._direction = direction
        self.update()

    def set_cursor(self, trace: int) -> None:
        if trace != self._cursor:
            self._cursor = trace
            self.update()

    def set_selection(self, a: int, b: int) -> None:
        self._selection = (min(a, b), max(a, b)) if a >= 0 and b >= 0 else (-1, -1)
        self.update()

    def clear_selection(self) -> None:
        self.set_selection(-1, -1)

    def set_picks(self, picks: list[tuple[int, float]]) -> None:
        self._picks = list(picks)
        self.update()

    def set_pick_mode(self, flag: bool) -> None:
        self._pick_mode = flag
        self.setCursor(Qt.CursorShape.CrossCursor if flag else Qt.CursorShape.ArrowCursor)

    def clear(self) -> None:
        self.transform = None
        self._image = None
        self._cursor = -1
        self._selection = (-1, -1)
        self._picks = []
        self._message = "no line open"
        self.update()

    # ---- view changes -----------------------------------------------------
    def fit(self) -> None:
        if self.transform is None:
            return
        t = self.transform
        r = self.image_rect()
        self.transform = ViewTransform.fit(t.n_traces, t.n_samples, t.t0_ns, t.dt_ns, r.width(), r.height())
        self.view_changed.emit()
        self.update()

    def one_to_one(self) -> None:
        """One trace per pixel column, anchored at the current window's left."""
        if self.transform is None:
            return
        t = self.transform
        self.transform = t.with_window(t.trace_lo, t.trace_lo + t.width, t.time_lo, t.time_hi)
        self.view_changed.emit()
        self.update()

    def zoom_at(self, factor: float, x: float, y: float) -> None:
        if self.transform is None:
            return
        self.transform = self.transform.zoomed(factor, x, y)
        self.view_changed.emit()
        self.update()

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.transform is not None:
            r = self.image_rect()
            self.transform = self.transform.resized(r.width(), r.height())
            self.view_changed.emit()

    def grab_image(self) -> QImage:
        return self.grab().toImage()

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        r = self.image_rect()
        t = self.transform
        if t is None:
            painter.setPen(AXIS_COLOUR)
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._message)
            painter.end()
            return
        if self._image is not None:
            sx = self._image.width() / t.n_traces
            sy = self._image.height() / t.n_samples
            x, y, w, h = t.source_rect()
            painter.drawImage(QRectF(r), self._image, QRectF(x * sx, y * sy, w * sx, h * sy))
        else:
            painter.setPen(AXIS_COLOUR)
            painter.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self._message)
        painter.setClipRect(r)
        self._paint_selection(painter, r, t)
        self._paint_picks(painter, r, t)
        self._paint_cursor(painter, r, t)
        painter.setClipping(False)
        self._paint_axes(painter, r, t)
        painter.end()

    def _paint_cursor(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        if self._cursor < 0:
            return
        x = r.left() + t.x_of_trace(self._cursor + 0.5)
        p.setPen(QPen(CURSOR_COLOUR, 1.5))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

    def _paint_selection(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        a, b = self._selection
        if a < 0:
            return
        x0 = r.left() + t.x_of_trace(a)
        x1 = r.left() + t.x_of_trace(b + 1)
        p.fillRect(QRectF(x0, r.top(), x1 - x0, r.height()), SELECTION_COLOUR)
        p.setPen(QPen(SELECTION_EDGE, 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0, r.top()), QPointF(x0, r.bottom()))
        p.drawLine(QPointF(x1, r.top()), QPointF(x1, r.bottom()))

    def _paint_picks(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.setBrush(PICK_COLOUR)
        for trace, time_ns in self._picks:
            x = r.left() + t.x_of_trace(trace + 0.5)
            y = r.top() + t.y_of_time(time_ns)
            p.drawPolygon(QPointF(x, y), QPointF(x - 5, y - 9), QPointF(x + 5, y - 9))

    def _paint_axes(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        p.setPen(AXIS_COLOUR)
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        # left: two-way time
        p.drawLine(r.topLeft(), r.bottomLeft())
        for tick in nice_ticks(t.time_lo, t.time_hi):
            y = r.top() + t.y_of_time(float(tick))
            p.drawLine(QPointF(r.left() - 4, y), QPointF(r.left(), y))
            p.drawText(QRectF(0, y - 8, r.left() - 6, 16), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{tick:g}")
        p.drawText(QRectF(0, 0, r.left() - 6, MARGIN_TOP + 10), int(Qt.AlignmentFlag.AlignRight), "ns")
        # right: depth
        p.drawLine(r.topRight(), r.bottomRight())
        if self._velocity is not None:
            for label, y in self._depth_ticks(t):
                yy = r.top() + y
                p.drawLine(QPointF(r.right(), yy), QPointF(r.right() + 4, yy))
                p.drawText(QRectF(r.right() + 6, yy - 8, MARGIN_RIGHT - 8, 16), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            p.drawText(QRectF(r.right() + 6, 0, MARGIN_RIGHT - 8, MARGIN_TOP + 10), int(Qt.AlignmentFlag.AlignLeft), "m")
        # bottom: distance along the line, or trace index
        p.drawLine(r.bottomLeft(), r.bottomRight())
        for label, x in self._distance_ticks(t):
            xx = r.left() + x
            p.drawLine(QPointF(xx, r.bottom()), QPointF(xx, r.bottom() + 4))
            p.drawText(QRectF(xx - 30, r.bottom() + 6, 60, 14), int(Qt.AlignmentFlag.AlignHCenter), label)
        unit = "m" if self._distance is not None else "trace"
        arrow = "→" if self._direction == 1 else "←"
        p.drawText(QRectF(r.left(), r.bottom() + 14, r.width(), 14), int(Qt.AlignmentFlag.AlignHCenter), f"{unit} along line {arrow}")

    def _depth_ticks(self, t: ViewTransform) -> list[tuple[str, float]]:
        assert self._velocity is not None
        times = np.linspace(t.time_lo, t.time_hi, 512)
        depths = self._velocity.depth_at(times)
        out = []
        for d in nice_ticks(float(depths[0]), float(depths[-1])):
            time_ns = float(np.interp(d, depths, times))
            out.append((f"{d:g}", t.y_of_time(time_ns)))
        return out

    def depth_tick_labels(self) -> list[str]:
        if self.transform is None or self._velocity is None:
            return []
        return [label for label, _ in self._depth_ticks(self.transform)]

    def _distance_ticks(self, t: ViewTransform) -> list[tuple[str, float]]:
        lo, hi = t.trace_lo, t.trace_hi
        if self._distance is None:
            return [(f"{tick:g}", t.x_of_trace(float(tick))) for tick in nice_ticks(lo, hi)]
        idx = np.arange(t.n_traces, dtype=float)
        d = self._distance
        d_lo, d_hi = np.interp([lo, min(hi, t.n_traces - 1)], idx, d)
        order = np.argsort(d)
        out = []
        for tick in nice_ticks(min(d_lo, d_hi), max(d_lo, d_hi)):
            trace = float(np.interp(tick, d[order], idx[order]))
            out.append((f"{tick:g}", t.x_of_trace(trace)))
        return out

    # ---- mouse ------------------------------------------------------------
    def _local(self, event: Any) -> tuple[float, float]:
        pos = event_pos(event)
        r = self.image_rect()
        return pos.x() - r.left(), pos.y() - r.top()

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if self.transform is None:
            return
        x, y = self._local(event)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event_pos(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._pick_mode or shift:
                self.pick_requested.emit(self.transform.trace_index_at(x), self.transform.time_of_y(y))
                return
            self._press = event_pos(event)
            self._dragging = False

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self.transform is None:
            return
        pos = event_pos(event)
        x, y = self._local(event)
        if self._pan_last is not None:
            d = pos - self._pan_last
            self._pan_last = pos
            self.transform = self.transform.panned(d.x(), d.y())
            self.view_changed.emit()
            self.update()
            return
        if self._press is not None:
            if abs(pos.x() - self._press.x()) > DRAG_THRESHOLD_PX:
                self._dragging = True
                a = self.transform.trace_index_at(self._press.x() - self.image_rect().left())
                b = self.transform.trace_index_at(x)
                self.set_selection(a, b)
            return
        if 0 <= x < self.transform.width:
            self.trace_hovered.emit(self.transform.trace_index_at(x))

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = None
            return
        if self._press is not None and self.transform is not None:
            if self._dragging:
                a, b = self._selection
                self.range_selected.emit(a, b)
            self._press = None
            self._dragging = False

    def wheelEvent(self, event: Any) -> None:  # noqa: N802
        if self.transform is None:
            return
        x, y = self._local(event)
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_at(1.25**steps, x, y)
```

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean. If `test_mouse_move_emits_the_trace_under_the_cursor` gets no events, the widget needs `show()` before `QTest.mouseMove` (the fixture does this) and `setMouseTracking(True)` (the constructor does).

```bash
git add packages/nsgeo-qgis
git commit -m "feat: profile viewer widget with cached image, axes, cursor, picks

A custom QWidget paints a sub-rectangle of one cached full-resolution
QImage through ViewTransform, so pan and zoom never touch numpy (3 ms a
frame measured). Time on the left, depth on the right from the velocity
model, distance along the line below; Shift+click or pick mode requests
a pick; drag selects a trace range."
```

---

### Task 15: Profile dock and the M5 checkpoint

The viewer bound to the session: opens the current line, shows header-derived axes immediately and the image when samples arrive, re-renders on stack changes, and carries the display-gain controls. Ends M5: first sight of real data.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Consumes: `SiteSession`, `ProfileView`, `RadargramImage`, `colormap_names`, `resolve_velocity`
- Produces: `ProfileDock(session, parent=None)` with `view: ProfileView`, `percentile_slider: QSlider` (900–1000, tenths of a percent), `percentile_label`, `colormap_combo`, `fit_button`, `one_to_one_button`, `channel_combo`, `velocity_label`, `difference_label`, `current_radargram() -> Radargram | None`, `set_difference_index(int)` (−1 = result; used by Task 19), `percentile -> float`, `colormap_name -> str`, `image: RadargramImage | None`, signals `error(str)`, `pick_requested(str, int, float)`; `velocity_source(session, key) -> str`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from nsgeo.velocity import VelocityModel
from plugin_testing import synthetic_dzt

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.profile_dock import ProfileDock, velocity_source

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.08))


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=240)
    line = Line.open(p, GridPlacement("A", "y", 0.0, 0.0, -1, "FILE__001"))
    session.add_lines([line])
    key = session.keys()[0]
    session.open_line(key)
    return session, dock, key, line


def test_opening_shows_axes_and_loading_before_samples_arrive(opened):
    session, dock, key, line = opened
    assert "FILE__001" in dock.windowTitle()
    assert dock.view.transform is not None and dock.view.transform.n_traces == 240
    assert dock.image is None
    session.set_profiles(key, line.load())
    assert dock.image is not None
    assert dock.view.transform.n_samples == 512


def test_display_gain_rerenders_without_touching_the_stack(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    before = dock.image
    dock.percentile_slider.setValue(950)
    assert dock.percentile == pytest.approx(95.0)
    assert dock.image is not before and dock.image.rg is before.rg
    assert "95.0" in dock.percentile_label.text()
    dock.colormap_combo.setCurrentText("seismic")
    assert dock.image.colormap_name == "seismic"
    assert len(session.stack_for(key)) == 0


def test_stack_changes_rerender_and_axes_follow_the_result(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.append_step(key, build_step("time_zero", mode="sample", sample=40))
    assert dock.view.transform.n_samples == 472
    assert dock.image.rg.n_samples == 472


def test_step_errors_surface_as_a_signal_not_an_exception(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    errors = []
    dock.error.connect(errors.append)
    session.append_step(key, build_step("bandpass", low_mhz=100.0, high_mhz=90_000.0))
    assert errors and "Nyquist" in errors[0]
    assert dock.image is not None  # previous image kept


def test_velocity_label_names_its_source(opened):
    session, dock, key, line = opened
    assert velocity_source(session, key) == "Grid A"
    assert "0.080" in dock.velocity_label.text() and "Grid A" in dock.velocity_label.text()
    session.set_line_velocity(key, VelocityModel.constant(0.095))
    assert velocity_source(session, key) == "line override"
    assert "0.095" in dock.velocity_label.text()


def test_cursor_and_selection_follow_the_session_and_vice_versa(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    session.set_trace(key, 12)
    assert dock.view._cursor == 12
    dock.view.trace_hovered.emit(30)
    assert session.current_trace == 30
    dock.view.range_selected.emit(5, 9)
    assert session.selection == (5, 9)


def test_channel_combo_hidden_for_single_channel_files(opened):
    session, dock, key, line = opened
    session.set_profiles(key, line.load())
    assert dock.channel_combo.isHidden()


def test_closing_the_site_clears_the_view(opened):
    session, dock, key, line = opened
    session.close_site()
    assert dock.view.transform is None and dock.image is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.profile_dock'`

- [ ] **Step 3: Implement the dock**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:

```python
"""The profile dock: viewer plus display-gain controls, bound to the session.

Display gain lives here, not in the processing dock, because it changes the
colour mapping and never the data.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import Radargram, StepStack
from nsgeo.render import DEFAULT_COLORMAP, colormap_names
from nsgeo.velocity import VelocityModel
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.render.qimage import RadargramImage
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.profile_view import ProfileView


def velocity_source(session: SiteSession, key: str) -> str:
    line = session.line_for_key(key)
    if line.velocity is not None:
        return "line override"
    grid = session.grid_for_line(line)
    if grid is not None and grid.velocity is not None:
        return f"Grid {grid.id}"
    return f"header ε {line.header.epsr:g}"


class ProfileDock(QgsDockWidget):
    error = pyqtSignal(str)
    pick_requested = pyqtSignal(str, int, float)

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Profile", parent)
        self.setObjectName("nsgeoProfileDock")
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)
        self.session = session
        self.image: RadargramImage | None = None
        self._difference_index = -1
        self._key: str | None = None

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 2, 4, 4)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Display gain"))
        self.percentile_slider = QSlider(Qt.Orientation.Horizontal)
        self.percentile_slider.setRange(900, 1000)
        self.percentile_slider.setValue(990)
        self.percentile_slider.setFixedWidth(120)
        self.percentile_label = QLabel("99.0 %")
        bar.addWidget(self.percentile_slider)
        bar.addWidget(self.percentile_label)
        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(colormap_names())
        self.colormap_combo.setCurrentText(DEFAULT_COLORMAP)
        bar.addWidget(self.colormap_combo)
        self.difference_label = QLabel("")
        bar.addWidget(self.difference_label)
        self.fit_button = QPushButton("Fit")
        self.one_to_one_button = QPushButton("1:1")
        bar.addWidget(self.fit_button)
        bar.addWidget(self.one_to_one_button)
        self.channel_combo = QComboBox()
        self.channel_combo.hide()
        bar.addWidget(self.channel_combo)
        bar.addStretch(1)
        self.velocity_label = QLabel("")
        bar.addWidget(self.velocity_label)
        layout.addLayout(bar)
        self.view = ProfileView(body)
        layout.addWidget(self.view, 1)
        self.setWidget(body)

        self.percentile_slider.valueChanged.connect(self._display_changed)
        self.colormap_combo.currentTextChanged.connect(self._display_changed)
        self.fit_button.clicked.connect(self.view.fit)
        self.one_to_one_button.clicked.connect(self.view.one_to_one)
        self.channel_combo.currentIndexChanged.connect(self._channel_changed)
        self.view.trace_hovered.connect(self._hovered)
        self.view.range_selected.connect(self._range_selected)
        self.view.pick_requested.connect(self._pick)

        session.line_opened.connect(self._on_line_opened)
        session.line_loaded.connect(self._on_line_loaded)
        session.stack_changed.connect(self._on_stack_changed)
        session.trace_changed.connect(self._on_trace_changed)
        session.selection_changed.connect(self._on_selection_changed)
        session.lines_changed.connect(self._refresh_velocity)
        session.grids_changed.connect(self._refresh_velocity)
        session.site_closed.connect(self._clear)

    # ---- display settings -------------------------------------------------
    @property
    def percentile(self) -> float:
        return self.percentile_slider.value() / 10.0

    @property
    def colormap_name(self) -> str:
        return self.colormap_combo.currentText()

    def _display_changed(self, *_: Any) -> None:
        self.percentile_label.setText(f"{self.percentile:.1f} %")
        if self.image is not None:
            self.image = self.image.with_display(self.percentile, self.colormap_name)
            self.view.set_image(self.image.image)

    # ---- session events ---------------------------------------------------
    def _on_line_opened(self, key: str) -> None:
        self._key = key or None
        self._difference_index = -1
        self.difference_label.setText("")
        if not key:
            self._clear_view_only()
            return
        line = self.session.line_for_key(key)
        label = getattr(line.placement, "label", None) or line.path.stem
        self.setWindowTitle(f"nsgeo Profile · {label} · {line.n_traces} traces")
        self.view.set_direction(int(getattr(line.placement, "direction", 1)))
        self.image = None
        profiles = self.session.profiles_for(key)
        if profiles:
            self._configure_channels(len(profiles))
            self._render()
        else:
            self.channel_combo.hide()
            self.view.set_axes(
                line.n_traces, line.header.n_samples, line.header.position_ns, line.header.dt_ns, line.distance_along()
            )
            self.view.set_image(None)
        self._refresh_velocity()

    def _on_line_loaded(self, key: str) -> None:
        if key == self._key:
            profiles = self.session.profiles_for(key) or []
            self._configure_channels(len(profiles))
            self._render()

    def _on_stack_changed(self, key: str) -> None:
        if key == self._key:
            self._render()

    def _on_trace_changed(self, key: str, index: int) -> None:
        if key == self._key:
            self.view.set_cursor(index)

    def _on_selection_changed(self, key: str, a: int, b: int) -> None:
        if key == self._key:
            self.view.set_selection(a, b)

    def _clear(self) -> None:
        self._key = None
        self._clear_view_only()

    def _clear_view_only(self) -> None:
        self.image = None
        self.view.clear()
        self.setWindowTitle("nsgeo Profile")
        self.velocity_label.setText("")
        self.channel_combo.hide()

    # ---- rendering --------------------------------------------------------
    def set_difference_index(self, index: int) -> None:
        self._difference_index = index
        self._render()

    def current_radargram(self) -> Radargram | None:
        if self._key is None:
            return None
        stack: StepStack = self.session.stack_for(self._key)
        if stack.source is None:
            return None
        try:
            if self._difference_index >= 0:
                return stack.difference(self._difference_index)
            return stack.result()
        except ValueError as exc:
            self.error.emit(str(exc))
            if self._difference_index >= 0:
                self._difference_index = -1
                self.difference_label.setText("")
            return None

    def _render(self) -> None:
        rg = self.current_radargram()
        if rg is None:
            return
        if self._key is not None:
            line = self.session.line_for_key(self._key)
            distance = line.distance_along() if rg.n_traces == line.n_traces else None
        else:
            distance = None
        keep_window = self.view.transform is not None and self.view.transform.n_traces == rg.n_traces
        old = self.view.transform
        self.view.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, rg.dt_ns, distance)
        if keep_window and old is not None and old.n_samples == rg.n_samples:
            self.view.transform = old
        self.image = (
            self.image.with_radargram(rg)
            if self.image is not None
            else RadargramImage(rg, self.percentile, self.colormap_name)
        )
        self.view.set_image(self.image.image)
        step_text = ""
        if self._difference_index >= 0 and self._key is not None:
            entries = self.session.stack_for(self._key).entries
            step_text = f"Difference: {entries[self._difference_index][0].name}"
        self.difference_label.setText(step_text)

    def _refresh_velocity(self, *_: Any) -> None:
        if self._key is None or not self.session.is_open:
            return
        try:
            model: VelocityModel = self.session.resolved_velocity(self._key)
        except KeyError:
            return
        self.view.set_velocity(model)
        self.velocity_label.setText(
            f"v = {model.surface_velocity:.3f} m/ns ({velocity_source(self.session, self._key)})"
        )

    def _configure_channels(self, n: int) -> None:
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        for i in range(n):
            self.channel_combo.addItem(f"channel {i}", i)
        if self._key is not None:
            self.channel_combo.setCurrentIndex(self.session.channel(self._key))
        self.channel_combo.blockSignals(False)
        self.channel_combo.setVisible(n > 1)

    def _channel_changed(self, index: int) -> None:
        if self._key is not None and index >= 0:
            self.session.set_channel(self._key, index)

    # ---- viewer events ----------------------------------------------------
    def _hovered(self, trace: int) -> None:
        if self._key is not None:
            self.session.set_trace(self._key, trace)

    def _range_selected(self, a: int, b: int) -> None:
        if self._key is not None:
            self.session.set_selection(self._key, a, b)

    def _pick(self, trace: int, time_ns: float) -> None:
        if self._key is not None:
            self.pick_requested.emit(self._key, trace, time_ns)
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py` `initGui`, after the survey dock:

```python
        self.profile_dock = ProfileDock(self.session, main)
        self.profile_dock.error.connect(lambda msg: self.message(msg, Qgis.MessageLevel.Warning))
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.profile_dock)
        self.docks.append(self.profile_dock)
```

with `from nsgeo_qgis.ui.profile_dock import ProfileDock`, `self.profile_dock: ProfileDock | None = None` in `__init__`, and `self.profile_dock = None` in `unload`.

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: profile dock bound to the session

Opens the current line with header-derived axes before samples arrive,
renders when they do, re-renders on stack changes with axes following
the result (time_zero crops), and carries the display-gain controls
that never touch the stack. Step errors reach the message bar."
```

**M5 checkpoint (manual, 5 minutes).** Reload the plugin, open the site from M4, click FILE__001 in the tree. The profile dock shows axes at once and the raw radargram within a second: a dominant direct-wave band at the top, mid-grey below, exactly like the raw render in the Lavish mock. Drag the display-gain slider: the image remaps instantly. Wheel over the image: zoom about the cursor; middle-drag: pan; Fit and 1:1 restore. Hover: the status readout is not present yet (Plan 3), but nothing errors. The depth axis on the right starts at about −0.44 m because time zero has not been applied. Click another line: the viewer switches and the previous line reopens instantly from cache.

---

### Task 16: Processing dock — the stack list

The ordered, toggleable stack for the current line, bound to the session. Add (from the registry, never hardcoded), remove, reorder, enable, and apply to the grid. Steps with `REQUIRED` parameters are requested through a signal that Task 17 answers with a form.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`

**Interfaces:**
- Consumes: `SiteSession` stack methods, `available_steps`, `build_step`, `default_params`, `required_params`
- Produces: `ProcessingDock(session, parent=None)` with `list: QListWidget`, `add_button`, `add_menu`, `remove_button`, `up_button`, `down_button`, `apply_button`, `status: QLabel`, `form_area: QVBoxLayout` (Task 17 fills it), `key() -> str | None`, `current_row() -> int`, `rebuild()`, `add_step(name)`, `remove_selected()`, `move_selected(delta)`, `apply_to_grid(confirm=True) -> list[str]`, signals `step_selected(int)`, `add_step_requested(str)`; module function `dest_index(start, row) -> int`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import available_steps
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import Qt

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.processing_dock import ProcessingDock, dest_index

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5)))
    session.add_lines(lines)
    key = session.keys()[0]
    session.set_profiles(key, lines[0].load())
    session.open_line(key)
    return session, dock, key


def test_add_menu_lists_the_registry_and_marks_required_steps(opened):
    _, dock, _ = opened
    texts = [a.text() for a in dock.add_menu.actions()]
    assert [t.split(" ")[0] for t in texts] == available_steps()
    assert any(t.startswith("bandpass") and "needs values" in t for t in texts)
    assert not any(t.startswith("dewow") and "needs values" in t for t in texts)


def test_add_remove_toggle_and_reorder(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    dock.add_step("background_mean")
    dock.add_step("gain_agc")
    assert [dock.list.item(i).text() for i in range(3)] == ["dewow", "background_mean", "gain_agc"]
    dock.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert session.stack_for(key).entries[1][1] is False
    dock.list.setCurrentRow(2)
    dock.move_selected(-1)
    assert [s.name for s, _ in session.stack_for(key).entries] == ["dewow", "gain_agc", "background_mean"]
    assert dock.list.currentRow() == 1
    dock.remove_selected()
    assert [s.name for s, _ in session.stack_for(key).entries] == ["dewow", "background_mean"]


def test_required_steps_are_requested_not_built(opened):
    session, dock, key = opened
    asked = []
    dock.add_step_requested.connect(asked.append)
    dock.add_step("bandpass")
    assert asked == ["bandpass"] and len(session.stack_for(key)) == 0


def test_selection_emits_and_rebuild_keeps_it(opened):
    session, dock, key = opened
    got = []
    dock.step_selected.connect(got.append)
    dock.add_step("dewow")
    dock.add_step("gain_agc")
    dock.list.setCurrentRow(1)
    assert got[-1] == 1
    session.set_step_enabled(key, 0, False)  # triggers rebuild
    assert dock.list.currentRow() == 1


def test_dest_index_matches_qt_rows_moved_semantics():
    assert dest_index(start=0, row=3) == 2  # moved down past two rows
    assert dest_index(start=3, row=0) == 0  # moved up to the top
    assert dest_index(start=1, row=1) == 1


def test_apply_to_grid_copies_to_the_other_lines(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    changed = dock.apply_to_grid(confirm=False)
    assert len(changed) == 2
    for other in changed:
        assert session.stack_for(other).to_dicts() == session.stack_for(key).to_dicts()
    assert "2 line" in dock.status.text()


def test_switching_lines_shows_that_lines_stack(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    other = session.keys()[1]
    session.open_line(other)
    assert dock.list.count() == 0
    session.open_line(key)
    assert dock.list.count() == 1


def test_no_line_disables_the_controls(qgis_app):
    dock = ProcessingDock(SiteSession())
    assert not dock.add_button.isEnabled() and not dock.apply_button.isEnabled()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.processing_dock'`

- [ ] **Step 3: Implement the dock**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`:

```python
"""The processing dock: the current line's step stack.

Steps come from the registry, never from a hardcoded list. Every edit goes
through the session so the core's no-mutation rule holds and every other
view updates. Nothing here computes anything.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import available_steps, build_step, default_params, required_params
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nsgeo_qgis.session import SiteSession


def dest_index(start: int, row: int) -> int:
    """Translate QAbstractItemModel.rowsMoved's destination row (the row the
    item is inserted *before*, in pre-move numbering) into the index the
    item ends up at."""
    return row if row < start else row - 1


class ProcessingDock(QgsDockWidget):
    step_selected = pyqtSignal(int)  # -1 when nothing is selected
    add_step_requested = pyqtSignal(str)  # steps with REQUIRED params

    def __init__(self, session: SiteSession, parent: QWidget | None = None) -> None:
        super().__init__("nsgeo Processing", parent)
        self.setObjectName("nsgeoProcessingDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.session = session
        self._updating = False

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.add_button = QToolButton()
        self.add_button.setText("Add step")
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_menu = QMenu(self.add_button)
        for name in available_steps():
            text = f"{name}  (needs values)" if required_params(name) else name
            self.add_menu.addAction(text, lambda n=name: self.add_step(n))
        self.add_button.setMenu(self.add_menu)
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("↑")
        self.down_button = QPushButton("↓")
        for w in (self.add_button, self.remove_button, self.up_button, self.down_button):
            row.addWidget(w)
        row.addStretch(1)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.list)

        self.form_area = QVBoxLayout()
        layout.addLayout(self.form_area)

        bottom = QHBoxLayout()
        self.apply_button = QPushButton("Apply to grid…")
        bottom.addWidget(self.apply_button)
        bottom.addStretch(1)
        layout.addLayout(bottom)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setWidget(body)

        self.remove_button.clicked.connect(self.remove_selected)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.apply_button.clicked.connect(self.apply_to_grid)
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.currentRowChanged.connect(self._on_current_row)
        self.list.model().rowsMoved.connect(self._on_rows_moved)

        session.line_opened.connect(lambda _key: self.rebuild())
        session.stack_changed.connect(self._on_stack_changed)
        session.site_closed.connect(self.rebuild)
        self.rebuild()

    # ---- state ------------------------------------------------------------
    def key(self) -> str | None:
        return self.session.current_key if self.session.is_open else None

    def current_row(self) -> int:
        return self.list.currentRow()

    def rebuild(self) -> None:
        key = self.key()
        keep = self.list.currentRow()
        self._updating = True
        try:
            self.list.clear()
            if key is not None:
                for step, enabled in self.session.stack_for(key).entries:
                    item = QListWidgetItem(step.name)
                    item.setFlags(
                        Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsDragEnabled
                    )
                    item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                    self.list.addItem(item)
            if 0 <= keep < self.list.count():
                self.list.setCurrentRow(keep)
        finally:
            self._updating = False
        has_line = key is not None
        for w in (self.add_button, self.apply_button):
            w.setEnabled(has_line)
        self._update_row_buttons()
        self.step_selected.emit(self.list.currentRow())

    def _update_row_buttons(self) -> None:
        row = self.list.currentRow()
        n = self.list.count()
        self.remove_button.setEnabled(row >= 0)
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(0 <= row < n - 1)

    def _on_stack_changed(self, key: str) -> None:
        if key == self.key():
            self.rebuild()

    # ---- list events ------------------------------------------------------
    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._updating:
            return
        key = self.key()
        if key is None:
            return
        row = self.list.row(item)
        flag = item.checkState() == Qt.CheckState.Checked
        if self.session.stack_for(key).entries[row][1] != flag:
            self.session.set_step_enabled(key, row, flag)

    def _on_current_row(self, row: int) -> None:
        if not self._updating:
            self._update_row_buttons()
            self.step_selected.emit(row)

    def _on_rows_moved(self, _parent: Any, start: int, _end: int, _dest: Any, row: int) -> None:
        if self._updating:
            return
        key = self.key()
        if key is None:
            return
        dst = dest_index(start, row)
        if dst != start:
            self.session.move_step(key, start, dst)

    # ---- actions ----------------------------------------------------------
    def add_step(self, name: str) -> None:
        key = self.key()
        if key is None:
            return
        if required_params(name):
            self.add_step_requested.emit(name)
            return
        self.session.append_step(key, build_step(name, **default_params(name)))
        self.list.setCurrentRow(self.list.count() - 1)

    def remove_selected(self) -> None:
        key = self.key()
        row = self.list.currentRow()
        if key is None or row < 0:
            return
        self.session.remove_step(key, row)

    def move_selected(self, delta: int) -> None:
        key = self.key()
        row = self.list.currentRow()
        dst = row + delta
        if key is None or row < 0 or not 0 <= dst < self.list.count():
            return
        self.session.move_step(key, row, dst)
        self.list.setCurrentRow(dst)

    def apply_to_grid(self, confirm: bool = True) -> list[str]:
        key = self.key()
        if key is None:
            return []
        line = self.session.line_for_key(key)
        grid = self.session.grid_for_line(line)
        if grid is None:
            self.status.setText("this line is not in a grid")
            return []
        if confirm:
            answer = QMessageBox.question(
                self,
                "Apply to grid",
                f"Replace the processing stack of every other line in grid {grid.id} with this one?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return []
        changed = self.session.apply_stack_to_grid(key, grid.id)
        self.status.setText(f"applied to {len(changed)} line(s) in grid {grid.id}")
        return changed
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py` `initGui`, after the profile dock:

```python
        self.processing_dock = ProcessingDock(self.session, main)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.processing_dock)
        self.docks.append(self.processing_dock)
```

with the import, the `__init__` attribute, and `self.processing_dock = None` in `unload`.

- [ ] **Step 5: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: processing dock with the current line's step stack

Add from the registry (required-parameter steps are requested, not
built), remove, reorder by drag or buttons, enable/disable, apply to
the grid after confirmation. Every edit is a session call; the list is
rebuilt from the stack on each change."
```

---

### Task 17: Schema-driven parameter form and the add-step dialog

One generic form built from `schema()`. The same widget edits the selected step in the dock and collects `REQUIRED` values in a modal before a step enters the stack. The modal validates by building the step and applying it to a one-trace slice of the current radargram, which is how Nyquist and window errors surface before anything is added.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py`

**Interfaces:**
- Consumes: `get_step`, `build_step`, `ParamSpec`, `REQUIRED`, `identity_curve`, `Radargram`, `DztHeader`
- Produces: `ParamForm(parent=None)` with `set_step(name, params=None)`, `clear()`, `set_value(name, text)`, `values() -> dict`, `is_complete() -> bool`, `build()`, `commit()`, `editors: dict[str, QWidget]`, `message: QLabel`, `step_name`, signals `committed(dict)`, `error(str)`, `edited()`; `AddStepDialog(step_name, header=None, radargram=None, parent=None)` with `form`, `ok_button`, `facts: QLabel`, `result_step()`; `ProcessingDock` gains `form: ParamForm`, `build_add_dialog(name) -> AddStepDialog`, `append_from_dialog(dialog)`, `add_step_with_dialog(name)`, `time_axis() -> tuple[float, float, int]`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtWidgets import QComboBox, QLineEdit

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.add_step_dialog import AddStepDialog
from nsgeo_qgis.ui.param_form import ParamForm
from nsgeo_qgis.ui.processing_dock import ProcessingDock

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


def test_form_builds_editors_from_the_schema(qgis_app):
    f = ParamForm()
    f.set_step("time_zero")
    assert set(f.editors) == {"mode", "sample", "threshold"}
    assert isinstance(f.editors["mode"], QComboBox)
    assert isinstance(f.editors["sample"], QLineEdit)
    assert f.values() == {"mode": "first_break", "sample": 0, "threshold": 0.2}


def test_form_shows_current_values_and_commits_new_ones(qgis_app):
    f = ParamForm()
    f.set_step("gain_agc", build_step("gain_agc", window_ns=12.0).params)
    assert f.editors["window_ns"].text() == "12"  # floats are shown with :g
    got = []
    f.committed.connect(got.append)
    f.set_value("window_ns", "25")
    f.commit()
    assert got == [{"window_ns": 25.0, "target": 1.0, "eps": 1e-12}]


def test_form_reports_bad_input_instead_of_raising(qgis_app):
    f = ParamForm()
    f.set_step("dewow")
    errors = []
    f.error.connect(errors.append)
    f.set_value("window_ns", "abc")
    f.commit()
    assert errors and "window" in errors[0].lower()
    assert "window" in f.message.text().lower()


def test_required_fields_start_blank_and_block_completion(qgis_app):
    f = ParamForm()
    f.set_step("bandpass")
    assert f.editors["low_mhz"].text() == "" and f.editors["taper_frac"].text() == "0.25"
    assert not f.is_complete()
    f.set_value("low_mhz", "100")
    f.set_value("high_mhz", "600")
    assert f.is_complete()
    assert f.build().params["high_mhz"] == 600.0


def test_add_step_dialog_shows_header_facts_and_validates_against_nyquist(qgis_app, tmp_path):
    p = synthetic_dzt(tmp_path, "L.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    from nsgeo.processing import Radargram

    rg = Radargram.from_profile(line.load()[0])
    d = AddStepDialog("bandpass", header=line.header, radargram=rg)
    assert "HS350US" in d.facts.text() and "Nyquist" in d.facts.text()
    assert not d.ok_button.isEnabled()
    d.form.set_value("low_mhz", "100")
    d.form.set_value("high_mhz", "5000")  # above the ~2309 MHz Nyquist
    assert not d.ok_button.isEnabled() and "Nyquist" in d.form.message.text()
    d.form.set_value("high_mhz", "600")
    assert d.ok_button.isEnabled()
    step = d.result_step()
    assert step.name == "bandpass" and step.params["low_mhz"] == 100.0


@pytest.fixture
def opened(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProcessingDock(session)
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    return session, dock, key


def test_dock_form_edits_the_selected_step_through_replace_step(opened):
    session, dock, key = opened
    dock.add_step("dewow")
    dock.list.setCurrentRow(0)
    assert dock.form.step_name == "dewow"
    before = session.stack_for(key).entries[0][0]
    dock.form.set_value("window_ns", "7.5")
    dock.form.commit()
    after = session.stack_for(key).entries[0][0]
    assert after is not before and after.params["window_ns"] == 7.5


def test_dock_adds_required_steps_through_the_dialog(opened):
    session, dock, key = opened
    dialog = dock.build_add_dialog("bandpass")
    dialog.form.set_value("low_mhz", "100")
    dialog.form.set_value("high_mhz", "600")
    dock.append_from_dialog(dialog)
    assert [s.name for s, _ in session.stack_for(key).entries] == ["bandpass"]


def test_dock_seeds_a_curve_step_with_the_identity(opened):
    session, dock, key = opened
    dock.add_step_with_dialog("gain_curve")
    step = session.stack_for(key).entries[0][0]
    t0, dt, n = dock.time_axis()
    assert step.params["points"] == [[t0, 0.0], [t0 + dt * (n - 1), 0.0]]
    assert t0 == pytest.approx(-11.086, abs=1e-3)
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.add_step_dialog'`

- [ ] **Step 3: Implement the form**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`:

```python
"""One generic parameter form, built from a step's schema().

No step name appears here. `kind` picks the editor: float and int are line
edits (so a REQUIRED field can be blank), choice is a combo box, curve is a
label pointing at the gain strip. Commit builds the step through the core,
so the core's validation is the only validation.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import REQUIRED, ParamSpec, build_step, get_step
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

REQUIRED_STYLE = "QLineEdit { border: 1px solid #d1702f; background: #fff8f2; }"


class ParamForm(QWidget):
    committed = pyqtSignal(dict)
    error = pyqtSignal(str)
    edited = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 0)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #b35c00;")
        self.editors: dict[str, QWidget] = {}
        self._specs: tuple[ParamSpec, ...] = ()
        self._curve_value: Any = None
        self.step_name: str | None = None
        self._updating = False

    # ---- building ---------------------------------------------------------
    def clear(self) -> None:
        while self._layout.rowCount():
            self._layout.removeRow(0)
        self.editors = {}
        self._specs = ()
        self._curve_value = None
        self.step_name = None
        self.message.setText("")

    def set_step(self, name: str, params: dict[str, Any] | None = None) -> None:
        self.clear()
        self.step_name = name
        self._specs = get_step(name).schema()
        self._updating = True
        try:
            for spec in self._specs:
                value = params[spec.name] if params and spec.name in params else spec.default
                editor = self._make_editor(spec, value)
                self.editors[spec.name] = editor
                label = f"{spec.label} ({spec.unit})" if spec.unit else spec.label
                editor.setToolTip(spec.help)
                self._layout.addRow(label, editor)
            self._layout.addRow(self.message)
        finally:
            self._updating = False

    def _make_editor(self, spec: ParamSpec, value: Any) -> QWidget:
        if spec.kind == "choice":
            combo = QComboBox()
            for choice in spec.choices:
                combo.addItem(choice, choice)
            if value is not REQUIRED:
                combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.currentIndexChanged.connect(self._on_edited)
            combo.currentIndexChanged.connect(self.commit)
            return combo
        if spec.kind == "curve":
            self._curve_value = None if value is REQUIRED else value
            return QLabel("edited in the profile viewer's gain strip")
        edit = QLineEdit()
        if value is REQUIRED:
            edit.setPlaceholderText("required")
            edit.setStyleSheet(REQUIRED_STYLE)
        else:
            edit.setText(f"{value:g}" if isinstance(value, float) else str(value))
        edit.textChanged.connect(self._on_edited)
        edit.editingFinished.connect(self.commit)
        return edit

    def _on_edited(self, *_: Any) -> None:
        if not self._updating:
            self.edited.emit()

    # ---- values -----------------------------------------------------------
    def set_value(self, name: str, text: str) -> None:
        editor = self.editors[name]
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findData(text)))
        elif isinstance(editor, QLineEdit):
            editor.setText(text)

    def is_complete(self) -> bool:
        for spec in self._specs:
            editor = self.editors[spec.name]
            if isinstance(editor, QLineEdit) and not editor.text().strip():
                return False
            if spec.kind == "curve" and self._curve_value is None:
                return False
        return True

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for spec in self._specs:
            editor = self.editors[spec.name]
            if spec.kind == "choice":
                assert isinstance(editor, QComboBox)
                out[spec.name] = editor.currentData()
            elif spec.kind == "curve":
                if self._curve_value is None:
                    raise ValueError(f"{spec.label}: no control points yet")
                out[spec.name] = self._curve_value
            else:
                assert isinstance(editor, QLineEdit)
                text = editor.text().strip().replace(",", ".")
                if not text:
                    raise ValueError(f"{spec.label} is required")
                try:
                    out[spec.name] = int(text) if spec.kind == "int" else float(text)
                except ValueError:
                    raise ValueError(f"{spec.label}: {text!r} is not a number") from None
        return out

    def build(self) -> Any:
        """The step, or None with `message` and `error` set."""
        if self.step_name is None:
            return None
        try:
            step = build_step(self.step_name, **self.values())
        except (ValueError, TypeError) as exc:
            self.message.setText(str(exc))
            self.error.emit(str(exc))
            return None
        self.message.setText("")
        return step

    def commit(self, *_: Any) -> None:
        if self._updating:
            return
        step = self.build()
        if step is not None:
            self.committed.emit(step.params)
```

- [ ] **Step 4: Implement the dialog**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py`:

```python
"""Collect REQUIRED parameters before a step enters the stack.

Blank fields, header facts as read-only reference, OK disabled until the
core builds the step and applies it to a one-trace slice of the current
radargram without error. Nothing is guessed on the user's behalf.
"""

from __future__ import annotations

from typing import Any

from nsgeo.io.dzt import DztHeader
from nsgeo.processing import Radargram
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from nsgeo_qgis.ui.param_form import ParamForm


def header_facts(header: DztHeader) -> str:
    nyquist = 500.0 / header.dt_ns
    return (
        f"From this file's header: antenna {header.antenna or '?'} · sample interval "
        f"{header.dt_ns:.4f} ns · Nyquist {nyquist:.0f} MHz · {header.n_samples} samples"
    )


class AddStepDialog(QDialog):
    def __init__(
        self,
        step_name: str,
        header: DztHeader | None = None,
        radargram: Radargram | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Add step: {step_name}")
        self.radargram = radargram
        layout = QVBoxLayout(self)
        self.form = ParamForm(self)
        self.form.set_step(step_name)
        layout.addWidget(self.form)
        self.facts = QLabel(header_facts(header) if header is not None else "")
        self.facts.setWordWrap(True)
        layout.addWidget(self.facts)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.form.edited.connect(self._validate)
        self._validate()

    def _validate(self, *_: Any) -> None:
        if not self.form.is_complete():
            self.form.message.setText("")
            self.ok_button.setEnabled(False)
            return
        step = self.form.build()
        if step is None:
            self.ok_button.setEnabled(False)
            return
        if self.radargram is not None:
            probe = self.radargram.replace(data=self.radargram.data[:, :1])
            try:
                step.apply(probe)
            except ValueError as exc:
                self.form.message.setText(str(exc))
                self.ok_button.setEnabled(False)
                return
        self.ok_button.setEnabled(True)

    def result_step(self) -> Any:
        return self.form.build()
```

- [ ] **Step 5: Put the form in the dock and route required steps**

In `processing_dock.py`, add imports `from nsgeo.processing import Radargram, get_step` (extend the existing line) and `from nsgeo_qgis.lookup import identity_curve`, `from nsgeo_qgis.ui.add_step_dialog import AddStepDialog`, `from nsgeo_qgis.ui.param_form import ParamForm`. In `__init__`, after `self.form_area`:

```python
        self.form = ParamForm(body)
        self.form_area.addWidget(self.form)
        self.form.committed.connect(self._on_form_committed)
        self.step_selected.connect(self._show_form)
        self.add_step_requested.connect(self.add_step_with_dialog)
```

and add these methods:

```python
    def _show_form(self, row: int) -> None:
        key = self.key()
        if key is None or row < 0:
            self.form.clear()
            return
        step, _ = self.session.stack_for(key).entries[row]
        self.form.set_step(step.name, step.params)

    def _on_form_committed(self, params: dict[str, Any]) -> None:
        key = self.key()
        row = self.list.currentRow()
        if key is None or row < 0 or self.form.step_name is None:
            return
        current = self.session.stack_for(key).entries[row][0]
        if current.params == params:
            return
        self.session.replace_step(key, row, build_step(self.form.step_name, **params))

    def time_axis(self) -> tuple[float, float, int]:
        """(t0_ns, dt_ns, n_samples) of the current line: the stack's source
        when loaded, else the header."""
        key = self.key()
        assert key is not None
        source = self.session.stack_for(key).source
        if source is not None:
            return source.t0_ns, source.dt_ns, source.n_samples
        h = self.session.line_for_key(key).header
        return h.position_ns, h.dt_ns, h.n_samples

    def build_add_dialog(self, name: str) -> AddStepDialog:
        key = self.key()
        assert key is not None
        line = self.session.line_for_key(key)
        return AddStepDialog(name, header=line.header, radargram=self.session.stack_for(key).source, parent=self)

    def append_from_dialog(self, dialog: AddStepDialog) -> None:
        key = self.key()
        step = dialog.result_step()
        if key is None or step is None:
            return
        self.session.append_step(key, step)
        self.list.setCurrentRow(self.list.count() - 1)

    def add_step_with_dialog(self, name: str) -> None:
        key = self.key()
        if key is None:
            return
        specs = get_step(name).schema()
        required = [s for s in specs if s.required]
        if required and all(s.kind == "curve" for s in required):
            # The identity curve is not a guess: seed it and let the strip edit it.
            t0, dt, n = self.time_axis()
            params = {s.name: identity_curve(t0, dt, n) for s in required}
            params.update(default_params(name))
            self.session.append_step(key, build_step(name, **params))
            self.list.setCurrentRow(self.list.count() - 1)
            return
        dialog = self.build_add_dialog(name)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.append_from_dialog(dialog)
```

(`QDialog` joins the `qgis.PyQt.QtWidgets` import; `Radargram` is only needed for the type of `source`, drop it if ruff flags it unused.)

- [ ] **Step 6: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: schema-driven parameter form and add-step dialog

One generic form built from schema(); no step name appears in plugin
code. Required parameters start blank with the header's antenna and
Nyquist shown as reference, and OK stays disabled until the core builds
the step and applies it to a one-trace probe. Curve-kind steps are
seeded with the identity instead of a dialog."
```

---

### Task 18: Gain-curve strip beside the profile

A vertical panel sharing the viewer's time mapping, visible while a curve-kind step is selected. Drag points, watch the image update; the change goes through `replace_step`. Control points are in absolute two-way time, the same axis the viewer draws.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py`

**Interfaces:**
- Consumes: `ViewTransform`, `MARGIN_TOP`, `event_pos`
- Produces: `GainStrip(parent=None)` with `set_time_mapping(transform, top_px)`, `set_points(points)`, `points() -> list[list[float]]`, `x_of_db`, `db_of_x`, `y_of_time`, `time_of_y`, `handle_at(pos) -> int | None`, signal `points_changed(list)`; `ProfileDock` gains `gain_strip: GainStrip`, `show_gain_strip(points | None)`, signal `gain_points_changed(list)`; `NsgeoPlugin` gains `_sync_gain_strip(row)`, `_curve_param_name(step) -> str | None`

- [ ] **Step 1: Write the failing test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py`:

```python
from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import synthetic_dzt
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest

from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.gain_strip import GainStrip
from nsgeo_qgis.ui.profile_dock import ProfileDock
from nsgeo_qgis.ui.profile_view import MARGIN_TOP
from nsgeo_qgis.ui.view_transform import ViewTransform

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def strip(qgis_app):
    s = GainStrip()
    s.resize(96, 300 + MARGIN_TOP + 28)
    s.show()
    t = ViewTransform.fit(100, 200, 0.0, 0.5, 600, 300)
    s.set_time_mapping(t, MARGIN_TOP)
    s.set_points([[0.0, 0.0], [100.0, 20.0]])
    return s


def test_mappings_round_trip(strip):
    assert strip.time_of_y(strip.y_of_time(37.0)) == pytest.approx(37.0)
    assert strip.db_of_x(strip.x_of_db(12.0)) == pytest.approx(12.0)
    assert strip.y_of_time(0.0) == MARGIN_TOP


def test_dragging_a_handle_moves_its_point_and_emits(strip):
    got = []
    strip.points_changed.connect(got.append)
    x0, y0 = strip.x_of_db(20.0), strip.y_of_time(100.0)
    assert strip.handle_at(QPoint(int(x0), int(y0))) == 1
    QTest.mousePress(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x0), int(y0)))
    QTest.mouseMove(strip, QPoint(int(strip.x_of_db(30.0)), int(y0)))
    QTest.mouseRelease(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(strip.x_of_db(30.0)), int(y0)))
    assert got and got[-1][1][1] == pytest.approx(30.0, abs=0.5)
    assert strip.points()[1][0] == pytest.approx(100.0, abs=0.5)


def test_double_click_adds_and_right_click_removes(strip):
    got = []
    strip.points_changed.connect(got.append)
    mid = QPoint(int(strip.x_of_db(10.0)), int(strip.y_of_time(50.0)))
    QTest.mouseDClick(strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, mid)
    assert len(strip.points()) == 3 and got[-1][1][0] == pytest.approx(50.0, abs=0.5)
    QTest.mouseClick(strip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, mid)
    assert len(strip.points()) == 2
    QTest.mouseClick(strip, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(int(strip.x_of_db(0.0)), int(strip.y_of_time(0.0))))
    assert len(strip.points()) == 2  # never below two


def test_profile_dock_shows_the_strip_only_when_asked(qgis_app, tmp_path):
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    session.add_lines([line])
    key = session.keys()[0]
    session.set_profiles(key, line.load())
    session.open_line(key)
    assert dock.gain_strip.isHidden()
    dock.show_gain_strip([[-11.0, 0.0], [99.0, 0.0]])
    assert not dock.gain_strip.isHidden()
    assert dock.gain_strip.y_of_time(-11.0) == pytest.approx(MARGIN_TOP + dock.view.transform.y_of_time(-11.0))
    changed = []
    dock.gain_points_changed.connect(changed.append)
    dock.gain_strip.set_points([[-11.0, 0.0], [99.0, 12.0]])
    dock.gain_strip.points_changed.emit(dock.gain_strip.points())
    assert changed and changed[0][1][1] == 12.0
    dock.show_gain_strip(None)
    assert dock.gain_strip.isHidden()


def test_plugin_routes_strip_edits_through_replace_step(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT")
    line = Line.open(p, GridPlacement("A", "y", 0.0))
    s.add_lines([line])
    key = s.keys()[0]
    s.set_profiles(key, line.load())
    s.open_line(key)
    plugin.processing_dock.add_step("dewow")
    plugin.processing_dock.add_step_with_dialog("gain_curve")
    plugin.processing_dock.list.setCurrentRow(1)
    assert not plugin.profile_dock.gain_strip.isHidden()
    plugin.profile_dock.gain_strip.set_points([[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]])
    plugin.profile_dock.gain_strip.points_changed.emit(plugin.profile_dock.gain_strip.points())
    assert s.stack_for(key).entries[1][0].params["points"][1] == [50.0, 6.0]
    plugin.processing_dock.list.setCurrentRow(0)
    assert plugin.profile_dock.gain_strip.isHidden()
    plugin.unload()
```

- [ ] **Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.gain_strip'`

- [ ] **Step 3: Implement the strip**

Create `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py`:

```python
"""Gain-curve editor sharing the profile viewer's time axis.

Control points are (two-way time ns, gain dB). Vertical position is the
viewer's own mapping, so a point sits exactly beside the sample it affects.
Drag to move, double-click to add, right-click to remove (never below two).
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import QPointF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

from nsgeo_qgis.qtcompat import event_pos
from nsgeo_qgis.ui.view_transform import ViewTransform

HANDLE_RADIUS = 5
HIT_RADIUS = 8
PAD_X = 10
CURVE_COLOUR = QColor(48, 140, 198)
ZERO_COLOUR = QColor(160, 160, 160)


class GainStrip(QWidget):
    points_changed = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(96)
        self.setMouseTracking(True)
        self._points: list[list[float]] = []
        self._transform: ViewTransform | None = None
        self._top = 0.0
        self._drag: int | None = None

    # ---- mappings ---------------------------------------------------------
    def set_time_mapping(self, transform: ViewTransform, top_px: float) -> None:
        self._transform = transform
        self._top = float(top_px)
        self.update()

    def set_points(self, points: list[list[float]]) -> None:
        self._points = sorted([[float(t), float(db)] for t, db in points], key=lambda p: p[0])
        self.update()

    def points(self) -> list[list[float]]:
        return [list(p) for p in self._points]

    def _db_range(self) -> tuple[float, float]:
        dbs = [p[1] for p in self._points] or [0.0]
        return min(-6.0, min(dbs) - 6.0), max(24.0, max(dbs) + 6.0)

    def x_of_db(self, db: float) -> float:
        lo, hi = self._db_range()
        return PAD_X + (db - lo) / (hi - lo) * (self.width() - 2 * PAD_X)

    def db_of_x(self, x: float) -> float:
        lo, hi = self._db_range()
        return lo + (x - PAD_X) / (self.width() - 2 * PAD_X) * (hi - lo)

    def y_of_time(self, t: float) -> float:
        assert self._transform is not None
        return self._top + self._transform.y_of_time(t)

    def time_of_y(self, y: float) -> float:
        assert self._transform is not None
        return self._transform.time_of_y(y - self._top)

    def handle_at(self, pos: Any) -> int | None:
        if self._transform is None:
            return None
        best, best_d = None, HIT_RADIUS + 1.0
        for i, (t, db) in enumerate(self._points):
            d = ((self.x_of_db(db) - pos.x()) ** 2 + (self.y_of_time(t) - pos.y()) ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        return best

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(250, 250, 250))
        if self._transform is None or not self._points:
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        x0 = self.x_of_db(0.0)
        p.setPen(QPen(ZERO_COLOUR, 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0, 0), QPointF(x0, self.height()))
        pts = [QPointF(self.x_of_db(db), self.y_of_time(t)) for t, db in self._points]
        # hold the end values outside the control range, like np.interp does
        ext = [QPointF(pts[0].x(), 0.0), *pts, QPointF(pts[-1].x(), self.height())]
        p.setPen(QPen(CURVE_COLOUR, 2))
        p.drawPolyline(*ext)
        p.setBrush(QColor(255, 255, 255))
        for q in pts:
            p.drawEllipse(q, HANDLE_RADIUS, HANDLE_RADIUS)
        p.setPen(QColor(90, 90, 90))
        lo, hi = self._db_range()
        p.drawText(2, 12, f"{lo:g}")
        p.drawText(self.width() - 26, 12, f"{hi:g} dB")
        p.end()

    # ---- mouse ------------------------------------------------------------
    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if self._transform is None:
            return
        pos = event_pos(event)
        hit = self.handle_at(pos)
        if event.button() == Qt.MouseButton.RightButton:
            if hit is not None and len(self._points) > 2:
                del self._points[hit]
                self.update()
                self.points_changed.emit(self.points())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = hit

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        if self._transform is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event_pos(event)
        if self.handle_at(pos) is not None:
            return
        self._points.append([self.time_of_y(pos.y()), self.db_of_x(pos.x())])
        self._points.sort(key=lambda q: q[0])
        self._drag = None
        self.update()
        self.points_changed.emit(self.points())

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag is None or self._transform is None:
            return
        pos = event_pos(event)
        self._points[self._drag] = [self.time_of_y(pos.y()), self.db_of_x(pos.x())]
        self.update()
        self.points_changed.emit(self.points())  # live: one broadcast multiply per move

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._points.sort(key=lambda q: q[0])
            self.update()
            self.points_changed.emit(self.points())
```

- [ ] **Step 4: Add the strip to the profile dock**

In `profile_dock.py`: import `GainStrip` and `MARGIN_TOP`; add `gain_points_changed = pyqtSignal(list)` to the signals; replace `layout.addWidget(self.view, 1)` with

```python
        viewer_row = QHBoxLayout()
        viewer_row.setSpacing(0)
        self.view = ProfileView(body)
        viewer_row.addWidget(self.view, 1)
        self.gain_strip = GainStrip(body)
        self.gain_strip.hide()
        viewer_row.addWidget(self.gain_strip)
        layout.addLayout(viewer_row, 1)
```

(and delete the earlier `self.view = ProfileView(body)` line), then connect in `__init__`:

```python
        self.view.view_changed.connect(self._sync_strip_mapping)
        self.gain_strip.points_changed.connect(self.gain_points_changed.emit)
```

and add:

```python
    def _sync_strip_mapping(self) -> None:
        if self.view.transform is not None:
            self.gain_strip.set_time_mapping(self.view.transform, MARGIN_TOP)

    def show_gain_strip(self, points: list[list[float]] | None) -> None:
        if points is None or self.view.transform is None:
            self.gain_strip.hide()
            return
        self._sync_strip_mapping()
        self.gain_strip.set_points(points)
        self.gain_strip.show()
```

Also call `self._sync_strip_mapping()` at the end of `_render()` so the strip follows axis changes.

- [ ] **Step 5: Route it in the plugin**

In `plugin.py` `initGui`, after both docks exist:

```python
        self.processing_dock.step_selected.connect(self._sync_gain_strip)
        self.profile_dock.gain_points_changed.connect(self._on_gain_points)
```

and add:

```python
    @staticmethod
    def _curve_param_name(step: Any) -> str | None:
        """The name of a step's curve-kind parameter, if it has one. Decided
        by the schema's kind, never by the step's name."""
        for spec in type(step).schema():
            if spec.kind == "curve":
                return str(spec.name)
        return None

    def _sync_gain_strip(self, row: int) -> None:
        assert self.session is not None and self.profile_dock is not None
        key = self.session.current_key
        if key is None or row < 0:
            self.profile_dock.show_gain_strip(None)
            return
        entries = self.session.stack_for(key).entries
        if row >= len(entries):
            self.profile_dock.show_gain_strip(None)
            return
        step = entries[row][0]
        name = self._curve_param_name(step)
        self.profile_dock.show_gain_strip(step.params[name] if name else None)

    def _on_gain_points(self, points: list) -> None:
        assert self.session is not None and self.processing_dock is not None
        key = self.session.current_key
        row = self.processing_dock.current_row()
        if key is None or row < 0:
            return
        step = self.session.stack_for(key).entries[row][0]
        name = self._curve_param_name(step)
        if name is None:
            return
        params = dict(step.params)
        params[name] = points
        try:
            self.session.replace_step(key, row, build_step(step.name, **params))
        except ValueError as exc:
            self.message(str(exc), Qgis.MessageLevel.Warning)
```

with `from nsgeo.processing import build_step`.

- [ ] **Step 6: Run, lint, commit**

Run: `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all PASS, clean.

```bash
git add packages/nsgeo-qgis
git commit -m "feat: gain-curve strip beside the profile, sharing its time axis

Control points are in absolute two-way time, so the strip borrows the
viewer's ViewTransform and a point sits beside the sample it affects.
Drags go through replace_step on every move (one broadcast multiply
when gain is last). Which step has a curve is decided by schema kind,
never by name."
```

---

### Task 19: Difference view, presets, and the M6 checkpoint

The difference view shows what a step removed, presets are named stacks saved in the survey JSON, and the root README stops saying nothing works. Ends M6: real data processable.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Site.presets`)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (serialise presets)
- Create: `packages/nsgeo-core/tests/test_presets.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (preset methods, `presets_changed`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (difference toggle, presets menu)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`difference_cleared`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Modify: `README.md`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py`

**Interfaces:**
- Consumes: `StepStack.difference`, `StepStack.to_dicts/from_dicts`
- Produces: `Site.presets: dict[str, list[dict[str, Any]]]`; JSON key `"presets"`; `SiteSession.preset_names()`, `save_preset(name, key)`, `apply_preset(name, key)`, `delete_preset(name)`, signal `presets_changed()`; `ProcessingDock.diff_button: QToolButton` (checkable), signal `difference_toggled(int)`, `presets_button`, `presets_menu`, `save_preset_named(name)`, `apply_preset_named(name)`; `ProfileDock.difference_cleared` signal

- [ ] **Step 1: Write the failing core test**

Create `packages/nsgeo-core/tests/test_presets.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site
from nsgeo.processing import StepStack, build_step
from nsgeo.project import ProjectError, load_site, save_site

from tests.synthetic import write_dzt


def _site(tmp_path):
    p = tmp_path / "L0.DZT"
    write_dzt(p, np.zeros((512, 20), dtype=np.int32))
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32616", 0.5)
    return Site(grids=[grid], lines=[Line.open(p, GridPlacement("G", "y", 0.0))])


def test_presets_round_trip_and_are_omitted_when_empty(tmp_path):
    site = _site(tmp_path)
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert "presets" not in out.read_text()
    stack = StepStack()
    stack.append(build_step("dewow", window_ns=6.0))
    stack.append(build_step("background_mean"))
    site.presets["campus"] = stack.to_dicts()
    save_site(site, out)
    back = load_site(out)
    assert back.presets == {"campus": stack.to_dicts()}
    assert StepStack.from_dicts(back.presets["campus"]).to_dicts() == stack.to_dicts()


def test_invalid_preset_is_a_project_error(tmp_path):
    site = _site(tmp_path)
    out = tmp_path / "survey.nsgeo.json"
    site.presets["bad"] = [{"step": "no_such_step", "params": {}}]
    save_site(site, out)
    with pytest.raises(ProjectError, match="bad"):
        load_site(out)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_presets.py -q`
Expected: FAIL — `AttributeError: 'Site' object has no attribute 'presets'`

- [ ] **Step 3: Add presets to the core**

`model/survey.py`, in `Site`: add `presets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)` after `stacks`.

`project.py`, in `save_site` before writing: `if site.presets: doc["presets"] = site.presets`. In `load_site`, after `site.stacks = stacks`:

```python
    presets = doc.get("presets", {})
    for name, dicts in presets.items():
        try:
            StepStack.from_dicts(dicts)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"invalid preset {name!r}: {exc}") from exc
    site.presets = dict(presets)
```

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests -q` — all PASS.

- [ ] **Step 4: Write the failing plugin test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def plugin(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5)))
    s.add_lines(lines)
    key = s.keys()[0]
    s.set_profiles(key, lines[0].load())
    s.open_line(key)
    yield plugin, s, key
    plugin.unload()


def test_difference_view_shows_what_a_step_removed(plugin):
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    pd.add_step("dewow")
    pd.add_step("background_mean")
    pd.list.setCurrentRow(1)
    pd.diff_button.setChecked(True)
    assert "background_mean" in prd.difference_label.text()
    diff = prd.current_radargram()
    result = s.stack_for(key).result()
    assert diff is not result
    np.testing.assert_allclose(diff.data, s.stack_for(key).intermediate(0).data - result.data)
    pd.diff_button.setChecked(False)
    assert prd.difference_label.text() == ""


def test_difference_view_declines_sample_count_changing_steps(plugin):
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    s.append_step(key, build_step("time_zero", mode="sample", sample=40))  # deterministic crop
    pd.list.setCurrentRow(0)
    messages = []
    prd.error.connect(messages.append)
    pd.diff_button.setChecked(True)
    assert messages and "sample count" in messages[0]
    assert not pd.diff_button.isChecked()
    assert prd.difference_label.text() == ""


def test_presets_save_apply_and_persist(plugin, tmp_path):
    plugin, s, key = plugin
    pd = plugin.processing_dock
    pd.add_step("dewow")
    pd.add_step("gain_agc")
    pd.save_preset_named("campus")
    assert s.preset_names() == ["campus"]
    other = s.keys()[1]
    s.open_line(other)
    assert pd.list.count() == 0
    pd.apply_preset_named("campus")
    assert [i.text() for i in (pd.list.item(r) for r in range(pd.list.count()))] == ["dewow", "gain_agc"]
    assert [a.text() for a in pd.presets_menu.actions() if a.text() == "campus"]
    s.save()
    assert '"presets"' in (tmp_path / "survey.nsgeo.json").read_text()
    s.delete_preset("campus")
    assert s.preset_names() == []
```

- [ ] **Step 5: Implement**

`session.py`: add `presets_changed = pyqtSignal()` and

```python
    # ---- presets ----------------------------------------------------------
    def preset_names(self) -> list[str]:
        return sorted(self._require_site().presets)

    def save_preset(self, name: str, key: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("a preset needs a name")
        self._require_site().presets[name] = self.stack_for(key).to_dicts()
        self._set_dirty(True)
        self.presets_changed.emit()

    def apply_preset(self, name: str, key: str) -> None:
        site = self._require_site()
        fresh = StepStack.from_dicts(site.presets[name])
        self._attach_source(key, fresh)
        site.stacks[key] = fresh
        self._touch_stack(key)

    def delete_preset(self, name: str) -> None:
        self._require_site().presets.pop(name, None)
        self._set_dirty(True)
        self.presets_changed.emit()
```

`processing_dock.py`: add `difference_toggled = pyqtSignal(int)`; in the top button row add

```python
        self.diff_button = QToolButton()
        self.diff_button.setText("Difference")
        self.diff_button.setCheckable(True)
        self.diff_button.setToolTip("Show what the selected step removed instead of the result")
        row.addWidget(self.diff_button)
        self.diff_button.toggled.connect(self._emit_difference)
```

and in the bottom row

```python
        self.presets_button = QToolButton()
        self.presets_button.setText("Presets")
        self.presets_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.presets_menu = QMenu(self.presets_button)
        self.presets_button.setMenu(self.presets_menu)
        bottom.addWidget(self.presets_button)
        session.presets_changed.connect(self._rebuild_presets_menu)
        session.site_opened.connect(self._rebuild_presets_menu)
        self._rebuild_presets_menu()
```

with methods:

```python
    def _emit_difference(self, checked: bool) -> None:
        self.difference_toggled.emit(self.list.currentRow() if checked else -1)

    def _rebuild_presets_menu(self) -> None:
        self.presets_menu.clear()
        self.presets_menu.addAction("Save current stack as…", self._save_preset_prompt)
        names = self.session.preset_names() if self.session.is_open else []
        if names:
            self.presets_menu.addSeparator()
            for name in names:
                self.presets_menu.addAction(name, lambda n=name: self.apply_preset_named(n))
            delete = self.presets_menu.addMenu("Delete")
            for name in names:
                delete.addAction(name, lambda n=name: self.session.delete_preset(n))

    def _save_preset_prompt(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name.strip():
            self.save_preset_named(name)

    def save_preset_named(self, name: str) -> None:
        key = self.key()
        if key is not None:
            self.session.save_preset(name, key)

    def apply_preset_named(self, name: str) -> None:
        key = self.key()
        if key is not None:
            self.session.apply_preset(name, key)
```

(`QInputDialog` joins the widgets import.) In `_on_current_row`, after emitting `step_selected`, add `if self.diff_button.isChecked(): self._emit_difference(True)` so moving the selection moves the difference view.

`profile_dock.py`: add `difference_cleared = pyqtSignal()`; in `current_radargram`'s `except ValueError` branch, emit it when reverting `_difference_index`.

`plugin.py` `initGui`:

```python
        self.processing_dock.difference_toggled.connect(self.profile_dock.set_difference_index)
        self.profile_dock.difference_cleared.connect(lambda: self.processing_dock.diff_button.setChecked(False))
```

`README.md`: replace the status blockquote with

```markdown
> **Status: early development.** The core library (DZT reader, survey model,
> processing) is complete and tested. The QGIS plugin loads sites, imports
> lines onto the map, and shows and processes profiles. Map↔profile cursor
> sync, picking, and a release zip are next.
```

- [ ] **Step 6: Run everything, lint, mypy, commit**

Run the full verification set from Global Constraints, plus `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`.
Expected: all PASS, clean.

```bash
git add packages/nsgeo-core packages/nsgeo-qgis README.md
git commit -m "feat: difference view and named presets

The difference view shows what the selected step removed, using the
stack's cached intermediates; steps that change the sample count are
declined with the core's message. Presets are named stacks stored in
the survey JSON, validated on load, and applied through the session."
```

**M6 checkpoint (manual, 15 minutes).** Reload the plugin, open the M4 site, click FILE__001.

1. Processing dock ▸ Add step ▸ `dewow`: the profile brightens slightly (low-frequency drift gone). Add `background_mean`: the direct-wave band disappears and reflectors appear, matching the processed render in the Lavish mock. Add `gain_agc`: deeper reflectors come up.
2. Select `background_mean`, press Difference: the profile shows horizontal bands only, the mean trace. Press again to return. Select a step and drag it to another position: the image updates and the list order follows. Untick `dewow`: image changes; tick again.
3. Select `gain_agc`: the form shows window 20, target 1, eps 1e-12. Change window to 10 and press Enter: image updates. Type `abc`: an orange message appears under the form, nothing changes.
4. Add step ▸ `bandpass (needs values)`: the modal opens with blank orange fields and the header line reading antenna HS350US, Nyquist 2309 MHz. Enter 100 and 5000: OK stays disabled with a Nyquist message. Enter 100 and 600: OK enables; add. Add step ▸ `time_zero`, drag it to the top: the depth axis now starts at 0 and the time axis at 0. Select it and press Difference: a message bar warning says the sample count changes; the button unchecks.
5. Add step ▸ `gain_curve`: it appends with no dialog and the strip appears beside the image with a flat 0 dB line. Drag the lower point right: the lower half of the image brightens live. Double-click to add a middle point; right-click it to remove.
6. Presets ▸ Save current stack as… ▸ `campus`. Click FILE__002 (empty stack) ▸ Presets ▸ `campus`: the same stack appears and the image is processed. Apply to grid… ▸ Yes: click FILE__003 through FILE__010, each shows the processed image. Save site; confirm `presets` and per-line `stack` blocks in the JSON.
7. Display gain slider and colormap combo still work on the processed image and appear nowhere in the JSON.

Anything that fails here is fixed before Plan 3 is written.

---

## Handoff to Plan 3 (M7–M9)

Not in this plan, by design (spec §10):

- `MapLink` (trace cursor marker, selection rubber band), the trace map tool (hover snaps, click opens), and `lookup.nearest_trace` wired to canvas-CRS coordinates cached per line.
- Pick tool and picks-layer writes: `ProfileDock.pick_requested(key, trace, time_ns)` and `ProfileView.set_pick_mode` already exist; `SiteLayers` already creates the `picks` table.
- `build_zip.py`, the CI zip job, release notes, and promoting the core's `__init__` exports from the list of names the plugin actually imported.
- Hover readout (trace, distance, time, depth) in the viewer toolbar.
- Reading DZX marks into a hover tooltip; relocating missing files on open; a target-layer picker for picks.

Before Plan 3 is written, execute this plan and run the M6 checkpoint; Plan 3's design of `MapLink` should read the session and viewer as they actually turned out.
