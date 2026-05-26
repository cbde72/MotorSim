from __future__ import annotations

import math

import numpy as np

from thermo0d.config.constants import AngleReference, CombCol, CombDurationMode, ConnectionType, FeatureCol, VolumeCol, VolumeType
from thermo0d.model.free_piston.forces import compute_load_info
from thermo0d.model.free_piston.geometry import bounce_volume_from_position, cylinder_distance_from_tdc, cylinder_dvdt_from_velocity, cylinder_volume_from_position, free_piston_equivalent_linear_kinematics, free_piston_local_cycle_angle_deg, free_piston_local_cycle_angle_rate_deg_s, free_piston_reference_is_active
from thermo0d.model.free_piston.thermo import pressure_from_state, temperature_from_state
from thermo0d.model.free_piston.combustion_latch import free_piston_cylinder_uses_latched_fuel, free_piston_uses_slot_closure_lambda, free_piston_uses_vapor_injector
from thermo0d.physics.flow import de_st_venant_wantzel_signed
from thermo0d.physics.combustion import combustion_duration_mode_from_row, vibe_beck_time_fraction_and_rate, vibe_beck_time_heat_release_rate_with_total_energy, vibe_fraction_and_rate, vibe_heat_release_rate_with_total_energy, vibe_time_fraction_and_rate, vibe_time_heat_release_rate_with_total_energy
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


def _apply_overlap_scavenging_correction(
    dy_dt: np.ndarray,
    fp,
    cylinder_idx: int,
    y: np.ndarray,
    mass_indices: np.ndarray,
    burned_indices: np.ndarray,
    air_indices: np.ndarray,
    environment_is_fixed: np.ndarray,
    transfer_in_rate_kg_per_s: float,
    transfer_air_in_rate_kg_per_s: float,
    exhaust_out_by_vol_kg_per_s: np.ndarray,
) -> None:
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


