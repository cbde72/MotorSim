"""Shared connection opening and effective-area helpers for Thermo0D.

This module keeps valve / slot / orifice opening logic out of ``rhs.py`` so the
same geometry evaluation can be reused consistently by the RHS, CSV export and
post-processing plots without fragile imports from private RHS helpers.
"""

from __future__ import annotations

import numba as nb
import numpy as np

from thermo0d.config.constants import AngleDomain, ConnCol, ConnectionType, FlowCoeffMode
from thermo0d.physics.flow import interpolate_piecewise
from thermo0d.physics.kinematics import reference_theta_and_zero, wrap_angle_deg

C_TYPE = int(ConnCol.TYPE)
C_PRIMARY = int(ConnCol.PRIMARY_DIM)
C_SECONDARY = int(ConnCol.SECONDARY_DIM)
C_OPEN = int(ConnCol.OPEN_VALUE)
C_REF = int(ConnCol.REF_TYPE)
C_ANGLE_DOMAIN = int(ConnCol.ANGLE_DOMAIN)
C_LIFT_SCALE = int(ConnCol.LIFT_SCALE)
C_LASH = int(ConnCol.LASH)
C_N_HOLES = int(ConnCol.N_HOLES)
C_CD_MODE = int(ConnCol.CD_MODE)
C_CD_F = int(ConnCol.CD_FORWARD)
C_CD_R = int(ConnCol.CD_REVERSE)
C_PROFILE_START = int(ConnCol.PROFILE_START)
C_PROFILE_LEN = int(ConnCol.PROFILE_LEN)
C_ALPHA_START = int(ConnCol.ALPHA_START)
C_ALPHA_LEN = int(ConnCol.ALPHA_LEN)
C_CD_TABLE_START = int(ConnCol.CD_TABLE_START)
C_CD_TABLE_LEN = int(ConnCol.CD_TABLE_LEN)
C_REF_FLOW_AREA = int(ConnCol.REF_FLOW_AREA)


@nb.njit(cache=True)
def evaluate_valve_state(
    conn_row: np.ndarray,
    theta_local_deg: float,
    theta_global_deg: float,
    cycle_deg: float,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
) -> tuple[float, float, float, float, float, float]:
    theta_ref_deg, ref_zero_deg = reference_theta_and_zero(
        theta_local_deg,
        theta_global_deg,
        cycle_deg,
        int(conn_row[C_REF]),
    )
    local_crank_deg = wrap_angle_deg(theta_ref_deg - ref_zero_deg - conn_row[C_OPEN], cycle_deg)
    profile_deg = local_crank_deg
    if int(conn_row[C_ANGLE_DOMAIN]) == AngleDomain.CAM:
        cam_ratio = cycle_deg / 360.0
        profile_deg = local_crank_deg / cam_ratio if cam_ratio > 1.0e-18 else local_crank_deg
    p_start = int(conn_row[C_PROFILE_START])
    p_len = int(conn_row[C_PROFILE_LEN])
    raw_lift = interpolate_piecewise(profile_deg, lift_table, p_start, p_len, 0, 1)
    lift = raw_lift * conn_row[C_LIFT_SCALE] - conn_row[C_LASH]
    if lift < 0.0:
        lift = 0.0
    bore_area = conn_row[C_REF_FLOW_AREA]
    a_start = int(conn_row[C_ALPHA_START])
    a_len = int(conn_row[C_ALPHA_LEN])
    alpha_forward = interpolate_piecewise(lift, alpha_table, a_start, a_len, 0, 1)
    alpha_reverse = interpolate_piecewise(lift, alpha_table, a_start, a_len, 0, 2)
    area_forward = alpha_forward * bore_area
    area_reverse = alpha_reverse * bore_area
    return lift, bore_area, area_forward, area_reverse, alpha_forward, alpha_reverse


@nb.njit(cache=True)
def evaluate_valve_area(
    conn_row: np.ndarray,
    theta_local_deg: float,
    theta_global_deg: float,
    cycle_deg: float,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
) -> tuple[float, float, float]:
    _lift, geom_area, area_forward, area_reverse, _alpha_forward, _alpha_reverse = evaluate_valve_state(
        conn_row,
        theta_local_deg,
        theta_global_deg,
        cycle_deg,
        lift_table,
        alpha_table,
    )
    if geom_area <= 1.0e-18:
        return 0.0, 0.0, 0.0
    return geom_area, area_forward / geom_area, area_reverse / geom_area


