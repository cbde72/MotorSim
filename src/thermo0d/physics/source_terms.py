"""Shared local energy source-term evaluators for Thermo0D."""

from __future__ import annotations

import numba as nb
import numpy as np

from thermo0d.config.constants import FeatureCol, VolumeCol, VolumeType
from thermo0d.physics.combustion import _vibe_heat_release_rate_impl
from thermo0d.physics.evaporation import evaporation_sink_rate
from thermo0d.physics.heat_transfer import wall_heat_context_for_volume, wall_heat_rate_and_coeff_from_row_numba

V_TYPE = int(VolumeCol.TYPE)
V_WALL = int(VolumeCol.WALL_ROW)
V_COMB = int(VolumeCol.COMB_ROW)
V_EVAP = int(VolumeCol.EVAP_ROW)
F_WALL = int(FeatureCol.WALL_HEAT)
F_COMB = int(FeatureCol.COMBUSTION)
F_EVAP = int(FeatureCol.EVAPORATION)
F_PV = int(FeatureCol.PV_WORK)
VOL_CYLINDER = int(VolumeType.CYLINDER)


@nb.njit(cache=True)
def volume_energy_source_terms(vol_type: int, wall_idx: int, comb_idx: int, evap_idx: int, wall_enabled: int, comb_enabled: int, evap_enabled: int, pv_enabled: int, wall_matrix: np.ndarray, comb_matrix: np.ndarray, evap_matrix: np.ndarray, wall_bore_m: float, wall_mean_piston_speed_m_s: float, pressure_pa: float, gas_temp_K: float, volume_m3: float, cylinder_mass_kg: float, mdot_in_kg_per_s: float, dvdt_m3_per_s: float, theta_local_deg: float, theta_global_deg: float, dtheta_local_dt_deg_s: float, dtheta_global_dt_deg_s: float, cycle_deg: float) -> tuple[float, float, float, float, float, float]:
    pdv_power = pressure_pa * dvdt_m3_per_s if pv_enabled == 1 else 0.0
    qdot_wall = 0.0
    htc_wall = 0.0
    wall_velocity = 0.0
    qdot_comb = 0.0
    qdot_evap = 0.0
    if wall_enabled == 1 and wall_idx >= 0:
        qdot_wall, htc_wall, wall_velocity, _dp = wall_heat_rate_and_coeff_from_row_numba(wall_matrix[wall_idx], wall_bore_m, pressure_pa, gas_temp_K, wall_mean_piston_speed_m_s, volume_m3, theta_local_deg, cycle_deg, cylinder_mass_kg, mdot_in_kg_per_s)
    if vol_type == VOL_CYLINDER:
        if comb_enabled == 1 and comb_idx >= 0:
            qdot_comb = _vibe_heat_release_rate_impl(theta_local_deg, theta_global_deg, dtheta_local_dt_deg_s, dtheta_global_dt_deg_s, comb_matrix[comb_idx], cycle_deg)
        if evap_enabled == 1 and evap_idx >= 0:
            qdot_evap = evaporation_sink_rate(theta_local_deg, theta_global_deg, dtheta_local_dt_deg_s, evap_matrix[evap_idx], cycle_deg)
    return pdv_power, qdot_wall, htc_wall, wall_velocity, qdot_comb, qdot_evap


@nb.njit(cache=True)
def cylinder_energy_source_terms_from_context(vol_row: np.ndarray, wall_matrix: np.ndarray, comb_matrix: np.ndarray, evap_matrix: np.ndarray, feature_flags: np.ndarray, wall_bore_m: float, wall_mean_piston_speed_m_s: float, pressure_pa: float, gas_temp_K: float, volume_m3: float, cylinder_mass_kg: float, mdot_in_kg_per_s: float, dvdt_m3_per_s: float, theta_local_deg: float, theta_global_deg: float, dtheta_local_dt_deg_s: float, dtheta_global_dt_deg_s: float, cycle_deg: float) -> tuple[float, float, float, float, float, float]:
    return volume_energy_source_terms(int(vol_row[V_TYPE]), int(vol_row[V_WALL]), int(vol_row[V_COMB]), int(vol_row[V_EVAP]), 1 if feature_flags[F_WALL] == 1 else 0, 1 if feature_flags[F_COMB] == 1 else 0, 1 if feature_flags[F_EVAP] == 1 else 0, 1 if feature_flags[F_PV] == 1 else 0, wall_matrix, comb_matrix, evap_matrix, wall_bore_m, wall_mean_piston_speed_m_s, pressure_pa, gas_temp_K, volume_m3, cylinder_mass_kg, mdot_in_kg_per_s, dvdt_m3_per_s, theta_local_deg, theta_global_deg, dtheta_local_dt_deg_s, dtheta_global_dt_deg_s, cycle_deg)


@nb.njit(cache=True)
def cylinder_energy_source_terms(vol_row: np.ndarray, kin_matrix: np.ndarray, wall_matrix: np.ndarray, comb_matrix: np.ndarray, evap_matrix: np.ndarray, feature_flags: np.ndarray, pressure_pa: float, gas_temp_K: float, volume_m3: float, cylinder_mass_kg: float, mdot_in_kg_per_s: float, dvdt_m3_per_s: float, theta_local_deg: float, theta_global_deg: float, dtheta_local_dt_deg_s: float, dtheta_global_dt_deg_s: float, cycle_deg: float) -> tuple[float, float, float, float, float, float]:
    wall_bore_m, wall_mean_piston_speed_m_s = wall_heat_context_for_volume(vol_row, kin_matrix)
    return cylinder_energy_source_terms_from_context(vol_row, wall_matrix, comb_matrix, evap_matrix, feature_flags, wall_bore_m, wall_mean_piston_speed_m_s, pressure_pa, gas_temp_K, volume_m3, cylinder_mass_kg, mdot_in_kg_per_s, dvdt_m3_per_s, theta_local_deg, theta_global_deg, dtheta_local_dt_deg_s, dtheta_global_dt_deg_s, cycle_deg)
