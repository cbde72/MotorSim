from __future__ import annotations

import numpy as np

from thermo0d.config.constants import (
    AngleDomain,
    AngleReference,
    CombCol,
    ConnCol,
    EvapCol,
    FlowCoeffMode,
)
from thermo0d.physics import rhs as rhs_mod
from thermo0d.physics.combustion import vibe_heat_release_rate
from thermo0d.physics.evaporation import evaporation_sink_rate


def test_safe_temperature_and_pressure_pyfunc():
    assert rhs_mod._safe_temperature.py_func(0.0, 10.0, 700.0) == 300.0
    assert rhs_mod._safe_temperature.py_func(1.0, 0.1, 700.0) == 1.0
    assert rhs_mod._safe_pressure.py_func(1.0, 300.0, 287.0, 0.0) == 1.0e3
    assert rhs_mod._safe_pressure.py_func(1e-9, 1.0, 287.0, 1.0) == 1.0


def test_evaluate_slot_state_constant_and_table_pyfunc():
    conn = np.zeros(len(ConnCol), dtype=float)
    conn[ConnCol.PRIMARY_DIM] = 0.01
    conn[ConnCol.SECONDARY_DIM] = 0.02
    conn[ConnCol.N_HOLES] = 2.0
    conn[ConnCol.OPEN_VALUE] = 0.005
    conn[ConnCol.CD_MODE] = float(FlowCoeffMode.CONSTANT)
    conn[ConnCol.CD_FORWARD] = 0.7
    conn[ConnCol.CD_REVERSE] = 0.5
    cd_table = np.array([[0.0, 0.1, 0.2], [0.02, 0.9, 0.8]], dtype=float)
    uncov, geom, af, ar, cdf, cdr = rhs_mod._evaluate_slot_state.py_func(conn, 0.015, cd_table)
    assert np.isclose(uncov, 0.01)
    assert np.isclose(geom, 0.01 * 0.01 * 2.0)
    assert np.isclose(af, geom * 0.7)
    assert np.isclose(ar, geom * 0.5)
    assert np.isclose(cdf, 0.7) and np.isclose(cdr, 0.5)

    conn[ConnCol.CD_MODE] = float(FlowCoeffMode.TABLE)
    conn[ConnCol.CD_TABLE_START] = 0.0
    conn[ConnCol.CD_TABLE_LEN] = 2.0
    _, geom2, af2, ar2, cdf2, cdr2 = rhs_mod._evaluate_slot_state.py_func(conn, 0.015, cd_table)
    assert np.isclose(geom2, geom)
    assert cdf2 > 0.0 and cdr2 > 0.0
    assert not np.isclose(cdf2, conn[ConnCol.CD_FORWARD])
    assert np.isclose(af2, geom * cdf2)


def test_evaluate_valve_area_and_heat_release_pyfunc():
    conn = np.zeros(len(ConnCol), dtype=float)
    conn[ConnCol.OPEN_VALUE] = 10.0
    conn[ConnCol.REF_TYPE] = float(AngleReference.ABSOLUTE)
    conn[ConnCol.ANGLE_DOMAIN] = float(AngleDomain.CRANK)
    conn[ConnCol.LIFT_SCALE] = 2.0
    conn[ConnCol.LASH] = 0.001
    conn[ConnCol.PROFILE_START] = 0.0
    conn[ConnCol.PROFILE_LEN] = 2.0
    conn[ConnCol.ALPHA_START] = 0.0
    conn[ConnCol.ALPHA_LEN] = 2.0
    conn[ConnCol.REF_FLOW_AREA] = 1.0e-3
    lift_table = np.array([[0.0, 0.0], [20.0, 0.005]], dtype=float)
    alpha_table = np.array([[0.0, 0.0, 0.0], [0.01, 0.2, 0.1]], dtype=float)
    area, cdf, cdr = rhs_mod._evaluate_valve_area.py_func(conn, 20.0, 20.0, 360.0, lift_table, alpha_table)
    assert np.isclose(area, 1.0e-3)
    assert np.isclose(cdf, 0.08)
    assert np.isclose(cdr, 0.04)

    comb = np.zeros(len(CombCol), dtype=float)
    comb[CombCol.MODEL] = 1.0
    comb[CombCol.START_DEG] = 5.0
    comb[CombCol.DURATION_DEG] = 20.0
    comb[CombCol.A] = 5.0
    comb[CombCol.M] = 2.0
    comb[CombCol.FUEL_MASS_PER_CYCLE] = 1.0e-5
    comb[CombCol.LHV] = 4.2e7
    comb[CombCol.REF_TYPE] = float(AngleReference.ABSOLUTE)
    assert vibe_heat_release_rate.py_func(0.0, 0.0, 1000.0, comb, 360.0) == 0.0
    assert vibe_heat_release_rate.py_func(15.0, 15.0, 1000.0, comb, 360.0) > 0.0

    evap = np.zeros(len(EvapCol), dtype=float)
    evap[EvapCol.MODEL] = 1.0
    evap[EvapCol.START_DEG] = 10.0
    evap[EvapCol.DURATION_DEG] = 30.0
    evap[EvapCol.EVAP_MASS_PER_CYCLE] = 2.0e-6
    evap[EvapCol.LATENT_HEAT] = 3.0e5
    evap[EvapCol.REF_TYPE] = float(AngleReference.ABSOLUTE)
    assert evaporation_sink_rate.py_func(0.0, 0.0, 1000.0, evap, 360.0) == 0.0
    assert evaporation_sink_rate.py_func(20.0, 20.0, 1000.0, evap, 360.0) > 0.0


def test_absolute_reference_uses_global_angle_and_wraps_across_cycle():
    comb = np.zeros(len(CombCol), dtype=float)
    comb[CombCol.MODEL] = 1.0
    comb[CombCol.START_DEG] = 350.0
    comb[CombCol.DURATION_DEG] = 30.0
    comb[CombCol.A] = 5.0
    comb[CombCol.M] = 2.0
    comb[CombCol.FUEL_MASS_PER_CYCLE] = 1.0e-5
    comb[CombCol.LHV] = 4.2e7
    comb[CombCol.REF_TYPE] = float(AngleReference.ABSOLUTE)
    assert vibe_heat_release_rate.py_func(175.0, 355.0, 1000.0, comb, 360.0) > 0.0
    assert vibe_heat_release_rate.py_func(190.0, 10.0, 1000.0, comb, 360.0) > 0.0
    assert vibe_heat_release_rate.py_func(220.0, 40.0, 1000.0, comb, 360.0) == 0.0
