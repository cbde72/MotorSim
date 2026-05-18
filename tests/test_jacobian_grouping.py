from __future__ import annotations

import numpy as np

from thermo0d.compute.jacobian import build_rhs_jacobian_sparsity, finite_difference_jacobian, greedy_color_columns


def test_greedy_color_columns_returns_nonempty_groups():
    conn = np.array([[0, 0, 1] + [0]*14], dtype=np.float64)
    feature_flags = np.array([1, 0, 0, 0, 0], dtype=np.int64)
    sparsity = build_rhs_jacobian_sparsity(2, conn, feature_flags)
    groups = greedy_color_columns(sparsity)
    assert groups
    cols = sorted(c for g in groups for c in g)
    assert cols == [0, 1, 2, 3]


def test_grouped_fd_matches_dense_fd_for_linear_system():
    a = np.array([[2.0, 0.0, 3.0], [0.0, -1.0, 0.0], [4.0, 0.0, 5.0]], dtype=np.float64)
    def rhs(_t, y):
        return a @ y
    y = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    sparsity = np.array([[1, 0, 1], [0, 1, 0], [1, 0, 1]], dtype=np.uint8)
    jac = finite_difference_jacobian(rhs, 0.0, y, eps=1e-8, sparsity=sparsity)
    assert np.allclose(jac, a, atol=1e-6)
