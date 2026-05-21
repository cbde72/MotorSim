from __future__ import annotations

import numpy as np

from thermo0d.config.constants import CombCol, CombDurationMode, CombStartMode, ConnCol, ConnectionType, FeatureCol, VolumeCol
from thermo0d.model.free_piston.geometry import cylinder_distance_from_tdc, cylinder_volume_from_position, free_piston_is_compression_stroke, free_piston_local_cycle_angle_deg
from thermo0d.model.free_piston.thermo import pressure_from_state
from thermo0d.physics.kinematics import reference_theta_and_zero, wrap_angle_deg
from thermo0d.physics.openings import connection_area_and_coefficients
from thermo0d.physics.composition import unburned_mass_kg
from thermo0d.physics.quellen_props import lambda_from_air_and_fuel_mass, properties_from_mass_energy_components_quellen


F_COMB = int(FeatureCol.COMBUSTION)


def free_piston_combustion_enabled(bundle) -> bool:
    feature_flags = getattr(bundle, 'feature_flags', None)
    return bool(feature_flags is not None and feature_flags.size > F_COMB and int(feature_flags[F_COMB]) == 1)


def free_piston_uses_slot_closure_lambda(bundle) -> bool:
    if not free_piston_combustion_enabled(bundle):
        return False
    fp = getattr(bundle, 'free_piston', None)
    return fp is not None and str(getattr(fp, 'combustion_fueling_mode', 'fixed_energy')) == 'lambda_from_cylinder_mass_at_slot_close' and int(getattr(fp, 'combustion_comb_idx', -1)) >= 0


def free_piston_uses_vapor_injector(bundle) -> bool:
    if not free_piston_combustion_enabled(bundle):
        return False
    fp = getattr(bundle, 'free_piston', None)
    return fp is not None and str(getattr(fp, 'combustion_fueling_mode', 'fixed_energy')) == 'lambda_from_cylinder_air_at_slot_close_vapor_injector' and int(getattr(fp, 'combustion_comb_idx', -1)) >= 0


def free_piston_uses_hcci_diesel(bundle) -> bool:
    if not free_piston_combustion_enabled(bundle):
        return False
    fp = getattr(bundle, 'free_piston', None)
    enabled = getattr(fp, 'hcci_enabled_by_vol', np.zeros(0, dtype=np.int64)) if fp is not None else np.zeros(0, dtype=np.int64)
    return fp is not None and int(getattr(enabled, 'shape', (0,))[0]) > 0 and bool(np.any(enabled))


def _ensure_runtime_arrays(bundle) -> None:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return
    n_vol = int(bundle.vol_matrix.shape[0])
    int_names = (
        'runtime_slots_were_open_by_vol',
        'runtime_latch_valid_by_vol',
        'runtime_time_combustion_initialized_by_vol',
        'runtime_time_combustion_armed_by_vol',
        'runtime_soc_active_by_vol',
        'runtime_slotclose_charge_active_by_vol',
    )
    float_names = (
        'runtime_latched_cylinder_mass_by_vol_kg',
        'runtime_latched_fuel_mass_by_vol_kg',
        'runtime_latched_energy_by_vol_J',
        'runtime_last_slot_area_by_vol_m2',
        'runtime_soc_time_by_vol_s',
        'runtime_soc_end_time_by_vol_s',
        'runtime_soc_energy_by_vol_J',
        'runtime_slotclose_charge_time_by_vol_s',
        'runtime_slotclose_charge_end_time_by_vol_s',
        'runtime_slotclose_charge_rate_by_vol_kg_per_s',
        'runtime_slotclose_charge_target_fuel_by_vol_kg',
        'runtime_hcci_integral_by_vol',
        'runtime_hcci_last_update_time_by_vol_s',
        'runtime_hcci_tau_by_vol_s',
    )
    for name in int_names:
        arr = getattr(fp, name)
        if int(getattr(arr, 'shape', (0,))[0]) != n_vol:
            setattr(fp, name, np.zeros(n_vol, dtype=np.int64))
    for name in float_names:
        arr = getattr(fp, name)
        if int(getattr(arr, 'shape', (0,))[0]) != n_vol:
            setattr(fp, name, np.zeros(n_vol, dtype=np.float64))


def _comb_idx_for_cylinder(bundle, cylinder_idx: int) -> int:
    idx = int(cylinder_idx)
    if idx < 0 or idx >= int(bundle.vol_matrix.shape[0]):
        return -1
    return int(bundle.vol_matrix[idx, VolumeCol.COMB_ROW])


def _comb_row_for_cylinder(bundle, cylinder_idx: int):
    comb_idx = _comb_idx_for_cylinder(bundle, cylinder_idx)
    if comb_idx < 0:
        return None
    return bundle.comb_matrix[comb_idx]


