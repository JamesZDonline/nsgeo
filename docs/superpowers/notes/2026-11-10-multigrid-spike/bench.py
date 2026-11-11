"""Minimum-curvature timings for the table in `nsgeo/slices/curvature.py` (#111).

Public API only, so it runs unchanged before and after the multigrid build.
Run from the worktree root:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/superpowers/notes/2026-11-10-multigrid-spike/bench.py

Max distance 0.375 m (0.75 x the 0.5 m line spacing) throughout. The "real
lines" rows need the ten local DZT files in packages/nsgeo-core/tests/data/local
and are skipped without them. Nothing else should run on the machine meanwhile.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "nsgeo-core"))

from nsgeo.slices import CubeFrame, plan_curvature  # noqa: E402

MAX_DISTANCE = 0.375
REPEATS = 3


def fields(shape, cell, n):
    """`n` smooth fields with some short-wavelength detail, one per slice."""
    y, x = (np.indices(shape) + 0.5) * cell
    return [
        np.sin(x / (1.7 + k)) * np.cos(y / (2.3 - 0.3 * k)) + 0.3 * np.sin(3.1 * x + 1.3 * y + k)
        for k in range(n)
    ]


def wandering(size_m, cell, covered=1.0, skip_one=False):
    """Lines along X, 0.5 m apart, each wandering +-6 cm, over the lower
    `covered` fraction of a square frame `size_m` on a side."""
    n = int(round(size_m / cell))
    pop = np.zeros((n, n), bool)
    x = (np.arange(n) + 0.5) * cell
    centres = np.arange(0.25, covered * size_m, 0.5)
    if skip_one:
        centres = np.delete(centres, centres.size // 2)
    for i, y0 in enumerate(centres):
        y = y0 + 0.06 * np.sin(x / 3.0 + i)
        pop[np.clip((y / cell).astype(int), 0, n - 1), np.arange(n)] = True
    return pop


def row(name, pop, cell, slices, repeats=REPEATS):
    started = time.perf_counter()
    plan = plan_curvature(pop, cell, MAX_DISTANCE)
    planned = time.perf_counter() - started
    times, iterations = [], []
    for v in slices[:repeats]:
        started = time.perf_counter()
        _, its = plan.solve(v)
        times.append(time.perf_counter() - started)
        iterations.append(its)
    print(
        f"    {name:34s} {planned:7.3f} s  {np.median(times):8.3f} s  {int(np.median(iterations)):6d}",
        flush=True,
    )


def real_rows():
    from tests.real_lines import FILES, SPACING, WINDOWS, binned, prepared_lines

    if len(FILES) < 10:
        print("    (real lines skipped: the ten local DZT files are not there)")
        return
    lines = prepared_lines(range(10), lambda local: local)
    for cell in (0.2, 0.05):
        nx, ny = int(round(20 / cell)), int(round(10 * SPACING / cell))
        frame = CubeFrame((0.0, 0.0), 0.0, cell, nx, ny, "EPSG:32633")
        binned_slices = [binned(lines, frame, k0, k1) for k0, k1 in WINDOWS[:REPEATS]]
        pop = binned_slices[0][1] > 0
        row(f"real lines, {cell} m", pop, cell, [v for v, _ in binned_slices])


def main():
    print(f"    {'case':34s} {'plan':>9s}  {'solve':>10s}  {'iters':>6s}")
    real_rows()
    for cell in (0.2, 0.1, 0.05):
        pop = wandering(50.0, cell)
        row(f"50 m grid, {cell} m", pop, cell, fields(pop.shape, cell, REPEATS))
    pop = wandering(50.0, 0.2, covered=0.4, skip_one=True)
    row("50 m, 40% covered, line skipped", pop, 0.2, fields(pop.shape, 0.2, REPEATS))


if __name__ == "__main__":
    main()
