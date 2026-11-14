"""What flows through processing, and how steps are discovered.

A step returns a whole Radargram rather than a bare array. Time-zero
correction crops rows and relabels the clock, so a step that returned only an
array would silently desynchronise the time axis from the data. Returning the
Radargram makes that an obvious test failure instead of a silent bug.

`time_zero` relabels the clock: the row it lands on reads 0 ns, and `zero_ns`
keeps every row's radar time (`zero_ns + t0_ns + i * dt_ns`). Every other step
passes the clock through untouched.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from typing import Any, ClassVar, Final, Protocol

import numpy as np


@dataclass(frozen=True, eq=False)
class Radargram:
    """Equality is identity (`eq=False`): comparing arrays is a test concern,
    done with `np.testing`."""

    data: np.ndarray
    dt_ns: float
    t0_ns: float
    #: Metres between traces, from the header's `traces_per_metre`. None when
    #: the file was collected on a timer rather than a survey wheel and so has
    #: no spatial axis. Optional and last so every existing construction and
    #: every `replace()` keeps working untouched.
    dx_m: float | None = None
    #: The radar-clock time this axis calls 0. Row `i` is at radar time
    #: `zero_ns + t0_ns + i * dt_ns`.
    zero_ns: float = 0.0
    #: True once a Time zero step has set the clock.
    zero_set: bool = False

    def __post_init__(self) -> None:
        if np.asarray(self.data).ndim != 2:
            raise ValueError(f"radargram data must be 2-D, got shape {self.data.shape}")
        if not self.dt_ns > 0:
            raise ValueError(f"dt_ns must be positive, got {self.dt_ns}")

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[0])

    @property
    def n_traces(self) -> int:
        return int(self.data.shape[1])

    def times_ns(self) -> np.ndarray:
        """Two-way time of each sample row."""
        return self.t0_ns + np.arange(self.n_samples, dtype=float) * self.dt_ns

    def to_radar_ns(self, t: Any) -> Any:
        """Convert time on this axis to the radar's own clock (float or array)."""
        return retime_ns(t, self.zero_ns, 0.0)

    def from_radar_ns(self, r: Any) -> Any:
        """Convert radar-clock time to this axis (float or array)."""
        return retime_ns(r, 0.0, self.zero_ns)

    def replace(self, **changes: Any) -> Radargram:
        return _dc_replace(self, **changes)

    @classmethod
    def from_profile(cls, profile: Any) -> Radargram:
        """Build from a model.Profile without importing it, keeping
        processing independent of the data model.

        Reads three header fields -- `dt_ns`, `position_ns` and
        `traces_per_metre` -- and nothing from the model itself, so the
        independence holds: these are facts about the file, not objects.
        `traces_per_metre <= 0` means the file was collected on a timer
        rather than a survey wheel, and leaves `dx_m` None rather than
        inventing a spacing for a line that has none.
        """
        tpm = profile.header.traces_per_metre
        return cls(
            data=np.asarray(profile.data, dtype=float),
            dt_ns=profile.header.dt_ns,
            t0_ns=profile.header.position_ns,
            dx_m=(1.0 / tpm) if tpm > 0 else None,
        )


def retime_ns(t: Any, from_zero_ns: float, to_zero_ns: float) -> Any:
    """Move time `t` from the axis whose zero is `from_zero_ns` (radar clock)
    to the one whose zero is `to_zero_ns`. The one conversion rule; float or
    array in, same kind out."""
    return t + (from_zero_ns - to_zero_ns)