def _local_piston_kinematics_for_volume(bundle, y_state: np.ndarray, volume_idx: int) -> tuple[float, float]:
    fp = bundle.free_piston
    dof_by_vol = getattr(fp, 'volume_mechanical_dof', np.zeros(0, dtype=np.int64))
    sign_by_vol = getattr(fp, 'volume_mechanical_sign', np.zeros(0, dtype=np.float64))
    mech_x = getattr(fp, 'mechanical_x_state_indices', np.array([fp.x_state_index], dtype=np.int64))
    mech_v = getattr(fp, 'mechanical_v_state_indices', np.array([fp.v_state_index], dtype=np.int64))
    vol_idx = int(volume_idx)
    dof = int(dof_by_vol[vol_idx]) if vol_idx < int(dof_by_vol.shape[0]) else 0
    sign = float(sign_by_vol[vol_idx]) if vol_idx < int(sign_by_vol.shape[0]) else 1.0
    if dof < 0:
        q_m = float(y_state[int(fp.x_state_index)])
        q_v_m_per_s = float(y_state[int(fp.v_state_index)])
    else:
        q_m = float(y_state[int(mech_x[dof])])
        q_v_m_per_s = float(y_state[int(mech_v[dof])])
    if sign < 0.0:
        return float(fp.x_min_m + fp.x_max_m - q_m), float(-q_v_m_per_s)
    return float(q_m), float(q_v_m_per_s)


def _arm_vapor_injector(fp, t_s: float, fuel_mass_kg: float) -> None:
    duration_s = float(getattr(fp, 'injector_duration_s', 0.0) or 0.0)
    if duration_s <= 0.0 or fuel_mass_kg <= 0.0:
        fp.runtime_injector_active = False
        fp.runtime_injector_time_s = float(t_s)
        fp.runtime_injector_end_time_s = float(t_s)
        fp.runtime_injector_target_fuel_mass_kg = 0.0
        fp.runtime_injector_injected_mass_kg = 0.0
        fp.runtime_injector_rate_kg_per_s = 0.0
        return
    fp.runtime_injector_active = True
    fp.runtime_injector_time_s = float(t_s)
    fp.runtime_injector_end_time_s = float(t_s + duration_s)
    fp.runtime_injector_target_fuel_mass_kg = float(fuel_mass_kg)
    fp.runtime_injector_injected_mass_kg = 0.0
    fp.runtime_injector_rate_kg_per_s = float(fuel_mass_kg / duration_s)


def _update_vapor_injector_state(fp, t_s: float) -> None:
    if not bool(getattr(fp, 'runtime_injector_active', False)):
        return
    if float(t_s) >= float(getattr(fp, 'runtime_injector_end_time_s', 0.0)) - 1.0e-15:
        fp.runtime_injector_active = False


def _arm_slotclose_charge(fp, t_s: float, fuel_mass_kg: float, duration_s: float) -> None:
    duration_s = float(duration_s)
    if duration_s <= 0.0 or fuel_mass_kg <= 0.0:
        fp.runtime_slotclose_charge_active = False
        fp.runtime_slotclose_charge_time_s = float(t_s)
        fp.runtime_slotclose_charge_end_time_s = float(t_s)
        fp.runtime_slotclose_charge_target_fuel_mass_kg = 0.0
        fp.runtime_slotclose_charge_rate_kg_per_s = 0.0
        return
    fp.runtime_slotclose_charge_active = True
    fp.runtime_slotclose_charge_time_s = float(t_s)
    fp.runtime_slotclose_charge_end_time_s = float(t_s + duration_s)
    fp.runtime_slotclose_charge_target_fuel_mass_kg = float(fuel_mass_kg)
    fp.runtime_slotclose_charge_rate_kg_per_s = float(fuel_mass_kg / duration_s)


def _update_slotclose_charge_state(fp, t_s: float) -> None:
    if not bool(getattr(fp, 'runtime_slotclose_charge_active', False)):
        return
    if float(t_s) >= float(getattr(fp, 'runtime_slotclose_charge_end_time_s', 0.0)) - 1.0e-15:
        fp.runtime_slotclose_charge_active = False


def _comb_duration_mode(bundle, cylinder_idx: int | None = None) -> int:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return int(CombDurationMode.ANGLE)
    if cylinder_idx is None:
        comb_idx = int(getattr(fp, 'combustion_comb_idx', -1))
        if comb_idx < 0:
            return int(CombDurationMode.ANGLE)
        comb_row = bundle.comb_matrix[comb_idx]
    else:
        comb_row = _comb_row_for_cylinder(bundle, int(cylinder_idx))
        if comb_row is None:
            return int(CombDurationMode.ANGLE)
    if comb_row.shape[0] <= int(CombCol.DURATION_MODE):
        return int(CombDurationMode.ANGLE)
    return int(comb_row[int(CombCol.DURATION_MODE)])


def _comb_start_mode(bundle, cylinder_idx: int | None = None) -> int:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return int(CombStartMode.ANGLE)
    if cylinder_idx is None:
        comb_idx = int(getattr(fp, 'combustion_comb_idx', -1))
        if comb_idx < 0:
            return int(CombStartMode.ANGLE)
        comb_row = bundle.comb_matrix[comb_idx]
    else:
        comb_row = _comb_row_for_cylinder(bundle, int(cylinder_idx))
        if comb_row is None:
            return int(CombStartMode.ANGLE)
    if comb_row.shape[0] <= int(CombCol.START_MODE):
        return int(CombStartMode.ANGLE)
    mode = int(comb_row[int(CombCol.START_MODE)])
    if mode in (int(CombStartMode.COMPRESSION_HUB), int(CombStartMode.HIGN_POSITION), int(CombStartMode.AUTOIGNITION)):
        return mode
    return int(CombStartMode.ANGLE)


