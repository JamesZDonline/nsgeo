### Task 2: The slice engine — preparation, plan cache, residency, one slice per tick

Everything between "the user chose a grid, a preset and a transform" and "here is a slice",
with no widgets in it. Its numeric half is Qt-free so it runs on the normal CI matrix and under
mypy.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- Modify: `.github/workflows/ci.yml` (add `slices_plan.py` to the mypy list)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py` (new)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py` (new)

**Interfaces:**

- Consumes: Task 1's `SliceWindow`, `plan_windows`, `limit_over_slices`, `shared_limit`,
  `clear_kernel_cache`; M10's `CubeFrame.for_grid`, `ZAxis.from_range`, `PreparedLine`,
  `LinePlan`, `plan_line`, `build_cube`, `stream_slice`, `CoverageError`, `SliceCube`,
  `Provenance`; `SiteSession` (`site`, `is_open`, `keys()`, `line_for_key`, `grid`,
  `grid_for_line`, `resolved_velocity`, `site.presets`, `site_closed`); `nsgeo.processing`'s
  `StepStack`, `build_step`, `available_steps`, `get_step`, `Radargram`.
- Produces:
  - `slices_plan.SourceChoice(grid_id: str, preset: str, transform: str, line_keys: tuple[str, ...])`
  - `slices_plan.Resolution(cell: float, dz_ns: float, t0_ns: float, t1_ns: float)`
  - `slices_plan.MemoryEstimate(lines_bytes: int, cube_bytes: int)` with `.total_bytes`
  - `slices_plan.transform_names() -> list[str]`
  - `slices_plan.preset_transform_conflict(steps) -> str | None`
  - `slices_plan.estimate_memory(prepared_samples: int, n_cells: int, nz: int) -> MemoryEstimate`
  - `slices_plan.choose_residency(estimate, n_lines, budget_bytes, always_resident=False) -> str`
    returning `"resident"` or `"streaming"`
  - `slices_plan.format_bytes(n: int) -> str`, `slices_plan.format_status(...) -> str`
  - `slices_plan.DEFAULT_BUDGET_BYTES`, `STREAM_MS_PER_LINE`, `FRAME_BUDGET_MS`, `NO_TRANSFORM`
  - `slices_engine.SliceEngine(session, on_prepared=None, on_error=None, on_progress=None,
    parent=None)` with `set_source`, `set_resolution`, `clear`, `dispose`, `is_prepared`,
    `frame`, `z`, `mode`, `line_count`, `estimate`, `choice`, `has_cube`,
    `slice_at(window) -> (values, coverage)`,
    `shared_limit(thickness_levels, clip) -> float`, `cube() -> SliceCube`,
    `provenance() -> Provenance`, `status_text() -> str`, `wait_for_preparation(timeout_ms)`.

**`SliceEngine` deliberately declares no `pyqtSignal`.** The orphan-signal test
(`tests/pure/test_no_orphan_signals.py`) requires a `connect` in the *package* for every declared
signal, and this task has no consumer to connect one to — the dock arrives in Task 3. Constructor
callbacks are the existing pattern for exactly this (`LineLoader(session, on_error=...)`), and
they keep the rule honest rather than inviting a placeholder `connect` that satisfies a grep and
consumes nothing.

---

- [ ] **Step 1: Write the failing pure tests**

Create `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`:

