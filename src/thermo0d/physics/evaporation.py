"""Evaporation source-term models for Thermo0D."""

from __future__ import annotations

import numba as nb
import numpy as np

from thermo0d.config.constants import EvapCol, EvaporationModel
from thermo0d.physics.combustion import wrapped_window_progress
from thermo0d.physics.kinematics import reference_theta_and_zero, wrap_angle_deg

E_MODEL = int(EvapCol.MODEL)
E_START = int(EvapCol.START_DEG)
E_DURATION = int(EvapCol.DURATION_DEG)
E_MASS = int(EvapCol.EVAP_MASS_PER_CYCLE)
E_LATENT = int(EvapCol.LATENT_HEAT)
E_REF = int(EvapCol.REF_TYPE)


@nb.njit(cache=True)
def evaporation_sink_rate(
    theta_local_deg: float,
    theta_global_deg: float,
    dtheta_dt_deg_s: float,
    evap_row: np.ndarray,
    cycle_deg: float,
) -> float:
    if int(evap_row[E_MODEL]) != EvaporationModel.SIMPLE:
        return 0.0
    theta_ref_deg, ref_zero_deg = reference_theta_and_zero(
        theta_local_deg,
        theta_global_deg,
        cycle_deg,
        int(evap_row[E_REF]),
    )
    theta_window_deg = wrap_angle_deg(theta_ref_deg - ref_zero_deg, cycle_deg)
    start_deg = evap_row[E_START]
    duration_deg = evap_row[E_DURATION]
    progress = wrapped_window_progress(theta_window_deg, start_deg, duration_deg, cycle_deg)
    if progress < 0.0:
        return 0.0
    mass_rate_per_deg = evap_row[E_MASS] / duration_deg
    return mass_rate_per_deg * dtheta_dt_deg_s * evap_row[E_LATENT]
