from __future__ import annotations

import numpy as np

from thermo0d.config.constants import VolumeCol, VolumeType, WallTemperatureCol, WallTemperatureZone
from thermo0d.model.free_piston.geometry import (
    cylinder_dvdt_from_velocity,
    cylinder_volume_from_position,
    free_piston_equivalent_linear_kinematics,
    free_piston_local_cycle_angle_deg,
    free_piston_local_cycle_angle_rate_deg_s,
)
from thermo0d.physics.heat_transfer import wall_heat_rate_and_coeff_from_row_numba
from thermo0d.physics.kinematics import cylinder_kinematic_state_from_time, global_theta_and_rate_from_time
from thermo0d.physics.quellen_props import properties_from_mass_energy_components_quellen
from thermo0d.physics.thermo import safe_pressure_from_ideal_gas, safe_temperature_from_state


WT_AREA = int(WallTemperatureCol.AREA)
WT_COND = int(WallTemperatureCol.CONDUCTANCE)
WT_COOL_T = int(WallTemperatureCol.COOLANT_TEMP)
WT_RELAX = int(WallTemperatureCol.RELAXATION)
WT_ENABLED = int(WallTemperatureCol.ENABLED)
WT_ZONE_COUNT = len(WallTemperatureZone)
V_TYPE = int(VolumeCol.TYPE)
V_KIN_ROW = int(VolumeCol.KIN_ROW)
V_WALL = int(VolumeCol.WALL_ROW)


def has_wall_temperature_model(bundle) -> bool:
    states = getattr(bundle, "wall_temperature_state_index_by_vol", None)
    averages = getattr(bundle, "wall_temperature_average_state_index_by_vol", None)
    params = getattr(bundle, "wall_temperature_params_by_vol", None)
    return states is not None and averages is not None and params is not None and int(states.size) > 0


def wall_temperature_cycle_period_s(bundle) -> float:
    cycle_deg = max(float(getattr(bundle, "cycle_deg", 360.0) or 360.0), 1.0e-12)
    return float(getattr(bundle, "cycle_period_s", 0.0) or 0.0) * 360.0 / cycle_deg


def apply_wall_temperature_cycle_update(bundle, t: np.ndarray, y: np.ndarray, first: int, last: int) -> int:
    if not has_wall_temperature_model(bundle):
        return 0
    first = max(int(first), 0)
    last = min(int(last), int(np.asarray(t).shape[0]) - 1)
    if last - first < 1:
        return 0

    t_seg = np.asarray(t[first:last + 1], dtype=np.float64)
    duration_s = float(t_seg[-1] - t_seg[0])
    if duration_s <= 1.0e-15:
        return 0

    wall_state_by_vol = bundle.wall_temperature_state_index_by_vol
    wall_avg_by_vol = bundle.wall_temperature_average_state_index_by_vol
    wall_params = bundle.wall_temperature_params_by_vol
    updated = 0
    y_target = y[:, last]
    for cyl_idx in getattr(bundle, "cylinder_indices", []) or []:
        i = int(cyl_idx)
        if i >= int(wall_state_by_vol.shape[0]) or i >= int(wall_avg_by_vol.shape[0]):
            continue
        alpha_integral = 0.0
        talpha_integral = 0.0
        last_alpha = 0.0
        last_temp = 0.0
        prev_t = float(t_seg[0])
        prev_alpha, prev_temp = _sample_cylinder_alpha_temp(bundle, i, prev_t, y[:, first])
        for sample_idx in range(1, int(t_seg.size)):
            cur_t = float(t_seg[sample_idx])
            cur_alpha, cur_temp = _sample_cylinder_alpha_temp(bundle, i, cur_t, y[:, first + sample_idx])
            dt = cur_t - prev_t
            if dt > 0.0:
                alpha_integral += 0.5 * (prev_alpha + cur_alpha) * dt
                talpha_integral += 0.5 * (prev_alpha * prev_temp + cur_alpha * cur_temp) * dt
            prev_t = cur_t
            prev_alpha = cur_alpha
            prev_temp = cur_temp
            last_alpha = cur_alpha
            last_temp = cur_temp
        alpha_avg = float(alpha_integral / duration_s)
        talpha_avg = float(talpha_integral / duration_s)

        alpha_idx = int(wall_avg_by_vol[i, 0])
        talpha_idx = int(wall_avg_by_vol[i, 1])
        if alpha_idx >= 0:
            y_target[alpha_idx] = alpha_avg
        if talpha_idx >= 0:
            y_target[talpha_idx] = talpha_avg

        alpha_for_eq = alpha_avg
        talpha_for_eq = talpha_avg
        if alpha_for_eq <= 1.0e-12:
            alpha_for_eq = float(last_alpha)
            talpha_for_eq = alpha_for_eq * float(last_temp)
        for zone in range(WT_ZONE_COUNT):
            wall_state_idx = int(wall_state_by_vol[i, zone])
            if wall_state_idx < 0 or float(wall_params[i, zone, WT_ENABLED]) <= 0.5:
                continue
            conductance = float(wall_params[i, zone, WT_COND])
            if conductance <= 1.0e-18 or alpha_for_eq + conductance <= 1.0e-18:
                continue
            coolant_temp = float(wall_params[i, zone, WT_COOL_T])
            relaxation = max(0.0, min(float(wall_params[i, zone, WT_RELAX]), 1.0))
            target = (talpha_for_eq + conductance * coolant_temp) / (alpha_for_eq + conductance)
            current = float(y_target[wall_state_idx])
            y_target[wall_state_idx] = current + relaxation * (target - current)
            updated += 1
    return updated