def free_piston_uses_time_vibe(bundle) -> bool:
    if not free_piston_combustion_enabled(bundle):
        return False
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return False
    for cyl_idx in getattr(bundle, 'cylinder_indices', []):
        if _comb_idx_for_cylinder(bundle, int(cyl_idx)) >= 0 and _comb_duration_mode(bundle, int(cyl_idx)) == int(CombDurationMode.TIME):
            return True
    return int(getattr(fp, 'combustion_comb_idx', -1)) >= 0 and _comb_duration_mode(bundle) == int(CombDurationMode.TIME)


def _free_piston_theta_window_deg(bundle, t_s: float, x_m: float, v_m_per_s: float, cylinder_idx: int | None = None) -> float:
    fp = bundle.free_piston
    if cylinder_idx is None:
        comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    else:
        comb_row = _comb_row_for_cylinder(bundle, int(cylinder_idx))
        if comb_row is None:
            return 0.0
    cycle_deg = float(bundle.cycle_deg)
    dtheta_dt_global = float(cycle_deg / bundle.cycle_period_s) if float(bundle.cycle_period_s) > 1.0e-18 else 0.0
    theta_global_deg = (float(t_s) * dtheta_dt_global) % cycle_deg if cycle_deg > 1.0e-18 else 0.0
    theta_local_deg = free_piston_local_cycle_angle_deg(float(x_m), float(v_m_per_s), fp.x_min_m, fp.x_max_m, cycle_deg)
    theta_ref_deg, ref_zero_deg = reference_theta_and_zero(theta_local_deg, theta_global_deg, cycle_deg, int(comb_row[int(CombCol.REF_TYPE)]))
    return float(wrap_angle_deg(theta_ref_deg - ref_zero_deg, cycle_deg))


def _time_mode_duration_s(bundle, cylinder_idx: int | None = None) -> float:
    fp = bundle.free_piston
    if fp is None:
        return 0.0
    if cylinder_idx is None:
        if int(getattr(fp, 'combustion_comb_idx', -1)) < 0:
            return 0.0
        comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    else:
        comb_row = _comb_row_for_cylinder(bundle, int(cylinder_idx))
        if comb_row is None:
            return 0.0
    return float(comb_row[int(CombCol.DURATION_DEG)])


def _current_combustion_energy_J(bundle, cylinder_idx: int | None = None) -> float:
    fp = bundle.free_piston
    if fp is None:
        return 0.0
    if free_piston_uses_slot_closure_lambda(bundle):
        if cylinder_idx is not None:
            _ensure_runtime_arrays(bundle)
            idx = int(cylinder_idx)
            return float(fp.runtime_latched_energy_by_vol_J[idx]) if bool(fp.runtime_latch_valid_by_vol[idx]) else 0.0
        return float(fp.runtime_latched_energy_J) if bool(fp.runtime_latch_valid) else 0.0
    if cylinder_idx is None:
        if int(getattr(fp, 'combustion_comb_idx', -1)) < 0:
            return 0.0
        comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    else:
        comb_row = _comb_row_for_cylinder(bundle, int(cylinder_idx))
        if comb_row is None:
            return 0.0
    return float(comb_row[int(CombCol.FUEL_MASS_PER_CYCLE)] * comb_row[int(CombCol.LHV)])


def _bootstrap_time_combustion_state(bundle) -> None:
    if not free_piston_uses_time_vibe(bundle):
        return
    fp = bundle.free_piston
    _ensure_runtime_arrays(bundle)
    y0 = bundle.y_init
    fp.runtime_time_combustion_initialized = True
    for cyl_idx in getattr(bundle, 'cylinder_indices', []):
        cyl = int(cyl_idx)
        comb_row = _comb_row_for_cylinder(bundle, cyl)
        if comb_row is None or _comb_duration_mode(bundle, cyl) != int(CombDurationMode.TIME):
            continue
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y0, cyl)
        start_mode = _comb_start_mode(bundle, cyl)
        if start_mode == int(CombStartMode.AUTOIGNITION):
            fp.runtime_time_combustion_initialized_by_vol[cyl] = 1
            fp.runtime_time_combustion_armed_by_vol[cyl] = 0
            continue
        start_value = float(comb_row[int(CombCol.START_DEG)])
        fp.runtime_time_combustion_initialized_by_vol[cyl] = 1
        if start_mode == int(CombStartMode.HIGN_POSITION):
            distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
            armed = bool(distance_from_tdc_m > start_value)
        else:
            theta_window_deg = _free_piston_theta_window_deg(bundle, 0.0, x_m, v_m_per_s, cyl)
            armed = bool(theta_window_deg < start_value)
        fp.runtime_time_combustion_armed_by_vol[cyl] = 1 if armed else 0
    fp.runtime_soc_active = False
    fp.runtime_soc_time_s = 0.0
    fp.runtime_soc_end_time_s = 0.0
    fp.runtime_soc_energy_J = 0.0