```python
"""The Qt-free arithmetic behind the Slices dock."""

from __future__ import annotations

import pytest
from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    FRAME_BUDGET_MS,
    MemoryEstimate,
    Resolution,
    SourceChoice,
    STREAM_MS_PER_LINE,
    choose_residency,
    estimate_memory,
    format_bytes,
    format_status,
    preset_transform_conflict,
    transform_names,
)


def test_transform_names_come_from_the_registry_not_a_hardcoded_list():
    """Adding an amplitude transform to the core registry must offer it
    here with no edit. The mutant is a literal list, which passes a
    membership assertion and silently omits anything added later."""
    from nsgeo.processing import available_steps, get_step

    names = transform_names()
    expected = [n for n in available_steps() if getattr(get_step(n), "unipolar", False)]
    assert names == expected
    assert set(names) == {"amp_abs", "amp_square", "amp_envelope"}
    assert "gain_agc" not in names and "dewow" not in names


def test_a_preset_carrying_an_amplitude_transform_is_a_conflict():
    """Ruling 2: the transform is appended by the engine and is never part
    of a preset, so that the transform is always the LAST enabled step and
    StepStack.output_unipolar is exact. A preset that already holds one
    breaks that, and the failure it produces -- unipolar data on a bipolar
    table -- is the one spec 8 exists to prevent."""
    assert preset_transform_conflict([{"step": "dewow", "params": {}}]) is None
    assert preset_transform_conflict([]) is None
    assert (
        preset_transform_conflict(
            [{"step": "time_zero"}, {"step": "amp_abs"}, {"step": "gain_agc"}]
        )
        == "amp_abs"
    )
    # Found wherever it sits, not only last -- gain-after-transform is
    # precisely the ordering that makes output_unipolar report False.
    assert preset_transform_conflict([{"step": "amp_envelope"}]) == "amp_envelope"
    # A disabled transform still conflicts: enabling it later would break
    # the invariant with no further warning.
    assert preset_transform_conflict([{"step": "amp_square", "enabled": False}]) == "amp_square"
    # An unknown step name is not this function's business to reject.
    assert preset_transform_conflict([{"step": "not_a_step"}]) is None


def test_memory_estimate_counts_the_lines_and_the_cube_separately():
    """Spec 7.4's inversion: by 120 lines the cached LINES cost more than
    the cube. A policy that only attacks the cube does nothing for a large
    site, so the two are reported apart."""
    est = estimate_memory(prepared_samples=10_000_000, n_cells=90_000, nz=230)
    assert est.lines_bytes == 10_000_000 * 4
    assert est.cube_bytes == 230 * 90_000 * 4 + 90_000 * 4
    assert est.total_bytes == est.lines_bytes + est.cube_bytes


def test_streaming_stays_the_default_while_nobody_could_perceive_the_difference():
    """Spec 9.2: a resident cube redraws in 0.56 ms against streaming's
    3.6 ms and nobody can perceive that. Holding the cube below the frame
    budget buys nothing and costs memory, so it is not done even when
    there is room."""
    small = MemoryEstimate(lines_bytes=28_000_000, cube_bytes=83_000_000)
    assert choose_residency(small, n_lines=24, budget_bytes=DEFAULT_BUDGET_BYTES) == "streaming"
    assert 24 * STREAM_MS_PER_LINE < FRAME_BUDGET_MS  # why


def test_a_large_site_is_promoted_to_a_resident_cube_when_it_fits():
    est = MemoryEstimate(lines_bytes=140_000_000, cube_bytes=83_000_000)
    n_lines = 200  # 200 * 0.14 ms = 28 ms per tick, past a 16 ms frame
    assert n_lines * STREAM_MS_PER_LINE > FRAME_BUDGET_MS
    assert choose_residency(est, n_lines, budget_bytes=DEFAULT_BUDGET_BYTES) == "resident"


def test_a_large_site_that_does_not_fit_degrades_to_streaming_rather_than_failing():
    """Spec 7.4: an over-budget cube degrades to streaming instead of
    failing, and the source dialog warns rather than hard-caps."""
    est = MemoryEstimate(lines_bytes=140_000_000, cube_bytes=4_000_000_000)
    assert choose_residency(est, n_lines=200, budget_bytes=DEFAULT_BUDGET_BYTES) == "streaming"


def test_the_settings_override_wins_in_both_directions():
    small = MemoryEstimate(lines_bytes=1_000, cube_bytes=1_000)
    assert choose_residency(small, 2, DEFAULT_BUDGET_BYTES, always_resident=True) == "resident"
    huge = MemoryEstimate(lines_bytes=1, cube_bytes=10**12)
    # The user asked for it and spec 7.4 never hard-caps; the dock warns.
    assert choose_residency(huge, 2, DEFAULT_BUDGET_BYTES, always_resident=True) == "resident"


def test_format_bytes_reads_like_the_spec_status_line():
    assert format_bytes(28_000_000) == "28 MB"
    assert format_bytes(1_500_000_000) == "1.5 GB"
    assert format_bytes(900) == "1 MB"  # never "0 MB": a held line is not nothing


def test_the_status_line_says_what_is_held_and_how_fast_it_redraws():
    """Spec 9.2's wording, near-verbatim: memory, not time, is the binding
    constraint, and a constraint the user cannot see is one they cannot
    act on."""
    est = MemoryEstimate(lines_bytes=28_000_000, cube_bytes=83_000_000)
    streaming = format_status("streaming", n_lines=24, estimate=est, redraw_ms=3.6)
    assert streaming == "24 lines held in memory, 28 MB · slices redraw in 4 ms"
    resident = format_status("resident", n_lines=24, estimate=est, redraw_ms=0.56)
    assert "whole volume" in resident
    assert "111 MB" in resident  # lines AND cube, because both are held
    assert format_status("streaming", 1, est, 3.6).startswith("1 line held")  # not "1 lines"
    assert "redraw in —" in format_status("streaming", 24, est, redraw_ms=None)


def test_the_value_objects_validate_themselves():
    with pytest.raises(ValueError):
        Resolution(cell=0.0, dz_ns=0.5, t0_ns=0.0, t1_ns=50.0)
    with pytest.raises(ValueError):
        Resolution(cell=0.1, dz_ns=-1.0, t0_ns=0.0, t1_ns=50.0)
    with pytest.raises(ValueError):
        Resolution(cell=0.1, dz_ns=0.5, t0_ns=50.0, t1_ns=0.0)
    ok = Resolution(cell=0.1, dz_ns=0.5, t0_ns=0.0, t1_ns=50.0)
    assert ok.cell == 0.1
    choice = SourceChoice(grid_id="A", preset="p", transform="amp_abs", line_keys=("a", "b"))
    assert choice.line_keys == ("a", "b")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q`
Expected: collection error — no module `nsgeo_qgis.slices_plan`.

- [ ] **Step 3: Implement `slices_plan.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`:

