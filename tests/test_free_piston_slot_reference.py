from __future__ import annotations

import numpy as np

from thermo0d.config.constants import ConnCol, FlowCoeffMode
from thermo0d.model.free_piston.geometry import cylinder_distance_from_tdc
from thermo0d.physics.openings import evaluate_slot_state
from thermo0d.physics import rhs as rhs_mod


def _slot_row() -> np.ndarray:
    conn = np.zeros(len(ConnCol), dtype=float)
    conn[ConnCol.PRIMARY_DIM] = 0.02
    conn[ConnCol.SECONDARY_DIM] = 0.012
    conn[ConnCol.N_HOLES] = 2.0
    conn[ConnCol.OPEN_VALUE] = 0.010
    conn[ConnCol.CD_MODE] = float(FlowCoeffMode.CONSTANT)
    conn[ConnCol.CD_FORWARD] = 0.82
    conn[ConnCol.CD_REVERSE] = 0.68
    return conn


def test_free_piston_distance_from_tdc_uses_x_max_as_tdc_reference() -> None:
    assert np.isclose(cylinder_distance_from_tdc(0.04, 0.04), 0.0)
    assert np.isclose(cylinder_distance_from_tdc(0.02, 0.04), 0.02)
    assert np.isclose(cylinder_distance_from_tdc(-0.01, 0.04), 0.05)


def test_slot_opening_with_free_piston_coordinate_uses_distance_from_tdc() -> None:
    conn = _slot_row()
    cd_table = np.zeros((0, 3), dtype=float)
    free_piston_x_m = -0.01
    distance_from_tdc_m = cylinder_distance_from_tdc(free_piston_x_m, 0.04)

    uncov, geom, af, ar, cdf, cdr = evaluate_slot_state.py_func(conn, distance_from_tdc_m, cd_table)

    assert np.isclose(uncov, 0.012)
    assert np.isclose(geom, 0.02 * 0.012 * 2.0)
    assert np.isclose(af, geom * 0.82)
    assert np.isclose(ar, geom * 0.68)
    assert np.isclose(cdf, 0.82)
    assert np.isclose(cdr, 0.68)


def test_classic_slot_reference_helper_behavior_is_unchanged() -> None:
    conn = _slot_row()
    cd_table = np.zeros((0, 3), dtype=float)
    uncov, geom, af, ar, cdf, cdr = rhs_mod._evaluate_slot_state.py_func(conn, 0.015, cd_table)
    assert np.isclose(uncov, 0.005)
    assert np.isclose(geom, 0.02 * 0.005 * 2.0)
    assert np.isclose(af, geom * 0.82)
    assert np.isclose(ar, geom * 0.68)
    assert np.isclose(cdf, 0.82)
    assert np.isclose(cdr, 0.68)
