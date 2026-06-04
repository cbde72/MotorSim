from __future__ import annotations

import math

import numba as nb
import numpy as np

from thermo0d.config.constants import AngleReference, CombCol, CombDurationMode, ConnCol, ConnectionType, EndpointKind, FeatureCol, VolumeCol, VolumeType, WallCol, WallTemperatureCol, WallTemperatureZone
from thermo0d.model.free_piston.forces import compute_load_info
from thermo0d.model.free_piston.geometry import bounce_volume_from_position, cylinder_distance_from_tdc, cylinder_dvdt_from_velocity, cylinder_volume_from_position, free_piston_equivalent_linear_kinematics, free_piston_local_cycle_angle_deg, free_piston_local_cycle_angle_rate_deg_s, free_piston_reference_is_active
from thermo0d.model.free_piston.thermo import pressure_from_state, temperature_from_state
from thermo0d.model.free_piston.combustion_latch import free_piston_cylinder_uses_latched_fuel, free_piston_uses_slot_closure_lambda, free_piston_uses_vapor_injector
from thermo0d.physics.flow import de_st_venant_wantzel_signed
from thermo0d.physics.combustion import _comb_duration_mode_from_row, beck_vibe_cf_peak_heat_release_rate, beck_vibe_cf_peak_heat_release_rate_numba, combustion_duration_mode_from_row, gamma_peak_heat_release_rate, gamma_peak_heat_release_rate_numba, vibe_beck_time_fraction_and_rate, vibe_beck_time_fraction_and_rate_numba, vibe_beck_time_heat_release_rate_with_total_energy, vibe_beck_time_heat_release_rate_with_total_energy_numba, vibe_fraction_and_rate, vibe_fraction_and_rate_numba, vibe_heat_release_rate_with_total_energy, vibe_heat_release_rate_with_total_energy_numba, vibe_time_fraction_and_rate, vibe_time_fraction_and_rate_numba, vibe_time_heat_release_rate_with_total_energy, vibe_time_heat_release_rate_with_total_energy_numba
from thermo0d.physics.openings import connection_area_and_coefficients
from thermo0d.physics.source_terms import volume_energy_source_terms
from thermo0d.physics.thermo import safe_pressure_from_ideal_gas, safe_temperature_from_state
from thermo0d.physics.composition import burned_fraction_0to1, combustion_conversion_rate_kg_per_s
from thermo0d.physics.quellen_props import default_airlike_lambda, lambda_from_air_and_fuel_mass, properties_from_mass_energy_components_quellen

F_MASS = int(FeatureCol.MASS_FLOW)
F_WALL = int(FeatureCol.WALL_HEAT)
F_COMB = int(FeatureCol.COMBUSTION)
F_EVAP = int(FeatureCol.EVAPORATION)
F_PV = int(FeatureCol.PV_WORK)
V_TYPE = int(VolumeCol.TYPE)
V_FIXED_VOLUME = int(VolumeCol.FIXED_VOLUME)
V_WALL_ROW = int(VolumeCol.WALL_ROW)
V_COMB_ROW = int(VolumeCol.COMB_ROW)
V_EVAP_ROW = int(VolumeCol.EVAP_ROW)
VOL_CYLINDER = int(VolumeType.CYLINDER)
VOL_BOUNCE_CHAMBER = int(VolumeType.BOUNCE_CHAMBER)
VOL_ENVIRONMENT = int(VolumeType.ENVIRONMENT)
W_TEMP = int(WallCol.WALL_TEMP)
W_AREA = int(WallCol.WALL_AREA)
COMB_START_DEG = int(CombCol.START_DEG)
COMB_DURATION_DEG = int(CombCol.DURATION_DEG)
COMB_A = int(CombCol.A)
COMB_M = int(CombCol.M)
COMB_REF_TYPE = int(CombCol.REF_TYPE)
COMB_DURATION_MODE_ANGLE = int(CombDurationMode.ANGLE)
CONN_SLOT = int(ConnectionType.SLOT)
C_TYPE = int(ConnCol.TYPE)
C_FROM = int(ConnCol.FROM_VOL)
C_TO = int(ConnCol.TO_VOL)
C_FROM_KIND = int(ConnCol.FROM_KIND)
C_TO_KIND = int(ConnCol.TO_KIND)
ENDPOINT_VOLUME = int(EndpointKind.VOLUME)
WT_AREA = int(WallTemperatureCol.AREA)
WT_ENABLED = int(WallTemperatureCol.ENABLED)
WT_ZONE_COUNT = len(WallTemperatureZone)
WT_COL_COUNT = len(WallTemperatureCol)

EMPTY_FLOAT = np.zeros(0, dtype=np.float64)
EMPTY_INT = np.zeros(0, dtype=np.int64)


def _coulomb_viscous_force(fc_N: float, cv_Ns_per_m: float, v_m_per_s: float) -> float:
    if abs(v_m_per_s) < 1.0e-15:
        return 0.0
    return float(fc_N * math.copysign(1.0, v_m_per_s) + cv_Ns_per_m * v_m_per_s)


def _bounce_pressure_Pa(x_m: float, fp) -> float:
    bounce_volume_m3 = bounce_volume_from_position(
        fp.bounce_chamber_volume0_m3,
        fp.bounce_area_m2,
        x_m,
        fp.x_min_m,
        fp.x_max_m,
    )
    return float(fp.bounce_p0_Pa * (fp.bounce_chamber_volume0_m3 / bounce_volume_m3) ** fp.bounce_polytropic_exponent)


def _stateful_bounce_index(bundle) -> int:
    for i in range(int(bundle.vol_matrix.shape[0])):
        if int(bundle.vol_matrix[i, VolumeCol.TYPE]) == VolumeType.BOUNCE_CHAMBER:
            return i
    return -1