def _update_time_combustion_state(bundle, t_s: float, y_state: np.ndarray) -> None:
    if not free_piston_uses_time_vibe(bundle):
        return
    fp = bundle.free_piston
    _ensure_runtime_arrays(bundle)
    for cyl_idx in getattr(bundle, 'cylinder_indices', []):
        cyl = int(cyl_idx)
        comb_row = _comb_row_for_cylinder(bundle, cyl)
        if comb_row is None or _comb_duration_mode(bundle, cyl) != int(CombDurationMode.TIME):
            continue
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y_state, cyl)
        start_mode = _comb_start_mode(bundle, cyl)
        if start_mode == int(CombStartMode.AUTOIGNITION):
            continue
        start_value = float(comb_row[int(CombCol.START_DEG)])
        duration_s = _time_mode_duration_s(bundle, cyl)
        if not bool(fp.runtime_time_combustion_initialized_by_vol[cyl]):
            fp.runtime_time_combustion_initialized_by_vol[cyl] = 1
            if start_mode == int(CombStartMode.HIGN_POSITION):
                distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
                armed = bool(distance_from_tdc_m > start_value)
            else:
                theta_window_deg = _free_piston_theta_window_deg(bundle, t_s, x_m, v_m_per_s, cyl)
                armed = bool(theta_window_deg < start_value)
            fp.runtime_time_combustion_armed_by_vol[cyl] = 1 if armed else 0
        if bool(fp.runtime_soc_active_by_vol[cyl]) and float(t_s) >= float(fp.runtime_soc_end_time_by_vol_s[cyl]) - 1.0e-15:
            fp.runtime_soc_active_by_vol[cyl] = 0
            if cyl == int(bundle.cylinder_indices[0]):
                fp.runtime_soc_active = False

        trigger_reached = False
        if start_mode == int(CombStartMode.HIGN_POSITION):
            distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
            if (not bool(fp.runtime_time_combustion_armed_by_vol[cyl])) and distance_from_tdc_m > start_value:
                fp.runtime_time_combustion_armed_by_vol[cyl] = 1
            trigger_reached = bool(fp.runtime_time_combustion_armed_by_vol[cyl]) and free_piston_is_compression_stroke(v_m_per_s, x_m, fp.x_min_m, fp.x_max_m) and distance_from_tdc_m <= start_value
        else:
            theta_window_deg = _free_piston_theta_window_deg(bundle, t_s, x_m, v_m_per_s, cyl)
            if (not bool(fp.runtime_time_combustion_armed_by_vol[cyl])) and theta_window_deg < start_value:
                fp.runtime_time_combustion_armed_by_vol[cyl] = 1
            trigger_reached = bool(fp.runtime_time_combustion_armed_by_vol[cyl]) and theta_window_deg >= start_value

        q_total_J = _current_combustion_energy_J(bundle, cyl)
        if (
            not bool(fp.runtime_soc_active_by_vol[cyl])
            and trigger_reached
            and q_total_J > 0.0
            and duration_s > 0.0
        ):
            fp.runtime_soc_active_by_vol[cyl] = 1
            fp.runtime_soc_time_by_vol_s[cyl] = float(t_s)
            fp.runtime_soc_end_time_by_vol_s[cyl] = float(t_s + duration_s)
            fp.runtime_soc_energy_by_vol_J[cyl] = float(q_total_J)
            fp.runtime_time_combustion_armed_by_vol[cyl] = 0
            if cyl == int(bundle.cylinder_indices[0]):
                fp.runtime_soc_active = True
                fp.runtime_soc_time_s = float(t_s)
                fp.runtime_soc_end_time_s = float(t_s + duration_s)
                fp.runtime_soc_energy_J = float(q_total_J)


