from __future__ import annotations

from pathlib import Path

import numpy as np

from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import MatrixModelBuilder
from thermo0d.compute.jacobian import build_rhs_jacobian_sparsity, finite_difference_jacobian
from thermo0d.compute.solvers import SolverFactory
from thermo0d.physics.rhs import RHSWrapper


def _bundle(config_rel: str):
    cfg_path = Path(config_rel)
    cfg = ConfigLoader.load(cfg_path)
    return MatrixModelBuilder(cfg, cfg_path).build()


def test_build_rhs_jacobian_sparsity_has_expected_shape_and_diagonal():
    bundle = _bundle('Projekte/config_1cyl_4t.yaml')
    jac = build_rhs_jacobian_sparsity(bundle.vol_matrix.shape[0], bundle.conn_matrix, bundle.feature_flags)
    dense = jac.toarray()
    n = bundle.y_init.size
    assert dense.shape == (n, n)
    assert np.all(np.diag(dense) == 1)


def test_connection_coupling_marks_both_connected_volumes():
    bundle = _bundle('Projekte/config_1cyl_4t.yaml')
    jac = bundle.jac_sparsity.toarray()
    rows = [0, 1, 2, 3]
    cols = [0, 1, 2, 3]
    for r in rows:
        for c in cols:
            assert jac[r, c] == 1


def test_solver_factory_remains_backward_compatible():
    names = SolverFactory.registered_names()
    assert 'euler' in names
    assert 'rk4' in names
    assert 'scipy_rk45' in names


def test_rhs_wrapper_exposes_numerical_jacobian():
    bundle = _bundle('Projekte/config_1cyl_4t.yaml')
    rhs = RHSWrapper(bundle)
    jac = rhs.jacobian_fd(0.0, bundle.y_init.copy(), eps=1.0e-8)
    assert jac.shape == (bundle.y_init.size, bundle.y_init.size)
    assert np.isfinite(jac).all()


def test_finite_difference_jacobian_respects_shape_for_simple_rhs():
    def simple_rhs(_t, y):
        return np.array([2.0 * y[0], y[0] - 3.0 * y[1]], dtype=np.float64)

    y = np.array([1.0, 2.0], dtype=np.float64)
    jac = finite_difference_jacobian(simple_rhs, 0.0, y)
    assert jac.shape == (2, 2)
    assert np.allclose(jac, np.array([[2.0, 0.0], [1.0, -3.0]]), atol=1.0e-5)