def _state_index_arrays(bundle, n_vol: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    cached = getattr(bundle, '_free_piston_rhs_state_indices', None)
    if cached is not None:
        mass_indices, energy_indices, burned_indices, air_indices, liquid_indices = cached
        if int(getattr(mass_indices, 'shape', (0,))[0]) == int(n_vol):
            return cached

    layout = bundle.state_layout
    cached = (
        np.asarray([int(layout.mass_index(i)) for i in range(n_vol)], dtype=np.int32),
        np.asarray([int(layout.energy_index(i)) for i in range(n_vol)], dtype=np.int32),
        np.asarray([int(layout.burned_mass_index(i)) for i in range(n_vol)], dtype=np.int32),
        np.asarray([int(layout.air_mass_index(i)) for i in range(n_vol)], dtype=np.int32),
        np.asarray([int(layout.liquid_fuel_mass_index(i)) for i in range(n_vol)], dtype=np.int32),
    )
    try:
        setattr(bundle, '_free_piston_rhs_state_indices', cached)
    except Exception:
        pass
    return cached




def _air_mass_from_state(layout, y: np.ndarray, volume_index: int) -> float:
    return float(layout.air_mass_from_state(y, volume_index))


def _burned_mass_from_state(layout, y: np.ndarray, volume_index: int) -> float:
    return float(layout.burned_mass_from_state(y, volume_index))

def _fuel_vapor_mass_from_state(layout, y: np.ndarray, volume_index: int) -> float:
    return float(layout.fuel_vapor_mass_from_state(y, volume_index))


def _upstream_species_fractions(layout, y: np.ndarray, volume_index: int, environment_is_fixed: np.ndarray) -> tuple[float, float]:
    if int(environment_is_fixed[volume_index]) == 1:
        return 0.0, 1.0
    upstream_mass = float(layout.gas_mass_from_state(y, volume_index))
    if upstream_mass <= 1.0e-18:
        return 0.0, 0.0
    upstream_burned = float(layout.burned_mass_from_state(y, volume_index))
    upstream_air = float(layout.air_mass_from_state(y, volume_index))
    burned_fraction = max(0.0, min(1.0, upstream_burned / upstream_mass))
    air_fraction = max(0.0, min(1.0 - burned_fraction, upstream_air / upstream_mass))
    return burned_fraction, air_fraction


def _smoothstep01(value: float) -> float:
    x = max(0.0, min(1.0, float(value)))
    return x * x * (3.0 - 2.0 * x)


@nb.njit(cache=True)
def _fp_clamp_numba(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


@nb.njit(cache=True)
def _fp_smoothstep01_numba(value: float) -> float:
    z = _fp_clamp_numba(value, 0.0, 1.0)
    return z * z * (3.0 - 2.0 * z)


@nb.njit(cache=True)
def _fp_equivalent_linear_kinematics_numba(
    q: float,
    q_dot: float,
    sign: float,
    kinematics_mode: int,
    x_min_m: float,
    x_max_m: float,
    angle_min_rad: float,
    angle_max_rad: float,
    effective_radius_m: float,
) -> tuple[float, float]:
    if kinematics_mode == 1:
        phi = q
        omega = q_dot
        if sign < 0.0:
            phi = angle_min_rad + angle_max_rad - phi
            omega = -omega
        radius = max(effective_radius_m, 1.0e-18)
        return x_min_m + radius * (phi - angle_min_rad), radius * omega
    if sign < 0.0:
        return x_min_m + x_max_m - q, -q_dot
    return q, q_dot


@nb.njit(cache=True)
def _fp_distance_from_tdc_numba(x_m: float, x_min_m: float, x_max_m: float) -> float:
    x_eff = _fp_clamp_numba(x_m, x_min_m, x_max_m)
    return x_eff - x_min_m


@nb.njit(cache=True)
def _fp_cylinder_volume_numba(clearance_volume_m3: float, piston_area_m2: float, x_m: float, x_min_m: float, x_max_m: float) -> float:
    x_eff = _fp_clamp_numba(x_m, x_min_m, x_max_m)
    volume = clearance_volume_m3 + piston_area_m2 * (x_eff - x_min_m)
    return max(volume, 1.0e-18)


@nb.njit(cache=True)
def _fp_bounce_volume_numba(chamber_volume0_m3: float, bounce_area_m2: float, x_m: float, x_min_m: float, x_max_m: float) -> float:
    x_eff = _fp_clamp_numba(x_m, x_min_m, x_max_m)
    volume = chamber_volume0_m3 - bounce_area_m2 * (x_eff - x_min_m)
    return max(volume, 1.0e-18)


@nb.njit(cache=True)
def _fp_is_compression_stroke_numba(v_m_per_s: float, x_m: float, x_min_m: float, x_max_m: float) -> bool:
    if v_m_per_s < -1.0e-12:
        return True
    if v_m_per_s > 1.0e-12:
        return False
    stroke = max(x_max_m - x_min_m, 0.0)
    if stroke <= 1.0e-18:
        return True
    frac = (_fp_clamp_numba(x_m, x_min_m, x_max_m) - x_min_m) / stroke
    return frac <= 0.5


@nb.njit(cache=True)
def _fp_local_cycle_angle_deg_numba(x_m: float, v_m_per_s: float, x_min_m: float, x_max_m: float, cycle_deg: float) -> float:
    half_cycle_deg = 0.5 * max(cycle_deg, 0.0)
    if half_cycle_deg <= 1.0e-18:
        return 0.0
    stroke = max(x_max_m - x_min_m, 0.0)
    if stroke <= 1.0e-18:
        return 0.0
    frac = (_fp_clamp_numba(x_m, x_min_m, x_max_m) - x_min_m) / stroke
    if _fp_is_compression_stroke_numba(v_m_per_s, x_m, x_min_m, x_max_m):
        return cycle_deg - half_cycle_deg * frac
    return half_cycle_deg * frac


@nb.njit(cache=True)
def _fp_local_cycle_angle_rate_deg_s_numba(v_m_per_s: float, x_min_m: float, x_max_m: float, cycle_deg: float) -> float:
    stroke_m = max(x_max_m - x_min_m, 0.0)
    half_cycle_deg = 0.5 * max(cycle_deg, 0.0)
    if stroke_m <= 1.0e-18 or half_cycle_deg <= 1.0e-18:
        return 0.0
    return (half_cycle_deg / stroke_m) * abs(v_m_per_s)


@nb.njit(cache=True)
def _fp_air_mass_from_state_numba(y: np.ndarray, i: int) -> float:
    gas = max(y[5 * i], 0.0)
    burned = y[5 * i + 2]
    if burned <= 0.0:
        burned = 0.0
    elif burned >= gas:
        burned = gas
    air = y[5 * i + 3]
    if air <= 0.0:
        return 0.0
    max_air = max(gas - burned, 0.0)
    if air >= max_air:
        return max_air
    return air


@nb.njit(cache=True)
def _fp_burned_mass_from_state_numba(y: np.ndarray, i: int) -> float:
    gas = max(y[5 * i], 0.0)
    burned = y[5 * i + 2]
    if burned <= 0.0:
        return 0.0
    if burned >= gas:
        return gas
    return burned


@nb.njit(cache=True)
def _fp_fuel_vapor_mass_from_state_numba(y: np.ndarray, i: int) -> float:
    gas = max(y[5 * i], 0.0)
    burned = _fp_burned_mass_from_state_numba(y, i)
    air = _fp_air_mass_from_state_numba(y, i)
    vapor = gas - burned - air
    return vapor if vapor > 0.0 else 0.0


@nb.njit(cache=True)
def _fp_upstream_species_fractions_numba(y: np.ndarray, volume_index: int, environment_is_fixed: np.ndarray) -> tuple[float, float]:
    if int(environment_is_fixed[volume_index]) == 1:
        return 0.0, 1.0
    mass = max(y[5 * volume_index], 0.0)
    if mass <= 1.0e-18:
        return 0.0, 0.0
    burned = _fp_burned_mass_from_state_numba(y, volume_index)
    air = _fp_air_mass_from_state_numba(y, volume_index)
    burned_fraction = max(0.0, min(1.0, burned / mass))
    air_fraction = max(0.0, min(1.0 - burned_fraction, air / mass))
    return burned_fraction, air_fraction


@nb.njit(cache=True)
def _fp_load_force_signed_numba(
    load_model_code: int,
    damping_Ns_per_m: float,
    v_m_per_s: float,
    x_m: float,
    x_min_m: float,
    x_max_m: float,
    max_damping_Ns_per_m: float,
    control_zone_m: float,
    power_target_W: float,
    efficiency_0to1: float,
    min_velocity_m_per_s: float,
    assist_velocity_threshold_m_per_s: float,
    assist_force_N: float,
    target_margin_m: float,
    hard_margin_m: float,
    stop_kp: float,
    moving_mass_kg: float,
    max_force_N: float,
) -> float:
    v_abs = abs(v_m_per_s)
    if load_model_code == 0:
        return 0.0
    if load_model_code == 1:
        return damping_Ns_per_m * v_m_per_s
    if load_model_code == 2:
        zone = max(control_zone_m, 1.0e-12)
        proximity = 0.0
        if abs(v_m_per_s) >= 1.0e-15:
            if v_m_per_s < 0.0:
                distance = max(x_m - x_min_m, 0.0)
                if distance < zone:
                    proximity = 1.0 - distance / zone
            else:
                distance = max(x_max_m - x_m, 0.0)
                if distance < zone:
                    proximity = 1.0 - distance / zone
        c_eff = damping_Ns_per_m + (max_damping_Ns_per_m - damping_Ns_per_m) * max(0.0, min(1.0, proximity))
        force = c_eff * v_m_per_s
        threshold = max(assist_velocity_threshold_m_per_s, 0.0)
        max_assist = max(assist_force_N, 0.0)
        if threshold > 0.0 and max_assist > 0.0 and v_abs >= 1.0e-15 and v_abs < threshold:
            assist = max_assist * (1.0 - v_abs / threshold)
            force += -math.copysign(assist, v_m_per_s)
        return force
    if load_model_code == 3:
        if v_abs < 1.0e-15:
            return 0.0
        if v_m_per_s < 0.0:
            distance_to_stop = max(x_m - x_min_m, 0.0)
        elif v_m_per_s > 0.0:
            distance_to_stop = max(x_max_m - x_m, 0.0)
        else:
            distance_to_stop = min(max(x_m - x_min_m, 0.0), max(x_max_m - x_m, 0.0))
        stroke = max(x_max_m - x_min_m, 1.0e-12)
        s = _fp_clamp_numba((x_m - x_min_m) / stroke, 0.0, 1.0)
        midstroke_weight = max(0.0, 4.0 * s * (1.0 - s))
        force_cap_from_damping = max(max_damping_Ns_per_m, 0.0) * v_abs
        force_cap = max_force_N
        if force_cap <= 0.0 or not math.isfinite(force_cap):
            force_cap = force_cap_from_damping if force_cap_from_damping > 0.0 else 1.0e300
        elif force_cap_from_damping > 0.0:
            force_cap = min(force_cap, force_cap_from_damping)
        base_force = max(damping_Ns_per_m, 0.0) * v_abs
        mech_power_target = max(power_target_W, 0.0) / max(efficiency_0to1, 1.0e-12)
        power_force = midstroke_weight * mech_power_target / max(v_abs, min_velocity_m_per_s)
        stop_force = 0.0
        zone = max(control_zone_m, 0.0)
        if zone > 0.0 and distance_to_stop < zone:
            stop_zone_weight = _fp_smoothstep01_numba((zone - distance_to_stop) / zone)
            distance_after_margin = max(distance_to_stop - target_margin_m, hard_margin_m, 1.0e-9)
            stop_force_req = moving_mass_kg * v_abs * v_abs / (2.0 * distance_after_margin)
            stop_force = max(stop_kp, 0.0) * stop_zone_weight * stop_force_req
        total_force = base_force + power_force + stop_force
        if distance_to_stop <= hard_margin_m:
            total_force = force_cap
        total_force = max(0.0, min(total_force, force_cap))
        return math.copysign(total_force, v_m_per_s)
    return 0.0


def _apply_overlap_scavenging_correction(
    dy_dt: np.ndarray,
    fp,
    cylinder_idx: int,
    y: np.ndarray,
    mass_indices: np.ndarray,
    burned_indices: np.ndarray,
    air_indices: np.ndarray,
    residual_indices_or_environment_is_fixed: np.ndarray,
    environment_is_fixed: np.ndarray | None = None,
    transfer_in_rate_kg_per_s: float = 0.0,
    transfer_air_in_rate_kg_per_s: float = 0.0,
    exhaust_out_by_vol_kg_per_s: np.ndarray | None = None,
) -> None:
    if environment_is_fixed is None:
        environment_is_fixed = residual_indices_or_environment_is_fixed
    if exhaust_out_by_vol_kg_per_s is None:
        exhaust_out_by_vol_kg_per_s = np.zeros(0, dtype=np.float64)
    exhaust_out_rate_kg_per_s = float(np.sum(exhaust_out_by_vol_kg_per_s))
    fp.runtime_scavenging_transfer_in_kg_per_s = float(transfer_in_rate_kg_per_s)
    fp.runtime_scavenging_exhaust_out_kg_per_s = float(exhaust_out_rate_kg_per_s)
    fp.runtime_scavenging_burned_correction_kg_per_s = 0.0
    fp.runtime_scavenging_short_circuit_fraction = 0.0
    if int(getattr(getattr(fp, 'runtime_scavenging_transfer_in_by_vol_kg_per_s', np.zeros(0)), 'shape', (0,))[0]) > cylinder_idx:
        fp.runtime_scavenging_transfer_in_by_vol_kg_per_s[cylinder_idx] = float(transfer_in_rate_kg_per_s)
        fp.runtime_scavenging_exhaust_out_by_vol_kg_per_s[cylinder_idx] = float(exhaust_out_rate_kg_per_s)
        fp.runtime_scavenging_burned_correction_by_vol_kg_per_s[cylinder_idx] = 0.0
        fp.runtime_scavenging_short_circuit_fraction_by_vol[cylinder_idx] = 0.0
    if not bool(getattr(fp, 'scavenging_enabled', False)):
        return
    if str(getattr(fp, 'scavenging_model', 'overlap_short_circuit_0d')) != 'overlap_short_circuit_0d':
        return
    if transfer_in_rate_kg_per_s <= 1.0e-18 or exhaust_out_rate_kg_per_s <= 1.0e-18:
        return

    cylinder_mass_kg = float(y[mass_indices[cylinder_idx]])
    if cylinder_mass_kg <= 1.0e-18:
        return
    base_burned_fraction = max(0.0, min(1.0, float(y[burned_indices[cylinder_idx]]) / cylinder_mass_kg))
    base_air_fraction = max(0.0, min(1.0 - base_burned_fraction, float(y[air_indices[cylinder_idx]]) / cylinder_mass_kg))
    if base_air_fraction <= 1.0e-15 and base_burned_fraction <= 1.0e-15:
        return

    ratio = transfer_in_rate_kg_per_s / max(exhaust_out_rate_kg_per_s, 1.0e-18)
    eta_scav = 1.0 - math.exp(-max(float(getattr(fp, 'scavenging_factor', 1.25)), 0.0) * ratio)
    eta_scav = min(eta_scav, max(float(getattr(fp, 'scavenging_max_trapping_efficiency', 0.92)), 0.0))
    short_x = (ratio - float(getattr(fp, 'scavenging_short_circuit_start_ratio', 0.70))) / max(float(getattr(fp, 'scavenging_short_circuit_slope', 0.35)), 1.0e-12)
    short_fraction = max(float(getattr(fp, 'scavenging_max_short_circuit_fraction', 0.35)), 0.0) * _smoothstep01(short_x)
    if short_fraction > 0.0:
        short_fraction = max(short_fraction, 1.0 - max(float(getattr(fp, 'scavenging_max_trapping_efficiency', 0.92)), 0.0))
    short_fraction = max(0.0, min(1.0, short_fraction))

    normal_exhaust_air_rate = exhaust_out_rate_kg_per_s * base_air_fraction
    normal_exhaust_burned_rate = exhaust_out_rate_kg_per_s * base_burned_fraction
    min_residual_fraction = max(0.0, min(1.0, float(getattr(fp, 'scavenging_min_residual_fraction', 0.03))))
    residual_drive = max(base_burned_fraction - min_residual_fraction, 0.0) / max(1.0 - min_residual_fraction, 1.0e-12)
    scavenged_extra_burned_rate = eta_scav * (1.0 - short_fraction) * transfer_in_rate_kg_per_s * residual_drive
    scavenged_extra_burned_rate = min(scavenged_extra_burned_rate, normal_exhaust_air_rate, normal_exhaust_burned_rate)
    short_circuit_air_rate = short_fraction * min(max(transfer_air_in_rate_kg_per_s, 0.0), exhaust_out_rate_kg_per_s)
    short_circuit_air_rate = min(short_circuit_air_rate, normal_exhaust_burned_rate + scavenged_extra_burned_rate)

    burned_correction_rate = scavenged_extra_burned_rate - short_circuit_air_rate
    if abs(burned_correction_rate) <= 1.0e-18:
        fp.runtime_scavenging_short_circuit_fraction = float(short_fraction)
        if int(getattr(getattr(fp, 'runtime_scavenging_short_circuit_fraction_by_vol', np.zeros(0)), 'shape', (0,))[0]) > cylinder_idx:
            fp.runtime_scavenging_short_circuit_fraction_by_vol[cylinder_idx] = float(short_fraction)
        return

    dy_dt[burned_indices[cylinder_idx]] -= burned_correction_rate
    dy_dt[air_indices[cylinder_idx]] += burned_correction_rate
    for vol_idx in range(int(exhaust_out_by_vol_kg_per_s.shape[0])):
        out_rate = float(exhaust_out_by_vol_kg_per_s[vol_idx])
        if out_rate <= 1.0e-18:
            continue
        share = out_rate / exhaust_out_rate_kg_per_s
        target_correction = burned_correction_rate * share
        if int(environment_is_fixed[vol_idx]) != 1:
            dy_dt[burned_indices[vol_idx]] += target_correction
            dy_dt[air_indices[vol_idx]] -= target_correction

    fp.runtime_scavenging_burned_correction_kg_per_s = float(burned_correction_rate)
    fp.runtime_scavenging_short_circuit_fraction = float(short_fraction)
    if int(getattr(getattr(fp, 'runtime_scavenging_burned_correction_by_vol_kg_per_s', np.zeros(0)), 'shape', (0,))[0]) > cylinder_idx:
        fp.runtime_scavenging_burned_correction_by_vol_kg_per_s[cylinder_idx] = float(burned_correction_rate)
        fp.runtime_scavenging_short_circuit_fraction_by_vol[cylinder_idx] = float(short_fraction)


@nb.njit(cache=True)
def _fp_is_in_indices_numba(value: int, indices: np.ndarray) -> bool:
    for k in range(indices.shape[0]):
        if int(indices[k]) == value:
            return True
    return False


@nb.njit(cache=True)
def _fp_apply_overlap_scavenging_correction_numba(
    dy_dt: np.ndarray,
    cylinder_idx: int,
    y: np.ndarray,
    environment_is_fixed: np.ndarray,
    transfer_in_rate_kg_per_s: float,
    transfer_air_in_rate_kg_per_s: float,
    exhaust_out_by_vol_kg_per_s: np.ndarray,
    scavenging_enabled: int,
    scavenging_factor: float,
    scavenging_max_trapping_efficiency: float,
    scavenging_short_circuit_start_ratio: float,
    scavenging_short_circuit_slope: float,
    scavenging_max_short_circuit_fraction: float,
    scavenging_min_residual_fraction: float,
    scav_diag_by_vol: np.ndarray,
) -> None:
    exhaust_out_rate = 0.0
    for i in range(exhaust_out_by_vol_kg_per_s.shape[0]):
        exhaust_out_rate += exhaust_out_by_vol_kg_per_s[i]
    scav_diag_by_vol[cylinder_idx, 0] = transfer_in_rate_kg_per_s
    scav_diag_by_vol[cylinder_idx, 1] = exhaust_out_rate
    scav_diag_by_vol[cylinder_idx, 2] = 0.0
    scav_diag_by_vol[cylinder_idx, 3] = 0.0
    if scavenging_enabled != 1:
        return
    if transfer_in_rate_kg_per_s <= 1.0e-18 or exhaust_out_rate <= 1.0e-18:
        return
    cylinder_mass = max(y[5 * cylinder_idx], 0.0)
    if cylinder_mass <= 1.0e-18:
        return
    base_burned_fraction = max(0.0, min(1.0, y[5 * cylinder_idx + 2] / cylinder_mass))
    base_air_fraction = max(0.0, min(1.0 - base_burned_fraction, y[5 * cylinder_idx + 3] / cylinder_mass))
    if base_air_fraction <= 1.0e-15 and base_burned_fraction <= 1.0e-15:
        return
    ratio = transfer_in_rate_kg_per_s / max(exhaust_out_rate, 1.0e-18)
    eta_scav = 1.0 - math.exp(-max(scavenging_factor, 0.0) * ratio)
    eta_scav = min(eta_scav, max(scavenging_max_trapping_efficiency, 0.0))
    short_x = (ratio - scavenging_short_circuit_start_ratio) / max(scavenging_short_circuit_slope, 1.0e-12)
    short_fraction = max(scavenging_max_short_circuit_fraction, 0.0) * _fp_smoothstep01_numba(short_x)
    if short_fraction > 0.0:
        short_fraction = max(short_fraction, 1.0 - max(scavenging_max_trapping_efficiency, 0.0))
    short_fraction = max(0.0, min(1.0, short_fraction))
    normal_exhaust_air_rate = exhaust_out_rate * base_air_fraction
    normal_exhaust_burned_rate = exhaust_out_rate * base_burned_fraction
    min_residual = max(0.0, min(1.0, scavenging_min_residual_fraction))
    residual_drive = max(base_burned_fraction - min_residual, 0.0) / max(1.0 - min_residual, 1.0e-12)
    scavenged_extra_burned_rate = eta_scav * (1.0 - short_fraction) * transfer_in_rate_kg_per_s * residual_drive
    scavenged_extra_burned_rate = min(scavenged_extra_burned_rate, normal_exhaust_air_rate, normal_exhaust_burned_rate)
    short_circuit_air_rate = short_fraction * min(max(transfer_air_in_rate_kg_per_s, 0.0), exhaust_out_rate)
    short_circuit_air_rate = min(short_circuit_air_rate, normal_exhaust_burned_rate + scavenged_extra_burned_rate)
    burned_correction_rate = scavenged_extra_burned_rate - short_circuit_air_rate
    scav_diag_by_vol[cylinder_idx, 2] = burned_correction_rate
    scav_diag_by_vol[cylinder_idx, 3] = short_fraction
    if abs(burned_correction_rate) <= 1.0e-18:
        return
    dy_dt[5 * cylinder_idx + 2] -= burned_correction_rate
    dy_dt[5 * cylinder_idx + 3] += burned_correction_rate
    for vol_idx in range(exhaust_out_by_vol_kg_per_s.shape[0]):
        out_rate = exhaust_out_by_vol_kg_per_s[vol_idx]
        if out_rate <= 1.0e-18:
            continue
        share = out_rate / exhaust_out_rate
        target_correction = burned_correction_rate * share
        if int(environment_is_fixed[vol_idx]) != 1:
            dy_dt[5 * vol_idx + 2] += target_correction
            dy_dt[5 * vol_idx + 3] -= target_correction


@nb.njit(cache=True)
def _compute_free_piston_rhs_numba(
    t_s: float,
    y: np.ndarray,
    vol_matrix: np.ndarray,
    conn_matrix: np.ndarray,
    wall_matrix: np.ndarray,
    comb_matrix: np.ndarray,
    evap_matrix: np.ndarray,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
    cd_table: np.ndarray,
    gas_props: np.ndarray,
    feature_flags: np.ndarray,
    environment_is_fixed: np.ndarray,
    environment_pressures_pa: np.ndarray,
    environment_temperatures_K: np.ndarray,
    boundary_pressures_pa: np.ndarray,
    boundary_temperatures_K: np.ndarray,
    wall_bore_by_vol: np.ndarray,
    wall_ups_by_vol: np.ndarray,
    wall_temperature_enabled: int,
    wall_temperature_state_index_by_vol: np.ndarray,
    wall_temperature_params_by_vol: np.ndarray,
    combustion_afr_stoich_by_vol: np.ndarray,
    combustion_efficiency_by_vol: np.ndarray,
    combustion_lhv_by_vol: np.ndarray,
    cylinder_indices: np.ndarray,
    mechanical_x_indices: np.ndarray,
    mechanical_v_indices: np.ndarray,
    volume_mechanical_dof: np.ndarray,
    volume_mechanical_sign: np.ndarray,
    uses_latched_fuel_by_vol: np.ndarray,
    use_time_vibe_by_vol: np.ndarray,
    x_idx: int,
    v_idx: int,
    mechanical_dofs: int,
    kinematics_mode: int,
    x_min_m: float,
    x_max_m: float,
    angle_min_rad: float,
    angle_max_rad: float,
    rotary_radius_m: float,
    generalized_load_scale: float,
    generalized_inertia: float,
    moving_mass_kg: float,
    piston_area_m2: float,
    clearance_volume_m3: float,
    bounce_chamber_volume0_m3: float,
    bounce_area_m2: float,
    friction_fc_N: float,
    friction_cv_Ns_per_m: float,
    cycle_deg: float,
    cycle_period_s: float,
    dt_s: float,
    load_model_code: int,
    load_damping_Ns_per_m: float,
    load_max_damping_Ns_per_m: float,
    load_control_zone_m: float,
    load_power_target_W: float,
    load_efficiency_0to1: float,
    load_min_velocity_m_per_s: float,
    load_motor_assist_until_soc: int,
    load_assist_velocity_threshold_m_per_s: float,
    load_assist_force_N: float,
    load_target_margin_m: float,
    load_hard_margin_m: float,
    load_stop_kp: float,
    load_max_force_N: float,
    uses_vapor_injector: int,
    uses_slot_closure_lambda: int,
    runtime_soc_energy_J: float,
    runtime_soc_active: int,
    runtime_soc_time_s: float,
    runtime_latched_energy_J: float,
    runtime_latch_valid: int,
    runtime_injector_active: int,
    runtime_injector_time_s: float,
    runtime_injector_end_time_s: float,
    runtime_injector_rate_kg_per_s: float,
    runtime_injector_active_by_vol: np.ndarray,
    runtime_injector_time_by_vol_s: np.ndarray,
    runtime_injector_end_time_by_vol_s: np.ndarray,
    runtime_injector_rate_by_vol_kg_per_s: np.ndarray,
    runtime_slotclose_charge_active: int,
    runtime_slotclose_charge_time_s: float,
    runtime_slotclose_charge_end_time_s: float,
    runtime_slotclose_charge_rate_kg_per_s: float,
    runtime_slotclose_charge_active_by_vol: np.ndarray,
    runtime_slotclose_charge_time_by_vol_s: np.ndarray,
    runtime_slotclose_charge_end_time_by_vol_s: np.ndarray,
    runtime_slotclose_charge_rate_by_vol_kg_per_s: np.ndarray,
    runtime_latch_valid_by_vol: np.ndarray,
    runtime_latched_energy_by_vol_J: np.ndarray,
    runtime_soc_active_by_vol: np.ndarray,
    runtime_soc_time_by_vol_s: np.ndarray,
    runtime_soc_energy_by_vol_J: np.ndarray,
    runtime_cool_flame_active_by_vol: np.ndarray,
    runtime_cool_flame_time_by_vol_s: np.ndarray,
    runtime_cool_flame_energy_by_vol_J: np.ndarray,
    runtime_cool_flame_peak_delay_by_vol_s: np.ndarray,
    runtime_cool_flame_qdot_peak_by_vol_W: np.ndarray,
    runtime_cool_flame_duration_model_by_vol_s: np.ndarray,
    hcci_burn_model_by_vol: np.ndarray,
    hcci_cool_flame_a_by_vol: np.ndarray,
    hcci_cool_flame_m_by_vol: np.ndarray,
    hcci_cool_flame_burn_model_by_vol: np.ndarray,
    hcci_cool_flame_duration_by_vol_s: np.ndarray,
    hcci_cool_flame_shape_m_by_vol: np.ndarray,
    scavenging_enabled: int,
    scavenging_factor: float,
    scavenging_max_trapping_efficiency: float,
    scavenging_short_circuit_start_ratio: float,
    scavenging_short_circuit_slope: float,
    scavenging_max_short_circuit_fraction: float,
    scavenging_min_residual_fraction: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n_vol = vol_matrix.shape[0]
    dy_dt = np.zeros_like(y)
    diag = np.zeros(4, dtype=np.float64)
    scav_diag_by_vol = np.zeros((n_vol, 4), dtype=np.float64)
    motor_assist_soc_seen = runtime_soc_time_s > 0.0
    if not motor_assist_soc_seen:
        for i_soc in range(runtime_soc_time_by_vol_s.shape[0]):
            if runtime_soc_time_by_vol_s[i_soc] > 0.0:
                motor_assist_soc_seen = True
                break
    x_m, v_m_per_s = _fp_equivalent_linear_kinematics_numba(
        y[x_idx], y[v_idx], 1.0, kinematics_mode, x_min_m, x_max_m, angle_min_rad, angle_max_rad, rotary_radius_m
    )
    cp_default = gas_props[0]
    cv_default = gas_props[1]
    gas_constant_default = gas_props[2]
    kappa_default = gas_props[3]
    use_promo_thermo = gas_props.shape[0] > 4 and gas_props[4] >= 0.5

    wall_temp_eff_by_vol = np.zeros(n_vol, dtype=np.float64)
    wall_area_eff_by_vol = np.zeros(n_vol, dtype=np.float64)
    if wall_temperature_enabled == 1 and wall_matrix.shape[0] > 0:
        for i in range(n_vol):
            wall_row_idx = int(vol_matrix[i, V_WALL_ROW])
            if wall_row_idx >= 0 and wall_row_idx < wall_matrix.shape[0]:
                wall_temp_eff_by_vol[i] = wall_matrix[wall_row_idx, W_TEMP]
                wall_area_eff_by_vol[i] = wall_matrix[wall_row_idx, W_AREA]
            if wall_row_idx >= 0 and wall_row_idx < wall_matrix.shape[0] and i < wall_temperature_state_index_by_vol.shape[0]:
                total_area = 0.0
                weighted_temp = 0.0
                for zone in range(WT_ZONE_COUNT):
                    wall_state_idx = int(wall_temperature_state_index_by_vol[i, zone])
                    if wall_state_idx >= 0 and wall_temperature_params_by_vol[i, zone, WT_ENABLED] > 0.5:
                        area = wall_temperature_params_by_vol[i, zone, WT_AREA]
                        total_area += area
                        weighted_temp += area * y[wall_state_idx]
                if total_area > 1.0e-18:
                    wall_area_eff_by_vol[i] = total_area
                    wall_temp_eff_by_vol[i] = weighted_temp / total_area

    pressures = np.zeros(n_vol, dtype=np.float64)
    temperatures = np.zeros(n_vol, dtype=np.float64)
    volumes = np.zeros(n_vol, dtype=np.float64)
    dvdts = np.zeros(n_vol, dtype=np.float64)
    cp_by_vol = np.full(n_vol, cp_default, dtype=np.float64)
    gas_constant_by_vol = np.full(n_vol, gas_constant_default, dtype=np.float64)
    kappa_by_vol = np.full(n_vol, kappa_default, dtype=np.float64)
    piston_x = np.zeros(n_vol, dtype=np.float64)
    theta_local_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
    theta_global_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
    dtheta_local_dt_by_vol = np.zeros(n_vol, dtype=np.float64)
    cycle_deg_by_vol = np.full(n_vol, cycle_deg, dtype=np.float64)
    mdot_in_by_vol = np.zeros(n_vol, dtype=np.float64)
    scav_transfer_in_by_cyl = np.zeros(n_vol, dtype=np.float64)
    scav_transfer_air_in_by_cyl = np.zeros(n_vol, dtype=np.float64)
    scav_exhaust_out_by_cyl_to_vol = np.zeros((n_vol, n_vol), dtype=np.float64)
    dtheta_dt_global = cycle_deg / cycle_period_s if cycle_period_s > 1.0e-18 else 0.0
    theta_progress_deg = (t_s * dtheta_dt_global) % cycle_deg if cycle_deg > 1.0e-18 else 0.0

    for i in range(n_vol):
        vol_row = vol_matrix[i]
        vol_type = int(vol_row[V_TYPE])
        is_fixed_environment = int(environment_is_fixed[i]) == 1 or vol_type == VOL_ENVIRONMENT
        mass = max(y[5 * i], 0.0)
        energy = y[5 * i + 1]
        air_mass = _fp_air_mass_from_state_numba(y, i)
        burned_mass = _fp_burned_mass_from_state_numba(y, i)
        fuel_vapor_mass = _fp_fuel_vapor_mass_from_state_numba(y, i)
        mech_dof = int(volume_mechanical_dof[i]) if i < volume_mechanical_dof.shape[0] else -1
        mech_sign = volume_mechanical_sign[i] if i < volume_mechanical_sign.shape[0] else 0.0
        if mech_dof >= 0:
            q_m = y[int(mechanical_x_indices[mech_dof])]
            q_v = y[int(mechanical_v_indices[mech_dof])]
            x_eff_m, v_eff_m_per_s = _fp_equivalent_linear_kinematics_numba(
                q_m, q_v, mech_sign, kinematics_mode, x_min_m, x_max_m, angle_min_rad, angle_max_rad, rotary_radius_m
            )
        else:
            x_eff_m = x_m
            v_eff_m_per_s = v_m_per_s
        if vol_type == VOL_CYLINDER:
            volume = _fp_cylinder_volume_numba(clearance_volume_m3, piston_area_m2, x_eff_m, x_min_m, x_max_m)
            dvdt = piston_area_m2 * v_eff_m_per_s
            afr_stoich = combustion_afr_stoich_by_vol[i] if i < combustion_afr_stoich_by_vol.shape[0] else 14.5
            if use_promo_thermo:
                lambda_value = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_stoich)
                temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume)
                cp_by_vol[i] = cp_i
                gas_constant_by_vol[i] = gas_constant_i
                kappa_by_vol[i] = kappa_i
            else:
                temp = safe_temperature_from_state(mass, energy, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume)
            piston_x[i] = _fp_distance_from_tdc_numba(x_eff_m, x_min_m, x_max_m)
            theta_local_deg_by_vol[i] = _fp_local_cycle_angle_deg_numba(x_eff_m, v_eff_m_per_s, x_min_m, x_max_m, cycle_deg)
            theta_global_deg_by_vol[i] = theta_progress_deg
            dtheta_local_dt_by_vol[i] = _fp_local_cycle_angle_rate_deg_s_numba(v_eff_m_per_s, x_min_m, x_max_m, cycle_deg)
        elif vol_type == VOL_BOUNCE_CHAMBER:
            volume = _fp_bounce_volume_numba(bounce_chamber_volume0_m3, bounce_area_m2, x_eff_m, x_min_m, x_max_m)
            dvdt = -bounce_area_m2 * v_eff_m_per_s
            afr_stoich = combustion_afr_stoich_by_vol[i] if i < combustion_afr_stoich_by_vol.shape[0] else 14.5
            if use_promo_thermo:
                lambda_value = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_stoich)
                temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume)
                cp_by_vol[i] = cp_i
                gas_constant_by_vol[i] = gas_constant_i
                kappa_by_vol[i] = kappa_i
            else:
                temp = safe_temperature_from_state(mass, energy, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume)
        elif is_fixed_environment:
            volume = max(vol_row[V_FIXED_VOLUME], 0.0)
            dvdt = 0.0
            temp = max(environment_temperatures_K[i], 1.0)
            press = max(environment_pressures_pa[i], 1.0)
        else:
            volume = max(vol_row[V_FIXED_VOLUME], 1.0e-18)
            dvdt = 0.0
            if use_promo_thermo:
                afr_stoich = combustion_afr_stoich_by_vol[i] if i < combustion_afr_stoich_by_vol.shape[0] else 14.5
                lambda_value = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_stoich)
                temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume)
                cp_by_vol[i] = cp_i
                gas_constant_by_vol[i] = gas_constant_i
                kappa_by_vol[i] = kappa_i
            else:
                temp = safe_temperature_from_state(mass, energy, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume)
        temperatures[i] = temp
        pressures[i] = press
        volumes[i] = volume
        dvdts[i] = dvdt

    enable_mass = feature_flags.size > F_MASS and int(feature_flags[F_MASS]) == 1
    if enable_mass:
        for j in range(conn_matrix.shape[0]):
            conn = conn_matrix[j]
            left = int(conn[C_FROM])
            right = int(conn[C_TO])
            conn_type = int(conn[C_TYPE])
            left_kind = int(conn[C_FROM_KIND]) if conn.shape[0] > C_FROM_KIND else ENDPOINT_VOLUME
            right_kind = int(conn[C_TO_KIND]) if conn.shape[0] > C_TO_KIND else ENDPOINT_VOLUME
            left_is_volume = left_kind == ENDPOINT_VOLUME
            right_is_volume = right_kind == ENDPOINT_VOLUME
            p_left = pressures[left] if left_is_volume else max(boundary_pressures_pa[left], 1.0)
            t_left = temperatures[left] if left_is_volume else max(boundary_temperatures_K[left], 1.0)
            p_right = pressures[right] if right_is_volume else max(boundary_pressures_pa[right], 1.0)
            t_right = temperatures[right] if right_is_volume else max(boundary_temperatures_K[right], 1.0)
            cyl_idx = -1
            if left_is_volume and int(vol_matrix[left, V_TYPE]) == VOL_CYLINDER:
                cyl_idx = left
            elif right_is_volume and int(vol_matrix[right, V_TYPE]) == VOL_CYLINDER:
                cyl_idx = right
            area, cd_f, cd_r = connection_area_and_coefficients(
                conn,
                conn_type,
                theta_local_deg_by_vol[cyl_idx] if cyl_idx >= 0 else 0.0,
                theta_global_deg_by_vol[cyl_idx] if cyl_idx >= 0 else 0.0,
                cycle_deg_by_vol[cyl_idx] if cyl_idx >= 0 else cycle_deg,
                piston_x[cyl_idx] if cyl_idx >= 0 else 0.0,
                lift_table,
                alpha_table,
                cd_table,
                p_left,
                p_right,
            )
            if area <= 1.0e-18 or (cd_f <= 0.0 and cd_r <= 0.0):
                continue
            if p_left >= p_right:
                gamma_up = kappa_by_vol[left] if left_is_volume else kappa_default
                gas_constant_up = gas_constant_by_vol[left] if left_is_volume else gas_constant_default
                cp_up = cp_by_vol[left] if left_is_volume else cp_default
                temp_up = t_left
            else:
                gamma_up = kappa_by_vol[right] if right_is_volume else kappa_default
                gas_constant_up = gas_constant_by_vol[right] if right_is_volume else gas_constant_default
                cp_up = cp_by_vol[right] if right_is_volume else cp_default
                temp_up = t_right
            mdot = de_st_venant_wantzel_signed(p_left, t_left, p_right, t_right, area, cd_f, cd_r, gamma_up, gas_constant_up)
            h_up = cp_up * temp_up
            if left_is_volume and int(environment_is_fixed[left]) != 1:
                dy_dt[5 * left] -= mdot
                dy_dt[5 * left + 1] -= mdot * h_up
            if right_is_volume and int(environment_is_fixed[right]) != 1:
                dy_dt[5 * right] += mdot
                dy_dt[5 * right + 1] += mdot * h_up
            if mdot >= 0.0:
                if left_is_volume:
                    burned_fraction, air_fraction = _fp_upstream_species_fractions_numba(y, left, environment_is_fixed)
                else:
                    burned_fraction, air_fraction = 0.0, 1.0
                burned_transfer = mdot * burned_fraction
                air_transfer = mdot * air_fraction
                if left_is_volume and int(environment_is_fixed[left]) != 1:
                    dy_dt[5 * left + 2] -= burned_transfer
                    dy_dt[5 * left + 3] -= air_transfer
                if right_is_volume and int(environment_is_fixed[right]) != 1:
                    dy_dt[5 * right + 2] += burned_transfer
                    dy_dt[5 * right + 3] += air_transfer
                if conn_type == CONN_SLOT:
                    if right_is_volume and left_is_volume and _fp_is_in_indices_numba(right, cylinder_indices) and left != right:
                        scav_transfer_in_by_cyl[right] += mdot
                        scav_transfer_air_in_by_cyl[right] += air_transfer
                    elif right_is_volume and left_is_volume and _fp_is_in_indices_numba(left, cylinder_indices) and right != left:
                        scav_exhaust_out_by_cyl_to_vol[left, right] += mdot
            else:
                if right_is_volume:
                    burned_fraction, air_fraction = _fp_upstream_species_fractions_numba(y, right, environment_is_fixed)
                else:
                    burned_fraction, air_fraction = 0.0, 1.0
                burned_transfer = (-mdot) * burned_fraction
                air_transfer = (-mdot) * air_fraction
                if left_is_volume and int(environment_is_fixed[left]) != 1:
                    dy_dt[5 * left + 2] += burned_transfer
                    dy_dt[5 * left + 3] += air_transfer
                if right_is_volume and int(environment_is_fixed[right]) != 1:
                    dy_dt[5 * right + 2] -= burned_transfer
                    dy_dt[5 * right + 3] -= air_transfer
                if conn_type == CONN_SLOT:
                    if right_is_volume and left_is_volume and _fp_is_in_indices_numba(left, cylinder_indices) and right != left:
                        scav_transfer_in_by_cyl[left] += -mdot
                        scav_transfer_air_in_by_cyl[left] += air_transfer
                    elif right_is_volume and left_is_volume and _fp_is_in_indices_numba(right, cylinder_indices) and left != right:
                        scav_exhaust_out_by_cyl_to_vol[right, left] += -mdot
            if left_is_volume and int(vol_matrix[left, V_TYPE]) == VOL_CYLINDER and mdot < 0.0:
                mdot_in_by_vol[left] += -mdot
            if right_is_volume and int(vol_matrix[right, V_TYPE]) == VOL_CYLINDER and mdot > 0.0:
                mdot_in_by_vol[right] += mdot
        for k in range(cylinder_indices.shape[0]):
            cyl = int(cylinder_indices[k])
            _fp_apply_overlap_scavenging_correction_numba(
                dy_dt,
                cyl,
                y,
                environment_is_fixed,
                scav_transfer_in_by_cyl[cyl],
                scav_transfer_air_in_by_cyl[cyl],
                scav_exhaust_out_by_cyl_to_vol[cyl],
                scavenging_enabled,
                scavenging_factor,
                scavenging_max_trapping_efficiency,
                scavenging_short_circuit_start_ratio,
                scavenging_short_circuit_slope,
                scavenging_max_short_circuit_fraction,
                scavenging_min_residual_fraction,
                scav_diag_by_vol,
            )

    cylinder_idx = int(cylinder_indices[0]) if cylinder_indices.shape[0] > 0 else 0
    if uses_vapor_injector == 1:
        used_by_vol = runtime_injector_active_by_vol.shape[0] >= n_vol
        if used_by_vol:
            for k in range(cylinder_indices.shape[0]):
                cyl = int(cylinder_indices[k])
                rate = runtime_injector_rate_by_vol_kg_per_s[cyl]
                if int(runtime_injector_active_by_vol[cyl]) != 0 and rate > 0.0 and t_s >= runtime_injector_time_by_vol_s[cyl] - 1.0e-15 and t_s < runtime_injector_end_time_by_vol_s[cyl] - 1.0e-15:
                    dy_dt[5 * cyl] += rate
                    mass = max(y[5 * cyl], 0.0)
                    if mass > 1.0e-18:
                        dy_dt[5 * cyl + 1] += rate * max(y[5 * cyl + 1] / mass, 0.0)
                    mdot_in_by_vol[cyl] += rate
        elif runtime_injector_active != 0 and runtime_injector_rate_kg_per_s > 0.0 and t_s >= runtime_injector_time_s - 1.0e-15 and t_s < runtime_injector_end_time_s - 1.0e-15:
            dy_dt[5 * cylinder_idx] += runtime_injector_rate_kg_per_s
            mass = max(y[5 * cylinder_idx], 0.0)
            if mass > 1.0e-18:
                dy_dt[5 * cylinder_idx + 1] += runtime_injector_rate_kg_per_s * max(y[5 * cylinder_idx + 1] / mass, 0.0)
            mdot_in_by_vol[cylinder_idx] += runtime_injector_rate_kg_per_s
    if uses_slot_closure_lambda == 1:
        used_by_vol = runtime_slotclose_charge_active_by_vol.shape[0] >= n_vol
        if used_by_vol:
            for k in range(cylinder_indices.shape[0]):
                cyl = int(cylinder_indices[k])
                rate = runtime_slotclose_charge_rate_by_vol_kg_per_s[cyl]
                if int(runtime_slotclose_charge_active_by_vol[cyl]) != 0 and rate > 0.0 and t_s >= runtime_slotclose_charge_time_by_vol_s[cyl] - 1.0e-15 and t_s < runtime_slotclose_charge_end_time_by_vol_s[cyl] - 1.0e-15:
                    dy_dt[5 * cyl] += rate
                    mass = max(y[5 * cyl], 0.0)
                    if mass > 1.0e-18:
                        dy_dt[5 * cyl + 1] += rate * max(y[5 * cyl + 1] / mass, 0.0)
                    mdot_in_by_vol[cyl] += rate
        elif runtime_slotclose_charge_active != 0 and runtime_slotclose_charge_rate_kg_per_s > 0.0 and t_s >= runtime_slotclose_charge_time_s - 1.0e-15 and t_s < runtime_slotclose_charge_end_time_s - 1.0e-15:
            rate = runtime_slotclose_charge_rate_kg_per_s
            dy_dt[5 * cylinder_idx] += rate
            mass = max(y[5 * cylinder_idx], 0.0)
            if mass > 1.0e-18:
                dy_dt[5 * cylinder_idx + 1] += rate * max(y[5 * cylinder_idx + 1] / mass, 0.0)
            mdot_in_by_vol[cylinder_idx] += rate

    for i in range(n_vol):
        vol_row = vol_matrix[i]
        vol_type = int(vol_row[V_TYPE])
        if int(environment_is_fixed[i]) == 1 or vol_type == VOL_ENVIRONMENT:
            dy_dt[5 * i] = 0.0
            dy_dt[5 * i + 1] = 0.0
            dy_dt[5 * i + 2] = 0.0
            dy_dt[5 * i + 3] = 0.0
            dy_dt[5 * i + 4] = 0.0
            continue
        comb_enabled = 1 if feature_flags.size > F_COMB and int(feature_flags[F_COMB]) == 1 else 0
        comb_idx = int(vol_row[V_COMB_ROW])
        duration_mode = COMB_DURATION_MODE_ANGLE
        if comb_idx >= 0:
            duration_mode = int(_comb_duration_mode_from_row(comb_matrix[comb_idx]))
        use_latched = vol_type == VOL_CYLINDER and comb_enabled == 1 and comb_idx >= 0 and i < uses_latched_fuel_by_vol.shape[0] and int(uses_latched_fuel_by_vol[i]) == 1
        use_time_vibe = vol_type == VOL_CYLINDER and comb_enabled == 1 and comb_idx >= 0 and i < use_time_vibe_by_vol.shape[0] and int(use_time_vibe_by_vol[i]) == 1
        pdv_power, qdot_wall, htc_wall, _wall_velocity, qdot_comb, qdot_evap = volume_energy_source_terms(
            vol_type,
            int(vol_row[V_WALL_ROW]),
            comb_idx,
            int(vol_row[V_EVAP_ROW]),
            1 if feature_flags.size > F_WALL and int(feature_flags[F_WALL]) == 1 else 0,
            0 if (use_latched or use_time_vibe) else comb_enabled,
            1 if feature_flags.size > F_EVAP and int(feature_flags[F_EVAP]) == 1 else 0,
            1 if feature_flags.size > F_PV and int(feature_flags[F_PV]) == 1 else 0,
            wall_matrix,
            comb_matrix,
            evap_matrix,
            wall_bore_by_vol[i],
            wall_ups_by_vol[i],
            pressures[i],
            temperatures[i],
            volumes[i],
            max(y[5 * i], 0.0),
            mdot_in_by_vol[i],
            dvdts[i],
            theta_local_deg_by_vol[i],
            theta_global_deg_by_vol[i],
            dtheta_local_dt_by_vol[i],
            dtheta_dt_global,
            cycle_deg_by_vol[i],
        )
        if wall_temperature_enabled == 1 and feature_flags.size > F_WALL and int(feature_flags[F_WALL]) == 1 and int(vol_row[V_WALL_ROW]) >= 0 and wall_area_eff_by_vol[i] > 0.0:
            qdot_wall = htc_wall * wall_area_eff_by_vol[i] * (wall_temp_eff_by_vol[i] - temperatures[i])
        if use_time_vibe:
            comb_row = comb_matrix[comb_idx]
            if runtime_soc_active_by_vol.shape[0] > i:
                q_total_active = runtime_soc_energy_by_vol_J[i] if int(runtime_soc_active_by_vol[i]) != 0 else 0.0
                soc_time = runtime_soc_time_by_vol_s[i]
            else:
                q_total_active = runtime_soc_energy_J if runtime_soc_active != 0 else 0.0
                soc_time = runtime_soc_time_s
            use_vibe_beck = hcci_burn_model_by_vol.shape[0] > i and int(hcci_burn_model_by_vol[i]) == 1
            if use_vibe_beck:
                qdot_comb = vibe_beck_time_heat_release_rate_with_total_energy_numba(t_s, soc_time, comb_row[COMB_DURATION_DEG], comb_row[COMB_A], comb_row[COMB_M], q_total_active)
            else:
                qdot_comb = vibe_time_heat_release_rate_with_total_energy_numba(t_s, soc_time, comb_row[COMB_DURATION_DEG], comb_row[COMB_A], comb_row[COMB_M], q_total_active)
            if runtime_cool_flame_active_by_vol.shape[0] > i and int(runtime_cool_flame_active_by_vol[i]) != 0:
                cf_a = hcci_cool_flame_a_by_vol[i] if hcci_cool_flame_a_by_vol.shape[0] > i else comb_row[COMB_A]
                cf_m = hcci_cool_flame_m_by_vol[i] if hcci_cool_flame_m_by_vol.shape[0] > i else comb_row[COMB_M]
                use_cf_vibe_beck = hcci_cool_flame_burn_model_by_vol.shape[0] > i and int(hcci_cool_flame_burn_model_by_vol[i]) == 1
                peak_delay = runtime_cool_flame_peak_delay_by_vol_s[i] if runtime_cool_flame_peak_delay_by_vol_s.shape[0] > i else 0.0
                qdot_peak = runtime_cool_flame_qdot_peak_by_vol_W[i] if runtime_cool_flame_qdot_peak_by_vol_W.shape[0] > i else 0.0
                duration_model = runtime_cool_flame_duration_model_by_vol_s[i] if runtime_cool_flame_duration_model_by_vol_s.shape[0] > i else 0.0
                cf_time = runtime_cool_flame_time_by_vol_s[i]
                if use_cf_vibe_beck:
                    duration_cf = duration_model if duration_model > 0.0 else (hcci_cool_flame_duration_by_vol_s[i] if hcci_cool_flame_duration_by_vol_s.shape[0] > i else 0.0)
                    qdot_comb += beck_vibe_cf_peak_heat_release_rate_numba(t_s, cf_time, peak_delay, qdot_peak, cf_m, duration_cf)
                elif qdot_peak > 0.0 and peak_delay > 0.0 and duration_model > 0.0:
                    shape_m = hcci_cool_flame_shape_m_by_vol[i] if hcci_cool_flame_shape_m_by_vol.shape[0] > i and hcci_cool_flame_shape_m_by_vol[i] > 0.0 else 2.0
                    qdot_comb += gamma_peak_heat_release_rate_numba(t_s, cf_time, peak_delay, qdot_peak, shape_m, duration_model)
                elif use_vibe_beck:
                    duration_cf = hcci_cool_flame_duration_by_vol_s[i] if hcci_cool_flame_duration_by_vol_s.shape[0] > i else 0.0
                    qdot_comb += vibe_beck_time_heat_release_rate_with_total_energy_numba(t_s, cf_time, duration_cf, cf_a, cf_m, runtime_cool_flame_energy_by_vol_J[i])
                else:
                    duration_cf = hcci_cool_flame_duration_by_vol_s[i] if hcci_cool_flame_duration_by_vol_s.shape[0] > i else 0.0
                    qdot_comb += vibe_time_heat_release_rate_with_total_energy_numba(t_s, cf_time, duration_cf, cf_a, cf_m, runtime_cool_flame_energy_by_vol_J[i])
        elif use_latched:
            comb_row = comb_matrix[comb_idx]
            if runtime_latch_valid_by_vol.shape[0] > i:
                q_total_latched = runtime_latched_energy_by_vol_J[i] if int(runtime_latch_valid_by_vol[i]) != 0 else 0.0
            else:
                q_total_latched = runtime_latched_energy_J if runtime_latch_valid != 0 else 0.0
            qdot_comb = vibe_heat_release_rate_with_total_energy_numba(
                theta_local_deg_by_vol[i],
                theta_global_deg_by_vol[i],
                dtheta_local_dt_by_vol[i],
                dtheta_dt_global,
                comb_row[COMB_START_DEG],
                comb_row[COMB_DURATION_DEG],
                comb_row[COMB_A],
                comb_row[COMB_M],
                q_total_latched,
                int(comb_row[COMB_REF_TYPE]),
                cycle_deg_by_vol[i],
            )
        dy_dt[5 * i + 1] = dy_dt[5 * i + 1] - pdv_power + qdot_wall + qdot_comb - qdot_evap
        evap_idx = int(vol_row[V_EVAP_ROW])
        if vol_type == VOL_CYLINDER and feature_flags.size > F_EVAP and int(feature_flags[F_EVAP]) == 1 and evap_idx >= 0 and qdot_evap > 0.0:
            latent = evap_matrix[evap_idx, 4]
            if latent > 1.0e-18 and y[5 * i + 4] > 0.0:
                evap_mdot = qdot_evap / latent
                dy_dt[5 * i + 4] -= evap_mdot
                dy_dt[5 * i] += evap_mdot
        if vol_type == VOL_CYLINDER and comb_idx >= 0 and qdot_comb > 0.0:
            comb_row = comb_matrix[comb_idx]
            if use_time_vibe:
                soc_time_conv = runtime_soc_time_by_vol_s[i] if runtime_soc_time_by_vol_s.shape[0] > i else runtime_soc_time_s
                use_vibe_beck = hcci_burn_model_by_vol.shape[0] > i and int(hcci_burn_model_by_vol[i]) == 1
                if use_vibe_beck:
                    xb, dxb_dt = vibe_beck_time_fraction_and_rate_numba(t_s, soc_time_conv, comb_row[COMB_DURATION_DEG], comb_row[COMB_A], comb_row[COMB_M])
                else:
                    xb, dxb_dt = vibe_time_fraction_and_rate_numba(t_s, soc_time_conv, comb_row[COMB_DURATION_DEG], comb_row[COMB_A], comb_row[COMB_M])
            else:
                xb, dxb_dt = vibe_fraction_and_rate_numba(
                    theta_local_deg_by_vol[i],
                    theta_global_deg_by_vol[i],
                    dtheta_local_dt_by_vol[i],
                    dtheta_dt_global,
                    comb_row[COMB_START_DEG],
                    comb_row[COMB_DURATION_DEG],
                    comb_row[COMB_A],
                    comb_row[COMB_M],
                    int(comb_row[COMB_REF_TYPE]),
                    cycle_deg_by_vol[i],
                )
            air_mass = _fp_air_mass_from_state_numba(y, i)
            fuel_vapor_mass = _fp_fuel_vapor_mass_from_state_numba(y, i)
            afr_stoich = combustion_afr_stoich_by_vol[i] if i < combustion_afr_stoich_by_vol.shape[0] else 14.5
            comb_eff = combustion_efficiency_by_vol[i] if i < combustion_efficiency_by_vol.shape[0] else 1.0
            lhv = combustion_lhv_by_vol[i] if i < combustion_lhv_by_vol.shape[0] else 0.0
            if afr_stoich > 1.0e-18 and comb_eff > 1.0e-18 and lhv > 1.0e-18:
                requested_fuel_burn_rate = qdot_comb / max(lhv * comb_eff, 1.0e-18)
                max_fuel_burn_rate_from_fuel = max(fuel_vapor_mass, 0.0) / max(dt_s, 1.0e-12)
                max_fuel_burn_rate_from_air = max(air_mass, 0.0) / max(afr_stoich * dt_s, 1.0e-18)
                fuel_burn_rate = min(requested_fuel_burn_rate, max_fuel_burn_rate_from_fuel, max_fuel_burn_rate_from_air)
                if fuel_burn_rate > 0.0:
                    air_consumption_rate = afr_stoich * fuel_burn_rate
                    burned_production_rate = fuel_burn_rate + air_consumption_rate
                    dy_dt[5 * i + 3] -= air_consumption_rate
                    dy_dt[5 * i + 2] += burned_production_rate
                    qdot_comb = fuel_burn_rate * lhv * comb_eff
                    dy_dt[5 * i + 1] = dy_dt[5 * i + 1] - pdv_power + qdot_wall + qdot_comb - qdot_evap
                    if i == cylinder_idx:
                        diag[0] = fuel_burn_rate
                        diag[1] = air_consumption_rate
                        diag[2] = burned_production_rate
                        diag[3] = qdot_comb
                else:
                    dy_dt[5 * i + 1] = dy_dt[5 * i + 1] - pdv_power + qdot_wall - qdot_evap

    for dof in range(mechanical_dofs):
        q_idx = int(mechanical_x_indices[dof])
        qv_idx = int(mechanical_v_indices[dof])
        q = y[q_idx]
        q_dot = y[qv_idx]
        q_m, q_v_m_per_s = _fp_equivalent_linear_kinematics_numba(q, q_dot, 1.0, kinematics_mode, x_min_m, x_max_m, angle_min_rad, angle_max_rad, rotary_radius_m)
        force_gas = 0.0
        force_bounce = 0.0
        for i in range(n_vol):
            if int(volume_mechanical_dof[i]) != dof:
                continue
            sign_i = volume_mechanical_sign[i]
            vol_type_i = int(vol_matrix[i, V_TYPE])
            if vol_type_i == VOL_CYLINDER:
                force_gas += sign_i * pressures[i] * piston_area_m2
            elif vol_type_i == VOL_BOUNCE_CHAMBER:
                force_bounce += -sign_i * pressures[i] * bounce_area_m2
        if abs(q_v_m_per_s) < 1.0e-15:
            force_friction = 0.0
        else:
            force_friction = -(friction_fc_N * math.copysign(1.0, q_v_m_per_s) + friction_cv_Ns_per_m * q_v_m_per_s)
        assist_threshold = load_assist_velocity_threshold_m_per_s
        assist_force = load_assist_force_N
        if load_motor_assist_until_soc == 1 and motor_assist_soc_seen:
            assist_threshold = 0.0
            assist_force = 0.0
        force_load = -_fp_load_force_signed_numba(
            load_model_code,
            load_damping_Ns_per_m,
            q_v_m_per_s,
            q_m,
            x_min_m,
            x_max_m,
            load_max_damping_Ns_per_m,
            load_control_zone_m,
            load_power_target_W,
            load_efficiency_0to1,
            load_min_velocity_m_per_s,
            assist_threshold,
            assist_force,
            load_target_margin_m,
            load_hard_margin_m,
            load_stop_kp,
            moving_mass_kg,
            load_max_force_N,
        )
        force_net = force_gas + force_bounce + force_friction + force_load
        dy_dt[q_idx] = q_dot
        dy_dt[qv_idx] = (force_net * generalized_load_scale) / generalized_inertia
    return dy_dt, diag, scav_diag_by_vol