@nb.njit(cache=True)
def evaluate_slot_state(conn_row: np.ndarray, piston_x_m: float, cd_table: np.ndarray) -> tuple[float, float, float, float, float, float]:
    width = conn_row[C_PRIMARY]
    height = conn_row[C_SECONDARY]
    holes = conn_row[C_N_HOLES]
    open_distance = conn_row[C_OPEN]
    uncovered = piston_x_m - open_distance
    if uncovered < 0.0:
        uncovered = 0.0
    if uncovered > height:
        uncovered = height
    geom_area = width * uncovered * holes
    if int(conn_row[C_CD_MODE]) == FlowCoeffMode.CONSTANT:
        cd_f = conn_row[C_CD_F]
        cd_r = conn_row[C_CD_R]
    else:
        start = int(conn_row[C_CD_TABLE_START])
        length = int(conn_row[C_CD_TABLE_LEN])
        cd_f = interpolate_piecewise(uncovered, cd_table, start, length, 0, 1)
        cd_r = interpolate_piecewise(uncovered, cd_table, start, length, 0, 2)
    area_forward = geom_area * cd_f
    area_reverse = geom_area * cd_r
    return uncovered, geom_area, area_forward, area_reverse, cd_f, cd_r


@nb.njit(cache=True)
def evaluate_slot_area(conn_row: np.ndarray, piston_x_m: float, cd_table: np.ndarray) -> tuple[float, float, float]:
    _uncovered, geom_area, _area_forward, _area_reverse, cd_f, cd_r = evaluate_slot_state(conn_row, piston_x_m, cd_table)
    return geom_area, cd_f, cd_r


@nb.njit(cache=True)
def evaluate_orifice_area(conn_row: np.ndarray) -> tuple[float, float, float]:
    area = max(conn_row[C_PRIMARY], 0.0)
    return area, max(conn_row[C_CD_F], 0.0), max(conn_row[C_CD_R], 0.0)


@nb.njit(cache=True)
def evaluate_check_valve_area(conn_row: np.ndarray, p_from_pa: float, p_to_pa: float) -> tuple[float, float, float]:
    area = max(conn_row[C_PRIMARY], 0.0)
    cd = max(conn_row[C_CD_F], 0.0)
    cracking = max(conn_row[C_OPEN], 0.0)
    if (p_from_pa - p_to_pa) <= cracking:
        return area, 0.0, 0.0
    return area, cd, 0.0


@nb.njit(cache=True)
def connection_area_and_coefficients(
    conn_row: np.ndarray,
    conn_type: int,
    cyl_theta_local_deg: float,
    cyl_theta_global_deg: float,
    cyl_cycle_deg: float,
    cyl_piston_x_m: float,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
    cd_table: np.ndarray,
    p_from_pa: float = 0.0,
    p_to_pa: float = 0.0,
) -> tuple[float, float, float]:
    if conn_type == ConnectionType.VALVE:
        return evaluate_valve_area(conn_row, cyl_theta_local_deg, cyl_theta_global_deg, cyl_cycle_deg, lift_table, alpha_table)
    if conn_type == ConnectionType.SLOT:
        return evaluate_slot_area(conn_row, cyl_piston_x_m, cd_table)
    if conn_type == ConnectionType.ORIFICE:
        return evaluate_orifice_area(conn_row)
    if conn_type == ConnectionType.CHECK_VALVE:
        return evaluate_check_valve_area(conn_row, p_from_pa, p_to_pa)
    return 0.0, 0.0, 0.0


def connection_effective_areas_py(
    conn_row: np.ndarray,
    conn_type: int,
    theta_local_deg: float,
    theta_global_deg: float,
    cycle_deg: float,
    piston_x_m: float,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
    cd_table: np.ndarray,
) -> tuple[float, float]:
    if conn_type == ConnectionType.VALVE:
        _lift, _geom_area, area_forward, area_reverse, _alpha_forward, _alpha_reverse = evaluate_valve_state(
            conn_row,
            float(theta_local_deg),
            float(theta_global_deg),
            float(cycle_deg),
            lift_table,
            alpha_table,
        )
        return float(area_forward), float(area_reverse)
    if conn_type == ConnectionType.SLOT:
        _uncovered, _geom_area, area_forward, area_reverse, _cd_f, _cd_r = evaluate_slot_state(
            conn_row,
            float(piston_x_m),
            cd_table,
        )
        return float(area_forward), float(area_reverse)
    if conn_type == ConnectionType.ORIFICE:
        area, cd_f, cd_r = evaluate_orifice_area(conn_row)
        return float(area * cd_f), float(area * cd_r)
    if conn_type == ConnectionType.CHECK_VALVE:
        area, cd_f, cd_r = evaluate_check_valve_area(conn_row, 0.0, 0.0)
        return float(area * cd_f), float(area * cd_r)
    return 0.0, 0.0
