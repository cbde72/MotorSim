from __future__ import annotations

from pathlib import Path

import numpy as np

from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.physics.rhs import RHSWrapper


def _bundle(config_rel: str):
    cfg_path = Path(config_rel)
    cfg = ConfigLoader.load(cfg_path)
    return build_model_bundle(cfg, cfg_path)


def test_analytic_flow_jacobian_matches_fd_for_flow_only_case():
    bundle = _bundle('Projekte/config_1cyl_4t.yaml')
    bundle.feature_flags[:] = 0.0
    bundle.feature_flags[0] = 1.0  # mass flow only
    rhs = RHSWrapper(bundle)
    y = bundle.y_init.copy()
    jac_a = rhs.jacobian_flow_analytic(0.0, y)
    jac_fd = rhs.jacobian_fd(0.0, y, eps=1.0e-7)
    assert jac_a.shape == jac_fd.shape
    assert np.isfinite(jac_a).all()
    assert np.allclose(jac_a, jac_fd, rtol=2.0e-3, atol=2.0e-5)


def test_hybrid_jacobian_matches_fd_full_rhs_reasonably():
    bundle = _bundle('Projekte/config_1cyl_4t.yaml')
    rhs = RHSWrapper(bundle)
    y = bundle.y_init.copy()
    jac_h = rhs.jacobian(0.0, y, eps=1.0e-7)
    jac_fd = rhs.jacobian_fd(0.0, y, eps=1.0e-7)
    assert jac_h.shape == jac_fd.shape
    assert np.isfinite(jac_h).all()
    # allow looser tolerance because of branch switching/guards and finite-difference noise
    assert np.allclose(jac_h, jac_fd, rtol=5.0e-2, atol=5.0e-3)
