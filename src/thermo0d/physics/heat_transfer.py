"""Heat-transfer helper models for Thermo0D."""

from __future__ import annotations

import numba as nb
import numpy as np

from thermo0d.config.constants import HeatTransferModel, VolumeCol, VolumeType, WallCol, WoschniDpMode, WoschniVariant

V_TYPE = int(VolumeCol.TYPE)
V_KIN_ROW = int(VolumeCol.KIN_ROW)
W_MODEL = int(WallCol.MODEL)
W_C1 = int(WallCol.C1)
W_C2 = int(WallCol.C2)
W_C3 = int(WallCol.C3)
W_TEMP = int(WallCol.WALL_TEMP)
W_AREA = int(WallCol.WALL_AREA)
W_VARIANT = int(WallCol.VARIANT)
W_DP_MODE = int(WallCol.DP_MODE)
W_MULT = int(WallCol.MULTIPLIER)
W_CUCM = int(WallCol.CUCM)
W_SWIRL = int(WallCol.SWIRL_NUMBER)
W_IMEP = int(WallCol.IMEP_BAR)
W_VCLR = int(WallCol.CLEARANCE_VOL)
W_VMAX = int(WallCol.MAX_VOL)

_DEFAULT_NONCYL_BORE_M = 0.1
_TINY = 1.0e-18
HT_WOSCHNI = int(HeatTransferModel.WOSCHNI)
WV_LEGACY = int(WoschniVariant.LEGACY)
WV_PROMO = int(WoschniVariant.PROMO)
WV_GT = int(WoschniVariant.GT)
WV_CLASSIC = int(WoschniVariant.CLASSIC)
WV_SWIRL = int(WoschniVariant.SWIRL)
WV_HUBER = int(WoschniVariant.HUBER)
WDP_OFF = int(WoschniDpMode.OFF)


@nb.njit(cache=True)
def wall_heat_context_for_volume(vol_row: np.ndarray, kin_matrix: np.ndarray) -> tuple[float, float]:
    if int(vol_row[V_TYPE]) == VolumeType.CYLINDER:
        kin_idx = int(vol_row[V_KIN_ROW])
        return kin_matrix[kin_idx, 1], 2.0 * kin_matrix[kin_idx, 2] * kin_matrix[kin_idx, 6] / 60.0
    return _DEFAULT_NONCYL_BORE_M, 0.0


@nb.njit(cache=True)
def _theta_mod(theta_local_deg: float, cycle_deg: float) -> float:
    out = theta_local_deg % cycle_deg
    if out < 0.0:
        out += cycle_deg
    return out


@nb.njit(cache=True)
def _phase_bucket(theta_local_deg: float, cycle_deg: float) -> int:
    th = _theta_mod(theta_local_deg, cycle_deg)
    if cycle_deg >= 719.0:
        if th < 180.0:
            return 2
        if th < 540.0:
            return 0
        return 1
    return 2 if th < 180.0 else 0


@nb.njit(cache=True)
def _legacy_htc(c1: float, c2: float, c3: float, bore_m: float, pressure_pa: float, gas_temp_K: float, mean_piston_speed_m_s: float) -> float:
    if bore_m <= _TINY or pressure_pa <= 0.0 or gas_temp_K <= 0.0:
        return 0.0
    return c1 * (bore_m ** (-0.2)) * (pressure_pa ** c2) * (gas_temp_K ** c3) * (1.0 + mean_piston_speed_m_s)


@nb.njit(cache=True)
def _promo_phase_c1(phase: int, cucm: float) -> float:
    return 6.18 + 0.417 * cucm if phase == 0 else 2.28 + 0.308 * cucm


@nb.njit(cache=True)
def _classic_phase_c1(phase: int) -> float:
    return 6.18 if phase == 0 else 2.28


@nb.njit(cache=True)
def _swirl_phase_c1(phase: int, swirl_number: float) -> float:
    return 6.18 + 0.417 * swirl_number if phase == 0 else 2.28 + 0.308 * swirl_number