def nyquist_mhz(dt_ns: float) -> float:
    """Nyquist frequency, in MHz, for a sample interval given in ns.

    `1 / (2 * dt_ns * 1e-9)` in Hz, rearranged to take `dt_ns` directly and
    return MHz: `(1 / (2 * dt_ns * 1e-9)) / 1e6 == 500.0 / dt_ns`. Shared so
    a front end reporting "this file's Nyquist" (a fact about the header,
    not a processing step) and `Bandpass.apply`'s own guard use the same
    formula rather than risking two copies drifting apart.
    """
    return 500.0 / dt_ns


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
    curve editor, time is a float two-way time in ns on the radargram's own
    axis (validated like float, but a front end may let the user drag it on
    the profile instead of typing it). `default` is a value or REQUIRED.
    """

    KINDS: ClassVar[tuple[str, ...]] = ("float", "int", "choice", "curve", "time")

    name: str
    kind: str
    label: str
    default: Any
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    #: When true the value must be strictly above `min`, not merely at it.
    min_exclusive: bool = False
    choices: tuple[str, ...] = field(default=())
    help: str = ""

    def __post_init__(self) -> None:
        if self.kind not in self.KINDS:
            raise ValueError(f"unknown param kind {self.kind!r}; expected one of {self.KINDS}")
        if self.kind == "choice" and not self.choices:
            raise ValueError(f"param {self.name!r} is a choice but declares no choices")
        if self.kind != "choice" and self.choices:
            raise ValueError(f"param {self.name!r} is {self.kind!r} but declares choices")
        if (
            self.kind == "choice"
            and self.default is not REQUIRED
            and self.default not in self.choices
        ):
            raise ValueError(f"param {self.name!r} default {self.default!r} is not in choices")

    @property
    def required(self) -> bool:
        return self.default is REQUIRED


#: The groups a step menu is laid out in, in the usual processing order.
#: Every step's `group` names one of these.
STEP_GROUPS: Final = ("Time", "Filters", "Background", "Migration", "Gain", "Amplitude")


class Step(Protocol):
    """A pure function of (parameters, radargram). No I/O, no hidden state.

    `name` is the id a saved stack stores; `title` is what a front end shows
    wherever it names the step. `group` and `order` place it in a step menu:
    one of `STEP_GROUPS`, and its position inside that group, lowest first.
    None of the three display attributes is ever saved, so rewording a title
    or regrouping a step leaves every project file as it was.
    """

    name: str
    title: str
    group: str
    order: int

    @property
    def params(self) -> dict[str, Any]: ...

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]: ...

    def apply(self, rg: Radargram) -> Radargram: ...


def is_unipolar(step: Any) -> bool:
    """Whether a step's output has no negative side.

    Read with `getattr` rather than declared on the `Step` protocol: every
    existing step is structurally a Step without the attribute, and adding
    a required one would break that silently at type-check time for no
    gain. Absent means bipolar, which is the correct default for every
    step that filters or gains a signed wiggle.
    """
    return bool(getattr(step, "unipolar", False))


_REGISTRY: dict[str, type[Any]] = {}


def register(cls: type[Any]) -> type[Any]:
    """Class decorator adding a step to the registry.

    Front ends enumerate the registry and build parameter widgets from each
    step's declared params, so new instruments contribute steps without any
    UI change.

    A name may be claimed once. The registry is what a saved
    `{"step": "gain_agc"}` resolves through, so a second front end or a
    user's own step module quietly taking a name already in use would make
    import order decide which implementation a saved stack runs -- the same
    project file producing different processing on different machines, with
    nothing in the file or the UI to say so. Re-registering the very same
    class is allowed, since a module imported twice is not a conflict.
    """
    existing = _REGISTRY.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"step name {cls.name!r} is already registered to "
            f"{existing.__module__}.{existing.__qualname__}; "
            f"{cls.__module__}.{cls.__qualname__} must choose another name, "
            f"because a saved stack naming it would resolve to whichever was "
            f"imported last"
        )
    problem = _display_problem(cls)
    if problem is not None:
        raise ValueError(f"step {cls.name!r}: {problem}")
    _REGISTRY[cls.name] = cls
    return cls


def _display_problem(cls: type[Any]) -> str | None:
    """What is wrong with a step's `title`, `group` or `order`, or None.

    Checked at registration because a front end reads them far from where
    the step is defined: a step without a `group` stopped the Processing
    panel loading, and one with an unknown group silently left every menu.
    """
    title = getattr(cls, "title", None)
    if not isinstance(title, str) or not title.strip():
        return f"title must be a non-empty string, got {title!r}"
    group = getattr(cls, "group", None)
    if group not in STEP_GROUPS:
        return f"group must be one of {STEP_GROUPS}, got {group!r}"
    order = getattr(cls, "order", None)
    if not isinstance(order, int) or isinstance(order, bool):
        return f"order must be an int, got {order!r}"
    return None


def available_steps() -> list[str]:
    return sorted(_REGISTRY)


def grouped_steps() -> list[tuple[str, list[str]]]:
    """Every registered step by group: groups in `STEP_GROUPS` order, steps
    inside a group by their `order`. A group with no steps is left out."""
    groups = []
    for group in STEP_GROUPS:
        members = [cls for cls in _REGISTRY.values() if cls.group == group]
        if members:
            groups.append((group, [cls.name for cls in sorted(members, key=lambda c: c.order)]))
    return groups


def step_title(name: str) -> str:
    """The title a front end shows for step `name`."""
    return str(get_step(name).title)


def get_step(name: str) -> type[Any]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown step {name!r}; available: {available_steps()}") from None


def _out_of_bounds(spec: ParamSpec, value: float) -> str | None:
    """Why `value` is outside `spec`'s declared bounds, or None if it is not."""
    if spec.min is not None:
        if spec.min_exclusive:
            if value <= spec.min:
                return f"must be > {spec.min}"
        elif value < spec.min:
            return f"must be >= {spec.min}"
    if spec.max is not None and value > spec.max:
        return f"must be <= {spec.max}"
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_))


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _curve_problem(spec: ParamSpec, value: Any) -> tuple[str, Any] | None:
    """What is wrong with a curve's points, and the offending dB entry (or None)."""
    try:
        points = list(value)
        if not all(len(point) == 2 for point in points):
            return "must be (time, dB) pairs of numbers", None
        pairs = [(point[0], point[1]) for point in points]
    except (TypeError, KeyError, IndexError):
        return "must be (time, dB) pairs of numbers", None
    if len(pairs) < 2:
        return "must have at least two points", None
    for t, db in pairs:
        if not (_is_number(t) and _is_number(db)):
            return "must be (time, dB) pairs of numbers", None
        if not (_is_finite(t) and _is_finite(db)):
            return "must be pairs of finite numbers", None
    for _, db in pairs:
        reason = _out_of_bounds(spec, db)
        if reason is not None:
            return reason, db
    return None