```python
"""Qt-free arithmetic behind the Slices dock.

Everything here is a pure function of plain values, so it runs on the
normal CI matrix (no QGIS) and under mypy, the same bargain `lookup.py`
makes. The dock reads it; the engine reads it; neither of them computes
any of it.

Two rules live here rather than in a widget, because both are decisions
with reasons rather than layout:

* **A preset never carries an amplitude transform.** The engine appends
  the chosen transform after the preset's steps, so the transform is
  always the last enabled step and `StepStack.output_unipolar` is exact.
  Were a preset to carry one with a gain after it, `output_unipolar`
  would report False -- it is deliberately conservative, reporting only
  the last enabled step -- and a unipolar slice would be drawn on a
  bipolar table, which is the configuration error spec 8 exists to name.
* **Residency is chosen, not asked about.** Spec 9.2: a resident cube
  redraws a slice in 0.56 ms against streaming's 3.6 ms, and nobody can
  perceive that. It only begins to matter on a large site during a
  continuous drag. Asking a user to understand the word "residency" to
  make that call is asking them to do the plugin's job.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nsgeo.processing import available_steps, get_step

#: The Transform combo's "no transform" entry. Spec 6.2 and GPRSLICE's own
#: `xfrm_method=NONE` both allow it: the slice is then a signed mean, drawn
#: on a bipolar table, and the two stay consistent because the transform
#: being absent is exactly what `output_unipolar` reports.
NO_TRANSFORM = ""

#: Measured, spec 7.4: streaming costs ~0.14 ms per line per tick.
STREAM_MS_PER_LINE = 0.14

#: One 60 Hz frame. Below this, streaming is imperceptible.
FRAME_BUDGET_MS = 16.0

#: What the plugin will hold before it stops promoting to a resident cube.
#: A default, never a cap -- spec 7.4 warns and degrades, it does not block.
DEFAULT_BUDGET_BYTES = 1_500_000_000


@dataclass(frozen=True)
class SourceChoice:
    """What goes into a cube: spec 9.1's four decisions, as one value.

    `transform` is `NO_TRANSFORM` or a name from `transform_names()`.
    `line_keys` is the included subset, in survey order -- the thing the
    `Choose...` dialog edits.
    """

    grid_id: str
    preset: str
    transform: str
    line_keys: tuple[str, ...]


@dataclass(frozen=True)
class Resolution:
    """The Resolution group's geometry: what a cube is binned at.

    Every field here invalidates every `LinePlan`. That is why they are
    one value rather than four setters -- there is no such thing as
    changing the cell size and keeping the plans, and M10 measured what
    happens when someone tries: a 1.0 m-cell plan used against a 0.5 m-cell
    frame bins every trace into the wrong cell, with no exception and
    plausible-looking coverage.

    The fill radius is NOT here: it is a display parameter applied after
    binning (spec 6.4), so it changes no plan.
    """

    cell: float
    dz_ns: float
    t0_ns: float
    t1_ns: float

    def __post_init__(self) -> None:
        if not self.cell > 0.0:
            raise ValueError(f"cell must be positive, got {self.cell}")
        if not self.dz_ns > 0.0:
            raise ValueError(f"dz_ns must be positive, got {self.dz_ns}")
        if not self.t1_ns > self.t0_ns:
            raise ValueError(f"t1_ns must exceed t0_ns, got {self.t0_ns}..{self.t1_ns}")


@dataclass(frozen=True)
class MemoryEstimate:
    """Held bytes, split the way spec 7.4 splits them.

    Separately, because they grow in opposite directions: cube memory
    grows with resolution and not with line count, cache memory the
    reverse. By 120 lines the cached lines cost more than the cube, so a
    single total would hide which one to act on.
    """

    lines_bytes: int
    cube_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.lines_bytes + self.cube_bytes


def transform_names() -> list[str]:
    """Registered steps whose output is unipolar, in registry order.

    From the registry, never a literal: the plugin's rule everywhere is
    that steps come from `available_steps()`, and a hardcoded list would
    silently omit any transform added to the core later.
    """
    return [name for name in available_steps() if getattr(get_step(name), "unipolar", False)]


def preset_transform_conflict(steps: Sequence[Mapping[str, Any]]) -> str | None:
    """The name of the first amplitude transform in a preset, or None.

    Anywhere in the stack, and regardless of `enabled`: a disabled
    transform is one click from breaking the same invariant, with nothing
    to warn about it a second time.
    """
    for entry in steps:
        name = str(entry.get("step", ""))
        try:
            cls = get_step(name)
        except (KeyError, ValueError):
            continue  # not a step we know; not this function's business
        if getattr(cls, "unipolar", False):
            return name
    return None


def estimate_memory(prepared_samples: int, n_cells: int, nz: int) -> MemoryEstimate:
    """Bytes held by the prepared lines, and by a cube of this shape.

    `prepared_samples` is the total float32 sample count across every
    prepared line (`sum(n_samples * n_traces)`). The cube is float32
    `mean` plus int32 `count`, which is what `SliceCube` stores.
    """
    return MemoryEstimate(
        lines_bytes=int(prepared_samples) * 4,
        cube_bytes=int(nz) * int(n_cells) * 4 + int(n_cells) * 4,
    )


def choose_residency(
    estimate: MemoryEstimate,
    n_lines: int,
    budget_bytes: int = DEFAULT_BUDGET_BYTES,
    always_resident: bool = False,
) -> str:
    """`"resident"` or `"streaming"`, from the line count and the budget.

    Three tiers are described in spec 7.4; two exist. The third -- one
    line at a time, memory-mapped off disk -- is unmeasured there, was
    never built, and M11 deliberately ships no control for it (plan
    Ruling 1). This function therefore returns one of two values, and
    nothing downstream should branch on a third.
    """
    if always_resident:
        return "resident"
    if n_lines * STREAM_MS_PER_LINE <= FRAME_BUDGET_MS:
        # Imperceptible. Holding a cube here would spend memory to buy
        # nothing a person can see.
        return "streaming"
    if estimate.total_bytes <= budget_bytes:
        return "resident"
    return "streaming"


def format_bytes(n: int) -> str:
    """Megabytes, or gigabytes past a thousand of them. Never `0 MB`."""
    mb = n / 1_000_000.0
    if mb >= 1000.0:
        return f"{mb / 1000.0:.1f} GB"
    return f"{max(1, round(mb))} MB"


def format_status(
    mode: str,
    n_lines: int,
    estimate: MemoryEstimate,
    redraw_ms: float | None,
) -> str:
    """Spec 9.2's status line: what is held, and how fast slices redraw.

    Memory first, because spec 7.2 found memory and not time to be the
    binding constraint -- halving the cell doubles the time and
    quadruples the cube.
    """
    held = estimate.lines_bytes
    noun = "line" if n_lines == 1 else "lines"
    if mode == "resident":
        held += estimate.cube_bytes
        what = f"{n_lines} {noun} and the whole volume held in memory"
    else:
        what = f"{n_lines} {noun} held in memory"
    speed = "—" if redraw_ms is None else f"{max(1, round(redraw_ms))} ms"
    return f"{what}, {format_bytes(held)} · slices redraw in {speed}"
```

