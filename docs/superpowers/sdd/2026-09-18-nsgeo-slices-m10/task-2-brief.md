### Task 2: Amplitude transform steps

Three registry steps, so the transform a cube is built from is one you can put on a profile and *see* rather than a hidden mode. They make the data unipolar, which the renderer must learn about — Task 3 consumes the flag this task adds.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/amplitude.py`
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py` (add `is_unipolar`)
- Modify: `packages/nsgeo-core/src/nsgeo/processing/stack.py` (add `output_unipolar`)
- Modify: `packages/nsgeo-core/src/nsgeo/processing/__init__.py` (import `amplitude`, export `is_unipolar`)
- Test: `packages/nsgeo-core/tests/test_steps_amplitude.py`

**Interfaces:**
- Consumes: `ParamSpec`, `Radargram`, `register` from `nsgeo.processing.base`; `build_step`.
- Produces:
  - Steps registered as `"amp_abs"`, `"amp_square"`, `"amp_envelope"`, each taking no parameters and each carrying `unipolar = True`
  - `nsgeo.processing.amplitude.analytic_envelope(data: np.ndarray) -> np.ndarray`
  - `nsgeo.processing.base.is_unipolar(step: Any) -> bool`
  - `nsgeo.processing.stack.StepStack.output_unipolar -> bool`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_steps_amplitude.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.processing import StepStack, build_step
from nsgeo.processing.amplitude import analytic_envelope
from nsgeo.processing.base import Radargram, is_unipolar


def make(data, dt_ns=0.2165, t0_ns=0.0):
    return Radargram(data=np.asarray(data, dtype=float), dt_ns=dt_ns, t0_ns=t0_ns)


def test_amp_abs_removes_the_negative_side():
    rg = make([[-2.0, 3.0], [1.0, -4.0]])
    out = build_step("amp_abs").apply(rg)
    np.testing.assert_allclose(out.data, [[2.0, 3.0], [1.0, 4.0]])


def test_amp_square_is_energy():
    rg = make([[-2.0, 3.0]])
    np.testing.assert_allclose(build_step("amp_square").apply(rg).data, [[4.0, 9.0]])


def test_transforms_preserve_the_time_axis():
    rg = make(np.ones((10, 4)), dt_ns=0.5, t0_ns=-3.0)
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        out = build_step(name).apply(rg)
        assert out.dt_ns == 0.5
        assert out.t0_ns == -3.0
        assert out.data.shape == (10, 4)


def test_envelope_of_a_sinusoid_is_its_amplitude():
    """The defining property: the envelope rides the peaks, not the wave."""
    n = 512
    t = np.arange(n)
    wave = 3.0 * np.sin(2.0 * np.pi * t / 16.0)
    env = analytic_envelope(wave[:, None])[:, 0]
    np.testing.assert_allclose(env[32:-32], 3.0, rtol=1e-6)


def test_envelope_is_never_negative():
    rng = np.random.default_rng(0)
    env = analytic_envelope(rng.normal(size=(97, 5)))
    assert (env >= 0.0).all()


def test_envelope_handles_an_odd_and_prime_length():
    """463 rows is what time_zero leaves on the real files, and it is prime
    -- the worst case for an FFT and the one we deliberately do not pad."""
    rng = np.random.default_rng(1)
    env = analytic_envelope(rng.normal(size=(463, 3)))
    assert env.shape == (463, 3)
    assert np.isfinite(env).all()


def test_envelope_is_not_the_zero_padded_approximation():
    """Padding to a fast length is 2.2x quicker and shifts the interior by
    ~1.3%. Pin the exact transform so that optimisation cannot reappear
    silently."""
    rng = np.random.default_rng(2)
    data = rng.normal(size=(463, 2))
    exact = analytic_envelope(data)
    padded = analytic_envelope(np.pad(data, ((0, 480 - 463), (0, 0))))[:463]
    assert not np.allclose(exact, padded, rtol=1e-3)


def test_all_three_transforms_declare_themselves_unipolar():
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        assert is_unipolar(build_step(name)) is True


def test_ordinary_steps_are_not_unipolar():
    assert is_unipolar(build_step("dewow")) is False


def test_stack_output_unipolar_follows_the_last_enabled_step():
    stack = StepStack()
    stack.source = make(np.ones((8, 4)))
    stack.append(build_step("dewow"))
    assert stack.output_unipolar is False
    stack.append(build_step("amp_abs"))
    assert stack.output_unipolar is True
    stack.set_enabled(1, False)
    assert stack.output_unipolar is False


def test_empty_stack_is_not_unipolar():
    assert StepStack().output_unipolar is False


def test_transforms_take_no_parameters():
    for name in ("amp_abs", "amp_square", "amp_envelope"):
        step = build_step(name)
        assert step.params == {}
        assert step.schema() == ()


