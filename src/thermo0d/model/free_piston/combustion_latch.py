from __future__ import annotations

import numpy as np

from thermo0d.config.constants import CombCol, CombDurationMode, CombStartMode, ConnCol, ConnectionType, FeatureCol
from thermo0d.model.free_piston.geometry import cylinder_distance_from_tdc, free_piston_is_compression_stroke, free_piston_local_cycle_angle_deg
from thermo0d.physics.kinematics import reference_theta_and_zero, wrap_angle_deg
from thermo0d.physics.openings import connection_area_and_coefficients
from thermo0d.physics.composition import unburned_mass_kg


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


def _comb_duration_mode(bundle) -> int:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None or int(getattr(fp, 'combustion_comb_idx', -1)) < 0:
        return int(CombDurationMode.ANGLE)
    comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    if comb_row.shape[0] <= int(CombCol.DURATION_MODE):
        return int(CombDurationMode.ANGLE)
    return int(comb_row[int(CombCol.DURATION_MODE)])


def _comb_start_mode(bundle) -> int:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None or int(getattr(fp, 'combustion_comb_idx', -1)) < 0:
        return int(CombStartMode.ANGLE)
    comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    if comb_row.shape[0] <= int(CombCol.START_MODE):
        return int(CombStartMode.ANGLE)
    mode = int(comb_row[int(CombCol.START_MODE)])
    if mode in (int(CombStartMode.COMPRESSION_HUB), int(CombStartMode.HIGN_POSITION)):
        return mode
    return int(CombStartMode.ANGLE)


def free_piston_uses_time_vibe(bundle) -> bool:
    if not free_piston_combustion_enabled(bundle):
        return False
    fp = getattr(bundle, 'free_piston', None)
    return fp is not None and int(getattr(fp, 'combustion_comb_idx', -1)) >= 0 and _comb_duration_mode(bundle) == int(CombDurationMode.TIME)


def _free_piston_theta_window_deg(bundle, t_s: float, x_m: float, v_m_per_s: float) -> float:
    fp = bundle.free_piston
    comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    cycle_deg = float(bundle.cycle_deg)
    dtheta_dt_global = float(cycle_deg / bundle.cycle_period_s) if float(bundle.cycle_period_s) > 1.0e-18 else 0.0
    theta_global_deg = (float(t_s) * dtheta_dt_global) % cycle_deg if cycle_deg > 1.0e-18 else 0.0
    theta_local_deg = free_piston_local_cycle_angle_deg(float(x_m), float(v_m_per_s), fp.x_min_m, fp.x_max_m, cycle_deg)
    theta_ref_deg, ref_zero_deg = reference_theta_and_zero(theta_local_deg, theta_global_deg, cycle_deg, int(comb_row[int(CombCol.REF_TYPE)]))
    return float(wrap_angle_deg(theta_ref_deg - ref_zero_deg, cycle_deg))


def _time_mode_duration_s(bundle) -> float:
    fp = bundle.free_piston
    if fp is None or int(getattr(fp, 'combustion_comb_idx', -1)) < 0:
        return 0.0
    comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    return float(comb_row[int(CombCol.DURATION_DEG)])


def _current_combustion_energy_J(bundle) -> float:
    fp = bundle.free_piston
    if fp is None or int(getattr(fp, 'combustion_comb_idx', -1)) < 0:
        return 0.0
    if free_piston_uses_slot_closure_lambda(bundle):
        return float(fp.runtime_latched_energy_J) if bool(fp.runtime_latch_valid) else 0.0
    comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    return float(comb_row[int(CombCol.FUEL_MASS_PER_CYCLE)] * comb_row[int(CombCol.LHV)])


def _bootstrap_time_combustion_state(bundle) -> None:
    if not free_piston_uses_time_vibe(bundle):
        return
    fp = bundle.free_piston
    y0 = bundle.y_init
    x_m = float(y0[int(fp.x_state_index)])
    v_m_per_s = float(y0[int(fp.v_state_index)])
    comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    start_mode = _comb_start_mode(bundle)
    start_value = float(comb_row[int(CombCol.START_DEG)])
    fp.runtime_time_combustion_initialized = True
    if start_mode == int(CombStartMode.HIGN_POSITION):
        distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
        fp.runtime_time_combustion_armed = bool(distance_from_tdc_m > start_value)
    else:
        theta_window_deg = _free_piston_theta_window_deg(bundle, 0.0, x_m, v_m_per_s)
        fp.runtime_time_combustion_armed = bool(theta_window_deg < start_value)
    fp.runtime_soc_active = False
    fp.runtime_soc_time_s = 0.0
    fp.runtime_soc_end_time_s = 0.0
    fp.runtime_soc_energy_J = 0.0


