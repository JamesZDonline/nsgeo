"""What a step receives: the queries behind the Processing panel's forms and the gain strip.

Plain functions over a `SiteSession`, no Qt widgets. The dock asks what a new
step's time field is bounded by and what to seed it with; the plugin's gain
strip asks whether a step's clock is known yet. Both need the same answer to
"is the clock still unknown behind an enabled Time zero", so it lives here
once (`clock_unknown`) instead of being copied.
"""

from __future__ import annotations

from typing import Any

from nsgeo.processing import Radargram, StepStack, first_break_row_or_none

from nsgeo_qgis.log import log as _log
from nsgeo_qgis.session import SiteSession


def clock_unknown(stack: StepStack, row: int) -> bool:
    """True when the samples have not loaded and an enabled `time_zero` sits
    above `row`: the header's radar clock is the wrong one then, and the real
    clock is unknown until the source arrives."""
    if stack.source is not None:
        return False
    return any(step.name == "time_zero" and on for step, on in stack.entries[:row])


def input_axis(session: SiteSession, key: str, row: int) -> tuple[float, float, int] | None:
    """(t0_ns, dt_ns, n_samples) of what the step at `row` receives:
    the stack's state after the step above it, or the source when it is
    first. Bounds a time field to the record that step can clip, so a
    `time_zero` ahead of it moves the lower limit. Falls back the way
    `time_axis` does when the stack does not evaluate cleanly.

    None when the samples have not loaded and an enabled `time_zero` sits
    above `row`: the header's radar-clock range is the wrong clock then,
    and the real one is unknown until the source arrives (the dock
    re-shows the form on `line_loaded`)."""
    stack = session.stack_for(key)
    if stack.source is not None:
        try:
            rg = stack.intermediate(row - 1) if row > 0 else stack.source
        except ValueError as exc:
            _log(
                f"input_axis: stack does not evaluate cleanly ({exc}); "
                "using the raw source axis instead (seed or field bound)"
            )
            rg = stack.source
        return rg.t0_ns, rg.dt_ns, rg.n_samples
    if clock_unknown(stack, row):
        return None
    h = session.line_for_key(key).header
    return h.position_ns, h.dt_ns, h.n_samples


def time_zero_seed(session: SiteSession, key: str, row: int, threshold: float) -> int | None:
    """The first-break row of what the step at `row` receives (the stack's state
    after the step above it, or the source when it is first), counted from that
    record's first row. None when the samples have not loaded, the record has no
    arrival, or the steps above it refuse. A Time zero set to this row crops
    what its own first-break mode would."""
    stack = session.stack_for(key)
    if stack.source is None:
        return None
    try:
        rg = stack.intermediate(row - 1) if row > 0 else stack.source
    except ValueError as exc:
        _log(f"time_zero_seed: the steps above row {row} do not evaluate ({exc})")
        return None
    return first_break_row_or_none(rg, threshold)


def time_axis(session: SiteSession, key: str) -> tuple[float, float, int]:
    """(t0_ns, dt_ns, n_samples) of the input a step appended right now
    would actually receive: the stack's own `result()` when it
    evaluates cleanly, so a step already in the stack that changes the
    axis (`time_zero` crops `n_samples` and relabels `t0_ns` -- see
    `nsgeo.processing.timezero`) is accounted for, exactly as the new
    step's own `apply()` will see it. Only used today to seed a new
    step's required parameters (see `add_step_with_dialog`): a curve's
    identity default, and a time at the record's end, so the
    distinction only bites once something ahead of it in the stack
    changes the sample axis.

    `result()` can raise `ValueError` when some OTHER step already in
    the stack is misconfigured (a bandpass whose high cut exceeds
    Nyquist, say) -- that is a problem with that step, not a reason
    this method should raise too: it falls back to the stack's raw
    source instead, same as before this method looked at `result()` at
    all. Logged when it fires: the seed then lands on the raw axis while
    the viewer keeps its last good (possibly quite different) transform,
    so a curve step seeded right now can end up with control points
    off the drawn axis with nothing said otherwise.

    With no samples loaded yet it reads the line's header, the radar's
    clock (`input_axis`), unless an enabled `time_zero` is in the stack:
    then the header is the wrong clock and the real one is unknown, so it
    is `(0.0, dt, n_samples)` from the header. On the time-zero clock the
    record starts at 0 and has at most the header's samples, so a time
    seeded at its end crops nothing (#163 item 3)."""
    axis = input_axis(session, key, len(session.stack_for(key).entries))
    if axis is None:
        # Behind a time_zero with no samples yet: the record starts at 0
        # on the time-zero clock and has at most the header's samples, so
        # a cutoff seeded at its end crops nothing.
        h = session.line_for_key(key).header
        return 0.0, h.dt_ns, h.n_samples
    return axis


def probe_radargram(session: SiteSession, key: str) -> Radargram | None:
    """What a step appended right now would actually receive: the
    stack's own `result()`, so a step already in the stack that changed
    the record is accounted for, exactly as the new step's own
    `apply()` will see it.

    The same quantity `time_axis` already describes, and the same
    fallback for the same reason: `result()` raises `ValueError` when
    some OTHER step in the stack is misconfigured, which is a problem
    with that step, not grounds for refusing to open the Add dialog.
    Logged when it fires, because the probe then validates against the
    raw source and can disagree with what the step will meet.

    This was `stack.source` -- the raw radargram, `t0 = -11.09` on
    every real file -- which left `migrate_fk` permanently un-addable
    with a disabled OK button and a message about a time zero that was
    already corrected two rows above it.
    """
    stack = session.stack_for(key)
    if stack.source is None:
        return None
    try:
        return stack.result()
    except ValueError as exc:
        _log(
            f"probe_radargram: stack does not evaluate cleanly ({exc}); "
            "validating the new step against the raw source instead"
        )
        return stack.source


def seed_params(session: SiteSession, name: str, key: str) -> dict[str, Any] | None:
    """What to start `name`'s fields at for this line, or None.

    Migration's velocity starts at whatever `resolve_velocity` says --
    line override, then the grid, then the header's dielectric -- so
    the field opens on the same number the depth axis and every pick
    already use. A seed only: once the step exists the value is its
    own, and a later velocity change does not reach back into it.
    """
    if name != "migrate_fk":
        return None
    try:
        return {"velocity_m_ns": session.resolved_velocity(key).surface_velocity}
    except ValueError as exc:
        # e.g. a header with a non-positive epsr, which loads fine and
        # fails when its velocity is resolved. A prefill is a
        # convenience; failing to make one must not stop the dialog
        # opening at all, which is the shape `plugin.py` already uses.
        _log(f"seed_params: cannot resolve a velocity for {key} ({exc}); leaving the field blank")
        return None
