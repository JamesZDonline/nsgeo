import sys, time, threading
import numpy as np
sys.path.insert(0, sys.argv[1])
import mg2
from check2 import solve, hier
from nsgeo.slices.curvature import plan_curvature


def crossing(cell):
    n = int(round(10 / cell))
    pop = np.zeros((n, n), bool)
    x = (np.arange(n) + 0.5) * cell
    for i, y0 in enumerate(np.arange(0.25, 10, 0.5)):
        y = y0 + 0.06 * np.sin(x / 3.0 + i)
        pop[np.clip((y / cell).astype(int), 0, n - 1), np.arange(n)] = True
    for x0 in (2.1, 5.3, 8.6):
        pop[:, int(x0 / cell)] = True
    return pop


for cell in (0.2, 0.1, 0.05):
    pop = crossing(cell)
    Y, X = (np.indices(pop.shape) + 0.5) * cell
    v = np.sin(X / 1.7) * np.cos(Y / 2.3) + 0.3 * np.sin(3.1 * X + 1.3 * Y)
    plan = plan_curvature(pop, cell, 0.375)
    H = hier(plan)
    print(cell, "mg its", solve(plan, H, v)[1], "today", plan.solve(v)[1])
# memory ratio at 400x400 lines
pop = np.zeros((400, 400), bool); pop[5::10] = True
plan = plan_curvature(pop, 0.05, 0.375); H = hier(plan)
nb = sum(a.nbytes for L in H.levels for a in (L.active, L.scale if hasattr(L, "scale") else L.inverse_diagonal)) + sum(L.coefficients.nbytes for L in H.levels[1:]) + H.coarse_inverse.nbytes + H.coarse_cells.nbytes
print("hierarchy bytes / plan coefficients bytes", nb / plan.coefficients.nbytes)