@nb.njit(cache=True)
def _gt_phase_c1(phase: int, cylinder_mass_kg: float, mdot_in_kg_per_s: float) -> float:
    if phase != 0:
        return 2.28
    refresh = mdot_in_kg_per_s / max(cylinder_mass_kg, _TINY)
    if refresh < 0.0:
        refresh = 0.0
    if refresh > 1.0:
        refresh = 1.0
    return 2.28 + 3.9 * refresh


@nb.njit(cache=True)
def _motored_pressure_estimate(dp_mode: int, pressure_pa: float, volume_m3: float, v_max_m3: float) -> float:
    if dp_mode == WDP_OFF:
        return pressure_pa
    if volume_m3 <= _TINY or v_max_m3 <= _TINY:
        return pressure_pa
    return max(1.0, 1.0e5 * (v_max_m3 / max(volume_m3, _TINY)) ** 1.32)


@nb.njit(cache=True)
def _apply_dp_term(base_velocity: float, pressure_pa: float, volume_m3: float, gas_temp_K: float, wall_row: np.ndarray) -> tuple[float, float]:
    if int(wall_row[W_DP_MODE]) == WDP_OFF:
        return base_velocity, 0.0
    pm = _motored_pressure_estimate(int(wall_row[W_DP_MODE]), pressure_pa, volume_m3, wall_row[W_VMAX])
    dp = max(pressure_pa - pm, 0.0)
    pressure_term = 3.24e-3 * max(wall_row[W_VMAX], _TINY) * gas_temp_K / 1.0e5 / max(volume_m3, _TINY) * dp
    return base_velocity + pressure_term, dp


@nb.njit(cache=True)
def _woschni_common_htc(k1: float, temp_exp: float, bore_m: float, pressure_pa: float, gas_temp_K: float, gas_velocity_m_s: float, multiplier: float) -> float:
    if bore_m <= _TINY or pressure_pa <= 0.0 or gas_temp_K <= 0.0 or gas_velocity_m_s <= 0.0:
        return 0.0
    return multiplier * k1 * (bore_m ** (-0.2)) * (pressure_pa ** 0.8) * (gas_temp_K ** (-temp_exp)) * (gas_velocity_m_s ** 0.8)


@nb.njit(cache=True)
def _evaluate_variant_htc(wall_row: np.ndarray, bore_m: float, pressure_pa: float, gas_temp_K: float, mean_piston_speed_m_s: float, volume_m3: float, theta_local_deg: float, cycle_deg: float, cylinder_mass_kg: float, mdot_in_kg_per_s: float) -> tuple[float, float, float]:
    variant = int(wall_row[W_VARIANT])
    if variant == WV_LEGACY:
        return _legacy_htc(wall_row[W_C1], wall_row[W_C2], wall_row[W_C3], bore_m, pressure_pa, gas_temp_K, mean_piston_speed_m_s), 1.0 + mean_piston_speed_m_s, 0.0
    phase = _phase_bucket(theta_local_deg, cycle_deg)
    multiplier = wall_row[W_MULT] if wall_row[W_MULT] > 0.0 else 1.0
    if variant == WV_PROMO:
        w = _promo_phase_c1(phase, wall_row[W_CUCM]) * mean_piston_speed_m_s
        w, dp = _apply_dp_term(w, pressure_pa, volume_m3, gas_temp_K, wall_row)
        htc = multiplier * 0.013 * (bore_m ** (-0.2)) * (gas_temp_K ** (-0.53)) * (max(pressure_pa * max(w, 0.0), 0.0) ** 0.8)
        return htc, w, dp
    if variant == WV_CLASSIC:
        w = _classic_phase_c1(phase) * mean_piston_speed_m_s
        w, dp = _apply_dp_term(w, pressure_pa, volume_m3, gas_temp_K, wall_row)
        return _woschni_common_htc(3.26, 0.53, bore_m, pressure_pa, gas_temp_K, w, multiplier), w, dp
    if variant == WV_SWIRL:
        w = _swirl_phase_c1(phase, wall_row[W_SWIRL]) * mean_piston_speed_m_s
        w, dp = _apply_dp_term(w, pressure_pa, volume_m3, gas_temp_K, wall_row)
        return _woschni_common_htc(3.26, 0.53, bore_m, pressure_pa, gas_temp_K, w, multiplier), w, dp
    if variant == WV_GT:
        w = _gt_phase_c1(phase, cylinder_mass_kg, mdot_in_kg_per_s) * mean_piston_speed_m_s
        w, dp = _apply_dp_term(w, pressure_pa, volume_m3, gas_temp_K, wall_row)
        return _woschni_common_htc(3.01426, 0.50, bore_m, pressure_pa, gas_temp_K, w, multiplier), w, dp
    if variant == WV_HUBER:
        w_base = _swirl_phase_c1(phase, wall_row[W_SWIRL]) * mean_piston_speed_m_s
        wh = w_base * (1.0 + 2.0 * (max(wall_row[W_VCLR], _TINY) / max(volume_m3, _TINY)) ** 2 * (max(wall_row[W_IMEP], 1.0) ** (-0.2)))
        w = wh if wh > w_base else w_base
        w, dp = _apply_dp_term(w, pressure_pa, volume_m3, gas_temp_K, wall_row)
        return _woschni_common_htc(3.26, 0.53, bore_m, pressure_pa, gas_temp_K, w, multiplier), w, dp
    return _legacy_htc(wall_row[W_C1], wall_row[W_C2], wall_row[W_C3], bore_m, pressure_pa, gas_temp_K, mean_piston_speed_m_s), 1.0 + mean_piston_speed_m_s, 0.0