def _sample_cylinder_alpha_temp(bundle, cyl_idx: int, t_s: float, state: np.ndarray) -> tuple[float, float]:
    vol_row = bundle.vol_matrix[int(cyl_idx)]
    wall_idx = int(vol_row[V_WALL])
    if int(vol_row[V_TYPE]) != int(VolumeType.CYLINDER) or wall_idx < 0 or wall_idx >= int(bundle.wall_matrix.shape[0]):
        return 0.0, 0.0

    volume_m3, dvdt_m3_s, theta_local_deg, dtheta_local_dt_deg_s, cycle_deg = _cylinder_kinematics(bundle, cyl_idx, t_s, state)
    _ = (dvdt_m3_s, dtheta_local_dt_deg_s)
    mass_kg, temp_K, pressure_Pa = _cylinder_thermo(bundle, cyl_idx, state, volume_m3)
    wall_bore_by_vol = getattr(bundle, "wall_bore_by_vol", None)
    wall_ups_by_vol = getattr(bundle, "wall_ups_by_vol", None)
    bore_m = float(wall_bore_by_vol[cyl_idx]) if wall_bore_by_vol is not None and cyl_idx < int(wall_bore_by_vol.shape[0]) else 0.1
    mean_piston_speed_m_s = float(wall_ups_by_vol[cyl_idx]) if wall_ups_by_vol is not None and cyl_idx < int(wall_ups_by_vol.shape[0]) else 0.0
    _q, htc, _w, _dp = wall_heat_rate_and_coeff_from_row_numba(
        bundle.wall_matrix[wall_idx],
        bore_m,
        pressure_Pa,
        temp_K,
        mean_piston_speed_m_s,
        volume_m3,
        theta_local_deg,
        cycle_deg,
        mass_kg,
        0.0,
    )
    return float(htc), float(temp_K)


def _cylinder_kinematics(bundle, cyl_idx: int, t_s: float, state: np.ndarray) -> tuple[float, float, float, float, float]:
    if str(getattr(bundle, "architecture", "classic") or "classic") == "free_piston":
        fp = bundle.free_piston
        dof = -1
        if getattr(fp, "volume_mechanical_dof", None) is not None and cyl_idx < int(fp.volume_mechanical_dof.shape[0]):
            dof = int(fp.volume_mechanical_dof[cyl_idx])
        if dof >= 0 and getattr(fp, "mechanical_x_state_indices", None) is not None and dof < int(fp.mechanical_x_state_indices.shape[0]):
            q_idx = int(fp.mechanical_x_state_indices[dof])
            qv_idx = int(fp.mechanical_v_state_indices[dof])
        else:
            q_idx = int(fp.x_state_index)
            qv_idx = int(fp.v_state_index)
        sign = 1.0
        if getattr(fp, "volume_mechanical_sign", None) is not None and cyl_idx < int(fp.volume_mechanical_sign.shape[0]):
            sign = float(fp.volume_mechanical_sign[cyl_idx])
        x_m, v_m_s = free_piston_equivalent_linear_kinematics(
            float(state[q_idx]),
            float(state[qv_idx]),
            sign,
            kinematics_type=str(getattr(fp, "kinematics_type", "linear") or "linear"),
            x_min_m=float(fp.x_min_m),
            x_max_m=float(fp.x_max_m),
            angle_min_rad=float(getattr(fp, "rotary_angle_min_rad", 0.0) or 0.0),
            angle_max_rad=float(getattr(fp, "rotary_angle_max_rad", 0.0) or 0.0),
            effective_radius_m=float(getattr(fp, "rotary_effective_radius_m", 1.0) or 1.0),
        )
        volume = cylinder_volume_from_position(float(fp.clearance_volume_m3), float(fp.piston_area_m2), x_m, float(fp.x_min_m), float(fp.x_max_m))
        dvdt = cylinder_dvdt_from_velocity(float(fp.piston_area_m2), v_m_s)
        cycle_deg = float(getattr(bundle, "cycle_deg", 360.0) or 360.0)
        theta = free_piston_local_cycle_angle_deg(x_m, v_m_s, float(fp.x_min_m), float(fp.x_max_m), cycle_deg)
        dtheta_dt = free_piston_local_cycle_angle_rate_deg_s(v_m_s, float(fp.x_min_m), float(fp.x_max_m), cycle_deg)
        return volume, dvdt, theta, dtheta_dt, cycle_deg

    kin_row = bundle.kin_matrix[int(bundle.vol_matrix[cyl_idx, V_KIN_ROW])]
    volume, dvdt, theta, _piston_pos, dtheta_dt, cycle_deg = cylinder_kinematic_state_from_time(kin_row, t_s)
    _theta_global, _dtheta_global, _cycle_global = global_theta_and_rate_from_time(t_s, kin_row)
    return float(volume), float(dvdt), float(theta), float(dtheta_dt), float(cycle_deg)