- [ ] **Step 4: Run and watch them pass; add the module to CI's mypy list**

Run: `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`
Expected: the new file's 10 tests pass alongside the existing pure tier.

Then in `.github/workflows/ci.yml`, extend the `lint` job's mypy invocation to:

```yaml
      - run: |
          mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
            packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
            packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py \
            packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py
```

and run the same command locally. Expected: `Success`.

- [ ] **Step 5: Prove the pure tests discriminate**

Three mutants, one at a time:

1. `transform_names` → `return ["amp_abs", "amp_square", "amp_envelope"]`. Expect
   `test_transform_names_come_from_the_registry_not_a_hardcoded_list` to FAIL — and note in the
   report *why* the equality against a recomputed list is what catches it, where a membership
   assertion would not.
2. `preset_transform_conflict` → only inspect `steps[-1]`. Expect the gain-after-transform case
   to FAIL.
3. `choose_residency` → drop the `n_lines * STREAM_MS_PER_LINE <= FRAME_BUDGET_MS` branch. Expect
   `test_streaming_stays_the_default_while_nobody_could_perceive_the_difference` to FAIL.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py \
        packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py .github/workflows/ci.yml
git commit -m "feat(slices): the Qt-free arithmetic behind the Slices dock

Registry-driven transforms, the preset-conflict rule that keeps
output_unipolar exact, the memory estimate and the two-tier residency
choice. Added to CI's mypy list.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Write the failing engine tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`:

```python
"""SliceEngine: preparation, the plan cache, residency, one slice per tick."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.render import UnipolarClip
from nsgeo.slices import CoverageError, SliceWindow
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import NO_TRANSFORM, Resolution, SourceChoice
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
    {"step": "gain_agc", "params": {}, "enabled": True},
]


@pytest.fixture
def sourced(qgis_app, tmp_path):
    """A session with four parallel lines in one grid, and an engine on it."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    errors: list[tuple[str, str]] = []
    prepared: list[int] = []
    engine = SliceEngine(
        session,
        on_prepared=lambda: prepared.append(1),
        on_error=lambda msg: errors.append(("error", msg)),
    )
    yield engine, session, errors, prepared
    engine.dispose()


def _prepare(engine, session, transform="amp_envelope", preset="p"):
    engine.set_source(
        SourceChoice(
            grid_id="A", preset=preset, transform=transform, line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000), "preparation did not finish"
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))


def test_preparation_applies_the_preset_and_appends_the_transform(sourced):
    engine, session, errors, prepared = sourced
    _prepare(engine, session)
    assert errors == []
    assert prepared == [1]
    assert engine.is_prepared
    assert engine.line_count == 4
    assert engine.output_unipolar is True
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    covered = values[coverage > 0]
    assert covered.size > 0
    assert np.isfinite(covered).all()
    assert (covered >= 0.0).all(), "an envelope is unipolar; a negative means it was not applied"


def test_no_transform_leaves_the_data_bipolar_and_says_so(sourced):
    engine, session, errors, _ = sourced
    _prepare(engine, session, transform=NO_TRANSFORM)
    assert engine.output_unipolar is False
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    covered = values[coverage > 0]
    assert (covered < 0.0).any(), "a signed mean of a signed radargram should reach below zero"


def test_a_preset_that_already_carries_a_transform_is_refused_by_name(sourced):
    """Ruling 2. The refusal must name the step, because the user's fix is
    to remove that specific step from that specific preset."""
    engine, session, errors, _ = sourced
    session.site.presets["bad"] = [
        {"step": "amp_abs", "params": {}, "enabled": True},
        {"step": "gain_agc", "params": {}, "enabled": True},
    ]
    with pytest.raises(ValueError, match="amp_abs"):
        engine.set_source(
            SourceChoice(grid_id="A", preset="bad", transform="amp_square", line_keys=("x",))
        )
    assert not engine.is_prepared


def test_changing_the_cell_size_re_plans_every_line(sourced):
    """The defect M10's final review called M11's first bug. A LinePlan is
    a function of (line, frame, z) and every Resolution control changes
    one of them; reusing a plan across that change bins every trace into
    the wrong cell. Before M10's guard existed it did so SILENTLY, with
    plausible coverage. The engine must drop its plans, not rely on the
    guard to raise."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    coarse, _ = engine.slice_at(SliceWindow(4, 14))
    assert coarse.shape == (24, 24)  # 6 m / 0.25 m

    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    fine, _ = engine.slice_at(SliceWindow(4, 14))  # must NOT raise
    assert fine.shape == (12, 12)

    # And a z-axis change, which the same plans would also survive by
    # length alone if nz happened to match.
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.25, t0_ns=2.0, t1_ns=16.0))
    again, _ = engine.slice_at(SliceWindow(4, 14))
    assert again.shape == (12, 12)


def test_streaming_and_a_resident_cube_give_the_same_slice(sourced):
    """Spec 11's property, in the form a user could notice: the mode they
    are in must not change what they see."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_always_resident(False)
    assert engine.mode == "streaming"
    streamed, cov_s = engine.slice_at(SliceWindow(6, 18))

    engine.set_always_resident(True)
    assert engine.mode == "resident"
    resident, cov_r = engine.slice_at(SliceWindow(6, 18))

    np.testing.assert_array_equal(cov_s, cov_r)
    both = np.isfinite(streamed) & np.isfinite(resident)
    assert both.any()
    np.testing.assert_allclose(streamed[both], resident[both], rtol=1e-5, atol=1e-6)
    np.testing.assert_array_equal(np.isfinite(streamed), np.isfinite(resident))


def test_the_shared_limit_agrees_between_the_two_modes(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    clip = UnipolarClip()
    engine.set_always_resident(False)
    streamed = engine.shared_limit(10, clip)
    engine.set_always_resident(True)
    resident = engine.shared_limit(10, clip)
    assert streamed == pytest.approx(resident, rel=1e-4)
    assert streamed > 0.0


def test_provenance_names_the_lines_that_were_actually_prepared(sourced):
    """Not the lines that were asked for. A line that failed to prepare is
    not in the cube and must not be claimed by its provenance -- that
    record is what a reader trusts the thing by."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    prov = engine.provenance()
    assert prov.line_keys == tuple(session.keys())
    assert prov.preset_name == "p"
    assert prov.transform == "amp_envelope"
    assert len(prov.steps) == len(PRESET)
    assert prov.core_version
    assert prov.built_utc.endswith("Z")


def test_a_z_range_the_lines_do_not_cover_is_reported_with_the_line_named(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=0.0, t1_ns=400.0))
    with pytest.raises(CoverageError, match="FILE__001"):
        engine.slice_at(SliceWindow(0, 4))


def test_the_status_line_follows_the_mode_and_the_line_count(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.slice_at(SliceWindow(4, 14))
    text = engine.status_text()
    assert text.startswith("4 lines held in memory")
    assert "slices redraw in" in text
    engine.set_always_resident(True)
    engine.slice_at(SliceWindow(4, 14))
    assert "whole volume" in engine.status_text()


def test_closing_the_site_releases_everything(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    assert engine.is_prepared
    session.close_site()
    assert not engine.is_prepared
    assert engine.line_count == 0
    assert engine.frame is None


def test_a_line_that_cannot_be_prepared_is_reported_by_name(sourced, tmp_path):
    engine, session, errors, _ = sourced
    key = session.keys()[0]
    session.line_for_key(key).path.unlink()  # the file goes away under us
    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform="amp_abs", line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000)
    assert any(key in msg for _, msg in errors), f"no error named {key}: {errors}"
```