@nb.njit(cache=True)
def wall_heat_rate_and_coeff_from_row_numba(wall_row: np.ndarray, bore_m: float, pressure_pa: float, gas_temp_K: float, mean_piston_speed_m_s: float, volume_m3: float, theta_local_deg: float, cycle_deg: float, cylinder_mass_kg: float, mdot_in_kg_per_s: float) -> tuple[float, float, float, float]:
    if int(wall_row[W_MODEL]) != HT_WOSCHNI:
        return 0.0, 0.0, 0.0, 0.0
    htc, w, dp = _evaluate_variant_htc(wall_row, bore_m, pressure_pa, gas_temp_K, mean_piston_speed_m_s, volume_m3, theta_local_deg, cycle_deg, cylinder_mass_kg, mdot_in_kg_per_s)
    return htc * wall_row[W_AREA] * (wall_row[W_TEMP] - gas_temp_K), htc, w, dp


@nb.njit(cache=True)
def wall_heat_rate_and_coeff_from_row(wall_row: np.ndarray, bore_m: float, pressure_pa: float, gas_temp_K: float, mean_piston_speed_m_s: float) -> tuple[float, float]:
    q, h, _w, _dp = wall_heat_rate_and_coeff_from_row_numba(wall_row, bore_m, pressure_pa, gas_temp_K, mean_piston_speed_m_s, 0.0, 0.0, 720.0, 0.0, 0.0)
    return q, h


@nb.njit(cache=True)
def wall_heat_rate_from_row(wall_row: np.ndarray, bore_m: float, pressure_pa: float, gas_temp_K: float, mean_piston_speed_m_s: float) -> float:
    q, _ = wall_heat_rate_and_coeff_from_row(wall_row, bore_m, pressure_pa, gas_temp_K, mean_piston_speed_m_s)
    return q


@nb.njit(cache=True)
def wall_heat_rate_for_volume(vol_row: np.ndarray, kin_matrix: np.ndarray, wall_row: np.ndarray, pressure_pa: float, gas_temp_K: float) -> float:
    bore_m, mean_piston_speed_m_s = wall_heat_context_for_volume(vol_row, kin_matrix)
    return wall_heat_rate_from_row(wall_row, bore_m, pressure_pa, gas_temp_K, mean_piston_speed_m_s)