def _update_hcci_diesel_autoignition_state(bundle, t_s: float, y_state: np.ndarray) -> None:
    if not free_piston_uses_hcci_diesel(bundle):
        return
    fp = bundle.free_piston
    _ensure_runtime_arrays(bundle)
    cv_default = float(bundle.gas_props[1])
    use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5
    for cyl_idx in getattr(bundle, 'cylinder_indices', []):
        cyl = int(cyl_idx)
        if cyl >= int(getattr(fp.hcci_enabled_by_vol, 'shape', (0,))[0]) or not bool(fp.hcci_enabled_by_vol[cyl]):
            continue
        comb_row = _comb_row_for_cylinder(bundle, cyl)
        if comb_row is None or _comb_duration_mode(bundle, cyl) != int(CombDurationMode.TIME):
            continue
        if bool(fp.runtime_soc_active_by_vol[cyl]) and float(t_s) >= float(fp.runtime_soc_end_time_by_vol_s[cyl]) - 1.0e-15:
            fp.runtime_soc_active_by_vol[cyl] = 0
            if cyl == int(bundle.cylinder_indices[0]):
                fp.runtime_soc_active = False

        last_t = float(fp.runtime_hcci_last_update_time_by_vol_s[cyl])
        dt_s = max(0.0, float(t_s) - last_t)
        fp.runtime_hcci_last_update_time_by_vol_s[cyl] = float(t_s)
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y_state, cyl)
        if not free_piston_is_compression_stroke(v_m_per_s, x_m, fp.x_min_m, fp.x_max_m):
            fp.runtime_hcci_integral_by_vol[cyl] = 0.0
            continue

        q_total_J = _current_combustion_energy_J(bundle, cyl)
        if q_total_J <= 0.0 or bool(fp.runtime_soc_active_by_vol[cyl]):
            continue

        mass = float(bundle.state_layout.gas_mass_from_state(y_state, cyl))
        energy = float(y_state[int(bundle.state_layout.energy_index(cyl))])
        air_mass = float(bundle.state_layout.air_mass_from_state(y_state, cyl))
        burned_mass = float(bundle.state_layout.burned_mass_from_state(y_state, cyl))
        fuel_mass = float(fp.runtime_latched_fuel_mass_by_vol_kg[cyl]) if bool(fp.runtime_latch_valid_by_vol[cyl]) else float(bundle.state_layout.fuel_vapor_mass_from_state(y_state, cyl))
        if mass <= 1.0e-18 or air_mass <= 1.0e-18 or fuel_mass <= 1.0e-18:
            continue

        volume = cylinder_volume_from_position(fp.clearance_volume_m3, fp.piston_area_m2, x_m, fp.x_min_m, fp.x_max_m)
        if use_promo_thermo:
            fuel_vapor_mass = float(bundle.state_layout.fuel_vapor_mass_from_state(y_state, cyl))
            temp_K, _cp, cv_i, gas_constant_i, _kappa = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
            pressure_Pa = pressure_from_state(mass, energy, volume, gas_constant_i, cv_i)
        else:
            temp_K = max(energy / max(mass * cv_default, 1.0e-18), 1.0)
            pressure_Pa = pressure_from_state(mass, energy, volume, float(bundle.gas_props[2]), cv_default)

        if temp_K < float(fp.hcci_start_temperature_min_by_vol_K[cyl]) or pressure_Pa < float(fp.hcci_start_pressure_min_by_vol_Pa[cyl]):
            continue

        afr = float(getattr(fp, 'combustion_afr_stoich_kg_air_per_kg_fuel', 14.5) or 14.5)
        if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and cyl < int(bundle.combustion_afr_stoich_by_vol.shape[0]):
            afr = float(bundle.combustion_afr_stoich_by_vol[cyl])
        lam = lambda_from_air_and_fuel_mass(air_mass, fuel_mass, afr)
        pressure_factor = (max(float(fp.hcci_reference_pressure_by_vol_Pa[cyl]), 1.0) / max(pressure_Pa, 1.0)) ** float(fp.hcci_pressure_exponent_by_vol[cyl])
        temp_factor = float(np.exp(float(fp.hcci_activation_temperature_by_vol_K[cyl]) / max(temp_K, 1.0)))
        lambda_factor = (max(lam, 1.0e-12) / max(float(fp.hcci_reference_lambda_by_vol[cyl]), 1.0e-12)) ** float(fp.hcci_lambda_slowdown_exponent_by_vol[cyl])
        residual_fraction = max(min(burned_mass / max(mass, 1.0e-18), 1.0), 0.0)
        residual_factor = 1.0 + (float(fp.hcci_residual_slowdown_factor_by_vol[cyl]) - 1.0) * residual_fraction
        tau_s = max(float(fp.hcci_tau_A_by_vol_s[cyl]) * pressure_factor * temp_factor * lambda_factor * residual_factor, 1.0e-9)
        tau_s = min(tau_s, float(fp.hcci_max_ignition_delay_by_vol_s[cyl]))
        fp.runtime_hcci_tau_by_vol_s[cyl] = tau_s
        fp.runtime_hcci_integral_by_vol[cyl] += dt_s / max(tau_s, 1.0e-12)
        if fp.runtime_hcci_integral_by_vol[cyl] >= 1.0:
            duration_s = _time_mode_duration_s(bundle, cyl)
            if duration_s > 0.0:
                fp.runtime_soc_active_by_vol[cyl] = 1
                fp.runtime_soc_time_by_vol_s[cyl] = float(t_s)
                fp.runtime_soc_end_time_by_vol_s[cyl] = float(t_s + duration_s)
                fp.runtime_soc_energy_by_vol_J[cyl] = float(q_total_J)
                fp.runtime_hcci_integral_by_vol[cyl] = 0.0
                if cyl == int(bundle.cylinder_indices[0]):
                    fp.runtime_soc_active = True
                    fp.runtime_soc_time_s = float(t_s)
                    fp.runtime_soc_end_time_s = float(t_s + duration_s)
                    fp.runtime_soc_energy_J = float(q_total_J)