def _compute_free_piston_rhs_python(t_s: float, y: np.ndarray, bundle) -> np.ndarray:
    fp = bundle.free_piston
    if fp is None:
        raise ValueError('bundle.free_piston must be present for free_piston RHS')

    x_idx = int(fp.x_state_index)
    v_idx = int(fp.v_state_index)
    mechanical_dofs = int(getattr(fp, 'mechanical_dofs', 1) or 1)
    mechanical_x_indices = getattr(fp, 'mechanical_x_state_indices', np.array([x_idx], dtype=np.int64))
    mechanical_v_indices = getattr(fp, 'mechanical_v_state_indices', np.array([v_idx], dtype=np.int64))
    volume_mechanical_dof = getattr(fp, 'volume_mechanical_dof', np.full(int(bundle.vol_matrix.shape[0]), -1, dtype=np.int64))
    volume_mechanical_sign = getattr(fp, 'volume_mechanical_sign', np.zeros(int(bundle.vol_matrix.shape[0]), dtype=np.float64))
    x_min_m = fp.x_min_m
    x_max_m = fp.x_max_m
    kinematics_type = str(getattr(fp, 'kinematics_type', 'linear') or 'linear')
    rotary_radius_m = float(getattr(fp, 'rotary_effective_radius_m', 1.0) or 1.0)
    moving_mass_kg = fp.moving_mass_kg
    generalized_load_scale = rotary_radius_m if kinematics_type == 'oscillating_rotary' else 1.0
    generalized_inertia = float(getattr(fp, 'rotary_inertia_kg_m2', moving_mass_kg)) if kinematics_type == 'oscillating_rotary' else moving_mass_kg
    piston_area_m2 = fp.piston_area_m2
    clearance_volume_m3 = fp.clearance_volume_m3
    bounce_chamber_volume0_m3 = fp.bounce_chamber_volume0_m3
    bounce_area_m2 = fp.bounce_area_m2
    friction_fc_N = fp.friction_fc_N
    friction_cv_Ns_per_m = fp.friction_cv_Ns_per_m
    runtime_soc_energy_J = fp.runtime_soc_energy_J if hasattr(fp, 'runtime_soc_energy_J') else 0.0
    runtime_soc_active = fp.runtime_soc_active if hasattr(fp, 'runtime_soc_active') else False
    runtime_soc_time_s = fp.runtime_soc_time_s if hasattr(fp, 'runtime_soc_time_s') else 0.0
    runtime_latched_energy_J = fp.runtime_latched_energy_J if hasattr(fp, 'runtime_latched_energy_J') else 0.0
    runtime_latch_valid = fp.runtime_latch_valid if hasattr(fp, 'runtime_latch_valid') else False
    runtime_injector_active = fp.runtime_injector_active if hasattr(fp, 'runtime_injector_active') else False
    runtime_injector_time_s = fp.runtime_injector_time_s if hasattr(fp, 'runtime_injector_time_s') else 0.0
    runtime_injector_end_time_s = fp.runtime_injector_end_time_s if hasattr(fp, 'runtime_injector_end_time_s') else 0.0
    runtime_injector_rate_kg_per_s = fp.runtime_injector_rate_kg_per_s if hasattr(fp, 'runtime_injector_rate_kg_per_s') else 0.0
    runtime_injector_active_by_vol = getattr(fp, 'runtime_injector_active_by_vol', EMPTY_INT)
    runtime_injector_time_by_vol_s = getattr(fp, 'runtime_injector_time_by_vol_s', EMPTY_FLOAT)
    runtime_injector_end_time_by_vol_s = getattr(fp, 'runtime_injector_end_time_by_vol_s', EMPTY_FLOAT)
    runtime_injector_rate_by_vol_kg_per_s = getattr(fp, 'runtime_injector_rate_by_vol_kg_per_s', EMPTY_FLOAT)
    runtime_slotclose_charge_active = fp.runtime_slotclose_charge_active if hasattr(fp, 'runtime_slotclose_charge_active') else False
    runtime_slotclose_charge_time_s = fp.runtime_slotclose_charge_time_s if hasattr(fp, 'runtime_slotclose_charge_time_s') else 0.0
    runtime_slotclose_charge_end_time_s = fp.runtime_slotclose_charge_end_time_s if hasattr(fp, 'runtime_slotclose_charge_end_time_s') else 0.0
    runtime_slotclose_charge_rate_kg_per_s = fp.runtime_slotclose_charge_rate_kg_per_s if hasattr(fp, 'runtime_slotclose_charge_rate_kg_per_s') else 0.0
    runtime_latch_valid_by_vol = getattr(fp, 'runtime_latch_valid_by_vol', EMPTY_INT)
    runtime_latched_energy_by_vol_J = getattr(fp, 'runtime_latched_energy_by_vol_J', EMPTY_FLOAT)
    runtime_soc_active_by_vol = getattr(fp, 'runtime_soc_active_by_vol', EMPTY_INT)
    runtime_soc_time_by_vol_s = getattr(fp, 'runtime_soc_time_by_vol_s', EMPTY_FLOAT)
    runtime_soc_energy_by_vol_J = getattr(fp, 'runtime_soc_energy_by_vol_J', EMPTY_FLOAT)
    runtime_cool_flame_active_by_vol = getattr(fp, 'runtime_cool_flame_active_by_vol', EMPTY_INT)
    runtime_cool_flame_time_by_vol_s = getattr(fp, 'runtime_cool_flame_time_by_vol_s', EMPTY_FLOAT)
    runtime_cool_flame_energy_by_vol_J = getattr(fp, 'runtime_cool_flame_energy_by_vol_J', EMPTY_FLOAT)
    runtime_cool_flame_peak_delay_by_vol_s = getattr(fp, 'runtime_cool_flame_peak_delay_by_vol_s', EMPTY_FLOAT)
    runtime_cool_flame_qdot_peak_by_vol_W = getattr(fp, 'runtime_cool_flame_qdot_peak_by_vol_W', EMPTY_FLOAT)
    runtime_cool_flame_duration_model_by_vol_s = getattr(fp, 'runtime_cool_flame_duration_model_by_vol_s', EMPTY_FLOAT)
    hcci_burn_model_by_vol = getattr(fp, 'hcci_burn_model_by_vol', EMPTY_INT)
    runtime_slotclose_charge_active_by_vol = getattr(fp, 'runtime_slotclose_charge_active_by_vol', EMPTY_INT)
    runtime_slotclose_charge_time_by_vol_s = getattr(fp, 'runtime_slotclose_charge_time_by_vol_s', EMPTY_FLOAT)
    runtime_slotclose_charge_end_time_by_vol_s = getattr(fp, 'runtime_slotclose_charge_end_time_by_vol_s', EMPTY_FLOAT)
    runtime_slotclose_charge_rate_by_vol_kg_per_s = getattr(fp, 'runtime_slotclose_charge_rate_by_vol_kg_per_s', EMPTY_FLOAT)
    if hasattr(fp, 'runtime_combustion_fuel_burn_rate_kg_per_s'):
        fp.runtime_combustion_fuel_burn_rate_kg_per_s = 0.0
        fp.runtime_combustion_air_consumption_rate_kg_per_s = 0.0
        fp.runtime_combustion_burned_production_rate_kg_per_s = 0.0
        fp.runtime_combustion_qdot_W = 0.0
    if hasattr(fp, 'runtime_scavenging_transfer_in_kg_per_s'):
        fp.runtime_scavenging_transfer_in_kg_per_s = 0.0
        fp.runtime_scavenging_exhaust_out_kg_per_s = 0.0
        fp.runtime_scavenging_burned_correction_kg_per_s = 0.0
        fp.runtime_scavenging_short_circuit_fraction = 0.0
    if int(getattr(getattr(fp, 'runtime_scavenging_transfer_in_by_vol_kg_per_s', np.zeros(0)), 'shape', (0,))[0]) >= int(bundle.vol_matrix.shape[0]):
        fp.runtime_scavenging_transfer_in_by_vol_kg_per_s.fill(0.0)
        fp.runtime_scavenging_exhaust_out_by_vol_kg_per_s.fill(0.0)
        fp.runtime_scavenging_burned_correction_by_vol_kg_per_s.fill(0.0)
        fp.runtime_scavenging_short_circuit_fraction_by_vol.fill(0.0)

    cylinder_idx = int(bundle.cylinder_indices[0])
    cyl_m_idx = int(bundle.state_layout.mass_index(cylinder_idx))
    cyl_U_idx = int(bundle.state_layout.energy_index(cylinder_idx))

    n_vol = int(bundle.vol_matrix.shape[0])
    mass_indices, energy_indices, burned_indices, air_indices, liquid_indices = _state_index_arrays(bundle, n_vol)

    bounce_idx = _stateful_bounce_index(bundle)

    x_m, v_m_per_s = free_piston_equivalent_linear_kinematics(
        float(y[x_idx]),
        float(y[v_idx]),
        1.0,
        kinematics_type=kinematics_type,
        x_min_m=x_min_m,
        x_max_m=x_max_m,
        angle_min_rad=float(getattr(fp, 'rotary_angle_min_rad', 0.0) or 0.0),
        angle_max_rad=float(getattr(fp, 'rotary_angle_max_rad', 0.0) or 0.0),
        effective_radius_m=rotary_radius_m,
    )
    cylinder_mass_kg = float(bundle.state_layout.gas_mass_from_state(y, cylinder_idx))
    cylinder_internal_energy_J = float(y[cyl_U_idx])
    cylinder_distance_from_tdc_m = cylinder_distance_from_tdc(x_m, x_min_m, x_max_m)

    if cylinder_mass_kg <= 0.0:
        cylinder_volume_m3 = cylinder_volume_from_position(clearance_volume_m3, piston_area_m2, x_m, x_min_m, x_max_m)
        raise ValueError(f'free-piston cylinder mass must be > 0 (t={t_s:.6g} s, x={x_m:.6g} m, v={v_m_per_s:.6g} m/s, V={cylinder_volume_m3:.6g} m^3, U={cylinder_internal_energy_J:.6g} J)')
    if cylinder_internal_energy_J <= 0.0:
        raise ValueError('free-piston cylinder internal energy must be > 0')

    cp_default = float(bundle.gas_props[0])
    cv_default = float(bundle.gas_props[1])
    gas_constant_default = float(bundle.gas_props[2])
    kappa_default = float(bundle.gas_props[3])
    use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5

    dy_dt = np.zeros_like(y)
    wall_matrix = bundle.wall_matrix
    wall_temperature_state_index_by_vol = getattr(bundle, 'wall_temperature_state_index_by_vol', None)
    wall_temperature_params_by_vol = getattr(bundle, 'wall_temperature_params_by_vol', None)
    wall_temperature_enabled = bool(getattr(bundle, 'wall_temperature_enabled', False)) and wall_temperature_state_index_by_vol is not None and wall_temperature_params_by_vol is not None
    wall_temp_eff_by_vol = np.empty(0, dtype=np.float64)
    wall_area_eff_by_vol = np.empty(0, dtype=np.float64)
    if wall_temperature_enabled and wall_matrix.shape[0] > 0:
        wall_temp_eff_by_vol = np.zeros(n_vol, dtype=np.float64)
        wall_area_eff_by_vol = np.zeros(n_vol, dtype=np.float64)
        for i in range(n_vol):
            wall_row_idx = int(bundle.vol_matrix[i, VolumeCol.WALL_ROW])
            if wall_row_idx >= 0 and wall_row_idx < wall_matrix.shape[0]:
                wall_temp_eff_by_vol[i] = float(wall_matrix[wall_row_idx, W_TEMP])
                wall_area_eff_by_vol[i] = float(wall_matrix[wall_row_idx, int(WallCol.WALL_AREA)])
            if wall_row_idx >= 0 and wall_row_idx < wall_matrix.shape[0] and i < int(wall_temperature_state_index_by_vol.shape[0]):
                total_area = 0.0
                weighted_temp = 0.0
                for zone in range(WT_ZONE_COUNT):
                    wall_state_idx = int(wall_temperature_state_index_by_vol[i, zone])
                    if wall_state_idx >= 0 and wall_temperature_params_by_vol is not None and float(wall_temperature_params_by_vol[i, zone, WT_ENABLED]) > 0.5:
                        area = float(wall_temperature_params_by_vol[i, zone, WT_AREA])
                        total_area += area
                        weighted_temp += area * float(y[wall_state_idx])
                if total_area > 1.0e-18:
                    wall_area_eff_by_vol[i] = total_area
                    wall_temp_eff_by_vol[i] = weighted_temp / total_area
    pressures = np.zeros(n_vol, dtype=np.float64)
    temperatures = np.zeros(n_vol, dtype=np.float64)
    volumes = np.zeros(n_vol, dtype=np.float64)
    dvdts = np.zeros(n_vol, dtype=np.float64)
    cp_by_vol = np.full(n_vol, cp_default, dtype=np.float64)
    cv_by_vol = np.full(n_vol, cv_default, dtype=np.float64)
    gas_constant_by_vol = np.full(n_vol, gas_constant_default, dtype=np.float64)
    kappa_by_vol = np.full(n_vol, kappa_default, dtype=np.float64)
    lambda_by_vol = np.full(n_vol, default_airlike_lambda(), dtype=np.float64)
    piston_x = np.zeros(n_vol, dtype=np.float64)
    theta_local_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
    theta_global_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
    dtheta_local_dt_by_vol = np.zeros(n_vol, dtype=np.float64)
    cycle_deg_by_vol = np.full(n_vol, float(bundle.cycle_deg), dtype=np.float64)
    mdot_in_by_vol = np.zeros(n_vol, dtype=np.float64)
    cylinder_index_set = {int(idx) for idx in getattr(bundle, 'cylinder_indices', [])}
    scav_transfer_in_by_cyl_kg_per_s = np.zeros(n_vol, dtype=np.float64)
    scav_transfer_air_in_by_cyl_kg_per_s = np.zeros(n_vol, dtype=np.float64)
    scav_exhaust_out_by_cyl_to_vol_kg_per_s = np.zeros((n_vol, n_vol), dtype=np.float64)

    environment_is_fixed = bundle.environment_is_fixed if bundle.environment_is_fixed is not None else np.zeros(n_vol, dtype=np.int64)
    environment_pressures_pa = bundle.environment_pressures_pa if bundle.environment_pressures_pa is not None else np.zeros(n_vol, dtype=np.float64)
    environment_temperatures_K = bundle.environment_temperatures_K if bundle.environment_temperatures_K is not None else np.zeros(n_vol, dtype=np.float64)
    boundary_pressures_pa = bundle.boundary_pressures_pa if getattr(bundle, 'boundary_pressures_pa', None) is not None else np.zeros(0, dtype=np.float64)
    boundary_temperatures_K = bundle.boundary_temperatures_K if getattr(bundle, 'boundary_temperatures_K', None) is not None else np.zeros(0, dtype=np.float64)
    wall_bore_by_vol = bundle.wall_bore_by_vol if bundle.wall_bore_by_vol is not None else np.zeros(n_vol, dtype=np.float64)
    wall_ups_by_vol = bundle.wall_ups_by_vol if bundle.wall_ups_by_vol is not None else np.zeros(n_vol, dtype=np.float64)

    cycle_deg = float(bundle.cycle_deg)
    dtheta_dt_global = float(cycle_deg / bundle.cycle_period_s) if float(bundle.cycle_period_s) > 1.0e-18 else 0.0
    theta_progress_deg = (float(t_s) * dtheta_dt_global) % cycle_deg if cycle_deg > 1.0e-18 else 0.0
    theta_local_free_piston_deg = free_piston_local_cycle_angle_deg(x_m, v_m_per_s, fp.x_min_m, fp.x_max_m, cycle_deg)
    dtheta_local_free_piston_dt_deg_s = free_piston_local_cycle_angle_rate_deg_s(v_m_per_s, fp.x_min_m, fp.x_max_m, cycle_deg)

    for i in range(n_vol):
        vol_row = bundle.vol_matrix[i]
        vol_type = int(vol_row[VolumeCol.TYPE])
        is_fixed_environment = int(environment_is_fixed[i]) == 1 or vol_type == VolumeType.ENVIRONMENT
        mass = float(bundle.state_layout.gas_mass_from_state(y, i))
        energy = float(y[bundle.state_layout.energy_index(i)])
        air_mass = _air_mass_from_state(bundle.state_layout, y, i)
        burned_mass = _burned_mass_from_state(bundle.state_layout, y, i)
        fuel_vapor_mass = _fuel_vapor_mass_from_state(bundle.state_layout, y, i)
        mech_dof = int(volume_mechanical_dof[i]) if i < int(len(volume_mechanical_dof)) else -1
        mech_sign = float(volume_mechanical_sign[i]) if i < int(len(volume_mechanical_sign)) else 0.0
        if mech_dof >= 0:
            q_m = float(y[int(mechanical_x_indices[mech_dof])])
            q_v_m_per_s = float(y[int(mechanical_v_indices[mech_dof])])
            x_eff_m, v_eff_m_per_s = free_piston_equivalent_linear_kinematics(
                q_m,
                q_v_m_per_s,
                mech_sign,
                kinematics_type=kinematics_type,
                x_min_m=x_min_m,
                x_max_m=x_max_m,
                angle_min_rad=float(getattr(fp, 'rotary_angle_min_rad', 0.0) or 0.0),
                angle_max_rad=float(getattr(fp, 'rotary_angle_max_rad', 0.0) or 0.0),
                effective_radius_m=rotary_radius_m,
            )
        else:
            x_eff_m = x_m
            v_eff_m_per_s = v_m_per_s

        if vol_type == VolumeType.CYLINDER:
            volume = cylinder_volume_from_position(clearance_volume_m3, piston_area_m2, x_eff_m, x_min_m, x_max_m)
            dvdt = cylinder_dvdt_from_velocity(piston_area_m2, v_eff_m_per_s)
            afr_stoich = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5
            if use_promo_thermo:
                lambda_value = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_stoich)
                temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume)
                cp_by_vol[i] = cp_i
                cv_by_vol[i] = cv_i
                gas_constant_by_vol[i] = gas_constant_i
                kappa_by_vol[i] = kappa_i
                lambda_by_vol[i] = lambda_value
            else:
                temp = safe_temperature_from_state(mass, energy, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume)
            piston_x[i] = cylinder_distance_from_tdc(x_eff_m, x_min_m, x_max_m)
            theta_local_deg_by_vol[i] = free_piston_local_cycle_angle_deg(x_eff_m, v_eff_m_per_s, fp.x_min_m, fp.x_max_m, cycle_deg)
            theta_global_deg_by_vol[i] = theta_progress_deg
            dtheta_local_dt_by_vol[i] = free_piston_local_cycle_angle_rate_deg_s(v_eff_m_per_s, fp.x_min_m, fp.x_max_m, cycle_deg)
            cycle_deg_by_vol[i] = cycle_deg
        elif vol_type == VolumeType.BOUNCE_CHAMBER:
            volume = bounce_volume_from_position(bounce_chamber_volume0_m3, bounce_area_m2, x_eff_m, x_min_m, x_max_m)
            dvdt = -cylinder_dvdt_from_velocity(bounce_area_m2, v_eff_m_per_s)
            afr_stoich = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5
            if use_promo_thermo:
                lambda_value = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_stoich)
                temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume)
                cp_by_vol[i] = cp_i
                cv_by_vol[i] = cv_i
                gas_constant_by_vol[i] = gas_constant_i
                kappa_by_vol[i] = kappa_i
                lambda_by_vol[i] = lambda_value
            else:
                temp = safe_temperature_from_state(mass, energy, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume)
        elif is_fixed_environment:
            volume = max(float(vol_row[VolumeCol.FIXED_VOLUME]), 0.0)
            dvdt = 0.0
            temp = max(float(environment_temperatures_K[i]), 1.0)
            press = max(float(environment_pressures_pa[i]), 1.0)
        else:
            volume = max(float(vol_row[VolumeCol.FIXED_VOLUME]), 1.0e-18)
            dvdt = 0.0
            afr_stoich = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5
            if use_promo_thermo:
                lambda_value = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_stoich)
                temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume)
                cp_by_vol[i] = cp_i
                cv_by_vol[i] = cv_i
                gas_constant_by_vol[i] = gas_constant_i
                kappa_by_vol[i] = kappa_i
                lambda_by_vol[i] = lambda_value
            else:
                temp = safe_temperature_from_state(mass, energy, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume)

        if not use_promo_thermo:
            cp_by_vol[i] = cp_default
            cv_by_vol[i] = cv_default
            gas_constant_by_vol[i] = gas_constant_default
            kappa_by_vol[i] = kappa_default
            lambda_by_vol[i] = default_airlike_lambda()

        temperatures[i] = temp
        pressures[i] = press
        volumes[i] = volume
        dvdts[i] = dvdt

    enable_mass = bundle.feature_flags.size > F_MASS and int(bundle.feature_flags[F_MASS]) == 1
    if enable_mass:
        for j in range(bundle.conn_matrix.shape[0]):
            conn = bundle.conn_matrix[j]
            left = int(conn[C_FROM])
            right = int(conn[C_TO])
            conn_type = int(conn[C_TYPE])
            left_kind = int(conn[C_FROM_KIND]) if conn.shape[0] > C_FROM_KIND else ENDPOINT_VOLUME
            right_kind = int(conn[C_TO_KIND]) if conn.shape[0] > C_TO_KIND else ENDPOINT_VOLUME
            left_is_volume = left_kind == ENDPOINT_VOLUME
            right_is_volume = right_kind == ENDPOINT_VOLUME
            p_left = float(pressures[left]) if left_is_volume else max(float(boundary_pressures_pa[left]), 1.0)
            t_left = float(temperatures[left]) if left_is_volume else max(float(boundary_temperatures_K[left]), 1.0)
            p_right = float(pressures[right]) if right_is_volume else max(float(boundary_pressures_pa[right]), 1.0)
            t_right = float(temperatures[right]) if right_is_volume else max(float(boundary_temperatures_K[right]), 1.0)

            cyl_idx = -1
            if left_is_volume and int(bundle.vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER:
                cyl_idx = left
            elif right_is_volume and int(bundle.vol_matrix[right, VolumeCol.TYPE]) == VolumeType.CYLINDER:
                cyl_idx = right

            area, cd_f, cd_r = connection_area_and_coefficients(
                conn,
                conn_type,
                theta_local_deg_by_vol[cyl_idx] if cyl_idx >= 0 else 0.0,
                theta_global_deg_by_vol[cyl_idx] if cyl_idx >= 0 else 0.0,
                cycle_deg_by_vol[cyl_idx] if cyl_idx >= 0 else cycle_deg,
                piston_x[cyl_idx] if cyl_idx >= 0 else 0.0,
                bundle.lift_table,
                bundle.alpha_table,
                bundle.cd_table,
                p_left,
                p_right,
            )
            if area <= 1.0e-18 or (cd_f <= 0.0 and cd_r <= 0.0):
                continue

            if p_left >= p_right:
                gamma_up = float(kappa_by_vol[left]) if left_is_volume else kappa_default
                gas_constant_up = float(gas_constant_by_vol[left]) if left_is_volume else gas_constant_default
                cp_up = float(cp_by_vol[left]) if left_is_volume else cp_default
                temp_up = t_left
            else:
                gamma_up = float(kappa_by_vol[right]) if right_is_volume else kappa_default
                gas_constant_up = float(gas_constant_by_vol[right]) if right_is_volume else gas_constant_default
                cp_up = float(cp_by_vol[right]) if right_is_volume else cp_default
                temp_up = t_right
            mdot = de_st_venant_wantzel_signed(
                p_left,
                t_left,
                p_right,
                t_right,
                area,
                cd_f,
                cd_r,
                gamma_up,
                gas_constant_up,
            )
            h_up = cp_up * temp_up

            if left_is_volume and int(environment_is_fixed[left]) != 1:
                dy_dt[mass_indices[left]] -= mdot
                dy_dt[energy_indices[left]] -= mdot * h_up
            if right_is_volume and int(environment_is_fixed[right]) != 1:
                dy_dt[mass_indices[right]] += mdot
                dy_dt[energy_indices[right]] += mdot * h_up

            if mdot >= 0.0:
                if left_is_volume:
                    upstream_burned_fraction, upstream_air_fraction = _upstream_species_fractions(bundle.state_layout, y, left, environment_is_fixed)
                else:
                    upstream_burned_fraction, upstream_air_fraction = 0.0, 1.0
                burned_transfer = mdot * upstream_burned_fraction
                air_transfer = mdot * upstream_air_fraction
                if left_is_volume and int(environment_is_fixed[left]) != 1:
                    dy_dt[burned_indices[left]] -= burned_transfer
                    dy_dt[air_indices[left]] -= air_transfer
                if right_is_volume and int(environment_is_fixed[right]) != 1:
                    dy_dt[burned_indices[right]] += burned_transfer
                    dy_dt[air_indices[right]] += air_transfer
                if conn_type == int(ConnectionType.SLOT):
                    if left_is_volume and right_is_volume and right in cylinder_index_set and left != right:
                        scav_transfer_in_by_cyl_kg_per_s[right] += float(mdot)
                        scav_transfer_air_in_by_cyl_kg_per_s[right] += float(air_transfer)
                    elif left_is_volume and right_is_volume and left in cylinder_index_set and right != left:
                        scav_exhaust_out_by_cyl_to_vol_kg_per_s[left, right] += float(mdot)
            else:
                if right_is_volume:
                    upstream_burned_fraction, upstream_air_fraction = _upstream_species_fractions(bundle.state_layout, y, right, environment_is_fixed)
                else:
                    upstream_burned_fraction, upstream_air_fraction = 0.0, 1.0
                burned_transfer = (-mdot) * upstream_burned_fraction
                air_transfer = (-mdot) * upstream_air_fraction
                if left_is_volume and int(environment_is_fixed[left]) != 1:
                    dy_dt[burned_indices[left]] += burned_transfer
                    dy_dt[air_indices[left]] += air_transfer
                if right_is_volume and int(environment_is_fixed[right]) != 1:
                    dy_dt[burned_indices[right]] -= burned_transfer
                    dy_dt[air_indices[right]] -= air_transfer
                if conn_type == int(ConnectionType.SLOT):
                    if left_is_volume and right_is_volume and left in cylinder_index_set and right != left:
                        scav_transfer_in_by_cyl_kg_per_s[left] += float(-mdot)
                        scav_transfer_air_in_by_cyl_kg_per_s[left] += float(air_transfer)
                    elif left_is_volume and right_is_volume and right in cylinder_index_set and left != right:
                        scav_exhaust_out_by_cyl_to_vol_kg_per_s[right, left] += float(-mdot)

            if left_is_volume and int(bundle.vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER and mdot < 0.0:
                mdot_in_by_vol[left] += -mdot
            if right_is_volume and int(bundle.vol_matrix[right, VolumeCol.TYPE]) == VolumeType.CYLINDER and mdot > 0.0:
                mdot_in_by_vol[right] += mdot

        for cyl_i in bundle.cylinder_indices:
            cyl = int(cyl_i)
            _apply_overlap_scavenging_correction(
                dy_dt,
                fp,
                cyl,
                y,
                mass_indices,
                burned_indices,
                air_indices,
                environment_is_fixed,
                float(scav_transfer_in_by_cyl_kg_per_s[cyl]),
                float(scav_transfer_air_in_by_cyl_kg_per_s[cyl]),
                scav_exhaust_out_by_cyl_to_vol_kg_per_s[cyl],
            )
        if int(getattr(getattr(fp, 'runtime_scavenging_transfer_in_by_vol_kg_per_s', np.zeros(0)), 'shape', (0,))[0]) >= n_vol:
            fp.runtime_scavenging_transfer_in_kg_per_s = float(np.sum(fp.runtime_scavenging_transfer_in_by_vol_kg_per_s))
            fp.runtime_scavenging_exhaust_out_kg_per_s = float(np.sum(fp.runtime_scavenging_exhaust_out_by_vol_kg_per_s))
            fp.runtime_scavenging_burned_correction_kg_per_s = float(np.sum(fp.runtime_scavenging_burned_correction_by_vol_kg_per_s))
            fp.runtime_scavenging_short_circuit_fraction = float(np.max(fp.runtime_scavenging_short_circuit_fraction_by_vol)) if n_vol > 0 else 0.0

    if free_piston_uses_vapor_injector(bundle):
        used_by_vol_injector = False
        if int(getattr(runtime_injector_active_by_vol, 'shape', (0,))[0]) >= n_vol:
            used_by_vol_injector = True
            for cyl_i in bundle.cylinder_indices:
                cyl = int(cyl_i)
                injector_rate = float(runtime_injector_rate_by_vol_kg_per_s[cyl])
                if (
                    bool(runtime_injector_active_by_vol[cyl])
                    and injector_rate > 0.0
                    and float(t_s) >= float(runtime_injector_time_by_vol_s[cyl]) - 1.0e-15
                    and float(t_s) < float(runtime_injector_end_time_by_vol_s[cyl]) - 1.0e-15
                ):
                    dy_dt[mass_indices[cyl]] += injector_rate
                    cylinder_mass_kg = float(bundle.state_layout.gas_mass_from_state(y, cyl))
                    cylinder_energy_J = float(y[energy_indices[cyl]])
                    if cylinder_mass_kg > 1.0e-18:
                        dy_dt[energy_indices[cyl]] += injector_rate * max(cylinder_energy_J / cylinder_mass_kg, 0.0)
                    mdot_in_by_vol[cyl] += injector_rate
        if (
            not used_by_vol_injector
            and bool(runtime_injector_active)
            and float(runtime_injector_rate_kg_per_s) > 0.0
            and float(t_s) >= float(runtime_injector_time_s) - 1.0e-15
            and float(t_s) < float(runtime_injector_end_time_s) - 1.0e-15
        ):
            dy_dt[mass_indices[cylinder_idx]] += float(runtime_injector_rate_kg_per_s)
            cylinder_mass_kg = float(bundle.state_layout.gas_mass_from_state(y, cylinder_idx))
            cylinder_energy_J = float(y[energy_indices[cylinder_idx]])
            if cylinder_mass_kg > 1.0e-18:
                dy_dt[energy_indices[cylinder_idx]] += float(runtime_injector_rate_kg_per_s) * max(cylinder_energy_J / cylinder_mass_kg, 0.0)
            mdot_in_by_vol[cylinder_idx] += float(runtime_injector_rate_kg_per_s)

    if free_piston_uses_slot_closure_lambda(bundle):
        used_by_vol_charge = False
        if int(getattr(runtime_slotclose_charge_active_by_vol, 'shape', (0,))[0]) >= n_vol:
            used_by_vol_charge = True
            for cyl_i in bundle.cylinder_indices:
                cyl = int(cyl_i)
                slotclose_charge_rate = float(runtime_slotclose_charge_rate_by_vol_kg_per_s[cyl])
                if (
                    bool(runtime_slotclose_charge_active_by_vol[cyl])
                    and slotclose_charge_rate > 0.0
                    and float(t_s) >= float(runtime_slotclose_charge_time_by_vol_s[cyl]) - 1.0e-15
                    and float(t_s) < float(runtime_slotclose_charge_end_time_by_vol_s[cyl]) - 1.0e-15
                ):
                    dy_dt[mass_indices[cyl]] += slotclose_charge_rate
                    cylinder_mass_kg = float(bundle.state_layout.gas_mass_from_state(y, cyl))
                    cylinder_energy_J = float(y[energy_indices[cyl]])
                    if cylinder_mass_kg > 1.0e-18:
                        dy_dt[energy_indices[cyl]] += slotclose_charge_rate * max(cylinder_energy_J / cylinder_mass_kg, 0.0)
                    mdot_in_by_vol[cyl] += slotclose_charge_rate
        if (
            not used_by_vol_charge
            and bool(runtime_slotclose_charge_active)
            and float(runtime_slotclose_charge_rate_kg_per_s) > 0.0
            and float(t_s) >= float(runtime_slotclose_charge_time_s) - 1.0e-15
            and float(t_s) < float(runtime_slotclose_charge_end_time_s) - 1.0e-15
        ):
            slotclose_charge_rate = float(runtime_slotclose_charge_rate_kg_per_s)
            dy_dt[mass_indices[cylinder_idx]] += slotclose_charge_rate
            cylinder_mass_kg = float(bundle.state_layout.gas_mass_from_state(y, cylinder_idx))
            cylinder_energy_J = float(y[energy_indices[cylinder_idx]])
            if cylinder_mass_kg > 1.0e-18:
                dy_dt[energy_indices[cylinder_idx]] += slotclose_charge_rate * max(cylinder_energy_J / cylinder_mass_kg, 0.0)
            mdot_in_by_vol[cylinder_idx] += slotclose_charge_rate

    for i in range(n_vol):
        vol_row = bundle.vol_matrix[i]
        vol_type = int(vol_row[VolumeCol.TYPE])
        if int(environment_is_fixed[i]) == 1 or vol_type == VolumeType.ENVIRONMENT:
            dy_dt[mass_indices[i]] = 0.0
            dy_dt[energy_indices[i]] = 0.0
            dy_dt[burned_indices[i]] = 0.0
            dy_dt[air_indices[i]] = 0.0
            dy_dt[liquid_indices[i]] = 0.0
            continue

        comb_enabled = 1 if bundle.feature_flags.size > F_COMB and int(bundle.feature_flags[F_COMB]) == 1 else 0
        comb_idx = int(vol_row[VolumeCol.COMB_ROW])
        if comb_enabled == 1 and vol_type == VolumeType.CYLINDER and comb_idx >= 0:
            comb_row = bundle.comb_matrix[comb_idx]
            if not free_piston_reference_is_active(int(comb_row[CombCol.REF_TYPE]), x_m, v_m_per_s, fp.x_min_m, fp.x_max_m):
                comb_enabled = 0

        duration_mode = int(CombDurationMode.ANGLE)
        if comb_idx >= 0:
            duration_mode = int(combustion_duration_mode_from_row(bundle.comb_matrix[comb_idx]))
        use_latched_fuel_combustion = (
            vol_type == VolumeType.CYLINDER
            and comb_enabled == 1
            and comb_idx >= 0
            and free_piston_cylinder_uses_latched_fuel(bundle, i)
        )
        use_time_vibe = (
            vol_type == VolumeType.CYLINDER
            and comb_enabled == 1
            and comb_idx >= 0
            and duration_mode == int(CombDurationMode.TIME)
        )
        pdv_power, qdot_wall, htc_wall, _wall_velocity, qdot_comb, qdot_evap = volume_energy_source_terms(
            vol_type,
            int(vol_row[VolumeCol.WALL_ROW]),
            comb_idx,
            int(vol_row[VolumeCol.EVAP_ROW]),
            1 if bundle.feature_flags.size > F_WALL and int(bundle.feature_flags[F_WALL]) == 1 else 0,
            0 if (use_latched_fuel_combustion or use_time_vibe) else comb_enabled,
            1 if bundle.feature_flags.size > F_EVAP and int(bundle.feature_flags[F_EVAP]) == 1 else 0,
            1 if bundle.feature_flags.size > F_PV and int(bundle.feature_flags[F_PV]) == 1 else 0,
            wall_matrix,
            bundle.comb_matrix,
            bundle.evap_matrix,
            float(wall_bore_by_vol[i]),
            float(wall_ups_by_vol[i]),
            pressures[i],
            temperatures[i],
            volumes[i],
            float(bundle.state_layout.gas_mass_from_state(y, i)),
            mdot_in_by_vol[i],
            dvdts[i],
            theta_local_deg_by_vol[i],
            theta_global_deg_by_vol[i],
            dtheta_local_dt_by_vol[i],
            dtheta_dt_global,
            cycle_deg_by_vol[i],
        )
        if wall_temperature_enabled and bundle.feature_flags.size > F_WALL and int(bundle.feature_flags[F_WALL]) == 1 and int(vol_row[VolumeCol.WALL_ROW]) >= 0 and float(wall_area_eff_by_vol[i]) > 0.0:
            qdot_wall = float(htc_wall) * float(wall_area_eff_by_vol[i]) * (float(wall_temp_eff_by_vol[i]) - float(temperatures[i]))
        if use_time_vibe:
            comb_row = bundle.comb_matrix[comb_idx]
            if int(getattr(runtime_soc_active_by_vol, 'shape', (0,))[0]) > i:
                q_total_active_J = float(runtime_soc_energy_by_vol_J[i]) if bool(runtime_soc_active_by_vol[i]) else 0.0
                soc_time_s = float(runtime_soc_time_by_vol_s[i])
            else:
                q_total_active_J = float(runtime_soc_energy_J) if bool(runtime_soc_active) else 0.0
                soc_time_s = float(runtime_soc_time_s)
            use_vibe_beck = int(getattr(hcci_burn_model_by_vol, 'shape', (0,))[0]) > i and int(hcci_burn_model_by_vol[i]) == 1
            if use_vibe_beck:
                qdot_comb = vibe_beck_time_heat_release_rate_with_total_energy(
                    t_s,
                    soc_time_s,
                    float(comb_row[CombCol.DURATION_DEG]),
                    float(comb_row[CombCol.A]),
                    float(comb_row[CombCol.M]),
                    q_total_active_J,
                )
            else:
                qdot_comb = vibe_time_heat_release_rate_with_total_energy(
                    t_s,
                    soc_time_s,
                    float(comb_row[CombCol.DURATION_DEG]),
                    float(comb_row[CombCol.A]),
                    float(comb_row[CombCol.M]),
                    q_total_active_J,
                )
            if int(getattr(runtime_cool_flame_active_by_vol, 'shape', (0,))[0]) > i and bool(runtime_cool_flame_active_by_vol[i]):
                # Use Cool-Flame specific Vibe parameters if available; otherwise
                # fall back to the standard main combustion A / M values.
                cf_a_arr = getattr(fp, 'hcci_cool_flame_a_by_vol', None)
                cf_a = float(cf_a_arr[i]) if cf_a_arr is not None and i < cf_a_arr.shape[0] else float(comb_row[CombCol.A])
                cf_m_arr = getattr(fp, 'hcci_cool_flame_m_by_vol', None)
                cf_m = float(cf_m_arr[i]) if cf_m_arr is not None and i < cf_m_arr.shape[0] else float(comb_row[CombCol.M])
                cf_burn_model_arr = getattr(fp, 'hcci_cool_flame_burn_model_by_vol', EMPTY_INT)
                use_cf_vibe_beck = i < int(getattr(cf_burn_model_arr, 'shape', (0,))[0]) and int(cf_burn_model_arr[i]) == 1
                peak_delay_s = float(runtime_cool_flame_peak_delay_by_vol_s[i]) if i < int(getattr(runtime_cool_flame_peak_delay_by_vol_s, 'shape', (0,))[0]) else 0.0
                qdot_peak_W = float(runtime_cool_flame_qdot_peak_by_vol_W[i]) if i < int(getattr(runtime_cool_flame_qdot_peak_by_vol_W, 'shape', (0,))[0]) else 0.0
                duration_model_s = float(runtime_cool_flame_duration_model_by_vol_s[i]) if i < int(getattr(runtime_cool_flame_duration_model_by_vol_s, 'shape', (0,))[0]) else 0.0
                if use_cf_vibe_beck:
                    qdot_comb += beck_vibe_cf_peak_heat_release_rate(
                        t_s,
                        float(runtime_cool_flame_time_by_vol_s[i]),
                        peak_delay_s,
                        qdot_peak_W,
                        cf_m,
                        duration_model_s if duration_model_s > 0.0 else float(fp.hcci_cool_flame_duration_by_vol_s[i]),
                    )
                elif qdot_peak_W > 0.0 and peak_delay_s > 0.0 and duration_model_s > 0.0:
                    shape_arr = getattr(fp, 'hcci_cool_flame_shape_m_by_vol', EMPTY_FLOAT)
                    shape_m = float(shape_arr[i]) if i < int(getattr(shape_arr, 'shape', (0,))[0]) and float(shape_arr[i]) > 0.0 else 2.0
                    qdot_comb += gamma_peak_heat_release_rate(
                        t_s,
                        float(runtime_cool_flame_time_by_vol_s[i]),
                        peak_delay_s,
                        qdot_peak_W,
                        shape_m,
                        duration_model_s,
                    )
                elif use_vibe_beck:
                    qdot_comb += vibe_beck_time_heat_release_rate_with_total_energy(
                        t_s,
                        float(runtime_cool_flame_time_by_vol_s[i]),
                        float(fp.hcci_cool_flame_duration_by_vol_s[i]),
                        cf_a,
                        cf_m,
                        float(runtime_cool_flame_energy_by_vol_J[i]),
                    )
                else:
                    qdot_comb += vibe_time_heat_release_rate_with_total_energy(
                        t_s,
                        float(runtime_cool_flame_time_by_vol_s[i]),
                        float(fp.hcci_cool_flame_duration_by_vol_s[i]),
                        cf_a,
                        cf_m,
                        float(runtime_cool_flame_energy_by_vol_J[i]),
                    )
        elif use_latched_fuel_combustion:
            comb_row = bundle.comb_matrix[comb_idx]
            if int(getattr(runtime_latch_valid_by_vol, 'shape', (0,))[0]) > i:
                q_total_latched_J = float(runtime_latched_energy_by_vol_J[i]) if bool(runtime_latch_valid_by_vol[i]) else 0.0
            else:
                q_total_latched_J = float(runtime_latched_energy_J) if bool(runtime_latch_valid) else 0.0
            qdot_comb = vibe_heat_release_rate_with_total_energy(
                theta_local_deg_by_vol[i],
                theta_global_deg_by_vol[i],
                dtheta_local_dt_by_vol[i],
                dtheta_dt_global,
                float(comb_row[CombCol.START_DEG]),
                float(comb_row[CombCol.DURATION_DEG]),
                float(comb_row[CombCol.A]),
                float(comb_row[CombCol.M]),
                q_total_latched_J,
                int(comb_row[CombCol.REF_TYPE]),
                cycle_deg_by_vol[i],
            )
        dy_dt[energy_indices[i]] = dy_dt[energy_indices[i]] - pdv_power + qdot_wall + qdot_comb - qdot_evap

        evap_idx = int(vol_row[VolumeCol.EVAP_ROW])
        if vol_type == VolumeType.CYLINDER and bundle.feature_flags.size > F_EVAP and int(bundle.feature_flags[F_EVAP]) == 1 and evap_idx >= 0 and qdot_evap > 0.0:
            latent = float(bundle.evap_matrix[evap_idx, 4])
            if latent > 1.0e-18 and float(y[liquid_indices[i]]) > 0.0:
                evap_mdot = qdot_evap / latent
                dy_dt[liquid_indices[i]] -= evap_mdot
                dy_dt[mass_indices[i]] += evap_mdot

        if vol_type == VolumeType.CYLINDER and comb_idx >= 0 and qdot_comb > 0.0:
            comb_row = bundle.comb_matrix[comb_idx]
            xb = 0.0
            dxb_dt = 0.0
            if use_time_vibe:
                if int(getattr(runtime_soc_time_by_vol_s, 'shape', (0,))[0]) > i:
                    soc_time_for_conversion_s = float(runtime_soc_time_by_vol_s[i])
                else:
                    soc_time_for_conversion_s = float(runtime_soc_time_s)
                use_vibe_beck = int(getattr(hcci_burn_model_by_vol, 'shape', (0,))[0]) > i and int(hcci_burn_model_by_vol[i]) == 1
                if use_vibe_beck:
                    xb, dxb_dt = vibe_beck_time_fraction_and_rate(
                        t_s,
                        soc_time_for_conversion_s,
                        float(comb_row[CombCol.DURATION_DEG]),
                        float(comb_row[CombCol.A]),
                        float(comb_row[CombCol.M]),
                    )
                else:
                    xb, dxb_dt = vibe_time_fraction_and_rate(
                        t_s,
                        soc_time_for_conversion_s,
                        float(comb_row[CombCol.DURATION_DEG]),
                        float(comb_row[CombCol.A]),
                        float(comb_row[CombCol.M]),
                    )
            else:
                xb, dxb_dt = vibe_fraction_and_rate(
                    theta_local_deg_by_vol[i],
                    theta_global_deg_by_vol[i],
                    dtheta_local_dt_by_vol[i],
                    dtheta_dt_global,
                    float(comb_row[CombCol.START_DEG]),
                    float(comb_row[CombCol.DURATION_DEG]),
                    float(comb_row[CombCol.A]),
                    float(comb_row[CombCol.M]),
                    int(comb_row[CombCol.REF_TYPE]),
                    cycle_deg_by_vol[i],
                )
            burn_rate = combustion_conversion_rate_kg_per_s(
                float(bundle.state_layout.gas_mass_from_state(y, i)),
                float(bundle.state_layout.burned_mass_from_state(y, i)),
                float(xb),
                float(dxb_dt),
            )
            _ = burn_rate
            air_mass = _air_mass_from_state(bundle.state_layout, y, i)
            fuel_vapor_mass = _fuel_vapor_mass_from_state(bundle.state_layout, y, i)
            afr_stoich = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5
            if getattr(bundle, 'combustion_efficiency_by_vol', None) is not None and i < int(bundle.combustion_efficiency_by_vol.shape[0]):
                comb_eff = float(bundle.combustion_efficiency_by_vol[i])
            else:
                comb_eff = float(getattr(fp, 'combustion_efficiency_0to1', 1.0) or 1.0)
            if getattr(bundle, 'combustion_lhv_by_vol', None) is not None and i < int(bundle.combustion_lhv_by_vol.shape[0]):
                lhv = float(bundle.combustion_lhv_by_vol[i])
            else:
                lhv = float(getattr(fp, 'combustion_lhv_J_per_kg', 0.0) or 0.0)
            if afr_stoich > 1.0e-18 and comb_eff > 1.0e-18 and lhv > 1.0e-18:
                requested_fuel_burn_rate = qdot_comb / max(lhv * comb_eff, 1.0e-18)
                max_fuel_burn_rate_from_fuel = max(fuel_vapor_mass, 0.0) / max(float(bundle.simulation.dt_s), 1.0e-12)
                max_fuel_burn_rate_from_air = max(air_mass, 0.0) / max(afr_stoich * float(bundle.simulation.dt_s), 1.0e-18)
                fuel_burn_rate = min(requested_fuel_burn_rate, max_fuel_burn_rate_from_fuel, max_fuel_burn_rate_from_air)
                if fuel_burn_rate > 0.0:
                    air_consumption_rate = afr_stoich * fuel_burn_rate
                    burned_production_rate = fuel_burn_rate + air_consumption_rate
                    dy_dt[air_indices[i]] -= air_consumption_rate
                    dy_dt[burned_indices[i]] += burned_production_rate
                    qdot_comb = fuel_burn_rate * lhv * comb_eff
                    dy_dt[energy_indices[i]] = dy_dt[energy_indices[i]] - pdv_power + qdot_wall + qdot_comb - qdot_evap
                    if i == cylinder_idx and hasattr(fp, 'runtime_combustion_fuel_burn_rate_kg_per_s'):
                        fp.runtime_combustion_fuel_burn_rate_kg_per_s = float(fuel_burn_rate)
                        fp.runtime_combustion_air_consumption_rate_kg_per_s = float(air_consumption_rate)
                        fp.runtime_combustion_burned_production_rate_kg_per_s = float(burned_production_rate)
                        fp.runtime_combustion_qdot_W = float(qdot_comb)
                else:
                    qdot_comb = 0.0
                    dy_dt[energy_indices[i]] = dy_dt[energy_indices[i]] - pdv_power + qdot_wall - qdot_evap

    for dof in range(mechanical_dofs):
        q_idx = int(mechanical_x_indices[dof])
        qv_idx = int(mechanical_v_indices[dof])
        q = float(y[q_idx])
        q_dot = float(y[qv_idx])
        q_m, q_v_m_per_s = free_piston_equivalent_linear_kinematics(
            q,
            q_dot,
            1.0,
            kinematics_type=kinematics_type,
            x_min_m=x_min_m,
            x_max_m=x_max_m,
            angle_min_rad=float(getattr(fp, 'rotary_angle_min_rad', 0.0) or 0.0),
            angle_max_rad=float(getattr(fp, 'rotary_angle_max_rad', 0.0) or 0.0),
            effective_radius_m=rotary_radius_m,
        )
        force_gas_N = 0.0
        force_bounce_N = 0.0
        for i in range(n_vol):
            if int(volume_mechanical_dof[i]) != dof:
                continue
            sign_i = float(volume_mechanical_sign[i])
            vol_type_i = int(bundle.vol_matrix[i, VolumeCol.TYPE])
            if vol_type_i == int(VolumeType.CYLINDER):
                force_gas_N += sign_i * float(pressures[i]) * piston_area_m2
            elif vol_type_i == int(VolumeType.BOUNCE_CHAMBER):
                force_bounce_N += -sign_i * float(pressures[i]) * bounce_area_m2
        force_friction_N = -_coulomb_viscous_force(friction_fc_N, friction_cv_Ns_per_m, q_v_m_per_s)
        assist_threshold = fp.load_assist_velocity_threshold_m_per_s
        assist_force = fp.load_assist_force_N
        motor_assist_soc_seen = float(getattr(fp, 'runtime_soc_time_s', 0.0) or 0.0) > 0.0
        if not motor_assist_soc_seen:
            runtime_soc_times = getattr(fp, 'runtime_soc_time_by_vol_s', None)
            if runtime_soc_times is not None:
                motor_assist_soc_seen = bool(np.any(np.asarray(runtime_soc_times, dtype=np.float64) > 0.0))
        if bool(getattr(fp, 'load_motor_assist_until_soc', True)) and motor_assist_soc_seen:
            assist_threshold = 0.0
            assist_force = 0.0
        load_info = compute_load_info(
            fp.load_model,
            fp.load_damping_Ns_per_m,
            q_v_m_per_s,
            x_m=q_m,
            x_min_m=x_min_m,
            x_max_m=x_max_m,
            max_damping_Ns_per_m=fp.load_max_damping_Ns_per_m,
            control_zone_m=fp.load_control_zone_m,
            power_target_W=fp.load_power_target_W,
            efficiency_0to1=fp.load_efficiency_0to1,
            min_velocity_m_per_s=fp.load_min_velocity_m_per_s,
            assist_velocity_threshold_m_per_s=assist_threshold,
            assist_force_N=assist_force,
            target_margin_m=fp.load_target_margin_m,
            hard_margin_m=fp.load_hard_margin_m,
            stop_kp=fp.load_stop_kp,
            moving_mass_kg=fp.moving_mass_kg,
            max_force_N=fp.load_max_force_N,
        )
        force_load_N = -float(load_info.force_signed_N)
        force_net_N = force_gas_N + force_bounce_N + force_friction_N + force_load_N
        dy_dt[q_idx] = q_dot
        dy_dt[qv_idx] = float((force_net_N * generalized_load_scale) / generalized_inertia)
    return dy_dt


def _free_piston_load_model_code(model: str) -> int:
    text = str(model or 'none').strip().lower()
    if text == 'none':
        return 0
    if text in {'viscous', 'electromagnetic_linear'}:
        return 1
    if text == 'generator_controlled':
        return 2
    if text == 'linear_generator_regulated':
        return 3
    return -1


def _free_piston_kinematics_mode(kinematics_type: str) -> int:
    return 1 if str(kinematics_type or 'linear') == 'oscillating_rotary' else 0


def _free_piston_static_numba_args(bundle):
    cached = getattr(bundle, '_free_piston_numba_static_args', None)
    if cached is not None:
        return cached
    fp = bundle.free_piston
    n_vol = int(bundle.vol_matrix.shape[0])
    wall_temperature_state_index_by_vol = (
        bundle.wall_temperature_state_index_by_vol
        if getattr(bundle, 'wall_temperature_state_index_by_vol', None) is not None
        else np.full((n_vol, WT_ZONE_COUNT), -1, dtype=np.int64)
    )
    wall_temperature_params_by_vol = (
        bundle.wall_temperature_params_by_vol
        if getattr(bundle, 'wall_temperature_params_by_vol', None) is not None
        else np.zeros((n_vol, WT_ZONE_COUNT, len(WallTemperatureCol)), dtype=np.float64)
    )
    combustion_afr_stoich_by_vol = (
        bundle.combustion_afr_stoich_by_vol
        if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None
        else np.full(n_vol, 14.5, dtype=np.float64)
    )
    combustion_efficiency_by_vol = (
        bundle.combustion_efficiency_by_vol
        if getattr(bundle, 'combustion_efficiency_by_vol', None) is not None
        else np.full(n_vol, float(getattr(fp, 'combustion_efficiency_0to1', 1.0) or 1.0), dtype=np.float64)
    )
    combustion_lhv_by_vol = (
        bundle.combustion_lhv_by_vol
        if getattr(bundle, 'combustion_lhv_by_vol', None) is not None
        else np.full(n_vol, float(getattr(fp, 'combustion_lhv_J_per_kg', 0.0) or 0.0), dtype=np.float64)
    )
    cylinder_indices_raw = getattr(bundle, 'cylinder_indices', None)
    cylinder_indices = np.asarray(cylinder_indices_raw if cylinder_indices_raw is not None else [], dtype=np.int64)
    uses_latched_fuel_by_vol = np.zeros(n_vol, dtype=np.int64)
    use_time_vibe_by_vol = np.zeros(n_vol, dtype=np.int64)
    for i in range(n_vol):
        if free_piston_cylinder_uses_latched_fuel(bundle, i):
            uses_latched_fuel_by_vol[i] = 1
        comb_idx = int(bundle.vol_matrix[i, VolumeCol.COMB_ROW])
        if comb_idx >= 0 and comb_idx < int(bundle.comb_matrix.shape[0]):
            if int(combustion_duration_mode_from_row(bundle.comb_matrix[comb_idx])) == int(CombDurationMode.TIME):
                use_time_vibe_by_vol[i] = 1
    kinematics_type = str(getattr(fp, 'kinematics_type', 'linear') or 'linear')
    moving_mass_kg = float(fp.moving_mass_kg)
    rotary_radius_m = float(getattr(fp, 'rotary_effective_radius_m', 1.0) or 1.0)
    kinematics_mode = _free_piston_kinematics_mode(kinematics_type)
    generalized_load_scale = rotary_radius_m if kinematics_mode == 1 else 1.0
    generalized_inertia = float(getattr(fp, 'rotary_inertia_kg_m2', moving_mass_kg)) if kinematics_mode == 1 else moving_mass_kg
    load_model_code = _free_piston_load_model_code(getattr(fp, 'load_model', 'none'))
    if load_model_code < 0:
        return None
    cached = {
        'environment_is_fixed': bundle.environment_is_fixed if bundle.environment_is_fixed is not None else np.zeros(n_vol, dtype=np.int64),
        'environment_pressures_pa': bundle.environment_pressures_pa if bundle.environment_pressures_pa is not None else np.zeros(n_vol, dtype=np.float64),
        'environment_temperatures_K': bundle.environment_temperatures_K if bundle.environment_temperatures_K is not None else np.zeros(n_vol, dtype=np.float64),
        'boundary_pressures_pa': bundle.boundary_pressures_pa if getattr(bundle, 'boundary_pressures_pa', None) is not None else np.zeros(0, dtype=np.float64),
        'boundary_temperatures_K': bundle.boundary_temperatures_K if getattr(bundle, 'boundary_temperatures_K', None) is not None else np.zeros(0, dtype=np.float64),
        'wall_bore_by_vol': bundle.wall_bore_by_vol if bundle.wall_bore_by_vol is not None else np.zeros(n_vol, dtype=np.float64),
        'wall_ups_by_vol': bundle.wall_ups_by_vol if bundle.wall_ups_by_vol is not None else np.zeros(n_vol, dtype=np.float64),
        'wall_temperature_state_index_by_vol': wall_temperature_state_index_by_vol,
        'wall_temperature_params_by_vol': wall_temperature_params_by_vol,
        'combustion_afr_stoich_by_vol': combustion_afr_stoich_by_vol,
        'combustion_efficiency_by_vol': combustion_efficiency_by_vol,
        'combustion_lhv_by_vol': combustion_lhv_by_vol,
        'cylinder_indices': cylinder_indices,
        'mechanical_x_indices': np.asarray(getattr(fp, 'mechanical_x_state_indices', np.array([fp.x_state_index], dtype=np.int64)), dtype=np.int64),
        'mechanical_v_indices': np.asarray(getattr(fp, 'mechanical_v_state_indices', np.array([fp.v_state_index], dtype=np.int64)), dtype=np.int64),
        'volume_mechanical_dof': np.asarray(getattr(fp, 'volume_mechanical_dof', np.full(n_vol, -1, dtype=np.int64)), dtype=np.int64),
        'volume_mechanical_sign': np.asarray(getattr(fp, 'volume_mechanical_sign', np.zeros(n_vol, dtype=np.float64)), dtype=np.float64),
        'uses_latched_fuel_by_vol': uses_latched_fuel_by_vol,
        'use_time_vibe_by_vol': use_time_vibe_by_vol,
        'x_idx': int(fp.x_state_index),
        'v_idx': int(fp.v_state_index),
        'mechanical_dofs': int(getattr(fp, 'mechanical_dofs', 1) or 1),
        'kinematics_mode': int(kinematics_mode),
        'x_min_m': float(fp.x_min_m),
        'x_max_m': float(fp.x_max_m),
        'angle_min_rad': float(getattr(fp, 'rotary_angle_min_rad', 0.0) or 0.0),
        'angle_max_rad': float(getattr(fp, 'rotary_angle_max_rad', 0.0) or 0.0),
        'rotary_radius_m': float(rotary_radius_m),
        'generalized_load_scale': float(generalized_load_scale),
        'generalized_inertia': float(generalized_inertia),
        'moving_mass_kg': moving_mass_kg,
        'piston_area_m2': float(fp.piston_area_m2),
        'clearance_volume_m3': float(fp.clearance_volume_m3),
        'bounce_chamber_volume0_m3': float(fp.bounce_chamber_volume0_m3),
        'bounce_area_m2': float(fp.bounce_area_m2),
        'friction_fc_N': float(fp.friction_fc_N),
        'friction_cv_Ns_per_m': float(fp.friction_cv_Ns_per_m),
        'cycle_deg': float(bundle.cycle_deg),
        'cycle_period_s': float(bundle.cycle_period_s),
        'dt_s': float(bundle.simulation.dt_s),
        'load_model_code': int(load_model_code),
        'load_damping_Ns_per_m': float(fp.load_damping_Ns_per_m),
        'load_max_damping_Ns_per_m': float(getattr(fp, 'load_max_damping_Ns_per_m', 0.0) or 0.0),
        'load_control_zone_m': float(getattr(fp, 'load_control_zone_m', 0.0) or 0.0),
        'load_power_target_W': float(getattr(fp, 'load_power_target_W', 0.0) or 0.0),
        'load_efficiency_0to1': float(getattr(fp, 'load_efficiency_0to1', 1.0) or 1.0),
        'load_min_velocity_m_per_s': float(getattr(fp, 'load_min_velocity_m_per_s', 1.0e-12) or 1.0e-12),
        'load_motor_assist_until_soc': 1 if bool(getattr(fp, 'load_motor_assist_until_soc', True)) else 0,
        'load_assist_velocity_threshold_m_per_s': float(getattr(fp, 'load_assist_velocity_threshold_m_per_s', 0.0) or 0.0),
        'load_assist_force_N': float(getattr(fp, 'load_assist_force_N', 0.0) or 0.0),
        'load_target_margin_m': float(getattr(fp, 'load_target_margin_m', 0.0) or 0.0),
        'load_hard_margin_m': float(getattr(fp, 'load_hard_margin_m', 0.0) or 0.0),
        'load_stop_kp': float(getattr(fp, 'load_stop_kp', 0.0) or 0.0),
        'load_max_force_N': float(getattr(fp, 'load_max_force_N', 0.0) or 0.0),
        'uses_vapor_injector': 1 if free_piston_uses_vapor_injector(bundle) else 0,
        'uses_slot_closure_lambda': 1 if free_piston_uses_slot_closure_lambda(bundle) else 0,
        'scavenging_enabled': 1 if bool(getattr(fp, 'scavenging_enabled', False)) and str(getattr(fp, 'scavenging_model', 'overlap_short_circuit_0d')) == 'overlap_short_circuit_0d' else 0,
        'scavenging_factor': float(getattr(fp, 'scavenging_factor', 1.25)),
        'scavenging_max_trapping_efficiency': float(getattr(fp, 'scavenging_max_trapping_efficiency', 0.92)),
        'scavenging_short_circuit_start_ratio': float(getattr(fp, 'scavenging_short_circuit_start_ratio', 0.70)),
        'scavenging_short_circuit_slope': float(getattr(fp, 'scavenging_short_circuit_slope', 0.35)),
        'scavenging_max_short_circuit_fraction': float(getattr(fp, 'scavenging_max_short_circuit_fraction', 0.35)),
        'scavenging_min_residual_fraction': float(getattr(fp, 'scavenging_min_residual_fraction', 0.03)),
    }
    try:
        setattr(bundle, '_free_piston_numba_static_args', cached)
    except Exception:
        pass
    return cached


def _free_piston_runtime_array(fp, name: str, fallback: np.ndarray) -> np.ndarray:
    value = getattr(fp, name, None)
    return fallback if value is None else value


def _free_piston_runtime_arrays(fp, n_vol: int):
    empty_i = EMPTY_INT
    empty_f = EMPTY_FLOAT
    return {
        'runtime_injector_active_by_vol': _free_piston_runtime_array(fp, 'runtime_injector_active_by_vol', empty_i),
        'runtime_injector_time_by_vol_s': _free_piston_runtime_array(fp, 'runtime_injector_time_by_vol_s', empty_f),
        'runtime_injector_end_time_by_vol_s': _free_piston_runtime_array(fp, 'runtime_injector_end_time_by_vol_s', empty_f),
        'runtime_injector_rate_by_vol_kg_per_s': _free_piston_runtime_array(fp, 'runtime_injector_rate_by_vol_kg_per_s', empty_f),
        'runtime_slotclose_charge_active_by_vol': _free_piston_runtime_array(fp, 'runtime_slotclose_charge_active_by_vol', empty_i),
        'runtime_slotclose_charge_time_by_vol_s': _free_piston_runtime_array(fp, 'runtime_slotclose_charge_time_by_vol_s', empty_f),
        'runtime_slotclose_charge_end_time_by_vol_s': _free_piston_runtime_array(fp, 'runtime_slotclose_charge_end_time_by_vol_s', empty_f),
        'runtime_slotclose_charge_rate_by_vol_kg_per_s': _free_piston_runtime_array(fp, 'runtime_slotclose_charge_rate_by_vol_kg_per_s', empty_f),
        'runtime_latch_valid_by_vol': _free_piston_runtime_array(fp, 'runtime_latch_valid_by_vol', empty_i),
        'runtime_latched_energy_by_vol_J': _free_piston_runtime_array(fp, 'runtime_latched_energy_by_vol_J', empty_f),
        'runtime_soc_active_by_vol': _free_piston_runtime_array(fp, 'runtime_soc_active_by_vol', empty_i),
        'runtime_soc_time_by_vol_s': _free_piston_runtime_array(fp, 'runtime_soc_time_by_vol_s', empty_f),
        'runtime_soc_energy_by_vol_J': _free_piston_runtime_array(fp, 'runtime_soc_energy_by_vol_J', empty_f),
        'runtime_cool_flame_active_by_vol': _free_piston_runtime_array(fp, 'runtime_cool_flame_active_by_vol', empty_i),
        'runtime_cool_flame_time_by_vol_s': _free_piston_runtime_array(fp, 'runtime_cool_flame_time_by_vol_s', empty_f),
        'runtime_cool_flame_energy_by_vol_J': _free_piston_runtime_array(fp, 'runtime_cool_flame_energy_by_vol_J', empty_f),
        'runtime_cool_flame_peak_delay_by_vol_s': _free_piston_runtime_array(fp, 'runtime_cool_flame_peak_delay_by_vol_s', empty_f),
        'runtime_cool_flame_qdot_peak_by_vol_W': _free_piston_runtime_array(fp, 'runtime_cool_flame_qdot_peak_by_vol_W', empty_f),
        'runtime_cool_flame_duration_model_by_vol_s': _free_piston_runtime_array(fp, 'runtime_cool_flame_duration_model_by_vol_s', empty_f),
        'hcci_burn_model_by_vol': _free_piston_runtime_array(fp, 'hcci_burn_model_by_vol', empty_i),
        'hcci_cool_flame_a_by_vol': _free_piston_runtime_array(fp, 'hcci_cool_flame_a_by_vol', empty_f),
        'hcci_cool_flame_m_by_vol': _free_piston_runtime_array(fp, 'hcci_cool_flame_m_by_vol', empty_f),
        'hcci_cool_flame_burn_model_by_vol': _free_piston_runtime_array(fp, 'hcci_cool_flame_burn_model_by_vol', empty_i),
        'hcci_cool_flame_duration_by_vol_s': _free_piston_runtime_array(fp, 'hcci_cool_flame_duration_by_vol_s', empty_f),
        'hcci_cool_flame_shape_m_by_vol': _free_piston_runtime_array(fp, 'hcci_cool_flame_shape_m_by_vol', empty_f),
    }


def _update_free_piston_runtime_diagnostics(fp, diag: np.ndarray, scav_diag_by_vol: np.ndarray) -> None:
    if hasattr(fp, 'runtime_combustion_fuel_burn_rate_kg_per_s'):
        fp.runtime_combustion_fuel_burn_rate_kg_per_s = float(diag[0])
        fp.runtime_combustion_air_consumption_rate_kg_per_s = float(diag[1])
        fp.runtime_combustion_burned_production_rate_kg_per_s = float(diag[2])
        fp.runtime_combustion_qdot_W = float(diag[3])
    if hasattr(fp, 'runtime_scavenging_transfer_in_by_vol_kg_per_s') and scav_diag_by_vol.shape[0] <= fp.runtime_scavenging_transfer_in_by_vol_kg_per_s.shape[0]:
        n = int(scav_diag_by_vol.shape[0])
        fp.runtime_scavenging_transfer_in_by_vol_kg_per_s[:n] = scav_diag_by_vol[:, 0]
        fp.runtime_scavenging_exhaust_out_by_vol_kg_per_s[:n] = scav_diag_by_vol[:, 1]
        fp.runtime_scavenging_burned_correction_by_vol_kg_per_s[:n] = scav_diag_by_vol[:, 2]
        fp.runtime_scavenging_short_circuit_fraction_by_vol[:n] = scav_diag_by_vol[:, 3]
        fp.runtime_scavenging_transfer_in_kg_per_s = float(np.sum(scav_diag_by_vol[:, 0]))
        fp.runtime_scavenging_exhaust_out_kg_per_s = float(np.sum(scav_diag_by_vol[:, 1]))
        fp.runtime_scavenging_burned_correction_kg_per_s = float(np.sum(scav_diag_by_vol[:, 2]))
        fp.runtime_scavenging_short_circuit_fraction = float(np.max(scav_diag_by_vol[:, 3])) if n > 0 else 0.0


def compute_free_piston_rhs(t_s: float, y: np.ndarray, bundle) -> np.ndarray:
    fp = bundle.free_piston
    if fp is None:
        raise ValueError('bundle.free_piston must be present for free_piston RHS')
    if bool(getattr(bundle, '_free_piston_numba_disabled', False)):
        return _compute_free_piston_rhs_python(t_s, y, bundle)
    static = _free_piston_static_numba_args(bundle)
    if static is None:
        return _compute_free_piston_rhs_python(t_s, y, bundle)
    n_vol = int(bundle.vol_matrix.shape[0])
    rt = _free_piston_runtime_arrays(fp, n_vol)
    try:
        dy_dt, diag, scav_diag_by_vol = _compute_free_piston_rhs_numba(
            float(t_s),
            np.asarray(y, dtype=np.float64),
            bundle.vol_matrix,
            bundle.conn_matrix,
            bundle.wall_matrix,
            bundle.comb_matrix,
            bundle.evap_matrix,
            bundle.lift_table,
            bundle.alpha_table,
            bundle.cd_table,
            bundle.gas_props,
            bundle.feature_flags,
            static['environment_is_fixed'],
            static['environment_pressures_pa'],
            static['environment_temperatures_K'],
            static['boundary_pressures_pa'],
            static['boundary_temperatures_K'],
            static['wall_bore_by_vol'],
            static['wall_ups_by_vol'],
            1 if bool(getattr(bundle, 'wall_temperature_enabled', False)) else 0,
            static['wall_temperature_state_index_by_vol'],
            static['wall_temperature_params_by_vol'],
            static['combustion_afr_stoich_by_vol'],
            static['combustion_efficiency_by_vol'],
            static['combustion_lhv_by_vol'],
            static['cylinder_indices'],
            static['mechanical_x_indices'],
            static['mechanical_v_indices'],
            static['volume_mechanical_dof'],
            static['volume_mechanical_sign'],
            static['uses_latched_fuel_by_vol'],
            static['use_time_vibe_by_vol'],
            static['x_idx'],
            static['v_idx'],
            static['mechanical_dofs'],
            static['kinematics_mode'],
            static['x_min_m'],
            static['x_max_m'],
            static['angle_min_rad'],
            static['angle_max_rad'],
            static['rotary_radius_m'],
            static['generalized_load_scale'],
            static['generalized_inertia'],
            static['moving_mass_kg'],
            static['piston_area_m2'],
            static['clearance_volume_m3'],
            static['bounce_chamber_volume0_m3'],
            static['bounce_area_m2'],
            static['friction_fc_N'],
            static['friction_cv_Ns_per_m'],
            static['cycle_deg'],
            static['cycle_period_s'],
            static['dt_s'],
            static['load_model_code'],
            static['load_damping_Ns_per_m'],
            static['load_max_damping_Ns_per_m'],
            static['load_control_zone_m'],
            static['load_power_target_W'],
            static['load_efficiency_0to1'],
            static['load_min_velocity_m_per_s'],
            static['load_motor_assist_until_soc'],
            static['load_assist_velocity_threshold_m_per_s'],
            static['load_assist_force_N'],
            static['load_target_margin_m'],
            static['load_hard_margin_m'],
            static['load_stop_kp'],
            static['load_max_force_N'],
            static['uses_vapor_injector'],
            static['uses_slot_closure_lambda'],
            float(getattr(fp, 'runtime_soc_energy_J', 0.0) or 0.0),
            1 if bool(getattr(fp, 'runtime_soc_active', False)) else 0,
            float(getattr(fp, 'runtime_soc_time_s', 0.0) or 0.0),
            float(getattr(fp, 'runtime_latched_energy_J', 0.0) or 0.0),
            1 if bool(getattr(fp, 'runtime_latch_valid', False)) else 0,
            1 if bool(getattr(fp, 'runtime_injector_active', False)) else 0,
            float(getattr(fp, 'runtime_injector_time_s', 0.0) or 0.0),
            float(getattr(fp, 'runtime_injector_end_time_s', 0.0) or 0.0),
            float(getattr(fp, 'runtime_injector_rate_kg_per_s', 0.0) or 0.0),
            rt['runtime_injector_active_by_vol'],
            rt['runtime_injector_time_by_vol_s'],
            rt['runtime_injector_end_time_by_vol_s'],
            rt['runtime_injector_rate_by_vol_kg_per_s'],
            1 if bool(getattr(fp, 'runtime_slotclose_charge_active', False)) else 0,
            float(getattr(fp, 'runtime_slotclose_charge_time_s', 0.0) or 0.0),
            float(getattr(fp, 'runtime_slotclose_charge_end_time_s', 0.0) or 0.0),
            float(getattr(fp, 'runtime_slotclose_charge_rate_kg_per_s', 0.0) or 0.0),
            rt['runtime_slotclose_charge_active_by_vol'],
            rt['runtime_slotclose_charge_time_by_vol_s'],
            rt['runtime_slotclose_charge_end_time_by_vol_s'],
            rt['runtime_slotclose_charge_rate_by_vol_kg_per_s'],
            rt['runtime_latch_valid_by_vol'],
            rt['runtime_latched_energy_by_vol_J'],
            rt['runtime_soc_active_by_vol'],
            rt['runtime_soc_time_by_vol_s'],
            rt['runtime_soc_energy_by_vol_J'],
            rt['runtime_cool_flame_active_by_vol'],
            rt['runtime_cool_flame_time_by_vol_s'],
            rt['runtime_cool_flame_energy_by_vol_J'],
            rt['runtime_cool_flame_peak_delay_by_vol_s'],
            rt['runtime_cool_flame_qdot_peak_by_vol_W'],
            rt['runtime_cool_flame_duration_model_by_vol_s'],
            rt['hcci_burn_model_by_vol'],
            rt['hcci_cool_flame_a_by_vol'],
            rt['hcci_cool_flame_m_by_vol'],
            rt['hcci_cool_flame_burn_model_by_vol'],
            rt['hcci_cool_flame_duration_by_vol_s'],
            rt['hcci_cool_flame_shape_m_by_vol'],
            static['scavenging_enabled'],
            static['scavenging_factor'],
            static['scavenging_max_trapping_efficiency'],
            static['scavenging_short_circuit_start_ratio'],
            static['scavenging_short_circuit_slope'],
            static['scavenging_max_short_circuit_fraction'],
            static['scavenging_min_residual_fraction'],
        )
        _update_free_piston_runtime_diagnostics(fp, diag, scav_diag_by_vol)
        return dy_dt
    except Exception as exc:
        try:
            setattr(bundle, '_free_piston_numba_disabled', True)
            setattr(bundle, '_free_piston_numba_last_error', repr(exc))
        except Exception:
            pass
        return _compute_free_piston_rhs_python(t_s, y, bundle)
