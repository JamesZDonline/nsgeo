"""A test-only Sensors & Software DT1 writer, copying the real layout (spec M21 §2).

The `.HD` starts with the free lines real files start with (`1234`, the
instrument, a date) and then holds one `KEY = value` per line, CRLF-ended. The
`.DT1` holds, per trace, a 128-byte header (25 little-endian float32 values,
then 28 bytes of comment) and the samples. Trace-header values: 0 the trace
number from 1, 1 the position, 2 the samples per trace, 5 the bytes per
sample, 6 the time window, 7 the stack count.

Synthetic files prove self-consistency only; the real files in
`tests/data/local/dt1-a` and `dt1-b` catch real quirks.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

TRACE_HEADER_BYTES = 128


def write_dt1(
    path: Path,
    data: np.ndarray,
    *,
    step: float = 0.25,
    window_ns: float = 400.0,
    timezero_point: float | None = 10.0,
    frequency: float | None = 100.0,
    survey_mode: str | None = "Reflection",
    units: str | None = "m",
    bytes_per_sample: int = 2,
    header_bytes_per_sample: int | None = None,
    hd_suffix: str = ".HD",
    hd_extra: Sequence[str] = (),
    drop_keys: Sequence[str] = (),
    hd_values: dict[str, str] | None = None,
    positions: Sequence[float] | None = None,
    start: float = 0.0,
) -> Path:
    """Write `data` (n_samples, n_traces) as `path` (.DT1) and its `.HD` beside it.

    `None` for an optional value leaves its key out of the `.HD`, as does
    naming the key in `drop_keys`. `hd_values` replaces a key's value as
    written (to write a non-number, say). `positions` overrides the per-trace
    positions, which otherwise step by `step` from `start`.
    `header_bytes_per_sample` is what trace-header value 5 says, by default the
    true width.
    """
    path = Path(path)
    data = np.asarray(data)
    n_samples, n_traces = data.shape
    if positions is None:
        positions = [start + i * step for i in range(n_traces)]
    keys: list[tuple[str, object]] = [
        ("NUMBER OF TRACES", n_traces),
        ("NUMBER OF PTS/TRC", n_samples),
        ("TIMEZERO AT POINT", timezero_point),
        ("TOTAL TIME WINDOW", window_ns),
        ("STARTING POSITION", positions[0] if n_traces else start),
        ("FINAL POSITION", positions[-1] if n_traces else start),
        ("STEP SIZE USED", step),
        ("POSITION UNITS", units),
        ("NOMINAL FREQUENCY", frequency),
        ("ANTENNA SEPARATION", 1.0),
        ("PULSER VOLTAGE (V)", 400),
        ("NUMBER OF STACKS", 16),
        ("SURVEY MODE", survey_mode),
    ]
    lines = ["1234", "Data Collected with pE PRO (test)", "2026-01-01"]
    for key, value in keys:
        if value is None or key in drop_keys:
            continue
        shown = (hd_values or {}).get(key, value)
        lines.append(f"{key:<19}= {shown} ")
    lines.extend(hd_extra)
    path.with_suffix(hd_suffix).write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))

    dtype = {2: "<i2", 4: "<i4"}[bytes_per_sample]
    said = bytes_per_sample if header_bytes_per_sample is None else header_bytes_per_sample
    with open(path, "wb") as fh:
        for i in range(n_traces):
            values = np.zeros(25, dtype="<f4")
            values[0] = i + 1
            values[1] = positions[i]
            values[2] = n_samples
            values[5] = said
            values[6] = window_ns
            values[7] = 16
            fh.write(values.tobytes() + b"\0" * (TRACE_HEADER_BYTES - 100))
            fh.write(data[:, i].astype(dtype).tobytes())
    return path
