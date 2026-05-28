"""Jacobian utilities for topology-based sparsity and finite differences.

The helper functions in this module are deliberately solver-agnostic. They map
network topology to a conservative sparsity pattern, derive column color groups
for compressed finite differencing and provide a generic numerical Jacobian used
for diagnostics and hybrid Jacobian strategies.
"""

from __future__ import annotations

import numpy as np
from scipy import sparse

from thermo0d.config.constants import ConnCol, FeatureCol


STATES_PER_VOLUME = 5


def build_rhs_jacobian_sparsity(
    n_volumes: int,
    conn_matrix: np.ndarray,
    feature_flags: np.ndarray,
    *,
    extra_state_count: int = 0,
    dense_extra_coupling: bool = False,
) -> sparse.csr_matrix:
    """Build a conservative structural sparsity pattern for the current RHS.

    Per volume the solver carries five thermodynamic states:
    gas mass, internal energy, burned gas tracer mass, air mass and liquid fuel mass.
    """
    n_vol = int(n_volumes)
    n_state = STATES_PER_VOLUME * n_vol + int(extra_state_count)
    pattern = np.zeros((n_state, n_state), dtype=np.uint8)

    def vol_rows(i: int) -> tuple[int, int, int, int, int]:
        base = STATES_PER_VOLUME * int(i)
        return (base, base + 1, base + 2, base + 3, base + 4)

    for i in range(n_vol):
        rows = vol_rows(i)
        for r in rows:
            for c in rows:
                pattern[r, c] = 1

    if feature_flags.size > int(FeatureCol.MASS_FLOW) and int(feature_flags[int(FeatureCol.MASS_FLOW)]) == 1:
        for j in range(conn_matrix.shape[0]):
            left = int(conn_matrix[j, int(ConnCol.FROM_VOL)])
            right = int(conn_matrix[j, int(ConnCol.TO_VOL)])
            rows = vol_rows(left) + vol_rows(right)
            for r in rows:
                for c in rows:
                    pattern[r, c] = 1

    if extra_state_count > 0:
        start = STATES_PER_VOLUME * n_vol
        for idx in range(start, n_state):
            pattern[idx, idx] = 1
        if dense_extra_coupling:
            pattern[start:n_state, :] = 1
            pattern[:, start:n_state] = 1

    return sparse.csr_matrix(pattern)


def build_column_interference_graph(sparsity: sparse.csr_matrix | np.ndarray) -> list[set[int]]:
    """Return a graph where columns sharing at least one active row interfere."""
    if not sparse.issparse(sparsity):
        sparsity = sparse.csr_matrix(np.asarray(sparsity))
    csc = sparsity.tocsc()
    n_cols = csc.shape[1]
    rows_to_cols: dict[int, list[int]] = {}
    for col in range(n_cols):
        start, end = csc.indptr[col], csc.indptr[col + 1]
        for row in csc.indices[start:end]:
            rows_to_cols.setdefault(int(row), []).append(col)

    graph: list[set[int]] = [set() for _ in range(n_cols)]
    for cols in rows_to_cols.values():
        for i, c1 in enumerate(cols):
            for c2 in cols[i + 1:]:
                graph[c1].add(c2)
                graph[c2].add(c1)
    return graph


def greedy_color_columns(sparsity: sparse.csr_matrix | np.ndarray) -> list[list[int]]:
    """Greedy graph coloring for Jacobian compression from a sparsity pattern."""
    graph = build_column_interference_graph(sparsity)
    order = sorted(range(len(graph)), key=lambda idx: len(graph[idx]), reverse=True)
    colors = [-1] * len(graph)
    for col in order:
        used = {colors[nbr] for nbr in graph[col] if colors[nbr] >= 0}
        color = 0
        while color in used:
            color += 1
        colors[col] = color
    n_colors = max(colors, default=-1) + 1
    groups = [[] for _ in range(n_colors)]
    for col, color in enumerate(colors):
        if color >= 0:
            groups[color].append(col)
    return groups


def finite_difference_jacobian(rhs, t: float, y: np.ndarray, eps: float = 1.0e-8, sparsity: sparse.csr_matrix | None = None) -> np.ndarray:
    """Numerical Jacobian for diagnostics, profiling and solver experiments.

    If a sparsity pattern is supplied, independent columns are grouped and
    perturbed simultaneously to reduce RHS calls.
    """
    y = np.asarray(y, dtype=np.float64)
    f0 = np.asarray(rhs(t, y), dtype=np.float64)
    n = y.size
    jac = np.zeros((n, n), dtype=np.float64)

    if sparsity is None or sparsity.shape != (n, n):
        groups = [[j] for j in range(n)]
        active_rows_by_col = None
    else:
        if not sparse.issparse(sparsity):
            sparsity = sparse.csr_matrix(np.asarray(sparsity))
        groups = greedy_color_columns(sparsity)
        csc = sparsity.tocsc()
        active_rows_by_col = []
        for col in range(n):
            start, end = csc.indptr[col], csc.indptr[col + 1]
            active_rows_by_col.append(csc.indices[start:end])

    for group in groups:
        if not group:
            continue
        y_pert = y.copy()
        steps = {}
        for j in group:
            step = eps * max(1.0, abs(y[j]))
            y_pert[j] += step
            steps[j] = step
        fg = np.asarray(rhs(t, y_pert), dtype=np.float64)
        delta = fg - f0
        for j in group:
            if active_rows_by_col is None:
                jac[:, j] = delta / steps[j]
            else:
                rows = active_rows_by_col[j]
                jac[rows, j] = delta[rows] / steps[j]
    return jac