def replay_free_piston_time_combustion_series(bundle, t: np.ndarray, y: np.ndarray, latched_energy_hist: np.ndarray | None = None, cylinder_idx: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = int(t.shape[0]) if t.ndim == 1 else 0
    soc_time_hist = np.zeros(n, dtype=np.float64)
    soc_energy_hist = np.zeros(n, dtype=np.float64)
    active_hist = np.zeros(n, dtype=np.float64)
    if not free_piston_uses_time_vibe(bundle):
        return soc_time_hist, soc_energy_hist, active_hist

    fp = bundle.free_piston
    cyl_idx = int(cylinder_idx) if cylinder_idx is not None else int(bundle.cylinder_indices[0])
    comb_row = _comb_row_for_cylinder(bundle, cyl_idx)
    if comb_row is None:
        return soc_time_hist, soc_energy_hist, active_hist
    start_mode = _comb_start_mode(bundle, cyl_idx)
    if start_mode == int(CombStartMode.AUTOIGNITION):
        return soc_time_hist, soc_energy_hist, active_hist
    start_value = float(comb_row[int(CombCol.START_DEG)])
    duration_s = float(comb_row[int(CombCol.DURATION_DEG)])
    armed = False
    initialized = False
    active = False
    soc_time_s = 0.0
    soc_end_time_s = 0.0
    soc_energy_J = 0.0

    for k in range(n):
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y[:, k], cyl_idx)
        if not initialized:
            if start_mode == int(CombStartMode.HIGN_POSITION):
                distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
                armed = bool(distance_from_tdc_m > start_value)
            else:
                theta_window_deg = _free_piston_theta_window_deg(bundle, float(t[k]), x_m, v_m_per_s, cyl_idx)
                armed = bool(theta_window_deg < start_value)
            initialized = True
        if active and float(t[k]) >= soc_end_time_s - 1.0e-15:
            active = False
        if start_mode == int(CombStartMode.HIGN_POSITION):
            distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
            if (not armed) and distance_from_tdc_m > start_value:
                armed = True
            trigger_reached = armed and free_piston_is_compression_stroke(v_m_per_s, x_m, fp.x_min_m, fp.x_max_m) and distance_from_tdc_m <= start_value
        else:
            theta_window_deg = _free_piston_theta_window_deg(bundle, float(t[k]), x_m, v_m_per_s, cyl_idx)
            if (not armed) and theta_window_deg < start_value:
                armed = True
            trigger_reached = armed and theta_window_deg >= start_value
        if latched_energy_hist is not None:
            q_total_J = float(latched_energy_hist[k])
        else:
            q_total_J = float(comb_row[int(CombCol.FUEL_MASS_PER_CYCLE)] * comb_row[int(CombCol.LHV)])
        if (not active) and trigger_reached and q_total_J > 0.0 and duration_s > 0.0:
            active = True
            soc_time_s = float(t[k])
            soc_end_time_s = float(t[k] + duration_s)
            soc_energy_J = q_total_J
            armed = False
        if active:
            soc_time_hist[k] = soc_time_s
            soc_energy_hist[k] = soc_energy_J
            active_hist[k] = 1.0
    return soc_time_hist, soc_energy_hist, active_hist


def _cylinder_slot_area_sum_m2(bundle, x_m: float, cylinder_idx: int | None = None) -> float:
    fp = bundle.free_piston
    if fp is None:
        return 0.0
    piston_x_m = cylinder_distance_from_tdc(float(x_m), fp.x_min_m, fp.x_max_m)
    total_area_m2 = 0.0
    cyl_filter = None if cylinder_idx is None else int(cylinder_idx)
    for idx in np.asarray(fp.combustion_cylinder_slot_conn_indices, dtype=np.int64):
        conn_row = bundle.conn_matrix[int(idx)]
        if cyl_filter is not None:
            left = int(conn_row[ConnCol.FROM_VOL])
            right = int(conn_row[ConnCol.TO_VOL])
            if left != cyl_filter and right != cyl_filter:
                continue
        geom_area, _cd_f, _cd_r = connection_area_and_coefficients(
            conn_row,
            int(conn_row[ConnCol.TYPE]),
            0.0,
            0.0,
            float(bundle.cycle_deg),
            piston_x_m,
            bundle.lift_table,
            bundle.alpha_table,
            bundle.cd_table,
            0.0,
            0.0,
        )
        total_area_m2 += float(geom_area)
    return float(total_area_m2)


def compute_lambda_energy_from_cylinder_mass(cylinder_unburned_mass_kg: float, bundle) -> tuple[float, float]:
    fp = bundle.free_piston
    if fp is None:
        return 0.0, 0.0
    m_air_ref_kg = max(float(cylinder_unburned_mass_kg), 0.0)
    denom = max(float(fp.combustion_lambda_target) * float(fp.combustion_afr_stoich_kg_air_per_kg_fuel), 1.0e-18)
    fuel_mass_kg = m_air_ref_kg / denom
    energy_J = float(fp.combustion_efficiency_0to1) * fuel_mass_kg * float(fp.combustion_lhv_J_per_kg)
    return float(fuel_mass_kg), float(energy_J)


