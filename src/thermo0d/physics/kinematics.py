"""Kinematic relations for cylinder motion and time-angle conversion.

These helpers convert simulation time to crank-angle state, piston travel,
instantaneous cylinder volume and dV/dt for crank-slider cylinders. The code is
kept Numba-compatible because it is called directly from the RHS and the
analytic flow Jacobian.
"""

from __future__ import annotations

import math

import numba as nb
import numpy as np

from thermo0d.config.constants import AngleReference, KinCol

KIN_TYPE = int(KinCol.TYPE)
KIN_BORE = int(KinCol.BORE)
KIN_STROKE = int(KinCol.STROKE)
KIN_CONROD = int(KinCol.CONROD)
KIN_CR = int(KinCol.COMPRESSION_RATIO)
KIN_PHASE = int(KinCol.PHASE_DEG)
KIN_SPEED = int(KinCol.SPEED_RPM)
KIN_CYCLE = int(KinCol.CYCLE_DEG)
REF_ABSOLUTE = int(AngleReference.ABSOLUTE)
REF_COMPRESSION_TDC = int(AngleReference.COMPRESSION_TDC)
REF_GAS_EXCHANGE_TDC = int(AngleReference.GAS_EXCHANGE_TDC)


@nb.njit(cache=True)
def wrap_angle_deg(angle_deg: float, cycle_deg: float) -> float:
    out = angle_deg % cycle_deg
    if out < 0.0:
        out += cycle_deg
    return out


@nb.njit(cache=True)
def reference_zero_deg(cycle_deg: float, ref_type: int) -> float:
    if ref_type == REF_ABSOLUTE:
        return 0.0
    if ref_type == REF_COMPRESSION_TDC:
        return 0.0
    if ref_type == REF_GAS_EXCHANGE_TDC:
        if cycle_deg >= 719.0:
            return 360.0
        return 0.0
    return 0.0


@nb.njit(cache=True)
def theta_and_rate_from_time(t: float, kin_row: np.ndarray) -> tuple[float, float, float]:
    speed_rpm = kin_row[KIN_SPEED]
    cycle_deg = kin_row[KIN_CYCLE]
    phase_deg = kin_row[KIN_PHASE]
    dtheta_dt_deg_s = 6.0 * speed_rpm
    theta_abs_deg = phase_deg + dtheta_dt_deg_s * t
    theta_cycle_deg = wrap_angle_deg(theta_abs_deg, cycle_deg)
    return theta_cycle_deg, dtheta_dt_deg_s, cycle_deg


@nb.njit(cache=True)
def global_theta_and_rate_from_time(t: float, kin_row: np.ndarray) -> tuple[float, float, float]:
    speed_rpm = kin_row[KIN_SPEED]
    cycle_deg = kin_row[KIN_CYCLE]
    dtheta_dt_deg_s = 6.0 * speed_rpm
    theta_abs_deg = dtheta_dt_deg_s * t
    theta_cycle_deg = wrap_angle_deg(theta_abs_deg, cycle_deg)
    return theta_cycle_deg, dtheta_dt_deg_s, cycle_deg


@nb.njit(cache=True)
def reference_theta_and_zero(
    theta_local_deg: float,
    theta_global_deg: float,
    cycle_deg: float,
    ref_type: int,
) -> tuple[float, float]:
    if ref_type == REF_ABSOLUTE:
        return theta_global_deg, 0.0
    return theta_local_deg, reference_zero_deg(cycle_deg, ref_type)


@nb.njit(cache=True)
def piston_displacement_from_tdc(kin_row: np.ndarray, theta_deg: float) -> float:
    r = 0.5 * kin_row[KIN_STROKE]
    l = kin_row[KIN_CONROD]
    theta = math.radians(theta_deg)
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)
    under = l * l - (r * sin_t) * (r * sin_t)
    if under <= 1.0e-18:
        under = 1.0e-18
    return r * (1.0 - cos_t) + l - math.sqrt(under)


@nb.njit(cache=True)
def cylinder_kinematic_state_with_global_from_time(
    kin_row: np.ndarray,
    t: float,
) -> tuple[float, float, float, float, float, float, float]:
    """Return full crank-slider state including local and global angle.

    Output order:
        volume_m3, dvdt_m3_per_s, theta_local_deg, theta_global_deg,
        piston_x_m, dtheta_dt_deg_per_s, cycle_deg
    """
    bore = kin_row[KIN_BORE]
    stroke = kin_row[KIN_STROKE]
    conrod = kin_row[KIN_CONROD]
    cr = kin_row[KIN_CR]

    theta_global_deg, dtheta_dt_deg_s, cycle_deg = global_theta_and_rate_from_time(t, kin_row)
    phase_deg = kin_row[KIN_PHASE]
    theta_local_deg = wrap_angle_deg(theta_global_deg + phase_deg, cycle_deg)

    area = 0.25 * math.pi * bore * bore
    r = 0.5 * stroke
    theta = math.radians(theta_local_deg)
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)

    under = conrod * conrod - (r * sin_t) * (r * sin_t)
    if under <= 1.0e-18:
        under = 1.0e-18
    sqrt_under = math.sqrt(under)

    piston_x_m = r * (1.0 - cos_t) + conrod - sqrt_under
    swept_volume = area * stroke
    clearance_volume = swept_volume / (cr - 1.0)
    volume = clearance_volume + area * piston_x_m

    dx_dtheta_rad = r * sin_t + (r * r * sin_t * cos_t) / sqrt_under
    dtheta_dt_rad_s = math.radians(dtheta_dt_deg_s)
    dvdt = area * dx_dtheta_rad * dtheta_dt_rad_s
    return volume, dvdt, theta_local_deg, theta_global_deg, piston_x_m, dtheta_dt_deg_s, cycle_deg


@nb.njit(cache=True)
def cylinder_kinematic_state_from_time(kin_row: np.ndarray, t: float) -> tuple[float, float, float, float, float, float]:
    """Return all hot-path crank-slider quantities for one cylinder.

    Output order:
        volume_m3, dvdt_m3_per_s, theta_cycle_deg, piston_x_m,
        dtheta_dt_deg_per_s, cycle_deg
    """
    volume, dvdt, theta_local_deg, _theta_global_deg, piston_x_m, dtheta_dt_deg_s, cycle_deg = cylinder_kinematic_state_with_global_from_time(kin_row, t)
    return volume, dvdt, theta_local_deg, piston_x_m, dtheta_dt_deg_s, cycle_deg


@nb.njit(cache=True)
def cylinder_volume_and_dvdt(kin_row: np.ndarray, t: float) -> tuple[float, float, float]:
    """Return cylinder volume, dV/dt and cycle angle for a crank-slider model."""
    volume, dvdt, theta_deg, _piston_x_m, _dtheta_dt_deg_s, _cycle_deg = cylinder_kinematic_state_from_time(kin_row, t)
    return volume, dvdt, theta_deg
