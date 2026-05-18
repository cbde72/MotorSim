from pathlib import Path

import numpy as np

from thermo0d.config.models import load_config
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.physics.rhs import RHSWrapper


def test_parser_and_rhs_shape():
    cfg_path = Path('Projekte/config_1cyl_4t.yaml')
    cfg = load_config(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    rhs = RHSWrapper(bundle)
    dy = rhs(0.0, bundle.y_init.copy())
    assert dy.shape == bundle.y_init.shape
    assert np.all(np.isfinite(dy))
    assert bundle.conn_matrix.shape[0] == 2


def test_valve_effective_area_uses_alpha_k_times_bore_area_and_cam_basis():
    from thermo0d.physics.rhs import _evaluate_valve_state
    from thermo0d.config.constants import ConnCol, AngleDomain, AngleReference

    conn = np.zeros(len(ConnCol), dtype=np.float64)
    conn[ConnCol.OPEN_VALUE] = 0.0
    conn[ConnCol.REF_TYPE] = float(AngleReference.ABSOLUTE)
    conn[ConnCol.ANGLE_DOMAIN] = float(AngleDomain.CAM)
    conn[ConnCol.LIFT_SCALE] = 1.0
    conn[ConnCol.LASH] = 0.0
    conn[ConnCol.PROFILE_START] = 0.0
    conn[ConnCol.PROFILE_LEN] = 2.0
    conn[ConnCol.ALPHA_START] = 0.0
    conn[ConnCol.ALPHA_LEN] = 2.0
    conn[ConnCol.REF_FLOW_AREA] = 1.0e-3

    lift_table = np.array([[0.0, 0.0], [180.0, 0.01]], dtype=np.float64)
    alpha_table = np.array([[0.0, 0.0, 0.0], [0.01, 0.2, 0.1]], dtype=np.float64)

    lift, geom_area, area_f, area_r, alpha_k_f, alpha_k_r = _evaluate_valve_state(conn, 360.0, 360.0, 720.0, lift_table, alpha_table)

    assert np.isclose(lift, 0.01)
    assert np.isclose(alpha_k_f, 0.2)
    assert np.isclose(area_f, 0.2 * conn[ConnCol.REF_FLOW_AREA])
    assert np.isclose(alpha_k_r, 0.1)
    assert np.isclose(area_r, 0.1 * conn[ConnCol.REF_FLOW_AREA])
    assert np.isclose(geom_area, conn[ConnCol.REF_FLOW_AREA])