def _cylinder_thermo(bundle, cyl_idx: int, state: np.ndarray, volume_m3: float) -> tuple[float, float, float]:
    layout = bundle.state_layout
    mass = float(layout.gas_mass_from_state(state, cyl_idx))
    energy = float(state[int(layout.energy_index(cyl_idx))])
    cv_default = float(bundle.gas_props[1])
    gas_constant_default = float(bundle.gas_props[2])
    use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5
    if use_promo_thermo:
        air_mass = float(layout.air_mass_from_state(state, cyl_idx))
        burned_mass = float(layout.burned_mass_from_state(state, cyl_idx))
        fuel_vapor_mass = float(layout.fuel_vapor_mass_from_state(state, cyl_idx))
        temp, _cp, cv_i, gas_constant_i, _kappa = properties_from_mass_energy_components_quellen(
            mass,
            energy,
            air_mass,
            fuel_vapor_mass,
            burned_mass,
            cv_default,
        )
        return mass, float(temp), float(safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume_m3))
    temp = safe_temperature_from_state(mass, energy, cv_default)
    press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume_m3)
    return mass, float(temp), float(press)


def build_fixed_step_wall_temperature_callback(bundle, t_eval: np.ndarray):
    if not has_wall_temperature_model(bundle):
        return None
    architecture = str(getattr(bundle, "architecture", "classic") or "classic")
    if architecture == "free_piston":
        return _build_free_piston_wall_temperature_callback(bundle)
    return _build_time_based_wall_temperature_callback(bundle, t_eval)


def _build_time_based_wall_temperature_callback(bundle, t_eval: np.ndarray):
    period_s = wall_temperature_cycle_period_s(bundle)
    if period_s <= 1.0e-15 or t_eval.size <= 1:
        return None
    wall_cycle_idx = np.floor(np.asarray(t_eval, dtype=np.float64) / period_s - 1.0e-12).astype(np.int64)
    wall_cycle_idx[wall_cycle_idx < 0] = 0
    transitions = np.flatnonzero(np.diff(wall_cycle_idx) != 0)
    starts = np.concatenate(([0], transitions + 1))
    stops = np.concatenate((transitions + 1, [t_eval.size - 1]))
    next_cycle_ptr = 0

    def step_callback(step_idx: int, t_hist: np.ndarray, y_hist: np.ndarray) -> None:
        nonlocal next_cycle_ptr
        while next_cycle_ptr < int(stops.size) and int(step_idx) >= int(stops[next_cycle_ptr]):
            first = int(starts[next_cycle_ptr])
            last = int(stops[next_cycle_ptr])
            if float(t_hist[last] - t_hist[first]) >= 0.999 * period_s:
                apply_wall_temperature_cycle_update(bundle, t_hist, y_hist, first, last)
            next_cycle_ptr += 1

    return step_callback


def _build_free_piston_wall_temperature_callback(bundle):
    fp = getattr(bundle, "free_piston", None)
    if fp is None:
        return None
    x_idx = int(fp.x_state_index)
    v_idx = int(fp.v_state_index)
    last_update_sample = -1
    last_sign = 0
    turns: list[tuple[int, float]] = []

    def step_callback(step_idx: int, t_hist: np.ndarray, y_hist: np.ndarray) -> None:
        nonlocal last_update_sample, last_sign, turns
        idx = int(step_idx)
        if idx < 4 or x_idx >= y_hist.shape[0] or v_idx >= y_hist.shape[0]:
            return
        v_now = float(y_hist[v_idx, idx])
        dx_now = float(y_hist[x_idx, idx] - y_hist[x_idx, idx - 1])
        eps = max(1.0e-10, 1.0e-6 * max(abs(v_now), abs(float(y_hist[v_idx, idx - 1]))))
        sign = 0
        if abs(v_now) > eps:
            sign = 1 if v_now > 0.0 else -1
        elif abs(dx_now) > eps:
            sign = 1 if dx_now > 0.0 else -1
        if sign == 0:
            return
        if last_sign == 0:
            last_sign = sign
            return
        if sign == last_sign:
            return
        turn_idx = max(0, idx - 1)
        turn_x = float(y_hist[x_idx, turn_idx])
        if not turns or turn_idx - turns[-1][0] > 1:
            turns.append((turn_idx, turn_x))
            if len(turns) > 4:
                turns = turns[-4:]
        last_sign = sign
        if len(turns) < 3:
            return
        a_idx, a_x = turns[-3]
        b_idx, b_x = turns[-2]
        c_idx, c_x = turns[-1]
        if c_idx <= last_update_sample:
            return
        if not (a_x > b_x and c_x > b_x):
            return
        apply_wall_temperature_cycle_update(bundle, t_hist, y_hist, int(a_idx), idx)
        last_update_sample = int(c_idx)

    return step_callback