def _update_time_combustion_state(bundle, t_s: float, y_state: np.ndarray) -> None:
    if not free_piston_uses_time_vibe(bundle):
        return
    fp = bundle.free_piston
    x_m = float(y_state[int(fp.x_state_index)])
    v_m_per_s = float(y_state[int(fp.v_state_index)])
    comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    start_mode = _comb_start_mode(bundle)
    start_value = float(comb_row[int(CombCol.START_DEG)])
    duration_s = _time_mode_duration_s(bundle)
    if not bool(fp.runtime_time_combustion_initialized):
        fp.runtime_time_combustion_initialized = True
        if start_mode == int(CombStartMode.HIGN_POSITION):
            distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
            fp.runtime_time_combustion_armed = bool(distance_from_tdc_m > start_value)
        else:
            theta_window_deg = _free_piston_theta_window_deg(bundle, t_s, x_m, v_m_per_s)
            fp.runtime_time_combustion_armed = bool(theta_window_deg < start_value)
    if bool(fp.runtime_soc_active) and float(t_s) >= float(fp.runtime_soc_end_time_s) - 1.0e-15:
        fp.runtime_soc_active = False

    trigger_reached = False
    if start_mode == int(CombStartMode.HIGN_POSITION):
        distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
        if (not bool(fp.runtime_time_combustion_armed)) and distance_from_tdc_m > start_value:
            fp.runtime_time_combustion_armed = True
        trigger_reached = bool(fp.runtime_time_combustion_armed) and free_piston_is_compression_stroke(v_m_per_s, x_m, fp.x_min_m, fp.x_max_m) and distance_from_tdc_m <= start_value
    else:
        theta_window_deg = _free_piston_theta_window_deg(bundle, t_s, x_m, v_m_per_s)
        if (not bool(fp.runtime_time_combustion_armed)) and theta_window_deg < start_value:
            fp.runtime_time_combustion_armed = True
        trigger_reached = bool(fp.runtime_time_combustion_armed) and theta_window_deg >= start_value

    q_total_J = _current_combustion_energy_J(bundle)
    if (
        not bool(fp.runtime_soc_active)
        and trigger_reached
        and q_total_J > 0.0
        and duration_s > 0.0
    ):
        fp.runtime_soc_active = True
        fp.runtime_soc_time_s = float(t_s)
        fp.runtime_soc_end_time_s = float(t_s + duration_s)
        fp.runtime_soc_energy_J = float(q_total_J)
        fp.runtime_time_combustion_armed = False