- [ ] **Step 8: Run them and watch them fail**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py -q -p no:xonsh`
Expected: collection error — no module `nsgeo_qgis.slices_engine`.

- [ ] **Step 9: Implement `slices_engine.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`:

```python
"""Preparing lines, holding plans, and handing over one slice per tick.

Spec 6.1's three tiers, owned in one place. Tier 1 -- load, preset,
transform -- is the only expensive step (about 0.9 s for 24 lines) and
depends on the preset and the transform and on nothing else, so it is
cached here and every geometric parameter stays cheap. Tier 2, the
resample-and-bin plan, depends on the cell size, dz and the z range, and
is dropped wholesale whenever any of them moves. Tier 3 is a slice, which
is what `slice_at` returns.

**No `pyqtSignal`.** `tests/pure/test_no_orphan_signals.py` requires a
`connect` in the package for every declared signal, and this module's
consumer (the Slices dock) does not exist yet. Constructor callbacks are
the pattern `LineLoader` already uses for exactly this, and they keep that
rule honest instead of inviting a `connect` that satisfies a grep and
consumes nothing.

Four hazards, all of them recorded elsewhere in this codebase and all of
them live here:

* `QgsApplication.taskManager().addTask()` keeps no strong reference to a
  `QgsTask.fromFunction()` task. `_pending` is the keep-alive; without it
  the task is collected silently and `on_finished` never runs. `addTask()`
  returning 0 means it was never added at all, so the bookkeeping has to
  be undone in that branch.
* `QgsTaskWrapper.finished()` swallows any exception an `on_finished`
  callback raises, with no traceback anywhere -- worse than the ordinary
  slot hazard, which at least reaches stderr. `_finished` guards its own
  body with `except`, not merely `finally`.
* The site can be closed, or a different site opened, while a preparation
  is in flight. `_generation` and the captured site identity together
  decide whether a result may be kept: keys are relative paths, so the
  same string can name a line in two different sites.
* **A `LinePlan` must never outlive the frame or z axis it was built
  against.** Every `Resolution` field invalidates every plan.
  `_rebuild_geometry` drops them by setting `_plans = None`, and
  `build_cube`/`stream_slice` carry M10's own guard underneath as a second
  line of defence. Do not "optimise" this into a partial update: M10
  measured the silent version binning every trace into the wrong cell with
  entirely plausible coverage.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

import nsgeo
import numpy as np
from nsgeo.processing import Radargram, StepStack, build_step
from nsgeo.slices import (
    CubeFrame,
    LinePlan,
    PreparedLine,
    Provenance,
    SliceCube,
    SliceWindow,
    ZAxis,
    build_cube,
    limit_over_slices,
    plan_line,
    plan_windows,
    stream_slice,
)
from nsgeo.slices import shared_limit as cube_shared_limit
from nsgeo.slices.fill import clear_kernel_cache
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer

from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    NO_TRANSFORM,
    MemoryEstimate,
    Resolution,
    SourceChoice,
    choose_residency,
    estimate_memory,
    format_status,
    preset_transform_conflict,
)

#: How much of the previous redraw timing survives into the reported one.
#: A plain last-value readout flickers between 2 ms and 9 ms on a drag and
#: is unreadable; this smooths it without hiding a real change.
_REDRAW_SMOOTHING = 0.7


class SliceEngine(QObject):
    """Everything between a chosen source and a slice. Owns no widgets."""

    def __init__(
        self,
        session: Any,
        on_prepared: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.on_prepared = on_prepared
        self.on_error = on_error
        self.on_progress = on_progress
        self._choice: SourceChoice | None = None
        self._resolution: Resolution | None = None
        self._lines: list[PreparedLine] = []
        self._plans: list[LinePlan] | None = None
        self._frame: CubeFrame | None = None
        self._z: ZAxis | None = None
        self._cube: SliceCube | None = None
        self._mode = "streaming"
        self._always_resident = False
        self._budget_bytes = DEFAULT_BUDGET_BYTES
        self._redraw_ms: float | None = None
        self._generation = 0
        self._running = False
        # See the module docstring: addTask() keeps no reference of its
        # own, so a task with no Python reference is collected silently
        # and its on_finished never runs.
        self._pending: set[QgsTask] = set()
        session.site_closed.connect(self.clear)

    # ---- state ------------------------------------------------------------
    @property
    def is_prepared(self) -> bool:
        return bool(self._lines)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def line_count(self) -> int:
        return len(self._lines)

    @property
    def frame(self) -> CubeFrame | None:
        return self._frame

    @property
    def z(self) -> ZAxis | None:
        return self._z

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def choice(self) -> SourceChoice | None:
        """What this engine was last pointed at. The exporter needs it to
        write a recipe; nothing may reach past this for `_choice`."""
        return self._choice

    @property
    def has_cube(self) -> bool:
        """Whether a resident cube is currently held.

        Public because "did this operation quietly build a cube?" is a
        contract, not an implementation detail: spec 7.4 makes a resident
        cube a latency optimisation and never a capability, and export is
        the operation most tempted to forget that.
        """
        return self._cube is not None

    @property
    def output_unipolar(self) -> bool:
        """Whether a slice from this source has no negative side.

        Exactly `transform != NO_TRANSFORM`, and that is a structural fact
        rather than a guess: the transform is appended AFTER the preset's
        steps, so it is always the last enabled step. `_build_stack`
        asserts the two agree, so a future edit that reorders them fails
        loudly instead of putting unipolar data on a bipolar table.
        """
        return self._choice is not None and self._choice.transform != NO_TRANSFORM

    @property
    def estimate(self) -> MemoryEstimate:
        samples = sum(int(line.data.size) for line in self._lines)
        n_cells = self._frame.n_cells if self._frame is not None else 0
        nz = self._z.nz if self._z is not None else 0
        return estimate_memory(samples, n_cells, nz)

    def set_always_resident(self, flag: bool) -> None:
        """The settings override of spec 9.2, worded there for what it
        buys: *keep the whole volume in memory for faster dragging*."""
        self._always_resident = bool(flag)
        self._choose_mode()

    def set_budget_bytes(self, budget: int) -> None:
        self._budget_bytes = int(budget)
        self._choose_mode()

    def _choose_mode(self) -> None:
        self._mode = choose_residency(
            self.estimate, len(self._lines), self._budget_bytes, self._always_resident
        )

    # ---- source -----------------------------------------------------------
    def set_source(self, choice: SourceChoice | None) -> None:
        """Choose what goes into the cube and start preparing it.

        Raises ValueError, synchronously and before any work starts, if
        the preset carries an amplitude transform (plan Ruling 2) -- the
        caller is a dialog, and a refusal it can show is worth more than
        an error that arrives a second later through a callback.
        """
        self._generation += 1
        self._lines = []
        self._plans = None
        self._cube = None
        self._redraw_ms = None
        self._choice = choice
        if choice is None or not self.session.is_open:
            self._rebuild_geometry()
            return

        site = self.session.site
        steps = list(site.presets.get(choice.preset, []))
        conflict = preset_transform_conflict(steps)
        if conflict is not None:
            self._choice = None
            raise ValueError(
                f"the preset {choice.preset!r} already contains the amplitude transform "
                f"{conflict!r}. A cube's transform is chosen here and applied last, so "
                f"remove {conflict!r} from the preset or choose it in Transform, not both"
            )

        jobs: list[tuple[str, Any, np.ndarray]] = []
        frames = site.frames
        for key in choice.line_keys:
            try:
                line = self.session.line_for_key(key)
                jobs.append((key, line, line.trace_coords(frames)))
            except Exception as exc:  # noqa: BLE001 -- a missing grid or a stale key
                self._report(f"{key}: {exc}")
        if not jobs:
            self._rebuild_geometry()
            self._finish_preparation()
            return
        self._start_task(jobs, steps, choice.transform, self._generation)

    def _build_stack(self, steps: Sequence[dict[str, Any]], transform: str) -> StepStack:
        """The preset, then the transform. Order is the whole point.

        `StepStack.output_unipolar` reports the LAST ENABLED step and is
        deliberately conservative: `[amp_abs, gain_agc]` reports False
        though AGC preserves unipolarity. Appending the transform makes
        that conservatism irrelevant, because the transform is always
        last. The assert is cheap and pins the property for whoever edits
        this next.
        """
        stack = StepStack.from_dicts([dict(s) for s in steps])
        if transform != NO_TRANSFORM:
            stack.append(build_step(transform))
        if stack.output_unipolar != (transform != NO_TRANSFORM):
            raise ValueError(
                "the built stack's polarity disagrees with the chosen transform; "
                "the transform must be the last enabled step"
            )
        return stack

    def _start_task(
        self,
        jobs: list[tuple[str, Any, np.ndarray]],
        steps: Sequence[dict[str, Any]],
        transform: str,
        generation: int,
    ) -> None:
        # Validated on the main thread, before the task runs, so a bad
        # preset cannot surface from a worker thread.
        self._build_stack(steps, transform)
        requested_against = self.session.site
        total = len(jobs)
        failures: list[str] = []

        def work(task: QgsTask) -> Any:
            out: list[PreparedLine] = []
            for index, (key, line, coords) in enumerate(jobs):
                if task.isCanceled():
                    return None
                try:
                    profiles = line.load()
                    radargram = Radargram.from_profile(profiles[0])
                    stack = self._build_stack(steps, transform)
                    stack.source = radargram
                    result = stack.result()
                    out.append(
                        PreparedLine(
                            key=key,
                            data=np.asarray(result.data, dtype=np.float32),
                            dt_ns=result.dt_ns,
                            t0_ns=result.t0_ns,
                            coords=coords,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 -- one bad line must not
                    # abandon the other twenty-three; it is named and skipped.
                    failures.append(f"{key}: {exc}")
                task.setProgress(100.0 * (index + 1) / total)
            return out

        def finished(exception: BaseException | None, result: Any = None) -> None:
            self._pending.discard(task)
            try:
                if generation != self._generation:
                    return  # a newer source was chosen; this result is stale
                if self.session.site is not requested_against:
                    return  # the site was closed or replaced under us
                self._running = False
                for message in failures:
                    self._report(message)
                if exception is not None:
                    self._report(str(exception))
                    return
                self._lines = list(result or [])
                self._rebuild_geometry()
                self._finish_preparation()
            except Exception as exc:  # noqa: BLE001 -- see the module docstring:
                # QgsTaskWrapper swallows this with no traceback anywhere.
                self._running = False
                self._report(f"could not finish preparing the slice source: {exc}")

        task = QgsTask.fromFunction("nsgeo: prepare slice source", work, on_finished=finished)
        task.progressChanged.connect(lambda pct: self._emit_progress(pct, total))
        self._pending.add(task)
        self._running = True
        if not QgsApplication.taskManager().addTask(task):
            # Never added, so on_finished will never run and nothing else
            # holds a reference either: undo everything here.
            self._pending.discard(task)
            self._running = False
            self._report("could not schedule the slice source preparation")

    def _emit_progress(self, percent: float, total: int) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(int(round(percent / 100.0 * total)), total)
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self._report(f"could not report progress: {exc}")

    def _finish_preparation(self) -> None:
        if self.on_prepared is None:
            return
        self.on_prepared()

    def _report(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)

    # ---- geometry ---------------------------------------------------------
    def set_resolution(self, resolution: Resolution | None) -> None:
        """Set the binning geometry. Drops every plan; see the module docstring."""
        self._resolution = resolution
        self._rebuild_geometry()

    def _rebuild_geometry(self) -> None:
        # Unconditional, and wholesale. There is no such thing as keeping
        # a plan across a geometry change.
        self._plans = None
        self._cube = None
        self._frame = None
        self._z = None
        self._redraw_ms = None
        if self._choice is None or self._resolution is None or not self.session.is_open:
            self._choose_mode()
            return
        grid = self.session.grid(self._choice.grid_id)
        res = self._resolution
        self._frame = CubeFrame.for_grid(grid, res.cell)
        self._z = ZAxis.from_range(res.t0_ns, res.t1_ns, res.dz_ns)
        self._choose_mode()

    def _require_geometry(self) -> tuple[CubeFrame, ZAxis]:
        if self._frame is None or self._z is None:
            raise RuntimeError("no slice geometry: choose a source and a resolution first")
        return self._frame, self._z

    def _ensure_plans(self) -> list[LinePlan]:
        """Plan every line against the CURRENT frame and axis.

        Lets `CoverageError` propagate rather than caching a failure: a
        line whose recording window does not cover the z range names
        itself in the message, and spec 9.1 wants the user to act on that
        (shrink the range, or exclude the line) rather than see a slice
        with a line silently missing from it.
        """
        if self._plans is None:
            frame, z = self._require_geometry()
            self._plans = [plan_line(line, frame, z) for line in self._lines]
        return self._plans

    # ---- slices -----------------------------------------------------------
    def _slice(self, window: SliceWindow) -> tuple[np.ndarray, np.ndarray]:
        """One slice, untimed. Used where a redraw timing would be a lie --
        the shared-limit pass takes tens of windows and is not a redraw."""
        frame, z = self._require_geometry()
        if not self._lines:
            raise RuntimeError("no lines are prepared")
        plans = self._ensure_plans()
        if self._mode == "resident":
            cube = self.cube()
            return cube.slice_levels(window.k0, window.k1), cube.coverage()
        return stream_slice(self._lines, plans, frame, z, window.k0, window.k1)

    def slice_at(self, window: SliceWindow) -> tuple[np.ndarray, np.ndarray]:
        """One slice and its coverage, both (ny, nx) in the grid-local frame.

        `values` is NaN where `coverage` is zero -- unfilled, which is
        what the coverage view shows and what `fill` consumes.
        """
        if self._mode == "resident":
            self.cube()  # built outside the timer: a build is not a redraw
        started = time.perf_counter()
        result = self._slice(window)
        self._record_redraw((time.perf_counter() - started) * 1000.0)
        return result

    def _record_redraw(self, ms: float) -> None:
        if self._redraw_ms is None:
            self._redraw_ms = ms
        else:
            self._redraw_ms = _REDRAW_SMOOTHING * self._redraw_ms + (1.0 - _REDRAW_SMOOTHING) * ms

    def shared_limit(self, thickness_levels: int, clip: Any) -> float:
        """One display limit for the whole source, at this thickness.

        Spec 8's shared stretch. Measured over slices at the thickness
        being displayed and never over the raw levels -- see
        `nsgeo.slices.display.shared_limit` for the measurement that makes
        the difference a bug rather than a nuance.
        """
        _, z = self._require_geometry()
        if self._mode == "resident":
            return cube_shared_limit(self.cube(), thickness_levels, clip)
        windows = plan_windows(z, thickness_levels, thickness_levels)
        return limit_over_slices((self._slice(w)[0] for w in windows), clip)

    def cube(self) -> SliceCube:
        """The resident cube, built on first use and cached.

        A latency optimisation, never a capability (spec 7.4) -- every
        caller here works without one. The exporter and the `.npz` writer
        use it because they want the whole volume anyway.
        """
        if self._cube is None:
            frame, z = self._require_geometry()
            plans = self._ensure_plans()
            self._cube = build_cube(self._lines, plans, frame, z, self.provenance())
        return self._cube

    def provenance(self) -> Provenance:
        """What a reader needs to trust the cube.

        `line_keys` comes from the lines that were actually PREPARED, not
        from the lines that were asked for: a line that failed is not in
        the cube, and a provenance that claims it is misleads exactly the
        reader it exists for.
        """
        if self._choice is None:
            raise RuntimeError("no source is chosen")
        site = self.session.site
        steps = tuple(dict(s) for s in site.presets.get(self._choice.preset, []))
        velocity = None
        if self._lines:
            velocity = self.session.resolved_velocity(self._lines[0].key).to_dict()
        return Provenance(
            line_keys=tuple(line.key for line in self._lines),
            preset_name=self._choice.preset,
            steps=steps,
            transform=self._choice.transform or "none",
            velocity=velocity,
            built_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            core_version=nsgeo.__version__,
        )

    def status_text(self) -> str:
        return format_status(self._mode, len(self._lines), self.estimate, self._redraw_ms)

    # ---- lifecycle --------------------------------------------------------
    def clear(self) -> None:
        """Drop the source and everything derived from it."""
        self._generation += 1
        self._choice = None
        self._resolution = None
        self._lines = []
        self._plans = None
        self._frame = None
        self._z = None
        self._cube = None
        self._redraw_ms = None
        self._running = False
        # A large cube's kernel spectra are tens of megabytes and have no
        # reason to outlive the source that needed them.
        clear_kernel_cache()

    def dispose(self) -> None:
        try:
            self.session.site_closed.disconnect(self.clear)
        except (TypeError, RuntimeError):
            pass  # already disconnected, or the C++ side is gone
        self.clear()
        self.on_prepared = None
        self.on_error = None
        self.on_progress = None

    def wait_for_preparation(self, timeout_ms: int = 20_000) -> bool:
        """Spin the event loop until preparation finishes. For tests.

        Returns whether it actually finished while this waited, not merely
        whether nothing is running afterwards -- a bare timeout would
        otherwise read as success.
        """
        if not self._running:
            return True
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        finished = False
        previous = self.on_prepared

        def done() -> None:
            nonlocal finished
            finished = True
            if previous is not None:
                previous()
            loop.quit()

        self.on_prepared = done
        timer.start(timeout_ms)
        loop.exec()
        self.on_prepared = previous
        return finished and not self._running
```

- [ ] **Step 10: Run the engine tests and watch them pass**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py -q -p no:xonsh`
Expected: 11 passed. Then the whole QGIS tier, to confirm nothing regressed: 470 + 11 = 481.

- [ ] **Step 11: Prove the engine tests discriminate**

Three mutants, one at a time, each reverted after:

1. In `_rebuild_geometry`, delete `self._plans = None`. Expect
   `test_changing_the_cell_size_re_plans_every_line` to FAIL (M10's guard raises from
   `stream_slice`). **Record the exact error message** — it is the evidence that the core guard
   and the engine's own invalidation are two independent defences, not one.
2. In `_build_stack`, insert the transform first (`stack.insert(0, build_step(transform))` before
   the preset steps rather than appending). Expect the polarity assert to fire, and
   `test_preparation_applies_the_preset_and_appends_the_transform` to FAIL.
3. In `provenance`, use `self._choice.line_keys` instead of the prepared lines. Confirm
   `test_provenance_names_the_lines_that_were_actually_prepared` still passes (all four prepared)
   — then extend that test with a fifth, deliberately broken line and confirm the mutant FAILS.
   If the extension is awkward, say so in the report and record the mutant as unverified rather
   than claiming a check you did not make.

- [ ] **Step 12: Full verification and commit**

Run all four commands from the Test commands block. Expected: 512+ core+pure / 2 skipped,
481 QGIS, ruff clean, mypy `Success`.

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py \
        packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py
git commit -m "feat(slices): SliceEngine — preparation, plan cache, residency

Tier 1 on a QgsTask with loader.py's four recorded hazards handled; every
Resolution change drops every LinePlan, which is the defect M10's final
review named as M11's first bug.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 2 is done when:** both tiers are green, mypy covers `slices_plan.py` locally and in CI,
and the three engine mutants are recorded.

---