def _problem(spec: ParamSpec, value: Any) -> tuple[str, Any] | None:
    if spec.kind == "choice":
        if not isinstance(value, str) or value not in spec.choices:
            return f"must be one of {list(spec.choices)}", None
    elif spec.kind == "int":
        if not isinstance(value, numbers.Integral) or isinstance(value, (bool, np.bool_)):
            return "must be a whole number", None
    elif spec.kind in ("float", "time"):
        if not _is_number(value):
            return "must be a number", None
        if not _is_finite(value):
            return "must be a finite number", None
    elif spec.kind == "curve":
        return _curve_problem(spec, value)
    else:
        return None
    if spec.kind in ("int", "float", "time"):
        reason = _out_of_bounds(spec, value)
        if reason is not None:
            return reason, None
    return None


def param_problem(spec: ParamSpec, value: Any) -> str | None:
    """Why `value` cannot be the setting `spec` declares, as a reason phrase, or None.

    The one place that decides, so `build_step` and the project-load repair
    agree. The phrases are quoted in user-facing notes: reword with care.
    """
    found = _problem(spec, value)
    return None if found is None else found[0]


def _validate_params(name: str, cls: type[Any], params: dict[str, Any]) -> None:
    """Check `params` against `cls.schema()` before the constructor sees them.

    Every step declares bounds and nothing enforced them: `build_step`
    passed `**params` straight through, and the plugin's parameter form
    reads no `spec.min`/`spec.max` at all because its own docstring says
    the core's validation is the only validation. Both halves believed the
    other one checked, so `gain_agc(target=-3.0)` (schema: min 0.0)
    inverted every sample's polarity and `time_zero(threshold=5.0)`
    (schema: max 1.0) silently did nothing -- both reachable from a
    hand-edited project file, a preset copied between machines, or any
    future front end, none of which raised.

    Here rather than in each step's `__init__` because this is the single
    funnel: the UI, `StepStack.from_dicts` (so every saved project and
    every preset), and any second front end all arrive through it. A rule
    added here is enforced for all of them at once; a rule added in a front
    end has to be added again by the next one.

    Raises ValueError, not the TypeError a bad `**kwargs` would otherwise
    produce: callers around every build_step in this repo already treat a
    rejected parameter set as a ValueError, and a parameter that is
    out of bounds is a bad value, not a bad call signature.
    """
    specs = {s.name: s for s in cls.schema()}
    unknown = sorted(set(params) - set(specs))
    if unknown:
        raise ValueError(f"step {name!r} has no parameter(s) {unknown}; it takes {sorted(specs)}")
    missing = sorted(s.name for s in specs.values() if s.required and s.name not in params)
    if missing:
        raise ValueError(f"step {name!r} requires {missing}, which has no safe default")
    for pname in sorted(params):
        spec = specs[pname]
        value = params[pname]
        found = _problem(spec, value)
        if found is None:
            continue
        reason, entry = found
        unit = f" {spec.unit}" if spec.unit else ""
        if spec.kind == "curve" and entry is not None:
            raise ValueError(f"step {name!r}: every {pname} value {reason}, got {entry}{unit}")
        raise ValueError(f"step {name!r}: {pname} {reason}, got {value!r}{unit}")


def build_step(name: str, **params: Any) -> Any:
    """The one way a step is constructed. Validates against `schema()` first."""
    cls = get_step(name)
    _validate_params(name, cls, params)
    return cls(**params)


def default_params(name: str) -> dict[str, Any]:
    """Constructor kwargs for every parameter that has a real default."""
    return {s.name: s.default for s in get_step(name).schema() if not s.required}


def required_params(name: str) -> tuple[str, ...]:
    """Parameters the UI must collect before the step can be built."""
    return tuple(s.name for s in get_step(name).schema() if s.required)