def bootstrap_free_piston_combustion_latch(bundle) -> None:
    _bootstrap_time_combustion_state(bundle)
    fp = bundle.free_piston
    _ensure_runtime_arrays(bundle)
    if fp is not None:
        fp.runtime_injector_active = False
        fp.runtime_injector_time_s = 0.0
        fp.runtime_injector_end_time_s = 0.0
        fp.runtime_injector_target_fuel_mass_kg = 0.0
        fp.runtime_injector_injected_mass_kg = 0.0
        fp.runtime_injector_rate_kg_per_s = 0.0
        fp.runtime_slotclose_charge_active = False
        fp.runtime_slotclose_charge_time_s = 0.0
        fp.runtime_slotclose_charge_end_time_s = 0.0
        fp.runtime_slotclose_charge_target_fuel_mass_kg = 0.0
        fp.runtime_slotclose_charge_rate_kg_per_s = 0.0
    if not (free_piston_uses_slot_closure_lambda(bundle) or free_piston_uses_vapor_injector(bundle)):
        return
    fp = bundle.free_piston
    y0 = bundle.y_init
    for cyl_idx in getattr(bundle, 'cylinder_indices', []):
        cyl = int(cyl_idx)
        if _comb_idx_for_cylinder(bundle, cyl) < 0:
            continue
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y0, cyl)
        area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m, cyl)
        fp.runtime_last_slot_area_by_vol_m2[cyl] = float(area_sum_m2)
        if cyl == int(bundle.cylinder_indices[0]):
            fp.runtime_last_slot_area_sum_m2 = float(area_sum_m2)
        if area_sum_m2 > float(fp.combustion_slot_open_threshold_m2):
            fp.runtime_slots_were_open_by_vol[cyl] = 1
            fp.runtime_latch_valid_by_vol[cyl] = 0
            if cyl < int(getattr(fp.runtime_hcci_integral_by_vol, 'shape', (0,))[0]):
                fp.runtime_hcci_integral_by_vol[cyl] = 0.0
            if cyl == int(bundle.cylinder_indices[0]):
                fp.runtime_slots_were_open = True
                fp.runtime_latch_valid = False
            continue
        if not (v_m_per_s < -float(fp.combustion_compression_velocity_threshold_m_per_s) and area_sum_m2 <= float(fp.combustion_slot_closed_threshold_m2)):
            continue
        air_idx = int(bundle.state_layout.air_mass_index(cyl))
        cylinder_air_mass_kg = float(y0[air_idx])
        fuel_mass_kg, energy_J = compute_lambda_energy_from_cylinder_mass(cylinder_air_mass_kg, bundle)
        fp.runtime_latched_cylinder_mass_by_vol_kg[cyl] = cylinder_air_mass_kg
        fp.runtime_latched_fuel_mass_by_vol_kg[cyl] = fuel_mass_kg
        fp.runtime_latched_energy_by_vol_J[cyl] = energy_J
        fp.runtime_latch_valid_by_vol[cyl] = 1
        fp.runtime_slots_were_open_by_vol[cyl] = 0
        if cyl < int(getattr(fp.runtime_hcci_integral_by_vol, 'shape', (0,))[0]):
            fp.runtime_hcci_integral_by_vol[cyl] = 0.0
        if cyl == int(bundle.cylinder_indices[0]):
            fp.runtime_latched_cylinder_mass_kg = cylinder_air_mass_kg
            fp.runtime_latched_fuel_mass_kg = fuel_mass_kg
            fp.runtime_latched_energy_J = energy_J
            fp.runtime_latch_valid = True
            fp.runtime_slots_were_open = False
        if free_piston_uses_slot_closure_lambda(bundle):
            duration_s = float(getattr(bundle.simulation, 'dt_s', 0.0))
            _arm_slotclose_charge(fp, 0.0, fuel_mass_kg, duration_s)
            fp.runtime_slotclose_charge_active_by_vol[cyl] = 1 if fuel_mass_kg > 0.0 and duration_s > 0.0 else 0
            fp.runtime_slotclose_charge_time_by_vol_s[cyl] = 0.0
            fp.runtime_slotclose_charge_end_time_by_vol_s[cyl] = duration_s
            fp.runtime_slotclose_charge_target_fuel_by_vol_kg[cyl] = fuel_mass_kg
            fp.runtime_slotclose_charge_rate_by_vol_kg_per_s[cyl] = fuel_mass_kg / duration_s if duration_s > 0.0 else 0.0
        if free_piston_uses_vapor_injector(bundle):
            _arm_vapor_injector(fp, 0.0, fuel_mass_kg)