def compute_free_piston_rhs(t_s: float, y: np.ndarray, bundle) -> np.ndarray:
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
    runtime_injector_active_by_vol = getattr(fp, 'runtime_injector_active_by_vol', np.zeros(0, dtype=np.int64))
    runtime_injector_time_by_vol_s = getattr(fp, 'runtime_injector_time_by_vol_s', np.zeros(0, dtype=np.float64))
    runtime_injector_end_time_by_vol_s = getattr(fp, 'runtime_injector_end_time_by_vol_s', np.zeros(0, dtype=np.float64))
    runtime_injector_rate_by_vol_kg_per_s = getattr(fp, 'runtime_injector_rate_by_vol_kg_per_s', np.zeros(0, dtype=np.float64))
    runtime_slotclose_charge_active = fp.runtime_slotclose_charge_active if hasattr(fp, 'runtime_slotclose_charge_active') else False
    runtime_slotclose_charge_time_s = fp.runtime_slotclose_charge_time_s if hasattr(fp, 'runtime_slotclose_charge_time_s') else 0.0
    runtime_slotclose_charge_end_time_s = fp.runtime_slotclose_charge_end_time_s if hasattr(fp, 'runtime_slotclose_charge_end_time_s') else 0.0
    runtime_slotclose_charge_rate_kg_per_s = fp.runtime_slotclose_charge_rate_kg_per_s if hasattr(fp, 'runtime_slotclose_charge_rate_kg_per_s') else 0.0
    runtime_latch_valid_by_vol = getattr(fp, 'runtime_latch_valid_by_vol', np.zeros(0, dtype=np.int64))
    runtime_latched_energy_by_vol_J = getattr(fp, 'runtime_latched_energy_by_vol_J', np.zeros(0, dtype=np.float64))
    runtime_soc_active_by_vol = getattr(fp, 'runtime_soc_active_by_vol', np.zeros(0, dtype=np.int64))
    runtime_soc_time_by_vol_s = getattr(fp, 'runtime_soc_time_by_vol_s', np.zeros(0, dtype=np.float64))
    runtime_soc_energy_by_vol_J = getattr(fp, 'runtime_soc_energy_by_vol_J', np.zeros(0, dtype=np.float64))
    runtime_cool_flame_active_by_vol = getattr(fp, 'runtime_cool_flame_active_by_vol', np.zeros(0, dtype=np.int64))
    runtime_cool_flame_time_by_vol_s = getattr(fp, 'runtime_cool_flame_time_by_vol_s', np.zeros(0, dtype=np.float64))
    runtime_cool_flame_energy_by_vol_J = getattr(fp, 'runtime_cool_flame_energy_by_vol_J', np.zeros(0, dtype=np.float64))
    hcci_burn_model_by_vol = getattr(fp, 'hcci_burn_model_by_vol', np.zeros(0, dtype=np.int64))
    runtime_slotclose_charge_active_by_vol = getattr(fp, 'runtime_slotclose_charge_active_by_vol', np.zeros(0, dtype=np.int64))
    runtime_slotclose_charge_time_by_vol_s = getattr(fp, 'runtime_slotclose_charge_time_by_vol_s', np.zeros(0, dtype=np.float64))
    runtime_slotclose_charge_end_time_by_vol_s = getattr(fp, 'runtime_slotclose_charge_end_time_by_vol_s', np.zeros(0, dtype=np.float64))
    runtime_slotclose_charge_rate_by_vol_kg_per_s = getattr(fp, 'runtime_slotclose_charge_rate_by_vol_kg_per_s', np.zeros(0, dtype=np.float64))
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
    mass_indices = np.array([int(bundle.state_layout.mass_index(i)) for i in range(n_vol)], dtype=np.int32)
    energy_indices = np.array([int(bundle.state_layout.energy_index(i)) for i in range(n_vol)], dtype=np.int32)
    burned_indices = np.array([int(bundle.state_layout.burned_mass_index(i)) for i in range(n_vol)], dtype=np.int32)
    air_indices = np.array([int(bundle.state_layout.air_mass_index(i)) for i in range(n_vol)], dtype=np.int32)
    liquid_indices = np.array([int(bundle.state_layout.liquid_fuel_mass_index(i)) for i in range(n_vol)], dtype=np.int32)

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
            left = int(conn[1])
            right = int(conn[2])
            conn_type = int(conn[0])

            cyl_idx = -1
            if int(bundle.vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER:
                cyl_idx = left
            elif int(bundle.vol_matrix[right, VolumeCol.TYPE]) == VolumeType.CYLINDER:
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
                pressures[left],
                pressures[right],
            )
            if area <= 1.0e-18 or (cd_f <= 0.0 and cd_r <= 0.0):
                continue

            if pressures[left] >= pressures[right]:
                gamma_up = kappa_by_vol[left]
                gas_constant_up = gas_constant_by_vol[left]
                cp_up = cp_by_vol[left]
                temp_up = temperatures[left]
            else:
                gamma_up = kappa_by_vol[right]
                gas_constant_up = gas_constant_by_vol[right]
                cp_up = cp_by_vol[right]
                temp_up = temperatures[right]
            mdot = de_st_venant_wantzel_signed(
                pressures[left],
                temperatures[left],
                pressures[right],
                temperatures[right],
                area,
                cd_f,
                cd_r,
                gamma_up,
                gas_constant_up,
            )
            h_up = cp_up * temp_up

            if int(environment_is_fixed[left]) != 1:
                dy_dt[mass_indices[left]] -= mdot
                dy_dt[energy_indices[left]] -= mdot * h_up
            if int(environment_is_fixed[right]) != 1:
                dy_dt[mass_indices[right]] += mdot
                dy_dt[energy_indices[right]] += mdot * h_up

            if mdot >= 0.0:
                upstream_burned_fraction, upstream_air_fraction = _upstream_species_fractions(bundle.state_layout, y, left, environment_is_fixed)
                burned_transfer = mdot * upstream_burned_fraction
                air_transfer = mdot * upstream_air_fraction
                if int(environment_is_fixed[left]) != 1:
                    dy_dt[burned_indices[left]] -= burned_transfer
                    dy_dt[air_indices[left]] -= air_transfer
                if int(environment_is_fixed[right]) != 1:
                    dy_dt[burned_indices[right]] += burned_transfer
                    dy_dt[air_indices[right]] += air_transfer
                if conn_type == int(ConnectionType.SLOT):
                    if right in cylinder_index_set and left != right:
                        scav_transfer_in_by_cyl_kg_per_s[right] += float(mdot)
                        scav_transfer_air_in_by_cyl_kg_per_s[right] += float(air_transfer)
                    elif left in cylinder_index_set and right != left:
                        scav_exhaust_out_by_cyl_to_vol_kg_per_s[left, right] += float(mdot)
            else:
                upstream_burned_fraction, upstream_air_fraction = _upstream_species_fractions(bundle.state_layout, y, right, environment_is_fixed)
                burned_transfer = (-mdot) * upstream_burned_fraction
                air_transfer = (-mdot) * upstream_air_fraction
                if int(environment_is_fixed[left]) != 1:
                    dy_dt[burned_indices[left]] += burned_transfer
                    dy_dt[air_indices[left]] += air_transfer
                if int(environment_is_fixed[right]) != 1:
                    dy_dt[burned_indices[right]] -= burned_transfer
                    dy_dt[air_indices[right]] -= air_transfer
                if conn_type == int(ConnectionType.SLOT):
                    if left in cylinder_index_set and right != left:
                        scav_transfer_in_by_cyl_kg_per_s[left] += float(-mdot)
                        scav_transfer_air_in_by_cyl_kg_per_s[left] += float(air_transfer)
                    elif right in cylinder_index_set and left != right:
                        scav_exhaust_out_by_cyl_to_vol_kg_per_s[right, left] += float(-mdot)

            if int(bundle.vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER and mdot < 0.0:
                mdot_in_by_vol[left] += -mdot
            if int(bundle.vol_matrix[right, VolumeCol.TYPE]) == VolumeType.CYLINDER and mdot > 0.0:
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
        pdv_power, qdot_wall, _htc_wall, _wall_velocity, qdot_comb, qdot_evap = volume_energy_source_terms(
            vol_type,
            int(vol_row[VolumeCol.WALL_ROW]),
            comb_idx,
            int(vol_row[VolumeCol.EVAP_ROW]),
            1 if bundle.feature_flags.size > F_WALL and int(bundle.feature_flags[F_WALL]) == 1 else 0,
            0 if (use_latched_fuel_combustion or use_time_vibe) else comb_enabled,
            1 if bundle.feature_flags.size > F_EVAP and int(bundle.feature_flags[F_EVAP]) == 1 else 0,
            1 if bundle.feature_flags.size > F_PV and int(bundle.feature_flags[F_PV]) == 1 else 0,
            bundle.wall_matrix,
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
                if use_vibe_beck:
                    qdot_comb += vibe_beck_time_heat_release_rate_with_total_energy(
                        t_s,
                        float(runtime_cool_flame_time_by_vol_s[i]),
                        float(fp.hcci_cool_flame_duration_by_vol_s[i]),
                        float(fp.hcci_cool_flame_a_by_vol[i]),
                        float(fp.hcci_cool_flame_m_by_vol[i]),
                        float(runtime_cool_flame_energy_by_vol_J[i]),
                    )
                else:
                    qdot_comb += vibe_time_heat_release_rate_with_total_energy(
                        t_s,
                        float(runtime_cool_flame_time_by_vol_s[i]),
                        float(fp.hcci_cool_flame_duration_by_vol_s[i]),
                        float(fp.hcci_cool_flame_a_by_vol[i]),
                        float(fp.hcci_cool_flame_m_by_vol[i]),
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
            assist_velocity_threshold_m_per_s=fp.load_assist_velocity_threshold_m_per_s,
            assist_force_N=fp.load_assist_force_N,
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
