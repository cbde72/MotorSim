"""Combustion source-term models for Thermo0D."""

from __future__ import annotations

import math

import numba as nb
import numpy as np

from thermo0d.config.constants import AngleReference, CombCol, CombustionModel
from thermo0d.physics.kinematics import reference_theta_and_zero, wrap_angle_deg

B_MODEL = int(CombCol.MODEL)
B_START = int(CombCol.START_DEG)
B_DURATION = int(CombCol.DURATION_DEG)
B_A = int(CombCol.A)
B_M = int(CombCol.M)
B_FUEL = int(CombCol.FUEL_MASS_PER_CYCLE)
B_LHV = int(CombCol.LHV)
B_REF = int(CombCol.REF_TYPE)


@nb.njit(cache=True)
def wrapped_window_progress(theta_deg: float, start_deg: float, duration_deg: float, cycle_deg: float) -> float:
    if duration_deg <= 1.0e-18:
        return -1.0
    if duration_deg >= cycle_deg:
        return 0.0
    delta = wrap_angle_deg(theta_deg - start_deg, cycle_deg)
    if delta > duration_deg:
        return -1.0
    return delta / duration_deg


@nb.njit(cache=True)
def vibe_heat_release_rate(
    theta_local_deg: float,
    theta_global_deg: float,
    dtheta_local_dt_deg_s: float,
    dtheta_global_dt_deg_s: float,
    comb_row: np.ndarray,
    cycle_deg: float,
) -> float:
    if int(comb_row[B_MODEL]) != CombustionModel.VIBE:
        return 0.0
    ref_type = int(comb_row[B_REF])
    theta_ref_deg, ref_zero_deg = reference_theta_and_zero(
        theta_local_deg,
        theta_global_deg,
        cycle_deg,
        ref_type,
    )
    theta_window_deg = wrap_angle_deg(theta_ref_deg - ref_zero_deg, cycle_deg)
    start_deg = comb_row[B_START]
    duration_deg = comb_row[B_DURATION]
    progress = wrapped_window_progress(theta_window_deg, start_deg, duration_deg, cycle_deg)
    if progress < 0.0:
        return 0.0
    x = progress
    a = comb_row[B_A]
    m = comb_row[B_M]
    dxb_dx = a * (m + 1.0) * (x ** m) * math.exp(-a * (x ** (m + 1.0)))
    dxb_dtheta = dxb_dx / duration_deg
    q_total = comb_row[B_FUEL] * comb_row[B_LHV]
    dtheta_ref_dt_deg_s = dtheta_global_dt_deg_s if ref_type == AngleReference.ABSOLUTE else dtheta_local_dt_deg_s
    return q_total * dxb_dtheta * dtheta_ref_dt_deg_s