def update_free_piston_combustion_latch_state(bundle, t_s: float, y_state: np.ndarray) -> None:
    _update_time_combustion_state(bundle, t_s, y_state)
    fp = bundle.free_piston
    _ensure_runtime_arrays(bundle)
    if fp is not None:
        _update_vapor_injector_state(fp, t_s)
        _update_slotclose_charge_state(fp, t_s)
        for cyl_idx in getattr(bundle, 'cylinder_indices', []):
            cyl = int(cyl_idx)
            if bool(fp.runtime_slotclose_charge_active_by_vol[cyl]) and float(t_s) >= float(fp.runtime_slotclose_charge_end_time_by_vol_s[cyl]) - 1.0e-15:
                fp.runtime_slotclose_charge_active_by_vol[cyl] = 0
    if not (free_piston_uses_slot_closure_lambda(bundle) or free_piston_uses_vapor_injector(bundle)):
        return
    fp = bundle.free_piston
    for cyl_idx in getattr(bundle, 'cylinder_indices', []):
        cyl = int(cyl_idx)
        if _comb_idx_for_cylinder(bundle, cyl) < 0:
            continue
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y_state, cyl)
        area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m, cyl)
        fp.runtime_last_slot_area_by_vol_m2[cyl] = float(area_sum_m2)
        if cyl == int(bundle.cylinder_indices[0]):
            fp.runtime_last_slot_area_sum_m2 = float(area_sum_m2)

        if area_sum_m2 > float(fp.combustion_slot_open_threshold_m2):
            fp.runtime_slots_were_open_by_vol[cyl] = 1
            fp.runtime_latch_valid_by_vol[cyl] = 0
            if cyl == int(bundle.cylinder_indices[0]):
                fp.runtime_slots_were_open = True
                fp.runtime_latch_valid = False
            continue

        if not (
            bool(fp.runtime_slots_were_open_by_vol[cyl])
            and area_sum_m2 <= float(fp.combustion_slot_closed_threshold_m2)
            and v_m_per_s < -float(fp.combustion_compression_velocity_threshold_m_per_s)
        ):
            continue

        air_idx = int(bundle.state_layout.air_mass_index(cyl))
        cylinder_air_mass_kg = float(y_state[air_idx])
        fuel_mass_kg, energy_J = compute_lambda_energy_from_cylinder_mass(cylinder_air_mass_kg, bundle)
        fp.runtime_latched_cylinder_mass_by_vol_kg[cyl] = cylinder_air_mass_kg
        fp.runtime_latched_fuel_mass_by_vol_kg[cyl] = fuel_mass_kg
        fp.runtime_latched_energy_by_vol_J[cyl] = energy_J
        fp.runtime_latch_valid_by_vol[cyl] = 1
        fp.runtime_slots_were_open_by_vol[cyl] = 0
        if cyl == int(bundle.cylinder_indices[0]):
            fp.runtime_latched_cylinder_mass_kg = cylinder_air_mass_kg
            fp.runtime_latched_fuel_mass_kg = fuel_mass_kg
            fp.runtime_latched_energy_J = energy_J
            fp.runtime_latch_valid = True
            fp.runtime_slots_were_open = False
        if free_piston_uses_slot_closure_lambda(bundle):
            duration_s = float(getattr(bundle.simulation, 'dt_s', 0.0))
            _arm_slotclose_charge(fp, t_s, fuel_mass_kg, duration_s)
            fp.runtime_slotclose_charge_active_by_vol[cyl] = 1 if fuel_mass_kg > 0.0 and duration_s > 0.0 else 0
            fp.runtime_slotclose_charge_time_by_vol_s[cyl] = float(t_s)
            fp.runtime_slotclose_charge_end_time_by_vol_s[cyl] = float(t_s + duration_s)
            fp.runtime_slotclose_charge_target_fuel_by_vol_kg[cyl] = fuel_mass_kg
            fp.runtime_slotclose_charge_rate_by_vol_kg_per_s[cyl] = fuel_mass_kg / duration_s if duration_s > 0.0 else 0.0
        if free_piston_uses_vapor_injector(bundle):
            _arm_vapor_injector(fp, t_s, fuel_mass_kg)
    _update_hcci_diesel_autoignition_state(bundle, t_s, y_state)


def replay_free_piston_combustion_latch_series(bundle, y: np.ndarray, cylinder_idx: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = int(y.shape[1])
    mass_hist = np.zeros(n, dtype=np.float64)
    fuel_hist = np.zeros(n, dtype=np.float64)
    energy_hist = np.zeros(n, dtype=np.float64)
    area_hist = np.zeros(n, dtype=np.float64)
    if not free_piston_uses_slot_closure_lambda(bundle):
        return mass_hist, fuel_hist, energy_hist, area_hist

    fp = bundle.free_piston
    slots_were_open = False
    latch_valid = False
    latched_mass = 0.0
    latched_fuel = 0.0
    latched_energy = 0.0
    cyl_idx = int(cylinder_idx) if cylinder_idx is not None else int(bundle.cylinder_indices[0])
    air_idx = int(bundle.state_layout.air_mass_index(cyl_idx))
    for k in range(n):
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y[:, k], cyl_idx)
        area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m, cyl_idx)
        area_hist[k] = area_sum_m2
        if area_sum_m2 > float(fp.combustion_slot_open_threshold_m2):
            slots_were_open = True
            latch_valid = False
        elif (
            slots_were_open
            and area_sum_m2 <= float(fp.combustion_slot_closed_threshold_m2)
            and v_m_per_s < -float(fp.combustion_compression_velocity_threshold_m_per_s)
        ):
            latched_mass = float(y[air_idx, k])
            latched_fuel, latched_energy = compute_lambda_energy_from_cylinder_mass(latched_mass, bundle)
            latch_valid = True
            slots_were_open = False
        elif (
            k == 0 and area_sum_m2 <= float(fp.combustion_slot_closed_threshold_m2)
            and v_m_per_s < -float(fp.combustion_compression_velocity_threshold_m_per_s)
        ):
            latched_mass = float(y[air_idx, k])
            latched_fuel, latched_energy = compute_lambda_energy_from_cylinder_mass(latched_mass, bundle)
            latch_valid = True
        if latch_valid:
            mass_hist[k] = latched_mass
            fuel_hist[k] = latched_fuel
            energy_hist[k] = latched_energy
    return mass_hist, fuel_hist, energy_hist, area_hist
