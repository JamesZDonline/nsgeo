# Multigrid for minimum curvature: spike and agreed description (#111)

2026-11-10. The scripts are in `2026-11-10-multigrid-spike/`. They were throwaway work, kept as the record. `mg2.py` is the reference prototype for the build plan, and `bench.py` produces the timings table in `curvature.py`.

## Why

The user drags the depth slider on their 20 × 16 m Grid 1 at a 0.05 m cell with minimum curvature. While the slider moves they see the kriging preview. When it stops, the sharp minimum-curvature slice takes about 2.5–3.5 s to arrive: a 0.3 s rest, then 2.1–3.1 s of solving. At 0.1 m the same flow felt smooth. They called 0.05 m "usable but not super fun".

## What was agreed in chat (user, 2026-11-10: "that sounds right. make the plan")

- **Goal.** At 0.05 m the sharp slice arrives in well under a second after the depth rests, so 0.05 m feels the way 0.1 m does today. In the issue's terms, 0.05 m should cost about 4× 0.1 m, not 18×.
- **The answer does not change.** It stays within milestone B's recorded tolerance and is pinned to the same dense reference test. The solver stays numpy-only and keeps the Python 3.9 floor.
- **Nothing else changes.** The panel, settings, saved files, the kriging preview, the 0.3 s rest and the 50 ms live-solve budget all stay as they are. Exports, Whole site and M15's cuts get faster without changes of their own. Exports still solve on the GUI thread; moving them off it belongs to #108.
- **Size M.** No design document beyond this note: a written plan of 2–3 tasks, then a walkthrough on Grid 1 at 0.05 m.

## What the spike measured

All on the user's Grid 1 cube at 0.05 m (400 × 320 cells, 13.6% of them holding data, private and not committed). Times are per slice, on 5-level windows.

| | Jacobi CG (today) | Multigrid-preconditioned CG |
|---|---|---|
| 0.05 m, max distance 0.25 m | 2.1–2.3 s, 802–872 iterations | 0.37–0.41 s, 13–15 iterations |
| 0.05 m, max distance 0.375 m | 2.3–3.3 s, 909–1236 iterations | 0.36–0.56 s, 13–21 iterations |
| 0.1 m (0.05 m cells merged 2 × 2) | 0.22–0.27 s, 328–440 iterations | about 0.1 s, 11–14 iterations |
| 0.2 m | 0.03–0.04 s, 144–171 iterations | 0.03 s, 9–10 iterations |
| Largest error inside the max distance vs a float64 solve, 0.05 m | 2.3e-4 / 4.8e-4 of the data range | 1.5e-4 / 2.9e-4 |

- **50 m synthetic grid at 0.05 m** (wandering lines 0.5 m apart): 17–18 s and 537 iterations today, 4.1–4.6 s and 13–14 iterations with multigrid. The cost per cell is about the same as on Grid 1, so multigrid scales with the number of cells.
- **The ten real local lines at 0.05 m:** 15–16 iterations against 524–556 today. The largest error against a float64 solve to 1e-10 was 2.8–3.5e-5 of the range, against 4.1–6.9e-5 today.
- **Crossing lines:** a 10 m grid with three lines along Y as well as X took 6, 10 and 14 iterations at 0.2, 0.1 and 0.05 m, against 39, 152 and 549 today.
- **Setup:** 0.16–0.21 s on Grid 1 for the production-shaped prototype `mg2.py`. The first version needed 0.4–1 s because it probed with dense matrices.
- **Memory:** the hierarchy adds about 0.78× the bytes of the plan's own 13-point coefficients.

## Decisions the spike settled (the coordinator's calls)

1. **Multigrid preconditions the existing conjugate gradients; it does not replace it.** One V-cycle per iteration. The stopping rule, the start, `should_stop` and the float32 arithmetic with float64 dot products all stay. Used on its own as an iteration, the V-cycle contracts the error by only 0.23–0.52 a cycle. Conjugate gradients turns that into about 15 iterations.
2. **Galerkin coarse operators**, `A_c = P'ᵀ A P'`, built by probing. `P'` is cell-centred bilinear prolongation (weights ¾ and ¼ per axis, clamped at the frame edge), masked to the finer level's unknowns. Restriction is its exact transpose. This takes care of the data cells, the irregular solve area and the natural edge conditions without any case analysis. A coarse row reaches 2 coarse cells, so every level after the first is a 25-point stencil and 25 probes (colours 5 apart) recover it exactly. Coarse cells that reach no finer unknown drop out.
3. **The smoother is l1-Jacobi Chebyshev, degree 2, on the interval [1/16, 1].** Each row is scaled by 1 / its absolute sum, so every eigenvalue of the scaled operator is at most 1 by construction. No eigenvalue estimate is needed, and the V-cycle is guaranteed symmetric positive definite. A global Gershgorin bound was safe but loose on coarse levels (16–40 against a true 2–4) and needed about 70% more iterations. Power iteration matched l1 but is only an estimate.
4. **The coarsest level is solved directly** with a dense pseudo-inverse (`eigh`, eigenvalues above 1e-6 of the largest) once it has at most 500 unknowns.
5. **Cubic prolongation was dropped.** It diverged in the spike, most likely because its wider coarse stencil was probed with too short a period. Bilinear needs no more.
6. **Scratch arrays are allocated per call.** The first prototype shared padding buffers between calls, which would race between the refine worker and the GUI thread.
