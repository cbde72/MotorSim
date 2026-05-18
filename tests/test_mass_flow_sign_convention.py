from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from thermo0d.config.constants import (
    ConnCol,
    ConnectionType,
    FeatureCol,
    FlowCoeffMode,
    KinCol,
    KinematicsType,
    SlotOpenMode,
    VolumeCol,
    VolumeType,
)
from thermo0d.output.rows import ResultRowBuilder
from thermo0d.physics.kinematics import cylinder_volume_and_dvdt


def _build_bundle() -> tuple[SimpleNamespace, float]:
    n_vol_cols = max(int(c) for c in VolumeCol) + 1
    n_conn_cols = max(int(c) for c in ConnCol) + 1
    n_kin_cols = max(int(c) for c in KinCol) + 1

    vol_matrix = np.zeros((2, n_vol_cols), dtype=np.float64)
    vol_matrix[0, int(VolumeCol.TYPE)] = VolumeType.PLENUM
    vol_matrix[0, int(VolumeCol.FIXED_VOLUME)] = 1.0e-3
    vol_matrix[1, int(VolumeCol.TYPE)] = VolumeType.CYLINDER
    vol_matrix[1, int(VolumeCol.KIN_ROW)] = 0

    kin_matrix = np.zeros((1, n_kin_cols), dtype=np.float64)
    kin_matrix[0, int(KinCol.TYPE)] = KinematicsType.CRANK_SLIDER
    kin_matrix[0, int(KinCol.BORE)] = 0.086
    kin_matrix[0, int(KinCol.STROKE)] = 0.086
    kin_matrix[0, int(KinCol.CONROD)] = 0.143
    kin_matrix[0, int(KinCol.COMPRESSION_RATIO)] = 10.0
    kin_matrix[0, int(KinCol.PHASE_DEG)] = 0.0
    kin_matrix[0, int(KinCol.SPEED_RPM)] = 60.0
    kin_matrix[0, int(KinCol.CYCLE_DEG)] = 360.0

    conn_matrix = np.zeros((1, n_conn_cols), dtype=np.float64)
    conn_matrix[0, int(ConnCol.TYPE)] = ConnectionType.SLOT
    conn_matrix[0, int(ConnCol.FROM_VOL)] = 0
    conn_matrix[0, int(ConnCol.TO_VOL)] = 1
    conn_matrix[0, int(ConnCol.PRIMARY_DIM)] = 1.0e-3
    conn_matrix[0, int(ConnCol.SECONDARY_DIM)] = 2.0e-2
    conn_matrix[0, int(ConnCol.OPEN_VALUE)] = 0.0
    conn_matrix[0, int(ConnCol.OPEN_MODE)] = SlotOpenMode.BY_DISTANCE
    conn_matrix[0, int(ConnCol.N_HOLES)] = 1.0
    conn_matrix[0, int(ConnCol.CD_MODE)] = FlowCoeffMode.CONSTANT
    conn_matrix[0, int(ConnCol.CD_FORWARD)] = 1.0
    conn_matrix[0, int(ConnCol.CD_REVERSE)] = 1.0

    feature_flags = np.zeros(max(int(c) for c in FeatureCol) + 1, dtype=np.float64)
    feature_flags[int(FeatureCol.MASS_FLOW)] = 1.0

    bundle = SimpleNamespace(
        gas_props=(1004.5, 717.5, 287.0, 1.4),
        vol_matrix=vol_matrix,
        kin_matrix=kin_matrix,
        conn_matrix=conn_matrix,
        lift_table=np.zeros((1, 3), dtype=np.float64),
        alpha_table=np.zeros((1, 3), dtype=np.float64),
        cd_table=np.zeros((1, 3), dtype=np.float64),
        feature_flags=feature_flags,
        volume_names=['plenum', 'cyl'],
        connection_names=['slot'],
        cylinder_indices=[1],
        wall_matrix=np.zeros((0, 6), dtype=np.float64),
        comb_matrix=np.zeros((0, 8), dtype=np.float64),
        evap_matrix=np.zeros((0, 6), dtype=np.float64),
    )

    cyl_volume, _, _ = cylinder_volume_and_dvdt(kin_matrix[0], 0.5)
    return bundle, float(cyl_volume)


def _state_for_pressures(bundle: SimpleNamespace, cyl_volume: float, p_plenum: float, p_cyl: float) -> np.ndarray:
    _cp, cv, gas_constant, _gamma = bundle.gas_props
    temp = 300.0
    plenum_volume = float(bundle.vol_matrix[0, int(VolumeCol.FIXED_VOLUME)])
    m_plenum = p_plenum * plenum_volume / (gas_constant * temp)
    m_cyl = p_cyl * cyl_volume / (gas_constant * temp)
    u_plenum = m_plenum * cv * temp
    u_cyl = m_cyl * cv * temp
    return np.array([[m_plenum], [u_plenum], [m_cyl], [u_cyl]], dtype=np.float64)


def test_positive_connection_mdot_means_from_vol_to_to_vol() -> None:
    bundle, cyl_volume = _build_bundle()
    y = _state_for_pressures(bundle, cyl_volume, p_plenum=2.0e5, p_cyl=1.0e5)
    rows = ResultRowBuilder.build(bundle, np.array([0.5], dtype=np.float64), y, np.array([0], dtype=int))
    row = rows[0]
    assert row['slot_mdot_kg_per_s'] > 0.0
    assert row['cyl_mdot_in_kg_per_s'] > 0.0
    assert row['cyl_mdot_out_kg_per_s'] == 0.0


def test_negative_connection_mdot_means_reverse_flow_and_positive_cylinder_out() -> None:
    bundle, cyl_volume = _build_bundle()
    y = _state_for_pressures(bundle, cyl_volume, p_plenum=1.0e5, p_cyl=2.0e5)
    rows = ResultRowBuilder.build(bundle, np.array([0.5], dtype=np.float64), y, np.array([0], dtype=int))
    row = rows[0]
    assert row['slot_mdot_kg_per_s'] < 0.0
    assert row['cyl_mdot_in_kg_per_s'] == 0.0
    assert row['cyl_mdot_out_kg_per_s'] > 0.0