def test_unknown_parameter_is_rejected():
    with pytest.raises(ValueError, match="has no parameter"):
        build_step("amp_abs", window_ns=3.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'nsgeo.processing.amplitude'`.

- [ ] **Step 3: Implement the transforms**

Create `packages/nsgeo-core/src/nsgeo/processing/amplitude.py`:

```python
"""Amplitude transforms: what a slice is actually made of.

A slice averages amplitude over a time window, and averaging a bipolar
wiggle over a window close to one wavelength gives roughly zero wherever
the reflection is strongest. So the signed radargram is transformed first:
absolute value is the cheap default, squared amplitude is the energy
measure the archaeological literature uses, and the Hilbert envelope is
the quality option.

These are registry steps rather than a hidden mode inside the binner so
that the transform can be put on a profile and looked at -- you can see on
a radargram exactly what the cube will be built from.

All three make the data unipolar, which the renderer must know: a colour
table centred on zero would spend half its range on values that cannot
occur. `unipolar = True` is what `render` consults, through
`base.is_unipolar`.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from nsgeo.processing.base import ParamSpec, Radargram, register


def analytic_envelope(data: np.ndarray) -> np.ndarray:
    """Hilbert analytic-signal modulus along axis 0. numpy only, no scipy.

    The analytic signal is built by doubling the positive frequencies of a
    full FFT and zeroing the negative half; its modulus is the envelope.

    The FFT is taken at the array's own length and is **never zero-padded
    to a faster one**. After `time_zero` the real files leave 463 rows,
    which is prime and therefore the worst case for an FFT -- padding to
    480 is 2.2x faster and was measured and rejected, because the Hilbert
    transform is non-local: padding shifts the result by ~1.3% through the
    interior and ~13% in the last rows. This step runs once per line in the
    cached tier, so exactness is the better trade. (Reflect-padding is
    worse than zero-padding here, at ~2.6% interior, not better.)
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError(f"expected a 2-D radargram, got shape {data.shape}")
    n = data.shape[0]
    spectrum = np.fft.fft(data, axis=0)
    weights = np.zeros(n)
    weights[0] = 1.0
    if n % 2 == 0:
        weights[n // 2] = 1.0
        weights[1 : n // 2] = 2.0
    else:
        weights[1 : (n + 1) // 2] = 2.0
    return np.abs(np.fft.ifft(spectrum * weights[:, None], axis=0))


class _NoParams:
    """Shared shape for the three transforms: no parameters, no choices."""

    unipolar = True

    def __init__(self) -> None:
        pass

    @property
    def params(self) -> Dict[str, Any]:
        return {}

    @classmethod
    def schema(cls) -> Tuple[ParamSpec, ...]:
        return ()


@register
class AmpAbs(_NoParams):
    name = "amp_abs"

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=np.abs(rg.data))


@register
class AmpSquare(_NoParams):
    name = "amp_square"

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=rg.data * rg.data)


@register
class AmpEnvelope(_NoParams):
    name = "amp_envelope"

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=analytic_envelope(rg.data))
```

- [ ] **Step 4: Add the `is_unipolar` helper**

In `packages/nsgeo-core/src/nsgeo/processing/base.py`, immediately after the `Step` protocol class, add:

```python
def is_unipolar(step: Any) -> bool:
    """Whether a step's output has no negative side.

    Read with `getattr` rather than declared on the `Step` protocol: every
    existing step is structurally a Step without the attribute, and adding
    a required one would break that silently at type-check time for no
    gain. Absent means bipolar, which is the correct default for every
    step that filters or gains a signed wiggle.
    """
    return bool(getattr(step, "unipolar", False))
```

- [ ] **Step 5: Add `StepStack.output_unipolar`**

In `packages/nsgeo-core/src/nsgeo/processing/stack.py`, change the import line to:

```python
from nsgeo.processing.base import Radargram, build_step, is_unipolar
```

and add this property in the `# ---- inspection ----` section, after `cache_size`:

```python
    @property
    def output_unipolar(self) -> bool:
        """Whether `result()` has no negative side.

        The last *enabled* step decides, because a disabled transform is
        not applied. Consulted by front ends choosing a colour table: a
        bipolar table on unipolar data wastes half its range.
        """
        for step, enabled in reversed(self._entries):
            if enabled:
                return is_unipolar(step)
        return False
```

- [ ] **Step 6: Register the module and export the helper**

In `packages/nsgeo-core/src/nsgeo/processing/__init__.py`, add `amplitude,` to the first import block (keeping alphabetical order, so it goes first) and `is_unipolar,` to the `base` import block (alphabetically, after `get_step`):

```python
from nsgeo.processing import (  # noqa: F401
    amplitude,
    background,
    bandpass,
    dewow,
    gain,
    timezero,
)
from nsgeo.processing.base import (  # noqa: F401
    REQUIRED,
    ParamSpec,
    Radargram,
    Step,
    available_steps,
    build_step,
    default_params,
    get_step,
    is_unipolar,
    nyquist_mhz,
    register,
    required_params,
)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest packages/nsgeo-core/tests/test_steps_amplitude.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the whole core suite**

Run: `python -m pytest packages/nsgeo-core/tests -q`

Expected: all pass. Two existing tests in `tests/test_schema.py` iterate every registered step and must still hold — `test_schema_names_match_params_keys_in_order` (trivially true for an empty schema and empty params) and `test_only_the_two_known_steps_have_required_params` (still true, since none of the three declares a `REQUIRED` default). If either fails, the new steps are wrong, not the tests.

- [ ] **Step 9: Lint, type-check and commit**

```bash
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src
git add packages/nsgeo-core/src/nsgeo/processing packages/nsgeo-core/tests/test_steps_amplitude.py
git commit -m "feat(processing): amp_abs, amp_square and amp_envelope steps

Registry steps rather than a mode inside the binner, so the transform a
cube is built from can be put on a profile and seen. The envelope is an
FFT analytic signal in numpy alone, taken at the array's own length: a
test pins it against the zero-padded approximation, which is 2.2x faster
and wrong by ~1.3% through the interior.

All three declare unipolar = True, read through base.is_unipolar and
surfaced as StepStack.output_unipolar for front ends choosing a palette.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