def replay_free_piston_time_combustion_series(bundle, t: np.ndarray, y: np.ndarray, latched_energy_hist: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = int(t.shape[0]) if t.ndim == 1 else 0
    soc_time_hist = np.zeros(n, dtype=np.float64)
    soc_energy_hist = np.zeros(n, dtype=np.float64)
    active_hist = np.zeros(n, dtype=np.float64)
    if not free_piston_uses_time_vibe(bundle):
        return soc_time_hist, soc_energy_hist, active_hist

    fp = bundle.free_piston
    comb_row = bundle.comb_matrix[int(fp.combustion_comb_idx)]
    start_mode = _comb_start_mode(bundle)
    start_value = float(comb_row[int(CombCol.START_DEG)])
    duration_s = float(comb_row[int(CombCol.DURATION_DEG)])
    armed = False
    initialized = False
    active = False
    soc_time_s = 0.0
    soc_end_time_s = 0.0
    soc_energy_J = 0.0

    for k in range(n):
        x_m = float(y[int(fp.x_state_index), k])
        v_m_per_s = float(y[int(fp.v_state_index), k])
        if not initialized:
            if start_mode == int(CombStartMode.HIGN_POSITION):
                distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
                armed = bool(distance_from_tdc_m > start_value)
            else:
                theta_window_deg = _free_piston_theta_window_deg(bundle, float(t[k]), x_m, v_m_per_s)
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
            theta_window_deg = _free_piston_theta_window_deg(bundle, float(t[k]), x_m, v_m_per_s)
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


def _cylinder_slot_area_sum_m2(bundle, x_m: float) -> float:
    fp = bundle.free_piston
    if fp is None:
        return 0.0
    piston_x_m = cylinder_distance_from_tdc(float(x_m), fp.x_min_m, fp.x_max_m)
    total_area_m2 = 0.0
    for idx in np.asarray(fp.combustion_cylinder_slot_conn_indices, dtype=np.int64):
        conn_row = bundle.conn_matrix[int(idx)]
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
    x_m = float(y0[int(fp.x_state_index)])
    v_m_per_s = float(y0[int(fp.v_state_index)])
    area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m)
    fp.runtime_last_slot_area_sum_m2 = float(area_sum_m2)
    if area_sum_m2 > float(fp.combustion_slot_open_threshold_m2):
        fp.runtime_slots_were_open = True
        fp.runtime_latch_valid = False
        return
    if v_m_per_s < -float(fp.combustion_compression_velocity_threshold_m_per_s) and area_sum_m2 <= float(fp.combustion_slot_closed_threshold_m2):
        air_idx = int(bundle.state_layout.air_mass_index(int(bundle.cylinder_indices[0])))
        cylinder_air_mass_kg = float(y0[air_idx])
        fuel_mass_kg, energy_J = compute_lambda_energy_from_cylinder_mass(cylinder_air_mass_kg, bundle)
        fp.runtime_latched_cylinder_mass_kg = cylinder_air_mass_kg
        fp.runtime_latched_fuel_mass_kg = fuel_mass_kg
        fp.runtime_latched_energy_J = energy_J
        fp.runtime_latch_valid = True
        fp.runtime_slots_were_open = False
        if free_piston_uses_slot_closure_lambda(bundle):
            _arm_slotclose_charge(fp, 0.0, fuel_mass_kg, getattr(bundle.simulation, 'dt_s', 0.0))
        if free_piston_uses_vapor_injector(bundle):
            _arm_vapor_injector(fp, 0.0, fuel_mass_kg)


def update_free_piston_combustion_latch_state(bundle, t_s: float, y_state: np.ndarray) -> None:
    _update_time_combustion_state(bundle, t_s, y_state)
    fp = bundle.free_piston
    if fp is not None:
        _update_vapor_injector_state(fp, t_s)
        _update_slotclose_charge_state(fp, t_s)
    if not (free_piston_uses_slot_closure_lambda(bundle) or free_piston_uses_vapor_injector(bundle)):
        return
    fp = bundle.free_piston
    x_m = float(y_state[int(fp.x_state_index)])
    v_m_per_s = float(y_state[int(fp.v_state_index)])
    area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m)
    fp.runtime_last_slot_area_sum_m2 = float(area_sum_m2)

    if area_sum_m2 > float(fp.combustion_slot_open_threshold_m2):
        fp.runtime_slots_were_open = True
        fp.runtime_latch_valid = False
        return

    if (
        fp.runtime_slots_were_open
        and area_sum_m2 <= float(fp.combustion_slot_closed_threshold_m2)
        and v_m_per_s < -float(fp.combustion_compression_velocity_threshold_m_per_s)
    ):
        air_idx = int(bundle.state_layout.air_mass_index(int(bundle.cylinder_indices[0])))
        cylinder_air_mass_kg = float(y_state[air_idx])
        fuel_mass_kg, energy_J = compute_lambda_energy_from_cylinder_mass(cylinder_air_mass_kg, bundle)
        fp.runtime_latched_cylinder_mass_kg = cylinder_air_mass_kg
        fp.runtime_latched_fuel_mass_kg = fuel_mass_kg
        fp.runtime_latched_energy_J = energy_J
        fp.runtime_latch_valid = True
        fp.runtime_slots_were_open = False
        if free_piston_uses_slot_closure_lambda(bundle):
            _arm_slotclose_charge(fp, t_s, fuel_mass_kg, getattr(bundle.simulation, 'dt_s', 0.0))
        if free_piston_uses_vapor_injector(bundle):
            _arm_vapor_injector(fp, t_s, fuel_mass_kg)


def replay_free_piston_combustion_latch_series(bundle, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
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
    air_idx = int(bundle.state_layout.air_mass_index(int(bundle.cylinder_indices[0])))
    for k in range(n):
        x_m = float(y[int(fp.x_state_index), k])
        v_m_per_s = float(y[int(fp.v_state_index), k])
        area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m)
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
