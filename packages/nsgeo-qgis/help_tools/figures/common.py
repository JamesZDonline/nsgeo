"""Shared drawing for the help-page figures.

Every recipe (`<step>.py`) builds on these four helpers and `save`:

- `load_radargram(dzt)`: the line, as nsgeo itself loads it.
- `stack_of(rg, steps)`: a `StepStack`, so a figure shows what the step really did.
- `panels(...)`: the before / after / difference figure.
- `antenna_mhz(header)`: the antenna's centre frequency, read from the header.
- `save(fig, path)`: the one way a figure reaches disk (a compact palette PNG).

Keep this API small and stable: every recipe depends on it.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from nsgeo.io.dzt import DztHeader, read_header, read_samples  # noqa: E402
from nsgeo.processing import Radargram, StepStack  # noqa: E402
from nsgeo.render import DEFAULT_COLORMAP, PercentileClip, colormap, to_rgb8  # noqa: E402

__all__ = ["antenna_mhz", "load_radargram", "panels", "save", "stack_of"]


def load_radargram(dzt: Path) -> tuple[Radargram, DztHeader]:
    """Channel 0 of `dzt` as a Radargram, plus its header.

    Mirrors `Radargram.from_profile`: `dt_ns` from the header, `t0_ns` from its
    `position_ns`.
    """
    header = read_header(dzt)
    data = read_samples(dzt, header)[0].astype(float)
    return Radargram(data=data, dt_ns=header.dt_ns, t0_ns=header.position_ns), header


def stack_of(rg: Radargram, steps: list) -> StepStack:
    """A `StepStack` over `rg` holding `steps` in order, all enabled."""
    stack = StepStack()
    stack.source = rg
    for step in steps:
        stack.append(step)
    return stack


def antenna_mhz(header: DztHeader) -> int | None:
    """The first 2-4 digit run in `header.antenna` ("HS350US" -> 350), else None."""
    match = re.search(r"\d{2,4}", header.antenna or "")
    return int(match.group()) if match else None


def save(fig, path: Path, *, dpi: int = 120) -> Path:
    """Write `fig` to `path` as a compact PNG, close it, and return `path`.

    The image is quantized to an 8-bit palette (at most 256 colours) and the PNG
    optimized. Greyscale radargram panels have few colours, so nothing visible
    is lost, and the files stay small enough to ship in the plugin.
    """
    from PIL import Image

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    with Image.open(buf) as im:
        small = im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    small.save(path, format="PNG", optimize=True)
    return path


def _draw(ax, arr: np.ndarray, title: str, x: np.ndarray, t: np.ndarray, t_max: float) -> None:
    lut = colormap(DEFAULT_COLORMAP)
    lim = PercentileClip(99).limit(arr)
    ax.imshow(
        to_rgb8(arr, lim, lut),
        aspect="auto",
        extent=[x[0], x[-1], t[-1], t[0]],
        interpolation="nearest",
    )
    ax.set_ylim(t_max, t[0])
    ax.set_title(title, fontsize=10, loc="left")
    ax.tick_params(labelsize=7)


def panels(
    stack: StepStack,
    index: int,
    out: Path,
    after_title: str,
    removed_title: str,
    header: DztHeader,
    t_max_ns: float | None = 50.0,
    *,
    dpi: int = 120,
) -> Path:
    """The before / after / difference figure for step `index` of `stack`.

    Before is the step's input (the source for index 0), after is its output, and
    the third panel is `stack.difference(index)`. Each panel is scaled on its own
    (99th percentile) with the default colormap. The y axis is two-way time, down
    to `t_max_ns` (`None` means the full trace). The x axis is distance, or trace
    number when the header has no `traces_per_metre`.
    """
    before = stack.intermediate(index - 1) if index else stack.source
    after = stack.intermediate(index)
    removed = stack.difference(index)
    t = after.times_ns()
    n = after.n_traces
    if header.traces_per_metre:
        x = np.arange(n) / header.traces_per_metre
        xlabel = "Distance along line (m)"
    else:
        x = np.arange(n, dtype=float)
        xlabel = "Trace number"
    t_max = float(t[-1]) if t_max_ns is None else t_max_ns
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.2), sharey=True, constrained_layout=True)
    for ax, arr, title in zip(
        axes, (before.data, after.data, removed.data), ("Before", after_title, removed_title)
    ):
        _draw(ax, arr, title, x, t, t_max)
        ax.set_xlabel(xlabel, fontsize=8)
    axes[0].set_ylabel("Two-way time (ns)", fontsize=8)
    return save(fig, out, dpi=dpi)
