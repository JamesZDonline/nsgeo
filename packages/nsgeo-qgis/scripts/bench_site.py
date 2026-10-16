"""Time the site view on a realistic synthetic site (M12 spec 4.8).

Ten grids, 20 m and 50 m on a side, 0.5 m line spacing, at M11's default
resolution: cell = min(0.5, spacing / 2), dz = the native sample interval,
the z range the prepared lines share, thickness 5 ns, fill radius 1.5 line
spacings. Runs offscreen in `.venv-qgis` with no plugin and no iface:

    QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python \\
        packages/nsgeo-qgis/scripts/bench_site.py [--samples 128] [--tpm 60]

Synthetic lines are fine for timing (spec 4.8). A tick's cost goes with
traces (traces per metre) and frame size, not with the samples per trace,
so `--samples` is kept small by default to fit the 10 x 50 m site in
memory: at 512 samples it would hold about 5.7 GB of prepared lines. The
short time axis gives the stretch pass fewer windows than a full one, so
it is also timed at a thickness that fills Ruling 4's twelve.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PLUGIN_DIR = HERE.parent
CORE_DIR = PLUGIN_DIR.parent / "nsgeo-core"
for _path in (PLUGIN_DIR, CORE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import nsgeo_qgis  # noqa: E402,F401  (runs the core path shim)

PRESET = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
    {"step": "gain_agc", "params": {}, "enabled": True},
]
SPACING = 0.5
N_GRIDS = 10
COLUMNS = 5
THICKNESS_NS = 5.0
THIN_NS = 1.5
RADIUS_SPACINGS = 1.5
N_WINDOWS = 20


def write_site(folder: Path, size_m: float, samples: int, tpm: float) -> list:
    """Ten adjacent grids of lines along y, as `[(grid, [(path, offset), ...]), ...]`."""
    from nsgeo.geometry.grid import Grid
    from tests.synthetic import write_dzt

    rng = np.random.default_rng(0)
    n_traces = int(round(size_m * tpm))
    data = (rng.normal(size=(samples, n_traces)) * 1e6).astype(np.int32)
    data[40:44, :] = 5_000_000
    n_lines = int(round(size_m / SPACING))
    grids = []
    for g in range(N_GRIDS):
        origin = (500_000.0 + (g % COLUMNS) * size_m, 4_000_000.0 + (g // COLUMNS) * size_m)
        grid = Grid(f"G{g}", origin, 0.0, size_m, size_m, "EPSG:32616", SPACING)
        lines = []
        sub = folder / grid.id
        sub.mkdir(parents=True)
        for i in range(n_lines):
            path = sub / f"FILE__{i + 1:03d}.DZT"
            write_dzt(path, data, traces_per_metre=tpm, range_ns=110.864 * samples / 512)
            lines.append((path, SPACING / 2 + i * SPACING))
        grids.append((grid, lines))
    return grids


def wait(predicate, timeout_s: float) -> None:
    from qgis.PyQt.QtCore import QCoreApplication, QEventLoop

    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("timed out")
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def ms(seconds: float) -> float:
    return seconds * 1000.0


def bench(size_m: float, samples: int, tpm: float, workdir: Path) -> dict:
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo.render import PercentileClip
    from nsgeo.slices import SliceWindow, fill
    from nsgeo_qgis.session import SiteSession
    from nsgeo_qgis.site_engine import SiteEngine
    from nsgeo_qgis.slices_plan import (
        NO_TRANSFORM,
        Resolution,
        SiteSource,
        SourceChoice,
        limit_windows,
        radius_cells_for,
    )

    folder = workdir / f"site_{int(size_m)}m"
    folder.mkdir()
    started = time.perf_counter()
    grids = write_site(folder / "raw", size_m, samples, tpm)
    written_s = time.perf_counter() - started

    session = SiteSession()
    session.new_site(folder)
    lines = []
    for grid, placed in grids:
        session.add_grid(grid)
        for path, offset in placed:
            lines.append(Line.open(path, GridPlacement(grid.id, "y", offset, 0.0, 1, path.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = [dict(s) for s in PRESET]
    by_grid: dict[str, list[str]] = {}
    for line in session.site.lines:
        by_grid.setdefault(line.placement.grid_id, []).append(session.line_key(line))
    source = SiteSource(
        transform=NO_TRANSFORM,
        grids=tuple(
            SourceChoice(grid.id, "p", NO_TRANSFORM, tuple(by_grid[grid.id])) for grid, _ in grids
        ),
    )

    errors: list[str] = []
    site = SiteEngine(session, on_error=errors.append)
    try:
        started = time.perf_counter()
        site.set_source(source)
        wait(lambda: not site.is_running, 3600)
        prep_s = time.perf_counter() - started
        if site.ready_grids != tuple(g.id for g, _ in grids):
            raise RuntimeError(f"not every grid prepared: {errors[:3]}")

        header = session.site.lines[0].header
        cell = min(0.5, SPACING / 2.0)
        res = Resolution(
            cell,
            header.dt_ns,
            header.position_ns,
            header.position_ns + (header.n_samples - 1) * header.dt_ns,
        )
        started = time.perf_counter()
        site.set_resolution(res)
        geometry_s = time.perf_counter() - started
        z = site.site_z
        tops = np.linspace(z.t0_ns, z.t_end_ns - THICKNESS_NS, N_WINDOWS)
        tick = {"radius_spacings": RADIUS_SPACINGS, "manual": {}}

        started = time.perf_counter()
        site.slice_at(float(tops[0]), THICKNESS_NS, method="none", **tick)
        first_s = time.perf_counter() - started

        def timed(method: str) -> list[float]:
            out = []
            for top in tops:
                t = time.perf_counter()
                site.slice_at(float(top), THICKNESS_NS, method=method, **tick)
                out.append(ms(time.perf_counter() - t))
            return out

        plain = timed("none")
        site.slice_at(float(tops[0]), THICKNESS_NS, method="edge", **tick)  # builds the seams
        edge = timed("edge")

        clip = PercentileClip()
        limits = {}
        for thickness in (THICKNESS_NS, THIN_NS):
            t = time.perf_counter()
            site.shared_limit(thickness, clip, method="none", **tick)
            limits[thickness] = ms(time.perf_counter() - t)
        n_limit = {
            th: len(limit_windows(z, max(1, round(th / z.dz_ns)))) for th in (THICKNESS_NS, THIN_NS)
        }

        # M11's baseline: one grid's own engine, slice_at plus fill, same windows.
        engine = site.engine_for(grids[0][0].id)
        radius = radius_cells_for(SPACING, RADIUS_SPACINGS, cell)
        baseline, binning = [], []
        for top in tops:
            window = engine.z.level_range(float(top), THICKNESS_NS)
            t = time.perf_counter()
            values, coverage = engine.slice_at(SliceWindow(*window))
            binned_at = time.perf_counter()
            fill(values, coverage, radius)
            baseline.append(ms(time.perf_counter() - t))
            binning.append(ms(binned_at - t))

        modes = sorted({site.engine_for(g).mode for g in site.ready_grids})
        status = site.status_text()

        # For comparison only: the same ticks with every grid's cube resident
        # (`set_always_resident`, M11 Ruling AN). The first tick builds them.
        for grid_id in site.ready_grids:
            site.engine_for(grid_id).set_always_resident(True)
        t = time.perf_counter()
        site.slice_at(float(tops[0]), THICKNESS_NS, method="none", **tick)
        build_s = time.perf_counter() - t
        resident = timed("none")
        resident_mb = sum(site.engine_for(g).estimate.cube_bytes for g in site.ready_grids) / 1e6
        return {
            "size": size_m,
            "lines": len(lines),
            "traces": int(round(size_m * tpm)),
            "lattice": f"{site.lattice.width} x {site.lattice.height}",
            "status": status,
            "modes": ",".join(modes),
            "written_s": written_s,
            "prep_s": prep_s,
            "geometry_ms": ms(geometry_s),
            "first_ms": ms(first_s),
            "median_ms": statistics.median(plain),
            "p90_ms": float(np.percentile(plain, 90)),
            "edge_median_ms": statistics.median(edge),
            "edge_p90_ms": float(np.percentile(edge, 90)),
            "limit_ms": limits[THICKNESS_NS],
            "limit_windows": n_limit[THICKNESS_NS],
            "limit_thin_ms": limits[THIN_NS],
            "limit_thin_windows": n_limit[THIN_NS],
            "baseline_median_ms": statistics.median(baseline),
            "baseline_p90_ms": float(np.percentile(baseline, 90)),
            "baseline_bin_ms": statistics.median(binning),
            "resident_build_ms": ms(build_s),
            "resident_median_ms": statistics.median(resident),
            "resident_p90_ms": float(np.percentile(resident, 90)),
            "resident_mb": resident_mb,
            "nz": z.nz,
            "errors": len(errors),
        }
    finally:
        site.dispose()
        session.close_site()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--samples", type=int, default=128, help="samples per trace (default 128)")
    ap.add_argument("--tpm", type=float, default=60.0, help="traces per metre (default 60)")
    ap.add_argument("--sizes", type=float, nargs="+", default=[20.0, 50.0])
    ap.add_argument("--workdir", type=Path, default=None, help="where to write the lines")
    args = ap.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication

    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    rows = []
    try:
        with tempfile.TemporaryDirectory(dir=args.workdir) as tmp:
            for size in args.sizes:
                rows.append(bench(size, args.samples, args.tpm, Path(tmp)))
                print(f"done: {size:g} m", file=sys.stderr, flush=True)
    finally:
        app.exitQgis()

    print(
        f"\n{N_GRIDS} grids per site, {SPACING} m line spacing, {args.tpm:g} traces/m, "
        f"{args.samples} samples/trace (time_zero, dewow, gain_agc; transform none); "
        f"cell {min(0.5, SPACING / 2):g} m, native dz, thickness {THICKNESS_NS:g} ns, "
        f"radius {RADIUS_SPACINGS:g} spacings; {N_WINDOWS} windows per timing.\n"
    )
    print(
        "| site | lines | traces/line | lattice | engine mode | prepare site (s) "
        "| first tick (ms) | slice_at median / p90 (ms) | edge median / p90 (ms) "
        "| shared_limit (ms) | one-grid baseline median / p90 (ms) |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {N_GRIDS} x {r['size']:g} m | {r['lines']} | {r['traces']} | {r['lattice']} "
            f"| {r['modes']} | {r['prep_s']:.1f} | {r['first_ms']:.0f} "
            f"| {r['median_ms']:.1f} / {r['p90_ms']:.1f} "
            f"| {r['edge_median_ms']:.1f} / {r['edge_p90_ms']:.1f} "
            f"| {r['limit_ms']:.0f} ({r['limit_windows']} windows at {THICKNESS_NS:g} ns); "
            f"{r['limit_thin_ms']:.0f} ({r['limit_thin_windows']} at {THIN_NS:g} ns) "
            f"| {r['baseline_median_ms']:.1f} / {r['baseline_p90_ms']:.1f} |"
        )
    print()
    for r in rows:
        print(
            f"{N_GRIDS} x {r['size']:g} m: {r['status']}; site axis {r['nz']} levels; "
            f"set_resolution {r['geometry_ms']:.0f} ms; one grid's tick is "
            f"{r['baseline_bin_ms']:.1f} ms binning + "
            f"{r['baseline_median_ms'] - r['baseline_bin_ms']:.1f} ms fill (medians); "
            f"lines written in {r['written_s']:.0f} s; {r['errors']} errors"
        )
        print(
            f"    with every cube resident ({r['resident_mb']:.0f} MB of cubes, built in "
            f"{r['resident_build_ms']:.0f} ms): slice_at median / p90 "
            f"{r['resident_median_ms']:.1f} / {r['resident_p90_ms']:.1f} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
